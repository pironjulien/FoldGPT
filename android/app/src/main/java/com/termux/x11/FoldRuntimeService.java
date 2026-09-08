package com.termux.x11;

import android.app.*;
import android.content.Intent;
import android.os.*;
import android.system.Os;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.util.Log;
import app.foldgpt.FoldActivity;
import app.foldgpt.FoldExecutorRuntime;
import app.foldgpt.RuntimeShutdownGate;
import app.foldgpt.KeyringVault;
import app.foldgpt.install.GuestIdentity;
import java.io.*;
import java.util.*;

/** Owns the X server and Linux process, independently of the display Activity. */
public final class FoldRuntimeService extends Service {
    private final Object lifecycleLock = new Object();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private java.lang.Process linux;
    private PowerManager.WakeLock wakeLock;
    private Thread worker;
    private java.util.concurrent.CompletableFuture<Void> workspaceClosed = java.util.concurrent.CompletableFuture.completedFuture(null);
    private volatile boolean stopping;
    private final RuntimeShutdownGate shutdownGate = new RuntimeShutdownGate();
    private long shutdownGeneration;
    private boolean restartWorkspace;
    private boolean destroyed;
    private boolean xReady;
    private int latestStartId;
    private FoldExecutorRuntime executorRuntime;
    @Override public void onCreate() {
        super.onCreate();
        executorRuntime = new FoldExecutorRuntime(this);
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("workspace", "Espace Linux", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, FoldActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, FoldRuntimeService.class).setAction("stop"), PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "workspace").setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle("FoldGPT").setContentText("Espace Linux actif").setContentIntent(open)
            .addAction(new Notification.Action.Builder(null, "Arrêter", stop).build()).setOngoing(true).build());
        String action = intent == null ? null : intent.getAction();
        if ("stop".equals(action)) {
            requestStop();
            return START_NOT_STICKY;
        }
        boolean prepareOnly = FoldExecutorRuntime.ACTION_PREPARE.equals(action);
        if (stopping) {
            restartWorkspace |= !prepareOnly;
            applyShutdownAction(shutdownGate.requestRestart());
            return START_NOT_STICKY;
        }
        if (prepareOnly) {
            // Deliberate native preparation command. Its failure is explicit;
            // it never starts the old launcher as an implicit fallback.
            prepareNative(executorRuntime);
            return START_NOT_STICKY;
        }
        if (worker == null) launchWorkspace();
        return START_NOT_STICKY;
    }
    private void prepareNative(FoldExecutorRuntime runtime) {
        runtime.prepare().whenComplete((endpoint, error) -> mainHandler.post(() -> {
            if (destroyed || runtime != executorRuntime) return;
            if (error != null) {
                Log.e("FoldGPT", "Selected native executor is unavailable", error);
                if (worker == null && !stopping) beginShutdown();
            } else {
                Log.i("FoldGPT", "Authenticated native executor endpoint prepared; desktop launcher unchanged");
            }
        }));
    }
    private void launchWorkspace() {
        synchronized (lifecycleLock) {
            if (destroyed || worker != null) return;
            stopping = false;
            restartWorkspace = false;
            FoldExecutorRuntime runtime = executorRuntime;
            workspaceClosed = new java.util.concurrent.CompletableFuture<>();
            java.util.concurrent.CompletableFuture<Void> completion = workspaceClosed;
            worker = new Thread(() -> startWorkspace(runtime, completion), "FoldGPT-runtime");
            worker.start();
        }
    }
    private void requestStop() {
        java.lang.Process running;
        Thread startingThread;
        RuntimeShutdownGate.Action completed;
        synchronized (lifecycleLock) {
            restartWorkspace = false;
            completed = shutdownGate.cancelRestart();
            running = linux;
            startingThread = worker;
        }
        beginShutdown();
        if (running != null) running.destroy();
        if (startingThread != null) startingThread.interrupt();
        applyShutdownAction(completed);
    }
    /** Main-thread transition: retain foreground status throughout native cleanup. */
    private void beginShutdown() {
        synchronized (lifecycleLock) {
            if (destroyed || stopping) return;
            stopping = true;
            shutdownGeneration = shutdownGate.begin(worker != null);
        }
        long generation = shutdownGeneration;
        FoldExecutorRuntime runtime = executorRuntime;
        try {
            runtime.requestStop().whenComplete((ignored, error) -> mainHandler.post(() -> {
                if (destroyed || runtime != executorRuntime) return;
                if (error != null) Log.e("FoldGPT", "Native cleanup is unconfirmed; retaining runtime service", error);
                applyShutdownAction(shutdownGate.nativeCompleted(generation, error));
            }));
        } catch (RuntimeException | LinkageError error) {
            Log.e("FoldGPT", "Native stop request failed; retaining runtime service", error);
            applyShutdownAction(shutdownGate.nativeCompleted(generation, error));
        }
    }
    private void applyShutdownAction(RuntimeShutdownGate.Action action) {
        if (destroyed) return;
        if (action == RuntimeShutdownGate.Action.RESTART) {
            // requestStop permanently closes one native owner. A restart needs
            // a fresh registered owner, only after the old one is really clean.
            boolean launch = restartWorkspace;
            executorRuntime = new FoldExecutorRuntime(this);
            stopping = false;
            restartWorkspace = false;
            if (launch) launchWorkspace();
            else prepareNative(executorRuntime);
        } else if (action == RuntimeShutdownGate.Action.STOP_SERVICE) {
            stopSelfResult(latestStartId);
        }
    }
    private void startWorkspace(FoldExecutorRuntime runtime, java.util.concurrent.CompletableFuture<Void> completion) {
        java.lang.Process started = null;
        byte[] keyringPassword = null;
        try {
            File root = new File(getFilesDir(), "debian");
            GuestIdentity identity = GuestIdentity.load(root.toPath());
            requireReadableFile(root, "usr/bin/env");
            requireReadableFile(root, "usr/local/bin/foldgpt-session");
            requireReadableFile(root, "usr/local/lib/foldgpt/foldgpt_keyring.py");
            requireReadableFile(root, "usr/local/lib/foldgpt/foldgpt_ime.py");
            requireReadableFile(root, "usr/local/lib/foldgpt/keyboard-focus.js");
            requireReadableFile(root, "usr/share/X11/xkb/rules/evdev");
            FoldExecutorRuntime.Endpoint nativeEndpoint = runtime.isNativeSelected()
                    ? runtime.prepare(identity.home).get(90, java.util.concurrent.TimeUnit.SECONDS) : null;
            if (nativeEndpoint != null && nativeEndpoint.directNative()) {
                requireReadableFile(root, "usr/local/bin/foldgpt-codex-native");
                requireReadableFile(root, "usr/local/libexec/foldgpt/codex-native");
            }
            // Validate Linux and unlock its existing credential before creating native
            // X11 threads. A missing first-install component must not leave a partial
            // display server running or request a Linux password window.
            keyringPassword = KeyringVault.loadPassword(this);
            synchronized (lifecycleLock) {
                if (stopping || destroyed) throw new InterruptedException("Workspace stopped");
            }
            File temp = new File(getCacheDir(), "x11"); temp.mkdirs();
            File sharedMemory = new File(getCacheDir(), "shm");
            if (!sharedMemory.isDirectory() && !sharedMemory.mkdirs()) throw new IOException("Cannot create shared memory directory");
            Os.setenv("TMPDIR", temp.getAbsolutePath(), true);
            Os.setenv("XKB_CONFIG_ROOT", new File(root, "usr/share/X11/xkb").getAbsolutePath(), true);
            System.loadLibrary("Xlorie");
            java.util.concurrent.CompletableFuture<Void> xStarted = new java.util.concurrent.CompletableFuture<>();
            mainHandler.post(() -> {
                try {
                    if (stopping || destroyed) throw new InterruptedException("Workspace stopped");
                    if (!xReady) {
                        CmdEntryPoint.ctx = this;
                        new CmdEntryPoint(new String[]{":2", "-nolisten", "tcp"});
                        xReady = true;
                    }
                    xStarted.complete(null);
                } catch (Throwable error) { xStarted.completeExceptionally(error); }
            });
            xStarted.get(15, java.util.concurrent.TimeUnit.SECONDS);
            File aliases = new File(getFilesDir(), "native"); aliases.mkdirs();
            File alias = new File(aliases, "libtalloc.so.2");
            refreshLibraryAlias(alias, getApplicationInfo().nativeLibraryDir + "/libtalloc.so");
            List<String> args = new ArrayList<>(Arrays.asList(
                getApplicationInfo().nativeLibraryDir + "/libproot.so", "--kill-on-exit", "--link2symlink", "--sysvipc",
                "-r", root.getAbsolutePath(), "-i", identity.prootIds(), "-w",
                nativeEndpoint != null && nativeEndpoint.directNative() ? nativeEndpoint.workspace() : identity.home,
                "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", "/system", "-b", "/apex",
                "-b", temp.getAbsolutePath() + ":/tmp",
                "-b", sharedMemory.getAbsolutePath() + ":/dev/shm"));
            if (nativeEndpoint != null && nativeEndpoint.directNative()) {
                // The controller and native authority must observe identical
                // absolute paths and inodes. Bind only the declared roots.
                for (String shared : new String[] {nativeEndpoint.workspace(), nativeEndpoint.endpointRoot(),
                        nativeEndpoint.pythonRoot(), nativeEndpoint.nativeRoot()}) {
                    args.add("-b"); args.add(shared + ":" + shared);
                }
            }
            args.addAll(Arrays.asList("/usr/bin/env", "-i", "HOME=" + identity.home, "USER=" + identity.user, "LOGNAME=" + identity.user,
                "LANG=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin",
                "DISPLAY=:2", "FOLDGPT_IME_UID=" + android.os.Process.myUid(),
                "FOLDGPT_URL_UID=" + android.os.Process.myUid(),
                "FOLDGPT_SCALE=" + getResources().getDisplayMetrics().density));
            if (nativeEndpoint != null && nativeEndpoint.directNative()) {
                args.add("CODEX_CLI_PATH=/usr/local/bin/foldgpt-codex-native");
                args.add("FOLDGPT_NATIVE_BOOTSTRAP=" + nativeEndpoint.startupManifest());
                args.add("FOLDGPT_NATIVE_WORKSPACE=" + nativeEndpoint.workspace());
            }
            args.addAll(Arrays.asList("/bin/bash", "/usr/local/bin/foldgpt-session"));
            ProcessBuilder builder = new ProcessBuilder(args);
            builder.environment().put("LD_LIBRARY_PATH", aliases + ":" + getApplicationInfo().nativeLibraryDir);
            builder.environment().put("PROOT_LOADER", getApplicationInfo().nativeLibraryDir + "/libproot-loader.so");
            builder.environment().put("PROOT_LOADER_32", getApplicationInfo().nativeLibraryDir + "/libproot-loader32.so");
            builder.environment().put("PROOT_TMP_DIR", temp.getAbsolutePath());
            // Os.setenv above configures Xlorie in this process. Give the child
            // an explicit private directory too; ProcessBuilder owns its env map.
            builder.environment().put("TMPDIR", temp.getAbsolutePath());
            builder.redirectErrorStream(true).redirectOutput(new File(getFilesDir(), "runtime.log"));
            synchronized (lifecycleLock) {
                if (stopping || destroyed) throw new InterruptedException("Workspace stopped");
                started = builder.start();
                linux = started;
                wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FoldGPT:workspace");
                wakeLock.acquire();
            }
            try (OutputStream input = started.getOutputStream()) {
                input.write(keyringPassword);
            } finally {
                Arrays.fill(keyringPassword, (byte) 0);
                keyringPassword = null;
            }
            int exit = started.waitFor();
            Log.i("FoldGPT", "Linux exited with " + exit);
        } catch (InterruptedException e) {
            // Stop is expected; clear the flag while waiting for process cleanup below.
            Thread.interrupted();
        } catch (Exception | LinkageError e) {
            Log.e("FoldGPT", "Workspace failed", e);
        } finally {
            if (keyringPassword != null) Arrays.fill(keyringPassword, (byte) 0);
            stopLinux(started);
            synchronized (lifecycleLock) {
                if (linux == started) linux = null;
                if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
                wakeLock = null;
            }
            completion.complete(null);
            Thread finished = Thread.currentThread();
            mainHandler.post(() -> {
                if (worker != finished || destroyed) return;
                worker = null;
                if (stopping) applyShutdownAction(shutdownGate.workspaceExited(shutdownGeneration));
                else beginShutdown();
            });
        }
    }
    private static void requireReadableFile(File root, String relative) throws IOException {
        File component = new File(root, relative);
        if (!component.isFile() || !component.canRead()) {
            throw new IOException("Linux installation is incomplete: " + relative);
        }
    }
    private static void refreshLibraryAlias(File alias, String target) throws ErrnoException {
        try {
            if (target.equals(Os.readlink(alias.getAbsolutePath()))) return;
        } catch (ErrnoException e) {
            if (e.errno != OsConstants.ENOENT && e.errno != OsConstants.EINVAL) throw e;
        }
        // APK updates move nativeLibraryDir. readlink also sees a dangling old link.
        File replacement = new File(alias.getParentFile(), alias.getName() + ".new");
        try { Os.remove(replacement.getAbsolutePath()); }
        catch (ErrnoException e) { if (e.errno != OsConstants.ENOENT) throw e; }
        Os.symlink(target, replacement.getAbsolutePath());
        Os.rename(replacement.getAbsolutePath(), alias.getAbsolutePath());
    }
    private static void stopLinux(java.lang.Process running) {
        if (running == null || !running.isAlive()) return;
        boolean interrupted = false;
        running.destroy();
        try {
            if (!running.waitFor(2, java.util.concurrent.TimeUnit.SECONDS)) {
                running.destroyForcibly();
            }
        } catch (InterruptedException e) {
            running.destroyForcibly();
            interrupted = true;
        }
        // A deadline or interrupt is not a process-exit receipt. Keep the worker
        // and foreground service until the actual child has been waited for.
        for (;;) {
            try { running.waitFor(); break; }
            catch (InterruptedException e) { interrupted = true; running.destroyForcibly(); }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }
    @Override public void onDestroy() {
        synchronized (lifecycleLock) {
            destroyed = true;
            stopping = true;
            shutdownGate.destroy();
            if (linux != null) linux.destroy();
            if (worker != null) worker.interrupt();
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
            wakeLock = null;
        }
        super.onDestroy();
        // A system-initiated destruction can bypass our normal foreground gate.
        // Request cleanup immediately, then request process exit only after the
        // workspace worker has really waited for its child. Register the exit
        // through the native generation gate at that time, so this old Service
        // cannot kill an intervening new Service generation.
        FoldExecutorRuntime endingRuntime = executorRuntime;
        endingRuntime.requestStop();
        workspaceClosed.thenRun(() -> mainHandler.post(() -> endingRuntime.shutdownAfterCleanup(
                () -> android.os.Process.killProcess(android.os.Process.myPid()))));
    }
}
