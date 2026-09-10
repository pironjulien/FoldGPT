package app.foldgpt.contextprobe;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.system.Os;
import android.util.Log;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** One fixed app-context probe. No command, path, URI, or extras accepted. */
public final class ContextProbeService extends Service {
    private boolean running;
    private volatile boolean retained;
    private static final String CHANNEL="foldgpt-context-probe";
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if (running) return START_NOT_STICKY;
        if (intent == null || intent.getAction() != null || intent.getData() != null
                || intent.getClipData() != null || intent.getExtras() != null) {
            Log.e("FoldGPT-ContextProbe","Refused nonfixed invocation");
            stopSelf(startId); return START_NOT_STICKY;
        }
        running=true;
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"FoldGPT app-context test",NotificationManager.IMPORTANCE_LOW));
        startForeground(1618,new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT native app-context diagnostic").setContentText("Fixed pipe and PTY test in separate app storage").setOngoing(true).build());
        new Thread(() -> {
            Path evidence=null;
            Process child=null;
            try {
                evidence=Files.createTempDirectory(getFilesDir().toPath(),"probe-");
                Os.chmod(evidence.toString(),0700);
                JSONObject inventory=new JSONObject(new String(asset("inventory.json",2097152),java.nio.charset.StandardCharsets.UTF_8));
                Path nativeRoot=Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
                JSONObject libraries=inventory.getJSONObject("libraries");
                for(java.util.Iterator<String> names=libraries.keys();names.hasNext();) {
                    String name=names.next();
                    if(!name.matches("lib[A-Za-z0-9_.]+\\.so")) throw new IllegalStateException("Invalid library inventory");
                    requireHash(Files.readAllBytes(nativeRoot.resolve(name)),libraries.getString(name));
                }
                JSONObject payload=inventory.getJSONObject("payload");
                for(java.util.Iterator<String> names=payload.keys();names.hasNext();) {
                    String relative=names.next();
                    Path destination=evidence.resolve(relative).normalize();
                    if(!destination.startsWith(evidence) || relative.startsWith("/") || relative.contains("\\")) throw new IllegalStateException("Invalid payload path");
                    byte[] content=asset("payload/"+relative,16777216);
                    requireHash(content,payload.getString(relative));
                    Files.createDirectories(destination.getParent());
                    Files.write(destination,content,StandardOpenOption.CREATE_NEW);
                }
                JSONArray aliases=inventory.getJSONArray("aliases");
                for(int i=0;i<aliases.length();i++) {
                    JSONObject alias=aliases.getJSONObject(i);
                    Path destination=evidence.resolve("python").resolve(alias.getString("path")).normalize();
                    if(!destination.startsWith(evidence.resolve("python"))) throw new IllegalStateException("Invalid alias path");
                    String library=alias.getString("nativeLibrary");
                    if(!libraries.has(library)) throw new IllegalStateException("Unknown alias library");
                    Files.createDirectories(destination.getParent());
                    Os.symlink(nativeRoot.resolve(library).toString(),destination.toString());
                }
                JSONObject identity=new JSONObject().put("pid",android.os.Process.myPid()).put("uid",android.os.Process.myUid())
                    .put("status",Files.readString(Path.of("/proc/self/status"))).put("packageName",getPackageName())
                    .put("cgroup",Files.readString(Path.of("/proc/self/cgroup"))).put("meminfo",Files.readString(Path.of("/proc/meminfo")));
                Files.writeString(evidence.resolve("java-identity.json"),identity.toString(2),StandardOpenOption.CREATE_NEW);
                Files.writeString(evidence.resolve("inventory.json"),inventory.toString(2),StandardOpenOption.CREATE_NEW);
                Files.writeString(getFilesDir().toPath().resolve("latest.txt"),evidence.getFileName().toString()+"\n");
                ProcessBuilder builder=new ProcessBuilder(nativeRoot.resolve("libfoldgpt_python_cli.so").toString(),
                    "-B","-s",evidence.resolve("probe.py").toString());
                builder.directory(evidence.toFile()); builder.environment().clear();
                builder.environment().put("PATH","/system/bin");
                builder.environment().put("LANG","C.UTF-8");
                builder.environment().put("HOME",evidence.toString());
                builder.environment().put("TMPDIR",evidence.toString());
                builder.environment().put("PYTHONHOME",evidence.resolve("python").toString());
                builder.environment().put("PYTHONDONTWRITEBYTECODE","1");
                builder.environment().put("PYTHONNOUSERSITE","1");
                child=builder.redirectErrorStream(true).redirectOutput(evidence.resolve("output.txt").toFile()).start();
                child.getOutputStream().close();
                if(!child.waitFor(90,TimeUnit.SECONDS)) {
                    retained=true;
                    Files.writeString(evidence.resolve("android-timeout.txt"),"FAIL: diagnostic owner retained; no forced kill or claimed cleanup\n",StandardOpenOption.CREATE_NEW);
                    Log.e("FoldGPT-ContextProbe","TIMEOUT owner retained evidence="+evidence);
                    return;
                }
                boolean success=false;
                if(Files.isRegularFile(evidence.resolve("report.json"))) {
                    JSONObject report=new JSONObject(Files.readString(evidence.resolve("report.json")));
                    success=child.exitValue()==0 && report.optBoolean("passed",false) && !report.optBoolean("ownershipRetained",true);
                }
                JSONObject done=new JSONObject().put("passed",success).put("processExit",child.exitValue()).put("pythonReaped",true).put("evidence",evidence.toString());
                Files.writeString(evidence.resolve("android-completion.json"),done.toString(2),StandardOpenOption.CREATE_NEW);
                Log.i("FoldGPT-ContextProbe","COMPLETE exit="+child.exitValue()+" evidence="+evidence);
            } catch(Exception error) {
                if(child!=null && child.isAlive())retained=true;
                Log.e("FoldGPT-ContextProbe","FAIL evidence="+evidence,error);
                if(evidence!=null)try{Files.writeString(evidence.resolve("android-failure.txt"),error.toString(),StandardOpenOption.CREATE_NEW);}catch(Exception ignored){}
            } finally {
                if(!retained) {running=false;stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();}
            }
        },"FoldGPT-app-context").start();
        return START_NOT_STICKY;
    }
    private byte[] asset(String name,int maximum)throws Exception{
        try(InputStream input=getAssets().open(name)){
            byte[] data=input.readNBytes(maximum+1);
            if(data.length>maximum)throw new IllegalStateException("Asset too large");
            return data;
        }
    }
    private static void requireHash(byte[] data,String expected)throws Exception{
        StringBuilder value=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(data))value.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        if(!value.toString().equals(expected))throw new IllegalStateException("Payload hash differs");
    }
}
