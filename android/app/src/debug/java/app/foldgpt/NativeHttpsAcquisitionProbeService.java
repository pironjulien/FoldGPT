package app.foldgpt;

import android.app.Application;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.ComponentName;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.TrafficStats;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.StrictMode;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.Log;
import app.foldgpt.install.AndroidInactiveClientInstaller;
import app.foldgpt.install.AndroidTrustedHttpsArtifact;
import app.foldgpt.install.TrustedHttpsArtifact;
import java.io.File;
import java.io.FileDescriptor;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.json.JSONArray;
import org.json.JSONObject;

/** DUMP-only fixed official-package HTTPS/cache diagnostic in its own process.
 * Every invocation owns a fresh private cache. No Intent URL, path, descriptor,
 * credential or command is consumed. This service never invokes an installer,
 * rootfs transaction, vault, client, activation or an existing profile.
 */
public final class NativeHttpsAcquisitionProbeService extends Service {
    private static final String TAG="FoldGPT-HttpsProbe",CHANNEL="foldgpt-https-acquisition-probe";
    private static final String ACTION="app.foldgpt.action.PROBE_HTTPS_ACQUISITION";
    private static final int NOTIFICATION=1627;
    // New input authenticated through the retained official key, InRelease,
    // Packages and package signature; see tools/install/https-acquisition/README.md.
    // The existing installed client and inactive v3 descriptor are unchanged.
    private static final String CLIENT_VERSION="26.901.51231";
    private static final String CLIENT_SHA="02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0";
    private static final long CLIENT_BYTES=388605714L,CLIENT_TAR_BYTES=1365708800L;
    private static final int CLIENT_MEMBERS=7360;
    private static final int DOWNLOAD_DEADLINE=(int)TimeUnit.MINUTES.toMillis(20);
    private static final int CACHE_DEADLINE=(int)TimeUnit.MINUTES.toMillis(3);
    private static final long SERVICE_DEADLINE=TimeUnit.MINUTES.toMillis(25);
    private final Handler main=new Handler(Looper.getMainLooper());
    private final Object lifecycle=new Object();
    private final AtomicBoolean cancelled=new AtomicBoolean(),disconnectSent=new AtomicBoolean();
    private volatile Thread worker;
    private volatile TrustedHttpsArtifact.Cancellation acquisition;
    private volatile boolean finishing;
    private volatile String cancellationReason="-";
    private int latestStartId;
    private final Runnable deadline=() -> cancel("SERVICE_DEADLINE");

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        try {
            requireFixedInvocation(intent);
            ServiceInfo declared=getPackageManager().getServiceInfo(new ComponentName(this,getClass()),0);
            String process=getPackageName()+":httpsAcquisitionProbe";
            if(!"android.permission.DUMP".equals(declared.permission) || !declared.exported
                    || !process.equals(declared.processName) || !process.equals(Application.getProcessName()))
                throw new IOException("HTTPS probe requires its DUMP-only isolated-process manifest declaration");
        } catch(Exception failure) {
            Log.e(TAG,"Refused probe invocation or manifest: "+failure.getClass().getSimpleName());
            if(worker==null) stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        if(worker!=null) return START_NOT_STICKY;
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,
            "Diagnostic HTTPS du client officiel",NotificationManager.IMPORTANCE_LOW));
        startForeground(NOTIFICATION,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT — diagnostic HTTPS")
            .setContentText("Téléchargement vérifié dans un cache de test isolé")
            .setOngoing(true).build());
        cancelled.set(false); disconnectSent.set(false); cancellationReason="-"; finishing=false;
        worker=new Thread(this::runProbe,"FoldGPT-https-acquisition-probe");
        worker.start();
        return START_NOT_STICKY;
    }

    private static void requireFixedInvocation(Intent intent) throws IOException {
        if(intent==null || intent.getData()!=null || intent.getClipData()!=null || intent.getSelector()!=null
                || intent.getCategories()!=null && !intent.getCategories().isEmpty()
                || intent.getExtras()!=null && !intent.getExtras().isEmpty()
                || intent.getAction()!=null && !ACTION.equals(intent.getAction()))
            throw new IOException("HTTPS probe accepts only its fixed no-argument invocation");
    }

    private void cancel(String reason) {
        TrustedHttpsArtifact.Cancellation token;
        synchronized(lifecycle) {
            if(finishing) return;
            cancellationReason=reason; cancelled.set(true);
            Thread current=worker;
            if(current!=null) current.interrupt();
            token=acquisition;
        }
        if(token!=null && disconnectSent.compareAndSet(false,true)) {
            // disconnect() can wait for platform socket state; never do this
            // blocking work on Android's lifecycle/main thread.
            Thread cleanup=new Thread(token::cancel,"FoldGPT-https-probe-disconnect");
            cleanup.setDaemon(true); cleanup.start();
        }
    }

    @Override public void onDestroy() {
        main.removeCallbacks(deadline);
        if(worker!=null) cancel("SERVICE_DESTROYED");
        super.onDestroy();
    }

    private void check(long started) throws IOException {
        if(cancelled.get() || Thread.currentThread().isInterrupted()) throw new InterruptedIOException("HTTPS probe cancelled");
        if(SystemClock.elapsedRealtime()-started>=SERVICE_DEADLINE) throw new java.net.SocketTimeoutException("HTTPS probe total deadline expired");
    }

    private void runProbe() {
        long started=SystemClock.elapsedRealtime();
        Path evidence=null,isolatedCache=null;
        PowerManager.WakeLock wake=null;
        String phase="private-cache",status="FAIL";
        JSONObject report=new JSONObject();
        AtomicLong firstCallbacks=new AtomicLong(),firstReceived=new AtomicLong(),secondCallbacks=new AtomicLong();
        try {
            report.put("schema","foldgpt.https-acquisition-probe.v1")
                .put("scope","official-client-https-acquisition-and-cache-revalidation-only")
                .put("runId",UUID.randomUUID().toString()).put("status","RUNNING")
                .put("uid",android.os.Process.myUid()).put("gid",Os.getgid()).put("pid",android.os.Process.myPid())
                .put("process",Application.getProcessName()).put("androidApi",Build.VERSION.SDK_INT)
                .put("startedElapsedRealtimeMillis",started)
                .put("downloadDeadlineMillis",DOWNLOAD_DEADLINE).put("cacheDeadlineMillis",CACHE_DEADLINE)
                .put("serviceDeadlineMillis",SERVICE_DEADLINE)
                .put("trustedClientVersion",CLIENT_VERSION).put("trustedClientSha256",CLIENT_SHA)
                .put("trustedClientBytes",CLIENT_BYTES).put("trustedClientTarBytes",CLIENT_TAR_BYTES)
                .put("trustedClientMembers",CLIENT_MEMBERS)
                .put("sourceDeclaration","AndroidInactiveClientInstaller.Descriptor.sourceUrl")
                .put("installationAttempted",false).put("activationAttempted",false)
                .put("liveProfileAccessAttempted",false).put("keyringAccessAttempted",false)
                .put("tlsConfiguration","platform-default-trust-and-hostname-verification")
                .put("cacheNetworkGuardPassed",false);
            check(started);
            Path managedCache=getCacheDir().getCanonicalFile().toPath();
            StructStat managedBefore=owned(managedCache);
            evidence=Files.createTempDirectory(managedCache,"https-",
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            finishCreatedDirectory(evidence); syncDirectory(managedCache);
            isolatedCache=Files.createDirectory(evidence.resolve("acquisition-cache"),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            finishCreatedDirectory(isolatedCache); syncDirectory(evidence);
            StructStat managedAfter=owned(managedCache);
            if(managedBefore.st_dev!=managedAfter.st_dev || managedBefore.st_ino!=managedAfter.st_ino
                    || managedBefore.st_uid!=managedAfter.st_uid || managedBefore.st_gid!=managedAfter.st_gid
                    || managedBefore.st_mode!=managedAfter.st_mode)
                throw new IOException("Managed Android cache identity, ownership or mode changed");
            report.put("evidenceLeaf",evidence.getFileName().toString()).put("evidenceIdentity",identity(evidence))
                .put("cacheIdentity",identity(isolatedCache)).put("cacheInitiallyEmpty",empty(isolatedCache))
                .put("managedCacheBefore",metadata(managedBefore)).put("managedCacheAfter",metadata(managedAfter))
                .put("managedCacheIdentityOwnerModePreserved",true).put("evidenceDirectory",metadata(owned(evidence)));
            if(!report.getBoolean("cacheInitiallyEmpty")) throw new IOException("New diagnostic acquisition cache is not empty");
            writeJson(evidence.resolve("report.json"),report);
            Log.i(TAG,"RUNNING evidence="+evidence);
            wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:HttpsAcquisitionProbe");
            wake.acquire(SERVICE_DEADLINE+TimeUnit.SECONDS.toMillis(30));
            main.postDelayed(deadline,SERVICE_DEADLINE);

            File cacheDirectory=isolatedCache.toFile();
            Context isolated=new ContextWrapper(this) {
                @Override public File getCacheDir() { return cacheDirectory; }
            };
            AndroidInactiveClientInstaller.Descriptor client=new AndroidInactiveClientInstaller.Descriptor(
                CLIENT_VERSION,CLIENT_SHA,CLIENT_BYTES,CLIENT_TAR_BYTES,CLIENT_MEMBERS);
            phase="actual-https-acquisition";
            long firstStarted=SystemClock.elapsedRealtime(); JSONObject firstTraffic=traffic();
            Path progressFile=evidence.resolve("progress.json");
            AtomicLong lastProgressWrite=new AtomicLong(firstStarted);
            acquisition=new TrustedHttpsArtifact.Cancellation(); check(started);
            TrustedHttpsArtifact.Result first=AndroidTrustedHttpsArtifact.acquireClient(isolated,client,
                new TrustedHttpsArtifact.Options(15000,30000,DOWNLOAD_DEADLINE),acquisition,(bytes,total) -> {
                    check(started);
                    long previous=firstReceived.getAndSet(bytes);
                    if(total!=CLIENT_BYTES || bytes<=previous || bytes>total) throw new IOException("Unexpected real acquisition progress");
                    firstCallbacks.incrementAndGet();
                    long now=SystemClock.elapsedRealtime();
                    if(bytes==total || now-lastProgressWrite.get()>=TimeUnit.SECONDS.toMillis(5)) {
                        lastProgressWrite.set(now);
                        try { writeJson(progressFile,new JSONObject().put("schema","foldgpt.https-acquisition-progress.v1")
                            .put("received",bytes).put("expected",total).put("elapsedMillis",now-firstStarted)); }
                        catch(IOException error) { throw error; }
                        catch(Exception error) { throw new IOException("Could not retain structural acquisition progress",error); }
                    }
                });
            acquisition=null;
            check(started);
            if(first.resumedFrom!=0 || firstCallbacks.get()==0 || firstReceived.get()!=CLIENT_BYTES
                    || first.descriptor.bytes!=CLIENT_BYTES || !CLIENT_SHA.equals(first.descriptor.sha256))
                throw new IOException("Fresh acquisition did not return the exact trusted full download");
            requireArtifactPath(first.file,isolatedCache,first.descriptor.key);
            report.put("sourceUrl",first.descriptor.url.toASCIIString()).put("descriptorCacheKey",first.descriptor.key)
                .put("artifactRelativePath",evidence.relativize(first.file).toString())
                .put("firstAcquireMillis",SystemClock.elapsedRealtime()-firstStarted)
                .put("firstResumedFrom",first.resumedFrom).put("firstUidTraffic",trafficDelta(firstTraffic,traffic()));

            phase="independent-first-file-verification";
            JSONObject firstFile=inspectArtifact(first.file,started);
            report.put("firstFile",firstFile);
            verifyArtifact(firstFile);
            writeJson(evidence.resolve("report.json"),report);

            phase="guarded-cache-revalidation";
            long secondStarted=SystemClock.elapsedRealtime(); JSONObject secondTraffic=traffic();
            StrictMode.ThreadPolicy original=StrictMode.getThreadPolicy();
            TrustedHttpsArtifact.Result second;
            acquisition=new TrustedHttpsArtifact.Cancellation(); check(started);
            try {
                // The real component must return through its verified-cache
                // branch. Android throws on Java network access in this worker
                // while this guard is active; no TLS policy or trust is changed.
                StrictMode.setThreadPolicy(new StrictMode.ThreadPolicy.Builder(original)
                    .detectNetwork().penaltyDeathOnNetwork().build());
                second=AndroidTrustedHttpsArtifact.acquireClient(isolated,client,
                    new TrustedHttpsArtifact.Options(15000,30000,CACHE_DEADLINE),acquisition,(bytes,total) -> {
                        secondCallbacks.incrementAndGet();
                        throw new IOException("Verified cache unexpectedly requested another download body");
                    });
            } finally { StrictMode.setThreadPolicy(original); acquisition=null; }
            check(started);
            report.put("cacheAcquireMillis",SystemClock.elapsedRealtime()-secondStarted)
                .put("cacheNetworkGuard","worker-only-StrictMode-detectNetwork-penaltyDeathOnNetwork")
                .put("cacheNetworkGuardPassed",true)
                .put("secondUidTraffic",trafficDelta(secondTraffic,traffic()));
            if(!first.file.equals(second.file) || !first.descriptor.key.equals(second.descriptor.key)
                    || secondCallbacks.get()!=0 || second.resumedFrom!=0)
                throw new IOException("Second acquisition did not reuse the exact verified artifact");

            phase="independent-cache-file-verification";
            JSONObject secondFile=inspectArtifact(second.file,started); report.put("secondFile",secondFile);
            verifyArtifact(secondFile);
            if(!firstFile.getString("identity").equals(secondFile.getString("identity"))
                    || !firstFile.getString("sha256").equals(secondFile.getString("sha256")))
                throw new IOException("Cached artifact identity or independently hashed bytes changed");
            report.put("sameArtifactInode",true).put("cacheReuseVerified",true);
            if(Files.exists(second.file.getParent().resolve("download.part"),LinkOption.NOFOLLOW_LINKS))
                throw new IOException("A partial remains next to the published artifact");
            check(started); phase="complete"; status="PASS";
        } catch(Throwable failure) {
            status=cancelled.get()?"CANCELLED":"FAIL";
            try { report.put("errors",errors(failure)); }
            catch(Exception ignored) { Log.e(TAG,"Unable to format diagnostic error type="+failure.getClass().getName()); }
            Log.e(TAG,status+" phase="+phase+" evidence="+evidence+" type="+failure.getClass().getName());
        } finally {
            // FileChannel treats a pending interrupt as an instruction to close
            // its FD. Record cancellation, then clear it for the final private
            // evidence writes; lifecycle callbacks no longer interrupt here.
            synchronized(lifecycle) { finishing=true; Thread.interrupted(); acquisition=null; }
            main.removeCallbacks(deadline);
            try {
                if(cancelled.get() && status.equals("PASS")) status="CANCELLED";
                report.put("status",status).put("phase",phase).put("durationMillis",SystemClock.elapsedRealtime()-started)
                    .put("cancellationReason",cancellationReason).put("firstProgressCallbacks",firstCallbacks.get())
                    .put("firstReceivedBytes",firstReceived.get()).put("secondProgressCallbacks",secondCallbacks.get())
                    .put("workerFinalizationReached",true)
                    .put("uidTrafficScope","shared-app-uid-counter-not-an-http-request-counter");
                if(isolatedCache!=null) {
                    try { report.put("cacheInventory",inventory(isolatedCache)); }
                    catch(Exception failure) {
                        report.put("cacheInventoryErrors",errors(failure));
                        if(status.equals("PASS")) { status="FAIL"; phase="final-cache-inventory"; }
                    }
                }
                report.put("status",status).put("phase",phase);
                if(evidence!=null) {
                    String reportHash=writeJson(evidence.resolve("report.json"),report);
                    writePrivate(evidence.resolve("android-completion.txt"),
                        (status+" uid="+android.os.Process.myUid()+" reportSha256="+reportHash+"\n").getBytes(StandardCharsets.US_ASCII));
                    Log.i(TAG,status+" evidence="+evidence+" reportSha256="+reportHash);
                }
            } catch(Exception failure) {
                Log.e(TAG,"FAIL final evidence write phase="+phase+" evidence="+evidence+" type="+failure.getClass().getName());
            } finally {
                try { if(wake!=null && wake.isHeld()) wake.release(); }
                catch(RuntimeException failure) { Log.e(TAG,"Wake cleanup failed type="+failure.getClass().getName()); }
                finally {
                    main.post(() -> { worker=null; stopForeground(STOP_FOREGROUND_REMOVE); stopSelfResult(latestStartId); });
                }
            }
        }
    }

    private JSONObject inspectArtifact(Path file,long started) throws Exception {
        StructStat before=owned(file);
        if(!OsConstants.S_ISREG(before.st_mode) || before.st_nlink!=1 || (before.st_mode&07777)!=0600)
            throw new IOException("Artifact is not a private single-link regular file");
        MessageDigest digest=MessageDigest.getInstance("SHA-256"); long bytes=0;
        try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer buffer=ByteBuffer.allocate(65536); int count;
            while((count=input.read(buffer))!=-1) {
                check(started); bytes+=count;
                if(bytes>CLIENT_BYTES) throw new IOException("Artifact exceeds the independently trusted byte count");
                buffer.flip(); digest.update(buffer); buffer.clear();
            }
        }
        StructStat after=owned(file);
        if(before.st_dev!=after.st_dev || before.st_ino!=after.st_ino || before.st_size!=after.st_size || bytes!=after.st_size)
            throw new IOException("Artifact changed during independent verification");
        return metadata(after).put("sha256",hex(digest.digest())).put("hashedBytes",bytes);
    }
    private static void verifyArtifact(JSONObject observed) throws Exception {
        if(observed.getLong("size")!=CLIENT_BYTES || observed.getLong("hashedBytes")!=CLIENT_BYTES
                || !CLIENT_SHA.equals(observed.getString("sha256")))
            throw new IOException("Actual official artifact differs from the fixed v3 descriptor; no input is re-authorized");
    }
    private static void requireArtifactPath(Path artifact,Path cache,String key) throws IOException {
        if(key==null || !key.matches("[0-9a-f]{64}")
                || !artifact.equals(cache.resolve("foldgpt-acquisition").resolve(key).resolve("verified.artifact")))
            throw new IOException("Acquisition returned an unexpected private artifact location");
    }
    private static JSONObject traffic() throws Exception {
        int uid=android.os.Process.myUid();
        JSONObject result=new JSONObject();
        try { return result.put("rxBytes",TrafficStats.getUidRxBytes(uid)).put("txBytes",TrafficStats.getUidTxBytes(uid)); }
        catch(RuntimeException unavailable) {
            return result.put("rxBytes",-1).put("txBytes",-1).put("unavailableType",unavailable.getClass().getName());
        }
    }
    private static JSONObject trafficDelta(JSONObject before,JSONObject after) throws Exception {
        JSONObject result=new JSONObject().put("before",before).put("after",after);
        for(String key:List.of("rxBytes","txBytes")) {
            long first=before.getLong(key),second=after.getLong(key);
            result.put(key+"Delta",first<0 || second<first?JSONObject.NULL:second-first);
        }
        return result;
    }
    private static boolean empty(Path directory) throws IOException { try(var entries=Files.list(directory)) { return !entries.findAny().isPresent(); } }
    private static JSONArray inventory(Path cache) throws Exception {
        JSONArray result=new JSONArray(); List<Path> pending=new ArrayList<>(); pending.add(cache);
        for(int index=0;index<pending.size();index++) {
            if(pending.size()>64) throw new IOException("Diagnostic cache inventory exceeds its fixed scope");
            Path path=pending.get(index); StructStat value=owned(path);
            JSONObject row=metadata(value).put("path",cache.equals(path)?".":cache.relativize(path).toString());
            result.put(row);
            if(OsConstants.S_ISDIR(value.st_mode)) {
                if((value.st_mode&07777)!=0700) throw new IOException("Diagnostic cache directory mode differs");
                try(var entries=Files.list(path)) {
                    List<Path> children=entries.limit(65).collect(java.util.stream.Collectors.toList());
                    if(pending.size()+children.size()>64) throw new IOException("Diagnostic cache inventory exceeds its fixed scope");
                    children.sort(Comparator.comparing(item -> item.getFileName().toString()));
                    pending.addAll(children);
                }
            } else if(!OsConstants.S_ISREG(value.st_mode) || value.st_nlink!=1 || (value.st_mode&07777)!=0600)
                throw new IOException("Diagnostic cache contains an unexpected file kind or mode");
        }
        return result;
    }
    private static JSONObject metadata(StructStat value) throws Exception {
        return new JSONObject().put("identity",Long.toUnsignedString(value.st_dev)+":"+Long.toUnsignedString(value.st_ino))
            .put("uid",value.st_uid).put("gid",value.st_gid).put("mode",String.format(Locale.ROOT,"%04o",value.st_mode&07777))
            .put("size",value.st_size).put("links",value.st_nlink)
            .put("kind",OsConstants.S_ISDIR(value.st_mode)?"directory":OsConstants.S_ISREG(value.st_mode)?"file":"other");
    }
    private static JSONArray errors(Throwable failure) throws Exception {
        JSONArray result=new JSONArray();
        for(int count=0;failure!=null && count<8;count++,failure=failure.getCause()) {
            String message=failure.getMessage();
            if(message==null) message="";
            message=message.replaceAll("[\\p{Cntrl}]"," ");
            if(message.length()>512) message=message.substring(0,512);
            result.put(new JSONObject().put("type",failure.getClass().getName()).put("message",message));
        }
        return result;
    }
    private static StructStat owned(Path path) throws IOException {
        try {
            StructStat value=Os.lstat(path.toString());
            if(value.st_uid!=android.os.Process.myUid()) throw new IOException("Diagnostic path is not app-owned");
            return value;
        } catch(ErrnoException error) { throw new IOException("Diagnostic no-follow inspection failed",error); }
    }
    private static String identity(Path path) throws IOException {
        StructStat value=owned(path); return Long.toUnsignedString(value.st_dev)+":"+Long.toUnsignedString(value.st_ino);
    }
    private static void requirePrivateDirectory(Path path) throws IOException {
        StructStat value=owned(path);
        if(!OsConstants.S_ISDIR(value.st_mode) || (value.st_mode&07777)!=0700) throw new IOException("Diagnostic directory must be private");
    }
    /** Only used immediately after this invocation creates the directory. */
    private static void finishCreatedDirectory(Path path) throws IOException {
        StructStat created=owned(path); FileDescriptor fd=null;
        try {
            fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
            StructStat before=Os.fstat(fd);
            if(!OsConstants.S_ISDIR(before.st_mode) || before.st_uid!=android.os.Process.myUid()
                    || before.st_dev!=created.st_dev || before.st_ino!=created.st_ino || (before.st_mode&07777&~02700)!=0)
                throw new IOException("New diagnostic directory identity, owner or initial mode differs");
            Os.fchmod(fd,0700);
            StructStat after=Os.fstat(fd),named=owned(path);
            if(after.st_dev!=created.st_dev || after.st_ino!=created.st_ino
                    || named.st_dev!=created.st_dev || named.st_ino!=created.st_ino
                    || after.st_uid!=before.st_uid || after.st_gid!=before.st_gid
                    || (after.st_mode&07777)!=0700 || (named.st_mode&07777)!=0700)
                throw new IOException("New diagnostic directory private mode was not retained");
            Os.fsync(fd);
        } catch(ErrnoException error) { throw new IOException("New diagnostic directory finalization failed",error); }
        finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("New diagnostic directory close failed",error); } }
    }
    private static void regularReport(Path path) throws IOException {
        StructStat value=owned(path);
        if(!OsConstants.S_ISREG(value.st_mode) || value.st_nlink!=1 || (value.st_mode&07777)!=0600 || value.st_size>65536)
            throw new IOException("Diagnostic report is not private, regular and bounded");
    }
    private static String writeJson(Path target,JSONObject report) throws Exception {
        byte[] bytes=(report.toString()+"\n").getBytes(StandardCharsets.UTF_8);
        if(bytes.length>65536) throw new IOException("Diagnostic report exceeds bound");
        writePrivate(target,bytes); return hex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    private static void writePrivate(Path target,byte[] bytes) throws IOException {
        requirePrivateDirectory(target.getParent());
        Path pending=target.resolveSibling(target.getFileName()+".next");
        if(Files.exists(pending,LinkOption.NOFOLLOW_LINKS)) { regularReport(pending); Files.delete(pending); }
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) regularReport(target);
        try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer data=ByteBuffer.wrap(bytes); while(data.hasRemaining()) output.write(data); output.force(true);
        }
        Files.move(pending,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); syncDirectory(target.getParent());
    }
    private static void syncDirectory(Path path) throws IOException {
        FileDescriptor fd=null;
        try {
            fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
            StructStat value=Os.fstat(fd);
            if(!OsConstants.S_ISDIR(value.st_mode) || value.st_uid!=android.os.Process.myUid()) throw new IOException("Diagnostic sync requires an owned directory");
            Os.fsync(fd);
        } catch(ErrnoException error) { throw new IOException("Diagnostic directory sync failed",error); }
        finally { if(fd!=null) try { Os.close(fd); } catch(ErrnoException error) { throw new IOException("Diagnostic directory close failed",error); } }
    }
    private static String hex(byte[] bytes) {
        StringBuilder text=new StringBuilder(); for(byte value:bytes) text.append(String.format(Locale.ROOT,"%02x",value&255)); return text.toString();
    }
}
