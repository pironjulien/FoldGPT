package app.foldgpt.install;

import android.app.*;
import android.content.*;
import android.os.*;
import android.system.*;
import android.util.Log;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.GeneralSecurityException;
import java.util.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** DUMP-only execution of the actual combined coordinator in one durable,
 * private fixture. Intent carries only fixture UUID/hash, never paths/commands.
 * No runtime activation, live vault access, Android key deletion or migration. */
public final class CombinedPreparationProbeService extends Service {
    private static final String TAG="FoldGPT-CombinedProbe",CHANNEL="foldgpt.combined-probe";
    private static final int NOTIFICATION=1624;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled=new AtomicBoolean();
    private final AtomicInteger archiveOpens=new AtomicInteger();
    private volatile Thread worker;
    private volatile String reason="-";
    private PowerManager.WakeLock wake;
    private int latestStartId;
    private final Runnable deadline=() -> cancel("DEADLINE");
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        if(worker!=null) return START_NOT_STICKY;
        String fixture=intent==null?null:intent.getStringExtra("fixture");
        String digest=intent==null?null:intent.getStringExtra("descriptorSha256");
        if(!CombinedPreparationFixture.validId(fixture) || digest==null || !digest.matches("[0-9a-f]{64}")) {
            Log.e(TAG,"Refused missing or malformed fixture identity"); stopSelf(startId); return START_NOT_STICKY;
        }
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"Diagnostic installation complète inactive",NotificationManager.IMPORTANCE_LOW));
        startForeground(NOTIFICATION,new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT — préparation inactive").setContentText("Client officiel et coffre isolé, sans activation").setOngoing(true).build());
        cancelled.set(false); reason="-"; archiveOpens.set(0);
        worker=new Thread(() -> runFixture(fixture,digest),"FoldGPT-combined-probe"); worker.start();
        return START_NOT_STICKY;
    }
    private void cancel(String value) { reason=value; cancelled.set(true); Thread current=worker; if(current!=null) current.interrupt(); }
    private void checkCancelled() throws InterruptedException {
        if(cancelled.get() || Thread.currentThread().isInterrupted()) throw new InterruptedException("Combined probe cancelled");
    }
    private void runFixture(String fixtureId,String descriptorHash) {
        long started=SystemClock.elapsedRealtime(); String phase="fixture-input";
        JSONObject report=new JSONObject(); Path evidence=null,fixture=null,files=null,noBackup=null;
        CombinedPreparationFixture input=null; Context isolated=null; RootfsExtractor.Spec spec=null;
        FileChannel lockChannel=null; FileLock lease=null;
        try {
            report.put("schema","foldgpt.combined-preparation-probe.v1").put("fixture",fixtureId)
                .put("runId",UUID.randomUUID().toString()).put("descriptorSha256",descriptorHash)
                .put("status","RUNNING").put("activationAttempted",false).put("uid",android.os.Process.myUid()).put("gid",Os.getgid());
            Path appFiles=getFilesDir().toPath().toRealPath(),appCache=getCacheDir().toPath().toRealPath();
            Path inputParent=appCache.resolve("combined-input"); directory(inputParent);
            Path inputs=inputParent.resolve(fixtureId); directory(inputs);
            byte[] descriptor=read(inputs.resolve("fixture.properties"),16384);
            input=CombinedPreparationFixture.parse(descriptor,descriptorHash,fixtureId);
            long total=input.number("totalDeadlineMillis");
            wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:CombinedProbe");
            wake.acquire(total+30000L); main.postDelayed(deadline,total);
            Path parent=appFiles.resolve(".combined-probes"); privateDirectory(parent);
            fixture=parent.resolve(fixtureId); privateDirectory(fixture);
            Path lock=fixture.resolve("probe.lock");
            lockChannel=FileChannel.open(lock,Set.of(StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            regular(lock,8192); lease=lockChannel.tryLock();
            if(lease==null) throw new IOException("Combined fixture is already leased");
            bindFixture(fixture,descriptor);
            Path locations=fixture.resolve("locations.json"),cache;
            if(Files.exists(locations,LinkOption.NOFOLLOW_LINKS)) {
                JSONObject saved=new JSONObject(new String(read(locations,8192),StandardCharsets.UTF_8));
                String leaf=saved.getString("cacheLeaf");
                if(saved.length()!=3 || !leaf.matches("cp-[A-Za-z0-9_-]{1,64}") || !saved.getString("fixtureIdentity").equals(identity(fixture)))
                    throw new IOException("Combined fixture locations differ");
                cache=appCache.resolve(leaf); directory(cache);
                if(!identity(cache).equals(saved.getString("cacheIdentity"))) throw new IOException("Combined cache identity changed");
            } else {
                cache=Files.createTempDirectory(appCache,"cp-",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
                writeJson(locations,new JSONObject().put("cacheLeaf",cache.getFileName().toString())
                    .put("fixtureIdentity",identity(fixture)).put("cacheIdentity",identity(cache)));
            }
            files=fixture.resolve("files"); noBackup=fixture.resolve("noBackup");
            privateDirectory(files); privateDirectory(noBackup); sync(fixture);
            final Path ownFiles=files,ownCache=cache,ownNoBackup=noBackup;
            isolated=new ContextWrapper(this) {
                @Override public File getFilesDir() { return ownFiles.toFile(); }
                @Override public File getCacheDir() { return ownCache.toFile(); }
                @Override public File getNoBackupFilesDir() { return ownNoBackup.toFile(); }
            };
            evidence=fixture.resolve("report.json");
            report.put("files",files.toString()).put("cache",cache.toString()).put("noBackup",noBackup.toString());
            phase="combined-first-call"; report.put("phase",phase); writeJson(evidence,report);
            spec=new RootfsExtractor.Spec(input.get("archiveSha256"),input.number("archiveBytes"),input.number("archivePayloadBytes"),
                input.number("archiveTarBytes"),(int)input.number("archiveMembers"));
            AndroidInactiveClientInstaller.Descriptor clientDescriptor=new AndroidInactiveClientInstaller.Descriptor(input.get("clientVersion"),
                input.get("clientSha256"),input.number("clientBytes"),input.number("clientTarBytes"),(int)input.number("clientMembers"));
            final Path archive=inputs.resolve("base.tar.gz");
            final long archiveBytes=input.number("archiveBytes");
            RootfsTransaction.ArchiveSource source=() -> {
                if(cancelled.get() || Thread.currentThread().isInterrupted()) throw new IOException("Fixture archive cancelled");
                try { regular(archive,archiveBytes); } catch(Exception error) { throw new IOException("Fixture archive rejected",error); }
                archiveOpens.incrementAndGet();
                return Files.newInputStream(archive,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS);
            };
            Path packageFile=inputs.resolve("package.deb");
            if(Files.exists(packageFile,LinkOption.NOFOLLOW_LINKS)) regular(packageFile,input.number("clientBytes")); else packageFile=null;
            AndroidInactivePreparation.ClientInput client=clientInput(input,inputs,clientDescriptor,packageFile);
            checkCancelled();
            AndroidInactivePreparation.Result first=AndroidInactivePreparation.prepare(isolated,spec,source,
                inputs.resolve("initialize_keyring.py"),input.get("initializerSha256"),inputs.resolve("supervise_keyring.py"),input.get("supervisorSha256"),client);
            checkCancelled();
            JSONObject firstSnapshot=snapshot(isolated,spec,first,input);
            report.put("first",firstSnapshot).put("successfulPrepareCalls",1); writeJson(evidence,report);
            int opensBeforeResume=archiveOpens.get();
            phase="combined-source-free-retry"; report.put("phase",phase); writeJson(evidence,report);
            AndroidInactivePreparation.Result second=AndroidInactivePreparation.prepare(isolated,spec,
                () -> { throw new IOException("Second combined call must not open any base source"); },
                inputs.resolve("initialize_keyring.py"),input.get("initializerSha256"),inputs.resolve("supervise_keyring.py"),input.get("supervisorSha256"),
                clientInput(input,inputs,clientDescriptor,null));
            checkCancelled();
            JSONObject secondSnapshot=snapshot(isolated,spec,second,input);
            for(String key:List.of("root","rootIdentity","installationId","collectionInstallationId","clientReportSha256",
                    "packageIdentity","coordinatorSha256","ciphertextSha256","collectionIntentSha256","guestUser","guestUid","guestGid"))
                if(!firstSnapshot.get(key).equals(secondSnapshot.get(key))) throw new IOException("Combined retry changed durable evidence: "+key);
            if(archiveOpens.get()!=opensBeforeResume) throw new IOException("Combined retry reopened base input");
            report.put("second",secondSnapshot).put("successfulPrepareCalls",2).put("sourceFreeRetry",true)
                .put("sameRootAccountClientVaultCollection",true).put("status","PASS").put("phase","verified")
                .put("archiveOpens",archiveOpens.get()).put("elapsedMillis",SystemClock.elapsedRealtime()-started);
            writeJson(evidence,report); Log.i(TAG,"PASS fixture="+fixtureId+" evidence="+evidence);
        } catch(Exception failure) {
            boolean interrupted=Thread.interrupted();
            try {
                boolean locked=failure instanceof GeneralSecurityException && (!getSystemService(UserManager.class).isUserUnlocked()
                    || getSystemService(KeyguardManager.class).isDeviceLocked());
                report.put("status",cancelled.get() || failure instanceof InterruptedException?"CANCELLED":locked?"WAITING_FOR_ANDROID_UNLOCK":"FAIL")
                    .put("phase",phase).put("errorType",failure.getClass().getName()).put("cancellationReason",reason)
                    .put("archiveOpens",archiveOpens.get()).put("elapsedMillis",SystemClock.elapsedRealtime()-started);
                if(isolated!=null && spec!=null && input!=null) {
                    try { report.put("observedInactiveClient",clientEvidence(isolated,spec,input,null)); }
                    catch(Exception absent) { report.put("clientEvidenceUnavailable",absent.getClass().getName()); }
                }
                JSONArray frames=new JSONArray();
                for(StackTraceElement frame:failure.getStackTrace()) { if(frames.length()==8) break; frames.put(frame.getClassName()+"."+frame.getMethodName()+":"+frame.getLineNumber()); }
                report.put("errorAt",frames);
                if(evidence!=null && lease!=null) writeJson(evidence,report);
            } catch(Exception reporting) { Log.e(TAG,"Combined report error: "+reporting.getClass().getSimpleName()); }
            finally { if(interrupted) Thread.currentThread().interrupt(); }
            Log.e(TAG,"Incomplete fixture="+fixtureId+" phase="+phase+" type="+failure.getClass().getSimpleName()+" evidence="+evidence);
        } finally {
            if(lease!=null) try { lease.release(); } catch(IOException error) { Log.e(TAG,"Probe lease release failed"); }
            if(lockChannel!=null) try { lockChannel.close(); } catch(IOException error) { Log.e(TAG,"Probe lease close failed"); }
            main.removeCallbacks(deadline); if(wake!=null && wake.isHeld()) wake.release();
            Thread finished=Thread.currentThread();
            main.post(() -> { if(worker==finished) { worker=null; if(stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE); } });
        }
    }
    private static AndroidInactivePreparation.ClientInput clientInput(CombinedPreparationFixture input,Path inputs,
            AndroidInactiveClientInstaller.Descriptor descriptor,Path source) throws Exception {
        return new AndroidInactivePreparation.ClientInput(descriptor,source,inputs.resolve("official_client_package.py"),input.get("verifierSha256"),
            inputs.resolve("install_official_client.py"),input.get("installerSha256"),input.number("packageDeadlineMillis"));
    }
    private static JSONObject snapshot(Context isolated,RootfsExtractor.Spec spec,AndroidInactivePreparation.Result result,CombinedPreparationFixture input) throws Exception {
        if(result.client==null) throw new IOException("Combined coordinator returned no client evidence");
        JSONObject evidence=clientEvidence(isolated,spec,input,result);
        if(!evidence.getString("coordinatorStep").equals("COLLECTION_PREPARED")) throw new IOException("Combined collection step incomplete");
        Path root=result.root,journal=isolated.getFilesDir().toPath().resolve(".foldgpt-install/fresh/inactive-preparation.v1");
        Map<String,String> fields=journal(journal);
        Path ciphertext=isolated.getNoBackupFilesDir().toPath().resolve("foldgpt-keyring/keyring-password.v1");
        String cipher=hash(ciphertext,8256);
        Path data=root.resolve(result.account.home.substring(1)).resolve(".local/share"); directory(data);
        String intent=hash(data.resolve(".foldgpt-keyring-intent.json"),4096);
        if(!cipher.equals(fields.get("vaultSha256")) || !intent.equals(fields.get("collectionIntentSha256"))
                || !result.collectionInstallationId.equals(fields.get("collectionInstallationId")) || !identity(data).equals(fields.get("dataIdentity")))
            throw new IOException("Actual vault/collection evidence differs from coordinator");
        return evidence.put("ciphertextSha256",cipher).put("collectionIntentSha256",intent)
            .put("collectionInstallationId",result.collectionInstallationId).put("guestUser",result.account.user)
            .put("guestUid",result.account.uid).put("guestGid",result.account.gid);
    }
    private static JSONObject clientEvidence(Context isolated,RootfsExtractor.Spec spec,CombinedPreparationFixture input,AndroidInactivePreparation.Result expected) throws Exception {
        Path files=isolated.getFilesDir().toPath();
        if(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS)) throw new IOException("Combined fixture was activated");
        Path root;
        try(RootfsTransaction transaction=AndroidRootfsTransaction.open(isolated,spec)) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Combined root is not PREPARED");
            root=transaction.prepare(() -> { throw new IOException("Evidence cannot extract a base"); }).root;
        }
        Path journalFile=files.resolve(".foldgpt-install/fresh/inactive-preparation.v1");
        Map<String,String> fields=journal(journalFile);
        if(!fields.getOrDefault("schema","").equals("foldgpt.inactive-preparation.v2")
                || !Set.of("CLIENT_PREPARED","VAULT_PREPARED","COLLECTION_PREPARED").contains(fields.get("step"))
                || !identity(root).equals(fields.get("bind.root"))) throw new IOException("No completed bound client coordinator step");
        Path client=root.resolve("var/lib/foldgpt/client-install"),packageFile=client.resolve("input/package.deb");
        JSONObject receipt=new JSONObject(new String(read(client.resolve("report.json"),1048576),StandardCharsets.UTF_8));
        String reportHash=hash(client.resolve("report.json"),1048576);
        if(!reportHash.equals(fields.get("clientReportSha256")) || !receipt.getString("installationId").equals(fields.get("installationId"))
                || !receipt.getString("rootIdentity").equals(identity(root)) || !receipt.getString("scope").equals("configured-client-package-only")
                || !receipt.getJSONObject("descriptor").getString("sha256").equals(input.get("clientSha256"))
                || !receipt.getJSONObject("installed").getString("version").equals(input.get("clientVersion"))
                || !receipt.getJSONObject("installed").getString("status").equals("install ok installed"))
            throw new IOException("Client report disagrees with actual coordinator evidence");
        if(expected!=null && (!expected.root.equals(root) || !expected.installationId.equals(fields.get("installationId"))
                || !expected.client.reportSha256.equals(reportHash))) throw new IOException("Coordinator result changed");
        regular(packageFile,input.number("clientBytes")); StructStat packageStat=Os.lstat(packageFile.toString());
        return new JSONObject().put("root",root.toString()).put("rootIdentity",identity(root)).put("state","PREPARED")
            .put("coordinatorStep",fields.get("step")).put("installationId",fields.get("installationId"))
            .put("clientReportSha256",reportHash).put("coordinatorSha256",hash(journalFile,8192))
            .put("packageIdentity",Long.toUnsignedString(packageStat.st_dev)+":"+Long.toUnsignedString(packageStat.st_ino));
    }
    private static Map<String,String> journal(Path file) throws Exception {
        String text=new String(read(file,8192),StandardCharsets.US_ASCII); int at=text.lastIndexOf("checksum=");
        if(at<0 || !text.substring(at).equals("checksum="+InactivePreparationJournal.sha256(text.substring(0,at).getBytes(StandardCharsets.US_ASCII))+"\n"))
            throw new IOException("Coordinator journal checksum differs");
        Map<String,String> fields=new HashMap<>();
        for(String line:text.substring(0,at).split("\n")) { int split=line.indexOf('='); if(split<=0 || fields.put(line.substring(0,split),line.substring(split+1))!=null) throw new IOException("Coordinator journal fields differ"); }
        return fields;
    }
    private static void bindFixture(Path fixture,byte[] descriptor) throws Exception {
        Path binding=fixture.resolve("fixture.properties");
        if(Files.exists(binding,LinkOption.NOFOLLOW_LINKS)) {
            if(!Arrays.equals(read(binding,16384),descriptor)) throw new IOException("Existing fixture descriptor changed");
        } else {
            try(var names=Files.list(fixture)) {
                if(names.anyMatch(path -> !Set.of("probe.lock","fixture.properties.next").contains(path.getFileName().toString())))
                    throw new IOException("Existing fixture data has no bound descriptor");
            }
            writeBytes(binding,descriptor);
        }
    }
    private static void privateDirectory(Path path) throws Exception {
        try { Os.mkdir(path.toString(),0700); } catch(ErrnoException error) { if(error.errno!=OsConstants.EEXIST) throw error; }
        directory(path); sync(path.getParent());
    }
    private static void directory(Path path) throws Exception {
        StructStat stat=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(stat.st_mode) || stat.st_uid!=android.os.Process.myUid() || (stat.st_mode&0077)!=0)
            throw new IOException("Fixture directory is not private and owned");
    }
    private static String identity(Path path) throws Exception {
        StructStat stat=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(stat.st_mode) || stat.st_uid!=android.os.Process.myUid()) throw new IOException("Fixture root ownership differs");
        return Long.toUnsignedString(stat.st_dev)+":"+Long.toUnsignedString(stat.st_ino);
    }
    private static void regular(Path path,long limit) throws Exception {
        StructStat stat=Os.lstat(path.toString());
        if(!OsConstants.S_ISREG(stat.st_mode) || stat.st_uid!=android.os.Process.myUid() || stat.st_nlink!=1 || (stat.st_mode&0077)!=0 || stat.st_size>limit)
            throw new IOException("Fixture file is not private, bounded and owned");
    }
    private static byte[] read(Path path,int limit) throws Exception {
        regular(path,limit);
        try(InputStream stream=Files.newInputStream(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            byte[] value=stream.readNBytes(limit+1); if(value.length>limit) throw new IOException("Fixture file grew"); return value;
        }
    }
    private static String hash(Path path,int limit) throws Exception { return InactivePreparationJournal.sha256(read(path,limit)); }
    private static void writeJson(Path path,JSONObject value) throws Exception { writeBytes(path,(value.toString(2)+"\n").getBytes(StandardCharsets.UTF_8)); }
    private static void writeBytes(Path path,byte[] bytes) throws Exception {
        if(bytes.length>65536) throw new IOException("Fixture report bound exceeded");
        Path pending=path.resolveSibling(path.getFileName()+".next");
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)) regular(path,65536);
        if(Files.exists(pending,LinkOption.NOFOLLOW_LINKS)) { regular(pending,65536); Files.delete(pending); }
        try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer value=ByteBuffer.wrap(bytes); while(value.hasRemaining()) output.write(value); output.force(true);
        }
        Files.move(pending,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); sync(path.getParent());
    }
    private static void sync(Path path) throws Exception {
        FileDescriptor fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_CLOEXEC|OsConstants.O_NOFOLLOW,0);
        try { Os.fsync(fd); } finally { Os.close(fd); }
    }
    @Override public void onDestroy() { cancel("SERVICE_DESTROYED"); main.removeCallbacks(deadline); super.onDestroy(); }
}
