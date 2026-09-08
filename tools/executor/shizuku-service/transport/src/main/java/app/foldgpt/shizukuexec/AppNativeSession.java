package app.foldgpt.shizukuexec;

import android.content.Context;
import android.os.Binder;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;

/** Local application owner. No exported service, privileged server or command relay. */
public final class AppNativeSession extends IExecutorSession.Stub {
    // Strong process-lifetime ownership: GC, a cancelled caller or an admission
    // exception cannot discard a live or quarantined generation.
    private static AppNativeSession current;
    private final SessionState state;
    private final int applicationUid;
    private final String nonce;
    private final AdmissionTrace admission;
    private final CountDownLatch launchFinished = new CountDownLatch(1);
    private ParcelFileDescriptor input, output, control;
    private volatile int childPid = -1;
    private JSONObject admissionResult;

    private AppNativeSession(int uid, String nonce, AdmissionTrace trace) {
        applicationUid = uid;
        this.nonce = nonce;
        state = SessionState.forApplication(Os.getuid(), uid);
        admission = trace;
    }

    public static synchronized IExecutorSession open(Context context, String launchPath, String nonce) {
        int uid = context.getApplicationInfo().uid;
        SessionState.forApplication(Os.getuid(), uid).authenticate(Binder.getCallingUid());
        if (current != null && !current.state.releasable())
            throw new IllegalStateException("Existing application session retains native ownership");
        AdmissionTrace trace = new AdmissionTrace();
        try {
            Deployment deployment = Deployment.forApplication(context, trace, launchPath, nonce);
            trace.at(AdmissionTrace.Stage.TRANSPORT_LOAD);
            AppNativeSpawn.load(deployment.transportLibrary);
            AppNativeSession session = new AppNativeSession(uid, nonce, trace);
            current = session;
            session.launch(deployment);
            return session;
        } catch (Exception | LinkageError error) {
            throw new IllegalStateException("Application executor admission failed: " + trace.result(false, error), error);
        }
    }

    private static void authenticateContext(Context context) {
        SessionState.forApplication(Os.getuid(), context.getApplicationInfo().uid).authenticate(Binder.getCallingUid());
    }
    /** Retained owner remains observable even when open failed after publication. */
    public static synchronized String cleanupStatus(Context context) {
        authenticateContext(context);
        if (current != null) return current.status();
        return idleStatus();
    }
    /** A prior failed opener cannot observe a later generation as its own. */
    public static synchronized String cleanupStatus(Context context, String nonce) {
        authenticateContext(context);
        requireNonce(nonce);
        if (current != null && current.nonce.equals(nonce)) return current.status();
        // open cannot replace an owner until its state is releasable. A
        // different current nonce thus cannot hide an older retained owner.
        return idleStatus();
    }
    private static String idleStatus() {
        try {
            return new JSONObject().put("state", "idle").put("launchOrigin", "android-app")
                    .put("cleanupComplete", true).put("ownerRetained", false).toString();
        } catch (Exception error) { throw new IllegalStateException("Application owner status failed", error); }
    }
    public static synchronized void requestCurrentStop(Context context) {
        authenticateContext(context);
        if (current != null) current.requestCancel();
    }
    public static synchronized void requestCurrentStop(Context context, String nonce) {
        authenticateContext(context);
        requireNonce(nonce);
        if (current != null && current.nonce.equals(nonce)) current.requestCancel();
    }
    private static void requireNonce(String nonce) {
        if (nonce == null || !nonce.matches("[0-9a-f]{32}"))
            throw new SecurityException("Application session nonce is required");
    }

    private synchronized void launch(Deployment deployment) throws Exception {
        ParcelFileDescriptor[] stdin = null, stdout = null, reports = null, controls = null;
        boolean observerStarted = false;
        try {
            admission.at(AdmissionTrace.Stage.PIPE_CREATE);
            stdin = ParcelFileDescriptor.createPipe();
            stdout = ParcelFileDescriptor.createPipe();
            reports = ParcelFileDescriptor.createPipe();
            controls = ParcelFileDescriptor.createPipe();
            input = stdin[1]; output = stdout[0]; control = controls[1];
            admission.at(AdmissionTrace.Stage.OBSERVER_START);
            final ParcelFileDescriptor report = reports[0];
            // Start the Java observer BEFORE fork. Failure to start a thread
            // therefore cannot strand a child without its waitpid owner.
            Thread observer = new Thread(() -> observe(report), "foldgpt-app-executor-owner");
            observer.start();
            observerStarted = true;
            admission.at(AdmissionTrace.Stage.NATIVE_FORK);
            childPid = AppNativeSpawn.launch(deployment.executable, deployment.argv,
                    applicationUid, deployment.workingDirectory,
                    stdin[0].getFd(), stdout[1].getFd(), reports[1].getFd(), controls[0].getFd());
            if (childPid <= 0) throw new IllegalStateException("Native launch returned no owned child");
            admission.at(AdmissionTrace.Stage.COMPLETE);
            admissionResult = admission.result(true, null);
        } catch (Exception | LinkageError error) {
            admissionResult = admission.result(false, error);
            if (childPid < 0) state.admissionRefused();
            else { state.fail(); requestCancel(); }
            throw error;
        } finally {
            if (childPid < 0) {
                closeAll(stdin); closeAll(stdout); closeAll(controls);
                input = output = control = null;
                if (reports != null) {
                    closeOne(reports[1]);
                    if (!observerStarted) closeOne(reports[0]);
                }
            } else {
                closeOne(stdin[0]); closeOne(stdout[1]); closeOne(reports[1]); closeOne(controls[0]);
            }
            launchFinished.countDown();
        }
    }

    private void authenticate() {
        if (Os.getuid() != applicationUid) throw new SecurityException("Application owner identity changed");
        state.authenticate(Binder.getCallingUid());
    }
    @Override public ParcelFileDescriptor takeInput() {
        authenticate();
        throw new IllegalStateException("Native channels are published directly with SCM_RIGHTS");
    }
    @Override public ParcelFileDescriptor takeOutput() {
        authenticate();
        throw new IllegalStateException("Native channels are published directly with SCM_RIGHTS");
    }
    @Override public void cancel() { authenticate(); requestCancel(); }
    @Override public synchronized String status() {
        authenticate();
        try {
            return new JSONObject(state.json()).put("bootstrapPid", childPid)
                    .put("directNative", true).put("launchOrigin", "android-app")
                    .put("admission", admissionResult == null ? JSONObject.NULL : admissionResult).toString();
        } catch (Exception error) { throw new IllegalStateException("Application session status failed", error); }
    }
    private synchronized void requestCancel() {
        state.cancel();
        // Closing this dedicated FD never waits behind a command writer. The
        // kernel also closes it when the application owner process dies.
        closeOne(control); control = null;
        closeOne(input); input = null;
    }
    private void observe(ParcelFileDescriptor report) {
        boolean interrupted = false;
        for (;;) {
            try { launchFinished.await(); break; }
            catch (InterruptedException error) { interrupted = true; requestCancel(); }
        }
        if (childPid < 0) { closeOne(report); if (interrupted) Thread.currentThread().interrupt(); return; }
        try (InputStream stream = new ParcelFileDescriptor.AutoCloseInputStream(report)) {
            ByteArrayOutputStream line = new ByteArrayOutputStream();
            int value, frames = 0;
            while ((value = stream.read()) != -1) {
                if (value == '\n') {
                    if (++frames > SessionState.MAX_REPORTS) throw new IllegalStateException("Too many private lifecycle reports");
                    state.report(line.toString(StandardCharsets.US_ASCII)); line.reset();
                } else {
                    if (value > 127 || line.size() >= 512) throw new IllegalStateException("Invalid private report frame");
                    line.write(value);
                }
            }
            if (line.size() != 0) throw new IllegalStateException("Incomplete private lifecycle report");
        } catch (Exception error) { state.fail(); requestCancel(); }
        try { state.reaped(AppNativeSpawn.waitChild(childPid)); }
        catch (Exception | LinkageError error) { state.fail(); requestCancel(); }
        if (state.releasable()) {
            synchronized (this) {
                closeOne(control); control = null; closeOne(input); input = null; closeOne(output); output = null;
            }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }
    private static void closeOne(ParcelFileDescriptor descriptor) {
        if (descriptor != null) try { descriptor.close(); }
        catch (Exception ignored) { /* Cleanup evidence is independently required. */ }
    }
    private static void closeAll(ParcelFileDescriptor[] descriptors) {
        if (descriptors != null) for (ParcelFileDescriptor descriptor : descriptors) closeOne(descriptor);
    }
}
