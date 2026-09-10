package app.foldgpt.runasbrokerqualification;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Binder;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.AtomicFile;
import android.widget.TextView;
import app.foldgpt.shizukuexec.IRunAsBrokerQualification;
import app.foldgpt.shizukuexec.RunAsBrokerInstallation;
import app.foldgpt.shizukuexec.RunAsBrokerQualificationService;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import rikka.shizuku.Shizuku;

/** Separate package, one broker trial; restored Intents cannot retry it. */
public final class RunAsBrokerQualificationActivity extends Activity {
    private static final String PREFIX = "app.foldgpt.runasbrokerqualification.v2.";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Binder owner = new Binder();
    private final java.util.concurrent.ExecutorService work = java.util.concurrent.Executors.newSingleThreadExecutor();
    private TextView text;
    private String action, reportName;
    private boolean finished, bound, permissionRequested, started;
    private volatile boolean running, cleanupComplete;
    private volatile IRunAsBrokerQualification service;
    private Shizuku.UserServiceArgs args;
    private final Shizuku.OnBinderReceivedListener received = () -> main.post(this::bind);
    private final Shizuku.OnBinderDeadListener dead = () -> main.post(() -> fail("Shizuku Binder lost; existing attempt retained"));
    private final Shizuku.OnRequestPermissionResultListener permission = (request, result) -> main.post(() -> {
        if (request == 1 && result == PackageManager.PERMISSION_GRANTED) bind();
        else if (request == 1) fail("Official Shizuku authorization was not granted");
    });
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            if (running || finished) return;
            service = IRunAsBrokerQualification.Stub.asInterface(binder);
            running = true;
            work.execute(RunAsBrokerQualificationActivity.this::run);
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            if (!finished) fail("Qualification UserService disconnected before its final report");
        }
    };
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        action = getIntent().getAction();
        text = new TextView(this); text.setTextIsSelectable(true); text.setPadding(24, 24, 24, 24); setContentView(text);
        if (!RunAsBrokerInstallation.QUALIFICATION.equals(getPackageName())) { fail("Wrong fixed APK identity"); return; }
        if (!(PREFIX + "AUTHORIZE").equals(action) && !(PREFIX + "PREFLIGHT").equals(action)
                && !(PREFIX + "RUN_BROKER_V2").equals(action) && !(PREFIX + "COLLECT_INFO").equals(action)) {
            fail("Only the four fixed qualification actions are admitted"); return;
        }
        reportName = action.substring(PREFIX.length()).toLowerCase(java.util.Locale.ROOT) + ".json";
        if ((PREFIX + "COLLECT_INFO").equals(action)) {
            work.execute(() -> {
                try {
                    JSONObject result = RunAsBrokerInstallation.capture(this).put("state", "complete").put("nativeSpawnAttempted", false);
                    main.post(() -> complete(result));
                } catch (Exception error) { main.post(() -> fail(error.toString())); }
            });
            return;
        }
        try {
            if ((PREFIX + "RUN_BROKER_V2").equals(action) && new File(directory(), "attempt-started-v2").exists()) {
                text.setText("This broker trial was already reserved. The marker and report are retained; no retry.");
                finished = true; return;
            }
            text.setText("Preparing fixed run-as broker qualification");
            args = new Shizuku.UserServiceArgs(new ComponentName(this, RunAsBrokerQualificationService.class))
                .daemon(false).tag("foldgpt-runas-broker-v2").version(2)
                .processNameSuffix("runas_broker_v2").debuggable(false);
            Shizuku.addBinderDeadListener(dead);
            Shizuku.addRequestPermissionResultListener(permission);
            Shizuku.addBinderReceivedListenerSticky(received);
        } catch (Exception error) { fail(error.toString()); }
    }
    private void bind() {
        if (finished || bound || !Shizuku.pingBinder()) return;
        try {
            if (Shizuku.getUid() != 2000) throw new SecurityException("Only nonroot Shizuku UID 2000 is admitted");
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                if (!(PREFIX + "AUTHORIZE").equals(action)) throw new SecurityException("Use the explicit AUTHORIZE action first");
                if (!permissionRequested) { permissionRequested = true; Shizuku.requestPermission(1); }
                return;
            }
            if ((PREFIX + "AUTHORIZE").equals(action)) {
                complete(new JSONObject().put("state", "complete").put("authorized", true)
                    .put("shizukuUid", Shizuku.getUid()).put("nativeSpawnAttempted", false));
                return;
            }
            if ((PREFIX + "RUN_BROKER_V2").equals(action)) {
                if (!new File(directory(), "attempt-started-v2").createNewFile()) {
                    finished = true; text.setText("Attempt already reserved; no retry."); return;
                }
                persist(new JSONObject().put("state", "reserved").put("nativeSpawnAttempted", false));
            }
            bound = true;
            Shizuku.bindUserService(args, connection);
            main.postDelayed(() -> { if (!finished) fail("Reporting deadline exceeded; preserve this attempt and ownership"); }, 60000);
        } catch (Exception error) { fail(error.toString()); }
    }
    private void run() {
        JSONObject result = new JSONObject();
        try {
            JSONObject expected = RunAsBrokerInstallation.capture(this);
            JSONObject preflight = new JSONObject(service.preflight());
            RunAsBrokerInstallation.requireSame(expected, preflight);
            result.put("installation", expected).put("preflight", preflight);
            if ((PREFIX + "PREFLIGHT").equals(action)) {
                result.put("state", "complete").put("nativeSpawnAttempted", false).put("passed", true);
            } else {
                started = true;
                service.start(owner, expected.toString());
                long deadline = SystemClock.elapsedRealtime() + 40000;
                do {
                    String encoded = service.status();
                    if (encoded.length() > 98304) throw new IllegalStateException("Service report exceeds bound");
                    JSONObject observed = new JSONObject(encoded);
                    result.put("service", observed);
                    if ("complete".equals(observed.optString("state"))) {
                        cleanupComplete = observed.getBoolean("cleanupComplete");
                        result.put("passed", observed.optBoolean("passed") && cleanupComplete && observed.getBoolean("childReaped"));
                        result.put("state", "complete");
                        break;
                    }
                    Thread.sleep(100);
                } while (SystemClock.elapsedRealtime() < deadline);
                if (!result.has("state")) throw new IllegalStateException("Service owner did not complete within the observation deadline");
            }
        } catch (Exception error) {
            cancel();
            try { result.put("state", "failed").put("passed", false).put("error", error.toString()); }
            catch (Exception ignored) { }
        }
        main.post(() -> { running = false; complete(result); });
    }
    private void cancel() {
        IRunAsBrokerQualification current = service;
        if (started && current != null) try { current.cancel(); } catch (Exception ignored) { }
    }
    private void complete(JSONObject result) {
        finished = true;
        try { persist(result); text.setText(result.toString(2)); }
        catch (Exception error) { text.setText(error.toString()); }
        release();
    }
    private void fail(String error) {
        if (finished) return;
        cancel(); finished = true;
        try { persist(new JSONObject().put("state", "failed").put("passed", false).put("error", error)); }
        catch (Exception ignored) { }
        if (text != null) text.setText(error);
        release();
    }
    private void release() {
        if (bound && (!started || cleanupComplete)) {
            try { Shizuku.unbindUserService(args, connection, cleanupComplete); bound = false; }
            catch (Exception error) { text.append("\nService release: " + error); }
        }
    }
    private File directory() throws Exception {
        File root = new File(getFilesDir().getCanonicalFile(), "runas-broker-v2");
        if ((!root.isDirectory() && !root.mkdir()) || !root.getCanonicalFile().equals(root)) {
            throw new SecurityException("Report directory is not canonical");
        }
        return root;
    }
    private void persist(JSONObject report) throws Exception {
        report.put("schema", "foldgpt.runas.broker-activity.v2").put("action", action)
            .put("recordedWallTimeMs", System.currentTimeMillis()).put("recordedElapsedRealtimeMs", SystemClock.elapsedRealtime());
        AtomicFile file = new AtomicFile(new File(directory(), reportName == null ? "rejected-action.json" : reportName));
        FileOutputStream output = file.startWrite();
        try { output.write((report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8)); file.finishWrite(output); }
        catch (Exception error) { file.failWrite(output); throw error; }
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (!finished || running || (started && !cleanupComplete)) {
            text.append("\nNew action refused while ownership remains unresolved."); return;
        }
        setIntent(new Intent(this, RunAsBrokerQualificationActivity.class).setAction(intent.getAction())); recreate();
    }
    @Override protected void onDestroy() {
        cancel(); release();
        Shizuku.removeBinderReceivedListener(received); Shizuku.removeBinderDeadListener(dead);
        Shizuku.removeRequestPermissionResultListener(permission); work.shutdown(); super.onDestroy();
    }
}
