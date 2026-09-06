package app.foldgpt.install;

import android.app.*;
import android.content.*;
import android.os.*;
import android.system.*;
import android.util.Log;
import org.json.JSONObject;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Fixed debug integration: authenticate/extract Debian, provision its real
 * account, reopen the lease, then run that guest identity. No activation,
 * account profile, Intent-controlled path/command, network or live-root edit. */
public final class GuestAccountProbeService extends Service {
    private static final RootfsExtractor.Spec SPEC=new RootfsExtractor.Spec(
        "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
        327673156L,958101116L,977131520L,20240);
    private volatile Thread worker;
    private volatile java.lang.Process child;
    private int latestStart;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        latestStart=startId;
        if(worker!=null) return START_NOT_STICKY;
        String channel="foldgpt.account-probe";
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(
            channel,"Diagnostic de l’installation Linux",NotificationManager.IMPORTANCE_LOW));
        startForeground(1622,new Notification.Builder(this,channel).setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT — préparation Linux").setContentText("Vérification dans une installation de test")
            .setOngoing(true).build());
        worker=new Thread(this::run,"FoldGPT-account-probe"); worker.start();
        return START_NOT_STICKY;
    }
    private void run() {
        Path evidence=null; JSONObject report=new JSONObject();
        PowerManager.WakeLock wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:AccountProbe");
        try {
            wake.acquire(600000);
            Path base=getFilesDir().toPath().toRealPath().resolve(".guest-account-probe"); privateDirectory(base);
            Path files=base.resolve("files"); privateDirectory(files);
            evidence=base.resolve("report.json");
            report.put("status","RUNNING").put("uid",android.os.Process.myUid()).put("gid",Os.getgid())
                .put("selinuxContext",Files.readString(Path.of("/proc/self/attr/current")).trim()).put("activationAttempted",false);
            Files.writeString(evidence,report.toString(2));
            Context isolated=new ContextWrapper(this) { @Override public File getFilesDir() { return files.toFile(); } };
            Path root; GuestIdentity identity;
            try(RootfsTransaction transaction=AndroidRootfsTransaction.open(isolated,SPEC)) {
                root=transaction.prepare(() -> Files.newInputStream(getCacheDir().toPath().resolve("rootfs-probe-input.tar.gz"),LinkOption.NOFOLLOW_LINKS)).root;
                identity=AndroidGuestAccountProvisioner.prepare(transaction);
                report.put("root",root.toString()).put("guestUid",identity.uid).put("guestGid",identity.gid).put("guestUser",identity.user);
            }
            try(RootfsTransaction transaction=AndroidRootfsTransaction.open(isolated,SPEC)) {
                transaction.prepare(() -> { throw new IOException("Recovery must not reopen the archive"); });
                GuestIdentity resumed=AndroidGuestAccountProvisioner.prepare(transaction);
                if(resumed.uid!=identity.uid || resumed.gid!=identity.gid || transaction.state()!=RootfsTransaction.State.PREPARED)
                    throw new IOException("Recovered guest account differs");
                runGuest(base,root,identity,report);
                if(Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS)) throw new IOException("Unexpected activation");
            }
            report.put("status","PASS");
            Files.writeString(evidence,report.toString(2));
            Log.i("FoldGPT-AccountProbe","PASS evidence="+evidence);
        } catch(Exception failure) {
            Log.e("FoldGPT-AccountProbe","FAIL evidence="+evidence,failure);
            try { report.put("status","FAIL").put("error",failure.toString()); if(evidence!=null) Files.writeString(evidence,report.toString(2)); }
            catch(Exception reportError) { Log.e("FoldGPT-AccountProbe","Report failed",reportError); }
        } finally {
            java.lang.Process running=child;
            if(running!=null && running.isAlive()) { running.destroyForcibly(); try { running.waitFor(5,TimeUnit.SECONDS); } catch(InterruptedException ignored) { Thread.currentThread().interrupt(); } }
            child=null;
            if(wake.isHeld()) wake.release();
            new Handler(Looper.getMainLooper()).post(() -> { worker=null; if(stopSelfResult(latestStart)) stopForeground(STOP_FOREGROUND_REMOVE); });
        }
    }
    private void runGuest(Path base,Path root,GuestIdentity identity,JSONObject report) throws Exception {
        Path nativeDir=Path.of(getApplicationInfo().nativeLibraryDir);
        Path scratch=base.resolve("scratch"),aliases=base.resolve("native"); privateDirectory(scratch); privateDirectory(aliases);
        Path talloc=aliases.resolve("libtalloc.so.2");
        if(Files.exists(talloc,LinkOption.NOFOLLOW_LINKS)) {
            if(!Files.isSymbolicLink(talloc)) throw new IOException("Unexpected native alias file");
            if(!Files.readSymbolicLink(talloc).equals(nativeDir.resolve("libtalloc.so"))) Files.delete(talloc);
        }
        if(!Files.exists(talloc,LinkOption.NOFOLLOW_LINKS)) Files.createSymbolicLink(talloc,nativeDir.resolve("libtalloc.so"));
        List<String> args=new ArrayList<>(List.of(nativeDir.resolve("libproot.so").toString(),"--kill-on-exit","--link2symlink","--sysvipc",
            "-r",root.toString(),"-i",identity.prootIds(),"-w",identity.home,"-b","/dev","-b","/proc","-b","/sys","-b","/system","-b","/apex",
            "-b",scratch+":/tmp","/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME="+identity.home,"USER="+identity.user,
            "/bin/bash","-c","set -eu; id -u; id -g; getent passwd foldgpt; test \"$HOME\" = /home/foldgpt; test -d \"$HOME\"; printf 'PASS guest identity\\n'"));
        ProcessBuilder builder=new ProcessBuilder(args);
        Map<String,String> env=builder.environment(); env.clear();
        env.put("LD_LIBRARY_PATH",aliases+":"+nativeDir); env.put("PROOT_LOADER",nativeDir.resolve("libproot-loader.so").toString());
        env.put("PROOT_LOADER_32",nativeDir.resolve("libproot-loader32.so").toString());
        env.put("PROOT_TMP_DIR",scratch.toString()); env.put("TMPDIR",scratch.toString());
        Path log=base.resolve("guest.log");
        child=builder.redirectErrorStream(true).redirectOutput(log.toFile()).start(); child.getOutputStream().close();
        if(!child.waitFor(30,TimeUnit.SECONDS)) throw new IOException("Guest identity execution timed out");
        if(Files.size(log)>65536) throw new IOException("Guest identity output exceeded bound");
        String output=Files.readString(log);
        if(child.exitValue()!=0 || !output.contains(identity.uid+"\n"+identity.gid+"\n") || !output.contains("PASS guest identity"))
            throw new IOException("Guest identity execution failed: "+output);
        report.put("guestOutput",output).put("guestExecuted",true);
    }
    private static void privateDirectory(Path path) throws Exception {
        try { Os.mkdir(path.toString(),0700); } catch(ErrnoException error) { if(error.errno!=OsConstants.EEXIST) throw error; }
        StructStat st=Os.lstat(path.toString());
        if(!OsConstants.S_ISDIR(st.st_mode) || st.st_uid!=android.os.Process.myUid() || (st.st_mode&0077)!=0)
            throw new IOException("Probe directory is not owned and private");
    }
    @Override public void onDestroy() { if(worker!=null) worker.interrupt(); java.lang.Process running=child; if(running!=null) running.destroy(); super.onDestroy(); }
}
