package app.foldgpt.shizukuexec;

import android.content.Context;
import android.os.Binder;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.system.OsConstants;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Authenticated owner of a fixed packaged backend; no privileged command API. */
public final class ExecutorService extends IExecutorService.Stub {
    private final int clientUid;
    private final Context context;
    private Session current;

    public ExecutorService(Context context) {
        this.context = context;
        clientUid = context.getApplicationInfo().uid;
        new SessionState(Os.getuid(), clientUid);
    }
    private void authenticate() {
        if (Binder.getCallingUid() != clientUid) throw new SecurityException("Unauthorized executor caller");
    }
    @Override public synchronized IExecutorSession open(IBinder owner) {
        authenticate();
        if (owner == null || !owner.isBinderAlive()) throw new IllegalArgumentException("A live client owner is required");
        if (current != null && !current.state.releasable()) {
            throw new IllegalStateException("Existing session retains native ownership");
        }
        try {
            Deployment deployment = new Deployment(context);
            Session session = new Session(owner);
            // Publish owner before native fork so destroy/death cannot race an
            // unregistered native child. Failed launch remains explicit.
            current = session;
            session.launch(deployment);
            return session;
        } catch (Exception error) { throw new IllegalStateException("Executor admission failed", error); }
    }
    @Override public synchronized String status() {
        authenticate();
        return current == null ? "{\"state\":\"idle\"}" : current.state.json();
    }
    @Override public synchronized void destroy() {
        int caller = Binder.getCallingUid();
        if (caller != clientUid && caller != 2000) throw new SecurityException("Unauthorized service destruction");
        if (current != null && !current.state.releasable()) {
            current.requestCancel();
            throw new IllegalStateException("Cleanup is pending; retaining the UserService");
        }
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    private final class Session extends IExecutorSession.Stub implements IBinder.DeathRecipient {
        final SessionState state = new SessionState(Os.getuid(), clientUid);
        final IBinder owner;
        ParcelFileDescriptor input, output, control;
        boolean cancelling;
        Session(IBinder owner) throws Exception { this.owner = owner; owner.linkToDeath(this, 0); }

        synchronized void launch(Deployment deployment) throws Exception {
            ParcelFileDescriptor[] stdin = null, stdout = null, reports = null, controls = null;
            boolean spawned = false;
            try {
                stdin = ParcelFileDescriptor.createPipe();
                stdout = ParcelFileDescriptor.createPipe();
                reports = ParcelFileDescriptor.createPipe();
                controls = ParcelFileDescriptor.createPipe();
                input = stdin[1]; output = stdout[0]; control = controls[1];
                int flags = Os.fcntlInt(control.getFileDescriptor(), OsConstants.F_GETFL, 0);
                Os.fcntlInt(control.getFileDescriptor(), OsConstants.F_SETFL, flags | OsConstants.O_NONBLOCK);
                int pid = NativeSpawn.launch(deployment.executable, deployment.argv,
                    stdin[0].getFd(), stdout[1].getFd(), reports[1].getFd(), controls[0].getFd());
                spawned = true;
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
            if (input == null || cancelling) throw new IllegalStateException("Input already transferred or cancelled");
            ParcelFileDescriptor result = input; input = null; return result;
        }
        @Override public synchronized ParcelFileDescriptor takeOutput() {
            state.authenticate(Binder.getCallingUid());
            if (output == null) throw new IllegalStateException("Output already transferred");
            ParcelFileDescriptor result = output; output = null; return result;
        }
        @Override public void cancel() { state.authenticate(Binder.getCallingUid()); requestCancel(); }
        @Override public String status() { state.authenticate(Binder.getCallingUid()); return state.json(); }
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
                synchronized (this) { closeOne(control); control = null; closeOne(input); input = null; }
                owner.unlinkToDeath(this, 0);
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
