package app.foldgpt;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.system.Os;
import android.util.Log;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.concurrent.TimeUnit;

/** Debug-only fixed GNU process-policy diagnostic in a real Zygote process.
 * Constructor paths and commands come from APK assets, never an Intent.
 */
public final class NativeGnuManagedProbeService extends Service {
    private static final String CHANNEL="foldgpt-gnu-managed-probe";
    private static final String[] SOURCES={
        "tools/executor/exec_server.py", "tools/executor/native_files.py",
        "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
        "tools/executor/native_files_rpc_fixture.py", "tools/executor/native_process_policy.py",
        "tools/executor/native_processes.py", "tools/executor/native_environment.py",
        "tools/executor/native_environment_unicode.py",
        "tools/executor/gnu-runtime/gnu_process_adapter.py",
        "tools/executor/gnu-runtime/gnu_runtime_capacity.py",
        "tools/executor/gnu-runtime/gnu_runtime_address.py",
        "tools/executor/gnu-runtime/test_gnu_process_adapter.py",
        "tools/executor/gnu-runtime/managed_android_fixture.py"
    };
    private final Handler handler=new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        if(running) return START_NOT_STICKY;
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"FoldGPT GNU process diagnostic",NotificationManager.IMPORTANCE_LOW));
        startForeground(1631,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT GNU execution diagnostic")
            .setContentText("Checking native command execution and file policies").setOngoing(true).build());
        running=true;
        new Thread(() -> {
            Process process=null;
            Path evidence=null;
            PowerManager.WakeLock wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:GnuManagedProbe");
            try {
                wake.acquire(TimeUnit.MINUTES.toMillis(6));
                evidence=Files.createTempDirectory(getCacheDir().getCanonicalFile().toPath(),"gm-");
                Os.chmod(evidence.toString(),0700);
                NativeProbeFiles inputs=new NativeProbeFiles(this);
                Path sources=evidence.resolve("sources"),python=evidence.resolve("python");
                inputs.sources("gnu-managed-probe",sources,SOURCES);
                inputs.python(python);
                Files.createDirectory(evidence.resolve("home"));
                Files.createDirectory(evidence.resolve("tmp"));
                Path nativeRoot=Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
                Path guestRoot=getFilesDir().toPath().resolve("debian").toRealPath();
                if(!Files.isDirectory(guestRoot)) throw new IOException("Installed GNU runtime is absent");
                for(String name:new String[]{"libfoldgpt_python.so","libfoldgpt-gnu-managed.so",
                        "libfoldgpt-native-files.so","libfoldgpt-strict-proot.so",
                        "libproot-loader.so","libproot-loader32.so","libtalloc.so","libandroid-shmem.so"})
                    if(!Files.isRegularFile(nativeRoot.resolve(name))) throw new IOException("Missing GNU diagnostic input: "+name);
                ProcessBuilder builder=new ProcessBuilder(nativeRoot.resolve("libfoldgpt_python.so").toString(),
                    "--home",python.toString(),"--",sources.resolve("tools/executor/gnu-runtime/managed_android_fixture.py").toString(),
                    "--runner",nativeRoot.resolve("libfoldgpt-gnu-managed.so").toString(),
                    "--files-helper",nativeRoot.resolve("libfoldgpt-native-files.so").toString(),
                    "--proot",nativeRoot.resolve("libfoldgpt-strict-proot.so").toString(),
                    "--loader",nativeRoot.resolve("libproot-loader.so").toString(),
                    "--loader32",nativeRoot.resolve("libproot-loader32.so").toString(),
                    "--rootfs",guestRoot.toString(),"--evidence",evidence.toString(),
                    "--uid",Integer.toString(android.os.Process.myUid()),"--android-runtime-address-budget");
                builder.directory(evidence.toFile()); builder.environment().clear();
                builder.environment().put("PATH","/system/bin"); builder.environment().put("LANG","C.UTF-8");
                builder.environment().put("HOME",evidence.resolve("home").toString());
                builder.environment().put("TMPDIR",evidence.resolve("tmp").toString());
                builder.redirectErrorStream(true).redirectOutput(evidence.resolve("fixture-output.txt").toFile());
                process=builder.start();
                process.getOutputStream().close();
                if(!process.waitFor(300,TimeUnit.SECONDS)) throw new IOException("GNU process diagnostic deadline exceeded");
                if(process.exitValue()!=0) throw new IOException("GNU process diagnostic failed: exit="+process.exitValue());
                Files.writeString(evidence.resolve("android-completion.txt"),"PASS uid="+android.os.Process.myUid()+"\n",StandardOpenOption.CREATE_NEW);
                Log.i("FoldGPT-GnuManaged","PASS evidence="+evidence);
            } catch(Exception error) {
                Log.e("FoldGPT-GnuManaged","FAIL evidence="+evidence,error);
            } finally {
                if(process!=null && process.isAlive()) {
                    process.destroy();
                    try {
                        if(!process.waitFor(15,TimeUnit.SECONDS)) Log.e("FoldGPT-GnuManaged","Native GNU cleanup did not finish");
                    } catch(InterruptedException error) { Thread.currentThread().interrupt(); }
                    if(process.isAlive()) {
                        boolean interrupted=Thread.interrupted();
                        for(;;) {
                            try {process.waitFor();break;}
                            catch(InterruptedException error) {interrupted=true;}
                        }
                        if(interrupted)Thread.currentThread().interrupt();
                    }
                }
                if(wake.isHeld()) wake.release();
                handler.post(() -> {running=false;if(stopSelfResult(latestStartId))stopForeground(STOP_FOREGROUND_REMOVE);});
            }
        },"FoldGPT-gnu-managed-probe").start();
        return START_NOT_STICKY;
    }
}
