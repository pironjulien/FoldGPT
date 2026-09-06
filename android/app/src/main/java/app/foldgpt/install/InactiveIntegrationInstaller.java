package app.foldgpt.install;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.security.MessageDigest;
import java.util.*;

/** Native filesystem installation under the existing inactive transaction lease.
 * No PRoot, subprocess, device, GPU execution, user credential or activation.
 * Requires the same exclusive app-owned stage model as RootfsTransaction:
 * no running guest or other concurrent writer sharing this Android UID.
 */
public final class InactiveIntegrationInstaller {
    private InactiveIntegrationInstaller() {}
    public interface Storage {
        String identity(Path path) throws IOException;
        long linkCount(Path path) throws IOException;
        int mode(Path path) throws IOException;
        void syncDirectory(Path path) throws IOException;
    }
    interface Checkpoint { void at(String name) throws IOException; }
    public static final class Result {
        public final Path root,report;
        public final String rootIdentity,bundleSha256,manifestSha256,reportSha256;
        private Result(Path root,Path report,String identity,InactiveIntegrationBundle bundle,String reportSha) {
            this.root=root; this.report=report; rootIdentity=identity; bundleSha256=bundle.sha256;
            manifestSha256=bundle.manifestSha256; reportSha256=reportSha;
        }
    }
    public static Result install(RootfsTransaction transaction,Storage storage,String installationId,
            InactiveIntegrationBundle bundle) throws IOException {
        return install(transaction,storage,installationId,bundle,name -> {});
    }
    static Result install(RootfsTransaction transaction,Storage storage,String installationId,
            InactiveIntegrationBundle bundle,Checkpoint checkpoint) throws IOException {
        Objects.requireNonNull(transaction); Objects.requireNonNull(storage); Objects.requireNonNull(bundle); Objects.requireNonNull(checkpoint);
        if(installationId==null || !installationId.matches("[0-9a-f]{64}")) throw new IOException("Coordinator installation identity is required");
        synchronized(transaction) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Integration requires the inactive PREPARED lease");
            Path root=transaction.prepare(() -> { throw new IOException("Integration cannot extract a Debian base"); }).root;
            Result result=new Installation(root,storage,installationId,bundle,checkpoint).run();
            if(transaction.state()!=RootfsTransaction.State.PREPARED || !transaction.prepare(() -> {
                    throw new IOException("Integration cannot re-extract a Debian base"); }).root.equals(root))
                throw new IOException("Integration transaction changed");
            return result;
        }
    }
    private static final class Installation {
        final Path root,state;
        final Storage storage;
        final String installationId,rootIdentity;
        final InactiveIntegrationBundle bundle;
        final Checkpoint checkpoint;
        final UserPrincipal owner;
        final GroupPrincipal group;
        final Set<String> installedDirectories=new TreeSet<>();
        Installation(Path root,Storage storage,String id,InactiveIntegrationBundle bundle,Checkpoint checkpoint) throws IOException {
            this.root=root; this.storage=storage; installationId=id; this.bundle=bundle; this.checkpoint=checkpoint;
            owner=Files.getOwner(root,LinkOption.NOFOLLOW_LINKS); group=Files.readAttributes(root,PosixFileAttributes.class,LinkOption.NOFOLLOW_LINKS).group();
            directory(root,false); rootIdentity=storage.identity(root);
            if(!rootIdentity.matches("[0-9]+:[0-9]+")) throw new IOException("Invalid native root identity");
            state=root.resolve("var/lib/foldgpt/integration-install");
            for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) if(entry.scope.equals("I")) {
                String parent=entry.path;
                while(parent.contains("/")) { parent=parent.substring(0,parent.lastIndexOf('/')); installedDirectories.add(parent); }
            }
        }
        Result run() throws IOException {
            // Compare the existing extractor's authenticated base receipt. The
            // transaction itself validates its entire receipt and stage inode.
            Path receipt=root.getParent().resolve("extracted.sha256");
            String baseReceipt=new String(read(receipt,128),StandardCharsets.US_ASCII);
            if(!baseReceipt.startsWith(bundle.baseSha256+"\n")) throw new IOException("Integration bundle belongs to another Debian base");
            GuestIdentity account=GuestIdentity.load(root);
            verifyXkb(); // Native, outside PRoot: includes exact tree and real link resolution.
            Path intent=state.resolve("intent.v1"),report=state.resolve("report.v1");
            parents(intent,false);
            boolean resumed=exists(intent),completed=exists(report);
            byte[] expectedIntent=("foldgpt.inactive-integration-intent.v1\n"+installationId+"\n"+rootIdentity+"\n"
                +bundle.sha256+"\n"+bundle.manifestSha256+"\n"+account.user+":"+account.prootIds()+":"+account.home+"\n")
                .getBytes(StandardCharsets.US_ASCII);
            if(resumed) requireExact(intent,expectedIntent,0600);
            else if(completed) throw new IOException("Integration report has no bound intent");
            if(resumed && exists(state.resolve("intent.v1.pending"))
                    || (!resumed || completed) && exists(state.resolve("report.v1.pending")))
                throw new IOException("Integration metadata contains an impossible or unbound pending publication");
            if(exists(state)) {
                directory(state,true);
                try(var children=Files.list(state)) {
                    for(Path child:children.collect(java.util.stream.Collectors.toList())) {
                        if(!Set.of("intent.v1","intent.v1.pending","report.v1","report.v1.pending").contains(child.getFileName().toString()))
                            throw new IOException("Unknown entry occupies integration state");
                        regular(child); requireMode(child,0600);
                    }
                }
            }
            // All pre-existing final files must already match exactly. Only the
            // two coordinator-owned 0600 keyring helpers may predate our intent.
            preflight(resumed,completed);
            // The client installer shares this state parent and requires 0700.
            // A previous integration build created it as 0755. Tighten only a
            // resumed installation whose exact intent and files were verified;
            // keep the inode, reports and any client state in place.
            Path stateParent=state.getParent();
            if(resumed && exists(stateParent)) {
                directory(stateParent,false);
                if(Files.getPosixFilePermissions(stateParent,LinkOption.NOFOLLOW_LINKS).equals(permissions(0755))) {
                    String identity=storage.identity(stateParent);
                    Files.setPosixFilePermissions(stateParent,permissions(0700));
                    directory(stateParent,true); requireMode(stateParent,0700);
                    if(!identity.equals(storage.identity(stateParent))) throw new IOException("Integration state parent changed during privacy correction");
                    storage.syncDirectory(stateParent); storage.syncDirectory(stateParent.getParent());
                }
            }
            if(exists(stateParent)) directory(stateParent,true);
            if(!resumed) {
                parents(intent,true); directory(state,true);
                publish(intent,expectedIntent,0600,"intent");
            }
            if(!completed) {
                for(String name:installedDirectories) {
                    Path path=root.resolve(name);
                    if(!exists(path)) {
                        parents(path,true);
                        Files.createDirectory(path,PosixFilePermissions.asFileAttribute(permissions(0755)));
                        Files.setPosixFilePermissions(path,permissions(0755));
                        directory(path,false); requireMode(path,0755); storage.syncDirectory(path); storage.syncDirectory(path.getParent());
                        checkpoint.at("directory-created");
                    }
                }
                for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) if(entry.scope.equals("I") && entry.kind.equals("F")) {
                    Path target=root.resolve(entry.path);
                    if(exists(target)) continue;
                    publish(target,bundle.bytes,entry.offset,entry.size,entry.mode,"file");
                }
                // Install links only after their complete target chain exists.
                // A death after any individual link therefore leaves no dangling
                // final link that a resumed preflight would have to excuse.
                List<InactiveIntegrationBundle.Entry> links=new ArrayList<>();
                for(InactiveIntegrationBundle.Entry entry:bundle.entries.values())
                    if(entry.scope.equals("I") && entry.kind.equals("L") && !exists(root.resolve(entry.path))) links.add(entry);
                while(!links.isEmpty()) {
                    int before=links.size();
                    for(Iterator<InactiveIntegrationBundle.Entry> iterator=links.iterator();iterator.hasNext();) {
                        InactiveIntegrationBundle.Entry entry=iterator.next(); Path target=root.resolve(entry.path);
                        if(!Files.isRegularFile(target.getParent().resolve(entry.link))) continue;
                        Files.createSymbolicLink(target,Path.of(entry.link)); verify(entry);
                        storage.syncDirectory(target.getParent()); iterator.remove(); checkpoint.at("link-written");
                    }
                    if(links.size()==before) throw new IOException("GPU link dependency chain cannot resolve");
                }
            }
            verifyXkb(); verifyInstalledTree(true);
            StringBuilder evidence=new StringBuilder("foldgpt.inactive-integration-report.v1\n")
                .append("scope\tscripts-gpu-files-native-xkb-and-declared-launch-inputs\n")
                .append("activation\tnot-performed\n").append("gpuExecution\tnot-performed\n")
                .append("installationId\t").append(installationId).append('\n')
                .append("rootIdentity\t").append(rootIdentity).append('\n')
                .append("bundleSha256\t").append(bundle.sha256).append('\n')
                .append("manifestSha256\t").append(bundle.manifestSha256).append('\n')
                .append("account\t").append(account.user).append(':').append(account.prootIds()).append(':').append(account.home).append('\n');
            for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) {
                verify(entry);
                evidence.append(entry.path).append('\t').append(entry.kind).append('\t')
                    .append(String.format(Locale.ROOT,"%04o",storage.mode(root.resolve(entry.path))&07777)).append('\t')
                    .append(storage.identity(root.resolve(entry.path))).append('\t').append(entry.sha).append('\t').append(entry.link).append('\n');
            }
            if(!storage.identity(root).equals(rootIdentity)) throw new IOException("Native integration root identity changed");
            GuestIdentity after=GuestIdentity.load(root);
            if(!after.user.equals(account.user) || !after.prootIds().equals(account.prootIds()) || !after.home.equals(account.home))
                throw new IOException("Guest account changed during integration");
            byte[] data=evidence.toString().getBytes(StandardCharsets.US_ASCII);
            if(completed) requireExact(report,data,0600);
            else publish(report,data,0600,"report");
            // Completed reports never repair drift or recreate a missing file.
            return new Result(root,report,rootIdentity,bundle,InactiveIntegrationBundle.hash(data));
        }
        void preflight(boolean resumed,boolean completed) throws IOException {
            for(String name:installedDirectories) if(exists(root.resolve(name))) directory(root.resolve(name),false);
            for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) if(entry.scope.equals("I")) {
                Path target=root.resolve(entry.path); parents(target,false);
                if(exists(target)) {
                    if(!resumed && !(entry.path.equals("usr/local/lib/foldgpt/install/initialize_keyring.py")
                            || entry.path.equals("usr/local/lib/foldgpt/install/supervise_keyring.py")))
                        throw new IOException("Unbound pre-existing integration target: "+entry.path);
                    verify(entry);
                } else if(completed) throw new IOException("Completed integration file is missing: "+entry.path);
                Path pending=target.resolveSibling(target.getFileName()+".pending");
                if(exists(pending)) {
                    if(!resumed || completed || exists(target) || !entry.kind.equals("F")) throw new IOException("Unbound or impossible integration pending file");
                    regular(pending);
                }
            }
            verifyInstalledTree(completed);
        }
        void verifyInstalledTree(boolean complete) throws IOException {
            Path prefix=root.resolve(InactiveIntegrationBundle.GPU_PREFIX);
            if(!exists(prefix)) { if(complete) throw new IOException("Reviewed GPU prefix is missing"); return; }
            Set<String> allowed=new HashSet<>(installedDirectories);
            for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) if(entry.scope.equals("I")) {
                allowed.add(entry.path); if(!complete && entry.kind.equals("F")) allowed.add(entry.path+".pending");
            }
            try(var paths=Files.walk(prefix)) {
                for(Path path:paths.collect(java.util.stream.Collectors.toList())) {
                    String name=relative(path);
                    if(!allowed.contains(name)) throw new IOException("Unknown file occupies the reviewed GPU prefix: "+name);
                    if(installedDirectories.contains(name)) { directory(path,false); requireMode(path,0755); }
                }
            }
        }
        void verifyXkb() throws IOException {
            Path tree=root.resolve(InactiveIntegrationBundle.XKB); parents(tree,false); directory(tree,false);
            Set<String> actual=new TreeSet<>(),expected=new TreeSet<>();
            for(InactiveIntegrationBundle.Entry entry:bundle.entries.values()) if(entry.scope.equals("V")) expected.add(entry.path);
            try(var paths=Files.walk(tree)) { for(Path path:paths.collect(java.util.stream.Collectors.toList())) actual.add(relative(path)); }
            if(!actual.equals(expected)) throw new IOException("Native XKB tree differs from the authenticated Debian inventory");
            for(String path:expected) verify(bundle.entries.get(path));
        }
        void verify(InactiveIntegrationBundle.Entry entry) throws IOException {
            Path target=root.resolve(entry.path); parents(target,false);
            if(entry.kind.equals("D")) directory(target,false);
            else if(entry.kind.equals("L")) {
                if(!Files.isSymbolicLink(target) || !Files.getOwner(target,LinkOption.NOFOLLOW_LINKS).equals(owner)
                        || !Files.readSymbolicLink(target).toString().equals(entry.link)) throw new IOException("Integration link differs: "+entry.path);
                // toRealPath executes the host's real symlink resolution, exactly
                // what native Xlorie uses, with no guest-root reinterpretation.
                Path resolved=target.toRealPath();
                if(!resolved.startsWith(root) || !Files.isRegularFile(resolved,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Native integration link escapes or dangles");
                if(entry.scope.equals("V") && !resolved.startsWith(root.resolve(InactiveIntegrationBundle.XKB))) throw new IOException("Native XKB link escapes its tree");
            } else {
                regular(target);
                BasicFileAttributes before=Files.readAttributes(target,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
                if(before.size()!=entry.size) throw new IOException("Integration file size differs: "+entry.path);
                String identity=storage.identity(target);
                MessageDigest digest;
                try { digest=MessageDigest.getInstance("SHA-256"); } catch(java.security.NoSuchAlgorithmException error) { throw new IOException(error); }
                try(InputStream stream=Files.newInputStream(target,LinkOption.NOFOLLOW_LINKS)) {
                    byte[] buffer=new byte[65536]; long count=0; int received;
                    while((received=stream.read(buffer))!=-1) {
                        count+=received; if(count>entry.size) throw new IOException("Integration file grew while reading"); digest.update(buffer,0,received);
                    }
                    if(count!=entry.size || !InactiveIntegrationBundle.hex(digest.digest()).equals(entry.sha)) throw new IOException("Integration file hash differs: "+entry.path);
                }
                if(!storage.identity(target).equals(identity)) throw new IOException("Integration file identity changed while reading");
            }
            requireMode(target,entry.mode);
        }
        void parents(Path target,boolean create) throws IOException {
            if(!target.normalize().equals(target) || !target.startsWith(root)) throw new IOException("Integration target escapes root");
            Path current=root;
            for(Path part:root.relativize(target.getParent())) {
                current=current.resolve(part);
                if(!exists(current)) {
                    if(!create) continue;
                    int mode=current.equals(state) || current.equals(state.getParent())?0700:0755;
                    Files.createDirectory(current,PosixFilePermissions.asFileAttribute(permissions(mode)));
                    Files.setPosixFilePermissions(current,permissions(mode)); storage.syncDirectory(current); storage.syncDirectory(current.getParent());
                }
                directory(current,current.equals(state));
            }
        }
        void publish(Path target,byte[] bytes,int mode,String point) throws IOException { publish(target,bytes,0,bytes.length,mode,point); }
        void publish(Path target,byte[] bytes,int offset,int size,int mode,String point) throws IOException {
            Path pending=target.resolveSibling(target.getFileName()+".pending");
            if(exists(pending)) regular(pending);
            try(FileChannel channel=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(permissions(0600)))) {
                regular(pending); channel.truncate(0); ByteBuffer buffer=ByteBuffer.wrap(bytes,offset,size);
                while(buffer.hasRemaining()) channel.write(buffer);
                Files.setPosixFilePermissions(pending,permissions(mode)); requireMode(pending,mode); channel.force(true);
            }
            storage.syncDirectory(target.getParent()); checkpoint.at(point+"-pending");
            if(exists(target)) throw new IOException("Integration publication target became occupied");
            // ATOMIC_MOVE is used only under the retained exclusive installation
            // lease; same-UID hostile/concurrent writers are outside this model.
            Files.move(pending,target,StandardCopyOption.ATOMIC_MOVE);
            storage.syncDirectory(target.getParent()); checkpoint.at(point+"-written");
        }
        byte[] read(Path path,int limit) throws IOException {
            regular(path);
            try(InputStream stream=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes=stream.readNBytes(limit+1); if(bytes.length>limit) throw new IOException("Oversized integration metadata"); return bytes;
            }
        }
        void requireExact(Path path,byte[] bytes,int mode) throws IOException {
            requireMode(path,mode); if(!Arrays.equals(read(path,Math.max(bytes.length,4096)),bytes)) throw new IOException("Bound integration metadata differs");
        }
        void regular(Path path) throws IOException {
            if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(owner)
                    || storage.linkCount(path)!=1) throw new IOException("Integration requires a single owned regular file: "+path.getFileName());
        }
        void directory(Path path,boolean privatePath) throws IOException {
            if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(owner)) throw new IOException("Integration directory is not real and owned");
            int mode=storage.mode(path);
            if((mode&(privatePath?0077:0002))!=0 || (mode&0020)!=0 && !Files.readAttributes(path,PosixFileAttributes.class,LinkOption.NOFOLLOW_LINKS).group().equals(group))
                throw new IOException("Integration directory is writable by another identity");
        }
        void requireMode(Path path,int mode) throws IOException { if((storage.mode(path)&07777)!=mode) throw new IOException("Integration mode differs: "+path.getFileName()); }
        String relative(Path path) { return root.relativize(path).toString().replace(File.separatorChar,'/'); }
    }
    private static boolean exists(Path path) throws IOException {
        try { Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS); return true; }
        catch(NoSuchFileException absent) { return false; }
    }
    private static Set<PosixFilePermission> permissions(int mode) {
        StringBuilder text=new StringBuilder(); String letters="rwxrwxrwx";
        for(int index=0;index<9;index++) text.append((mode&(1<<(8-index)))!=0?letters.charAt(index):'-');
        return PosixFilePermissions.fromString(text.toString());
    }
}
