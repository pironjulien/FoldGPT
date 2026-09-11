package app.foldgpt;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;
import android.view.View;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

/** Same-Android-UID external URL transport, never a guest-process sandbox. */
final class FoldUrlBridge {
    private static final FoldUrlBridge INSTANCE = new FoldUrlBridge();
    private final Object lock = new Object();
    private final Set<Activity> owners = Collections.newSetFromMap(new IdentityHashMap<>());
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor(r -> new Thread(r, "FoldGPT-URL-lifecycle"));
    private Activity active;
    private LocalServerSocket server;
    private LocalSocket client;
    private Thread reader;

    static FoldUrlBridge get() { return INSTANCE; }
    void attach(Activity activity) {
        synchronized (lock) { owners.add(activity); }
        lifecycle.execute(this::reconcile);
    }
    void resume(Activity activity) {
        synchronized (lock) { if (owners.contains(activity)) active = activity; }
        lifecycle.execute(this::reconcile);
    }
    void pause(Activity activity) {
        synchronized (lock) { if (active == activity) active = null; }
    }
    void detach(Activity activity) {
        synchronized (lock) { owners.remove(activity); if (active == activity) active = null; }
        lifecycle.execute(this::reconcile);
    }

    private void reconcile() {
        synchronized (lock) {
            if (!owners.isEmpty()) {
                if (server != null) return;
                LocalServerSocket created = null;
                try {
                    created = new LocalServerSocket("foldgpt-url-" + android.os.Process.myUid());
                    Os.fcntlInt(created.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
                    server = created;
                    LocalServerSocket endpoint = created;
                    reader = new Thread(() -> serve(endpoint), "FoldGPT-URL");
                    reader.start();
                    Log.i("FoldGPT-URL", "Endpoint listening");
                } catch (Exception error) {
                    server = null;
                    if (created != null) try { created.close(); } catch (IOException ignored) { }
                    Log.e("FoldGPT-URL", "Endpoint start failed");
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
            stopped = server; accepted = client; worker = reader;
            server = null; client = null; reader = null;
        }
        if (stopped == null) return;
        try { Os.shutdown(stopped.getFileDescriptor(), OsConstants.SHUT_RDWR); } catch (Exception ignored) { }
        try { stopped.close(); } catch (IOException ignored) { }
        if (accepted != null) {
            try { accepted.shutdownInput(); } catch (IOException ignored) { }
            try { accepted.close(); } catch (IOException ignored) { }
        }
        if (worker != null) {
            worker.interrupt();
            try { worker.join(2500); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            if (worker.isAlive()) Log.e("FoldGPT-URL", "Endpoint reader did not terminate after shutdown");
        }
        Log.i("FoldGPT-URL", "Endpoint closed");
    }

    private boolean isCurrent(LocalServerSocket endpoint) {
        synchronized (lock) { return server == endpoint; }
    }

    private static byte[] readRequest(LocalSocket request) throws IOException {
        long deadline = SystemClock.elapsedRealtime() + 2000;
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        while (input.size() <= FoldWebUri.MAX_REQUEST_BYTES) {
            long remaining = deadline - SystemClock.elapsedRealtime();
            if (remaining <= 0) throw new SocketTimeoutException("Request deadline");
            request.setSoTimeout((int) remaining);
            int value = request.getInputStream().read();
            if (value < 0) throw new IOException("Incomplete request");
            if (value == '\n') return input.toByteArray();
            input.write(value);
        }
        throw new IOException("Oversized request");
    }

    private static boolean visibleUnlocked(Activity target) {
        if (target == null || target.isFinishing() || target.isDestroyed() || !target.hasWindowFocus()) return false;
        View content = target.findViewById(android.R.id.content);
        PowerManager power = target.getSystemService(PowerManager.class);
        KeyguardManager keyguard = target.getSystemService(KeyguardManager.class);
        return content != null && content.isShown() && content.getWindowVisibility() == View.VISIBLE
                && power != null && power.isInteractive() && keyguard != null
                && !keyguard.isKeyguardLocked() && !keyguard.isDeviceLocked();
    }

    private String launch(LocalServerSocket endpoint, String url) throws Exception {
        CompletableFuture<String> applied = new CompletableFuture<>();
        AtomicInteger state = new AtomicInteger(0); // 0 waiting, 1 launch committed, 2 cancelled.
        long deadline = SystemClock.elapsedRealtime() + 2000;
        Runnable action = () -> {
            if (applied.isDone()) return;
            try {
                Activity target;
                synchronized (lock) { target = server == endpoint ? active : null; }
                if (!visibleUnlocked(target)) { applied.complete("not_visible"); return; }
                Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
                if (SystemClock.elapsedRealtime() >= deadline || !state.compareAndSet(0, 1)) return;
                // Lifecycle callbacks share this main thread. A queued request
                // cannot launch after pause/detach or deadline cancellation.
                target.startActivity(intent);
                applied.complete("accepted");
            } catch (ActivityNotFoundException error) { applied.complete("no_handler"); }
            catch (RuntimeException error) { applied.complete("launch_failed"); }
        };
        try {
            if (!main.post(action)) return "unavailable";
            return applied.get(2, TimeUnit.SECONDS);
        } catch (TimeoutException error) { return "timeout"; }
        finally {
            state.compareAndSet(0, 2);
            applied.cancel(false);
            main.removeCallbacks(action);
        }
    }

    private static void respond(LocalSocket request, String result) throws IOException {
        request.setSoTimeout(2000);
        String response = result.equals("accepted") ? "{\"accepted\":true}\n"
                : "{\"accepted\":false,\"error\":\"" + result + "\"}\n";
        request.getOutputStream().write(response.getBytes(StandardCharsets.US_ASCII));
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
                    Os.fcntlInt(request.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
                    if (request.getPeerCredentials().getUid() != android.os.Process.myUid()) {
                        respond(request, "unauthorized");
                        continue;
                    }
                    String result;
                    try { result = launch(endpoint, FoldWebUri.parseRequest(readRequest(request))); }
                    catch (IllegalArgumentException error) { result = "invalid_url"; }
                    catch (SocketTimeoutException error) { result = "timeout"; }
                    catch (IOException error) { result = "invalid_request"; }
                    respond(request, result);
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    break;
                } catch (Exception error) {
                    if (isCurrent(endpoint)) Log.w("FoldGPT-URL", "Request failed; no request content logged");
                } finally {
                    synchronized (lock) { if (client == accepted) client = null; }
                }
            }
        } catch (IOException error) {
            if (isCurrent(endpoint)) Log.e("FoldGPT-URL", "Endpoint read failed");
        } finally {
            lifecycle.execute(() -> { if (isCurrent(endpoint)) stopEndpoint(); });
        }
    }
}
