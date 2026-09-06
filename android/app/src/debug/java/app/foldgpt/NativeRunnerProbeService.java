package app.foldgpt;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.util.concurrent.TimeUnit;

/** Debug-only fixed executable/grant checks under the real Zygote app context.
 * No command, path, policy, account or model input is accepted from the intent.
 * An absent executable is an error; there is no privilege/fallback path. */
public final class NativeRunnerProbeService extends Service {
    private static final String CHANNEL = "foldgpt-native-runner-probe";
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (running) return START_NOT_STICKY;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
            CHANNEL, "FoldGPT native execution diagnostic", NotificationManager.IMPORTANCE_LOW));
        startForeground(1619, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT native execution diagnostic")
            .setContentText("Checking private local test files and process restrictions")
            .setOngoing(true).build());
        running = true;
        new Thread(() -> {
            Process process = null;
            try {
                String directory = getApplicationInfo().nativeLibraryDir;
                File log = new File(getCacheDir(), "native-runner-probe.log");
                ProcessBuilder builder = new ProcessBuilder(directory + "/libfoldgpt-native-runner-probe.so",
                    getCacheDir().getCanonicalPath(), new File(directory).getCanonicalPath());
                builder.environment().clear();
                process = builder.redirectErrorStream(true).redirectOutput(log).start();
                if (!process.waitFor(80, TimeUnit.SECONDS)) {
                    process.destroy();
                    if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly();
                    throw new IOException("Native runner diagnostic exceeded its bounded deadline");
                }
                if (process.exitValue() != 0) throw new IOException("Native runner diagnostic exit=" + process.exitValue());
                Log.i("FoldGPT-RunnerProbe", "Fixed native runner fixture passed; evidence=" + log.getAbsolutePath());
            } catch (Exception error) {
                Log.e("FoldGPT-RunnerProbe", "Native runner diagnostic failed", error);
            } finally {
                if (process != null && process.isAlive()) process.destroyForcibly();
                mainHandler.post(() -> {
                    running = false;
                    if (stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE);
                });
            }
        }, "FoldGPT-native-runner-probe").start();
        return START_NOT_STICKY;
    }
}
