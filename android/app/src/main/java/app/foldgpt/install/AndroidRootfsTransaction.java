package app.foldgpt.install;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.FileDescriptor;
import java.io.IOException;
import java.nio.file.Path;

/** Android adapter. Opening/preparing does not start Linux, make keys, install
 * the official client or publish files/debian. Keep the returned lease through
 * separate trusted provisioning and explicit activation validation. */
public final class AndroidRootfsTransaction {
    private AndroidRootfsTransaction() {}

    public static RootfsTransaction open(Context context, RootfsExtractor.Spec spec) throws IOException {
        return RootfsTransaction.open(context.getFilesDir().toPath(), spec, new Posix());
    }

    private static final class Posix implements RootfsTransaction.Posix {
        @Override public String storageBackend() { return ProotHardlinkStorage.BACKEND; }
        @Override public void createHardlinks(Path root, java.util.Map<Path, java.util.List<Path>> groups) throws IOException {
            ProotHardlinkStorage.create(root, groups, this);
        }
        @Override public void setSymlinkModified(Path path, java.nio.file.attribute.FileTime modified) throws IOException {
            NativeInstallFiles.setSymlinkModified(path, modified);
        }
        @Override public void chmod(Path path, int mode) throws IOException {
            try {
                StructStat stat = Os.lstat(path.toString());
                if (stat.st_uid != android.os.Process.myUid() || OsConstants.S_ISLNK(stat.st_mode))
                    throw new IOException("Refusing chmod of foreign or linked installer path");
                Os.chmod(path.toString(), mode);
            } catch (ErrnoException error) { throw new IOException("Installer chmod failed", error); }
        }
        @Override public void syncDirectory(Path path) throws IOException {
            FileDescriptor fd = null;
            try {
                fd = Os.open(path.toString(), OsConstants.O_RDONLY | OsConstants.O_NONBLOCK | OsConstants.O_NOFOLLOW | OsConstants.O_CLOEXEC, 0);
                StructStat stat = Os.fstat(fd);
                if (stat.st_uid != android.os.Process.myUid() || !OsConstants.S_ISDIR(stat.st_mode))
                    throw new IOException("Installer sync target is not an owned directory");
                Os.fsync(fd);
            } catch (ErrnoException error) { throw new IOException("Installer directory sync failed", error); }
            finally {
                if (fd != null) try { Os.close(fd); } catch (ErrnoException error) { throw new IOException("Installer directory close failed", error); }
            }
        }
        @Override public String identity(Path path) throws IOException {
            try {
                StructStat stat = Os.lstat(path.toString());
                if (stat.st_uid != android.os.Process.myUid() || !OsConstants.S_ISDIR(stat.st_mode))
                    throw new IOException("Prepared root is not an owned directory");
                return Long.toUnsignedString(stat.st_dev) + ":" + Long.toUnsignedString(stat.st_ino);
            } catch (ErrnoException error) { throw new IOException("Prepared root identity failed", error); }
        }
        @Override public long linkCount(Path path) throws IOException {
            try { return Os.lstat(path.toString()).st_nlink; }
            catch (ErrnoException error) { throw new IOException("Installer file identity failed", error); }
        }
    }
}
