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
import app.foldgpt.shizukuexec.AppNativeSession;
import app.foldgpt.shizukuexec.Deployment;
import app.foldgpt.shizukuexec.ExecutorService;
import app.foldgpt.shizukuexec.IExecutorService;
import app.foldgpt.shizukuexec.IExecutorSession;
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
    private final RuntimeOwnerWorker work = new RuntimeOwnerWorker("FoldGPT-executor-owner");
    private final CompletableFuture<Void> closed = new CompletableFuture<>();
    private final CompletableFuture<Throwable> failure = new CompletableFuture<>();
    private final CompletableFuture<Void> ownerDeath = new CompletableFuture<>();
    private CompletableFuture<Endpoint> preparing;
    private Shizuku.UserServiceArgs args;
    private IExecutorService remote;
    private AppSocketBridge bridge;
    private IExecutorSession nativeSession;
    private final android.os.Binder nativeOwner = new android.os.Binder();
    private NativeLaunch nativeLaunch;
    private boolean directNative, applicationLaunch;
    private boolean closing, bound, listeners, failed;
    private boolean permissionRequested;
    private String failureReason, failureDetail;
    private JSONObject lastRemoteStatus, lastNativeSessionStatus;
    private Endpoint lastEndpoint;
    private String recordedState = "idle", lastPersisted;

    public record Endpoint(String socketPath, int peerUid, String startupManifest, String workspace,
                           String endpointRoot, String pythonRoot, String nativeRoot) {
        public boolean directNative() { return startupManifest != null; }
    }

    public FoldExecutorRuntime(Context context) {
        this.context = context.getApplicationContext();
        if (!(context.getPackageName() + ":runtime").equals(android.app.Application.getProcessName())) {
            throw new IllegalStateException("Native execution must be owned by FoldRuntimeService :runtime");
        }
        generation = EXIT_GATE.register();
    }

    public synchronized CompletableFuture<Endpoint> prepare() {
        try { return prepare(app.foldgpt.install.GuestIdentity.load(new File(context.getFilesDir(), "debian").toPath()).home); }
        catch (Exception error) { return CompletableFuture.failedFuture(error); }
    }
    /** Only an installed explicit production schema selects the normal UI route. */
    public boolean isNativeSelected() throws Exception {
        String[] assets = context.getAssets().list("");
        if (assets == null || !java.util.Arrays.asList(assets).contains("foldgpt-executor-deployment.json")) return false;
        JSONObject deployment = new JSONObject(new String(asset("foldgpt-executor-deployment.json", 65536), StandardCharsets.UTF_8));
        String schema = deployment.getString("schema");
        if (schema.equals("foldgpt.native.deployment.v1") || schema.equals("foldgpt.native.deployment.v2")) return true;
        if (schema.equals("foldgpt.shizuku.deployment.v1")) return false;
        throw new SecurityException("Installed executor selection has an unsupported schema");
    }
    public synchronized CompletableFuture<Endpoint> prepare(String controllerHome) {
        if (closing) return CompletableFuture.failedFuture(new IllegalStateException("Native executor owner is closing"));
        if (preparing != null) return preparing;
        preparing = new CompletableFuture<>();
        persist("preparing", null, null);
        work.execute(() -> {
            try {
                admitQualifiedDeployment();
                if (directNative) nativeLaunch = new NativeLaunch(context, controllerHome);
                Deployment.verifyInstalledInputs(context);
                if (applicationLaunch) openApplicationSession();
                else main.post(this::attachBinder);
            } catch (Exception | LinkageError error) { fail("qualified_native_deployment_unavailable", error); }
        });
        return preparing;
    }

    /** Application-origin deployments never enter the privileged service route. */
    private synchronized void openApplicationSession() {
        if (closing || failed) { finishWhenClean(); return; }
        try {
            nativeSession = AppNativeSession.open(context, nativeLaunch.launchPath, nativeLaunch.nonce);
            observeNative();
        } catch (Exception | LinkageError error) {
            fail("application_native_endpoint_unavailable", error);
            requestStop();
        }
    }

    private final Shizuku.OnBinderReceivedListener binderReceived = () -> main.post(this::bind);
    private final Shizuku.OnRequestPermissionResultListener permissionResult = (code, result) -> main.post(() -> {
        synchronized (FoldExecutorRuntime.this) {
            if (code != 1 || closing || failed) return;
            if (result == PackageManager.PERMISSION_GRANTED) bind();
            else {
                fail("shizuku_authorization_denied", new SecurityException("Official Shizuku authorization was denied"));
                requestStop();
            }
        }
    });
    private final Shizuku.OnBinderDeadListener binderDead = () -> {
        synchronized (FoldExecutorRuntime.this) { if (closed.isDone()) return; }
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
                        if (directNative) {
                            nativeSession = remote.openNative(nativeOwner, nativeLaunch.launchPath, nativeLaunch.nonce);
                            observeNative();
                            return;
                        }
                        bridge = new AppSocketBridge(context, remote, new AppSocketBridge.Listener() {
                            @Override public void onFailure(String message, boolean cleanupUnknown) {
                                fail(cleanupUnknown ? "native_cleanup_unknown" : "native_transport_failed", new IllegalStateException(message));
                            }
                            @Override public void onSessionClosed() { work.execute(FoldExecutorRuntime.this::finishWhenClean); }
                        });
                        Endpoint endpoint = new Endpoint(bridge.socketPath(), bridge.peerUid(), null, null, null, null, null);
                        persist("ready", null, endpoint);
                        preparing.complete(endpoint);
                    } catch (Exception | LinkageError error) {
                        // openNative may have refused before returning a session.
                        // Retain the actual service admission diagnostic as well.
                        try { lastRemoteStatus = new JSONObject(remote.status()); }
                        catch (Exception unavailable) { /* Keep the last observed response, if any. */ }
                        fail("native_endpoint_unavailable", error);
                    }
                }
            });
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            synchronized (FoldExecutorRuntime.this) { if (closed.isDone()) return; }
            fail("native_service_disconnected", new IllegalStateException("No automatic native backend reconnect"));
            requestStop();
        }
    };

    /** Readiness is the native private report plus the actual fork PID and inode manifest. */
    private synchronized void observeNative() {
        if (nativeSession == null || closed.isDone()) return;
        try {
            refreshEvidence();
            JSONObject status = lastNativeSessionStatus;
            if (closing) { finishWhenClean(); return; }
            NativeSessionObservation.Outcome outcome = NativeSessionObservation.outcome(status);
            if (outcome == NativeSessionObservation.Outcome.CLOSED) {
                // Normal controller EOF closes the native session with a zero
                // exit. Keep that successful lifecycle; do not invent a cancel
                // request or an endpoint failure after the real clean wait.
                closing = true;
                if (!preparing.isDone()) preparing.completeExceptionally(
                        new IllegalStateException("Native session closed before endpoint delivery"));
                finishWhenClean();
                return;
            }
            if (outcome == NativeSessionObservation.Outcome.FAILED) {
                throw new IllegalStateException("Native session refused or stopped: " + status);
            }
            if (status.optBoolean("ready") && !preparing.isDone()) {
                int uid = context.getApplicationInfo().uid;
                nativeLaunch.verifyReady(status.getInt("bootstrapPid"), uid);
                Endpoint endpoint = new Endpoint(nativeLaunch.socketPath, uid, nativeLaunch.manifestPath,
                        nativeLaunch.workspace, nativeLaunch.endpointRoot, nativeLaunch.pythonRoot, nativeLaunch.nativeRoot);
                persist("ready", null, endpoint);
                preparing.complete(endpoint);
            }
            persist(recordedState, failureReason, null);
        } catch (Exception error) {
            fail("native_session_unavailable", error);
            requestStop();
            return;
        }
        main.postDelayed(() -> work.execute(this::observeNative), 200);
    }

    /** Each value is a copy of a real response, never reconstructed from flags. */
    private void refreshEvidence() throws Exception {
        if (nativeSession != null) lastNativeSessionStatus = new JSONObject(nativeSession.status());
        else if (applicationLaunch && nativeLaunch != null) {
            lastNativeSessionStatus = new JSONObject(AppNativeSession.cleanupStatus(context, nativeLaunch.nonce));
        }
        if (remote != null) lastRemoteStatus = new JSONObject(remote.status());
        if (applicationLaunch && nativeSession != null
                && NativeSessionObservation.requiresProcessRetirement(lastNativeSessionStatus)) {
            // Also observed during closing: the workspace may exit before this
            // owner is reaped, so the normal readiness observer is insufficient.
            ownerDeath.complete(null);
        }
    }

    private synchronized void attachBinder() {
        if (closing || failed) { finishWhenClean(); return; }
        if (!listeners) {
            listeners = true;
            Shizuku.addBinderDeadListener(binderDead);
            Shizuku.addRequestPermissionResultListener(permissionResult);
            Shizuku.addBinderReceivedListenerSticky(binderReceived);
        }
        ShizukuProvider.disableAutomaticSuiInitialization();
        ShizukuProvider.enableMultiProcessSupport(false);
        if (REQUESTED_BINDER.compareAndSet(false, true)) ShizukuProvider.requestBinderForNonProviderProcess(context);
        // Only the official binder-received callback establishes completed
        // attachApplication. pingBinder alone can precede its UID/permission data.
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
            int serviceUid = Shizuku.getUid();
            if (serviceUid != 2000) throw new SecurityException("Shizuku is not the non-root shell backend; observed UID=" + serviceUid);
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                if (!permissionRequested) {
                    permissionRequested = true;
                    persist("awaiting_authorization", null, null);
                    Shizuku.requestPermission(1);
                }
                return;
            }
            int version = Math.toIntExact(context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
            args = new Shizuku.UserServiceArgs(new ComponentName(context, ExecutorService.class))
                // Stable IPC identity; APK version changes ask Shizuku to
                // retire the former service through its cleanup-aware destroy.
                .daemon(false).tag("foldgpt-executor-v2").version(version)
                .processNameSuffix("executor").debuggable(false);
            bound = true;
            Shizuku.bindUserService(args, connection);
        } catch (Exception | LinkageError error) { fail("shizuku_authorization_or_binding_unavailable", error); }
    }

    /** First observed owner failure, including failures after successful startup. */
    public CompletableFuture<Throwable> failure() { return failure; }

    /** Owner wait without cleanup, distinct from successful session closure. */
    public CompletableFuture<Void> ownerDeath() { return ownerDeath; }

    /** Called on the main thread after durable recovery/stop intent is saved. */
    public synchronized boolean retireProcessAfterOwnerDeath(Runnable exit) throws Exception {
        if (!applicationLaunch || nativeSession == null || closed.isDone()) return false;
        refreshEvidence();
        if (!NativeSessionObservation.requiresProcessRetirement(lastNativeSessionStatus)) return false;
        persist("owner-exited-unclean", "android_process_group_retirement", null);
        return EXIT_GATE.runExitAfterOwnerDeath(generation, exit);
    }

    /** Stop admission immediately; the completion future is native cleanup, not a deadline. */
    public synchronized CompletableFuture<Void> requestStop() {
        if (closed.isDone()) return closed;
        if (!closing) {
            closing = true;
            if (preparing != null && !preparing.isDone()) preparing.completeExceptionally(new IllegalStateException("Native executor stop requested"));
            if (bridge != null) bridge.close();
            if (nativeSession != null) try { nativeSession.cancel(); }
            catch (Exception error) { fail("native_cancel_unconfirmed", error); }
            else if (applicationLaunch && nativeLaunch != null) try { AppNativeSession.requestCurrentStop(context, nativeLaunch.nonce); }
            catch (Exception | LinkageError error) { fail("application_native_cancel_unconfirmed", error); }
            persist(failed ? "unavailable" : "stopping", failureReason, null);
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
        // Local ownership needs the same terminal report AND real wait as the
        // remote service. An absent Binder is not evidence of local cleanup.
        if (applicationLaunch && nativeLaunch != null) {
            try {
                refreshEvidence();
                if (!lastNativeSessionStatus.getBoolean("cleanupComplete")
                        || lastNativeSessionStatus.getBoolean("ownerRetained")) {
                    persist(recordedState, failureReason, null);
                    main.postDelayed(() -> work.execute(this::finishWhenClean), 200);
                    return;
                }
            } catch (Exception | LinkageError error) {
                persist(recordedState, failureReason, null);
                return;
            }
        }
        // A pending remote connection cannot admit commands before its callback.
        if (remote != null) {
            try {
                refreshEvidence();
                JSONObject status = lastRemoteStatus;
                persist(recordedState, failureReason, null);
                if (!"idle".equals(status.optString("state")) && !status.optBoolean("cleanupComplete", false)) {
                    main.postDelayed(() -> work.execute(this::finishWhenClean), 200);
                    return;
                }
            } catch (Exception error) {
                // A successful first response must survive a later Binder read
                // failure. Neither a stale copy nor EOF grants cleanup.
                persist(recordedState, failureReason, null);
                return;
            }
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
            Shizuku.removeRequestPermissionResultListener(permissionResult);
            Shizuku.removeBinderReceivedListener(binderReceived);
        }
        persist(failed ? "unavailable" : "closed", failureReason, null);
        // Native cleanup is now proven. Drain accepted callbacks and retire this
        // generation's worker; already posted observer ticks become harmless.
        work.close();
        EXIT_GATE.markClean(generation);
        closed.complete(null);
        scheduleProcessExitIfClean();
    }
    private synchronized void fail(String reason, Throwable cause) {
        failed = true;
        failureReason = reason;
        failureDetail = cause == null ? null : cause.getClass().getName() + ": " + cause.getMessage();
        if (failureDetail != null && failureDetail.length() > 4096) failureDetail = failureDetail.substring(0, 4096) + "[truncated]";
        Log.e("FoldGPT-executor", reason, cause);
        persist("unavailable", reason, null);
        if (preparing != null && !preparing.isDone()) preparing.completeExceptionally(new IllegalStateException(reason, cause));
        failure.complete(new IllegalStateException(reason, cause));
        if (closing) work.execute(this::finishWhenClean);
    }

    private void admitQualifiedDeployment() throws Exception {
        byte[] qualified = asset("foldgpt-executor-qualification.json", 65536);
        JSONObject qualification = new JSONObject(new String(qualified, StandardCharsets.UTF_8));
        directNative = "foldgpt.native.package.v1".equals(qualification.getString("schema"));
        String scope = directNative ? "native-production-candidate" : "host-native-executor";
        if ((!directNative && !"foldgpt.shizuku.qualification.v1".equals(qualification.getString("schema")))
                || !scope.equals(qualification.getString("scope"))) {
            throw new SecurityException("Unsupported native qualification scope");
        }
        byte[] deployment = asset("foldgpt-executor-deployment.json", 65536);
        byte[] manifest = asset("foldgpt-executor-manifest.json", 1024 * 1024);
        byte[] evidence = asset("foldgpt-executor-evidence.json", 1024 * 1024);
        requireHash(deployment, qualification.getString("deploymentSha256"));
        requireHash(manifest, qualification.getString("sourceManifestSha256"));
        requireHash(evidence, qualification.getString("evidenceSha256"));
        JSONObject proof = new JSONObject(new String(evidence, StandardCharsets.UTF_8));
        if (!directNative && (!Boolean.TRUE.equals(proof.get("success")) || !scope.equals(proof.getString("scope")))) {
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
        JSONObject config = new JSONObject(new String(deployment, StandardCharsets.UTF_8));
        String schema = config.getString("schema");
        applicationLaunch = "foldgpt.native.deployment.v2".equals(schema);
        if (directNative != (applicationLaunch || "foldgpt.native.deployment.v1".equals(schema))
                || (applicationLaunch && (!"android-app".equals(config.getString("launchOrigin"))
                    || !"android-app".equals(qualification.getString("launchOrigin"))))
                || (!applicationLaunch && (config.has("launchOrigin") || qualification.has("launchOrigin")))) {
            throw new SecurityException("Native package and launch origin disagree");
        }
        if (applicationLaunch) {
            requireHash(asset("foldgpt-app-launch-build.json", 65536), qualification.getString("appLaunchBuildSha256"));
        } else if (qualification.has("appLaunchBuildSha256")) {
            throw new SecurityException("Application launcher attestation in another launch origin");
        }
        String entry = applicationLaunch ? "foldgpt_app_bootstrap.py"
                : directNative ? "foldgpt_native_bootstrap.py" : "foldgpt_shizuku_bootstrap.py";
        if (!expected.equals(actual) || !expected.contains(entry)) {
            throw new SecurityException("Installed executor sources differ from qualification");
        }
        String factory = config.getString("backendFactory").split(":", -1)[0].replace('.', '/') + ".py";
        if (!expected.contains(factory)) throw new SecurityException("Qualified backend factory is absent");
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
        // A STOP received after the service exited can instantiate a new idle
        // owner. Its no-op cleanup must not overwrite the last selected session.
        if (preparing == null) return;
        recordedState = state;
        if (endpoint != null) lastEndpoint = endpoint;
        AtomicFile file = new AtomicFile(new File(context.getFilesDir(), "native-executor-status.json"));
        FileOutputStream output = null;
        try {
            JSONObject status = new JSONObject().put("schema", "foldgpt.native.owner.v1").put("state", state)
                .put("generation", generation).put("selected", preparing != null).put("officialLauncherReplaced", false);
            status.put("launchOrigin", applicationLaunch ? "android-app" : "run-as");
            status.put("lastRemoteStatus", lastRemoteStatus == null ? JSONObject.NULL : lastRemoteStatus)
                .put("lastNativeSessionStatus", lastNativeSessionStatus == null ? JSONObject.NULL : lastNativeSessionStatus);
            if (reason != null) status.put("reason", reason);
            if (failureDetail != null) status.put("errorDetail", failureDetail);
            if (lastEndpoint != null) {
                status.put("socketPath", lastEndpoint.socketPath()).put("peerUid", lastEndpoint.peerUid()).put("directNative", lastEndpoint.directNative());
                if (lastEndpoint.directNative()) status.put("startupManifest", lastEndpoint.startupManifest()).put("workspace", lastEndpoint.workspace());
            }
            String encoded = status.toString(2) + "\n";
            if (encoded.equals(lastPersisted)) return;
            output = file.startWrite();
            output.write(encoded.getBytes(StandardCharsets.UTF_8));
            file.finishWrite(output);
            lastPersisted = encoded;
        } catch (Exception error) {
            if (output != null) file.failWrite(output);
            Log.e("FoldGPT-executor", "Cannot persist native executor state", error);
        }
    }
}
