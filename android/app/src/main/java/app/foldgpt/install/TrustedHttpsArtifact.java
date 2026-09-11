package app.foldgpt.install;

import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;

/** Authenticated-input acquisition into a private cache, never runtime readiness.
 * URL, exact size and SHA-256 must arrive from an independently trusted release
 * descriptor. TLS uses the platform's normal trust and hostname verification.
 * Partial bytes are reusable only under that exact descriptor and are always
 * hashed completely before publication. An HTTP range/ETag is not authentication.
 * All cooperating acquisitions use the per-descriptor process/file lease.
 * The private cache is not a boundary against hostile native code with our UID.
 */
public final class TrustedHttpsArtifact {
    private TrustedHttpsArtifact() {}
    private static final Set<String> NAMES=Set.of("lease","descriptor.v1","descriptor.next","download.part","verified.artifact");
    public interface Storage {
        String identity(Path path) throws IOException;
        long linkCount(Path path) throws IOException;
        int mode(Path path) throws IOException;
        /** Only called immediately after this acquisition created the directory.
         * Verify the expected no-follow identity, clear inherited special bits,
         * and require the same directory with the full mode 0700 afterwards. */
        void finishCreatedDirectory(Path path,String expectedIdentity) throws IOException;
        void syncDirectory(Path path) throws IOException;
    }
    public interface Progress { void received(long bytes,long total) throws IOException; }
    interface Checkpoint { void at(String name) throws IOException; }

    public static final class Descriptor {
        public final URI url;
        public final long bytes;
        public final String sha256,key;
        private final byte[] document;
        public Descriptor(URI url,long bytes,String sha256) throws IOException {
            this.url=https(url);
            if(bytes<=0 || sha256==null || !sha256.matches("[0-9a-f]{64}"))
                throw new IOException("An independently trusted exact artifact size and SHA-256 are required");
            this.bytes=bytes; this.sha256=sha256;
            document=("foldgpt.https-artifact.v1\n"+url.toASCIIString()+"\n"+bytes+"\n"+sha256+"\n").getBytes(StandardCharsets.US_ASCII);
            key=hex(digest().digest(document));
        }
    }
    public static final class Options {
        public final int connectTimeoutMillis,readTimeoutMillis,totalTimeoutMillis;
        public Options(int connect,int read,int total) {
            if(connect<=0 || read<=0 || total<=0) throw new IllegalArgumentException("Positive acquisition deadlines are required");
            connectTimeoutMillis=connect; readTimeoutMillis=read; totalTimeoutMillis=total;
        }
    }
    /** One monotonic cancellation token per acquisition. No global connection state. */
    public static final class Cancellation {
        private boolean cancelled;
        private HttpsURLConnection connection;
        public void cancel() {
            HttpsURLConnection active;
            synchronized(this) { cancelled=true; active=connection; }
            if(active!=null) active.disconnect();
        }
        private synchronized void check() throws InterruptedIOException {
            if(cancelled || Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Artifact acquisition cancelled");
        }
        private synchronized void attach(HttpsURLConnection value) throws IOException {
            check();
            if(connection!=null) throw new IOException("Cancellation token is already attached to an acquisition");
            connection=value;
        }
        private synchronized void detach(HttpsURLConnection value) { if(connection==value) connection=null; }
    }
    public static final class Result {
        public final Path file;
        public final Descriptor descriptor;
        public final long resumedFrom;
        private Result(Path file,Descriptor descriptor,long resumedFrom) { this.file=file; this.descriptor=descriptor; this.resumedFrom=resumedFrom; }
    }
    private static final class IntegrityFailure extends IOException {
        IntegrityFailure(String message) { super(message); }
    }

    public static Result acquire(Path managedCache,Descriptor descriptor,Options options,Cancellation cancellation,
                                 Progress progress,Storage storage) throws IOException {
        return acquire(managedCache,descriptor,options,cancellation,progress,storage,name -> {});
    }
    static Result acquire(Path managedCache,Descriptor descriptor,Options options,Cancellation cancellation,
                          Progress progress,Storage storage,Checkpoint checkpoint) throws IOException {
        Objects.requireNonNull(descriptor); Objects.requireNonNull(options); Objects.requireNonNull(cancellation);
        Objects.requireNonNull(progress); Objects.requireNonNull(storage); Objects.requireNonNull(checkpoint);
        return new Acquisition(managedCache,descriptor,options,cancellation,progress,storage,checkpoint).run();
    }

    private static final class Acquisition {
        final Path parent,cache,directory,partial,target;
        final Descriptor descriptor;
        final Options options;
        final Cancellation cancellation;
        final Progress progress;
        final Storage storage;
        final Checkpoint checkpoint;
        final UserPrincipal owner;
        final long started=System.nanoTime();
        Acquisition(Path input,Descriptor descriptor,Options options,Cancellation cancellation,Progress progress,
                    Storage storage,Checkpoint checkpoint) throws IOException {
            Path absolute=input.toAbsolutePath().normalize();
            if(!absolute.equals(absolute.toRealPath()) || !Files.isDirectory(absolute,LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Acquisition cache must be a real managed directory");
            parent=absolute; owner=Files.getOwner(parent,LinkOption.NOFOLLOW_LINKS);
            if(Files.getPosixFilePermissions(parent,LinkOption.NOFOLLOW_LINKS).contains(java.nio.file.attribute.PosixFilePermission.OTHERS_WRITE))
                throw new IOException("Acquisition cache parent is writable by others");
            this.descriptor=descriptor; this.options=options; this.cancellation=cancellation; this.progress=progress;
            this.storage=storage; this.checkpoint=checkpoint;
            cache=parent.resolve("foldgpt-acquisition"); directory=cache.resolve(descriptor.key);
            partial=directory.resolve("download.part"); target=directory.resolve("verified.artifact");
        }
        Result run() throws IOException {
            check(); createPrivate(cache); storage.syncDirectory(parent);
            createPrivate(directory); storage.syncDirectory(cache);
            Path lease=directory.resolve("lease");
            if(exists(lease)) regular(lease);
            try(FileChannel channel=FileChannel.open(lease,Set.of(StandardOpenOption.CREATE,StandardOpenOption.READ,
                    StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),permissions("rw-------"))) {
                regular(lease);
                FileLock lock;
                try { lock=channel.tryLock(); }
                catch(OverlappingFileLockException busy) { throw new IOException("Another acquisition holds this artifact lease",busy); }
                if(lock==null) throw new IOException("Another acquisition holds this artifact lease");
                try(lock) {
                    check();
                    try(var paths=Files.list(directory)) {
                        for(Path path:paths.collect(java.util.stream.Collectors.toList())) {
                            if(!NAMES.contains(path.getFileName().toString())) throw new IOException("Unknown file occupies artifact cache entry");
                            regular(path);
                        }
                    }
                    bindDescriptor();
                    if(exists(target)) {
                        if(exists(partial)) throw new IOException("Published artifact and competing partial coexist");
                        verify(target); storage.syncDirectory(directory);
                        return new Result(target,descriptor,0);
                    }
                    long offset=exists(partial)?Files.size(partial):0;
                    if(offset>descriptor.bytes) throw new IOException("Partial artifact exceeds its trusted size");
                    try {
                        if(offset<descriptor.bytes) offset=download(offset);
                        verify(partial);
                    } catch(IntegrityFailure failure) {
                        // Only this registered, private partial is discarded.
                        // An already published artifact is never repaired silently.
                        if(exists(partial)) { regular(partial); Files.delete(partial); storage.syncDirectory(directory); }
                        throw failure;
                    }
                    String verifiedIdentity=storage.identity(partial);
                    checkpoint.at("part-verified"); check(); regular(partial);
                    if(!verifiedIdentity.equals(storage.identity(partial))) throw new IOException("Verified partial inode changed before publication");
                    if(exists(target)) throw new FileAlreadyExistsException("Artifact publication target appeared while leased");
                    Files.move(partial,target,StandardCopyOption.ATOMIC_MOVE);
                    checkpoint.at("artifact-published"); storage.syncDirectory(directory);
                    verify(target);
                    return new Result(target,descriptor,offset);
                }
            }
        }
        void bindDescriptor() throws IOException {
            Path file=directory.resolve("descriptor.v1"),pending=directory.resolve("descriptor.next");
            if(exists(file)) {
                if(!Arrays.equals(readSmall(file,16384),descriptor.document)) throw new IOException("Cached acquisition descriptor differs");
                if(exists(pending)) { regular(pending); Files.delete(pending); storage.syncDirectory(directory); }
                return;
            }
            if(exists(partial) || exists(target)) throw new IOException("Artifact data has no durable trusted descriptor binding");
            if(exists(pending)) { regular(pending); Files.delete(pending); }
            try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,
                    LinkOption.NOFOLLOW_LINKS),permissions("rw-------"))) {
                ByteBuffer data=ByteBuffer.wrap(descriptor.document); while(data.hasRemaining()) output.write(data); output.force(true);
            }
            checkpoint.at("descriptor-ready"); check();
            if(exists(file)) throw new FileAlreadyExistsException("Acquisition descriptor appeared while leased");
            Files.move(pending,file,StandardCopyOption.ATOMIC_MOVE); storage.syncDirectory(directory);
        }
        long download(long offset) throws IOException {
            URI location=descriptor.url; Set<URI> visited=new HashSet<>();
            for(int redirects=0;redirects<=5;redirects++) {
                check();
                if(!visited.add(location)) throw new IOException("HTTPS artifact redirect loop");
                HttpsURLConnection connection=(HttpsURLConnection)location.toURL().openConnection();
                connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
                connection.setConnectTimeout(timeout(options.connectTimeoutMillis));
                connection.setReadTimeout(timeout(options.readTimeoutMillis));
                connection.setRequestProperty("Accept-Encoding","identity");
                if(offset>0) connection.setRequestProperty("Range","bytes="+offset+"-");
                try {
                    cancellation.attach(connection);
                    int status=connection.getResponseCode(); check();
                    if(Set.of(301,302,303,307,308).contains(status)) {
                        String next=connection.getHeaderField("Location");
                        if(next==null || next.length()>8192) throw new IOException("Invalid artifact redirect location");
                        try { location=https(location.resolve(next)); }
                        catch(IllegalArgumentException invalid) { throw new IOException("Invalid HTTPS artifact redirect",invalid); }
                        continue;
                    }
                    if(status!=200 && !(status==206 && offset>0)) throw new IOException("HTTPS artifact status differs: "+status);
                    String encoding=connection.getHeaderField("Content-Encoding");
                    if(encoding!=null && !encoding.equalsIgnoreCase("identity")) throw new IOException("Encoded artifact response is unsupported");
                    long start=status==200?0:offset;
                    if(status==206) {
                        String wanted="bytes "+start+"-"+(descriptor.bytes-1)+"/"+descriptor.bytes;
                        if(!wanted.equals(connection.getHeaderField("Content-Range"))) throw new IOException("Artifact Content-Range differs from trusted size and offset");
                    } else if(connection.getHeaderField("Content-Range")!=null) throw new IOException("Unexpected artifact Content-Range");
                    long length=connection.getContentLengthLong(),remaining=descriptor.bytes-start;
                    if(length!=-1 && length!=remaining) throw new IOException("Artifact HTTP length differs from trusted size");
                    transfer(connection,start);
                    return start;
                } catch(IOException failure) {
                    cancellation.check(); throw failure;
                } finally { cancellation.detach(connection); connection.disconnect(); }
            }
            throw new IOException("Too many HTTPS artifact redirects");
        }
        void transfer(HttpsURLConnection connection,long start) throws IOException {
            if(exists(partial)) regular(partial);
            try(InputStream input=connection.getInputStream();
                FileChannel output=FileChannel.open(partial,Set.of(StandardOpenOption.CREATE,StandardOpenOption.READ,
                    StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),permissions("rw-------"))) {
                regular(partial); storage.syncDirectory(directory);
                if(start==0) output.truncate(0);
                else if(output.size()!=start) throw new IOException("Partial artifact changed before range transfer");
                output.position(start);
                byte[] buffer=new byte[65536]; long received=start;
                try {
                    for(;;) {
                        check(); connection.setReadTimeout(timeout(options.readTimeoutMillis));
                        int count=input.read(buffer);
                        if(count<0) break;
                        if(count==0) continue;
                        if(count>descriptor.bytes-received) throw new IntegrityFailure("Artifact response exceeds the trusted byte count");
                        ByteBuffer bytes=ByteBuffer.wrap(buffer,0,count); while(bytes.hasRemaining()) output.write(bytes);
                        received+=count; progress.received(received,descriptor.bytes);
                    }
                    if(received!=descriptor.bytes) throw new EOFException("Artifact transfer ended before the trusted byte count");
                } finally { output.force(true); }
            }
        }
        void verify(Path file) throws IOException {
            check(); regular(file); String identity=storage.identity(file);
            if(Files.size(file)!=descriptor.bytes) throw new IntegrityFailure("Artifact size does not match its trusted descriptor");
            MessageDigest hash=digest();
            try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer=ByteBuffer.allocate(65536); long count=0;
                while(input.read(buffer)!=-1) {
                    check(); buffer.flip(); count+=buffer.remaining();
                    if(count>descriptor.bytes) throw new IntegrityFailure("Artifact grew during verification");
                    hash.update(buffer); buffer.clear();
                }
                if(count!=descriptor.bytes || !hex(hash.digest()).equals(descriptor.sha256))
                    throw new IntegrityFailure("Artifact SHA-256 differs from the independently trusted descriptor");
                // A complete partial may come from a process killed before its
                // writer's finally block. Hashing page-cache bytes is not fsync.
                input.force(true);
            }
            regular(file);
            if(!identity.equals(storage.identity(file)) || Files.size(file)!=descriptor.bytes)
                throw new IOException("Artifact inode changed during verification");
        }
        byte[] readSmall(Path file,int limit) throws IOException {
            regular(file);
            try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer=ByteBuffer.allocate(limit+1);
                while(buffer.hasRemaining() && input.read(buffer)!=-1) {}
                if(!buffer.hasRemaining()) throw new IOException("Oversized cached artifact descriptor");
                byte[] data=new byte[buffer.position()]; buffer.flip(); buffer.get(data);
                return data;
            }
        }
        void createPrivate(Path path) throws IOException {
            boolean created=false;
            try { Files.createDirectory(path,permissions("rwx------")); created=true; }
            catch(FileAlreadyExistsException existing) { /* Existing directories are validated, never chmod-ed. */ }
            if(created) storage.finishCreatedDirectory(path,storage.identity(path));
            if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !owner.equals(Files.getOwner(path,LinkOption.NOFOLLOW_LINKS))
                    || storage.mode(path)!=0700)
                throw new IOException("Artifact cache directory must be private and owned");
        }
        void regular(Path path) throws IOException {
            if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !owner.equals(Files.getOwner(path,LinkOption.NOFOLLOW_LINKS))
                    || storage.linkCount(path)!=1 || storage.mode(path)!=0600)
                throw new IOException("Artifact cache file must be private, owned and single-link");
        }
        void check() throws IOException {
            cancellation.check();
            if((System.nanoTime()-started)/1000000>=options.totalTimeoutMillis) throw new java.net.SocketTimeoutException("Artifact acquisition deadline expired");
        }
        int timeout(int limit) throws IOException {
            check();
            return (int)Math.max(1,Math.min(limit,options.totalTimeoutMillis-(System.nanoTime()-started)/1000000));
        }
    }
    private static URI https(URI url) throws IOException {
        if(url==null || !"https".equals(url.getScheme()) || url.getHost()==null || url.getHost().isEmpty()
                || url.getRawUserInfo()!=null || url.getRawFragment()!=null || url.getPort()==0 || url.getPort()>65535
                || url.toASCIIString().length()>8192 || url.toASCIIString().matches("(?i).*%0[ad].*"))
            throw new IOException("A bounded absolute HTTPS URL without credentials or fragments is required");
        return url;
    }
    private static boolean exists(Path path) throws IOException {
        try { Files.readAttributes(path,java.nio.file.attribute.BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS); return true; }
        catch(NoSuchFileException absent) { return false; }
    }
    private static java.nio.file.attribute.FileAttribute<Set<java.nio.file.attribute.PosixFilePermission>> permissions(String mode) {
        return PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString(mode));
    }
    private static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch(NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static String hex(byte[] bytes) {
        StringBuilder value=new StringBuilder(); for(byte b:bytes) value.append(String.format(Locale.ROOT,"%02x",b&255)); return value.toString();
    }
}
