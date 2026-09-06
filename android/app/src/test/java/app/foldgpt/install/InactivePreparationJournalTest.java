package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.install.RootfsTransactionTest.*;

/** Filesystem journal tests only; fixture hashes do not simulate Android crypto or GNOME. */
public class InactivePreparationJournalTest {
    private static final String DIGEST="1234567890abcdef".repeat(4);
    private static final String COLLECTION="/org/freedesktop/secrets/collection/FoldGPT_fixture";
    private static final GuestAccountProvisioner.Storage STORAGE=new GuestAccountProvisioner.Storage() {
        public String identity(Path path) throws IOException { return POSIX.identity(path); }
        public long linkCount(Path path) throws IOException { return POSIX.linkCount(path); }
        public void syncDirectory(Path path) throws IOException { POSIX.syncDirectory(path); }
    };
    private final List<Path> owned=new ArrayList<>();
    private Path temporary() throws IOException {
        Path path=Files.createTempDirectory("foldgpt-inactive-journal-",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        owned.add(path); return path;
    }
    @After public void cleanup() throws IOException { for(Path path:owned) removeFixture(path); }
    private static Map<String,String> bindings(Path root) throws IOException {
        return Map.of("root",STORAGE.identity(root),"base",DIGEST,"initializer",DIGEST,"supervisor",DIGEST,"vaultParent",STORAGE.identity(root));
    }
    private static void advance(InactivePreparationJournal journal) throws IOException {
        if(journal.step()==InactivePreparationJournal.Step.ROOT_PREPARED) journal.accountPrepared();
        if(journal.step()==InactivePreparationJournal.Step.ACCOUNT_PREPARED) journal.vaultPrepared(DIGEST);
        if(journal.step()==InactivePreparationJournal.Step.VAULT_PREPARED) journal.collectionPrepared(DIGEST,DIGEST,COLLECTION,"1:2");
    }
    @Test public void persistsExactBoundIdentityAndOnlyInactiveOrderedSteps() throws Exception {
        Path root=temporary(),file=root.resolve("coordinator.v1");
        InactivePreparationJournal journal=InactivePreparationJournal.open(file,bindings(root),STORAGE);
        String id=journal.value("installationId");
        assertTrue(id.matches("[0-9a-f]{64}"));
        fails(() -> journal.vaultPrepared(DIGEST));
        fails(() -> journal.collectionPrepared(DIGEST,DIGEST,COLLECTION,"1:2"));
        advance(journal);
        InactivePreparationJournal resumed=InactivePreparationJournal.open(file,bindings(root),STORAGE);
        assertEquals(InactivePreparationJournal.Step.COLLECTION_PREPARED,resumed.step());
        assertEquals(id,resumed.value("installationId"));
        assertEquals(DIGEST,resumed.value("vaultSha256")); assertEquals(COLLECTION,resumed.value("collectionPath"));
        assertEquals(4,InactivePreparationJournal.Step.values().length);
        assertFalse(Files.exists(root.resolve("debian"),LinkOption.NOFOLLOW_LINKS));
    }
    @Test public void resumesAfterRealProcessDeathOnBothSidesOfEveryPublication() throws Exception {
        for(String step:List.of("ROOT_PREPARED","ACCOUNT_PREPARED","VAULT_PREPARED","COLLECTION_PREPARED")) for(String point:List.of("ready-","written-")) {
            Path root=temporary(),file=root.resolve("coordinator.v1");
            Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-cp",System.getProperty("java.class.path"),
                    InactivePreparationJournalTest.class.getName(),root.toString(),point+step).redirectErrorStream(true).start();
            if(!child.waitFor(30,TimeUnit.SECONDS)) { child.destroyForcibly(); fail("Journal child timed out"); }
            assertEquals(new String(child.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8),71,child.exitValue());
            String before=Files.exists(file)?InactivePreparationJournal.open(file,bindings(root),STORAGE).value("installationId"):null;
            InactivePreparationJournal resumed=InactivePreparationJournal.open(file,bindings(root),STORAGE);
            advance(resumed);
            if(before!=null) assertEquals(before,resumed.value("installationId"));
            assertEquals(InactivePreparationJournal.Step.COLLECTION_PREPARED,resumed.step());
            assertFalse(Files.exists(file.resolveSibling("coordinator.v1.next")));
        }
    }
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);
        InactivePreparationJournal journal=InactivePreparationJournal.open(root.resolve("coordinator.v1"),bindings(root),STORAGE,
            point -> { if(point.equals(args[1])) Runtime.getRuntime().halt(71); });
        advance(journal); throw new AssertionError("Requested real process-death point was not reached");
    }
    @Test public void refusesChangedRootComponentsChecksumAndUnsafeLinks() throws Exception {
        Path root=temporary(),file=root.resolve("coordinator.v1");
        InactivePreparationJournal.open(file,bindings(root),STORAGE);
        byte[] original=Files.readAllBytes(file);
        Map<String,String> changed=new TreeMap<>(bindings(root)); changed.put("root","55:66");
        fails(() -> InactivePreparationJournal.open(file,changed,STORAGE));
        changed.put("root",bindings(root).get("root")); changed.put("base","abcdef0123456789".repeat(4));
        fails(() -> InactivePreparationJournal.open(file,changed,STORAGE));
        Files.writeString(file,Files.readString(file).replace("ROOT_PREPARED","ACCOUNT_PREPARED"));
        fails(() -> InactivePreparationJournal.open(file,bindings(root),STORAGE));
        Files.write(file,original);
        Path other=root.resolve("other"); Files.createLink(other,file);
        fails(() -> InactivePreparationJournal.open(file,bindings(root),STORAGE));
        Files.delete(other); Files.move(file,other); Files.createSymbolicLink(file,Path.of("other"));
        fails(() -> InactivePreparationJournal.open(file,bindings(root),STORAGE));
        assertArrayEquals(original,Files.readAllBytes(other));
    }
    @Test public void missingEvidenceCannotBeRecordedAsCollectionPreparation() throws Exception {
        Path root=temporary(),file=root.resolve("coordinator.v1");
        InactivePreparationJournal journal=InactivePreparationJournal.open(file,bindings(root),STORAGE);
        journal.accountPrepared(); fails(() -> journal.vaultPrepared("-")); journal.vaultPrepared(DIGEST);
        fails(() -> journal.collectionPrepared(DIGEST,DIGEST,"/org/freedesktop/secrets/collection/session","1:2"));
        fails(() -> journal.collectionPrepared("-",DIGEST,COLLECTION,"1:2"));
        fails(() -> journal.collectionPrepared(DIGEST,DIGEST,COLLECTION,"-"));
        assertEquals(InactivePreparationJournal.Step.VAULT_PREPARED,journal.step());
    }
}
