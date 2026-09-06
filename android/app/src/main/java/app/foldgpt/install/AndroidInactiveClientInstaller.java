package app.foldgpt.install;

import android.content.Context;
import android.system.*;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.*;
import java.util.*;
import org.json.JSONObject;

/** One actual official-client package step under the caller's PREPARED lease.
 * Never opens a new transaction, changes account/vault journals, starts a client,
 * activates a root or installs APKs. Source hashes are trusted coordinator inputs.
 */
public final class AndroidInactiveClientInstaller {
    private AndroidInactiveClientInstaller() {}
    public static final class Descriptor {
        public final String version,sha256;
        public final long bytes,maxTarBytes;
        public final int maxMembers;
        public Descriptor(String version,String sha256,long bytes,long maxTarBytes,int maxMembers) throws IOException {
            if(version==null || !version.matches("[0-9][A-Za-z0-9.+:~\\-]*") || sha256==null
                    || !sha256.matches("[0-9a-f]{64}") || bytes<=0 || maxTarBytes<=0 || maxMembers<=0)
                throw new IOException("Authenticated official client descriptor is required");
            this.version=version; this.sha256=sha256; this.bytes=bytes; this.maxTarBytes=maxTarBytes; this.maxMembers=maxMembers;
        }
        JSONObject json() throws Exception {
            return new JSONObject().put("format","foldgpt.official-client-input.v1")
                .put("sourceUrl","https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_arm64.deb")
                .put("sourceDocument","https://learn.chatgpt.com/docs/linux/linux-app").put("package","chatgpt")
                .put("architecture","arm64").put("version",version).put("sha256",sha256).put("bytes",bytes)
                .put("maxTarBytes",maxTarBytes).put("maxMembers",maxMembers);
        }
    }
    public static final class Result {
        public final Path root,report,diagnosticWork;
        public final String rootIdentity,packageSha256,reportSha256;
        private Result(Path root,Path report,Path work,String identity,String packageSha,String reportSha) {
            this.root=root; this.report=report; diagnosticWork=work; rootIdentity=identity;
            packageSha256=packageSha; reportSha256=reportSha;
        }
    }
    public static Result install(Context context,RootfsTransaction transaction,String installationId,Descriptor descriptor,
            Path packageSource,Path verifierSource,String verifierSha256,Path installerSource,String installerSha256,
            long timeoutMillis) throws Exception {
        Objects.requireNonNull(context); Objects.requireNonNull(transaction); Objects.requireNonNull(descriptor);
        if(installationId==null || !installationId.matches("[0-9a-f]{64}") || timeoutMillis<=0 || timeoutMillis>Integer.MAX_VALUE)
            throw new IOException("Bound coordinator identity and deadline required");
        synchronized(transaction) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Client install requires inactive PREPARED lease");
            Path root=transaction.prepare(() -> { throw new IOException("Client install cannot extract a base"); }).root;
            String rootIdentity=identity(root);
            GuestIdentity account=GuestIdentity.load(root);
            if(account.uid!=android.os.Process.myUid() || account.gid!=Os.getgid()) throw new IOException("Guest/Android account identity differs");
            Path cache=context.getCacheDir().toPath(); ownedDirectory(cache,false);
            Path work=Files.createTempDirectory(cache,"ci-",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            for(String name:List.of("input","tmp","shm","native")) {
                Files.createDirectory(work.resolve(name),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
                ownedDirectory(work.resolve(name),true);
            }
            Path input=work.resolve("input");
            copyVerified(verifierSource,input.resolve("official_client_package.py"),verifierSha256,1048576,-1,true);
            copyVerified(installerSource,input.resolve("install_official_client.py"),installerSha256,1048576,-1,true);
            Path archive=packageSource;
            if(archive==null) {
                archive=root;
                for(String name:List.of("var","lib","foldgpt","client-install","input")) { archive=archive.resolve(name); ownedDirectory(archive,false); }
                archive=archive.resolve("package.deb");
            }
            copyVerified(archive,input.resolve("package.deb"),descriptor.sha256,descriptor.bytes,descriptor.bytes,false);
            writeNew(input.resolve("descriptor.json"),(descriptor.json().toString()+"\n").getBytes(StandardCharsets.UTF_8));
            sync(input); sync(work);
            Path nativeDirectory=Path.of(context.getApplicationInfo().nativeLibraryDir);
            for(String name:List.of("libproot.so","libproot-loader.so","libproot-loader32.so","libtalloc.so","libandroid-shmem.so")) {
                if(!Files.isRegularFile(nativeDirectory.resolve(name),LinkOption.NOFOLLOW_LINKS))
                    throw new IOException("Android-verified APK native installation component is missing");
            }
            Files.createSymbolicLink(work.resolve("native/libtalloc.so.2"),nativeDirectory.resolve("libtalloc.so"));
            String output=InactiveClientInstallCommand.run(InactiveClientInstallCommand.create(nativeDirectory,root,work,
                installationId,rootIdentity,timeoutMillis),timeoutMillis,work.resolve("runner.log"),Process::destroy);
            String receipt=null;
            for(String line:output.split("\n")) if(line.startsWith("FOLDGPT_CLIENT_RECEIPT=")) {
                if(receipt!=null) throw new IOException("Duplicate inactive client receipt");
                receipt=line.substring("FOLDGPT_CLIENT_RECEIPT=".length());
            }
            String[] fields=receipt==null?new String[0]:receipt.split("\t",-1);
            if(fields.length!=4 || !fields[0].equals(descriptor.sha256) || !fields[1].equals(descriptor.version)
                    || !fields[2].equals(rootIdentity) || !fields[3].matches("[0-9a-f]{64}"))
                throw new IOException("Missing or mismatching inactive client receipt");
            Path report=root;
            for(String name:List.of("var","lib","foldgpt","client-install")) { report=report.resolve(name); ownedDirectory(report,false); }
            report=report.resolve("report.json");
            byte[] data=readOwned(report,1048576);
            if(!hash(data).equals(fields[3])) throw new IOException("Client receipt differs from durable report bytes");
            JSONObject evidence=new JSONObject(new String(data,StandardCharsets.UTF_8));
            JSONObject installed=evidence.getJSONObject("installed");
            if(!evidence.getString("format").equals("foldgpt.inactive-client-install.v1")
                    || !evidence.getString("scope").equals("configured-client-package-only")
                    || !evidence.getString("rootIdentity").equals(rootIdentity)
                    || !evidence.getString("installationId").equals(installationId)
                    || !evidence.getJSONObject("descriptor").getString("sha256").equals(descriptor.sha256)
                    || !installed.getString("version").equals(descriptor.version) || !installed.getString("architecture").equals("arm64")
                    || !installed.getString("status").equals("install ok installed") || !evidence.getBoolean("basePackagesUnchanged"))
                throw new IOException("Inactive client report identity or package scope differs");
            GuestIdentity after=GuestIdentity.load(root);
            if(!after.user.equals(account.user) || after.uid!=account.uid || after.gid!=account.gid || !after.home.equals(account.home)
                    || !identity(root).equals(rootIdentity) || transaction.state()!=RootfsTransaction.State.PREPARED)
                throw new IOException("Inactive installation or guest identity changed");
            transaction.prepare(() -> { throw new IOException("Client verification cannot extract a base"); });
            return new Result(root,report,work,rootIdentity,descriptor.sha256,fields[3]);
        }
    }
    private static void copyVerified(Path source,Path target,String expected,long limit,long exact,boolean text) throws Exception {
        if(expected==null || !expected.matches("[0-9a-f]{64}")) throw new IOException("Installer source requires trusted SHA-256");
        StructStat before=regular(source);
        MessageDigest digest=MessageDigest.getInstance("SHA-256"); long count=0;
        try(FileChannel input=FileChannel.open(source,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS);
                FileChannel output=FileChannel.open(target,Set.of(StandardOpenOption.WRITE,StandardOpenOption.CREATE_NEW,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer buffer=ByteBuffer.allocate(65536);
            while(input.read(buffer)!=-1) {
                buffer.flip(); count+=buffer.remaining();
                if(count>limit) throw new IOException("Installer source exceeds authenticated bound");
                if(text) for(int index=0;index<buffer.limit();index++) if(buffer.get(index)==0 || buffer.get(index)=='\r')
                    throw new IOException("Installer sources must use canonical LF without NUL");
                digest.update(buffer.asReadOnlyBuffer()); while(buffer.hasRemaining()) output.write(buffer); buffer.clear();
            }
            output.force(true);
        }
        StructStat after=regular(source);
        if(before.st_dev!=after.st_dev || before.st_ino!=after.st_ino || before.st_size!=after.st_size
                || count==0 || exact>=0 && count!=exact || !hex(digest.digest()).equals(expected))
            throw new IOException("Installer source identity, size or digest differs");
    }
    private static void writeNew(Path path,byte[] value) throws IOException {
        try(FileChannel channel=FileChannel.open(path,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer data=ByteBuffer.wrap(value); while(data.hasRemaining()) channel.write(data); channel.force(true);
        }
    }
    private static byte[] readOwned(Path path,int limit) throws IOException {
        regular(path);
        try(InputStream stream=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] data=stream.readNBytes(limit+1); if(data.length>limit) throw new IOException("Inactive client report too large"); return data;
        }
    }
    private static StructStat regular(Path path) throws IOException {
        try { StructStat info=Os.lstat(path.toString());
            if(!OsConstants.S_ISREG(info.st_mode) || info.st_uid!=android.os.Process.myUid() || info.st_nlink!=1)
                throw new IOException("Installer input must be a single app-owned regular file"); return info;
        } catch(ErrnoException error) { throw new IOException("Installer source stat failed",error); }
    }
    private static void ownedDirectory(Path path,boolean privatePath) throws IOException {
        try { StructStat info=Os.lstat(path.toString());
            if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid()
                    || (info.st_mode & (privatePath?0077:0002))!=0 || (info.st_mode&0020)!=0 && info.st_gid!=Os.getgid())
                throw new IOException("Installer directory ownership or permissions differ");
        } catch(ErrnoException error) { throw new IOException("Installer directory stat failed",error); }
    }
    private static String identity(Path path) throws IOException {
        ownedDirectory(path,false);
        try { StructStat info=Os.lstat(path.toString()); return Long.toUnsignedString(info.st_dev)+":"+Long.toUnsignedString(info.st_ino); }
        catch(ErrnoException error) { throw new IOException("Installer root identity failed",error); }
    }
    private static void sync(Path path) throws IOException {
        FileDescriptor fd=null;
        try { fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0); Os.fsync(fd); }
        catch(ErrnoException error) { throw new IOException("Installer input directory synchronization failed",error); }
        finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Installer sync descriptor close failed",error); } }
    }
    private static String hash(byte[] data) throws Exception { return hex(MessageDigest.getInstance("SHA-256").digest(data)); }
    private static String hex(byte[] data) { StringBuilder value=new StringBuilder(); for(byte item:data) value.append(String.format(Locale.ROOT,"%02x",item&255)); return value.toString(); }
}
