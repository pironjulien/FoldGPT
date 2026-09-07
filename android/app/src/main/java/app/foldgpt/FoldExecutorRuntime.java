package app.foldgpt;

import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.AtomicFile;
import android.util.Log;
import app.foldgpt.shizukuexec.AppSocketBridge;
import app.foldgpt.shizukuexec.Deployment;
import app.foldgpt.shizukuexec.ExecutorService;
import app.foldgpt.shizukuexec.IExecutorService;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import rikka.shizuku.Shizuku;
import rikka.shizuku.ShizukuProvider;

/** Owns a deliberately selected native executor from FoldRuntimeService :runtime.
 * No application/UI command is silently redirected and no Shizuku permission,
 * server, wireless-debugging setting or legacy executor is started here.
 */
public final class FoldExecutorRuntime {
    public static final String ACTION_PREPARE = "app.foldgpt.action.PREPARE_NATIVE_EXECUTOR";
    private static final AtomicBoolean REQUESTED_BINDER = new AtomicBoolean();
    private static final RuntimeExitGate EXIT_GATE = new RuntimeExitGate();
    private final long generation;
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final java.util.concurrent.ExecutorService work = java.util.concurrent.Executors.newSingleThreadExecutor(
        task -> new Thread(task, "FoldGPT-executor-owner"));
    private final CompletableFuture<Void> closed = new CompletableFuture<>();
    private CompletableFuture<Endpoint> preparing;
    private Shizuku.UserServiceArgs args;
    private IExecutorService remote;
    private AppSocketBridge bridge;
    private boolean closing, bound, listeners, failed;
    private String failureReason;

    public record Endpoint(String socketPath, int peerUid) {}

    public FoldExecutorRuntime(Context context) {
        this.context = context.getApplicationContext();
        if (!(context.getPackageName() + ":runtime").equals(android.app.Application.getProcessName())) {
            throw new IllegalStateException("Native execution must be owned by FoldRuntimeService :runtime");
        }
        generation = EXIT_GATE.register();
    }

    public synchronized CompletableFuture<Endpoint> prepare() {
        if (closing) return CompletableFuture.failedFuture(new IllegalStateException("Native executor owner is closing"));
        if (preparing != null) return preparing;
        preparing = new CompletableFuture<>();
        work.execute(() -> {
            try {
                admitQualifiedDeployment();
                main.post(this::attachBinder);
            } catch (Exception | LinkageError error) { fail("qualified_native_deployment_unavailable", error); }
        });
        return preparing;
    }

    private final Shizuku.OnBinderReceivedListener binderReceived = () -> main.post(this::bind);
    private final Shizuku.OnBinderDeadListener binderDead = () -> {
        fail("shizuku_binder_lost", new IllegalStateException("Native ownership must be recovered before reconnecting"));
        requestStop();
    };
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            work.execute(() -> {
                synchronized (FoldExecutorRuntime.this) {
                    if (remote != null) return;
                    remote = IExecutorService.Stub.asInterface(binder);
                    if (closing || failed) { finishWhenClean(); return; }
                    try {
                        bridge = new AppSocketBridge(context, remote, new AppSocketBridge.Listener() {
                            @Override public void onFailure(String message, boolean cleanupUnknown) {
                                fail(cleanupUnknown ? "native_cleanup_unknown" : "native_transport_failed", new IllegalStateException(message));
                            }
                            @Override public void onSessionClosed() { work.execute(FoldExecutorRuntime.this::finishWhenClean); }
                        });
                        Endpoint endpoint = new Endpoint(bridge.socketPath(), bridge.peerUid());
                        persist("ready", null, endpoint);
                        preparing.complete(endpoint);
                    } catch (Exception | LinkageError error) { fail("native_endpoint_unavailable", error); }
                }
            });
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            fail("native_service_disconnected", new IllegalStateException("No automatic native backend reconnect"));
            requestStop();
        }
    };

    private synchronized void attachBinder() {
        if (closing || failed) { finishWhenClean(); return; }
        if (!listeners) {
            listeners = true;
            Shizuku.addBinderDeadListener(binderDead);
            Shizuku.addBinderReceivedListenerSticky(binderReceived);
        }
        ShizukuProvider.disableAutomaticSuiInitialization();
        ShizukuProvider.enableMultiProcessSupport(false);
        if (REQUESTED_BINDER.compareAndSet(false, true)) ShizukuProvider.requestBinderForNonProviderProcess(context);
        bind();
        // Official environment initialization window. No command is replayed
        // after timeout; a late binder response is only cleaned up.
        main.postDelayed(() -> {
            synchronized (FoldExecutorRuntime.this) {
                if (preparing != null && !preparing.isDone()) {
                    fail("shizuku_initialization_timeout", new IllegalStateException("Shizuku did not initialize within 30 seconds"));
                    requestStop();
                }
            }
        }, 30000);
    }
    private synchronized void bind() {
        if (closing || failed || bound || !Shizuku.pingBinder()) return;
        try {
            if (Shizuku.getUid() != 2000) throw new SecurityException("Shizuku is not the non-root shell backend");
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                throw new SecurityException("Official Shizuku authorization is not granted");
            }
            int version = Math.toIntExact(context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
            args = new Shizuku.UserServiceArgs(new ComponentName(context, ExecutorService.class))
                .daemon(false).tag("foldgpt-executor-v" + version).version(version)
                .processNameSuffix("executor").debuggable(false);
            bound = true;
            Shizuku.bindUserService(args, connection);
        } catch (Exception | LinkageError error) { fail("shizuku_authorization_or_binding_unavailable", error); }
    }

    /** Stop admission immediately; the completion future is native cleanup, not a deadline. */
    public synchronized CompletableFuture<Void> requestStop() {
        if (!closing) {
            closing = true;
            if (preparing != null && !preparing.isDone()) preparing.completeExceptionally(new IllegalStateException("Native executor stop requested"));
            if (bridge != null) bridge.close();
        }
        work.execute(this::finishWhenClean);
        return closed;
    }
    public void shutdownAfterCleanup(Runnable whenSafe) {
        EXIT_GATE.requestExit(generation, whenSafe);
        requestStop();
        scheduleProcessExitIfClean();
    }
    private void scheduleProcessExitIfClean() {
        main.post(EXIT_GATE::runExitIfClean);
    }
    private synchronized void finishWhenClean() {
        if (!closing || closed.isDone()) return;
        if (bridge != null && !bridge.cleanupComplete()) return;
        // If no remote was delivered, no bridge/session was constructed and no
        // worker command could have been admitted. Detaching that pending
        // connection is safe; a late callback only observes closing=true.
        if (remote != null) {
            try {
                JSONObject status = new JSONObject(remote.status());
                if (!"idle".equals(status.optString("state")) && !status.optBoolean("cleanupComplete", false)) return;
            } catch (Exception error) { return; } // The actual owner is not proven clean.
        }
        if (bound) {
            bound = false;
            // Detach only this connection. Another service instance may now
            // have a binding; never remove its shared UserService record.
            main.post(() -> {
                try { Shizuku.unbindUserService(args, connection, false); }
                catch (Exception error) { Log.w("FoldGPT-executor", "Detach failed after confirmed cleanup", error); }
            });
        }
        if (listeners) {
            listeners = false;
            Shizuku.removeBinderDeadListener(binderDead);
            Shizuku.removeBinderReceivedListener(binderReceived);
        }
        persist(failed ? "unavailable" : "closed", failureReason, null);
        closed.complete(null);
        EXIT_GATE.markClean(generation);
        scheduleProcessExitIfClean();
    }
    private synchronized void fail(String reason, Throwable cause) {
        failed = true;
        failureReason = reason;
        Log.e("FoldGPT-executor", reason, cause);
        persist("unavailable", reason, null);
        if (preparing != null && !preparing.isDone()) preparing.completeExceptionally(new IllegalStateException(reason, cause));
        if (closing) work.execute(this::finishWhenClean);
    }

    private void admitQualifiedDeployment() throws Exception {
        byte[] qualified = asset("foldgpt-executor-qualification.json", 65536);
        JSONObject qualification = new JSONObject(new String(qualified, StandardCharsets.UTF_8));
        if (!"foldgpt.shizuku.qualification.v1".equals(qualification.getString("schema"))
                || !"host-native-executor".equals(qualification.getString("scope"))) {
            throw new SecurityException("Unsupported native qualification scope");
        }
        byte[] deployment = asset("foldgpt-executor-deployment.json", 65536);
        byte[] manifest = asset("foldgpt-executor-manifest.json", 1024 * 1024);
        byte[] evidence = asset("foldgpt-executor-evidence.json", 1024 * 1024);
        requireHash(deployment, qualification.getString("deploymentSha256"));
        requireHash(manifest, qualification.getString("sourceManifestSha256"));
        requireHash(evidence, qualification.getString("evidenceSha256"));
        JSONObject proof = new JSONObject(new String(evidence, StandardCharsets.UTF_8));
        if (!Boolean.TRUE.equals(proof.get("success")) || !"host-native-executor".equals(proof.getString("scope"))) {
            throw new SecurityException("No passing host qualification for this exact deployment");
        }
        JSONArray files = new JSONArray(new String(manifest, StandardCharsets.UTF_8));
        Set<String> expected = new HashSet<>();
        for (int i = 0; i < files.length(); ++i) {
            JSONObject file = files.getJSONObject(i);
            String path = file.getString("path");
            if (path.isEmpty() || path.startsWith("/") || path.contains("\\") || path.indexOf('\0') >= 0
                    || java.util.Arrays.stream(path.split("/", -1)).anyMatch(part -> part.isEmpty() || part.equals(".") || part.equals(".."))
                    || !expected.add(path)) throw new SecurityException("Invalid qualified source manifest path");
            requireHash(asset("foldgpt-executor/" + path, 2 * 1024 * 1024), file.getString("sha256"));
        }
        Set<String> actual = new HashSet<>();
        listAssets("foldgpt-executor", "", actual);
        if (!expected.equals(actual) || !expected.contains("foldgpt_shizuku_bootstrap.py")) {
            throw new SecurityException("Installed executor sources differ from qualification");
        }
        JSONObject config = new JSONObject(new String(deployment, StandardCharsets.UTF_8));
        String factory = config.getString("backendFactory").split(":", -1)[0].replace('.', '/') + ".py";
        if (!expected.contains(factory)) throw new SecurityException("Qualified backend factory is absent");
        Deployment.verifyInstalledInputs(context);
    }
    private void listAssets(String root, String relative, Set<String> output) throws Exception {
        String location = relative.isEmpty() ? root : root + "/" + relative;
        String[] children = context.getAssets().list(location);
        if (children == null || children.length == 0) {
            if (!relative.isEmpty()) output.add(relative);
        } else for (String child : children) listAssets(root, relative.isEmpty() ? child : relative + "/" + child, output);
    }
    private byte[] asset(String name, int limit) throws Exception {
        try (InputStream input = context.getAssets().open(name)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] block = new byte[65536]; int count;
            while ((count = input.read(block)) >= 0) {
                if (bytes.size() + count > limit) throw new SecurityException("Native admission asset exceeds its bound");
                bytes.write(block, 0, count);
            }
            return bytes.toByteArray();
        }
    }
    private static void requireHash(byte[] data, String expected) throws Exception {
        if (!expected.matches("[0-9a-f]{64}")) throw new SecurityException("Invalid native qualification digest");
        StringBuilder digest = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(data)) digest.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        if (!expected.contentEquals(digest)) throw new SecurityException("Native qualification digest mismatch");
    }
    private synchronized void persist(String state, String reason, Endpoint endpoint) {
        AtomicFile file = new AtomicFile(new File(context.getFilesDir(), "native-executor-status.json"));
        FileOutputStream output = null;
        try {
            JSONObject status = new JSONObject().put("schema", "foldgpt.native.owner.v1").put("state", state)
                .put("generation", generation).put("selected", preparing != null).put("officialLauncherReplaced", false);
            if (reason != null) status.put("reason", reason);
            if (endpoint != null) status.put("socketPath", endpoint.socketPath()).put("peerUid", endpoint.peerUid());
            output = file.startWrite();
            output.write((status.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
            file.finishWrite(output);
        } catch (Exception error) {
            if (output != null) file.failWrite(output);
            Log.e("FoldGPT-executor", "Cannot persist native executor state", error);
        }
    }
}
