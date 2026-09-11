package app.foldgpt.install;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.FileDescriptor;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Path;

/** Acquisition adapter only; callers retain normal installation sequencing. */
public final class AndroidTrustedHttpsArtifact {
    private AndroidTrustedHttpsArtifact() {}
    public static TrustedHttpsArtifact.Result acquireClient(Context context,AndroidInactiveClientInstaller.Descriptor client,
            TrustedHttpsArtifact.Options options,TrustedHttpsArtifact.Cancellation cancellation,
            TrustedHttpsArtifact.Progress progress) throws Exception {
        // Read the source already declared by the official-client component.
        // Do not invent a second endpoint or derive trust from the response.
        TrustedHttpsArtifact.Descriptor input=new TrustedHttpsArtifact.Descriptor(
            URI.create(client.json().getString("sourceUrl")),client.bytes,client.sha256);
        return TrustedHttpsArtifact.acquire(context.getCacheDir().toPath(),input,options,cancellation,progress,new Storage());
    }
    private static final class Storage implements TrustedHttpsArtifact.Storage {
        private StructStat stat(Path path) throws IOException {
            try {
                StructStat value=Os.lstat(path.toString());
                if(value.st_uid!=android.os.Process.myUid()) throw new IOException("Acquisition cache path is not Android-app-owned");
                return value;
            } catch(ErrnoException error) { throw new IOException("Acquisition cache lstat failed",error); }
        }
        public String identity(Path path) throws IOException {
            return identity(stat(path));
        }
        private String identity(StructStat value) { return Long.toUnsignedString(value.st_dev)+":"+Long.toUnsignedString(value.st_ino); }
        public long linkCount(Path path) throws IOException { return stat(path).st_nlink; }
        public int mode(Path path) throws IOException { return stat(path).st_mode&07777; }
        public void finishCreatedDirectory(Path path,String expectedIdentity) throws IOException {
            FileDescriptor fd=null;
            try {
                fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
                StructStat before=Os.fstat(fd);
                if(!OsConstants.S_ISDIR(before.st_mode) || before.st_uid!=android.os.Process.myUid()
                        || !expectedIdentity.equals(identity(before)) || (before.st_mode&07777&~02700)!=0)
                    throw new IOException("New acquisition directory identity, owner or initial mode differs");
                // Android's managed cache may be setgid. mkdir(0700) can then
                // create 2700; normalize only the exact newly created inode.
                Os.fchmod(fd,0700);
                StructStat after=Os.fstat(fd),named=stat(path);
                if(!expectedIdentity.equals(identity(after)) || !expectedIdentity.equals(identity(named))
                        || after.st_uid!=before.st_uid || after.st_gid!=before.st_gid
                        || (after.st_mode&07777)!=0700 || (named.st_mode&07777)!=0700)
                    throw new IOException("New acquisition directory private mode was not retained");
                Os.fsync(fd);
            } catch(ErrnoException error) { throw new IOException("New acquisition directory finalization failed",error); }
            finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("New acquisition directory close failed",error); } }
        }
        public void syncDirectory(Path path) throws IOException {
            FileDescriptor fd=null;
            try {
                fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
                StructStat value=Os.fstat(fd);
                if(!OsConstants.S_ISDIR(value.st_mode) || value.st_uid!=android.os.Process.myUid())
                    throw new IOException("Acquisition sync target is not an owned directory");
                Os.fsync(fd);
            } catch(ErrnoException error) { throw new IOException("Acquisition directory sync failed",error); }
            finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Acquisition directory close failed",error); } }
        }
    }
}
