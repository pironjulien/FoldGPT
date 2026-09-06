package app.foldgpt.install;

import android.app.*;
import android.content.*;
import android.os.*;
import android.system.*;
import android.util.Log;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Fixed debug-only guest operations, under the actual Zygote UID and seccomp.
 * Reads the inactive Debian stage; mutations are confined by ownership to a
 * newly allocated disposable fixture. PRoot itself is not a security boundary.
 * No Intent parameters, network, credentials or current runtime mutations.
 */
public final class ProotStorageProbeService extends Service {
    private static final RootfsExtractor.Spec SPEC = new RootfsExtractor.Spec(
        "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
        327673156L, 958101116L, 977131520L, 20240);
    private volatile Thread worker;
    private volatile java.lang.Process child;
    private int startId;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        startId = id;
        if (worker != null) return START_NOT_STICKY;
        String channel = "foldgpt.storage-probe";
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel(channel,"Diagnostic du stockage Linux",NotificationManager.IMPORTANCE_LOW));
        startForeground(1621,new Notification.Builder(this,channel)
            .setSmallIcon(android.R.drawable.ic_menu_info_details).setContentTitle("FoldGPT — test du stockage Linux")
            .setContentText("Vérification des liens de fichiers dans un espace de test").setOngoing(true).build());
        worker = new Thread(this::probe,"FoldGPT-storage-probe"); worker.start();
        return START_NOT_STICKY;
    }
    private void probe() {
        Path work = null;
        JSONObject report = new JSONObject();
        PowerManager.WakeLock wake = getSystemService(PowerManager.class).newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,"FoldGPT:StorageProbe");
        try {
            wake.acquire(180000);
            work = Files.createTempDirectory(getCacheDir().toPath(),"proot-storage-",
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath();
            report.put("schema","foldgpt.proot-storage-probe.v1").put("uid",android.os.Process.myUid())
                .put("pid",android.os.Process.myPid()).put("status","RUNNING")
                .put("selinuxContext",Files.readString(Path.of("/proc/self/attr/current")).trim());
            for (String line : Files.readAllLines(Path.of("/proc/self/status")))
                if (line.startsWith("Seccomp:") || line.startsWith("NoNewPrivs:"))
                    report.put(line.split(":")[0],line.split(":")[1].trim());
            Path nativeDir = Path.of(getApplicationInfo().nativeLibraryDir);
            for (String library : List.of("libproot.so","libproot-loader.so","libproot-loader32.so",
                    "libtalloc.so","libandroid-shmem.so","libfoldgpt-l2s-fixture.so"))
                report.put(library,hash(nativeDir.resolve(library)));
            Path isolatedFiles = getFilesDir().toPath().toRealPath().resolve(".rootfs-proot-install-probe/files");
            ContextWrapper isolated = new ContextWrapper(this) {
                @Override public File getFilesDir() { return isolatedFiles.toFile(); }
            };
            JSONArray checks = new JSONArray(); report.put("checks",checks);
            write(work,report);
            try (RootfsTransaction transaction = AndroidRootfsTransaction.open(isolated,SPEC)) {
                Path root = transaction.prepare(() -> { throw new IOException("Prepared base is required; no extraction here"); }).root;
                if (transaction.state()!=RootfsTransaction.State.PREPARED) throw new IOException("Only an inactive base may be inspected");
                report.put("root",root.toString());
                Path data = Files.createDirectory(work.resolve("data"));
                run(work,root,data,"inspect",List.of("/probe","inspect-archive"),checks);
                run(work,root,data,"debian-exec",List.of("/usr/bin/perl","-e","print qq(PASS pristine Debian Perl execution\\n)"),checks);
                run(work,root,data,"shared-memory",List.of("/probe","shared-memory"),checks);
                run(work,root,data,"generated",List.of("/probe","create"),checks);
                requireEmpty(data);
                // The exact production Java converter provisions this group.
                Path source = data.resolve("a"); Files.writeString(source,"one\n");
                ProotHardlinkStorage.create(data,Map.of(source,List.of(data.resolve("b"))),new RootfsExtractor.Posix() {
                    public void chmod(Path path,int mode) throws IOException { throw new IOException("Unexpected chmod in storage conversion"); }
                    public void syncDirectory(Path path) throws IOException {
                        try (var channel=java.nio.channels.FileChannel.open(path,StandardOpenOption.READ)) { channel.force(true); }
                    }
                    public void setSymlinkModified(Path path,java.nio.file.attribute.FileTime time) throws IOException {
                        NativeInstallFiles.setSymlinkModified(path,time);
                    }
                });
                JSONObject physical = new JSONObject();
                try (var paths=Files.newDirectoryStream(data)) {
                    for (Path path:paths) {
                        StructStat info=Os.lstat(path.toString());
                        physical.put(path.getFileName().toString(),new JSONObject().put("inode",info.st_ino)
                            .put("mode",info.st_mode).put("nlink",info.st_nlink)
                            .put("target",Files.isSymbolicLink(path)?Files.readSymbolicLink(path).toString():JSONObject.NULL));
                    }
                }
                report.put("provisionedHostLayout",physical); write(work,report);
                run(work,root,data,"provisioned",List.of("/probe","verify"),checks);
                requireEmpty(data);
                if (Files.exists(isolatedFiles.resolve("debian"),LinkOption.NOFOLLOW_LINKS))
                    throw new IOException("Unexpected activation pointer");
            }
            report.put("status","PASS");
            write(work,report);
            Log.i("FoldGPT-StorageProbe","PASS evidence="+work);
        } catch (Exception failure) {
            Log.e("FoldGPT-StorageProbe","FAIL evidence="+work,failure);
            try { report.put("status","FAIL").put("error",failure.toString()); if(work!=null) write(work,report); }
            catch(Exception ignored) { Log.e("FoldGPT-StorageProbe","Unable to write failure report",ignored); }
        } finally {
            if(wake.isHeld()) wake.release();
            new Handler(Looper.getMainLooper()).post(() -> { worker=null; if(stopSelfResult(startId)) stopForeground(STOP_FOREGROUND_REMOVE); });
        }
    }
    private void run(Path work,Path root,Path data,String name,List<String> command,JSONArray checks) throws Exception {
        Path nativeDir=Path.of(getApplicationInfo().nativeLibraryDir), aliases=Files.createDirectories(work.resolve("native"));
        Path talloc=aliases.resolve("libtalloc.so.2");
        if(!Files.exists(talloc,LinkOption.NOFOLLOW_LINKS)) Files.createSymbolicLink(talloc,nativeDir.resolve("libtalloc.so"));
        Path scratch=Files.createDirectories(work.resolve("scratch"));
        List<String> args=new ArrayList<>(List.of(nativeDir.resolve("libproot.so").toString(),
            "--kill-on-exit","--link2symlink","--sysvipc","-r",root.toString(),"-i","10410:10410","-w","/",
            "-b","/dev","-b","/proc","-b","/sys","-b","/system","-b","/apex",
            "-b",nativeDir.resolve("libfoldgpt-l2s-fixture.so")+":/probe","-b",data+":/data"));
        args.addAll(command);
        ProcessBuilder builder=new ProcessBuilder(args);
        Map<String,String> env=builder.environment();
        env.put("LD_LIBRARY_PATH",aliases+":"+nativeDir);
        env.put("PROOT_LOADER",nativeDir.resolve("libproot-loader.so").toString());
        env.put("PROOT_LOADER_32",nativeDir.resolve("libproot-loader32.so").toString());
        env.put("PROOT_TMP_DIR",scratch.toString()); env.put("TMPDIR",scratch.toString());
        env.remove("PROOT_L2S_DIR"); env.remove("LD_PRELOAD");
        Path output=work.resolve(name+".log");
        child=builder.redirectErrorStream(true).redirectOutput(output.toFile()).start();
        try {
            child.getOutputStream().close();
            if(!child.waitFor(30,TimeUnit.SECONDS)) throw new IOException("Guest probe timed out: "+name);
            if(Files.size(output)>65536) throw new IOException("Guest probe output exceeds bound");
            String text=Files.readString(output);
            checks.put(new JSONObject().put("name",name).put("exit",child.exitValue()).put("output",text));
            if(child.exitValue()!=0 || !text.contains("PASS")) throw new IOException("Guest probe failed: "+name+"; "+text);
        } finally {
            if(child.isAlive()) { child.destroy(); if(!child.waitFor(2,TimeUnit.SECONDS)) child.destroyForcibly(); }
            child=null;
        }
    }
    private static void requireEmpty(Path data) throws IOException {
        try(var paths=Files.list(data)) { if(paths.findAny().isPresent()) throw new IOException("Final guest unlink left backing files"); }
    }
    private static void write(Path work,JSONObject report) throws Exception {
        Files.writeString(work.resolve("report.json"),report.toString(2));
    }
    private static String hash(Path path) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream stream=Files.newInputStream(path)) { byte[] bytes=new byte[65536]; for(int n;(n=stream.read(bytes))!=-1;) digest.update(bytes,0,n); }
        StringBuilder result=new StringBuilder(); for(byte value:digest.digest()) result.append(String.format(Locale.ROOT,"%02x",value&255));
        return result.toString();
    }
    @Override public void onDestroy() {
        if(worker!=null) worker.interrupt();
        java.lang.Process running=child; if(running!=null) running.destroy();
        super.onDestroy();
    }
}
