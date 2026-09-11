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
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;

/** Fixed offline GNU guest bridge to a native Android broker, in private test
 * directories. No account, model request, live profile or arbitrary Intent
 * command/path is accepted. The installed Debian tree supplies runtime files. */
public final class NativePrivateExecProbeService extends Service {
    private static final String CHANNEL="foldgpt-private-exec-probe";
    private static final String[] SOURCES={
        "tools/executor/exec_server.py", "tools/executor/native_files.py",
        "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
        "tools/executor/native_files_rpc_fixture.py",
        "tools/executor/native_file_streams.py",
        "tools/executor/private_exec_broker.py", "tools/executor/private_exec_fixture.py"
    };
    private final Handler mainHandler=new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;
    private long assetBytes;
    private int assetFiles;

    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStartId=startId;
        if(running) return START_NOT_STICKY;
        NotificationManager notifications=getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL,
            "FoldGPT private execution transport diagnostic",NotificationManager.IMPORTANCE_LOW));
        startForeground(1621,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT private transport diagnostic")
            .setContentText("Testing the guest bridge and native file broker")
            .setOngoing(true).build());
        running=true;
        new Thread(() -> {
            Process process=null;
            Path evidence=null;
            PowerManager.WakeLock wake=getSystemService(PowerManager.class).newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:PrivateExecProbe");
            wake.acquire(TimeUnit.SECONDS.toMillis(150));
            try {
                // A short canonical prefix keeps the AF_UNIX path below108bytes.
                evidence=Files.createTempDirectory(getCacheDir().getCanonicalFile().toPath(),"pex-");
                Os.chmod(evidence.toString(),0700);
                Path sourceRoot=evidence.resolve("sources");
                for(String relative:SOURCES) {
                    Path target=sourceRoot.resolve(relative);
                    Files.createDirectories(target.getParent());
                    try(InputStream input=getAssets().open("private-exec-probe/"+relative)) {
                        byte[] data=input.readNBytes(1048577);
                        if(data.length>1048576) throw new IOException("Diagnostic source exceeds bound");
                        Files.write(target,data,StandardOpenOption.CREATE_NEW);
                    }
                }
                assetBytes=0; assetFiles=0;
                Path pythonHome=evidence.resolve("python");
                copyAssets("native-python",pythonHome);
                Path nativeDirectory=Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
                Path root=new File(getFilesDir(),"debian").getCanonicalFile().toPath();
                if(!Files.isDirectory(root)) throw new IOException("Installed Debian runtime is absent");
                for(String name:List.of("libfoldgpt_python.so","libfoldgpt-native-files.so",
                        "libfoldgpt_file_handle.so",
                        "libfoldgpt-exec-bridge.so","libproot.so","libproot-loader.so","libtalloc.so"))
                    if(!Files.isRegularFile(nativeDirectory.resolve(name))) throw new IOException("APK diagnostic library absent: "+name);
                Path compat=Files.createDirectory(evidence.resolve("native"));
                Files.createSymbolicLink(compat.resolve("libtalloc.so.2"),nativeDirectory.resolve("libtalloc.so"));
                Files.createDirectory(evidence.resolve("shm"));
                String ids=android.os.Process.myUid()+":"+Os.getgid();
                List<String> bridge=new ArrayList<>(List.of(nativeDirectory.resolve("libproot.so").toString(),
                    "--kill-on-exit","--link2symlink","--sysvipc","-r",root.toString(),"-i",ids,"-w","/workspace"));
                for(String system:List.of("/dev","/proc","/sys","/system","/apex")) { bridge.add("-b"); bridge.add(system); }
                for(String binding:List.of(evidence.resolve("tmp")+":/tmp",evidence.resolve("shm")+":/dev/shm",
                        evidence.resolve("ipc")+":/tmp/foldgpt-private-ipc",evidence.resolve("workspace")+":/workspace",
                        evidence.resolve("home")+":/tmp/foldgpt-private-home",
                        nativeDirectory.resolve("libfoldgpt-exec-bridge.so")+":/tmp/foldgpt-exec-bridge")) {
                    bridge.add("-b"); bridge.add(binding);
                }
                bridge.addAll(List.of("/usr/bin/env","-i","PATH=/usr/bin:/bin","HOME=/tmp/foldgpt-private-home",
                    "LANG=C.UTF-8","/tmp/foldgpt-exec-bridge"));
                Path bridgeCommand=evidence.resolve("bridge-command.json");
                Files.writeString(bridgeCommand,new JSONArray(bridge).toString()+"\n",StandardOpenOption.CREATE_NEW);
                ProcessBuilder builder=new ProcessBuilder(nativeDirectory.resolve("libfoldgpt_python.so").toString(),
                    "--home",pythonHome.toString(),"--",sourceRoot.resolve("tools/executor/private_exec_fixture.py").toString(),
                    "--helper",nativeDirectory.resolve("libfoldgpt-native-files.so").toString(),
                    "--handle-helper",nativeDirectory.resolve("libfoldgpt_file_handle.so").toString(),
                    "--evidence",evidence.toString(),"--android-home",pythonHome.toString(),
                    "--android-uid",Integer.toString(android.os.Process.myUid()),
                    "--bridge-command-file",bridgeCommand.toString(),"--guest-socket","/tmp/foldgpt-private-ipc/exec.sock");
                builder.directory(evidence.toFile()); builder.environment().clear();
                builder.environment().put("PATH","/system/bin"); builder.environment().put("LANG","C.UTF-8");
                builder.environment().put("HOME",evidence.resolve("home").toString());
                builder.environment().put("TMPDIR",evidence.resolve("tmp").toString());
                builder.environment().put("LD_LIBRARY_PATH",compat+":"+nativeDirectory);
                builder.environment().put("PROOT_LOADER",nativeDirectory.resolve("libproot-loader.so").toString());
                builder.environment().put("PROOT_LOADER_32",nativeDirectory.resolve("libproot-loader32.so").toString());
                builder.environment().put("PROOT_TMP_DIR",evidence.resolve("tmp").toString());
                process=builder.redirectErrorStream(true).redirectOutput(evidence.resolve("fixture-output.txt").toFile()).start();
                process.getOutputStream().close();
                if(!process.waitFor(90,TimeUnit.SECONDS)) throw new IOException("Private transport fixture exceeded deadline");
                if(process.exitValue()!=0 || !Files.isRegularFile(evidence.resolve("report.json")))
                    throw new IOException("Private transport fixture failed: exit="+process.exitValue());
                Files.writeString(evidence.resolve("android-completion.txt"),"PASS uid="+android.os.Process.myUid()+"\n",
                    StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
                Log.i("FoldGPT-PrivateExec","PASS evidence="+evidence);
            } catch(Exception error) {
                Log.e("FoldGPT-PrivateExec","FAIL evidence="+evidence,error);
            } finally {
                if(process!=null && process.isAlive()) {
                    process.destroy();
                    try {
                        if(!process.waitFor(15,TimeUnit.SECONDS)) Log.e("FoldGPT-PrivateExec","Diagnostic cleanup did not finish");
                    } catch(InterruptedException error) { Thread.currentThread().interrupt(); }
                }
                if(wake.isHeld()) wake.release();
                mainHandler.post(() -> { running=false; if(stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE); });
            }
        },"FoldGPT-private-exec-probe").start();
        return START_NOT_STICKY;
    }
    private void copyAssets(String source,Path target) throws IOException {
        String[] names=getAssets().list(source);
        if(names==null) throw new IOException("Missing native Python assets");
        if(names.length>0) {
            Files.createDirectory(target);
            for(String name:names) {
                if(name.isEmpty() || name.equals(".") || name.equals("..") || name.contains("/") || name.contains("\\"))
                    throw new IOException("Invalid asset component");
                copyAssets(source+"/"+name,target.resolve(name));
            }
        } else {
            if(++assetFiles>20000) throw new IOException("Native Python asset count exceeds bound");
            try(InputStream input=getAssets().open(source);var output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)) {
                byte[] buffer=new byte[65536]; int count;
                while((count=input.read(buffer))!=-1) {
                    assetBytes+=count;
                    if(assetBytes>256L*1024*1024) throw new IOException("Native Python assets exceed bound");
                    output.write(buffer,0,count);
                }
            }
        }
    }
}
