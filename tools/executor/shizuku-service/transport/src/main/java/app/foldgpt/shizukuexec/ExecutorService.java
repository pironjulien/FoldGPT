package app.foldgpt.shizukuexec;

import android.content.Context;
import android.os.Binder;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Authenticated owner of a fixed packaged backend; no privileged command API. */
public final class ExecutorService extends IExecutorService.Stub {
    private final int clientUid;
    private final Context context;
    private Session current;
    private boolean destroyRequested;
    private JSONObject lastAdmission, lastPreflight;

    public ExecutorService(Context context) {
        this.context = context;
        clientUid = context.getApplicationInfo().uid;
        new SessionState(Os.getuid(), clientUid);
    }
    private void authenticate() {
        if (Binder.getCallingUid() != clientUid) throw new SecurityException("Unauthorized executor caller");
    }
    @Override public synchronized IExecutorSession open(IBinder owner) {
        return open(owner, null, null);
    }
    @Override public synchronized IExecutorSession openNative(IBinder owner, String launchPath, String nonce) {
        if (launchPath == null || nonce == null) throw new SecurityException("Native launch identity is required");
        return open(owner, launchPath, nonce);
    }
    private IExecutorSession open(IBinder owner, String launchPath, String nonce) {
        authenticate();
        AdmissionTrace trace = new AdmissionTrace();
        try {
            if (destroyRequested) throw new IllegalStateException("Service destruction is already pending");
            if (owner == null || !owner.isBinderAlive()) throw new IllegalArgumentException("A live client owner is required");
            if (current != null && !current.state.releasable()) {
                throw new IllegalStateException("Existing session retains native ownership");
            }
            Deployment deployment = new Deployment(context, trace, launchPath, nonce);
            if (deployment.directNative && launchPath == null) throw new SecurityException("Native deployment requires explicit direct startup");
            trace.at(AdmissionTrace.Stage.TRANSPORT_LOAD);
            NativeSpawn.load(deployment.transportLibrary);
            trace.at(AdmissionTrace.Stage.OWNER_LINK);
            Session session = new Session(owner);
            // Publish owner before native fork so destroy/death cannot race an
            // unregistered native child. Failed launch remains explicit.
            current = session;
            session.launch(deployment, trace);
            trace.at(AdmissionTrace.Stage.COMPLETE);
            lastAdmission = trace.result(true, null);
            return session;
        } catch (Exception | LinkageError error) {
            lastAdmission = trace.result(false, error);
            throw new IllegalStateException("Executor admission failed; authenticated status contains the bounded cause", error);
        }
    }
    @Override public synchronized String status() {
        authenticate();
        try {
            JSONObject result = current == null ? new JSONObject().put("state", "idle") : current.snapshot();
            return result.put("admission", lastAdmission == null ? JSONObject.NULL : lastAdmission)
                .put("preflight", lastPreflight == null ? JSONObject.NULL : lastPreflight).toString();
        } catch (Exception error) { throw new IllegalStateException("Executor status encoding failed", error); }
    }
    @Override public synchronized String preflight() {
        authenticate();
        AdmissionTrace trace = new AdmissionTrace();
        try {
            if (destroyRequested) throw new IllegalStateException("Service destruction is already pending");
            if (current != null && !current.state.releasable()) throw new IllegalStateException("Existing session retains native ownership");
            // Same installed-input checks as open, but no System.load, owner,
            // pipes, bootstrap fork, broker/socket, workspace marker or worker.
            new Deployment(context, trace);
            trace.at(AdmissionTrace.Stage.COMPLETE);
            lastPreflight = trace.result(true, null);
        } catch (Exception | LinkageError error) { lastPreflight = trace.result(false, error); }
        try {
            JSONObject result = new JSONObject().put("schema", "foldgpt.executor-preflight.v1")
                .put("nativeSpawnAttempted", false).put("admission", lastPreflight).put("service", new JSONObject(status()));
            try {
                android.content.pm.ApplicationInfo cached = context.getApplicationInfo();
                android.content.pm.PackageInfo installed = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
                android.content.pm.ApplicationInfo fresh = installed.applicationInfo;
                result.put("context", new JSONObject().put("serviceUid", Os.getuid()).put("servicePid", Os.getpid())
                    .put("clientUid", clientUid).put("installedVersion", installed.getLongVersionCode())
                    .put("contextNativeLibraryDir", AdmissionTrace.ascii(cached.nativeLibraryDir, 1024))
                    .put("contextSourceDir", AdmissionTrace.ascii(cached.sourceDir, 1024))
                    .put("packageManagerNativeLibraryDir", AdmissionTrace.ascii(fresh.nativeLibraryDir, 1024))
                    .put("packageManagerSourceDir", AdmissionTrace.ascii(fresh.sourceDir, 1024))
                    .put("nativeDirectoryMatches", java.util.Objects.equals(cached.nativeLibraryDir, fresh.nativeLibraryDir))
                    .put("sourceDirectoryMatches", java.util.Objects.equals(cached.sourceDir, fresh.sourceDir)));
            } catch (Exception | LinkageError error) { result.put("contextError", AdmissionTrace.failure(error)); }
            return result.toString();
        } catch (Exception error) { throw new IllegalStateException("Executor preflight encoding failed", error); }
    }
    @Override public synchronized void destroy() {
        int caller = Binder.getCallingUid();
        if (caller != clientUid && caller != 2000) throw new SecurityException("Unauthorized service destruction");
        destroyRequested = true;
        if (current != null && !current.state.releasable()) {
            current.requestCancel();
            // Shizuku removes its record and invokes destroy as one-way. The
            // observer must complete this request later; no second call is
            // guaranteed after the client process disappears.
            return;
        }
        android.os.Process.killProcess(android.os.Process.myPid());
    }
    private synchronized void finishDestroy() {
        if (destroyRequested && current != null && current.state.releasable()) {
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }

    private final class Session extends IExecutorSession.Stub implements IBinder.DeathRecipient {
        final SessionState state = new SessionState(Os.getuid(), clientUid);
        final IBinder owner;
        ParcelFileDescriptor input, output, control;
        boolean cancelling, directNative;
        volatile int childPid = -1;
        Session(IBinder owner) throws Exception { this.owner = owner; owner.linkToDeath(this, 0); }

        synchronized void launch(Deployment deployment, AdmissionTrace trace) throws Exception {
            directNative = deployment.directNative;
            ParcelFileDescriptor[] stdin = null, stdout = null, reports = null, controls = null;
            boolean spawned = false;
            try {
                trace.at(AdmissionTrace.Stage.PIPE_CREATE);
                stdin = ParcelFileDescriptor.createPipe();
                stdout = ParcelFileDescriptor.createPipe();
                reports = ParcelFileDescriptor.createPipe();
                controls = ParcelFileDescriptor.createPipe();
                input = stdin[1]; output = stdout[0]; control = controls[1];
                trace.at(AdmissionTrace.Stage.CONTROL_FLAGS);
                int flags = Os.fcntlInt(control.getFileDescriptor(), OsConstants.F_GETFL, 0);
                Os.fcntlInt(control.getFileDescriptor(), OsConstants.F_SETFL, flags | OsConstants.O_NONBLOCK);
                trace.at(AdmissionTrace.Stage.NATIVE_FORK);
                int pid = NativeSpawn.launch(deployment.executable, deployment.argv,
                    stdin[0].getFd(), stdout[1].getFd(), reports[1].getFd(), controls[0].getFd());
                childPid = pid;
                spawned = true;
                trace.at(AdmissionTrace.Stage.OBSERVER_START);
                ParcelFileDescriptor report = reports[0]; reports[0] = null;
                Thread observer = new Thread(() -> observe(pid, report), "foldgpt-executor-owner");
                observer.start();
                if (cancelling || !owner.isBinderAlive()) requestCancel();
            } catch (Exception error) {
                if (!spawned) {
                    state.admissionRefused();
                    owner.unlinkToDeath(this, 0);
                } else state.fail();
                throw error;
            } finally {
                // On successful handoff only service-owned duplicate ends remain.
                if (!spawned) { closeAll(stdin); closeAll(stdout); closeAll(reports); closeAll(controls); }
                else { closeOne(stdin[0]); closeOne(stdout[1]); closeOne(reports[1]); closeOne(controls[0]); }
            }
        }
        @Override public synchronized ParcelFileDescriptor takeInput() {
            state.authenticate(Binder.getCallingUid());
            if (directNative) throw new IllegalStateException("Native channels are published directly with SCM_RIGHTS");
            if (input == null || cancelling) throw new IllegalStateException("Input already transferred or cancelled");
            ParcelFileDescriptor result = input; input = null; return result;
        }
        @Override public synchronized ParcelFileDescriptor takeOutput() {
            state.authenticate(Binder.getCallingUid());
            if (directNative) throw new IllegalStateException("Native channels are published directly with SCM_RIGHTS");
            if (output == null) throw new IllegalStateException("Output already transferred");
            ParcelFileDescriptor result = output; output = null; return result;
        }
        @Override public void cancel() { state.authenticate(Binder.getCallingUid()); requestCancel(); }
        @Override public String status() {
            state.authenticate(Binder.getCallingUid());
            try { return snapshot().toString(); }
            catch (Exception error) { throw new IllegalStateException(error); }
        }
        JSONObject snapshot() throws Exception {
            return new JSONObject(state.json()).put("bootstrapPid", childPid).put("directNative", directNative);
        }
        @Override public void binderDied() { requestCancel(); }
        synchronized void requestCancel() {
            cancelling = true; state.cancel();
            // Closing a dedicated pipe cannot block behind an RPC stdin write.
            // EOF also arrives automatically if the UserService itself dies.
            closeOne(control); control = null;
            closeOne(input); input = null;
        }
        void observe(int pid, ParcelFileDescriptor report) {
            try (InputStream stream = new ParcelFileDescriptor.AutoCloseInputStream(report)) {
                ByteArrayOutputStream line = new ByteArrayOutputStream();
                int value, frames = 0;
                while ((value = stream.read()) != -1) {
                    if (value == '\n') {
                        if (++frames > 2) throw new IllegalStateException("Too many private lifecycle reports");
                        state.report(line.toString(StandardCharsets.US_ASCII)); line.reset();
                    } else {
                        if (value > 127 || line.size() >= 512) throw new IllegalStateException("Invalid private report frame");
                        line.write(value);
                    }
                }
                if (line.size() != 0) throw new IllegalStateException("Incomplete private lifecycle report");
            } catch (Exception error) { state.fail(); requestCancel(); }
            try { state.reaped(NativeSpawn.waitChild(pid)); }
            catch (Exception error) { state.fail(); }
            if (state.releasable()) {
                synchronized (this) { closeOne(control); control = null; closeOne(input); input = null; closeOne(output); output = null; }
                owner.unlinkToDeath(this, 0);
                finishDestroy();
            }
        }
    }
    private static void closeOne(ParcelFileDescriptor fd) {
        if (fd != null) try { fd.close(); } catch (Exception ignored) { /* Ownership state never relies on this close. */ }
    }
    private static void closeAll(ParcelFileDescriptor[] fds) {
        if (fds != null) for (ParcelFileDescriptor fd : fds) closeOne(fd);
    }
}
