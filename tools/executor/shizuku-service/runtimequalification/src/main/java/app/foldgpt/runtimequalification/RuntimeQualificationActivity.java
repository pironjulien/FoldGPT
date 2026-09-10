package app.foldgpt.runtimequalification;

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

/** One fixed runtime diagnostic, through the production authenticated transport. */
public final class RuntimeQualificationActivity extends Activity {
    private static final String COLLECT_ACTION = ".RUNTIME_COLLECT_INFO";
    // Android can restore the previous Activity Intent after a package update.
    // An earlier APK's launch action must never reserve this revision's trial.
    private static final String AUTHORIZE_ACTION = ".RUNTIME_AUTHORIZE";
    private static final String PREFLIGHT_ACTION = ".RUNTIME_PREFLIGHT";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final java.util.concurrent.ExecutorService work = java.util.concurrent.Executors.newSingleThreadExecutor();
    private final Binder owner = new Binder();
    private TextView text;
    private volatile IExecutorSession session;
    private volatile boolean cleanupComplete;
    private volatile boolean cancelRequested;
    private volatile boolean nativeOpenAttempted;
    private boolean bound, permissionRequested, finished, running;
    private boolean preflightOnly, authorizeOnly, attemptReserved;
    private RuntimeProfile profile;
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
                if (preflightOnly) readOnly(service); else runDiagnostic(service);
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
        try { profile = RuntimeProfile.forPackage(getPackageName()); }
        catch (SecurityException error) { text.setText(error.toString()); finished = true; return; }
        if ((getPackageName() + COLLECT_ACTION).equals(getIntent().getAction())) {
            try {
                JSONObject info = new JSONObject().put("schema", "foldgpt.android-runtime-package.v1")
                    .put("nativeLibraryDir", getApplicationInfo().nativeLibraryDir).put("sourceDir", getApplicationInfo().sourceDir)
                    .put("clientUid", android.os.Process.myUid()).put("packageName", profile.packageName)
                    .put("nativeBase", profile.base).put("diagnosticVersion", profile.diagnosticVersion);
                File file = new File(reportDirectory(), "package-info.json");
                try (FileOutputStream output = new FileOutputStream(file)) {
                    output.write((info.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
                }
                text.setText(info.toString(2));
            } catch (Exception error) { text.setText(error.toString()); }
            finished = true; return;
        }
        preflightOnly = (getPackageName() + PREFLIGHT_ACTION).equals(getIntent().getAction());
        authorizeOnly = (getPackageName() + AUTHORIZE_ACTION).equals(getIntent().getAction());
        if (preflightOnly) reportName = "preflight.json";
        if (authorizeOnly) reportName = "authorization.json";
        if (!preflightOnly && !authorizeOnly && !(getPackageName() + profile.runAction).equals(getIntent().getAction())) {
            fail("Only the fixed runtime actions are admitted"); return;
        }
        try {
            if (!preflightOnly && !authorizeOnly
                    && new File(reportDirectory(), "attempt-started").exists()) {
                text.setText("An attempt was already reserved. Existing report and ownership are retained; no retry.");
                finished = true; return;
            }
            // Preserve the laboratory admission order. Independent profiles reserve
            // only after official authorization, immediately before its bind.
            persist(new JSONObject().put("schema", "foldgpt.android-runtime-rpc.v1").put("state", "pending")
                .put("nativeLibraryDir", getApplicationInfo().nativeLibraryDir).put("clientUid", android.os.Process.myUid()));
            text.setText("Waiting for official Shizuku authorization");
            if (!authorizeOnly) args = new Shizuku.UserServiceArgs(new ComponentName(this, ExecutorService.class))
                .daemon(false).tag(profile.serviceTag)
                .version(profile.serviceVersion)
                .processNameSuffix(profile.processSuffix).debuggable(false);
            Shizuku.addBinderDeadListener(dead);
            Shizuku.addRequestPermissionResultListener(permission);
            Shizuku.addBinderReceivedListenerSticky(received);
        } catch (Exception error) { fail(error.toString()); }
    }
    private void bind() {
        if (finished || bound || !Shizuku.pingBinder()) return;
        try {
            if (Shizuku.getUid() != 2000) {
                throw new SecurityException("Independent qualification requires nonroot Shizuku before any authorization request");
            }
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                if (preflightOnly || (!authorizeOnly)) {
                    throw new SecurityException("Existing official Shizuku authorization is required; use RUNTIME_AUTHORIZE first");
                }
                if (!permissionRequested) { permissionRequested = true; Shizuku.requestPermission(1); }
                return;
            }
            if (Shizuku.getUid() != 2000) throw new SecurityException("Only nonroot Shizuku UID 2000 is admitted");
            if (authorizeOnly) {
                complete(new JSONObject().put("schema", "foldgpt.android-shizuku-authorization.v1")
                    .put("state", "complete").put("authorized", true).put("shizukuServerUid", Shizuku.getUid())
                    .put("clientUid", android.os.Process.myUid()).put("nativeSpawnAttempted", false)
                    .put("attemptReserved", false).put("userServiceBindAttempted", false)
                    .put("transportCleanupComplete", false));
                return;
            }
            if (!preflightOnly && !reserveAttempt()) return;
            bound = true;
            Shizuku.bindUserService(args, connection);
            main.postDelayed(() -> {
                if (!finished) {
                    cancel();
                    fail("Diagnostic reporting deadline exceeded; native owner retained, no retry");
                }
            }, 60000);
        } catch (Exception error) { fail(error.toString()); }
    }
    private boolean reserveAttempt() throws Exception {
        if (attemptReserved) return true;
        if (!new File(reportDirectory(), "attempt-started").createNewFile()) {
            text.setText("An attempt was already reserved. Existing report and ownership are retained; no retry.");
            finished = true; return false;
        }
        attemptReserved = true;
        return true;
    }
    private static JSONObject boundedServiceReport(String encoded) throws Exception {
        if (encoded == null || encoded.length() > 32768) throw new IllegalStateException("Service report exceeds bound");
        return new JSONObject(encoded);
    }
    private void readOnly(IExecutorService service) {
        JSONObject result = new JSONObject();
        try {
            result.put("schema", "foldgpt.android-service-inspection.v1").put("servicePresent", true)
                .put("nativeSpawnAttempted", false).put("operation", "runtime_preflight_v" + profile.serviceVersion);
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
        JSONArray frames = new JSONArray(), requests = new JSONArray();
        boolean rpcSuccess = false;
        try {
            String nativeDirectory = new File(getApplicationInfo().nativeLibraryDir).getCanonicalPath();
            result.put("schema", "foldgpt.android-runtime-rpc.v1").put("nativeLibraryDir", nativeDirectory)
                .put("clientUid", android.os.Process.myUid()).put("shizukuServerUid", Shizuku.getUid())
                .put("nativeEvidenceRequired", true);
            JSONObject preflight = boundedServiceReport(service.preflight());
            result.put("preflight", preflight);
            if (!Boolean.TRUE.equals(preflight.getJSONObject("admission").get("admitted"))) {
                throw new IllegalStateException("Read-only executor preflight refused before open");
            }
            if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled during preflight");
            JSONObject plan;
            try (InputStream asset = getAssets().open("foldgpt-runtime-requests.json")) {
                plan = RuntimeContract.resolveRequests(asset.readAllBytes(), nativeDirectory, profile);
            }
            nativeOpenAttempted = true;
            session = service.open(owner);
            if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled while opening the service");
            try (OutputStream output = new ParcelFileDescriptor.AutoCloseOutputStream(session.takeInput());
                 InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(session.takeOutput())) {
                JSONObject initialize = new JSONObject().put("id", 1).put("method", "initialize")
                    .put("params", new JSONObject().put("clientName", "foldgpt-fixed-runtime-qualification"));
                requests.put(initialize); send(output, initialize); response(input, frames, 1);
                JSONObject initialized = new JSONObject().put("method", "initialized");
                requests.put(initialized); send(output, initialized);
                JSONObject start = plan.getJSONObject("start");
                if (cancelRequested) throw new IllegalStateException("Qualification admission was cancelled before process/start");
                requests.put(start); send(output, start); response(input, frames, 2);
                JSONObject write = plan.getJSONObject("write");
                requests.put(write); send(output, write);
                JSONObject written = response(input, frames, 3); result.put("stdinWrite", written);
                RuntimeContract.require(written.length() == 1 && "accepted".equals(written.get("status")),
                    "Exact RPC stdin was not accepted");
                boolean closed = false;
                for (int i = 0; i < frames.length(); ++i) if (frames.getJSONObject(i).optString("method").equals("process/closed")) closed = true;
                while (!closed) {
                    JSONObject frame = read(input); frames.put(frame);
                    if (frames.length() > 128) throw new IllegalStateException("Too many RPC frames");
                    closed = frame.optString("method").equals("process/closed");
                }
                JSONObject reading = plan.getJSONObject("read");
                requests.put(reading); send(output, reading);
                JSONObject read = response(input, frames, 4); result.put("read", read);
                JSONObject file = plan.getJSONObject("file");
                requests.put(file); send(output, file);
                JSONObject material = response(input, frames, 5); result.put("materialRead", material);
                byte[][] streams = RuntimeContract.streams(read);
                JSONObject worker = RuntimeContract.validateResult(streams[0], streams[1], read, material, nativeDirectory, profile);
                result.put("stdout", new String(streams[0], StandardCharsets.UTF_8))
                    .put("stderr", new String(streams[1], StandardCharsets.UTF_8)).put("worker", worker)
                    .put("stdoutBase64", java.util.Base64.getEncoder().encodeToString(streams[0]))
                    .put("stderrBase64", java.util.Base64.getEncoder().encodeToString(streams[1]));
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
                .put("state", "complete").put("frames", frames).put("requests", requests); } catch (Exception ignored) { }
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
        try { persist(new JSONObject().put("schema", "foldgpt.android-runtime-rpc.v1").put("state", "failed")
            .put("error", message).put("rpcSuccess", false).put("transportCleanupComplete", cleanupComplete)); }
        catch (Exception ignored) { }
        if (text != null) text.setText(message);
        releaseIfClean();
    }
    private void releaseIfClean() {
        if (bound && (preflightOnly)) {
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
        report.put("diagnosticVersion", profile.diagnosticVersion).put("requestedAction", requestedAction)
            .put("packageName", profile.packageName).put("nativeBase", profile.base)
            .put("recordedWallTimeMs", System.currentTimeMillis())
            .put("recordedElapsedRealtimeMs", SystemClock.elapsedRealtime());
        AtomicFile file = new AtomicFile(new File(reportDirectory(), reportName));
        FileOutputStream output = file.startWrite();
        try { output.write((report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8)); file.finishWrite(output); }
        catch (Exception error) { file.failWrite(output); throw error; }
    }
    private File reportDirectory() throws Exception {
        File directory = new File(getFilesDir().getCanonicalFile(), profile.reportDirectory);
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
        setIntent(new Intent(this, RuntimeQualificationActivity.class).setAction(intent.getAction()));
        recreate();
    }
    @Override protected void onDestroy() {
        cancel(); releaseIfClean();
        Shizuku.removeBinderReceivedListener(received); Shizuku.removeBinderDeadListener(dead);
        Shizuku.removeRequestPermissionResultListener(permission); work.shutdown(); super.onDestroy();
    }
}
