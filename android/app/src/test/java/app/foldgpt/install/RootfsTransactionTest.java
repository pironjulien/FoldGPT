package app.foldgpt.install;

import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/** Real Linux filesystem/JVM tests, including separate processes killed without
 * finally blocks. No Android, official client, keyring or account is exercised. */
public class RootfsTransactionTest {
    @Test public void prootBackingSharesBytesAndRejectsConflicts() throws Exception {
        Path root = Files.createTempDirectory("foldgpt-l2s-test-");
        try {
            Path source = root.resolve("source"), alias = root.resolve("alias");
            Files.writeString(source, "first");
            ProotHardlinkStorage.create(root, Map.of(source, List.of(alias)), POSIX);
            assertTrue(Files.isSymbolicLink(source));
            assertEquals(Files.readSymbolicLink(source), Files.readSymbolicLink(alias));
            assertEquals(source.toRealPath(), alias.toRealPath());
            Files.writeString(alias, "second");
            assertEquals("second", Files.readString(source));
            assertTrue(Files.isRegularFile(ProotHardlinkStorage.data(source, 2), LinkOption.NOFOLLOW_LINKS));
            Path other = root.resolve("other"), otherAlias = root.resolve("other-alias");
            Files.writeString(other, "protected");
            Files.writeString(ProotHardlinkStorage.intermediate(other), "existing");
            try { ProotHardlinkStorage.create(root, Map.of(other, List.of(otherAlias)), POSIX); fail("collision accepted"); }
            catch (IOException expected) { assertEquals("protected", Files.readString(other)); }
        } finally {
            try (var paths = Files.walk(root)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
    }
    static final RootfsTransaction.Posix POSIX = new RootfsTransaction.Posix() {
        public void chmod(Path path, int mode) throws IOException {
            if (Files.isSymbolicLink(path)) throw new IOException("Refusing linked chmod target");
            // Match Android lstat + Os.chmod under the exclusive-tree contract.
            // JDK NOFOLLOW uses a read-open + fchmod and cannot reopen mode 0000.
            Files.setAttribute(path, "unix:mode", mode);
        }
        public void syncDirectory(Path path) throws IOException {
            if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Not a real directory");
            try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) { channel.force(true); }
        }
        public String identity(Path path) throws IOException {
            return Long.toUnsignedString(((Number)Files.getAttribute(path, "unix:dev", LinkOption.NOFOLLOW_LINKS)).longValue()) + ":"
                    + Long.toUnsignedString(((Number)Files.getAttribute(path, "unix:ino", LinkOption.NOFOLLOW_LINKS)).longValue());
        }
        public long linkCount(Path path) throws IOException { return ((Number)Files.getAttribute(path, "unix:nlink", LinkOption.NOFOLLOW_LINKS)).longValue(); }
    };
    static RootfsTransaction.Posix prootPosix(ProotHardlinkStorage.Checkpoint checkpoint) {
        return new RootfsTransaction.Posix() {
            public String storageBackend() { return ProotHardlinkStorage.BACKEND; }
            public void createHardlinks(Path root, Map<Path,List<Path>> groups) throws IOException {
                ProotHardlinkStorage.create(root,groups,this,checkpoint);
            }
            public void chmod(Path path,int mode) throws IOException { POSIX.chmod(path,mode); }
            public void syncDirectory(Path path) throws IOException { POSIX.syncDirectory(path); }
            public String identity(Path path) throws IOException { return POSIX.identity(path); }
            public long linkCount(Path path) throws IOException { return POSIX.linkCount(path); }
        };
    }
    @Test public void prootConversionSurvivesRealProcessDeathsAndKeepsStableAbsolutePaths() throws Exception {
        for (String point : List.of("backing-moved","intermediate-created","source-created","alias-created","group-synced")) {
            Path files=temporary(); Fixture fixture=standard(); Path input=files.resolve("input.gz"); Files.write(input,fixture.archive);
            assertEquals(71,child("proot-crash",files,input,fixture.spec,point));
            assertFalse(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS));
            Path oldStage;
            try(var stages=Files.list(files.resolve(".foldgpt-install/fresh/stages"))) { oldStage=stages.findFirst().orElseThrow(); }
            assertFalse(Files.exists(oldStage.resolve("extracted.sha256")));
            Path root;
            try(RootfsTransaction resumed=RootfsTransaction.open(files,fixture.spec,prootPosix(name -> {}))) {
                root=resumed.prepare(fixture::open).root;
                assertFalse(Files.exists(oldStage,LinkOption.NOFOLLOW_LINKS));
                assertTrue(Files.isSymbolicLink(root.resolve("usr/value")));
                assertEquals(root.resolve("usr/.l2s.value0001"),Files.readSymbolicLink(root.resolve("usr/alias")));
                assertEquals("actual base bytes\n",Files.readString(root.resolve("usr/alias")));
                resumed.activate(RootfsTransactionTest::fixtureValidator);
            }
            assertEquals(root,files.resolve("debian").toRealPath());
            assertEquals("actual base bytes\n",Files.readString(files.resolve("debian/usr/alias")));
            try(RootfsTransaction resumed=RootfsTransaction.open(files,fixture.spec,prootPosix(name -> {}))) {
                assertEquals(root,resumed.prepare(() -> { throw new IOException("Unexpected extraction after activation"); }).root);
            }
        }
    }
    @Test public void storageBackendMismatchCannotAdoptPreparedData() throws Exception {
        Fixture fixture=standard(); Path files=temporary();
        try(RootfsTransaction transaction=RootfsTransaction.open(files,fixture.spec,POSIX)) { transaction.prepare(fixture::open); }
        fails(() -> { try(RootfsTransaction ignored=RootfsTransaction.open(files,fixture.spec,prootPosix(name -> {}))) {} });
        try(RootfsTransaction transaction=RootfsTransaction.open(files,fixture.spec,POSIX)) {
            assertTrue(Files.isRegularFile(transaction.prepare(fixture::open).root.resolve("usr/value"),LinkOption.NOFOLLOW_LINKS));
        }
    }
    final List<Path> owned = new ArrayList<>();
    Path temporary() throws IOException { Path path = Files.createTempDirectory("foldgpt-install-test-"); owned.add(path); return path; }
    @After public void cleanup() throws IOException {
        for (Path path : owned) {
            if (!path.getFileName().toString().startsWith("foldgpt-install-test-") || Files.isSymbolicLink(path)) throw new IOException("Invalid owned fixture");
            removeFixture(path);
        }
    }
    static void removeFixture(Path path) throws IOException {
        if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            POSIX.chmod(path, 0700);
            try (DirectoryStream<Path> children = Files.newDirectoryStream(path)) {
                for (Path child : children) removeFixture(child);
            }
        }
        Files.delete(path);
    }

    static final class Member {
        final String name, link; final byte type; final int mode; final byte[] bytes;
        Member(String name, char type, int mode, String value) {
            this.name = name; this.type = (byte)type; this.mode = mode;
            this.link = type == '1' || type == '2' ? value : "";
            this.bytes = type == '0' ? value.getBytes(StandardCharsets.UTF_8) : new byte[0];
        }
    }
    static final class Fixture {
        final byte[] archive, tar; final RootfsExtractor.Spec spec;
        Fixture(byte[] tar, long payload, int members) throws IOException {
            this.tar = tar;
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (GZIPOutputStream gzip = new GZIPOutputStream(bytes)) { gzip.write(tar); }
            this.archive = bytes.toByteArray();
            this.spec = new RootfsExtractor.Spec(hash(archive), archive.length, payload, tar.length, members);
        }
        InputStream open() { return new ByteArrayInputStream(archive); }
    }
    static Fixture archive(Member... members) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream(); long payload = 0;
        try (TarArchiveOutputStream tar = new TarArchiveOutputStream(buffer)) {
            tar.setLongFileMode(TarArchiveOutputStream.LONGFILE_POSIX);
            for (Member member : members) {
                TarArchiveEntry entry = new TarArchiveEntry(member.name, member.type, true);
                entry.setMode(member.mode); entry.setUserId(0); entry.setGroupId(0); entry.setModTime(0);
                entry.setLinkName(member.link); entry.setSize(member.bytes.length);
                tar.putArchiveEntry(entry); tar.write(member.bytes); tar.closeArchiveEntry(); payload += member.bytes.length;
            }
        }
        return new Fixture(buffer.toByteArray(), payload, members.length);
    }
    static Fixture standard() throws IOException {
        return archive(new Member("./", '5', 0755, ""), new Member("./usr/", '5', 0755, ""),
                new Member("./usr/value", '0', 0644, "actual base bytes\n"),
                new Member("./bin", '2', 0777, "usr"), new Member("./usr/alias", '1', 0644, "./usr/value"));
    }
    static String hash(byte[] bytes) {
        try {
            StringBuilder value = new StringBuilder();
            for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes)) value.append(String.format(Locale.ROOT, "%02x", b & 255));
            return value.toString();
        } catch (Exception error) { throw new IllegalStateException(error); }
    }
    static void fixtureValidator(Path root) throws IOException {
        if (!Files.readString(root.resolve("usr/value")).equals("actual base bytes\n")) throw new IOException("Invalid test fixture");
        // This validates only the fixed test runtime, never a production client/keyring.
    }
    static void fails(IOAction action) throws Exception {
        try { action.run(); fail("Expected a real refusal"); } catch (IOException expected) { assertNotNull(expected.getMessage()); }
    }
    interface IOAction { void run() throws Exception; }

    @Test public void preparesWithoutActivatingAndActivatesOnlyAfterValidation() throws Exception {
        Path files = temporary(); Fixture fixture = standard(); Path root;
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            root = transaction.prepare(fixture::open).root;
            assertEquals(RootfsTransaction.State.PREPARED, transaction.state());
            assertFalse(Files.exists(files.resolve("debian"), LinkOption.NOFOLLOW_LINKS));
            assertEquals("usr", Files.readSymbolicLink(root.resolve("bin")).toString());
            assertTrue(Files.isSameFile(root.resolve("usr/value"), root.resolve("usr/alias")));
            transaction.activate(RootfsTransactionTest::fixtureValidator);
            assertEquals(RootfsTransaction.State.ACTIVE, transaction.state());
        }
        assertTrue(Files.isSymbolicLink(files.resolve("debian")));
        assertEquals(root, files.resolve("debian").toRealPath());
        assertFalse(Files.exists(root.getParent().resolve("verified-input.tar.gz")));
        try (RootfsTransaction recovered = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            assertEquals(root, recovered.prepare(() -> { throw new IOException("Must not download twice"); }).root);
            recovered.activate(path -> { throw new IOException("Completed activation must not provision twice"); });
        }
    }

    @Test public void existingMigrationRemainsUntouched() throws Exception {
        Path files = temporary(); Fixture fixture = standard();
        Files.createDirectory(files.resolve("debian")); Files.writeString(files.resolve("debian/profile"), "private existing profile");
        fails(() -> RootfsTransaction.open(files, fixture.spec, POSIX));
        assertEquals("private existing profile", Files.readString(files.resolve("debian/profile")));
        assertFalse(Files.exists(files.resolve(".foldgpt-install")));
    }

    @Test public void activationLosesCreationRaceWithoutReplacingDestination() throws Exception {
        Path files = temporary(); Fixture fixture = standard();
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX, name -> {
            if (name.equals("before-activation-pointer")) {
                Files.createDirectory(files.resolve("debian")); Files.writeString(files.resolve("debian/profile"), "race winner");
            }
        })) {
            transaction.prepare(fixture::open);
            fails(() -> transaction.activate(RootfsTransactionTest::fixtureValidator));
        }
        assertEquals("race winner", Files.readString(files.resolve("debian/profile")));
        fails(() -> RootfsTransaction.open(files, fixture.spec, POSIX));
    }

    @Test public void validatorFailurePreservesInactivePreparedRoot() throws Exception {
        Path files = temporary(); Fixture fixture = standard(); Path root;
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            root = transaction.prepare(fixture::open).root;
            fails(() -> transaction.activate(path -> { throw new IOException("Missing real runtime components"); }));
        }
        assertFalse(Files.exists(files.resolve("debian"), LinkOption.NOFOLLOW_LINKS));
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            assertEquals(root, transaction.prepare(() -> { throw new IOException("Unexpected download"); }).root);
        }
    }

    @Test public void journalChecksumAndHardlinkTamperingAreRefused() throws Exception {
        Path files = temporary(); Fixture fixture = standard();
        try (RootfsTransaction ignored = RootfsTransaction.open(files, fixture.spec, POSIX)) {}
        Path journal = files.resolve(".foldgpt-install/fresh/journal.v1");
        String original = Files.readString(journal);
        Files.writeString(journal, original.replace("\nNEW\n", "\nPREPARING\n"));
        fails(() -> RootfsTransaction.open(files, fixture.spec, POSIX));
        Files.writeString(journal, original);
        Files.createLink(files.resolve("journal-alias"), journal);
        fails(() -> RootfsTransaction.open(files, fixture.spec, POSIX));
        Files.delete(files.resolve("journal-alias"));
        Files.createLink(files.resolve("lock-alias"), files.resolve(".foldgpt-install/install.lock"));
        fails(() -> RootfsTransaction.open(files, fixture.spec, POSIX));
    }

    @Test public void changedTrustedDescriptorIsRefused() throws Exception {
        Path files = temporary(); Fixture fixture = standard();
        try (RootfsTransaction ignored = RootfsTransaction.open(files, fixture.spec, POSIX)) {}
        RootfsExtractor.Spec changed = new RootfsExtractor.Spec(fixture.spec.sha256, fixture.spec.compressedBytes,
                fixture.spec.payloadBytes, fixture.spec.maxTarBytes + 512, fixture.spec.members);
        fails(() -> RootfsTransaction.open(files, changed, POSIX));
    }

    @Test public void badDigestAndInterruptedDownloadCanResumeSafely() throws Exception {
        Path files = temporary(); Fixture fixture = standard();
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            fails(() -> transaction.prepare(() -> new ByteArrayInputStream(new byte[]{1, 2, 3})));
        }
        assertFalse(Files.exists(files.resolve("debian"), LinkOption.NOFOLLOW_LINKS));
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            assertNotNull(transaction.prepare(fixture::open).root);
        }
    }

    @Test public void crashesRecoverAfterReceiptAndBeforeOrAfterPointerPublication() throws Exception {
        for (String point : List.of("after-extracted-receipt", "journal-ready-PREPARED", "before-activation-pointer", "after-activation-pointer", "after-active-journal", "partial-download")) {
            Path files = temporary(); Fixture fixture = standard();
            Path input = files.resolve("input.gz"); Files.write(input, fixture.archive);
            assertEquals(point, 71, child("crash", files, input, fixture.spec, point));
            AtomicInteger downloads = new AtomicInteger();
            try (RootfsTransaction recovered = RootfsTransaction.open(files, fixture.spec, POSIX)) {
                RootfsTransaction.Prepared prepared = recovered.prepare(() -> { downloads.incrementAndGet(); return fixture.open(); });
                fixtureValidator(prepared.root);
                recovered.activate(RootfsTransactionTest::fixtureValidator);
                assertEquals(RootfsTransaction.State.ACTIVE, recovered.state());
            }
            assertEquals(point, point.equals("partial-download") ? 1 : 0, downloads.get());
            assertEquals("actual base bytes\n", Files.readString(files.resolve("debian/usr/value")));
        }
    }

    @Test public void secondJvmCannotAcquireActiveInstallLease() throws Exception {
        Path files = temporary(); Fixture fixture = standard(); Path input = files.resolve("input.gz"); Files.write(input, fixture.archive);
        try (RootfsTransaction ignored = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            assertEquals(23, child("lock", files, input, fixture.spec, "none"));
        }
        assertEquals(0, child("lock", files, input, fixture.spec, "none"));
    }

    @Test public void preservesSpecialModesAbsoluteGuestLinksAndPaxPaths() throws Exception {
        Path files = temporary(); String longName = "n".repeat(180);
        Fixture fixture = archive(new Member("./", '5', 01777, ""), new Member("./usr/", '5', 0755, ""),
                new Member("./usr/" + longName, '0', 04755, "package bytes"), new Member("./guest-link", '2', 0777, "/usr/" + longName));
        try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) {
            Path root = transaction.prepare(fixture::open).root;
            assertEquals(01777, ((Number)Files.getAttribute(root, "unix:mode")).intValue() & 07777);
            assertEquals(04755, ((Number)Files.getAttribute(root.resolve("usr/" + longName), "unix:mode")).intValue() & 07777);
            assertEquals("/usr/" + longName, Files.readSymbolicLink(root.resolve("guest-link")).toString());
        }
    }

    @Test public void maliciousPathsLinksAndNormalizedDuplicatesDoNotEscape() throws Exception {
        Path outside = temporary(); Path sentinel = outside.resolve("sentinel"); Files.writeString(sentinel, "outside is intact");
        List<Fixture> fixtures = List.of(
                archive(new Member("./", '5', 0755, ""), new Member("../sentinel", '0', 0644, "attack")),
                archive(new Member("./", '5', 0755, ""), new Member("/sentinel", '0', 0644, "attack")),
                archive(new Member("./", '5', 0755, ""), new Member("value", '0', 0644, "one"), new Member("./value", '0', 0644, "two")),
                archive(new Member("./", '5', 0755, ""), new Member("link", '2', 0777, outside.toString()), new Member("link/sentinel", '0', 0644, "attack")),
                archive(new Member("./", '5', 0755, ""), new Member("alias", '1', 0644, "../sentinel")),
                archive(new Member("./", '5', 0755, ""), new Member("fifo", '6', 0644, "")));
        for (Fixture fixture : fixtures) {
            Path files = temporary();
            try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) { fails(() -> transaction.prepare(fixture::open)); }
            assertFalse(Files.exists(files.resolve("debian"), LinkOption.NOFOLLOW_LINKS));
            assertEquals("outside is intact", Files.readString(sentinel));
        }
    }

    @Test public void inaccessibleDirectoriesRetainModesAndInterruptedStagesRecover() throws Exception {
        for (int mode : new int[]{0000, 0111}) {
            Path files = temporary();
            Fixture fixture = archive(new Member("./", '5', 0755, ""),
                    new Member("locked/", '5', mode, ""),
                    new Member("locked/value", '0', 0000, "real bytes"));
            try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX,
                    checkpoint -> {
                        if (checkpoint.equals("after-extracted-receipt")) {
                            Path stages = files.resolve(".foldgpt-install/fresh/stages");
                            try (DirectoryStream<Path> children = Files.newDirectoryStream(stages)) {
                                Path stage = children.iterator().next();
                                assertEquals(mode, ((Number)Files.getAttribute(stage.resolve("root/locked"), "unix:mode")).intValue() & 07777);
                                Files.delete(stage.resolve("extracted.sha256"));
                            }
                            throw new IOException("Interrupted before receipt completion");
                        }
                    })) {
                fails(() -> transaction.prepare(fixture::open));
            }
            try (RootfsTransaction resumed = RootfsTransaction.open(files, fixture.spec, POSIX)) {
                Path root = resumed.prepare(fixture::open).root;
                assertEquals(mode, ((Number)Files.getAttribute(root.resolve("locked"), "unix:mode")).intValue() & 07777);
                POSIX.chmod(root.resolve("locked"), 0700);
                assertEquals(0000, ((Number)Files.getAttribute(root.resolve("locked/value"), "unix:mode")).intValue() & 07777);
                POSIX.chmod(root.resolve("locked/value"), 0400);
                assertEquals("real bytes", Files.readString(root.resolve("locked/value")));
            }
        }
    }

    @Test public void truncatedTerminalBlocksTrailingDataAndBadGzipCrcAreRejected() throws Exception {
        Fixture source = standard(); int last = source.tar.length - 1;
        while (last >= 0 && source.tar[last] == 0) last--;
        int end = ((last / 512) + 1) * 512;
        List<Fixture> fixtures = new ArrayList<>();
        fixtures.add(new Fixture(Arrays.copyOf(source.tar, end), source.spec.payloadBytes, source.spec.members));
        fixtures.add(new Fixture(Arrays.copyOf(source.tar, end + 512), source.spec.payloadBytes, source.spec.members));
        byte[] trailing = Arrays.copyOf(source.tar, source.tar.length + 512); trailing[trailing.length - 1] = 1;
        fixtures.add(new Fixture(trailing, source.spec.payloadBytes, source.spec.members));
        for (Fixture fixture : fixtures) {
            Path files = temporary();
            try (RootfsTransaction transaction = RootfsTransaction.open(files, fixture.spec, POSIX)) { fails(() -> transaction.prepare(fixture::open)); }
        }
        byte[] corrupt = source.archive.clone(); corrupt[corrupt.length - 8] ^= 1;
        RootfsExtractor.Spec corruptSpec = new RootfsExtractor.Spec(hash(corrupt), corrupt.length, source.spec.payloadBytes, source.spec.maxTarBytes, source.spec.members);
        try (RootfsTransaction transaction = RootfsTransaction.open(temporary(), corruptSpec, POSIX)) {
            fails(() -> transaction.prepare(() -> new ByteArrayInputStream(corrupt)));
        }
    }

    static int child(String mode, Path files, Path input, RootfsExtractor.Spec spec, String point) throws Exception {
        List<String> command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin/java").toString(), "-cp",
                System.getProperty("java.class.path"), RootfsTransactionTest.class.getName(), mode, files.toString(), input.toString(), spec.sha256,
                Long.toString(spec.compressedBytes), Long.toString(spec.payloadBytes), Long.toString(spec.maxTarBytes), Integer.toString(spec.members), point));
        Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
        if (!process.waitFor(30, TimeUnit.SECONDS)) { process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS); throw new IOException("Child JVM deadline"); }
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        if (process.exitValue() != 0 && process.exitValue() != 71 && process.exitValue() != 23) throw new IOException("Child JVM failed: " + output);
        return process.exitValue();
    }
    public static void main(String[] args) throws Exception {
        Path files = Path.of(args[1]), archive = Path.of(args[2]);
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(args[3], Long.parseLong(args[4]), Long.parseLong(args[5]), Long.parseLong(args[6]), Integer.parseInt(args[7]));
        String point = args[8];
        if (args[0].equals("proot-crash")) {
            try(RootfsTransaction transaction=RootfsTransaction.open(files,spec,
                    prootPosix(name -> { if(name.equals(point)) Runtime.getRuntime().halt(71); }))) {
                transaction.prepare(() -> Files.newInputStream(archive));
            }
            throw new IOException("Storage crash checkpoint was not reached");
        }
        if (args[0].equals("lock")) {
            try (RootfsTransaction ignored = RootfsTransaction.open(files, spec, POSIX)) { return; }
            catch (IOException busy) { if (!busy.getMessage().contains("lease")) throw busy; System.exit(23); }
        }
        try (RootfsTransaction transaction = RootfsTransaction.open(files, spec, POSIX, name -> { if (name.equals(point)) Runtime.getRuntime().halt(71); })) {
            transaction.prepare(() -> {
                InputStream input = Files.newInputStream(archive);
                if (!point.equals("partial-download")) return input;
                return new FilterInputStream(input) {
                    boolean first = true;
                    @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                        if (!first) Runtime.getRuntime().halt(71);
                        first = false; return in.read(bytes, offset, Math.min(length, 8));
                    }
                };
            });
            transaction.activate(RootfsTransactionTest::fixtureValidator);
        }
        throw new IOException("Crash checkpoint was not reached");
    }
}
