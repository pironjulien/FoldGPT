package app.foldgpt.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** A fresh-install lease and durable transaction, never a migration or updater.
 *
 * Own the lease while preparing guest identity, keys and client in the returned
 * inactive root. activate() is separate and requires a trusted real validator.
 * The Debian base alone is deliberately never activated automatically.
 *
 * Requires an app-owned stable files directory and exclusive installer access:
 * no guest may run from these private stages before activation. This is not a
 * security boundary against arbitrary concurrent native code with the same UID.
 */
public final class RootfsTransaction implements AutoCloseable {
    public enum State { NEW, PREPARING, PREPARED, ACTIVATING, ACTIVE }

    public interface Posix extends RootfsExtractor.Posix {
        /** Stable "device:inode" identity from lstat, not a Java object identity. */
        String identity(Path path) throws IOException;
        long linkCount(Path path) throws IOException;
    }
    public interface ArchiveSource { InputStream open() throws IOException; }
    public interface ActivationValidator {
        /** Must verify the actual complete runtime, account/keyring provisioning
         * and required integration, not merely acknowledge this pristine base. */
        void validate(Path inactiveRoot) throws IOException;
    }
    interface Checkpoint { void at(String name) throws IOException; }

    public static final class Prepared {
        public final Path root;
        public final State state;
        private Prepared(Path root, State state) { this.root = root; this.state = state; }
    }

    private final Path files, container, transaction, stages, journal;
    private final RootfsExtractor.Spec spec;
    private final Posix posix;
    private final UserPrincipal owner;
    private final FileChannel leaseChannel;
    private final FileLock lease;
    private final Checkpoint checkpoint;
    private State state;
    private String stageName = "-", rootIdentity = "-";
    private boolean closed, poisoned;

    public static RootfsTransaction open(Path appFiles, RootfsExtractor.Spec spec, Posix posix) throws IOException {
        return open(appFiles, spec, posix, name -> {});
    }

    static RootfsTransaction open(Path appFiles, RootfsExtractor.Spec spec, Posix posix, Checkpoint checkpoint) throws IOException {
        if (spec == null || posix == null || checkpoint == null) throw new NullPointerException();
        if (Files.isSymbolicLink(appFiles)) throw new IOException("App files directory is a symlink");
        Path files = appFiles.toRealPath();
        if (!attributes(files).isDirectory()) throw new IOException("App files directory is not a directory");
        Path container = files.resolve(".foldgpt-install");
        if (!exists(container) && exists(files.resolve("debian")))
            throw new FileAlreadyExistsException("An existing Linux installation is never replaced");
        UserPrincipal owner = Files.getOwner(files, LinkOption.NOFOLLOW_LINKS);
        createPrivate(container, owner);
        posix.syncDirectory(files);
        Path mutex = container.resolve("install.lock");
        if (exists(mutex)) requireRegular(mutex, owner, posix);
        FileChannel channel = FileChannel.open(mutex, Set.of(StandardOpenOption.CREATE, StandardOpenOption.READ,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        FileLock lock = null;
        try {
            requireRegular(mutex, owner, posix);
            try { lock = channel.tryLock(); }
            catch (OverlappingFileLockException busy) { throw new IOException("Another installation transaction holds the lease", busy); }
            if (lock == null) throw new IOException("Another installation transaction holds the lease");
            RootfsTransaction result = new RootfsTransaction(files, spec, posix, owner, channel, lock, checkpoint);
            result.loadOrCreate();
            return result;
        } catch (IOException | RuntimeException failure) {
            if (lock != null) try { lock.release(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            try { channel.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    private RootfsTransaction(Path files, RootfsExtractor.Spec spec, Posix posix, UserPrincipal owner,
                              FileChannel channel, FileLock lease, Checkpoint checkpoint) {
        this.files = files; this.container = files.resolve(".foldgpt-install");
        this.transaction = container.resolve("fresh"); this.stages = transaction.resolve("stages");
        this.journal = transaction.resolve("journal.v1"); this.spec = spec;
        this.posix = posix; this.owner = owner; this.leaseChannel = channel; this.lease = lease; this.checkpoint = checkpoint;
    }

    public synchronized State state() throws IOException { usable(); return state; }

    public synchronized Prepared prepare(ArchiveSource source) throws IOException {
        usable();
        if (source == null) throw new NullPointerException("archive source");
        try {
            if (recoverActivated()) return prepared();
            refuseExistingActivation();
            if (state == State.PREPARED || state == State.ACTIVATING) {
                verifyPrepared();
                return prepared();
            }
            writeState(State.PREPARING, "-", "-");
            createPrivate(stages, owner);
            posix.syncDirectory(transaction);
            Path completed = null;
            List<Path> abandoned = new ArrayList<>();
            try (var paths = Files.list(stages)) {
                for (Path stage : paths.collect(java.util.stream.Collectors.toList())) {
                    inspectStage(stage);
                    if (validReceipt(stage)) {
                        if (completed != null) throw new IOException("Ambiguous completed rootfs stages");
                        completed = stage;
                    } else abandoned.add(stage);
                }
            }
            // Only registered transaction stages are reclaimed. A live root,
            // migration, arbitrary path or guest symlink target is never walked.
            for (Path stage : abandoned) removeStage(stage);
            if (completed == null) {
                checkpoint.at("before-extract");
                try (InputStream input = source.open()) {
                    if (input == null) throw new IOException("Archive source returned no stream");
                    completed = RootfsExtractor.prepare(input, stages, spec, posix).stage;
                }
            }
            checkpoint.at("after-extracted-receipt");
            inspectStage(completed);
            if (!validReceipt(completed)) throw new IOException("Extraction receipt is missing or invalid");
            Path root = completed.resolve("root");
            writeState(State.PREPARED, completed.getFileName().toString(), posix.identity(root));
            return prepared();
        } catch (IOException | RuntimeException failure) { poisoned = true; throw failure; }
    }

    public synchronized Prepared activate(ActivationValidator validator) throws IOException {
        usable();
        if (validator == null) throw new NullPointerException("A complete runtime validator is required");
        try {
            if (recoverActivated()) return prepared();
            refuseExistingActivation();
            if (state != State.PREPARED && state != State.ACTIVATING) throw new IOException("Rootfs is not prepared");
            verifyPrepared();
            Path root = root();
            validator.validate(root);
            // Flush later provisioning mutations as well as the extracted base.
            syncTree(root);
            writeState(State.ACTIVATING, stageName, rootIdentity);
            checkpoint.at("before-activation-pointer");
            // Java's ATOMIC_MOVE may replace an existing directory. Exclusive
            // symlink creation gives atomic publication with EEXIST semantics
            // on both Android and Linux; it cannot clobber files/debian.
            Files.createSymbolicLink(files.resolve("debian"), relativeRoot());
            checkpoint.at("after-activation-pointer");
            posix.syncDirectory(files);
            writeState(State.ACTIVE, stageName, rootIdentity);
            checkpoint.at("after-active-journal");
            removeArchiveCache();
            return prepared();
        } catch (IOException | RuntimeException failure) { poisoned = true; throw failure; }
    }

    private Prepared prepared() throws IOException {
        return new Prepared(root(), state);
    }

    private void loadOrCreate() throws IOException {
        createPrivate(transaction, owner);
        posix.syncDirectory(container);
        if (exists(journal)) {
            requireRegular(journal, owner, posix);
            byte[] bytes = readSmall(journal, 2048);
            String[] lines = new String(bytes, StandardCharsets.US_ASCII).split("\n", -1);
            if (lines.length != 12 || !lines[0].equals("foldgpt.fresh-install.v1") || !lines[11].isEmpty()
                    || !lines[1].equals(spec.sha256) || !lines[2].equals(Long.toString(spec.compressedBytes))
                    || !lines[3].equals(Long.toString(spec.payloadBytes)) || !lines[4].equals(Long.toString(spec.maxTarBytes))
                    || !lines[5].equals(Integer.toString(spec.members)) || !lines[9].equals("base-only-no-implicit-activation:" + posix.storageBackend()))
                throw new IOException("Installation journal or trusted artifact differs");
            String authenticatedPart = String.join("\n", java.util.Arrays.copyOf(lines, 10)) + "\n";
            if (!lines[10].equals(checksum(authenticatedPart.getBytes(StandardCharsets.US_ASCII))))
                throw new IOException("Installation journal checksum differs");
            try { state = State.valueOf(lines[6]); } catch (IllegalArgumentException bad) { throw new IOException("Unknown install state", bad); }
            stageName = lines[7]; rootIdentity = lines[8];
            if (state == State.NEW || state == State.PREPARING) {
                if (!stageName.equals("-") || !rootIdentity.equals("-")) throw new IOException("Invalid unprepared journal");
            } else if (!validStageName(stageName) || !rootIdentity.matches("[0-9]+:[0-9]+")) throw new IOException("Invalid prepared journal identity");
        } else {
            try (var children = Files.list(transaction)) {
                for (Path child : children.collect(java.util.stream.Collectors.toList()))
                    if (!child.getFileName().toString().equals("journal.next"))
                        throw new IOException("Unidentified files occupy the fresh transaction directory");
            }
            refuseExistingActivation();
            writeState(State.NEW, "-", "-");
        }
        // Interrupted publication is recognized only from our durable intent
        // and exact pointer/target inode; an arbitrary existing Debian is refused.
        if (!recoverActivated()) refuseExistingActivation();
    }

    private void writeState(State next, String stage, String identity) throws IOException {
        String value = "foldgpt.fresh-install.v1\n" + spec.sha256 + "\n" + spec.compressedBytes + "\n"
                + spec.payloadBytes + "\n" + spec.maxTarBytes + "\n" + spec.members + "\n"
                + next.name() + "\n" + stage + "\n" + identity + "\nbase-only-no-implicit-activation:" + posix.storageBackend() + "\n";
        Path pending = transaction.resolve("journal.next");
        value += checksum(value.getBytes(StandardCharsets.US_ASCII)) + "\n";
        if (exists(pending)) { requireRegular(pending, owner, posix); Files.delete(pending); }
        try (FileChannel out = FileChannel.open(pending, Set.of(StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes = ByteBuffer.wrap(value.getBytes(StandardCharsets.US_ASCII));
            while (bytes.hasRemaining()) out.write(bytes);
            out.force(true);
        }
        checkpoint.at("journal-ready-" + next.name());
        Files.move(pending, journal, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        posix.syncDirectory(transaction);
        state = next; stageName = stage; rootIdentity = identity;
    }

    private boolean recoverActivated() throws IOException {
        Path destination = files.resolve("debian");
        if (!exists(destination)) {
            if (state == State.ACTIVE) throw new IOException("Activated rootfs pointer is missing; no silent reinstall");
            return false;
        }
        if ((state != State.ACTIVATING && state != State.ACTIVE) || !Files.isSymbolicLink(destination)
                || !Files.readSymbolicLink(destination).equals(relativeRoot()))
            throw new FileAlreadyExistsException("Existing Linux installation does not belong to this transaction");
        inspectStage(stage());
        if (!posix.identity(root()).equals(rootIdentity)) throw new IOException("Activated rootfs identity changed");
        if (state == State.ACTIVATING) {
            posix.syncDirectory(files);
            writeState(State.ACTIVE, stageName, rootIdentity);
        }
        removeArchiveCache();
        return true;
    }

    private void verifyPrepared() throws IOException {
        inspectStage(stage());
        if (!validReceipt(stage()) || !posix.identity(root()).equals(rootIdentity))
            throw new IOException("Prepared rootfs receipt/identity changed");
    }

    private Path stage() throws IOException {
        if (!validStageName(stageName)) throw new IOException("No prepared stage");
        return stages.resolve(stageName);
    }
    private Path root() throws IOException { return stage().resolve("root"); }
    private Path relativeRoot() throws IOException { return files.relativize(root()); }

    private void inspectStage(Path stage) throws IOException {
        if (!stage.getParent().equals(stages) || !validStageName(stage.getFileName().toString()))
            throw new IOException("Unrecognized staging path");
        requirePrivate(stage, owner);
        try (var paths = Files.list(stage)) {
            for (Path child : paths.collect(java.util.stream.Collectors.toList())) {
                String name = child.getFileName().toString();
                if (name.equals("root")) {
                    if (!attributes(child).isDirectory() || !Files.getOwner(child, LinkOption.NOFOLLOW_LINKS).equals(owner))
                        throw new IOException("Staged root is not an owned directory");
                } else if (name.equals("verified-input.tar.gz") || name.equals("extracted.sha256")) requireRegular(child, owner, posix);
                else throw new IOException("Unknown file occupies an installation stage");
            }
        }
    }

    private boolean validReceipt(Path stage) throws IOException {
        Path receipt = stage.resolve("extracted.sha256");
        if (!exists(receipt)) return false;
        requireRegular(receipt, owner, posix);
        return new String(readSmall(receipt, 128), StandardCharsets.US_ASCII).equals(spec.sha256 + "\n" + posix.storageBackend() + "\n")
                && exists(stage.resolve("root")) && attributes(stage.resolve("root")).isDirectory();
    }

    private void removeArchiveCache() throws IOException {
        Path archive = stage().resolve("verified-input.tar.gz");
        if (exists(archive)) { requireRegular(archive, owner, posix); Files.delete(archive); posix.syncDirectory(stage()); }
    }

    private void removeStage(Path stage) throws IOException {
        inspectStage(stage);
        removeOwnedNode(stage);
        posix.syncDirectory(stages);
    }

    private void removeOwnedNode(Path path) throws IOException {
        // walkFileTree opens directories before preVisitDirectory, so it cannot
        // recover a partial extraction already carrying mode 0000 or 0111.
        // Inspect without following links, then chmod before opening children.
        if (attributes(path).isDirectory()) {
            if (!Files.getOwner(path, LinkOption.NOFOLLOW_LINKS).equals(owner))
                throw new IOException("Foreign-owned stage directory");
            posix.chmod(path, 0700);
            try (var children = Files.newDirectoryStream(path)) {
                for (Path child : children) removeOwnedNode(child);
            }
        }
        Files.delete(path);
    }

    private void syncTree(Path root) throws IOException {
        Files.walkFileTree(root, new SimpleFileVisitor<>() {
            @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attributes) throws IOException {
                if (attributes.isRegularFile()) {
                    try (FileChannel channel = FileChannel.open(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) { channel.force(true); }
                } else if (!attributes.isSymbolicLink()) throw new IOException("Unexpected special file in prepared runtime");
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult postVisitDirectory(Path directory, IOException failure) throws IOException {
                if (failure != null) throw failure;
                posix.syncDirectory(directory);
                return FileVisitResult.CONTINUE;
            }
        });
    }

    private void refuseExistingActivation() throws IOException {
        if (exists(files.resolve("debian"))) throw new FileAlreadyExistsException("Existing Linux installation is preserved");
    }
    private void usable() throws IOException {
        if (closed || poisoned || !lease.isValid()) throw new IOException("Close and reopen the installation transaction after an error");
    }
    private static boolean validStageName(String name) { return name.matches("rootfs-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"); }
    private static BasicFileAttributes attributes(Path path) throws IOException { return Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
    private static boolean exists(Path path) throws IOException { try { attributes(path); return true; } catch (NoSuchFileException absent) { return false; } }
    private static void createPrivate(Path directory, UserPrincipal owner) throws IOException {
        try { Files.createDirectory(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
        catch (FileAlreadyExistsException exists) { /* validated below */ }
        requirePrivate(directory, owner);
    }
    private static void requirePrivate(Path directory, UserPrincipal owner) throws IOException {
        if (!attributes(directory).isDirectory() || !Files.getOwner(directory, LinkOption.NOFOLLOW_LINKS).equals(owner)
                || !Files.getPosixFilePermissions(directory, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rwx------")))
            throw new IOException("Installation directory is not private and owned");
    }
    private static void requireRegular(Path file, UserPrincipal owner, Posix posix) throws IOException {
        if (!attributes(file).isRegularFile() || !Files.getOwner(file, LinkOption.NOFOLLOW_LINKS).equals(owner)
                || posix.linkCount(file) != 1
                || Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).contains(java.nio.file.attribute.PosixFilePermission.GROUP_WRITE)
                || Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).contains(java.nio.file.attribute.PosixFilePermission.OTHERS_WRITE))
            throw new IOException("Unsafe installation metadata file");
    }
    private static String checksum(byte[] bytes) {
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder result = new StringBuilder();
            for (byte value : digest) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return result.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static byte[] readSmall(Path file, int maximum) throws IOException {
        try (FileChannel channel = FileChannel.open(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            if (channel.size() > maximum) throw new IOException("Oversized installation metadata");
            ByteBuffer buffer = ByteBuffer.allocate(maximum + 1);
            while (buffer.hasRemaining() && channel.read(buffer) != -1) {}
            if (!buffer.hasRemaining()) throw new IOException("Oversized installation metadata");
            byte[] bytes = new byte[buffer.position()]; buffer.flip(); buffer.get(bytes); return bytes;
        }
    }
    @Override public synchronized void close() throws IOException {
        if (closed) return;
        closed = true;
        try { lease.release(); } finally { leaseChannel.close(); }
    }
}
