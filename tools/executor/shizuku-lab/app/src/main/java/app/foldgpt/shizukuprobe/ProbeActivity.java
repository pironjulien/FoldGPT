package app.foldgpt.shizukuprobe;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.AtomicFile;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import rikka.shizuku.Shizuku;

/** DUMP-protected diagnostic entry point for two fixed qualification operations. */
public final class ProbeActivity extends Activity {
    public static final String ACTION_COLLECT = BuildConfig.APPLICATION_ID + ".COLLECT";
    public static final String ACTION_RUN_FIXED = BuildConfig.APPLICATION_ID + ".RUN_FIXED";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private TextView text;
    private boolean requestedPermission;
    private boolean bound;
    private boolean finished;
    private boolean destroyed;
    private boolean runFixed;
    private boolean retainService;
    private Shizuku.UserServiceArgs serviceArgs;

    private final Shizuku.OnBinderReceivedListener binderReceived = () -> main.post(this::connect);
    private final Shizuku.OnBinderDeadListener binderDead = () -> main.post(() -> fail("Shizuku binder died"));
    private final Shizuku.OnRequestPermissionResultListener permissionResult = (request, result) -> {
        if (request == 1) main.post(() -> {
            if (result == PackageManager.PERMISSION_GRANTED) connect();
            else fail("Official Shizuku permission was not granted");
        });
    };
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            worker.execute(() -> {
                try {
                    IQualificationService service = IQualificationService.Stub.asInterface(binder);
                    JSONObject result = new JSONObject(runFixed ? service.runFixed() : service.collectContext());
                    result.put("clientUid", android.os.Process.myUid());
                    result.put("clientPid", android.os.Process.myPid());
                    result.put("shizukuSdkVersion", "13.1.5");
                    result.put("shizukuServerApiVersion", Shizuku.getVersion());
                    result.put("shizukuServerUid", Shizuku.getUid());
                    main.post(() -> complete(result));
                } catch (Exception error) {
                    main.post(() -> fail(error.getClass().getSimpleName() + ": " + error.getMessage()));
                }
            });
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            if (!finished) fail("Qualification service disconnected before a report");
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        text = new TextView(this);
        text.setPadding(24, 24, 24, 24);
        text.setTextIsSelectable(true);
        setContentView(text);
        String action = getIntent().getAction();
        if (!ACTION_COLLECT.equals(action) && !ACTION_RUN_FIXED.equals(action)) {
            fail("Only the fixed COLLECT and RUN_FIXED actions are supported");
            return;
        }
        runFixed = ACTION_RUN_FIXED.equals(action);
        status("Waiting for official Shizuku Binder");
        serviceArgs = new Shizuku.UserServiceArgs(new ComponentName(this, ProbeService.class))
                .daemon(false).tag("foldgpt-qualification-v" + BuildConfig.VERSION_CODE).version(BuildConfig.VERSION_CODE)
                .processNameSuffix("qualification").debuggable(false);
        Shizuku.addBinderDeadListener(binderDead);
        Shizuku.addRequestPermissionResultListener(permissionResult);
        Shizuku.addBinderReceivedListenerSticky(binderReceived);
    }

    private void connect() {
        if (destroyed || finished || bound || !Shizuku.pingBinder()) return;
        try {
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                if (!requestedPermission) {
                    requestedPermission = true;
                    status("Requesting the official Shizuku authorization");
                    Shizuku.requestPermission(1);
                }
                return;
            }
            if (Shizuku.getUid() != 2000) {
                fail("Shizuku is not running as non-root shell UID 2000");
                return;
            }
            status(runFixed ? "Binding the fixed native qualification UserService" : "Binding the fixed read-only UserService");
            bound = true;
            Shizuku.bindUserService(serviceArgs, connection);
            main.postDelayed(() -> {
                if (!finished && !destroyed) {
                    if (runFixed) retainService = true;
                    fail("UserService exceeded its reporting deadline; no retry is scheduled");
                }
            }, runFixed ? 60000 : 30000);
        } catch (Exception error) {
            fail(error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    private void status(String message) {
        text.setText(message);
        try {
            persist(new JSONObject().put("schema", "foldgpt.shizuku.context.v1")
                    .put("state", "pending").put("message", message)
                    .put("observedAtMillis", System.currentTimeMillis()));
        } catch (Exception error) { text.append("\nReport write failed: " + error); }
    }

    private void complete(JSONObject result) {
        if (finished || destroyed) return;
        finished = true;
        if (runFixed && !result.optBoolean("cleanup_complete", false)) retainService = true;
        try {
            result.put("state", "complete");
            persist(result);
            text.setText(result.toString(2));
        } catch (Exception error) { text.setText("Report write failed: " + error); }
        removeService();
    }

    private void fail(String message) {
        if (finished || destroyed) return;
        finished = true;
        try {
            JSONObject result = new JSONObject().put("schema", "foldgpt.shizuku.context.v1")
                    .put("state", "failed").put("success", false)
                    .put("error", message).put("observedAtMillis", System.currentTimeMillis());
            persist(result);
            text.setText(result.toString(2));
        } catch (Exception error) { text.setText(message + "\nReport write failed: " + error); }
        removeService();
    }

    private void persist(JSONObject report) throws Exception {
        AtomicFile file = new AtomicFile(new File(getFilesDir(), "report.json"));
        FileOutputStream output = null;
        try {
            output = file.startWrite();
            output.write((report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
            file.finishWrite(output);
        } catch (Exception error) {
            if (output != null) file.failWrite(output);
            throw error;
        }
    }

    private void removeService() {
        if (retainService) {
            text.append("\nNative cleanup unresolved: UserService ownership retained; no automatic retry.");
            return;
        }
        if (bound) {
            bound = false;
            try { Shizuku.unbindUserService(serviceArgs, connection, true); }
            catch (Exception error) { text.append("\nService removal failed: " + error); }
        }
    }

    @Override protected void onDestroy() {
        destroyed = true;
        removeService();
        Shizuku.removeBinderReceivedListener(binderReceived);
        Shizuku.removeBinderDeadListener(binderDead);
        Shizuku.removeRequestPermissionResultListener(permissionResult);
        worker.shutdown();
        super.onDestroy();
    }
}
