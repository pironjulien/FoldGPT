package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.FileTime;
import java.util.*;

/** Explicit storage ABI of the pinned Termux PRoot link2symlink extension.
 * This is shared guest file storage, not native hardlinks and not isolation.
 * Used only before activation in an exclusive stage whose absolute path will
 * not change. An incomplete conversion has no receipt and is reclaimed by the
 * transaction. Never silently substitute this backend after native link fails. */
final class ProotHardlinkStorage {
    static final String BACKEND = "proot-termux-l2s-7266fb3-v1";
    private ProotHardlinkStorage() {}
    static void create(Path root, Map<Path, List<Path>> groups, RootfsExtractor.Posix posix) throws IOException {
        create(root, groups, posix, name -> {});
    }
    interface Checkpoint { void at(String name) throws IOException; }
    static void create(Path root, Map<Path, List<Path>> groups, RootfsExtractor.Posix posix,
                       Checkpoint checkpoint) throws IOException {
        if (!root.equals(root.toRealPath())) throw new IOException("PRoot storage requires immutable canonical root");
        Set<Path> reserved = new HashSet<>();
        for (Map.Entry<Path, List<Path>> group : groups.entrySet()) {
            Path source = group.getKey();
            if (!source.startsWith(root) || !Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)
                    || group.getValue().isEmpty() || group.getValue().size() >= 9999)
                throw new IOException("Invalid PRoot hardlink group");
            Path intermediate = intermediate(source), data = data(source, group.getValue().size() + 1);
            for (Path output : concat(group.getValue(), intermediate, data)) {
                if (!output.startsWith(root) || !reserved.add(output) || Files.exists(output, LinkOption.NOFOLLOW_LINKS))
                    throw new IOException("PRoot hardlink storage conflicts with archive path");
            }
        }
        for (Map.Entry<Path, List<Path>> group : groups.entrySet()) {
            if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException();
            Path source = group.getKey(), intermediate = intermediate(source);
            Path data = data(source, group.getValue().size() + 1);
            FileTime modified = Files.getLastModifiedTime(source, LinkOption.NOFOLLOW_LINKS);
            // The backing file keeps its actual inode, bytes, mode and mtime.
            // No file bytes are copied and no guest operation is fabricated.
            Files.move(source, data, StandardCopyOption.ATOMIC_MOVE);
            checkpoint.at("backing-moved");
            Files.createSymbolicLink(intermediate, data);
            checkpoint.at("intermediate-created");
            Files.createSymbolicLink(source, intermediate);
            posix.setSymlinkModified(source, modified);
            checkpoint.at("source-created");
            Set<Path> parents = new HashSet<>();
            parents.add(source.getParent());
            for (Path alias : group.getValue()) {
                Files.createSymbolicLink(alias, intermediate);
                posix.setSymlinkModified(alias, modified);
                checkpoint.at("alias-created");
                parents.add(alias.getParent());
            }
            for (Path directory : parents) posix.syncDirectory(directory);
            checkpoint.at("group-synced");
        }
    }
    static Path intermediate(Path source) {
        return source.resolveSibling(".l2s." + source.getFileName() + "0001");
    }
    static Path data(Path source, int count) {
        return source.resolveSibling(intermediate(source).getFileName() + String.format(Locale.ROOT, ".%04d", count));
    }
    private static List<Path> concat(List<Path> aliases, Path intermediate, Path data) {
        List<Path> paths = new ArrayList<>(aliases); paths.add(intermediate); paths.add(data); return paths;
    }
}
