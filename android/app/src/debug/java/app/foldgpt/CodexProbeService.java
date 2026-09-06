package app.foldgpt;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;
import java.io.File;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Debug-only fixed offline fixture, launched with the real Zygote app context. */
public final class CodexProbeService extends Service {
    private static final String CHANNEL = "foldgpt-offline-probe";
    private final AtomicBoolean running = new AtomicBoolean(false);

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(
            CHANNEL, "FoldGPT offline diagnostic", NotificationManager.IMPORTANCE_LOW));
        startForeground(1618, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT offline diagnostic")
            .setContentText("Testing an isolated local fixture; no model requests")
            .setOngoing(true).build());
        if (!running.compareAndSet(false, true)) return START_NOT_STICKY;
        new Thread(() -> {
            Process process = null;
            try {
                // No extras or user-provided commands/paths are accepted.
                String nativeDirectory = getApplicationInfo().nativeLibraryDir;
                File log = new File(getCacheDir(), "codex-probe.log");
                process = new ProcessBuilder(nativeDirectory + "/libfoldgpt-codex-probe.so",
                    getDataDir().getAbsolutePath(), nativeDirectory)
                    .redirectErrorStream(true).redirectOutput(log).start();
                // Native deadline is 90 seconds plus bounded descendant cleanup.
                if (!process.waitFor(105, TimeUnit.SECONDS)) {
                    throw new java.io.IOException("Offline diagnostic exceeded native deadline");
                }
                Log.i("FoldGPT-Probe", "codex offline experiment exit=" + process.exitValue());
            } catch (Exception error) {
                Log.e("FoldGPT-Probe", "Offline diagnostic failed", error);
            } finally {
                if (process != null && process.isAlive()) process.destroyForcibly();
                running.set(false);
                stopForeground(STOP_FOREGROUND_REMOVE);
                stopSelf();
            }
        }, "FoldGPT-offline-codex-probe").start();
        return START_NOT_STICKY;
    }
}
