package app.foldgpt.kernelqualification;

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
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.util.AtomicFile;
import android.widget.TextView;
import app.foldgpt.shizukuexec.ExecutorService;
import app.foldgpt.shizukuexec.IExecutorService;
import app.foldgpt.shizukuexec.IExecutorSession;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import rikka.shizuku.Shizuku;

/** One fixed kernel diagnostic, through the production authenticated transport. */
public final class QualificationActivity extends Activity {
    private static final String REPORT_DIRECTORY = "kernel-v6";
    private static final String COLLECT_ACTION = ".KERNEL_COLLECT_INFO";
    // Android can restore the previous Activity Intent after a package update.
    // An earlier APK's launch action must never reserve this revision's trial.
    private static final String RUN_ACTION = ".KERNEL_RUN_FIXED_V10";
    private static final String PREFLIGHT_ACTION = ".KERNEL_PREFLIGHT";
    private static final String OLD_STATUS_ACTION = ".KERNEL_STATUS_V3";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final java.util.concurrent.ExecutorService work = java.util.concurrent.Executors.newSingleThreadExecutor();
    private final Binder owner = new Binder();
    private TextView text;
    private volatile IExecutorSession session;
    private volatile boolean cleanupComplete;
    private volatile boolean cancelRequested;
    private volatile boolean nativeOpenAttempted;
    private boolean bound, permissionRequested, finished, running;
    private boolean preflightOnly, oldStatusOnly;
    private String reportName = "report.json";
    private String requestedAction;
    private Shizuku.UserServiceArgs args;
    private final Shizuku.OnBinderReceivedListener received = () -> main.post(this::bind);
    private final Shizuku.OnBinderDeadListener dead = () -> main.post(() -> fail("Shizuku Binder lost; no retry"));
    private final Shizuku.OnRequestPermissionResultListener permission = (request, result) -> main.post(() -> {
        if (request == 1 && result == PackageManager.PERMISSION_GRANTED) bind();
        else if (request == 1) fail("Official Shizuku authorization was not granted");
    });
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            if (running || finished) return;
            running = true;
            work.execute(() -> {
                IExecutorService service = IExecutorService.Stub.asInterface(binder);
                if (preflightOnly || oldStatusOnly) readOnly(service); else runDiagnostic(service);
            });
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            if (!finished) fail("UserService lost before independent cleanup proof");
        }
    };
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestedAction = getIntent().getAction();
        text = new TextView(this); text.setTextIsSelectable(true); text.setPadding(24, 24, 24, 24); setContentView(text);
        if ((getPackageName() + COLLECT_ACTION).equals(getIntent().getAction())) {
            try {
                JSONObject info = new JSONObject().put("schema", "foldgpt.android-kernel-package.v1")
                    .put("nativeLibraryDir", getApplicationInfo().nativeLibraryDir).put("sourceDir", getApplicationInfo().sourceDir)
                    .put("clientUid", android.os.Process.myUid());
                File file = new File(reportDirectory(), "package-info.json");
                try (FileOutputStream output = new FileOutputStream(file)) {
                    output.write((info.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
                }
                text.setText(info.toString(2));
            } catch (Exception error) { text.setText(error.toString()); }
            finished = true; return;
        }
        preflightOnly = (getPackageName() + PREFLIGHT_ACTION).equals(getIntent().getAction());
        oldStatusOnly = (getPackageName() + OLD_STATUS_ACTION).equals(getIntent().getAction());
        if (preflightOnly) reportName = "preflight.json";
        if (oldStatusOnly) reportName = "previous-service-status.json";
        if (!preflightOnly && !oldStatusOnly && !(getPackageName() + RUN_ACTION).equals(getIntent().getAction())) {
            fail("Only the fixed kernel actions are admitted"); return;
        }
        try {
            if (!preflightOnly && !oldStatusOnly && !new File(reportDirectory(), "attempt-started").createNewFile()) {
                text.setText("An attempt was already reserved. Existing report and ownership are retained; no retry.");
                finished = true; return;
            }
            persist(new JSONObject().put("schema", "foldgpt.android-kernel-rpc.v1").put("state", "pending")
                .put("nativeLibraryDir", getApplicationInfo().nativeLibraryDir).put("clientUid", android.os.Process.myUid()));
            text.setText("Waiting for official Shizuku authorization");
            args = new Shizuku.UserServiceArgs(new ComponentName(this, ExecutorService.class))
                .daemon(false).tag(oldStatusOnly ? "foldgpt-kernel-qualification-v3" : "foldgpt-kernel-qualification-v6")
                .version(oldStatusOnly ? 3 : 6)
                .processNameSuffix("kernelqualification").debuggable(false);
            Shizuku.addBinderDeadListener(dead);
            Shizuku.addRequestPermissionResultListener(permission);
            Shizuku.addBinderReceivedListenerSticky(received);
        } catch (Exception error) { fail(error.toString()); }
    }
    private void bind() {
        if (finished || bound || !Shizuku.pingBinder()) return;
        try {
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                if (preflightOnly || oldStatusOnly) throw new SecurityException("Existing official Shizuku authorization is required for read-only inspection");
                if (!permissionRequested) { permissionRequested = true; Shizuku.requestPermission(1); }
                return;
            }
            if (Shizuku.getUid() != 2000) throw new SecurityException("Only nonroot Shizuku UID 2000 is admitted");
            bound = true;
            if (oldStatusOnly) {
                // SDK NO_CREATE only attaches to an already-running old tag.
                // Never open, preflight, restart, cancel or destroy that owner.
                int version = Shizuku.peekUserService(args, connection);
                if (version < 0) {
                    complete(new JSONObject().put("schema", "foldgpt.android-service-inspection.v1")
                        .put("state", "complete").put("servicePresent", false).put("nativeSpawnAttempted", false)
                        .put("ownershipEstablished", false));
                    return;
                }
            } else Shizuku.bindUserService(args, connection);
            main.postDelayed(() -> {
                if (!finished) {
                    cancel();
                    fail("Diagnostic reporting deadline exceeded; native owner retained, no retry");
                }
            }, 30000);
        } catch (Exception error) { fail(error.toString()); }
    }
    private static JSONObject boundedServiceReport(String encoded) throws Exception {
        if (encoded == null || encoded.length() > 32768) throw new IllegalStateException("Service report exceeds bound");
        return new JSONObject(encoded);
    }
    private void readOnly(IExecutorService service) {
        JSONObject result = new JSONObject();
        try {
            result.put("schema", "foldgpt.android-service-inspection.v1").put("servicePresent", true)
                .put("nativeSpawnAttempted", false).put("operation", oldStatusOnly ? "previous_v3_status" : "preflight_v6");
            if (preflightOnly) result.put("preflight", boundedServiceReport(service.preflight()));
            result.put("serviceStatus", boundedServiceReport(service.status()));
        } catch (Exception error) {
            try { result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage());
                result.put("serviceStatus", boundedServiceReport(service.status())); }
            catch (Exception statusError) { try { result.put("statusError", statusError.getClass().getSimpleName()); } catch (Exception ignored) { } }
        }
        try { result.put("state", "complete").put("transportCleanupComplete", false); } catch (Exception ignored) { }
        main.post(() -> complete(result));
    }
    private void runDiagnostic(IExecutorService service) {
        JSONObject result = new JSONObject();
        JSONArray frames = new JSONArray();
        boolean rpcSuccess = false;
        try {
            result.put("schema", "foldgpt.android-kernel-rpc.v1").put("nativeLibraryDir", getApplicationInfo().nativeLibraryDir)
                .put("clientUid", android.os.Process.myUid()).put("shizukuServerUid", Shizuku.getUid())
                .put("nativeEvidenceRequired", true);
            JSONObject preflight = boundedServiceReport(service.preflight());
            result.put("preflight", preflight);
            if (!Boolean.TRUE.equals(preflight.getJSONObject("admission").get("admitted"))) {
                throw new IllegalStateException("Read-only executor preflight refused before open");
            }
            if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled during preflight");
            nativeOpenAttempted = true;
            session = service.open(owner);
            if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled while opening the service");
            try (OutputStream output = new ParcelFileDescriptor.AutoCloseOutputStream(session.takeInput());
                 InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(session.takeOutput())) {
                send(output, new JSONObject("{\"id\":1,\"method\":\"initialize\",\"params\":{\"clientName\":\"foldgpt-fixed-kernel-qualification\"}}"));
                response(input, frames, 1);
                send(output, new JSONObject("{\"method\":\"initialized\"}"));
                byte[] request;
                try (InputStream asset = getAssets().open("foldgpt-kernel-request.json")) { request = asset.readAllBytes(); }
                JSONObject start = new JSONObject(new String(request, StandardCharsets.UTF_8));
                if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled before process/start");
                send(output, start); response(input, frames, start.getInt("id"));
                boolean closed = false;
                for (int i = 0; i < frames.length(); ++i) if (frames.getJSONObject(i).optString("method").equals("process/closed")) closed = true;
                while (!closed) {
                    JSONObject frame = read(input); frames.put(frame);
                    if (frames.length() > 128) throw new IllegalStateException("Too many RPC frames");
                    closed = frame.optString("method").equals("process/closed");
                }
                send(output, new JSONObject("{\"id\":3,\"method\":\"process/read\",\"params\":{\"processId\":\"kernel-qualification\"}}"));
                JSONObject read = response(input, frames, 3);
                result.put("read", read);
                ByteArrayOutputStream stdout = new ByteArrayOutputStream(), stderr = new ByteArrayOutputStream();
                JSONArray chunks = read.getJSONArray("chunks");
                for (int i = 0; i < chunks.length(); ++i) {
                    JSONObject chunk = chunks.getJSONObject(i);
                    byte[] bytes = android.util.Base64.decode(chunk.getString("chunk"), android.util.Base64.DEFAULT);
                    (chunk.getString("stream").equals("stdout") ? stdout : stderr).write(bytes);
                    if (stdout.size() + stderr.size() > 8192) throw new IllegalStateException("Worker output exceeds bound");
                }
                String observed = stdout.toString(StandardCharsets.UTF_8);
                result.put("stdout", observed).put("stderr", stderr.toString(StandardCharsets.UTF_8));
                JSONObject proofs = new JSONObject(observed);
                Set<String> flags = Set.of("success", "memoryRead", "memoryWrite", "pidfdGetfd", "sharedOffset",
                    "privateReadDenied", "protectedWriteDenied", "rawChdirDenied", "networkDenied", "ioctlDenied", "binderDenied",
                    "threadMemory", "threadPidfdGetfd");
                if (proofs.length() != flags.size() + 1 || !proofs.getString("type").equals("kernel-qualification")
                        || stderr.size() != 0 || !observed.endsWith("\n") || observed.strip().contains("\n")) {
                    throw new IllegalStateException("Fixed worker record differs from qualification contract");
                }
                for (String flag : flags) if (!Boolean.TRUE.equals(proofs.get(flag))) throw new IllegalStateException("Kernel proof failed: " + flag);
                if (!Boolean.TRUE.equals(read.get("exited")) || !Boolean.TRUE.equals(read.get("closed"))
                        || !(read.get("exitCode") instanceof Integer) || read.getInt("exitCode") != 0
                        || !read.isNull("failure")) throw new IllegalStateException("Worker did not exit cleanly");
                rpcSuccess = true;
            }
        } catch (Exception error) {
            try { result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage()); } catch (Exception ignored) { }
            try { result.put("serviceStatus", boundedServiceReport(service.status())); }
            catch (Exception statusError) { try { result.put("statusError", statusError.getClass().getSimpleName()); } catch (Exception ignored) { } }
        } finally {
            cancel();
            if (session != null) {
                long deadline = SystemClock.elapsedRealtime() + 7000;
                try {
                    JSONObject status;
                    do {
                        status = new JSONObject(session.status());
                        result.put("transport", status);
                        cleanupComplete = Boolean.TRUE.equals(status.get("cleanupComplete"))
                            && Boolean.TRUE.equals(status.get("bootstrapReaped"));
                        if (cleanupComplete || Boolean.TRUE.equals(status.get("quarantined"))) break;
                        Thread.sleep(50);
                    } while (SystemClock.elapsedRealtime() < deadline);
                } catch (Exception error) { try { result.put("cleanupError", error.toString()); } catch (Exception ignored) { } }
            }
            try { result.put("rpcSuccess", rpcSuccess).put("transportCleanupComplete", cleanupComplete)
                .put("state", "complete").put("frames", frames); } catch (Exception ignored) { }
            main.post(() -> complete(result));
        }
    }
    private static void send(OutputStream output, JSONObject frame) throws Exception {
        output.write((frame.toString() + "\n").getBytes(StandardCharsets.UTF_8)); output.flush();
    }
    private static JSONObject read(InputStream input) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); int value;
        while ((value = input.read()) != -1 && value != '\n') {
            if (bytes.size() >= 65536) throw new IllegalStateException("RPC frame exceeds bound"); bytes.write(value);
        }
        if (value == -1) throw new IllegalStateException("RPC transport ended before a complete response");
        return new JSONObject(bytes.toString(StandardCharsets.UTF_8));
    }
    private static JSONObject response(InputStream input, JSONArray frames, int id) throws Exception {
        for (int i = 0; i < 128; ++i) {
            JSONObject frame = read(input); frames.put(frame);
            if (frame.has("id") && frame.getInt("id") == id) {
                if (frame.has("error")) throw new IllegalStateException("RPC refusal: " + frame.get("error"));
                return frame.getJSONObject("result");
            }
        }
        throw new IllegalStateException("RPC response did not arrive within frame budget");
    }
    private void cancel() {
        cancelRequested = true;
        IExecutorSession current = session;
        if (current != null) try { current.cancel(); } catch (Exception ignored) { /* never promotes cleanup */ }
    }
    private void complete(JSONObject result) {
        // Late real cleanup evidence is valuable even after the reporting deadline.
        // This callback follows actual worker completion, unlike fail(deadline).
        running = false;
        finished = true;
        try { persist(result); text.setText(result.toString(2)); } catch (Exception error) { text.setText(error.toString()); }
        releaseIfClean();
    }
    private void fail(String message) {
        if (finished) return;
        cancel();
        finished = true;
        try { persist(new JSONObject().put("schema", "foldgpt.android-kernel-rpc.v1").put("state", "failed")
            .put("error", message).put("rpcSuccess", false).put("transportCleanupComplete", cleanupComplete)); }
        catch (Exception ignored) { }
        if (text != null) text.setText(message);
        releaseIfClean();
    }
    private void releaseIfClean() {
        if (bound && (preflightOnly || oldStatusOnly)) {
            // SDK remove=false unregisters only this observer, preserving the
            // service record and its current native ownership without destroy.
            try { Shizuku.unbindUserService(args, connection, false); bound = false; }
            catch (Exception error) { text.append("\nRead-only observer detach failed: " + error); }
        } else if (bound && cleanupComplete) {
            try { Shizuku.unbindUserService(args, connection, true); bound = false; }
            catch (Exception error) { text.append("\nService release failed: " + error); }
        }
    }
    private void persist(JSONObject report) throws Exception {
        report.put("diagnosticVersion", 10).put("requestedAction", requestedAction)
            .put("recordedWallTimeMs", System.currentTimeMillis())
            .put("recordedElapsedRealtimeMs", SystemClock.elapsedRealtime());
        AtomicFile file = new AtomicFile(new File(reportDirectory(), reportName));
        FileOutputStream output = file.startWrite();
        try { output.write((report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8)); file.finishWrite(output); }
        catch (Exception error) { file.failWrite(output); throw error; }
    }
    private File reportDirectory() throws Exception {
        File directory = new File(getFilesDir().getCanonicalFile(), REPORT_DIRECTORY);
        if ((!directory.isDirectory() && !directory.mkdir()) || !directory.getCanonicalFile().equals(directory)) {
            throw new SecurityException("Diagnostic report directory is not admitted");
        }
        return directory;
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        // Explicit am start may deliver to the existing top Activity. Previously
        // this was ignored and the caller unknowingly read an older report.
        if (!finished || running || (nativeOpenAttempted && !cleanupComplete)) {
            text.append("\nNew action refused while prior work or ownership remains unresolved.");
            return;
        }
        setIntent(new Intent(this, QualificationActivity.class).setAction(intent.getAction()));
        recreate();
    }
    @Override protected void onDestroy() {
        cancel(); releaseIfClean();
        Shizuku.removeBinderReceivedListener(received); Shizuku.removeBinderDeadListener(dead);
        Shizuku.removeRequestPermissionResultListener(permission); work.shutdown(); super.onDestroy();
    }
}
