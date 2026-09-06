package app.foldgpt.install;

import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.FileDescriptor;
import java.io.IOException;
import java.nio.file.Path;

/** Android entry point; identities come from the running app, never a device fixture. */
public final class AndroidGuestAccountProvisioner {
    private AndroidGuestAccountProvisioner() {}
    public static GuestIdentity prepare(RootfsTransaction transaction) throws IOException {
        return GuestAccountProvisioner.prepare(transaction,new Storage(),android.os.Process.myUid(),Os.getgid());
    }
    private static final class Storage implements GuestAccountProvisioner.Storage {
        public String identity(Path path) throws IOException {
            try {
                StructStat stat=Os.lstat(path.toString());
                if(stat.st_uid!=android.os.Process.myUid() || !OsConstants.S_ISDIR(stat.st_mode))
                    throw new IOException("Guest account root must be an owned directory");
                return Long.toUnsignedString(stat.st_dev)+":"+Long.toUnsignedString(stat.st_ino);
            } catch(ErrnoException error) { throw new IOException("Guest root identity failed",error); }
        }
        public long linkCount(Path path) throws IOException {
            try { return Os.lstat(path.toString()).st_nlink; }
            catch(ErrnoException error) { throw new IOException("Guest metadata link inspection failed",error); }
        }
        public void syncDirectory(Path path) throws IOException {
            FileDescriptor fd=null;
            try {
                fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
                StructStat stat=Os.fstat(fd);
                if(stat.st_uid!=android.os.Process.myUid() || !OsConstants.S_ISDIR(stat.st_mode))
                    throw new IOException("Guest account sync requires an owned directory");
                Os.fsync(fd);
            } catch(ErrnoException error) { throw new IOException("Guest account directory sync failed",error); }
            finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Guest account directory close failed",error); } }
        }
    }
}
