package app.foldgpt.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;

/** Android's public Java filesystem API cannot set a symlink's timestamp.
 * This JNI operation calls real utimensat with AT_SYMLINK_NOFOLLOW. It is
 * only used inside the exclusive, inactive, installer-owned staging tree. */
final class NativeInstallFiles {
    static { System.loadLibrary("foldgpt-install"); }
    private NativeInstallFiles() {}
    static void setSymlinkModified(Path path, FileTime modified) throws IOException {
        java.time.Instant instant = modified.toInstant();
        int error = setLinkTime(path.getParent().toString().getBytes(StandardCharsets.UTF_8),
                path.getFileName().toString().getBytes(StandardCharsets.UTF_8),
                instant.getEpochSecond(), instant.getNano());
        if (error != 0) throw new IOException("Installer symlink timestamp failed, errno=" + error);
    }
    private static native int setLinkTime(byte[] parent, byte[] name, long seconds, int nanos);
}
