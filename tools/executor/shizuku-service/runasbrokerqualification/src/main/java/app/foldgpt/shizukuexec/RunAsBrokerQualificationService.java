package app.foldgpt.shizukuexec;

import android.content.Context;
import android.os.Binder;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.FutureTask;

/** Fixed broker experiment, authenticated to its own diagnostic APK. */
public final class RunAsBrokerQualificationService extends IRunAsBrokerQualification.Stub implements IBinder.DeathRecipient {
    private final Context context;
    private final int clientUid;
    private volatile JSONObject report;
    private IBinder owner;
    private boolean started, cancelling, destroyRequested;
    private volatile boolean reaped, releasable;
    private ParcelFileDescriptor input, control;

    public RunAsBrokerQualificationService(Context context) {
        this.context = context;
        clientUid = context.getApplicationInfo().uid;
        if (Os.getuid() != 2000 || Os.geteuid() != 2000 || clientUid < 10000) {
            throw new SecurityException("Only the nonroot shell UserService is admitted");
        }
        report = json("state", "idle");
    }
    private void authenticate() {
        if (Binder.getCallingUid() != clientUid) throw new SecurityException("Foreign qualification caller");
    }
    private static JSONObject json(String name, Object value) {
        try { return new JSONObject().put(name, value); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }
    @Override public synchronized String preflight() {
        authenticate();
        if (started || destroyRequested) throw new IllegalStateException("Existing one-shot ownership");
        try {
            return RunAsBrokerInstallation.capture(context).toString();
        } catch (Exception error) { throw new IllegalStateException("Installation admission refused", error); }
    }
    @Override public synchronized void start(IBinder requestedOwner, String expectedInstallation) {
        authenticate();
        if (started || destroyRequested || requestedOwner == null || !requestedOwner.isBinderAlive()) {
            throw new IllegalStateException("A new live owner and unused service are required");
        }
        if (expectedInstallation == null || expectedInstallation.length() > 32768) throw new SecurityException("Installation record bound");
        try {
            JSONObject expected = new JSONObject(expectedInstallation);
            RunAsBrokerInstallation.requireSame(expected, RunAsBrokerInstallation.capture(context));
            owner = requestedOwner;
            owner.linkToDeath(this, 0);
            started = true;
            report = json("state", "starting");
            new Thread(() -> run(expected), "foldgpt-runas-broker-owner").start();
        } catch (Exception error) { throw new IllegalStateException("Fixed launch admission refused", error); }
    }
    @Override public String status() { authenticate(); return report.toString(); }
    @Override public synchronized void cancel() { authenticate(); requestCancel(); }
    @Override public synchronized void binderDied() { requestCancel(); }
    private synchronized void requestCancel() {
        cancelling = true;
        close(input); input = null;
        close(control); control = null;
    }
    @Override public synchronized void destroy() {
        int caller = Binder.getCallingUid();
        if (caller != clientUid && caller != 2000) throw new SecurityException("Foreign destroy caller");
        destroyRequested = true;
        requestCancel();
        if (!started || releasable) android.os.Process.killProcess(android.os.Process.myPid());
    }
    private void run(JSONObject installation) {
        JSONObject result = new JSONObject();
        ParcelFileDescriptor[] in = null, out = null, err = null, ctl = null;
        int pid = -1;
        FutureTask<byte[]> stdout = null, stderr = null;
        boolean readsComplete = false, nativeCleanup = false;
        String nonce = UUID.randomUUID().toString().replace("-", "");
        try {
            JSONObject target = installation.getJSONObject("target");
            String directory = installation.getJSONObject("qualification").getString("nativeLibraryDir");
            result.put("schema", "foldgpt.runas.broker-service.v1").put("installation", installation)
                .put("serviceUid", Os.getuid()).put("servicePid", Os.getpid()).put("clientUid", clientUid)
                .put("nonce", nonce).put("state", "running").put("nativeSpawnAttempted", false);
            NativeSpawn.load(directory + "/libfoldgpt_shizuku_transport.so");
            in = ParcelFileDescriptor.createPipe(); out = ParcelFileDescriptor.createPipe();
            err = ParcelFileDescriptor.createPipe(); ctl = ParcelFileDescriptor.createPipe();
            stdout = reader(out[0]); stderr = reader(err[0]);
            synchronized (this) {
                if (cancelling) throw new IllegalStateException("Owner cancelled before launch");
                input = in[1]; control = ctl[1];
                String executable = directory + "/libfoldgpt_runas_broker_bootstrap.so";
                String[] argv = {"/system/bin/run-as", RunAsBrokerInstallation.TARGET, executable, "--broker-v1",
                    Integer.toString(target.getInt("uid")), target.getString("dataDir"), Integer.toString(Os.getpid()), nonce,
                    installation.getJSONObject("qualification").getString("sourceDir")};
                result.put("argv", new org.json.JSONArray(argv)).put("nativeSpawnAttempted", true);
                pid = NativeSpawn.launch("/system/bin/run-as", argv, in[0].getFd(), out[1].getFd(), err[1].getFd(), ctl[0].getFd());
                result.put("ownerPid", pid);
            }
            close(in[0]); close(out[1]); close(err[1]); close(ctl[0]);
            report = new JSONObject(result.toString());
            synchronized (this) {
                if (cancelling) throw new IllegalStateException("Owner cancelled after launch");
                writeAndClose(input, "foldgpt.runas.broker.v1:stdin:" + nonce + "\n"); input = null;
                // FD3 remains alive until completion or explicit cancellation.
            }
            int waitStatus = NativeSpawn.waitChild(pid);
            reaped = true;
            result.put("waitStatus", waitStatus).put("childReaped", true);
            String output = new String(stdout.get(), StandardCharsets.US_ASCII);
            String diagnostic = new String(stderr.get(), StandardCharsets.US_ASCII);
            readsComplete = true;
            result.put("stdout", output).put("stderr", diagnostic).put("pipeReadersComplete", true);
            JSONObject finalReceipt = new JSONObject(diagnostic);
            nativeCleanup = finalReceipt.optInt("pid") == pid && nonce.equals(finalReceipt.optString("nonce"))
                && (("foldgpt.runas.broker-report.v1".equals(finalReceipt.optString("schema"))
                    && finalReceipt.optBoolean("cleanupComplete"))
                    || ("foldgpt.runas.broker-admission.v1".equals(finalReceipt.optString("schema"))
                        && Boolean.FALSE.equals(finalReceipt.opt("nativeWorkerStarted"))));
            result.put("nativeCleanupVerified", nativeCleanup);
            JSONObject child = new JSONObject(output), receipt = new JSONObject(diagnostic);
            result.put("child", child).put("receipt", receipt);
            RunAsBrokerInstallation.requireSame(installation, RunAsBrokerInstallation.capture(context));
            result.put("installationUnchanged", true);
            boolean passed = waitStatus == 0 && child.getBoolean("passed") && receipt.getBoolean("passed")
                && "foldgpt.runas.broker-child.v1".equals(child.getString("schema"))
                && "foldgpt.runas.broker-report.v1".equals(receipt.getString("schema"))
                && nonce.equals(child.getString("nonce")) && nonce.equals(receipt.getString("nonce"))
                && child.getInt("pid") == pid && receipt.getInt("pid") == pid
                && receipt.getInt("reportFd") == 2 && receipt.getBoolean("stdoutFlushed")
                && receipt.getBoolean("cleanupComplete") && child.getBoolean("cleanupComplete");
            result.put("passed", passed);
        } catch (Exception | LinkageError error) {
            try { result.put("passed", false).put("error", error.getClass().getSimpleName() + ": " + error.getMessage()); }
            catch (Exception ignored) { }
        } finally {
            requestCancel();
            // Close inherited source/write ends before waiting, retaining the
            // readers so a genuine run-as error is never replaced by our close.
            if (in != null) close(in[0]);
            if (out != null) close(out[1]);
            if (err != null) close(err[1]);
            if (ctl != null) close(ctl[0]);
            if (pid > 0 && !reaped) {
                try { result.put("waitStatus", NativeSpawn.waitChild(pid)); reaped = true; }
                catch (Exception error) { try { result.put("reapError", error.toString()); } catch (Exception ignored) { } }
            }
            // Preserve both streams even if a launch/transition fails; native
            // ownership is not inferred from a callback or an elapsed deadline.
            if (!readsComplete && stdout != null && stderr != null) {
                try {
                    result.put("stdout", new String(stdout.get(), StandardCharsets.US_ASCII));
                    result.put("stderr", new String(stderr.get(), StandardCharsets.US_ASCII));
                    readsComplete = true;
                } catch (Exception error) { try { result.put("readerError", error.toString()); } catch (Exception ignored) { } }
            }
            boolean pipesClosed = closeAll(in) & closeAll(out) & closeAll(err) & closeAll(ctl);
            try {
                boolean clean = (pid < 0 || (reaped && nativeCleanup)) && pipesClosed
                    && ((stdout == null && stderr == null) || readsComplete);
                releasable = clean;
                result.put("state", "complete").put("childReaped", reaped).put("pipeReadersComplete", readsComplete)
                    .put("pipesClosed", pipesClosed).put("cleanupComplete", clean).put("quarantined", !clean);
            } catch (Exception ignored) { }
            report = result;
            synchronized (this) {
                if (owner != null) owner.unlinkToDeath(this, 0);
                if (destroyRequested && releasable) android.os.Process.killProcess(android.os.Process.myPid());
            }
        }
    }
    private static FutureTask<byte[]> reader(ParcelFileDescriptor fd) {
        FutureTask<byte[]> task = new FutureTask<>(() -> {
            try (InputStream stream = new ParcelFileDescriptor.AutoCloseInputStream(fd)) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[1024]; int count;
                while ((count = stream.read(buffer)) != -1) {
                    if (bytes.size() + count > 32768) throw new IllegalStateException("Fixed report exceeds 32 KiB");
                    bytes.write(buffer, 0, count);
                }
                return bytes.toByteArray();
            }
        });
        new Thread(task, "foldgpt-runas-pipe-reader").start();
        return task;
    }
    private static void writeAndClose(ParcelFileDescriptor fd, String value) throws Exception {
        if (fd == null) throw new IllegalStateException("Challenge pipe cancelled");
        try (OutputStream stream = new ParcelFileDescriptor.AutoCloseOutputStream(fd)) {
            stream.write(value.getBytes(StandardCharsets.US_ASCII));
        }
    }
    private static boolean close(ParcelFileDescriptor fd) {
        if (fd != null) try { fd.close(); } catch (Exception error) { return false; }
        return true;
    }
    private static boolean closeAll(ParcelFileDescriptor[] fds) {
        boolean closed = true;
        if (fds != null) for (ParcelFileDescriptor fd : fds) closed &= close(fd);
        return closed;
    }
}
