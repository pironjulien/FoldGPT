package app.foldgpt.install;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONArray;
import org.json.JSONObject;

/** Fixed debug probe; register with android.permission.DUMP in its own process.
 * Reuses only .guest-account-probe/files and isolates files/cache/noBackup. No
 * Intent-controlled inputs, live-vault access, key deletion or activation.
 */
public final class InactivePreparationProbeService extends Service {
    private static final String TAG="FoldGPT-InactiveProbe";
    private static final String CHANNEL="foldgpt.inactive-probe";
    private static final int NOTIFICATION=1623;
    // Two 60-second coordinator process deadlines, their bounded cleanup and
    // local metadata work. Existing authenticated extraction must be reused.
    private static final long DEADLINE_MS=180000L;
    private static final long CLEANUP_MARGIN_MS=30000L;
    private static final RootfsExtractor.Spec SPEC=new RootfsExtractor.Spec(
        "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
        327673156L,958101116L,977131520L,20240);
    private static final String INITIALIZER_SHA="f2a11141839bd3a563e7250275cdf307c9b6c8cb4422c5591c693a82036f39c0";
    private static final String SUPERVISOR_SHA="3e46f4318889d8dca20dedbe43b443ed24c8336671bb62bd38feba03fbbf0dff";
    private final Handler main=new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled=new AtomicBoolean();
    private volatile Thread worker;
    private volatile String cancellationReason="-";
    private PowerManager.WakeLock wake;
    private int latestStartId;
    private final Runnable deadline=() -> cancel("DEADLINE");

    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        if(worker!=null) return START_NOT_STICKY;
        NotificationManager notifications=getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL,
            "Diagnostic de préparation privée",NotificationManager.IMPORTANCE_LOW));
        startForeground(NOTIFICATION,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT — préparation privée")
            .setContentText("Vérification isolée du coffre, sans activation")
            .setOngoing(true).build());
        cancelled.set(false); cancellationReason="-";
        wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:InactiveProbe");
        wake.acquire(DEADLINE_MS+CLEANUP_MARGIN_MS);
        worker=new Thread(this::runProbe,"FoldGPT-inactive-probe");
        main.postDelayed(deadline,DEADLINE_MS); worker.start();
        return START_NOT_STICKY;
    }
    private void cancel(String reason) {
        cancellationReason=reason; cancelled.set(true);
        Thread running=worker; if(running!=null) running.interrupt();
        // The coordinator's SecretPipeProcess handles interrupted waits, stops
        // its owned PRoot child, closes the pipes and erases the credential.
    }
    private void checkCancelled() throws InterruptedException {
        if(cancelled.get() || Thread.currentThread().isInterrupted()) throw new InterruptedException("Inactive probe cancelled");
    }
    private void runProbe() {
        long started=SystemClock.elapsedRealtime();
        JSONObject report=new JSONObject(); Path evidence=null;
        String phase="isolated-paths";
        boolean reportOwned=false;
        AtomicInteger archiveOpens=new AtomicInteger();
        try {
            report.put("schema","foldgpt.inactive-preparation-probe.v1").put("runId",UUID.randomUUID().toString())
                .put("status","RUNNING").put("phase",phase).put("uid",android.os.Process.myUid())
                .put("gid",Os.getgid()).put("pid",android.os.Process.myPid()).put("activationAttempted",false)
                .put("archiveSha256",SPEC.sha256).put("initializerSha256",INITIALIZER_SHA)
                .put("supervisorSha256",SUPERVISOR_SHA);
            Path appFiles=getFilesDir().toPath().toRealPath();
            Path base=appFiles.resolve(".guest-account-probe"); requirePrivateDirectory(base);
            Path files=base.resolve("files"); requirePrivateDirectory(files);
            // Only public, hash-pinned source artifacts are read from app cache.
            // Never call this Service's getNoBackupFilesDir or open its vault.
            Path stagedInputs=getCacheDir().toPath().toRealPath();
            Path archive=stagedInputs.resolve("rootfs-probe-input.tar.gz");
            Path initializer=stagedInputs.resolve("inactive-initialize.py");
            Path supervisor=stagedInputs.resolve("inactive-supervise.py");
            Path cache=base.resolve("cache"),noBackup=base.resolve("noBackup");
            privateDirectory(cache); privateDirectory(noBackup); syncDirectory(base);
            evidence=base.resolve("inactive-report.json");
            Path lockPath=base.resolve("inactive-probe.lock");
            if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)) requireRegular(lockPath,true,8192);
            try(FileChannel channel=FileChannel.open(lockPath,Set.of(StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                FileLock lease=channel.tryLock()) {
                requireRegular(lockPath,true,8192);
                if(lease==null) throw new IOException("Another inactive probe holds the lease");
                reportOwned=true;
                Context isolated=new ContextWrapper(this) {
                    @Override public File getFilesDir() { return files.toFile(); }
                    @Override public File getCacheDir() { return cache.toFile(); }
                    @Override public File getNoBackupFilesDir() { return noBackup.toFile(); }
                };
                if(!isolated.getFilesDir().toPath().toRealPath().equals(files)
                        || !isolated.getCacheDir().toPath().toRealPath().equals(cache)
                        || !isolated.getNoBackupFilesDir().toPath().toRealPath().equals(noBackup)
                        || files.equals(cache) || files.equals(noBackup) || cache.equals(noBackup))
                    throw new IOException("Probe Context did not isolate every private directory");
                report.put("isolatedFiles",files.toString()).put("isolatedCache",cache.toString())
                    .put("isolatedNoBackup",noBackup.toString());
                writeReport(evidence,report);
                Log.i(TAG,"START evidence="+evidence);
                checkCancelled();
                phase="prepared-root-preflight";
                Path root=assertPrepared(isolated,null);
                String rootIdentity=identity(root);
                report.put("root",root.toString()).put("rootIdentity",rootIdentity).put("initialState","PREPARED");
                // These exact local paths are the only possible source inputs.
                // The existing PREPARED receipt must make opening the archive
                // unnecessary; both real coordinator calls count any opening.
                requireRegular(archive,false,SPEC.compressedBytes);
                if(Files.size(archive)!=SPEC.compressedBytes) throw new IOException("Probe archive size differs");
                requireRegular(initializer,false,1048576); requireRegular(supervisor,false,1048576);
                RootfsTransaction.ArchiveSource source=() -> {
                    if(cancelled.get() || Thread.currentThread().isInterrupted()) throw new IOException("Probe archive read cancelled");
                    archiveOpens.incrementAndGet();
                    return Files.newInputStream(archive,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS);
                };
                phase="first-preparation"; report.put("phase",phase); writeReport(evidence,report);
                AndroidInactivePreparation.Result first=AndroidInactivePreparation.prepare(isolated,SPEC,source,
                    initializer,INITIALIZER_SHA,supervisor,SUPERVISOR_SHA);
                checkCancelled();
                assertPrepared(isolated,root);
                if(!first.root.equals(root) || !identity(root).equals(rootIdentity)) throw new IOException("First preparation replaced the existing root");
                Path ciphertext=noBackup.resolve("foldgpt-keyring/keyring-password.v1");
                Path journal=files.resolve(".foldgpt-install/fresh/inactive-preparation.v1");
                String vaultHash=hash(ciphertext,8256),journalHash=hash(journal,8192);
                report.put("firstInstallationId",first.installationId).put("firstCollectionInstallationId",first.collectionInstallationId)
                    .put("firstState","PREPARED").put("isolatedCiphertextSha256",vaultHash)
                    .put("coordinatorJournalSha256",journalHash).put("guestUid",first.account.uid).put("guestGid",first.account.gid);
                phase="second-preparation"; report.put("phase",phase); writeReport(evidence,report);
                AndroidInactivePreparation.Result second=AndroidInactivePreparation.prepare(isolated,SPEC,source,
                    initializer,INITIALIZER_SHA,supervisor,SUPERVISOR_SHA);
                checkCancelled();
                assertPrepared(isolated,root);
                if(!first.root.equals(second.root) || !rootIdentity.equals(identity(second.root))
                        || !first.installationId.equals(second.installationId)
                        || !first.collectionInstallationId.equals(second.collectionInstallationId)
                        || first.account.uid!=second.account.uid || first.account.gid!=second.account.gid
                        || !first.account.user.equals(second.account.user)
                        || !vaultHash.equals(hash(ciphertext,8256)) || !journalHash.equals(hash(journal,8192))
                        || archiveOpens.get()!=0)
                    throw new IOException("Repeated inactive preparation changed its root, account, vault, collection or source usage");
                report.put("secondInstallationId",second.installationId).put("secondCollectionInstallationId",second.collectionInstallationId)
                    .put("secondState","PREPARED").put("sameRoot",true).put("sameInstallation",true).put("sameCollection",true)
                    .put("sameCiphertext",true).put("sameCoordinatorJournal",true).put("successfulPrepareCalls",2)
                    .put("archiveOpens",archiveOpens.get()).put("status","PASS").put("phase","verified")
                    .put("elapsedMillis",SystemClock.elapsedRealtime()-started);
                writeReport(evidence,report);
                Log.i(TAG,"PASS evidence="+evidence);
            }
        } catch(Exception failure) {
            // Record structural diagnostics only: no exception/RPC payload,
            // environment, source content or credential is copied into logs.
            boolean interrupted=Thread.interrupted();
            try {
                report.put("status",cancelled.get() || failure instanceof InterruptedException?"CANCELLED":"FAIL")
                    .put("phase",phase).put("errorType",failure.getClass().getName())
                    .put("cancellationReason",cancellationReason).put("archiveOpens",archiveOpens.get())
                    .put("elapsedMillis",SystemClock.elapsedRealtime()-started);
                if(failure instanceof SecretPipeProcess.ProcessFailure) {
                    SecretPipeProcess.ProcessFailure process=(SecretPipeProcess.ProcessFailure)failure;
                    report.put("processExit",process.exitCode).put("processStage",process.stage.name())
                        .put("processCode",process.code.name()).put("processOutputBytes",process.capturedOutputBytes);
                }
                JSONArray frames=new JSONArray();
                for(StackTraceElement frame:failure.getStackTrace()) {
                    if(frames.length()==8) break;
                    frames.put(frame.getClassName()+"."+frame.getMethodName()+":"+frame.getLineNumber());
                }
                report.put("errorAt",frames);
                if(evidence!=null && reportOwned) writeReport(evidence,report);
            } catch(Exception reporting) { Log.e(TAG,"Inactive probe report failed: "+reporting.getClass().getSimpleName()); }
            finally { if(interrupted) Thread.currentThread().interrupt(); }
            Log.e(TAG,"FAIL phase="+phase+" type="+failure.getClass().getSimpleName()+" evidence="+evidence);
        } finally {
            main.removeCallbacks(deadline);
            if(wake!=null && wake.isHeld()) wake.release();
            Thread finished=Thread.currentThread();
            main.post(() -> {
                if(worker!=finished) return;
                worker=null;
                if(stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE);
            });
        }
    }
    private static Path assertPrepared(Context isolated,Path expected) throws Exception {
        Path files=isolated.getFilesDir().toPath();
        if(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS)) throw new IOException("Probe root was unexpectedly activated");
        try(RootfsTransaction transaction=AndroidRootfsTransaction.open(isolated,SPEC)) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Reuse requires an already PREPARED account probe root");
            Path actual=transaction.prepare(() -> { throw new IOException("Prepared root preflight must not extract another base"); }).root;
            if(expected!=null && !expected.equals(actual)) throw new IOException("Prepared root changed across coordinator calls");
            return actual;
        }
    }
    private static void privateDirectory(Path path) throws Exception {
        try { Os.mkdir(path.toString(),0700); }
        catch(ErrnoException error) { if(error.errno!=OsConstants.EEXIST) throw error; }
        requirePrivateDirectory(path);
    }
    private static void requirePrivateDirectory(Path path) throws Exception {
        StructStat info=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid() || (info.st_mode&0077)!=0)
            throw new IOException("Probe directory must be real, private and owned");
    }
    private static void requireRegular(Path path,boolean privateFile,long limit) throws Exception {
        StructStat info=Os.lstat(path.toString());
        if(!OsConstants.S_ISREG(info.st_mode) || info.st_uid!=android.os.Process.myUid() || info.st_nlink!=1
                || (info.st_mode&(privateFile?0077:0022))!=0 || info.st_size>limit)
            throw new IOException("Probe input/report must be an owned, bounded regular file");
    }
    private static String identity(Path path) throws Exception {
        StructStat info=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid()) throw new IOException("Probe root must remain an owned directory");
        return Long.toUnsignedString(info.st_dev)+":"+Long.toUnsignedString(info.st_ino);
    }
    private static String hash(Path path,int limit) throws Exception {
        requireRegular(path,true,limit);
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(FileChannel input=FileChannel.open(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer buffer=ByteBuffer.allocate(limit+1);
            while(buffer.hasRemaining() && input.read(buffer)!=-1) {}
            if(!buffer.hasRemaining()) throw new IOException("Isolated evidence file grew during hashing");
            buffer.flip(); digest.update(buffer);
        }
        StringBuilder text=new StringBuilder(); for(byte value:digest.digest()) text.append(String.format(Locale.ROOT,"%02x",value&255)); return text.toString();
    }
    private static void writeReport(Path target,JSONObject report) throws Exception {
        Path pending=target.resolveSibling("inactive-report.next");
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) requireRegular(target,true,65536);
        if(Files.exists(pending,LinkOption.NOFOLLOW_LINKS)) { requireRegular(pending,true,65536); Files.delete(pending); }
        byte[] value=(report.toString(2)+"\n").getBytes(StandardCharsets.UTF_8);
        if(value.length>65536) throw new IOException("Inactive probe report exceeded bound");
        try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes=ByteBuffer.wrap(value); while(bytes.hasRemaining()) output.write(bytes); output.force(true);
        }
        Files.move(pending,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        syncDirectory(target.getParent());
    }
    private static void syncDirectory(Path path) throws Exception {
        java.io.FileDescriptor descriptor=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
        try {
            StructStat info=Os.fstat(descriptor);
            if(!OsConstants.S_ISDIR(info.st_mode) || info.st_uid!=android.os.Process.myUid()) throw new IOException("Probe sync target differs");
            Os.fsync(descriptor);
        } finally { Os.close(descriptor); }
    }
    @Override public void onDestroy() {
        cancel("SERVICE_DESTROYED"); main.removeCallbacks(deadline); super.onDestroy();
    }
}
