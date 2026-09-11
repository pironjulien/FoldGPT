package app.foldgpt.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.install.RootfsTransactionTest.*;

/** Real unprivileged Linux files, native symlink resolution and process deaths.
 * Tiny declared fixtures test installer mechanics; they are never GPU evidence. */
public class InactiveIntegrationInstallerTest {
    static final String ID="b".repeat(64),XKB=InactiveIntegrationBundle.XKB;
    static final InactiveIntegrationInstaller.Storage STORAGE=new InactiveIntegrationInstaller.Storage() {
        public String identity(Path path) throws IOException { return POSIX.identity(path); }
        public long linkCount(Path path) throws IOException { return POSIX.linkCount(path); }
        public int mode(Path path) throws IOException { return (Integer)Files.getAttribute(path,"unix:mode",LinkOption.NOFOLLOW_LINKS); }
        public void syncDirectory(Path path) throws IOException { POSIX.syncDirectory(path); }
    };
    static final GuestAccountProvisioner.Storage ACCOUNT_STORAGE=new GuestAccountProvisioner.Storage() {
        public String identity(Path path) throws IOException { return POSIX.identity(path); }
        public long linkCount(Path path) throws IOException { return POSIX.linkCount(path); }
        public void syncDirectory(Path path) throws IOException { POSIX.syncDirectory(path); }
    };
    final List<Path> owned=new ArrayList<>();
    Path temporary() throws IOException { Path path=Files.createTempDirectory("foldgpt-integration-test-"); owned.add(path); return path; }
    @After public void cleanup() throws IOException { for(Path path:owned) removeFixture(path); }
    static Fixture base() throws IOException {
        List<Member> members=new ArrayList<>();
        for(String path:List.of(".","etc","home","var","var/lib","usr","usr/share","usr/share/X11",XKB,XKB+"/rules"))
            members.add(new Member(path+"/",'5',0755,""));
        members.add(new Member("etc/passwd",'0',0644,"root:!:0:0:root:/root:/bin/bash\n"));
        members.add(new Member("etc/group",'0',0644,"root:!:0:\n"));
        members.add(new Member(XKB+"/rules/base",'0',0644,"fixture base rules\n"));
        members.add(new Member(XKB+"/rules/evdev",'0',0644,"fixture evdev rules\n"));
        members.add(new Member(XKB+"/rules/xorg",'2',0777,"base"));
        return archive(members.toArray(new Member[0]));
    }
    static byte[] container(String baseSha) throws IOException {
        TreeMap<String,String> records=new TreeMap<>(); TreeMap<String,byte[]> payload=new TreeMap<>();
        for(var item:InactiveIntegrationBundle.FILES.entrySet()) {
            byte[] data=(item.getKey().equals(InactiveIntegrationBundle.CONTRACT_PATH)?InactiveIntegrationBundle.CONTRACT:"fixture "+item.getKey()+"\n").getBytes(StandardCharsets.US_ASCII);
            payload.put(item.getKey(),data);
            records.put(item.getKey(),record("I","F",item.getValue(),data,item.getKey(),"-"));
        }
        InactiveIntegrationBundle.LINKS.forEach((path,target) -> records.put(path,"I\tL\t0777\t0\t-\t"+path+"\t"+target));
        for(String path:List.of(XKB,XKB+"/rules")) records.put(path,"V\tD\t0755\t0\t-\t"+path+"\t-");
        for(String name:List.of("base","evdev")) records.put(XKB+"/rules/"+name,record("V","F",0644,("fixture "+name+" rules\n").getBytes(StandardCharsets.US_ASCII),XKB+"/rules/"+name,"-"));
        records.put(XKB+"/rules/xorg","V\tL\t0777\t0\t-\t"+XKB+"/rules/xorg\tbase");
        String manifest=InactiveIntegrationBundle.FORMAT+"\nbase\t"+baseSha+"\nguest\t"+"a".repeat(64)+"\ngpu\t"+InactiveIntegrationBundle.GPU_SHA+"\n"+String.join("\n",records.values())+"\n";
        return frame(manifest,payload.values());
    }
    static String record(String scope,String kind,int mode,byte[] data,String path,String link) throws IOException {
        return scope+"\t"+kind+"\t"+String.format(Locale.ROOT,"%04o",mode)+"\t"+data.length+"\t"+InactiveIntegrationBundle.hash(data)+"\t"+path+"\t"+link;
    }
    static byte[] frame(String manifest,Collection<byte[]> payload) throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); DataOutputStream out=new DataOutputStream(bytes);
        out.write((InactiveIntegrationBundle.FORMAT+"\n").getBytes(StandardCharsets.US_ASCII));
        byte[] encoded=manifest.getBytes(StandardCharsets.US_ASCII); out.writeInt(encoded.length); out.write(encoded);
        for(byte[] item:payload) out.write(item);
        return bytes.toByteArray();
    }
    static InactiveIntegrationBundle bundle(Fixture base) throws IOException { return parse(container(base.spec.sha256)); }
    static InactiveIntegrationBundle parse(byte[] data) throws IOException {
        return InactiveIntegrationBundle.read(new ByteArrayInputStream(data),InactiveIntegrationBundle.hash(data),data.length);
    }
    static Path prepare(RootfsTransaction transaction,Fixture base) throws IOException {
        Path root=transaction.prepare(base::open).root;
        GuestAccountProvisioner.prepare(transaction,ACCOUNT_STORAGE,12345,23456); return root;
    }
    @Test public void installsActualFilesAndNativeLinksThenRevalidatesWithoutReplacingAnyInode() throws Exception {
        Fixture base=base(); Path files=temporary(); InactiveIntegrationBundle bundle=bundle(base);
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            InactiveIntegrationInstaller.Result first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            assertEquals(PosixFilePermissions.fromString("rwx------"),Files.getPosixFilePermissions(root.resolve("var/lib/foldgpt")));
            Map<String,String> identities=new TreeMap<>();
            for(var entry:bundle.entries.values()) identities.put(entry.path,STORAGE.identity(root.resolve(entry.path)));
            String report=Files.readString(first.report),reportIdentity=STORAGE.identity(first.report);
            InactiveIntegrationInstaller.Result second=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            assertEquals(first.reportSha256,second.reportSha256); assertEquals(report,Files.readString(second.report));
            assertEquals(reportIdentity,STORAGE.identity(second.report));
            for(var entry:identities.entrySet()) assertEquals(entry.getKey(),entry.getValue(),STORAGE.identity(root.resolve(entry.getKey())));
            assertTrue(report.contains("gpuExecution\tnot-performed\n")); assertTrue(report.contains("activation\tnot-performed\n"));
            assertEquals(RootfsTransaction.State.PREPARED,transaction.state()); assertFalse(Files.exists(files.resolve("debian")));
            assertEquals(root.resolve(XKB+"/rules/base"),root.resolve(XKB+"/rules/xorg").toRealPath());
        }
    }
    @Test public void boundLegacyStateParentIsMadePrivateWithoutReplacingReportsOrFiles() throws Exception {
        Fixture base=base(); Path files=temporary(); InactiveIntegrationBundle bundle=bundle(base);
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            InactiveIntegrationInstaller.Result first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            Path parent=root.resolve("var/lib/foldgpt");
            String parentIdentity=STORAGE.identity(parent),reportIdentity=STORAGE.identity(first.report);
            Files.setPosixFilePermissions(parent,PosixFilePermissions.fromString("rwxr-xr-x"));
            InactiveIntegrationInstaller.Result second=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            assertEquals(PosixFilePermissions.fromString("rwx------"),Files.getPosixFilePermissions(parent));
            assertEquals(parentIdentity,STORAGE.identity(parent));
            assertEquals(reportIdentity,STORAGE.identity(second.report));
            assertEquals(first.reportSha256,second.reportSha256);
        }
    }
    @Test public void everyDurablePublicationResumesAfterActualJvmDeath() throws Exception {
        for(String point:List.of("intent-pending","intent-written","directory-created","file-pending","file-written","link-written","report-pending","report-written")) {
            Path files=temporary(); Fixture base=base();
            Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-cp",System.getProperty("java.class.path"),
                InactiveIntegrationInstallerTest.class.getName(),files.toString(),point).redirectErrorStream(true).start();
            if(!child.waitFor(30,TimeUnit.SECONDS)) { child.destroyForcibly(); fail("Integration child timed out at "+point); }
            String output=new String(child.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
            assertEquals(point+": "+output,71,child.exitValue());
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                transaction.prepare(() -> { throw new IOException("No new base is permitted on retry"); });
                var first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base));
                assertEquals(first.reportSha256,InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base)).reportSha256);
                try(var paths=Files.walk(first.root)) { assertFalse(paths.anyMatch(path -> path.getFileName().toString().endsWith(".pending"))); }
                assertEquals(RootfsTransaction.State.PREPARED,transaction.state());
            }
        }
    }
    public static void main(String[] args) throws Exception {
        Fixture base=base();
        try(RootfsTransaction transaction=RootfsTransaction.open(Path.of(args[0]),base.spec,POSIX)) {
            prepare(transaction,base);
            InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base),name -> { if(name.equals(args[1])) Runtime.getRuntime().halt(71); });
        }
        throw new AssertionError("Crash checkpoint was not reached");
    }
    @Test public void xkbCorruptionExtraFilesAndExternalLinksAreRefusedBeforeIntent() throws Exception {
        for(String mutation:List.of("bytes","extra","link","mode")) {
            Path files=temporary(); Fixture base=base();
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=prepare(transaction,base),xkb=root.resolve(XKB);
                if(mutation.equals("bytes")) Files.writeString(xkb.resolve("rules/base"),"corrupt\n");
                if(mutation.equals("extra")) Files.writeString(xkb.resolve("rules/unknown"),"extra\n");
                if(mutation.equals("mode")) Files.setPosixFilePermissions(xkb.resolve("rules/base"),PosixFilePermissions.fromString("rw-------"));
                if(mutation.equals("link")) { Files.delete(xkb.resolve("rules/xorg")); Files.createSymbolicLink(xkb.resolve("rules/xorg"),Path.of("/etc/passwd")); }
                fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base)));
                assertFalse(Files.exists(root.resolve("var/lib/foldgpt/integration-install/intent.v1")));
                assertFalse(Files.exists(root.resolve(InactiveIntegrationBundle.GPU_PREFIX)));
            }
        }
    }
    @Test public void completedInstallationNeverRepairsByteModeLinkMissingOrExtraDrift() throws Exception {
        for(String mutation:List.of("bytes","mode","link","missing","extra")) {
            Path files=temporary(); Fixture base=base();
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=prepare(transaction,base); var result=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base));
                Path gpu=root.resolve(InactiveIntegrationBundle.GPU_PREFIX),target=gpu.resolve("lib/libGL.so.1.2.0");
                byte[] report=Files.readAllBytes(result.report);
                if(mutation.equals("bytes")) Files.writeString(target,"corrupt\n");
                if(mutation.equals("mode")) Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rw-------"));
                if(mutation.equals("link")) { Files.delete(gpu.resolve("lib/libGL.so")); Files.createSymbolicLink(gpu.resolve("lib/libGL.so"),Path.of("libEGL.so")); }
                if(mutation.equals("missing")) Files.delete(target);
                if(mutation.equals("extra")) Files.writeString(gpu.resolve("lib/unknown.so"),"extra\n");
                fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base)));
                assertArrayEquals(report,Files.readAllBytes(result.report));
                if(mutation.equals("missing")) assertFalse(Files.exists(target));
            }
        }
    }
    @Test public void symlinkParentsAndHardlinkedSourcesAreRefused() throws Exception {
        for(String mutation:List.of("parent","hardlink")) {
            Path files=temporary(); Fixture base=base();
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=prepare(transaction,base);
                if(mutation.equals("parent")) Files.createSymbolicLink(root.resolve("opt"),temporary());
                else Files.createLink(root.resolve(XKB+"/rules/alias"),root.resolve(XKB+"/rules/base"));
                fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base)));
                assertFalse(Files.exists(root.resolve("var/lib/foldgpt/integration-install/intent.v1")));
            }
        }
    }
    @Test public void allowsOnlyTheTwoExactCoordinatorHelpersBeforeItsIntent() throws Exception {
        Fixture base=base(); Path files=temporary(); InactiveIntegrationBundle bundle=bundle(base);
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            for(String name:List.of("initialize_keyring.py","supervise_keyring.py")) {
                var entry=bundle.entries.get("usr/local/lib/foldgpt/install/"+name); Path target=root.resolve(entry.path);
                Files.createDirectories(target.getParent()); Files.write(target,Arrays.copyOfRange(bundle.bytes,entry.offset,entry.offset+entry.size));
                Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rw-------"));
            }
            assertNotNull(InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle));
        }
        files=temporary();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base); var entry=bundle.entries.get("usr/local/bin/foldgpt-session"); Path target=root.resolve(entry.path);
            Files.createDirectories(target.getParent()); Files.write(target,Arrays.copyOfRange(bundle.bytes,entry.offset,entry.offset+entry.size));
            Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rwx------"));
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle));
            assertFalse(Files.exists(root.resolve("var/lib/foldgpt/integration-install/intent.v1")));
        }
    }
    @Test public void inputIdentityAndLeaseRemainBoundOnEveryRetry() throws Exception {
        Fixture base=base(); Path files=temporary();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,parse(container("f".repeat(64)))));
            assertFalse(Files.exists(root.resolve("var/lib/foldgpt/integration-install/intent.v1")));
            var result=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base));
            byte[] report=Files.readAllBytes(result.report);
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,"c".repeat(64),bundle(base)));
            assertArrayEquals(report,Files.readAllBytes(result.report));
            transaction.activate(candidate -> {}); // Fixture validator only; production adapter never calls activation.
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle(base)));
        }
    }
    @Test public void archiveAuthenticationAndCanonicalRecordsFailClosed() throws Exception {
        byte[] data=container("f".repeat(64));
        fails(() -> InactiveIntegrationBundle.read(new ByteArrayInputStream(data),"0".repeat(64),data.length));
        fails(() -> InactiveIntegrationBundle.read(new ByteArrayInputStream(data),InactiveIntegrationBundle.hash(data),data.length-1));
        fails(() -> parse(Arrays.copyOf(data,data.length+1)));
        int start=(InactiveIntegrationBundle.FORMAT+"\n").length()+4;
        int length=java.nio.ByteBuffer.wrap(data,start-4,4).getInt();
        String manifest=new String(data,start,length,StandardCharsets.US_ASCII);
        byte[] payload=Arrays.copyOfRange(data,start+length,data.length);
        for(String bad:List.of(manifest.replace("usr/local/bin/xdg-open","usr/local/bin/../xdg-open"),
                manifest.replace("I\tF\t0700","I\tF\t0777"),manifest.replace("\tbase\n","\t/etc/passwd\n"),
                manifest.replace("V\tD\t0755\t0\t-\t"+XKB+"/rules\t-\n",""),
                manifest.replace("V\tD\t0755\t0\t-\t"+XKB+"\t-\n",""),manifest.replace("gpu\t"+InactiveIntegrationBundle.GPU_SHA,"gpu\t"+"0".repeat(64))))
            fails(() -> parse(frame(bad,List.of(payload))));
    }
    @Test public void partialOwnPendingFileIsRecoverableButCompletedTargetsNeverAcceptPendingAliases() throws Exception {
        Fixture base=base(); Path files=temporary();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base); InactiveIntegrationBundle bundle=bundle(base);
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle,name -> {
                if(name.equals("file-pending")) throw new IOException("Simulated interrupted caller; separate tests cover JVM death");
            }));
            Path pending;
            try(var paths=Files.walk(root)) {
                pending=paths.filter(path -> path.getFileName().toString().endsWith(".pending")).findFirst().orElseThrow();
            }
            Files.writeString(pending,"partial write");
            var result=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            assertFalse(Files.exists(pending));
            Files.writeString(pending,"unexpected pending alias");
            fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle));
            assertTrue(Files.exists(result.report)); assertTrue(Files.exists(pending));
        }
    }
}
