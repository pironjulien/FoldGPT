package app.foldgpt;

import android.content.Intent;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.Bundle;
import android.util.Log;
import com.termux.x11.FoldRuntimeService;
import com.termux.x11.MainActivity;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Display host with a peer-credential checked IME endpoint. No text crosses this bridge. */
public final class FoldActivity extends MainActivity {
    private volatile boolean resumed;
    private final Object imeLock = new Object();
    private volatile boolean endpointRunning;
    private LocalServerSocket imeServer;
    private LocalSocket imeClient;
    private Thread imeThread;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // The desktop client enforces a minimum window height. Keep its canvas
        // and let LorieView follow the input cursor above the Android keyboard.
        prefs.Reseed.put(false);
        if (!getPreferences(MODE_PRIVATE).getBoolean("configured", false)) {
            prefs.fullscreen.put(true);
            prefs.showAdditionalKbd.put(false);
            prefs.touchMode.put("3");
            getPreferences(MODE_PRIVATE).edit().putBoolean("configured", true).apply();
        }
        endpointRunning = true;
        imeThread = new Thread(this::serveIme, "FoldGPT-IME");
        imeThread.start();
    }
    @Override public void onResume() {
        super.onResume();
        resumed = true;
        startForegroundService(new Intent(this, FoldRuntimeService.class));
    }
    @Override public void onPause() { resumed = false; super.onPause(); }
    @Override protected void onDestroy() {
        resumed = false;
        synchronized (imeLock) {
            endpointRunning = false;
            // Closing both sockets wakes accept/read immediately, including during rotation.
            try { if (imeClient != null) imeClient.close(); } catch (IOException ignored) { }
            try { if (imeServer != null) imeServer.close(); } catch (IOException ignored) { }
        }
        if (imeThread != null) imeThread.interrupt();
        super.onDestroy();
    }
    private void serveIme() {
        LocalServerSocket server = null;
        try {
            synchronized (imeLock) {
                if (!endpointRunning) return;
                server = new LocalServerSocket("foldgpt-ime-" + android.os.Process.myUid());
                imeServer = server;
            }
            while (endpointRunning && !Thread.currentThread().isInterrupted()) {
                // An accept failure ends the endpoint; retrying a closed socket would spin.
                LocalSocket acceptedClient = server.accept();
                synchronized (imeLock) {
                    if (!endpointRunning) { acceptedClient.close(); break; }
                    imeClient = acceptedClient;
                }
                try (LocalSocket client = acceptedClient) {
                    // Only processes in FoldGPT's own Android sandbox can request the keyboard.
                    if (client.getPeerCredentials().getUid() != android.os.Process.myUid()) continue;
                    client.setSoTimeout(2000);
                    ByteArrayOutputStream line = new ByteArrayOutputStream();
                    int value;
                    while (line.size() <= 256 && (value = client.getInputStream().read()) >= 0 && value != '\n') line.write(value);
                    if (line.size() > 256) continue;
                    JSONObject request = new JSONObject(line.toString(StandardCharsets.UTF_8.name()));
                    boolean show = request.getBoolean("visible");
                    CompletableFuture<Boolean> applied = new CompletableFuture<>();
                    runOnUiThread(() -> {
                        if (applied.isDone()) return;
                        boolean allowed = endpointRunning && !isDestroyed() && (!show || (resumed && hasWindowFocus()));
                        if (allowed) getLorieView().setKeyboardVisible(show);
                        Log.i("FoldGPT-IME", "requested=" + show + " applied=" + allowed);
                        applied.complete(allowed);
                    });
                    boolean accepted;
                    try { accepted = applied.get(2, TimeUnit.SECONDS); }
                    finally { applied.cancel(false); }
                    client.getOutputStream().write(("{\"accepted\":" + accepted + "}\n").getBytes(StandardCharsets.UTF_8));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    break;
                } catch (Exception e) {
                    if (endpointRunning) Log.w("FoldGPT-IME", "Request failed", e);
                } finally {
                    synchronized (imeLock) { if (imeClient == acceptedClient) imeClient = null; }
                }
            }
        } catch (IOException e) {
            if (endpointRunning) Log.e("FoldGPT-IME", "Endpoint failed", e);
        } finally {
            synchronized (imeLock) { if (imeServer == server) imeServer = null; }
            try { if (server != null) server.close(); } catch (IOException ignored) { }
        }
    }
}
