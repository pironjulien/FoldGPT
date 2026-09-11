package app.foldgpt.install;

import android.system.*;
import java.io.*;
import java.nio.file.*;

/** Native Android adapter. Caller retains the same PREPARED coordinator lease.
 * Authenticating the release input is mandatory even on a completed retry. */
public final class AndroidInactiveIntegrationInstaller {
    private AndroidInactiveIntegrationInstaller() {}
    public static InactiveIntegrationInstaller.Result install(RootfsTransaction transaction,String installationId,
            InputStream bundleSource,String independentlyTrustedSha256,long independentlyTrustedBytes) throws IOException {
        InactiveIntegrationBundle bundle=InactiveIntegrationBundle.read(bundleSource,independentlyTrustedSha256,independentlyTrustedBytes);
        return installVerified(transaction,installationId,bundle);
    }
    static InactiveIntegrationInstaller.Result installVerified(RootfsTransaction transaction,String installationId,
            InactiveIntegrationBundle bundle) throws IOException {
        synchronized(transaction) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Integration requires an inactive lease");
            Path root=transaction.prepare(() -> { throw new IOException("Integration must not extract a base"); }).root;
            GuestIdentity account=GuestIdentity.load(root);
            if(account.uid!=android.os.Process.myUid() || account.gid!=Os.getgid()) throw new IOException("Guest and native Android identities differ");
            return InactiveIntegrationInstaller.install(transaction,new NativeStorage(),installationId,bundle);
        }
    }
    private static final class NativeStorage implements InactiveIntegrationInstaller.Storage {
        private StructStat stat(Path path) throws IOException {
            try {
                StructStat value=Os.lstat(path.toString());
                if(value.st_uid!=android.os.Process.myUid()) throw new IOException("Integration path is not Android-app-owned");
                return value;
            } catch(ErrnoException error) { throw new IOException("Native integration lstat failed",error); }
        }
        public String identity(Path path) throws IOException { StructStat value=stat(path); return Long.toUnsignedString(value.st_dev)+":"+Long.toUnsignedString(value.st_ino); }
        public long linkCount(Path path) throws IOException { return stat(path).st_nlink; }
        public int mode(Path path) throws IOException { return stat(path).st_mode; }
        public void syncDirectory(Path path) throws IOException {
            FileDescriptor fd=null;
            try {
                fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
                StructStat value=Os.fstat(fd);
                if(!OsConstants.S_ISDIR(value.st_mode) || value.st_uid!=android.os.Process.myUid()) throw new IOException("Integration sync requires an owned directory");
                Os.fsync(fd);
            } catch(ErrnoException error) { throw new IOException("Native integration directory sync failed",error); }
            finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Native integration descriptor close failed",error); } }
        }
    }
}
