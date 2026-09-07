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

/** Fixed real lifecycle backend conformance; no Intent command or policy input.
 * Registered only in debug with DUMP permission and a dedicated process.
 */
public final class NativeProcessRpcProbeService extends Service {
    private static final String CHANNEL="foldgpt-process-rpc-probe";
    private static final String[] SOURCES={
        "tools/executor/exec_server.py", "tools/executor/native_files.py",
        "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
        "tools/executor/native_files_rpc_fixture.py", "tools/executor/native_process_policy.py",
        "tools/executor/native_processes.py", "tools/executor/test_native_processes_live.py",
        "tools/executor/native_environment.py", "tools/executor/native_environment_unicode.py",
        "tools/executor/native_processes_android_fixture.py"
    };
    private static final long ADDRESS_SPACE_BYTES=(33L+1L)<<28;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        if(running) return START_NOT_STICKY;
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"FoldGPT native process lifecycle diagnostic",NotificationManager.IMPORTANCE_LOW));
        startForeground(1628,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT native process lifecycle diagnostic")
            .setContentText("Checking actual native stdin, output, signals and cleanup").setOngoing(true).build());
        running=true;
        new Thread(() -> {
            Process process=null;
            Path evidence=null;
            PowerManager.WakeLock wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:ProcessRpcProbe");
            try {
                wake.acquire(TimeUnit.MINUTES.toMillis(6));
                evidence=Files.createTempDirectory(getCacheDir().getCanonicalFile().toPath(),"pr-");
                Os.chmod(evidence.toString(),0700);
                NativeProbeFiles inputs=new NativeProbeFiles(this);
                Path sources=evidence.resolve("sources"),python=evidence.resolve("python");
                inputs.sources("process-rpc-probe",sources,SOURCES);
                inputs.python(python);
                Files.createDirectory(evidence.resolve("home"));
                Files.createDirectory(evidence.resolve("tmp"));
                Path nativeRoot=Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
                for(String name:new String[]{"libfoldgpt_python.so","libfoldgpt-native-process-runner.so","libfoldgpt-native-process-fixture.so","libfoldgpt-native-files.so"})
                    if(!Files.isRegularFile(nativeRoot.resolve(name))) throw new IOException("Missing process lifecycle native program: "+name);
                ProcessBuilder builder=new ProcessBuilder(nativeRoot.resolve("libfoldgpt_python.so").toString(),
                    "--home",python.toString(),"--",sources.resolve("tools/executor/native_processes_android_fixture.py").toString(),
                    "--runner",nativeRoot.resolve("libfoldgpt-native-process-runner.so").toString(),
                    "--fixture",nativeRoot.resolve("libfoldgpt-native-process-fixture.so").toString(),
                    "--files-helper",nativeRoot.resolve("libfoldgpt-native-files.so").toString(),
                    "--evidence",evidence.toString(),"--uid",Integer.toString(android.os.Process.myUid()),
                    "--address-space-bytes",Long.toString(ADDRESS_SPACE_BYTES));
                builder.directory(evidence.toFile()); builder.environment().clear();
                builder.environment().put("PATH","/system/bin"); builder.environment().put("LANG","C.UTF-8");
                builder.environment().put("HOME",evidence.resolve("home").toString());
                builder.environment().put("TMPDIR",evidence.resolve("tmp").toString());
                process=builder.redirectErrorStream(true).redirectOutput(evidence.resolve("fixture-output.txt").toFile()).start();
                process.getOutputStream().close();
                if(!process.waitFor(240,TimeUnit.SECONDS)) throw new IOException("Lifecycle diagnostic exceeded deadline");
                if(process.exitValue()!=0 || !Files.isRegularFile(evidence.resolve("report.json")))
                    throw new IOException("Lifecycle diagnostic failed: exit="+process.exitValue());
                Files.writeString(evidence.resolve("android-completion.txt"),"PASS uid="+android.os.Process.myUid()+"\n",StandardOpenOption.CREATE_NEW);
                Log.i("FoldGPT-ProcessRpc","PASS evidence="+evidence);
            } catch(Exception error) {
                Log.e("FoldGPT-ProcessRpc","FAIL evidence="+evidence,error);
            } finally {
                if(process!=null && process.isAlive()) {
                    process.destroy();
                    try {
                        if(!process.waitFor(15,TimeUnit.SECONDS)) Log.e("FoldGPT-ProcessRpc","Native lifecycle cleanup did not finish");
                    } catch(InterruptedException error) { Thread.currentThread().interrupt(); }
                }
                if(wake.isHeld()) wake.release();
                handler.post(() -> {running=false;if(stopSelfResult(latestStartId))stopForeground(STOP_FOREGROUND_REMOVE);});
            }
        },"FoldGPT-process-rpc-probe").start();
        return START_NOT_STICKY;
    }
}
