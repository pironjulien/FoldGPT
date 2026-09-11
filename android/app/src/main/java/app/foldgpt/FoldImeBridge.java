package app.foldgpt;

import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.Handler;
import android.os.Looper;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** One endpoint per display process, independent of Activity recreation. */
final class FoldImeBridge {
    private static final FoldImeBridge INSTANCE = new FoldImeBridge();
    private final Object lock = new Object();
    private final Set<FoldActivity> owners = Collections.newSetFromMap(new IdentityHashMap<>());
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor(r -> new Thread(r, "FoldGPT-IME-lifecycle"));
    private FoldActivity active;
    private LocalServerSocket server;
    private LocalSocket client;
    private Thread reader;

    static FoldImeBridge get() { return INSTANCE; }

    void attach(FoldActivity activity) {
        synchronized (lock) { owners.add(activity); }
        lifecycle.execute(this::reconcile);
    }

    void resume(FoldActivity activity) {
        synchronized (lock) { if (owners.contains(activity)) active = activity; }
        lifecycle.execute(this::reconcile);
    }

    void pause(FoldActivity activity) {
        synchronized (lock) { if (active == activity) active = null; }
    }

    void detach(FoldActivity activity) {
        synchronized (lock) {
            owners.remove(activity);
            if (active == activity) active = null;
        }
        lifecycle.execute(this::reconcile);
    }

    private void reconcile() {
        synchronized (lock) {
            if (owners.isEmpty()) {
                // Teardown is serialized with the next bind, outside the UI thread.
            } else if (server != null) {
                return;
            } else {
                LocalServerSocket created = null;
                try {
                    created = new LocalServerSocket("foldgpt-ime-" + android.os.Process.myUid());
                    Os.fcntlInt(created.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
                    server = created;
                    LocalServerSocket listening = created;
                    reader = new Thread(() -> serve(listening), "FoldGPT-IME");
                    reader.start();
                    Log.i("FoldGPT-IME", "Endpoint listening");
                } catch (Exception error) {
                    if (created != null) {
                        server = null;
                        try { created.close(); } catch (IOException ignored) { }
                    }
                    Log.e("FoldGPT-IME", "Endpoint start failed", error);
                }
                return;
            }
        }
        stopEndpoint();
    }

    private void stopEndpoint() {
        LocalServerSocket stopped;
        LocalSocket accepted;
        Thread worker;
        synchronized (lock) {
            stopped = server;
            accepted = client;
            worker = reader;
            server = null;
            client = null;
            reader = null;
        }
        if (stopped == null) return;
        // close alone does not reliably interrupt an in-flight Linux accept().
        // shutdown first wakes the reader and releases the abstract name on close.
        try { Os.shutdown(stopped.getFileDescriptor(), OsConstants.SHUT_RDWR); }
        catch (Exception error) { Log.w("FoldGPT-IME", "Listener shutdown failed", error); }
        try { stopped.close(); } catch (IOException error) { Log.w("FoldGPT-IME", "Listener close failed", error); }
        if (accepted != null) {
            try { accepted.shutdownInput(); } catch (IOException ignored) { }
            try { accepted.close(); } catch (IOException ignored) { }
        }
        if (worker != null) {
            worker.interrupt();
            try { worker.join(2500); }
            catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            if (worker.isAlive()) Log.e("FoldGPT-IME", "Endpoint reader did not terminate after shutdown");
        }
        Log.i("FoldGPT-IME", "Endpoint closed");
    }

    private boolean isCurrent(LocalServerSocket endpoint) {
        synchronized (lock) { return server == endpoint; }
    }

    private void serve(LocalServerSocket endpoint) {
        try {
            while (isCurrent(endpoint) && !Thread.currentThread().isInterrupted()) {
                LocalSocket accepted = endpoint.accept();
                synchronized (lock) {
                    if (server != endpoint) { accepted.close(); break; }
                    client = accepted;
                }
                try (LocalSocket request = accepted) {
                    if (request.getPeerCredentials().getUid() != android.os.Process.myUid()) continue;
                    request.setSoTimeout(2000);
                    ByteArrayOutputStream input = new ByteArrayOutputStream();
                    int value;
                    while (input.size() <= 256 && (value = request.getInputStream().read()) >= 0 && value != '\n') input.write(value);
                    if (input.size() > 256) continue;
                    JSONObject payload = new JSONObject(input.toString(StandardCharsets.UTF_8.name()));
                    if (payload.length() != 1 || !(payload.opt("visible") instanceof Boolean)) continue;
                    boolean show = payload.getBoolean("visible");
                    CompletableFuture<Boolean> applied = new CompletableFuture<>();
                    main.post(() -> {
                        if (applied.isDone()) return;
                        FoldActivity target;
                        synchronized (lock) { target = server == endpoint ? active : null; }
                        boolean allowed = target != null && target.applyImeVisibility(show);
                        Log.i("FoldGPT-IME", "requested=" + show + " applied=" + allowed);
                        applied.complete(allowed);
                    });
                    boolean allowed;
                    try { allowed = applied.get(2, TimeUnit.SECONDS); }
                    finally { applied.cancel(false); }
                    request.getOutputStream().write(("{\"accepted\":" + allowed + "}\n").getBytes(StandardCharsets.UTF_8));
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    break;
                } catch (Exception error) {
                    if (isCurrent(endpoint)) Log.w("FoldGPT-IME", "Request failed; no request content logged");
                } finally {
                    synchronized (lock) { if (client == accepted) client = null; }
                }
            }
        } catch (IOException error) {
            if (isCurrent(endpoint)) Log.e("FoldGPT-IME", "Endpoint read failed", error);
        } finally {
            lifecycle.execute(() -> { if (isCurrent(endpoint)) stopEndpoint(); });
        }
    }
}
