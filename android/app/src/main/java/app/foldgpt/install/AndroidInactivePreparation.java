package app.foldgpt.install;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import app.foldgpt.KeyringVault;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;

/** Concrete, deliberately INACTIVE coordinator: authenticated base -> local
 * account -> intact official client installation -> Android vault -> supervised
 * GNOME collection. No activation, display, client launch or model call occurs.
 * The explicitly named keyring-only diagnostic retains its earlier scope.
 * A result is not runtime
 * readiness. Keep the private data until the complete installer is implemented.
 */
public final class AndroidInactivePreparation {
    private AndroidInactivePreparation() {}
    public static final class Result {
        public final Path root;
        public final GuestIdentity account;
        public final String installationId,collectionInstallationId;
        /** Present only for prepare(..., ClientInput); never inferred from keyring-only evidence. */
        public final AndroidInactiveClientInstaller.Result client;
        private Result(Path root,GuestIdentity account,InactivePreparationJournal journal,AndroidInactiveClientInstaller.Result client) {
            this.root=root; this.account=account; installationId=journal.value("installationId");
            collectionInstallationId=journal.value("collectionInstallationId");
            this.client=client;
        }
    }
    /** Independently authenticated package/helper inputs. A null package path
     * means source-free recovery from this exact staged installation's ledger. */
    public static final class ClientInput {
        public final AndroidInactiveClientInstaller.Descriptor descriptor;
        public final Path packageSource,verifierSource,installerSource;
        public final String verifierSha256,installerSha256;
        public final long timeoutMillis;
        public ClientInput(AndroidInactiveClientInstaller.Descriptor descriptor,Path packageSource,
                Path verifierSource,String verifierSha256,Path installerSource,String installerSha256,long timeoutMillis) throws IOException {
            this.descriptor=Objects.requireNonNull(descriptor); this.packageSource=packageSource;
            this.verifierSource=Objects.requireNonNull(verifierSource); this.installerSource=Objects.requireNonNull(installerSource);
            if(verifierSha256==null || !verifierSha256.matches("[0-9a-f]{64}") || installerSha256==null
                    || !installerSha256.matches("[0-9a-f]{64}") || timeoutMillis<=0 || timeoutMillis>Integer.MAX_VALUE)
                throw new IOException("Authenticated client helpers and bounded deadline are required");
            this.verifierSha256=verifierSha256; this.installerSha256=installerSha256; this.timeoutMillis=timeoutMillis;
        }
        private String descriptorSha256() {
            String canonical="foldgpt.inactive-client-binding.v1\npackage=chatgpt\narchitecture=arm64\nversion="+descriptor.version
                +"\nsha256="+descriptor.sha256+"\nbytes="+descriptor.bytes+"\nmaxTarBytes="+descriptor.maxTarBytes
                +"\nmaxMembers="+descriptor.maxMembers+"\n";
            return InactivePreparationJournal.sha256(canonical.getBytes(StandardCharsets.US_ASCII));
        }
    }
    /** Source SHA values must come from the authenticated installer/package,
     * never a checksum supplied by the same unauthenticated download. Native
     * inputs are the current app's Android-verified installed APK libraries.
     * A probe Context must isolate files/cache/noBackup together. No alternate
     * Keystore alias is needed: its ciphertext is independent and never imports,
     * reads, replaces or deletes the production vault ciphertext or AES key.
     */
    public static Result prepare(Context context,RootfsExtractor.Spec spec,RootfsTransaction.ArchiveSource archive,
            Path initializerSource,String initializerSha256,Path supervisorSource,String supervisorSha256,ClientInput client) throws Exception {
        return prepareBound(context,spec,archive,initializerSource,initializerSha256,supervisorSource,supervisorSha256,
            Objects.requireNonNull(client,"Client-enabled preparation requires authenticated inputs"));
    }
    /** Retains the already tested v1 diagnostic and never installs a package.
     * It cannot resume or downgrade a journal made by the client-enabled path. */
    public static Result prepareKeyringOnly(Context context,RootfsExtractor.Spec spec,RootfsTransaction.ArchiveSource archive,
            Path initializerSource,String initializerSha256,Path supervisorSource,String supervisorSha256) throws Exception {
        return prepareBound(context,spec,archive,initializerSource,initializerSha256,supervisorSource,supervisorSha256,null);
    }
    private static Result prepareBound(Context context,RootfsExtractor.Spec spec,RootfsTransaction.ArchiveSource archive,
            Path initializerSource,String initializerSha256,Path supervisorSource,String supervisorSha256,ClientInput clientInput) throws Exception {
        Objects.requireNonNull(context); Objects.requireNonNull(spec); Objects.requireNonNull(archive);
        byte[] initializer=verifiedScript(initializerSource,initializerSha256);
        byte[] supervisor=verifiedScript(supervisorSource,supervisorSha256);
        if(clientInput!=null) {
            verifiedScript(clientInput.verifierSource,clientInput.verifierSha256);
            verifiedScript(clientInput.installerSource,clientInput.installerSha256);
        }
        Path files=context.getFilesDir().toPath(),noBackup=context.getNoBackupFilesDir().toPath();
        Storage storage=new Storage(); storage.managedDirectory(files); storage.managedDirectory(noBackup);
        Path nativeDirectory=Path.of(context.getApplicationInfo().nativeLibraryDir);
        String nativeDigest=nativeDescriptor(nativeDirectory);
        Path encrypted=noBackup.resolve("foldgpt-keyring/keyring-password.v1");
        Path pendingImport=noBackup.resolve("foldgpt-keyring/keyring-password.import");
        byte[] credential=null;
        try(RootfsTransaction transaction=AndroidRootfsTransaction.open(context,spec)) {
            RootfsTransaction.Prepared prepared=transaction.prepare(archive);
            if(prepared.state!=RootfsTransaction.State.PREPARED) throw new IOException("Inactive preparation refuses an activated transaction");
            Path root=prepared.root;
            // Retain one authoritative pathname. Different scope/schema cannot
            // evade the earlier intent by creating a second coordinator file.
            Path journalFile=files.resolve(".foldgpt-install/fresh/inactive-preparation.v1");
            Path data=root.resolve("home/foldgpt/.local/share");
            if(!InactivePreparationJournal.exists(journalFile)
                    && (InactivePreparationJournal.exists(encrypted) || InactivePreparationJournal.exists(pendingImport)
                    || InactivePreparationJournal.exists(data)))
                throw new IOException("Pre-existing vault or collection data has no inactive coordinator intent");
            Map<String,String> bindings=new TreeMap<>();
            bindings.put("root",storage.identity(root));
            bindings.put("base",spec.sha256+":"+spec.compressedBytes+":"+spec.payloadBytes+":"+spec.maxTarBytes+":"+spec.members);
            bindings.put("initializer",initializerSha256); bindings.put("supervisor",supervisorSha256); bindings.put("native",nativeDigest);
            bindings.put("vaultParent",storage.identity(noBackup)); bindings.put("uid",Integer.toString(android.os.Process.myUid()));
            bindings.put("gid",Integer.toString(Os.getgid()));
            if(clientInput!=null) {
                bindings.put("client",clientInput.descriptorSha256()); bindings.put("clientVerifier",clientInput.verifierSha256);
                bindings.put("clientInstaller",clientInput.installerSha256);
            }
            InactivePreparationJournal journal=clientInput==null?InactivePreparationJournal.open(journalFile,bindings,storage)
                :InactivePreparationJournal.openWithClient(journalFile,bindings,storage);
            GuestIdentity account;
            if(journal.step()==InactivePreparationJournal.Step.ROOT_PREPARED) {
                account=AndroidGuestAccountProvisioner.prepare(transaction); journal.accountPrepared();
            } else {
                account=GuestIdentity.load(root);
                if(!account.user.equals("foldgpt") || account.uid!=android.os.Process.myUid() || account.gid!=Os.getgid())
                    throw new IOException("Inactive coordinator guest identity changed");
            }
            AndroidInactiveClientInstaller.Result client=null;
            if(clientInput!=null) {
                // The package step always executes its real verification, even
                // after a completed journal step. Failure prevents vault use.
                client=AndroidInactiveClientInstaller.install(context,transaction,journal.value("installationId"),
                    clientInput.descriptor,clientInput.packageSource,clientInput.verifierSource,clientInput.verifierSha256,
                    clientInput.installerSource,clientInput.installerSha256,clientInput.timeoutMillis);
                if(!client.root.equals(root) || !client.rootIdentity.equals(bindings.get("root"))
                        || !client.packageSha256.equals(clientInput.descriptor.sha256))
                    throw new IOException("Inactive client evidence differs from coordinator inputs");
                if(journal.step()==InactivePreparationJournal.Step.ACCOUNT_PREPARED) journal.clientPrepared(client.reportSha256);
                else if(!client.reportSha256.equals(journal.value("clientReportSha256")))
                    throw new IOException("Resumed client report differs from coordinator evidence");
            }
            Path scripts=directoryChain(root,"usr/local/lib/foldgpt/install",storage);
            installScript(scripts.resolve("initialize_keyring.py"),initializer,initializerSha256,storage);
            installScript(scripts.resolve("supervise_keyring.py"),supervisor,supervisorSha256,storage);
            if(journal.step().ordinal()>=InactivePreparationJournal.Step.VAULT_PREPARED.ordinal())
                requireHash(encrypted,journal.value("vaultSha256"),storage,8256,true);
            else if(!InactivePreparationJournal.exists(encrypted) && InactivePreparationJournal.exists(data))
                throw new IOException("Collection preparation data exists but its Android credential is missing");
            credential=KeyringVault.prepareFreshPassword(context);
            String vaultHash=hashFile(encrypted,storage,8256,true);
            if(journal.step()==(clientInput==null?InactivePreparationJournal.Step.ACCOUNT_PREPARED:InactivePreparationJournal.Step.CLIENT_PREPARED))
                journal.vaultPrepared(vaultHash);
            else if(!vaultHash.equals(journal.value("vaultSha256"))) throw new IOException("Inactive vault ciphertext changed");
            if(journal.step()==InactivePreparationJournal.Step.COLLECTION_PREPARED) verifyCollectionFiles(data,journal,storage);
            ProcessBuilder process=guestProcess(context,root,account,nativeDirectory,storage);
            String output=SecretPipeProcess.run(process,credential,60000);
            credential=null; // SecretPipeProcess erased the exact transferred array.
            JSONObject receipt=receipt(output);
            String intentHash=receipt.getString("intentSha256"),collectionId=receipt.getString("installationId");
            String collectionPath=receipt.getString("collection"),dataIdentity=receipt.getString("dataIdentity");
            // Verify the guest receipt against actual host-side private files,
            // including PRoot's device/inode presentation. No translation bypass.
            storage.directory(data,true);
            if(!storage.identity(data).equals(dataIdentity)) throw new IOException("Guest/Android collection inode differs");
            requireHash(data.resolve(".foldgpt-keyring-intent.json"),intentHash,storage,4096,true);
            JSONObject intent=new JSONObject(new String(readOwned(data.resolve(".foldgpt-keyring-intent.json"),storage,4096,true),StandardCharsets.UTF_8));
            if(!intent.getString("schema").equals("foldgpt.keyring-intent.v1") || !intent.getString("installationId").equals(collectionId)
                    || !(intent.getLong("dataDevice")+":"+intent.getLong("dataInode")).equals(dataIdentity))
                throw new IOException("Guest collection receipt differs from its durable intent");
            requireHash(encrypted,vaultHash,storage,8256,true);
            if(journal.step()==InactivePreparationJournal.Step.VAULT_PREPARED)
                journal.collectionPrepared(intentHash,collectionId,collectionPath,dataIdentity);
            else if(!intentHash.equals(journal.value("collectionIntentSha256")) || !collectionId.equals(journal.value("collectionInstallationId"))
                    || !collectionPath.equals(journal.value("collectionPath")) || !dataIdentity.equals(journal.value("dataIdentity")))
                throw new IOException("Resumed collection differs from coordinator identity");
            if(transaction.state()!=RootfsTransaction.State.PREPARED || InactivePreparationJournal.exists(files.resolve("debian")))
                throw new IOException("Inactive preparation encountered unexpected activation");
            return new Result(root,account,journal,client);
        } finally { if(credential!=null) Arrays.fill(credential,(byte)0); }
    }
    private static JSONObject receipt(String output) throws Exception {
        String line=null;
        for(String candidate:output.split("\n")) if(candidate.startsWith("FOLDGPT_KEYRING_RECEIPT=")) {
            if(line!=null) throw new IOException("Duplicate inactive collection receipt");
            line=candidate.substring("FOLDGPT_KEYRING_RECEIPT=".length());
        }
        if(line==null || line.length()>4096) throw new IOException("Inactive collection receipt missing or oversized");
        JSONObject result=new JSONObject(line);
        if(result.length()!=5 || !result.getString("schema").equals("foldgpt.inactive-keyring.v1")
                || !result.getString("intentSha256").matches("[0-9a-f]{64}")
                || !result.getString("installationId").matches("[0-9a-f]{64}")
                || !result.getString("collection").matches("/org/freedesktop/secrets/collection/[A-Za-z0-9_]+")
                || result.getString("collection").endsWith("/session")
                || !result.getString("dataIdentity").matches("[0-9]+:[0-9]+")) throw new IOException("Invalid inactive collection receipt");
        return result;
    }
    private static void verifyCollectionFiles(Path data,InactivePreparationJournal journal,Storage storage) throws IOException {
        storage.directory(data,true);
        if(!storage.identity(data).equals(journal.value("dataIdentity"))) throw new IOException("Prepared collection directory changed");
        requireHash(data.resolve(".foldgpt-keyring-intent.json"),journal.value("collectionIntentSha256"),storage,4096,true);
    }
    private static ProcessBuilder guestProcess(Context context,Path root,GuestIdentity account,Path nativeDirectory,Storage storage) throws Exception {
        Path cache=context.getCacheDir().toPath(); storage.managedDirectory(cache);
        // PRoot translates pathname sockets to their physical Android path.
        // GNOME appends /control to its control directory; a long cache prefix
        // previously made that pathname exceed Linux sockaddr_un.sun_path.
        Path work=Files.createTempDirectory(cache,"kr-",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        if(work.resolve("runtime/control/control").toString().getBytes(StandardCharsets.UTF_8).length>107)
            throw new IOException("Private keyring cache path exceeds the Unix socket pathname limit");
        // Per-run sockets and temporary files live outside the rootfs and cannot
        // address an earlier run. Android may reclaim this stopped cache later.
        for(String child:List.of("runtime","shm","native")) Files.createDirectory(work.resolve(child),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.createSymbolicLink(work.resolve("native/libtalloc.so.2"),nativeDirectory.resolve("libtalloc.so"));
        List<String> command=new ArrayList<>(List.of(nativeDirectory.resolve("libproot.so").toString(),"--kill-on-exit","--link2symlink","--sysvipc",
            "-r",root.toString(),"-i",account.prootIds(),"-w",account.home,
            "-b","/dev","-b","/proc","-b","/sys","-b","/system","-b","/apex",
            "-b",work+":/tmp","-b",work.resolve("shm")+":/dev/shm",
            "/usr/bin/env","-i","HOME="+account.home,"USER="+account.user,"LOGNAME="+account.user,
            "PATH=/usr/bin:/bin","LANG=C.UTF-8","XDG_RUNTIME_DIR=/tmp/runtime","PYTHONDONTWRITEBYTECODE=1",
            "/usr/bin/python3","-B","/usr/local/lib/foldgpt/install/supervise_keyring.py"));
        ProcessBuilder builder=new ProcessBuilder(command);
        builder.environment().clear();
        builder.environment().put("PATH","/system/bin");
        builder.environment().put("LD_LIBRARY_PATH",work.resolve("native")+":"+nativeDirectory);
        builder.environment().put("PROOT_LOADER",nativeDirectory.resolve("libproot-loader.so").toString());
        builder.environment().put("PROOT_LOADER_32",nativeDirectory.resolve("libproot-loader32.so").toString());
        builder.environment().put("PROOT_TMP_DIR",work.toString()); builder.environment().put("TMPDIR",work.toString());
        return builder;
    }
    private static Path directoryChain(Path root,String relative,Storage storage) throws IOException {
        Path path=root;
        for(String segment:relative.split("/")) {
            Path next=path.resolve(segment);
            if(!InactivePreparationJournal.exists(next)) Files.createDirectory(next,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwxr-xr-x")));
            storage.directory(next,false); storage.syncDirectory(next); storage.syncDirectory(path); path=next;
        }
        return path;
    }
    private static void installScript(Path target,byte[] content,String sha256,Storage storage) throws IOException {
        if(InactivePreparationJournal.exists(target)) { requireHash(target,sha256,storage,1048576,false); return; }
        Path pending=target.resolveSibling("."+target.getFileName()+".next");
        if(InactivePreparationJournal.exists(pending)) { storage.regular(pending,true); Files.delete(pending); }
        try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes=ByteBuffer.wrap(content); while(bytes.hasRemaining()) output.write(bytes); output.force(true);
        }
        Files.move(pending,target,StandardCopyOption.ATOMIC_MOVE);
        // Private 0600 scripts are readable by this app-owned guest. No chmod,
        // execution bit or ownership simulation is required for Python sources.
        storage.syncDirectory(target.getParent()); requireHash(target,sha256,storage,1048576,true);
    }
    private static byte[] verifiedScript(Path path,String expected) throws IOException {
        if(expected==null || !expected.matches("[0-9a-f]{64}") || !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Verified installer script required");
        byte[] value=readBounded(path,1048576);
        if(!InactivePreparationJournal.sha256(value).equals(expected)) throw new IOException("Installer script differs from trusted descriptor");
        String decoded=StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(value)).toString();
        if(decoded.indexOf('\0')>=0 || decoded.indexOf('\r')>=0) throw new IOException("Installer scripts require canonical UTF-8/LF");
        return value;
    }
    private static String nativeDescriptor(Path directory) throws IOException {
        StringBuilder result=new StringBuilder();
        for(String name:List.of("libproot.so","libproot-loader.so","libproot-loader32.so","libtalloc.so","libandroid-shmem.so")) {
            Path file=directory.resolve(name);
            if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Installed APK native component is missing");
            result.append(name).append(':').append(InactivePreparationJournal.sha256(readBounded(file,33554432))).append('\n');
        }
        return InactivePreparationJournal.sha256(result.toString().getBytes(StandardCharsets.US_ASCII));
    }
    private static void requireHash(Path file,String expected,Storage storage,int limit,boolean privateFile) throws IOException {
        if(!hashFile(file,storage,limit,privateFile).equals(expected)) throw new IOException("Inactive preparation file evidence differs: "+file.getFileName());
    }
    private static String hashFile(Path file,Storage storage,int limit,boolean privateFile) throws IOException {
        return InactivePreparationJournal.sha256(readOwned(file,storage,limit,privateFile));
    }
    private static byte[] readOwned(Path file,Storage storage,int limit,boolean privateFile) throws IOException {
        storage.regular(file,privateFile); return readBounded(file,limit);
    }
    private static byte[] readBounded(Path file,int limit) throws IOException {
        try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            if(input.size()<1 || input.size()>limit) throw new IOException("Inactive preparation input size differs");
            ByteBuffer buffer=ByteBuffer.allocate((int)input.size()+1);
            while(buffer.hasRemaining() && input.read(buffer)!=-1) {}
            if(!buffer.hasRemaining()) throw new IOException("Inactive preparation input grew during read");
            byte[] bytes=new byte[buffer.position()]; buffer.flip(); buffer.get(bytes); return bytes;
        }
    }
    private static final class Storage implements GuestAccountProvisioner.Storage {
        public String identity(Path path) throws IOException {
            StructStat stat=stat(path);
            if(!OsConstants.S_ISDIR(stat.st_mode) || stat.st_uid!=android.os.Process.myUid()) throw new IOException("Inactive preparation inode must belong to the app");
            return Long.toUnsignedString(stat.st_dev)+":"+Long.toUnsignedString(stat.st_ino);
        }
        void managedDirectory(Path path) throws IOException {
            // Android creates its managed files/cache/noBackup containers with
            // group access for the app GID on some versions. The transaction,
            // vault and run directories inside them enforce their own 0700.
            StructStat info=stat(path);
            if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid() || (info.st_mode&0002)!=0
                    || ((info.st_mode&0020)!=0 && info.st_gid!=Os.getgid()))
                throw new IOException("Android-managed preparation container has unexpected ownership or permissions");
        }
        public long linkCount(Path path) throws IOException { return stat(path).st_nlink; }
        void directory(Path path,boolean privateDirectory) throws IOException {
            StructStat info=stat(path);
            if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid() || (info.st_mode&(privateDirectory?0077:0022))!=0)
                throw new IOException("Inactive preparation directory must be real, owned and protected");
        }
        void regular(Path path,boolean privateFile) throws IOException {
            StructStat info=stat(path);
            if(!OsConstants.S_ISREG(info.st_mode) || info.st_uid!=android.os.Process.myUid() || info.st_nlink!=1 || (info.st_mode&(privateFile?0077:0022))!=0)
                throw new IOException("Inactive preparation file must be regular, owned and protected");
        }
        private StructStat stat(Path path) throws IOException {
            try { return Os.lstat(path.toString()); }
            catch(ErrnoException error) { throw new IOException("Inactive preparation path inspection failed: "+path.getFileName(),error); }
        }
        public void syncDirectory(Path path) throws IOException {
            FileDescriptor fd=null;
            try {
                fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
                StructStat info=Os.fstat(fd);
                if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid()) throw new IOException("Inactive preparation sync target differs");
                Os.fsync(fd);
            } catch(ErrnoException error) { throw new IOException("Inactive preparation directory sync failed",error); }
            finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Inactive preparation directory close failed",error); } }
        }
    }
}
