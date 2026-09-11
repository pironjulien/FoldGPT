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
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/** ADB-only, offline real stdio/file policy fixture in the Zygote app context.
 * Uses APK-owned source assets, a new private workspace, and an empty profile.
 * No Intent command/path/policy input and no configuration of the live client.
 * The interpreter is loaded directly: PRoot is not a supervisor boundary. */
public final class NativeFilesRpcProbeService extends Service {
    private static final String CHANNEL = "foldgpt-native-files-rpc-probe";
    private static final String[] SOURCES = {
        "tools/executor/exec_server.py", "tools/executor/native_files.py",
        "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
        "tools/executor/native_files_server.py", "tools/executor/native_files_rpc_fixture.py"
    };
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean running;
    private int latestStartId;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (running) return START_NOT_STICKY;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
            CHANNEL, "FoldGPT native file transport diagnostic", NotificationManager.IMPORTANCE_LOW));
        startForeground(1620, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("FoldGPT native file transport diagnostic")
            .setContentText("Checking native file requests in a private fixture")
            .setOngoing(true).build());
        running = true;
        new Thread(() -> {
            Process process = null;
            File evidence = null;
            try {
                evidence = new File(getCacheDir(), "native-files-rpc-" + UUID.randomUUID()).getCanonicalFile();
                Files.createDirectory(evidence.toPath());
                Os.chmod(evidence.getPath(), 0700);
                File sources = new File(evidence, "sources");
                for (String relative : SOURCES) {
                    File target = new File(sources, relative);
                    Files.createDirectories(target.getParentFile().toPath());
                    try (InputStream input = getAssets().open("native-files-rpc/" + relative)) {
                        byte[] bytes = input.readNBytes(1048577);
                        if (bytes.length > 1048576) throw new IOException("APK diagnostic source exceeds bound");
                        Files.write(target.toPath(), bytes, StandardOpenOption.CREATE_NEW);
                    }
                }
                pythonAssetBytes = 0;
                pythonAssetFiles = 0;
                File pythonHome = new File(evidence, "python");
                copyPythonAssets("native-python", pythonHome);
                File python = new File(getApplicationInfo().nativeLibraryDir, "libfoldgpt_python.so").getCanonicalFile();
                File helper = new File(getApplicationInfo().nativeLibraryDir, "libfoldgpt-native-files.so").getCanonicalFile();
                for (File executable : new File[]{python, helper})
                    if (!executable.isFile()) throw new IOException("Required diagnostic executable is absent");
                List<String> command = new ArrayList<>(Arrays.asList(
                    python.getPath(), "--home", pythonHome.getPath(), "--",
                    new File(sources, "tools/executor/native_files_rpc_fixture.py").getPath(),
                    "--helper", helper.getPath(), "--android-home", pythonHome.getPath(), "--evidence", evidence.getPath(),
                    "--android-uid", Integer.toString(android.os.Process.myUid())));
                ProcessBuilder builder = new ProcessBuilder(command).directory(evidence);
                builder.environment().clear();
                builder.environment().put("PATH", "/system/bin");
                builder.environment().put("LANG", "C.UTF-8");
                builder.environment().put("HOME", new File(evidence, "home").getPath());
                builder.environment().put("TMPDIR", new File(evidence, "tmp").getPath());
                process = builder.redirectErrorStream(true).redirectOutput(new File(evidence, "fixture-output.txt")).start();
                process.getOutputStream().close();
                if (!process.waitFor(90, TimeUnit.SECONDS))
                    throw new IOException("Native file RPC fixture exceeded deadline");
                int originalExit = process.exitValue();
                if (originalExit != 0 || !new File(evidence, "report.json").isFile())
                    throw new IOException("Native file RPC fixture failed: exit=" + originalExit);
                Files.writeString(new File(evidence, "android-completion.txt").toPath(),
                    "PASS uid=" + android.os.Process.myUid() + " pid=" + android.os.Process.myPid() + "\n",
                    StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
                Log.i("FoldGPT-FileRpcProbe", "PASS; evidence=" + evidence.getPath());
            } catch (Exception error) {
                Log.e("FoldGPT-FileRpcProbe", "FAIL; evidence=" + (evidence == null ? "not-created" : evidence.getPath()), error);
            } finally {
                if (process != null && process.isAlive()) process.destroyForcibly();
                mainHandler.post(() -> {
                    running = false;
                    if (stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE);
                });
            }
        }, "FoldGPT-native-files-rpc-probe").start();
        return START_NOT_STICKY;
    }

    private long pythonAssetBytes;
    private int pythonAssetFiles;
    private void copyPythonAssets(String source, File target) throws IOException {
        String[] names = getAssets().list(source);
        if (names == null) throw new IOException("Missing Python assets");
        if (names.length > 0) {
            Files.createDirectory(target.toPath());
            for (String name : names) {
                if (name.isEmpty() || name.equals(".") || name.equals("..") || name.contains("/") || name.contains("\\"))
                    throw new IOException("Invalid Python asset component");
                copyPythonAssets(source + "/" + name, new File(target, name));
            }
        } else {
            if (++pythonAssetFiles > 20000) throw new IOException("Python asset count exceeds bound");
            try (InputStream input = getAssets().open(source);
                 java.io.OutputStream output = Files.newOutputStream(target.toPath(), StandardOpenOption.CREATE_NEW)) {
                byte[] buffer = new byte[65536];
                int size;
                while ((size = input.read(buffer)) != -1) {
                    pythonAssetBytes += size;
                    if (pythonAssetBytes > 256L * 1024 * 1024) throw new IOException("Python assets exceed bound");
                    output.write(buffer, 0, size);
                }
            }
        }
    }
}
