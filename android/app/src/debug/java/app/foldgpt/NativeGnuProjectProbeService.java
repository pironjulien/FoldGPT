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

/** Fixed GNU project under native kernel restrictions, in the Zygote app UID.
 * The APK owns both the launcher and its embedded test. No Intent input selects
 * a command, policy, account, workspace or program. The live client is unused.
 */
public final class NativeGnuProjectProbeService extends Service {
    private static final String CHANNEL = "foldgpt-gnu-project-probe";
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (running) return START_NOT_STICKY;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,
            "FoldGPT native GNU project diagnostic", NotificationManager.IMPORTANCE_LOW));
        startForeground(1627, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT native project diagnostic")
            .setContentText("Testing a private Python project on the phone")
            .setOngoing(true).build());
        running = true;
        new Thread(() -> {
            Process process = null;
            Path evidence = null;
            PowerManager.WakeLock wake = getSystemService(PowerManager.class).newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "FoldGPT:GnuProjectProbe");
            wake.acquire(TimeUnit.SECONDS.toMillis(150));
            try {
                evidence = Files.createTempDirectory(getCacheDir().getCanonicalFile().toPath(), "gnu-log-");
                Os.chmod(evidence.toString(), 0700);
                Path nativeDirectory = Path.of(getApplicationInfo().nativeLibraryDir).toRealPath();
                Path program = nativeDirectory.resolve("libfoldgpt-gnu-project.so");
                if (!Files.isRegularFile(program)) throw new IOException("Native project launcher is absent");
                ProcessBuilder builder = new ProcessBuilder(program.toString(),
                    getDataDir().getCanonicalPath(), nativeDirectory.toString());
                builder.environment().clear();
                process = builder.redirectOutput(evidence.resolve("stdout.log").toFile())
                    .redirectError(evidence.resolve("stderr.log").toFile()).start();
                process.getOutputStream().close();
                if (!process.waitFor(105, TimeUnit.SECONDS))
                    throw new IOException("Native project exceeded its deadline");
                int code = process.exitValue();
                Files.writeString(evidence.resolve("android-exit.txt"),
                    "exit=" + code + " uid=" + android.os.Process.myUid() + "\n",
                    StandardOpenOption.CREATE_NEW);
                if (code != 0) throw new IOException("Native project failed with exit " + code);
                Log.i("FoldGPT-GnuProject", "Native diagnostic completed; evidence=" + evidence);
            } catch (Exception error) {
                Log.e("FoldGPT-GnuProject", "Native project failed; evidence=" + evidence, error);
            } finally {
                if (process != null && process.isAlive()) {
                    process.destroy();
                    try {
                        if (!process.waitFor(10, TimeUnit.SECONDS))
                            Log.e("FoldGPT-GnuProject", "Native descendant cleanup did not finish");
                    } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                }
                if (wake.isHeld()) wake.release();
                main.post(() -> {
                    running = false;
                    if (stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE);
                });
            }
        }, "FoldGPT-gnu-project-probe").start();
        return START_NOT_STICKY;
    }
}
