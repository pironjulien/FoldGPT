package app.foldgpt.install;

import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;

import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.zip.GZIPInputStream;

/** Prepares an inactive rootfs. Activation and the shared runtime lease are the caller's job.
 *
 * The parent must be private, stable, and exclusively installer-owned: no guest may run
 * concurrently. The method never merges with an installed filesystem or follows guest
 * links. Its SHA/size/count limits must come from a trusted release manifest, not the
 * archive being downloaded. An unfinished stage is retained for the transaction owner.
 */
public final class RootfsExtractor {
    private RootfsExtractor() {}

    /** Android supplies Os.chmod and directory fsync; host tests use their real POSIX equivalents. */
    public interface Posix {
        void chmod(Path path, int mode) throws IOException;
        void syncDirectory(Path path) throws IOException;
        default String storageBackend() { return "native-posix-v1"; }
        default void createHardlinks(Path root, Map<Path, List<Path>> groups) throws IOException {
            for (Map.Entry<Path, List<Path>> group : groups.entrySet())
                for (Path alias : group.getValue()) Files.createLink(alias, group.getKey());
        }
        default void setSymlinkModified(Path path, java.nio.file.attribute.FileTime modified) throws IOException {
            Files.getFileAttributeView(path, java.nio.file.attribute.BasicFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS).setTimes(modified, null, null);
        }
    }

    public static final class Spec {
        public final String sha256;
        public final long compressedBytes, payloadBytes, maxTarBytes;
        public final int members;
        public Spec(String sha256, long compressedBytes, long payloadBytes, long maxTarBytes, int members) {
            if (sha256 == null || !sha256.matches("[0-9a-f]{64}") || compressedBytes < 1
                    || payloadBytes < 0 || maxTarBytes < payloadBytes || members < 1) {
                throw new IllegalArgumentException("Invalid trusted rootfs manifest");
            }
            this.sha256 = sha256;
            this.compressedBytes = compressedBytes;
            this.payloadBytes = payloadBytes;
            this.maxTarBytes = maxTarBytes;
            this.members = members;
        }
    }

    public static final class Prepared {
        public final Path stage, root;
        public final Spec spec;
        private Prepared(Path stage, Path root, Spec spec) {
            this.stage = stage; this.root = root; this.spec = spec;
        }
    }

    private static final class Entry {
        final String name, link;
        final int mode;
        final char type;
        final java.nio.file.attribute.FileTime modified;
        Entry(String name, TarArchiveEntry value, char type) {
            this.name = name; this.link = value.getLinkName();
            this.mode = value.getMode() & 07777; this.type = type;
            this.modified = value.getLastModifiedTime();
        }
    }

    /** Does not close the caller's input. No rootfs path is returned on any failure. */
    public static Prepared prepare(InputStream input, Path parent, Spec spec, Posix posix) throws IOException {
        parent = parent.toAbsolutePath().normalize();
        if (!parent.equals(parent.toRealPath())
                || !Files.readAttributes(parent, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS).isDirectory()
                || !Files.getPosixFilePermissions(parent, LinkOption.NOFOLLOW_LINKS)
                    .equals(PosixFilePermissions.fromString("rwx------"))) {
            throw new IOException("Rootfs staging parent must be a real private directory");
        }
        Path stage = parent.resolve("rootfs-" + UUID.randomUUID());
        Files.createDirectory(stage, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        posix.syncDirectory(parent);
        Path archive = stage.resolve("verified-input.tar.gz");
        Path root = stage.resolve("root");
        // Keep the same private file descriptor for copy, authentication and extraction.
        try (FileChannel snapshot = FileChannel.open(archive, StandardOpenOption.CREATE_NEW,
                StandardOpenOption.READ, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
            posix.chmod(archive, 0600);
            MessageDigest digest = sha256();
            byte[] block = new byte[65536];
            long received = 0;
            for (int count; (count = input.read(block)) != -1;) {
                interrupted();
                if (count == 0) continue;
                if (count > spec.compressedBytes - received) throw new IOException("Rootfs download exceeds trusted size");
                digest.update(block, 0, count);
                ByteBuffer bytes = ByteBuffer.wrap(block, 0, count);
                while (bytes.hasRemaining()) snapshot.write(bytes);
                received += count;
            }
            if (received != spec.compressedBytes || !hex(digest.digest()).equals(spec.sha256)) {
                throw new IOException("Rootfs archive authentication failed");
            }
            snapshot.force(true);
            posix.syncDirectory(stage);
            Files.createDirectory(root, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            snapshot.position(0);
            validateTarFraming(new FilterInputStream(Channels.newInputStream(snapshot)) {
                @Override public void close() { /* snapshot belongs to outer scope */ }
            }, spec);
            snapshot.position(0);
            extract(Channels.newInputStream(snapshot), root, spec, posix);
        }
        // The receipt is durable before the caller can move into later installation states.
        Path receipt = stage.resolve("extracted.sha256");
        try (FileChannel out = FileChannel.open(receipt, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            ByteBuffer bytes = ByteBuffer.wrap((spec.sha256 + "\n" + posix.storageBackend() + "\n").getBytes(java.nio.charset.StandardCharsets.US_ASCII));
            while (bytes.hasRemaining()) out.write(bytes);
            out.force(true);
        }
        posix.syncDirectory(stage);
        return new Prepared(stage, root, spec);
    }

    private static void extract(InputStream compressed, Path root, Spec spec, Posix posix) throws IOException {
        Map<String, Entry> entries = new HashMap<>();
        List<Entry> links = new ArrayList<>();
        long payload = 0;
        try (TarArchiveInputStream tar = new TarArchiveInputStream(
                new BoundedInput(new GZIPInputStream(compressed), spec.maxTarBytes), "UTF-8")) {
            TarArchiveEntry raw;
            byte[] block = new byte[65536];
            while ((raw = tar.getNextEntry()) != null) {
                interrupted();
                String name = memberName(raw.getName());
                char type = raw.isDirectory() ? 'd' : raw.isSymbolicLink() ? 's' : raw.isLink() ? 'h' : raw.isFile() ? 'f' : '?';
                if (!raw.isCheckSumOK() || raw.isSparse() || !tar.canReadEntryData(raw)
                        || type == '?' || (!name.isEmpty() && name.length() > 4096)
                        || (name.isEmpty() && type != 'd') || raw.getSize() < 0
                        || (type != 'f' && raw.getSize() != 0)) throw new IOException("Unsupported rootfs archive member");
                if (entries.size() >= spec.members || entries.containsKey(name)) throw new IOException("Duplicate or excess rootfs member");
                Entry entry = new Entry(name, raw, type);
                entries.put(name, entry);
                Path target = root.resolve(name);
                ensureDirectories(root, target.getParent());
                if (type == 'd') {
                    ensureDirectories(root, target);
                } else if (type == 's' || type == 'h') {
                    links.add(entry);
                } else {
                    if (raw.getSize() > spec.payloadBytes - payload) throw new IOException("Rootfs payload exceeds trusted size");
                    try (FileChannel out = FileChannel.open(target, StandardOpenOption.CREATE_NEW,
                            StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                        long copied = 0;
                        for (int count; (count = tar.read(block)) != -1;) {
                            interrupted();
                            ByteBuffer bytes = ByteBuffer.wrap(block, 0, count);
                            while (bytes.hasRemaining()) out.write(bytes);
                            copied += count;
                        }
                        if (copied != raw.getSize()) throw new IOException("Truncated rootfs member");
                        Files.setLastModifiedTime(target, entry.modified);
                        posix.chmod(target, entry.mode);
                        out.force(true);
                    }
                    payload += raw.getSize();
                }
            }
        }
        if (entries.size() != spec.members || payload != spec.payloadBytes) throw new IOException("Rootfs manifest totals differ");
        // Require every implicit directory in the archive; a link can never replace one.
        for (Entry entry : entries.values()) {
            String parent = entry.name;
            while (!parent.isEmpty()) {
                int slash = parent.lastIndexOf('/');
                parent = slash < 0 ? "" : parent.substring(0, slash);
                Entry ancestor = entries.get(parent);
                if (ancestor == null || ancestor.type != 'd') throw new IOException("Rootfs member traverses a link or undeclared directory");
            }
        }
        Map<Path, List<Path>> hardlinkGroups = new java.util.LinkedHashMap<>();
        for (Entry entry : links) {
            if (entry.type != 'h') continue;
            String sourceName = memberName(entry.link);
            Entry source = entries.get(sourceName);
            if (source == null || source.type != 'f' || source.mode != entry.mode || !source.modified.equals(entry.modified))
                throw new IOException("Invalid rootfs hardlink target");
            hardlinkGroups.computeIfAbsent(root.resolve(sourceName), ignored -> new ArrayList<>()).add(root.resolve(entry.name));
        }
        posix.createHardlinks(root, hardlinkGroups);
        for (Entry entry : links) {
            interrupted();
            Path target = root.resolve(entry.name);
            if (entry.type == 'h') {
                // Materialized by the declared storage backend above.
            } else {
                validateGuestSymlink(entry.name, entry.link);
                Files.createSymbolicLink(target, java.nio.file.Paths.get(entry.link));
                posix.setSymlinkModified(target, entry.modified);
            }
        }
        // Final modes (including sticky bits) and directory metadata are synchronized
        // bottom-up, after all entries are in place. No chown or device nodes on Android.
        List<Entry> directories = new ArrayList<>();
        for (Entry entry : entries.values()) if (entry.type == 'd') directories.add(entry);
        directories.sort(Comparator.comparingInt((Entry entry) -> entry.name.length()).reversed());
        for (Entry entry : directories) {
            Path directory = root.resolve(entry.name);
            // Open before applying 0000/0111: their owner may no longer open
            // this directory for reading afterwards, but its existing fd can
            // still flush the final mode and mtime without altering them.
            try (FileChannel channel = FileChannel.open(directory,
                    StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                Files.setLastModifiedTime(directory, entry.modified);
                posix.chmod(directory, entry.mode);
                channel.force(true);
            }
        }
    }

    private static void ensureDirectories(Path root, Path directory) throws IOException {
        if (directory == null || !directory.startsWith(root)) {
            // The archive's sole root entry has the staging directory as its parent.
            if (directory != null && directory.equals(root.getParent())) return;
            throw new IOException("Rootfs path leaves staging root");
        }
        Path current = root;
        for (Path part : root.relativize(directory)) {
            current = current.resolve(part);
            try { Files.createDirectory(current); }
            catch (java.nio.file.FileAlreadyExistsException exists) {
                if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Rootfs parent is not a directory");
            }
        }
    }

    private static String memberName(String input) throws IOException {
        if (input == null || input.startsWith("/") || input.indexOf('\\') >= 0 || input.indexOf('\0') >= 0) throw new IOException("Invalid rootfs path");
        if (input.equals("./")) return "";
        while (input.startsWith("./")) input = input.substring(2);
        if (input.equals(".")) return "";
        if (input.endsWith("/")) input = input.substring(0, input.length() - 1);
        if (input.isEmpty()) throw new IOException("Empty rootfs path");
        for (String part : input.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals("..")) throw new IOException("Ambiguous rootfs path");
        return input;
    }

    private static void validateGuestSymlink(String name, String target) throws IOException {
        if (target == null || target.isEmpty() || target.length() > 4096 || target.indexOf('\0') >= 0 || target.indexOf('\\') >= 0) throw new IOException("Invalid guest symlink");
        ArrayDeque<String> components = new ArrayDeque<>();
        if (!target.startsWith("/")) {
            int slash = name.lastIndexOf('/');
            if (slash >= 0) for (String part : name.substring(0, slash).split("/")) components.add(part);
        }
        for (String part : target.split("/")) {
            if (part.isEmpty() || part.equals(".")) continue;
            if (part.equals("..")) {
                if (components.isEmpty()) throw new IOException("Guest symlink traverses above guest root");
                components.removeLast();
            } else components.addLast(part);
        }
    }

    private static final class BoundedInput extends FilterInputStream {
        private long remaining;
        BoundedInput(InputStream input, long remaining) { super(input); this.remaining = remaining; }
        @Override public int read() throws IOException {
            int value = in.read();
            if (value >= 0 && --remaining < 0) throw new IOException("Rootfs tar exceeds trusted limit");
            return value;
        }
        @Override public int read(byte[] bytes, int offset, int length) throws IOException {
            int count = in.read(bytes, offset, (int)Math.min(length, Math.min(Integer.MAX_VALUE, remaining + 1)));
            if (count > 0 && (remaining -= count) < 0) throw new IOException("Rootfs tar exceeds trusted limit");
            return count;
        }
        @Override public long skip(long count) throws IOException {
            byte[] block = new byte[(int)Math.min(8192, Math.max(1, count))];
            long skipped = 0;
            while (skipped < count) {
                int read = read(block, 0, (int)Math.min(block.length, count - skipped));
                if (read < 0) break;
                skipped += read;
            }
            return skipped;
        }
    }

    /** Commons Compress accepts a bare EOF in place of tar's terminal blocks.
     * Validate the fixed POSIX-tar framing first, including the gzip CRC/trailer,
     * while leaving semantic PAX/path interpretation to the maintained parser.
     */
    private static void validateTarFraming(InputStream compressed, Spec spec) throws IOException {
        try (InputStream raw = new BoundedInput(new GZIPInputStream(compressed), spec.maxTarBytes)) {
            byte[] header = new byte[512], block = new byte[65536];
            long headers = 0;
            while (true) {
                readExact(raw, header, 512);
                if (allZero(header, 512)) {
                    readExact(raw, header, 512);
                    if (!allZero(header, 512)) throw new IOException("Missing second terminal tar block");
                    for (int count; (count = raw.read(block)) != -1;)
                        if (!allZero(block, count)) throw new IOException("Data follows terminal tar blocks");
                    return;
                }
                if (++headers > 2L * spec.members + 1) throw new IOException("Excess tar framing records");
                long checksum = 0;
                for (int i = 0; i < 512; i++) checksum += i >= 148 && i < 156 ? 32 : header[i] & 255;
                if (checksum != octal(header, 148, 8)) throw new IOException("Invalid tar header checksum");
                if (header[257] != 'u' || header[258] != 's' || header[259] != 't' || header[260] != 'a'
                        || header[261] != 'r' || header[262] != 0 || header[263] != '0' || header[264] != '0')
                    throw new IOException("Expected POSIX ustar/PAX archive");
                long size = octal(header, 124, 12);
                int type = header[156];
                if (type != 0 && type != '0' && type != '1' && type != '2' && type != '5' && type != 'x')
                    throw new IOException("Unsupported tar framing type");
                if (type == 'x' && size > 65536) throw new IOException("Oversized PAX metadata");
                if (size > spec.maxTarBytes) throw new IOException("Oversized tar member");
                for (long remaining = size; remaining > 0;) {
                    int count = (int)Math.min(remaining, block.length);
                    readExact(raw, block, count);
                    remaining -= count;
                }
                int padding = (int)((512 - size % 512) % 512);
                readExact(raw, header, padding);
                if (!allZero(header, padding)) throw new IOException("Nonzero tar entry padding");
            }
        }
    }

    private static long octal(byte[] bytes, int offset, int size) throws IOException {
        long result = 0;
        boolean ended = false, digit = false;
        for (int i = offset; i < offset + size; i++) {
            int value = bytes[i] & 255;
            if (value == 0 || value == ' ') { if (digit || value == 0) ended = true; continue; }
            if (ended || value < '0' || value > '7' || result > (Long.MAX_VALUE - 7) / 8)
                throw new IOException("Invalid tar numeric field");
            digit = true;
            result = result * 8 + value - '0';
        }
        return result;
    }

    private static void readExact(InputStream input, byte[] bytes, int length) throws IOException {
        int received = 0;
        while (received < length) {
            interrupted();
            int count = input.read(bytes, received, length - received);
            if (count < 0) throw new java.io.EOFException("Truncated tar framing");
            received += count;
        }
    }

    private static boolean allZero(byte[] bytes, int length) {
        for (int i = 0; i < length; i++) if (bytes[i] != 0) return false;
        return true;
    }

    private static MessageDigest sha256() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }
    private static void interrupted() throws IOException {
        if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException("Rootfs preparation interrupted");
    }
}
