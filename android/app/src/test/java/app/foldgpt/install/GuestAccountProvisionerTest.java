package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.install.RootfsTransactionTest.*;

/** Real Linux files and transactions; crash cases halt a separate JVM without finally. */
public class GuestAccountProvisionerTest {
    private static final int UID=12345,GID=23456;
    private static final String PASSWD="root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n";
    private static final String GROUP="root:x:0:\ndaemon:x:1:\n";
    private static final String SHADOW="root:!:0:0:99999:7:::\ndaemon:*:0:0:99999:7:::\n";
    private static final String GSHADOW="root:*::\ndaemon:*::\n";
    private static final GuestAccountProvisioner.Storage STORAGE=new GuestAccountProvisioner.Storage() {
        public String identity(Path path) throws IOException { return POSIX.identity(path); }
        public long linkCount(Path path) throws IOException { return POSIX.linkCount(path); }
        public void syncDirectory(Path path) throws IOException { POSIX.syncDirectory(path); }
    };
    private final List<Path> owned=new ArrayList<>();
    private Path temporary() throws IOException { Path path=Files.createTempDirectory("foldgpt-account-test-"); owned.add(path); return path; }
    @After public void cleanup() throws IOException { for(Path path:owned) removeFixture(path); }
    private static Fixture fixture() throws IOException {
        return fixture(true,true);
    }
    private static Fixture fixture(boolean shadow,boolean gshadow) throws IOException {
        List<Member> members=new ArrayList<>(List.of(new Member("./",'5',0755,""),new Member("./etc/",'5',0755,""),
            new Member("./home/",'5',0755,""),new Member("./etc/passwd",'0',0644,shadow?PASSWD:PASSWD.replace(":x:",":*:")),
            new Member("./etc/group",'0',0644,gshadow?GROUP:GROUP.replace(":x:",":*:"))));
        if(shadow) members.add(new Member("./etc/shadow",'0',0600,SHADOW));
        if(gshadow) members.add(new Member("./etc/gshadow",'0',0600,GSHADOW));
        return archive(members.toArray(new Member[0]));
    }
    @Test public void createsActualLockedAccountWithoutActivationAndPreservesSystemAccounts() throws Exception {
        Path files=temporary(); Fixture base=fixture();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=transaction.prepare(base::open).root;
            GuestIdentity result=GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID);
            assertEquals("foldgpt",result.user); assertEquals(UID+":"+GID,result.prootIds());
            assertEquals("/home/foldgpt",result.home); assertEquals("/bin/bash",result.shell);
            assertEquals(PASSWD+"foldgpt:x:12345:23456:FoldGPT:/home/foldgpt:/bin/bash\n",Files.readString(root.resolve("etc/passwd")));
            assertEquals(GROUP+"foldgpt:x:23456:\n",Files.readString(root.resolve("etc/group")));
            assertEquals(SHADOW+"foldgpt:!:0:0:99999:7:::\n",Files.readString(root.resolve("etc/shadow")));
            assertEquals(GSHADOW+"foldgpt:!::\n",Files.readString(root.resolve("etc/gshadow")));
            assertEquals("rwx------",java.nio.file.attribute.PosixFilePermissions.toString(Files.getPosixFilePermissions(root.resolve("home/foldgpt"))));
            assertEquals(RootfsTransaction.State.PREPARED,transaction.state());
            assertFalse(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS));
            String intent=Files.readString(root.resolve("etc/foldgpt-account.v1"));
            Map<String,String> identities=new HashMap<>();
            for(String database:List.of("passwd","group","shadow","gshadow","foldgpt-user","foldgpt-account.v1"))
                identities.put(database,POSIX.identity(root.resolve("etc").resolve(database)));
            assertEquals(UID,GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID).uid);
            assertEquals(intent,Files.readString(root.resolve("etc/foldgpt-account.v1")));
            for(Map.Entry<String,String> item:identities.entrySet()) assertEquals(item.getValue(),POSIX.identity(root.resolve("etc").resolve(item.getKey())));
        }
    }
    @Test public void repairsOwnJournalBoundFilesAfterUmaskFilteredPublication() throws Exception {
        Path files=temporary(); Fixture base=fixture();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=transaction.prepare(base::open).root;
            GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID);
            String passwd=Files.readString(root.resolve("etc/passwd"));
            for(String name:List.of("group","foldgpt-user"))
                Files.setPosixFilePermissions(root.resolve("etc/"+name),java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
            assertEquals(UID,GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID).uid);
            for(String name:List.of("group","foldgpt-user"))
                assertEquals("rw-r--r--",java.nio.file.attribute.PosixFilePermissions.toString(Files.getPosixFilePermissions(root.resolve("etc/"+name))));
            assertEquals(passwd,Files.readString(root.resolve("etc/passwd")));
        }
    }
    @Test public void resumesAfterEveryDurableStepAndRealProcessDeath() throws Exception {
        crashes(true);
        crashes(false);
    }
    private void crashes(boolean shadow) throws Exception {
        for(String checkpoint:List.of("intent-ready","intent-written","group-ready","group-written","gshadow-ready","gshadow-written",
                "passwd-ready","passwd-written","shadow-ready","shadow-written","home-created","selection-ready","selection-written","verified")) {
            if(!shadow && (checkpoint.startsWith("shadow") || checkpoint.startsWith("gshadow"))) continue;
            Path files=temporary(); Fixture base=fixture(shadow,shadow);
            Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-cp",System.getProperty("java.class.path"),
                GuestAccountProvisionerTest.class.getName(),files.toString(),checkpoint,shadow?"shadow":"plain").redirectErrorStream(true).start();
            if(!child.waitFor(30,TimeUnit.SECONDS)) { child.destroyForcibly(); fail("Provisioning child timed out at "+checkpoint); }
            String output=new String(child.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
            assertEquals(checkpoint+": "+output,71,child.exitValue());
            try(RootfsTransaction resumed=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=resumed.prepare(() -> { throw new IOException("A provisioned base must not be extracted again"); }).root;
                assertEquals(UID,GuestAccountProvisioner.prepare(resumed,STORAGE,UID,GID).uid);
                assertEquals(1,Files.readAllLines(root.resolve("etc/passwd")).stream().filter(line -> line.startsWith("foldgpt:")).count());
                assertEquals(1,Files.readAllLines(root.resolve("etc/group")).stream().filter(line -> line.startsWith("foldgpt:")).count());
                assertEquals(RootfsTransaction.State.PREPARED,resumed.state());
                assertFalse(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS));
                try(var children=Files.list(root.resolve("etc"))) { assertFalse(children.anyMatch(path -> path.getFileName().toString().endsWith(".next"))); }
            }
        }
    }
    public static void main(String[] args) throws Exception {
        boolean shadow=!args[2].equals("plain");
        Fixture base=fixture(shadow,shadow);
        try(RootfsTransaction transaction=RootfsTransaction.open(Path.of(args[0]),base.spec,POSIX)) {
            transaction.prepare(base::open);
            GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID,name -> { if(name.equals(args[1])) Runtime.getRuntime().halt(71); });
        }
        throw new AssertionError("Crash checkpoint was not reached");
    }
    @Test public void preservesBasesWithoutShadowAndSupportsMixedShadowSchemes() throws Exception {
        for(boolean shadow:List.of(false,true)) for(boolean gshadow:List.of(false,true)) {
            Path files=temporary(); Fixture base=fixture(shadow,gshadow);
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=transaction.prepare(base::open).root;
                GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID);
                GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID);
                assertEquals(shadow,Files.exists(root.resolve("etc/shadow")));
                assertEquals(gshadow,Files.exists(root.resolve("etc/gshadow")));
                assertTrue(Files.readString(root.resolve("etc/passwd")).endsWith("foldgpt:"+(shadow?"x":"!")+":12345:23456:FoldGPT:/home/foldgpt:/bin/bash\n"));
                assertTrue(Files.readString(root.resolve("etc/group")).endsWith("foldgpt:"+(gshadow?"x":"!")+":23456:\n"));
                if(!shadow) {
                    Files.writeString(root.resolve("etc/shadow"),SHADOW);
                    fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
                }
            }
        }
    }
    @Test public void conflictingNamesAndIdsAreRefusedBeforeAnyAccountMutation() throws Exception {
        for(String[] conflict:List.of(new String[]{"passwd",PASSWD+"foldgpt:x:456:456::/home/foldgpt:/bin/bash\n"},
                new String[]{"passwd",PASSWD+"other:x:12345:456::/home/other:/bin/bash\n"},
                new String[]{"passwd",PASSWD+"other:x:456:23456::/home/other:/bin/bash\n"},
                new String[]{"group",GROUP+"other:x:23456:\n"},new String[]{"group",GROUP+"foldgpt:x:456:\n"},
                new String[]{"group",GROUP.replace("daemon:x:1:","daemon:x:1:foldgpt")},
                new String[]{"shadow",SHADOW+"foldgpt:!:0:0:99999:7:::\n"},
                new String[]{"gshadow",GSHADOW.replace("daemon:*::","daemon:*:foldgpt:")})) {
            Path files=temporary(); Fixture base=fixture();
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=transaction.prepare(base::open).root;
                Files.writeString(root.resolve("etc").resolve(conflict[0]),conflict[1]);
                Map<String,String> before=snapshot(root);
                fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
                assertEquals(before,snapshot(root));
                assertFalse(Files.exists(root.resolve("etc/foldgpt-account.v1")));
                assertFalse(Files.exists(root.resolve("home/foldgpt")));
            }
        }
    }
    @Test public void changedDatabaseOrIdentityCannotBeAdoptedOnResume() throws Exception {
        Path files=temporary(); Fixture base=fixture();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=transaction.prepare(base::open).root;
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID,name -> { if(name.equals("group-written")) throw new IOException("Injected power interruption"); }));
            Files.writeString(root.resolve("etc/shadow"),SHADOW+"outsider:!:0:0:99999:7:::\n");
            Map<String,String> before=snapshot(root);
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
            assertEquals(before,snapshot(root));
            Files.writeString(root.resolve("etc/shadow"),SHADOW);
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID+1,GID));
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID+1));
            assertEquals(UID,GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID).uid);
        }
    }
    @Test public void rejectsLinkedMetadataOrHomeWithoutFollowingIt() throws Exception {
        for(String subject:List.of("etc/passwd","etc/group","etc/shadow","etc/gshadow","etc/foldgpt-account.v1","home/foldgpt")) {
            Path files=temporary(); Fixture base=fixture(); Path outside=Files.createTempFile("foldgpt-account-outside-","");
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=transaction.prepare(base::open).root;
                Files.writeString(outside,"preserve outside\n");
                Files.deleteIfExists(root.resolve(subject)); Files.createSymbolicLink(root.resolve(subject),outside);
                fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
                assertEquals("preserve outside\n",Files.readString(outside));
            } finally { Files.delete(outside); }
        }
    }
    @Test public void rejectsHardlinkedDatabaseAndUnknownExistingHome() throws Exception {
        Path files=temporary(); Fixture base=fixture();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=transaction.prepare(base::open).root;
            Files.createLink(root.resolve("etc/passwd.other"),root.resolve("etc/passwd"));
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
            Files.delete(root.resolve("etc/passwd.other"));
            Files.createDirectory(root.resolve("home/foldgpt"));
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
            assertEquals(PASSWD,Files.readString(root.resolve("etc/passwd")));
        }
    }
    @Test public void neverTouchesUnpreparedClosedOrActivatedTransaction() throws Exception {
        Path files=temporary(); Fixture base=fixture(); RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX);
        try {
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
            assertEquals(RootfsTransaction.State.NEW,transaction.state());
            transaction.prepare(base::open);
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,0,GID));
            GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID);
            transaction.activate(root -> { if(GuestIdentity.load(root).uid!=UID) throw new IOException("Fixture identity differs"); });
            fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
        } finally { transaction.close(); }
        fails(() -> GuestAccountProvisioner.prepare(transaction,STORAGE,UID,GID));
    }
    private static Map<String,String> snapshot(Path root) throws IOException {
        Map<String,String> result=new HashMap<>();
        for(String name:List.of("passwd","group","shadow","gshadow")) result.put(name,Files.readString(root.resolve("etc").resolve(name)));
        return result;
    }
}
