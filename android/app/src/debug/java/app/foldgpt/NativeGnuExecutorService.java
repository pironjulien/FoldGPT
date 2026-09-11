package app.foldgpt;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.Log;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Explicit debug integration service, outside the GNU compatibility process.
 * The socket accepts the actual execution protocol with its policies. Intents
 * carry no command, path, UID, runtime or policy selection. Starting this service
 * alone does not change the official client's configuration or environment.
 */
public final class NativeGnuExecutorService extends Service {
    private static final String CHANNEL="foldgpt-gnu-executor";
    private static final String[] SOURCES={
        "tools/executor/exec_server.py", "tools/executor/native_files.py",
        "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
        "tools/executor/native_process_policy.py", "tools/executor/native_processes.py",
        "tools/executor/native_file_streams.py", "tools/executor/native_environment.py",
        "tools/executor/native_environment_unicode.py", "tools/executor/native_executor_backend.py",
        "tools/executor/private_exec_broker.py", "tools/executor/gnu-runtime/gnu_process_adapter.py",
        "tools/executor/gnu-runtime/gnu_runtime_capacity.py",
        "tools/executor/gnu-runtime/gnu_runtime_address.py",
        "tools/executor/gnu-runtime/gnu_executor_broker.py"
    };
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Object ownership=new Object();
    private Process broker;
    private boolean running,stopping;
    private int latestStartId;
    private long generation;
    @Override public IBinder onBind(Intent intent) {return null;}
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if("stop".equals(intent==null?null:intent.getAction())) {
            synchronized(ownership) {
                latestStartId=startId;requestStop();
                if(!running)stopSelfResult(startId);
            }
            return START_NOT_STICKY;
        }
        final long ownedGeneration;
        synchronized(ownership) {
            latestStartId=startId;
            if(running)return START_NOT_STICKY;
            running=true;stopping=false;
            ownedGeneration=++generation;
        }
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"Exécution native FoldGPT",NotificationManager.IMPORTANCE_LOW));
        startForeground(1632,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_manage).setContentTitle("FoldGPT")
            .setContentText("Moteur d’exécution natif actif").setOngoing(true).build());
        new Thread(()->serve(ownedGeneration),"FoldGPT-gnu-executor").start();
        return START_NOT_STICKY;
    }
    private static Path privateDirectory(Path path) throws Exception {
        if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS)) {
            Files.createDirectory(path);Os.chmod(path.toString(),0700);
        }
        StructStat info=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(info.st_mode)||info.st_uid!=android.os.Process.myUid()
                ||(info.st_mode&0077)!=0||!path.equals(path.toRealPath()))
            throw new IOException("Native executor requires an owned private canonical directory");
        return path;
    }
    private void serve(long ownedGeneration) {
        Process child=null;
        Path instance=null;
        try {
            Path files=getFilesDir().getCanonicalFile().toPath();
            Path cache=getCacheDir().getCanonicalFile().toPath();
            Path root=files.resolve("debian").toRealPath();
            Path workspace=privateDirectory(root.resolve("workspace"));
            privateDirectory(workspace.resolve(".home"));
            Path state=privateDirectory(files.resolve("native-executor"));
            Path scratch=privateDirectory(state.resolve("scratch"));
            Path temporary=privateDirectory(state.resolve("guest-tmp"));
            Path x11=cache.resolve("x11").toRealPath();
            Path socket=privateDirectory(x11.resolve("foldgpt-gnu"));
            instance=Files.createTempDirectory(cache,"ge-");Os.chmod(instance.toString(),0700);
            NativeProbeFiles inputs=new NativeProbeFiles(this);
            Path sources=instance.resolve("sources"),python=instance.resolve("python");
            inputs.sources("gnu-executor",sources,SOURCES);inputs.python(python);
            Path home=privateDirectory(instance.resolve("home")),tmp=privateDirectory(instance.resolve("tmp"));
            Path nativeRoot=Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
            String[][] programs={{"helper","libfoldgpt-native-files.so"},
                {"handle-helper","libfoldgpt_file_handle.so"},{"process-runner","libfoldgpt-gnu-managed.so"},
                {"proot","libfoldgpt-strict-proot.so"},{"loader","libproot-loader.so"},
                {"loader32","libproot-loader32.so"}};
            List<String> command=new ArrayList<>(List.of(nativeRoot.resolve("libfoldgpt_python.so").toString(),
                "--home",python.toString(),"--",sources.resolve("tools/executor/gnu-runtime/gnu_executor_broker.py").toString(),
                "--socket-dir",socket.toString(),"--workspace",workspace.toString(),
                "--rootfs",root.toString(),"--scratch",scratch.toString(),"--guest-tmp",temporary.toString(),
                "--peer-uid",Integer.toString(android.os.Process.myUid()),
                "--android-runtime-address-budget"));
            for(String[] program:programs) {
                Path binary=nativeRoot.resolve(program[1]);
                if(!Files.isRegularFile(binary))throw new IOException("Native executor input missing: "+program[1]);
                command.add("--"+program[0]);command.add(binary.toString());
            }
            ProcessBuilder builder=new ProcessBuilder(command);
            builder.directory(instance.toFile());builder.environment().clear();
            builder.environment().put("PATH","/system/bin");builder.environment().put("LANG","C.UTF-8");
            builder.environment().put("HOME",home.toString());builder.environment().put("TMPDIR",tmp.toString());
            builder.redirectErrorStream(true).redirectOutput(instance.resolve("service.log").toFile());
            synchronized(ownership) {
                if(stopping)throw new InterruptedException("Native executor stopped during startup");
                child=builder.start();broker=child;
            }
            child.getOutputStream().close();
            Log.i("FoldGPT-GnuExecutor","Native broker started; instance="+instance);
            int code=child.waitFor();
            Files.writeString(instance.resolve("exit.txt"),"exit="+code+"\n");
            if(code!=0)throw new IOException("Native executor exit="+code);
        } catch(InterruptedException error) {
            Thread.currentThread().interrupt();
        } catch(Exception error) {
            Log.e("FoldGPT-GnuExecutor","Executor failed; instance="+instance,error);
        } finally {
            if(child!=null&&child.isAlive()) {
                child.destroy();
                try {
                    if(!child.waitFor(15,TimeUnit.SECONDS))
                        Log.e("FoldGPT-GnuExecutor","Cleanup pending; persistent session marker retained");
                } catch(InterruptedException error) {Thread.currentThread().interrupt();}
            }
            if(child!=null&&child.isAlive()) {
                // Keep the Process handle and generation owned until its real
                // exit. An elapsed cleanup deadline does not authorize reuse.
                boolean interrupted=Thread.interrupted();
                for(;;) {
                    try {child.waitFor();break;}
                    catch(InterruptedException error) {interrupted=true;}
                }
                if(interrupted)Thread.currentThread().interrupt();
            }
            finishGeneration(ownedGeneration,child);
        }
    }
    private void finishGeneration(long ownedGeneration,Process child) {
        handler.post(()->{
            synchronized(ownership) {
                if(generation!=ownedGeneration||(child!=null&&child.isAlive()))return;
                broker=null;running=false;
                if(stopSelfResult(latestStartId))stopForeground(STOP_FOREGROUND_REMOVE);
            }
        });
    }
    private void requestStop() {
        synchronized(ownership) {stopping=true;if(broker!=null)broker.destroy();}
    }
    @Override public void onDestroy() {requestStop();super.onDestroy();}
}
