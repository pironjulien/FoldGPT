package app.foldgpt.shizukuexec;

import android.content.Context;
import android.net.Credentials;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Binder;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.Closeable;
import java.io.File;
import java.io.FileDescriptor;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;

/** App-UID AF_UNIX endpoint for the existing GNU/native stdio RPC client.
 * Own this object and the official Shizuku binding in the application lifecycle,
 * not in a transient Activity. It never chooses or modifies a workspace.
 */
public final class AppSocketBridge implements Closeable {
    public interface Listener {
        /** No command text/content is included; invoked on a worker thread. */
        void onFailure(String message, boolean cleanupUnknown);
        /** Native cleanup was independently confirmed; another session is admissible. */
        void onSessionClosed();
    }
    private final IExecutorService service;
    private final Listener listener;
    private final int uid;
    private final File path;
    private final long device, inode;
    private final LocalServerSocket server;
    private final Object lock = new Object();
    private volatile boolean closed;
    private Run active;

    public AppSocketBridge(Context context, IExecutorService service, Listener listener) throws Exception {
        uid = android.os.Process.myUid();
        if (uid < 10000 || context.getApplicationInfo().uid != uid) {
            throw new SecurityException("Local endpoint must run in its ordinary application UID");
        }
        this.service = java.util.Objects.requireNonNull(service);
        this.listener = java.util.Objects.requireNonNull(listener);
        File directory = context.getDir("foldgpt_exec", Context.MODE_PRIVATE);
        StructStat dir = Os.lstat(directory.getPath());
        if (!directory.equals(directory.getCanonicalFile()) || !OsConstants.S_ISDIR(dir.st_mode)
                || dir.st_uid != uid || (dir.st_mode & 0077) != 0) {
            throw new SecurityException("Executor endpoint directory is not app-private");
        }
        path = new File(directory, "rpc-" + UUID.randomUUID().toString().replace("-", "") + ".sock");
        if (path.getPath().getBytes(StandardCharsets.UTF_8).length >= 108) {
            throw new IOException("Executor endpoint exceeds the native Unix path limit");
        }
        LocalServerSocket listening = null;
        FileDescriptor duplicate = null;
        StructStat identity;
        try (LocalSocket binding = new LocalSocket(LocalSocket.SOCKET_STREAM)) {
            binding.bind(new LocalSocketAddress(path.getPath(), LocalSocketAddress.Namespace.FILESYSTEM));
            identity = Os.lstat(path.getPath());
            if (!OsConstants.S_ISSOCK(identity.st_mode) || identity.st_uid != uid) {
                throw new SecurityException("New endpoint ownership differs");
            }
            Os.chmod(path.getPath(), 0600);
            duplicate = Os.dup(binding.getFileDescriptor());
            listening = new LocalServerSocket(duplicate);
            duplicate = null; // LocalServerSocket now owns this separate descriptor.
        } catch (Exception error) {
            if (duplicate != null) Os.close(duplicate);
            if (listening != null) listening.close();
            // Do not guess at deleting a path after failed identity admission.
            throw error;
        }
        device = identity.st_dev; inode = identity.st_ino; server = listening;
        new Thread(this::accept, "foldgpt-executor-accept").start();
    }
    public String socketPath() { return path.getPath(); }
    public int peerUid() { return uid; }
    /** True only when no native session remains owned by this bridge. */
    public boolean cleanupComplete() { synchronized (lock) { return active == null; } }

    private void accept() {
        while (!closed) {
            LocalSocket socket = null;
            try {
                socket = server.accept();
                Credentials peer = socket.getPeerCredentials();
                if (peer.getUid() != uid || peer.getPid() <= 0) {
                    socket.close(); continue;
                }
                synchronized (lock) {
                    if (closed || active != null) { socket.close(); continue; }
                    active = new Run(socket);
                    socket = null;
                    active.start();
                }
            } catch (Exception error) {
                if (socket != null) try { socket.close(); } catch (IOException ignored) {}
                if (!closed) {
                    close();
                    listener.onFailure("Executor endpoint admission failed; listener stopped", !cleanupComplete());
                }
                return;
            }
        }
    }

    private final class Run {
        final LocalSocket socket;
        final Binder owner = new Binder();
        IExecutorSession session;
        InputStream rpcOutput;
        OutputStream rpcInput;
        final CountDownLatch outputFinished = new CountDownLatch(1);
        boolean outputStarted;
        volatile boolean stopping;

        Run(LocalSocket socket) { this.socket = socket; }
        void start() {
            try {
                session = service.open(owner);
                rpcInput = new ParcelFileDescriptor.AutoCloseOutputStream(session.takeInput());
                rpcOutput = new ParcelFileDescriptor.AutoCloseInputStream(session.takeOutput());
                new Thread(this::input, "foldgpt-executor-input").start();
                new Thread(this::output, "foldgpt-executor-output").start(); outputStarted = true;
                new Thread(this::observe, "foldgpt-executor-cleanup").start();
            } catch (Exception error) {
                stop();
                if (!outputStarted) outputFinished.countDown();
                if (session == null) {
                    // Failed admission cannot establish that the remote service
                    // never forked: retain the endpoint reservation and inspect
                    // the service's own state, instead of immediately retrying.
                    new Thread(this::observe, "foldgpt-executor-admission").start();
                } else new Thread(this::observe, "foldgpt-executor-cleanup").start();
                listener.onFailure("Executor Binder session admission failed", true);
            }
        }
        void input() {
            try {
                copy(socket.getInputStream(), rpcInput);
                // Actual client EOF closes the sole service pipe writer after
                // all preceding request bytes were forwarded. Output stays open.
                rpcInput.close();
            } catch (IOException error) { stop(); }
        }
        void output() {
            try { copy(rpcOutput, socket.getOutputStream()); }
            catch (IOException error) { stop(); }
            finally {
                try { socket.shutdownOutput(); } catch (IOException ignored) {}
                try { socket.shutdownInput(); } catch (IOException ignored) {}
                closeQuietly(rpcOutput);
                outputFinished.countDown();
            }
        }
        void observe() {
            try {
                for (;;) {
                    String encoded = session != null ? session.status() : service.status();
                    JSONObject status = new JSONObject(encoded);
                    if (status.optBoolean("cleanupComplete", false) || "idle".equals(status.optString("state"))) {
                        // waitpid/cleanup may precede draining the last bytes
                        // already in stdout's kernel pipe. Never truncate them
                        // merely because the backend has exited successfully.
                        outputFinished.await();
                        closeQuietly(socket);
                        closeQuietly(rpcInput); closeQuietly(rpcOutput);
                        synchronized (lock) { if (active == this) active = null; }
                        listener.onSessionClosed();
                        return;
                    }
                    if (status.optBoolean("transportFailed", false) || status.optBoolean("quarantined", false)
                            || status.optBoolean("bootstrapReaped", false)) {
                        listener.onFailure("Native cleanup is unresolved; bridge ownership retained", true);
                        return;
                    }
                    Thread.sleep(250);
                }
            } catch (Exception error) {
                stop();
                listener.onFailure("Executor owner unavailable; no automatic reconnect", true);
            }
        }
        void stop() {
            if (stopping) return;
            stopping = true;
            // Independent Binder cancellation never waits for a blocked stream
            // copy. Native ownership remains with the service/real backend.
            if (session != null) try { session.cancel(); } catch (Exception ignored) {}
            try { socket.shutdownInput(); } catch (IOException ignored) {}
            try { socket.shutdownOutput(); } catch (IOException ignored) {}
            closeQuietly(socket);
            // Avoid synchronously closing rpcInput behind a blocking write.
            // Cancellation wakes backend cleanup through its separate pipe.
        }
    }
    static void copy(InputStream input, OutputStream output) throws IOException {
        byte[] buffer = new byte[65536];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (count != 0) output.write(buffer, 0, count);
        }
    }
    @Override public void close() {
        closed = true;
        try { server.close(); } catch (IOException ignored) {}
        synchronized (lock) { if (active != null) active.stop(); }
        try {
            StructStat present = Os.lstat(path.getPath());
            if (present.st_dev == device && present.st_ino == inode && OsConstants.S_ISSOCK(present.st_mode)
                    && present.st_uid == uid && !path.delete()) {
                listener.onFailure("Owned executor socket could not be removed", false);
            }
        } catch (Exception ignored) { /* Never unlink an unverified replacement. */ }
    }
    private static void closeQuietly(Closeable value) {
        if (value != null) try { value.close(); } catch (IOException ignored) {}
    }
}
