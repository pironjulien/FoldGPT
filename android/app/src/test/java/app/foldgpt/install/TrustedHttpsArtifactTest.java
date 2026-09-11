package app.foldgpt.install;

import com.sun.net.httpserver.*;
import javax.net.ssl.*;
import java.io.*;
import java.net.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.*;
import static org.junit.Assert.*;

/** Real local HTTPS and unprivileged cache/process tests. The test JVM receives
 * only its generated test-CA truststore. Production has no TLS override hook. */
public class TrustedHttpsArtifactTest {
    static final TrustedHttpsArtifact.Storage STORAGE=new TrustedHttpsArtifact.Storage() {
        public String identity(Path path) throws IOException {
            return Files.getAttribute(path,"unix:dev",LinkOption.NOFOLLOW_LINKS)+":"+Files.getAttribute(path,"unix:ino",LinkOption.NOFOLLOW_LINKS);
        }
        public long linkCount(Path path) throws IOException { return ((Number)Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS)).longValue(); }
        public int mode(Path path) throws IOException { return ((Number)Files.getAttribute(path,"unix:mode",LinkOption.NOFOLLOW_LINKS)).intValue()&07777; }
        public void finishCreatedDirectory(Path path,String expectedIdentity) throws IOException {
            Object owner=Files.getAttribute(path,"unix:uid",LinkOption.NOFOLLOW_LINKS),group=Files.getAttribute(path,"unix:gid",LinkOption.NOFOLLOW_LINKS);
            if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !expectedIdentity.equals(identity(path)) || (mode(path)&~02700)!=0)
                throw new IOException("New test-storage directory identity or mode differs");
            Files.setAttribute(path,"unix:mode",0700,LinkOption.NOFOLLOW_LINKS);
            if(!expectedIdentity.equals(identity(path)) || mode(path)!=0700
                    || !owner.equals(Files.getAttribute(path,"unix:uid",LinkOption.NOFOLLOW_LINKS))
                    || !group.equals(Files.getAttribute(path,"unix:gid",LinkOption.NOFOLLOW_LINKS)))
                throw new IOException("New test-storage directory private mode was not retained");
            syncDirectory(path);
        }
        public void syncDirectory(Path path) throws IOException { try(FileChannel channel=FileChannel.open(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) { channel.force(true); } }
    };
    static final TrustedHttpsArtifact.Options OPTIONS=new TrustedHttpsArtifact.Options(3000,1500,15000);
    static final TrustedHttpsArtifact.Progress SILENT=(count,total) -> {};
    final List<Path> owned=new ArrayList<>();
    final List<HttpsServer> servers=new ArrayList<>();
    final List<ExecutorService> executors=new ArrayList<>();
    final byte[] body=new byte[1024*1024+37];
    Path cache;
    HttpsServer server;
    AtomicInteger requests=new AtomicInteger();
    List<String> ranges=Collections.synchronizedList(new ArrayList<>());
    volatile String mode="normal";
    CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);

    @Before public void setup() throws Exception {
        assertNotEquals("Run actual private cache tests as a nonroot user",0,((Number)Files.getAttribute(Path.of("/proc/self"),"unix:uid")).intValue());
        new Random(1534).nextBytes(body); cache=temporary();
        server=server(Path.of(System.getProperty("foldgpt.test.keyStore")));
        server.createContext("/artifact",exchange -> {
            requests.incrementAndGet(); String range=exchange.getRequestHeaders().getFirst("Range"); ranges.add(range==null?"-":range);
            try {
                if(mode.equals("hold")) {
                    exchange.sendResponseHeaders(200,body.length); exchange.getResponseBody().write(body,0,65536); exchange.getResponseBody().flush();
                    entered.countDown(); release.await(8,TimeUnit.SECONDS); return;
                }
                if(mode.equals("short")) {
                    mode="normal"; exchange.sendResponseHeaders(200,body.length); exchange.getResponseBody().write(body,0,131072); return;
                }
                if(mode.equals("encoding")) exchange.getResponseHeaders().set("Content-Encoding","gzip");
                if(mode.equals("extra")) {
                    exchange.sendResponseHeaders(200,0); exchange.getResponseBody().write(body); exchange.getResponseBody().write(1); return;
                }
                int start=range==null || mode.equals("ignore-range")?0:Integer.parseInt(range.substring(6,range.length()-1));
                if(start>0) exchange.getResponseHeaders().set("Content-Range",mode.equals("bad-range")?"bytes 0-3/4":
                    "bytes "+start+"-"+(body.length-1)+"/"+body.length);
                exchange.sendResponseHeaders(start>0?206:200,body.length-start);
                byte[] data=mode.equals("wrong-hash")?new byte[body.length]:body;
                exchange.getResponseBody().write(data,start,data.length-start);
            } catch(Exception expectedDuringInterruptedTests) {
                // Truncated exchanges and killed clients really close TLS sockets.
            } finally { exchange.close(); }
        });
        server.start();
    }
    @After public void cleanup() throws Exception {
        release.countDown(); for(HttpsServer item:servers) item.stop(0);
        for(ExecutorService executor:executors) { executor.shutdownNow(); executor.awaitTermination(5,TimeUnit.SECONDS); }
        for(Path root:owned) try(var paths=Files.walk(root)) {
            for(Path path:paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
        }
    }
    Path temporary() throws IOException { Path path=Files.createTempDirectory("foldgpt-https-"); owned.add(path); return path; }
    HttpsServer server(Path keys) throws Exception {
        KeyStore store=KeyStore.getInstance("PKCS12");
        try(InputStream input=Files.newInputStream(keys)) { store.load(input,"foldgpt-test-only".toCharArray()); }
        KeyManagerFactory managers=KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()); managers.init(store,"foldgpt-test-only".toCharArray());
        SSLContext tls=SSLContext.getInstance("TLS"); tls.init(managers.getKeyManagers(),null,null);
        HttpsServer value=HttpsServer.create(new InetSocketAddress("127.0.0.1",0),0);
        value.setHttpsConfigurator(new HttpsConfigurator(tls));
        ExecutorService executor=Executors.newCachedThreadPool(); executors.add(executor); value.setExecutor(executor);
        servers.add(value); return value;
    }
    URI url(String path) { return URI.create("https://localhost:"+server.getAddress().getPort()+path); }
    TrustedHttpsArtifact.Descriptor descriptor() throws Exception { return new TrustedHttpsArtifact.Descriptor(url("/artifact"),body.length,hash(body)); }
    Path directory(TrustedHttpsArtifact.Descriptor value) { return cache.resolve("foldgpt-acquisition").resolve(value.key); }
    TrustedHttpsArtifact.Result acquire(TrustedHttpsArtifact.Descriptor value) throws IOException {
        return TrustedHttpsArtifact.acquire(cache,value,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE);
    }
    static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    static void refused(Callable<?> operation) throws Exception {
        try { operation.call(); fail("Unsafe or incomplete acquisition was accepted"); }
        catch(IOException expected) {}
    }
    static void privateFile(Path path,byte[] bytes) throws IOException {
        Files.write(path,bytes,StandardOpenOption.CREATE_NEW); Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));
    }

    @Test public void exactHttpsBytesAreVerifiedPublishedAndRevalidatedWithoutNetwork() throws Exception {
        var descriptor=descriptor(); var result=acquire(descriptor);
        assertArrayEquals(body,Files.readAllBytes(result.file)); assertEquals(0,result.resumedFrom);
        assertEquals(1,requests.get()); assertFalse(Files.exists(directory(descriptor).resolve("download.part")));
        assertEquals(PosixFilePermissions.fromString("rw-------"),Files.getPosixFilePermissions(result.file));
        String inode=STORAGE.identity(result.file);
        assertEquals(inode,STORAGE.identity(acquire(descriptor).file)); assertEquals(1,requests.get());
        Files.write(result.file,new byte[body.length]);
        refused(() -> acquire(descriptor)); assertEquals(1,requests.get()); assertArrayEquals(new byte[body.length],Files.readAllBytes(result.file));
    }
    @Test public void actualSetgidParentYieldsExactPrivateDirectoriesWithoutChangingParent() throws Exception {
        Files.setAttribute(cache,"unix:mode",02771,LinkOption.NOFOLLOW_LINKS);
        assertEquals(02771,STORAGE.mode(cache));
        String parentIdentity=STORAGE.identity(cache);
        Object parentUid=Files.getAttribute(cache,"unix:uid",LinkOption.NOFOLLOW_LINKS);
        Object parentGid=Files.getAttribute(cache,"unix:gid",LinkOption.NOFOLLOW_LINKS);
        Path inherited=Files.createDirectory(cache.resolve("actual-inheritance"),
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        assertEquals("The regression fixture must actually reproduce kernel setgid inheritance",02700,STORAGE.mode(inherited));
        assertEquals("Java POSIX permissions conceal inherited special bits",PosixFilePermissions.fromString("rwx------"),Files.getPosixFilePermissions(inherited));
        Files.delete(inherited);
        var descriptor=descriptor(); var result=acquire(descriptor);
        assertArrayEquals(body,Files.readAllBytes(result.file));
        assertEquals(0700,STORAGE.mode(cache.resolve("foldgpt-acquisition")));
        assertEquals(0700,STORAGE.mode(directory(descriptor)));
        try(var files=Files.list(directory(descriptor))) {
            for(Path file:files.toList()) assertEquals(0600,STORAGE.mode(file));
        }
        assertEquals(02771,STORAGE.mode(cache)); assertEquals(parentIdentity,STORAGE.identity(cache));
        assertEquals(parentUid,Files.getAttribute(cache,"unix:uid",LinkOption.NOFOLLOW_LINKS));
        assertEquals(parentGid,Files.getAttribute(cache,"unix:gid",LinkOption.NOFOLLOW_LINKS));
        assertEquals(STORAGE.identity(result.file),STORAGE.identity(acquire(descriptor).file)); assertEquals(1,requests.get());
        System.out.println("setgid-parent: actual mkdir=2700; published directories=0700; files=0600; parent=2771 unchanged; uid="+parentUid+" gid="+parentGid);
    }
    @Test public void existingDirectoriesWithSpecialBitsAreRejectedAndPreservedBeforeNetwork() throws Exception {
        var descriptor=descriptor();
        for(String level:List.of("cache","descriptor")) {
            cache=temporary();
            Path root=Files.createDirectory(cache.resolve("foldgpt-acquisition"),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Path target=level.equals("cache")?root:Files.createDirectory(root.resolve(descriptor.key),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Files.setAttribute(target,"unix:mode",02700,LinkOption.NOFOLLOW_LINKS);
            String identity=STORAGE.identity(target); privateFile(target.resolve("existing-evidence"),new byte[]{7,3});
            refused(() -> acquire(descriptor)); assertEquals(0,requests.get());
            assertEquals(02700,STORAGE.mode(target)); assertEquals(identity,STORAGE.identity(target));
            assertArrayEquals(new byte[]{7,3},Files.readAllBytes(target.resolve("existing-evidence")));
        }
    }
    @Test public void specialBitsOnPublishedFilesAreRejectedWithoutRepair() throws Exception {
        var descriptor=descriptor(); Path artifact=acquire(descriptor).file;
        Files.setAttribute(artifact,"unix:mode",02600,LinkOption.NOFOLLOW_LINKS);
        assertEquals(02600,STORAGE.mode(artifact)); String identity=STORAGE.identity(artifact);
        refused(() -> acquire(descriptor)); assertEquals(1,requests.get());
        assertEquals(02600,STORAGE.mode(artifact)); assertEquals(identity,STORAGE.identity(artifact));
        assertArrayEquals(body,Files.readAllBytes(artifact));
    }
    @Test public void realTruncatedHttpsResumesAtActualPrivatePartialLength() throws Exception {
        var descriptor=descriptor(); mode="short"; refused(() -> acquire(descriptor));
        Path partial=directory(descriptor).resolve("download.part"); long actual=Files.size(partial);
        assertTrue(actual>0 && actual<body.length); assertFalse(Files.exists(directory(descriptor).resolve("verified.artifact")));
        var result=acquire(descriptor);
        assertEquals(actual,result.resumedFrom); assertEquals("bytes="+actual+"-",ranges.get(1));
        assertArrayEquals(body,Files.readAllBytes(result.file));
    }
    @Test public void serverIgnoringRangeRestartsFromZeroAndHashesWholeArtifact() throws Exception {
        var descriptor=descriptor(); mode="short"; refused(() -> acquire(descriptor)); mode="ignore-range";
        var result=acquire(descriptor); assertEquals(0,result.resumedFrom); assertArrayEquals(body,Files.readAllBytes(result.file));
    }
    @Test public void inconsistentRangeCannotAppendOrPublish() throws Exception {
        var descriptor=descriptor(); mode="short"; refused(() -> acquire(descriptor));
        Path partial=directory(descriptor).resolve("download.part"); byte[] original=Files.readAllBytes(partial);
        mode="bad-range"; refused(() -> acquire(descriptor)); assertArrayEquals(original,Files.readAllBytes(partial));
        assertFalse(Files.exists(directory(descriptor).resolve("verified.artifact")));
        mode="normal"; assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file));
    }
    @Test public void wrongHashAndOversizedBodyDiscardOnlyOwnedPartialAndNeverPublish() throws Exception {
        var descriptor=descriptor();
        for(String failure:List.of("wrong-hash","extra","encoding")) {
            mode=failure; refused(() -> acquire(descriptor));
            assertFalse(Files.exists(directory(descriptor).resolve("verified.artifact")));
            assertFalse(Files.exists(directory(descriptor).resolve("download.part")));
        }
        mode="normal"; assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file));
    }
    @Test public void platformTlsRejectsUntrustedCertificateAndWrongHostname() throws Exception {
        HttpsServer untrusted=server(Path.of(System.getProperty("foldgpt.test.untrustedKeyStore")));
        AtomicInteger reached=new AtomicInteger();
        untrusted.createContext("/artifact",exchange -> { reached.incrementAndGet(); exchange.close(); }); untrusted.start();
        var foreign=new TrustedHttpsArtifact.Descriptor(URI.create("https://localhost:"+untrusted.getAddress().getPort()+"/artifact"),body.length,hash(body));
        try { acquire(foreign); fail("Untrusted certificate accepted"); }
        catch(SSLHandshakeException expected) {}
        assertEquals(0,reached.get());
        // The trusted test certificate has DNS:localhost only, not an IP SAN.
        var wrongName=new TrustedHttpsArtifact.Descriptor(URI.create("https://127.0.0.1:"+server.getAddress().getPort()+"/artifact"),body.length,hash(body));
        try { acquire(wrongName); fail("Wrong TLS hostname accepted"); }
        catch(SSLHandshakeException expected) {}
        assertEquals(0,requests.get());
    }
    @Test public void boundedHttpsRedirectsWorkButDowngradeAndLoopsFail() throws Exception {
        server.createContext("/redirect",exchange -> { exchange.getResponseHeaders().set("Location","/artifact"); exchange.sendResponseHeaders(302,-1); exchange.close(); });
        server.createContext("/downgrade",exchange -> { exchange.getResponseHeaders().set("Location","http://localhost:1/unrequested"); exchange.sendResponseHeaders(302,-1); exchange.close(); });
        server.createContext("/loop",exchange -> { exchange.getResponseHeaders().set("Location","/loop"); exchange.sendResponseHeaders(302,-1); exchange.close(); });
        var redirected=new TrustedHttpsArtifact.Descriptor(url("/redirect"),body.length,hash(body));
        assertArrayEquals(body,Files.readAllBytes(acquire(redirected).file));
        for(String path:List.of("/downgrade","/loop")) refused(() -> acquire(new TrustedHttpsArtifact.Descriptor(url(path),body.length,hash(body))));
        assertEquals(1,requests.get());
    }
    @Test public void explicitCancellationReleasesSocketLeaseAndPreservesResumableBytes() throws Exception {
        var descriptor=descriptor(); mode="hold"; var token=new TrustedHttpsArtifact.Cancellation();
        ExecutorService executor=Executors.newSingleThreadExecutor(); executors.add(executor);
        Future<?> running=executor.submit(() -> {
            try { TrustedHttpsArtifact.acquire(cache,descriptor,OPTIONS,token,SILENT,STORAGE); throw new AssertionError("Cancelled download completed"); }
            catch(InterruptedIOException expected) { return; }
            catch(IOException unexpected) { throw new RuntimeException(unexpected); }
        });
        assertTrue(entered.await(5,TimeUnit.SECONDS));
        refused(() -> acquire(descriptor)); // The same JVM cannot bypass its descriptor lease.
        token.cancel(); running.get(5,TimeUnit.SECONDS); release.countDown(); mode="normal";
        assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file));
    }
    @Test public void threadInterruptionAndTotalDeadlineNeverPublish() throws Exception {
        var descriptor=descriptor();
        Thread.currentThread().interrupt();
        try { refused(() -> acquire(descriptor)); } finally { Thread.interrupted(); }
        assertEquals(0,requests.get());
        mode="hold";
        long started=System.nanoTime();
        try {
            TrustedHttpsArtifact.acquire(cache,descriptor,new TrustedHttpsArtifact.Options(1000,5000,250),
                new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE);
            fail("Stalled TLS body exceeded the total deadline without failure");
        } catch(SocketTimeoutException expected) {}
        assertTrue("Overall deadline did not clip the longer read timeout",TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-started)<2000);
        assertFalse(Files.exists(directory(descriptor).resolve("verified.artifact")));
    }
    @Test public void immutableDescriptorAndCacheAliasesCannotBeAdopted() throws Exception {
        for(String source:List.of("http://localhost/file","https://user:secret@localhost/file","https://localhost/file#fragment", "https://localhost/%0Avalue"))
            refused(() -> new TrustedHttpsArtifact.Descriptor(URI.create(source),body.length,hash(body)));
        refused(() -> new TrustedHttpsArtifact.Descriptor(url("/artifact"),0,hash(body)));
        var descriptor=descriptor(); mode="short"; refused(() -> acquire(descriptor));
        Path directory=directory(descriptor),metadata=directory.resolve("descriptor.v1");
        byte[] original=Files.readAllBytes(metadata); Files.writeString(metadata,"untrusted descriptor\n");
        refused(() -> acquire(descriptor)); assertEquals(1,requests.get()); Files.write(metadata,original);
        Path partial=directory.resolve("download.part"),outside=cache.resolve("outside");
        privateFile(outside,"untouched".getBytes(StandardCharsets.US_ASCII)); Files.delete(partial); Files.createSymbolicLink(partial,outside);
        refused(() -> acquire(descriptor)); assertEquals("untouched",Files.readString(outside));
        Files.delete(partial); Files.createLink(partial,outside); refused(() -> acquire(descriptor)); assertEquals("untouched",Files.readString(outside));
    }
    @Test public void sameBytesFromDifferentTrustedUrlsHaveSeparateCacheBindings() throws Exception {
        var first=descriptor(); var second=new TrustedHttpsArtifact.Descriptor(url("/artifact?revision=2"),body.length,hash(body));
        assertNotEquals(first.key,second.key);
        assertNotEquals(acquire(first).file,acquire(second).file); assertEquals(2,requests.get());
    }
    @Test public void interruptionBeforePublicationRecoversOnlyAfterRehashAndNeverReplacesCollision() throws Exception {
        var descriptor=descriptor();
        refused(() -> TrustedHttpsArtifact.acquire(cache,descriptor,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE,
            point -> { if(point.equals("part-verified")) throw new IOException("Injected interruption after real SHA verification"); }));
        assertEquals(body.length,Files.size(directory(descriptor).resolve("download.part")));
        assertFalse(Files.exists(directory(descriptor).resolve("verified.artifact")));
        assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file)); assertEquals(1,requests.get());
        Path other=temporary();
        Path collision=other.resolve("foldgpt-acquisition").resolve(descriptor.key).resolve("verified.artifact");
        refused(() -> TrustedHttpsArtifact.acquire(other,descriptor,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE,
            point -> { if(point.equals("part-verified")) privateFile(collision,"existing stays".getBytes(StandardCharsets.US_ASCII)); }));
        assertEquals("existing stays",Files.readString(collision));
    }
    @Test public void descriptorPublicationInterruptionIsRecoverableWithoutAdoptingUnboundData() throws Exception {
        var descriptor=descriptor();
        refused(() -> TrustedHttpsArtifact.acquire(cache,descriptor,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE,
            point -> { if(point.equals("descriptor-ready")) throw new IOException("Injected descriptor publication interruption"); }));
        assertEquals(0,requests.get()); assertTrue(Files.exists(directory(descriptor).resolve("descriptor.next")));
        assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file));
        Files.delete(directory(descriptor).resolve("descriptor.v1"));
        refused(() -> acquire(descriptor)); assertEquals(1,requests.get());
    }
    @Test public void interruptionAfterRenameRevalidatesActualArtifactAndRejectsCompetingPartial() throws Exception {
        var descriptor=descriptor();
        refused(() -> TrustedHttpsArtifact.acquire(cache,descriptor,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE,
            point -> { if(point.equals("artifact-published")) throw new IOException("Injected interruption before directory sync"); }));
        Path artifact=directory(descriptor).resolve("verified.artifact");
        assertArrayEquals(body,Files.readAllBytes(acquire(descriptor).file)); assertEquals(1,requests.get());
        privateFile(directory(descriptor).resolve("download.part"),new byte[]{1});
        refused(() -> acquire(descriptor)); assertArrayEquals(body,Files.readAllBytes(artifact));
    }
    @Test public void privateCacheDirectoryAliasesAndUnknownFilesAreRefusedBeforeNetwork() throws Exception {
        var descriptor=descriptor(); Path alias=cache.resolve("alias"); Files.createSymbolicLink(alias,cache);
        refused(() -> TrustedHttpsArtifact.acquire(alias,descriptor,OPTIONS,new TrustedHttpsArtifact.Cancellation(),SILENT,STORAGE));
        Path entry=cache.resolve("foldgpt-acquisition"); Files.createDirectory(entry);
        Files.setPosixFilePermissions(entry,PosixFilePermissions.fromString("rwxr-xr-x"));
        refused(() -> acquire(descriptor)); assertEquals(0,requests.get());
        Files.setPosixFilePermissions(entry,PosixFilePermissions.fromString("rwx------"));
        Path slot=entry.resolve(descriptor.key); Files.createDirectory(slot,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        privateFile(slot.resolve("unbound-input"),new byte[]{1});
        refused(() -> acquire(descriptor)); assertEquals(0,requests.get());
        assertArrayEquals(new byte[]{1},Files.readAllBytes(slot.resolve("unbound-input")));
    }
    @Test public void processDeathReleasesCrossProcessLeaseAndResumesRealHttpsPartial() throws Exception {
        var descriptor=descriptor(); Path marker=cache.resolve("child-progress");
        List<String> command=new ArrayList<>(List.of(Path.of(System.getProperty("java.home"),"bin/java").toString(),
            "-Djavax.net.ssl.trustStore="+System.getProperty("javax.net.ssl.trustStore"),
            "-Djavax.net.ssl.trustStorePassword=foldgpt-test-only","-cp",System.getProperty("java.class.path"),
            TrustedHttpsArtifactTest.class.getName(),cache.toString(),descriptor.url.toString(),Long.toString(descriptor.bytes),descriptor.sha256,marker.toString()));
        Process child=new ProcessBuilder(command).redirectErrorStream(true).redirectOutput(cache.resolve("child-output").toFile()).start();
        try {
            long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
            while(!Files.exists(marker) && child.isAlive() && System.nanoTime()<end) Thread.sleep(10);
            assertTrue("Child failed before actual bytes: "+Files.readString(cache.resolve("child-output")),Files.exists(marker));
            refused(() -> acquire(descriptor)); // A distinct process owns the lease.
            child.destroyForcibly(); assertTrue(child.waitFor(5,TimeUnit.SECONDS));
        } finally { if(child.isAlive()) { child.destroyForcibly(); child.waitFor(5,TimeUnit.SECONDS); } }
        long count=Files.size(directory(descriptor).resolve("download.part")); assertTrue(count>0 && count<body.length);
        var result=acquire(descriptor); assertEquals(count,result.resumedFrom); assertArrayEquals(body,Files.readAllBytes(result.file));
    }
    public static void main(String[] args) throws Exception {
        var input=new TrustedHttpsArtifact.Descriptor(URI.create(args[1]),Long.parseLong(args[2]),args[3]);
        TrustedHttpsArtifact.acquire(Path.of(args[0]),input,OPTIONS,new TrustedHttpsArtifact.Cancellation(),(count,total) -> {
            Files.writeString(Path.of(args[4]),Long.toString(count));
            try { Thread.sleep(60000); } catch(InterruptedException interrupted) { Thread.currentThread().interrupt(); throw new InterruptedIOException("Test child interrupted"); }
        },STORAGE);
    }
}
