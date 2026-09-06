package com.termux.x11;

import android.app.*;
import android.content.Intent;
import android.os.*;
import android.system.Os;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.util.Log;
import app.foldgpt.FoldActivity;
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
    private volatile boolean stopping;
    private boolean restartRequested;
    private boolean destroyed;
    private boolean xReady;
    private int latestStartId;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if ("stop".equals(intent == null ? null : intent.getAction())) {
            requestStop();
            return START_NOT_STICKY;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("workspace", "Espace Linux", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, FoldActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, FoldRuntimeService.class).setAction("stop"), PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "workspace").setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle("FoldGPT").setContentText("Espace Linux actif").setContentIntent(open)
            .addAction(new Notification.Action.Builder(null, "Arrêter", stop).build()).setOngoing(true).build());
        if (stopping) restartRequested = true;
        else if (worker == null) launchWorkspace();
        return START_NOT_STICKY;
    }
    private void launchWorkspace() {
        synchronized (lifecycleLock) {
            if (destroyed || worker != null) return;
            stopping = false;
            restartRequested = false;
            worker = new Thread(this::startWorkspace, "FoldGPT-runtime");
            worker.start();
        }
    }
    private void requestStop() {
        java.lang.Process running;
        Thread startingThread;
        synchronized (lifecycleLock) {
            stopping = true;
            restartRequested = false;
            running = linux;
            startingThread = worker;
        }
        if (running != null) running.destroy();
        if (startingThread != null) startingThread.interrupt();
        else stopSelfResult(latestStartId);
    }
    private void startWorkspace() {
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
                "-r", root.getAbsolutePath(), "-i", identity.prootIds(), "-w", identity.home,
                "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", "/system", "-b", "/apex",
                "-b", temp.getAbsolutePath() + ":/tmp",
                "-b", sharedMemory.getAbsolutePath() + ":/dev/shm",
                "/usr/bin/env", "-i", "HOME=" + identity.home, "USER=" + identity.user, "LOGNAME=" + identity.user,
                "LANG=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin",
                "DISPLAY=:2", "FOLDGPT_IME_UID=" + android.os.Process.myUid(),
                "FOLDGPT_SCALE=" + getResources().getDisplayMetrics().density,
                "/bin/bash", "/usr/local/bin/foldgpt-session"));
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
            Thread finished = Thread.currentThread();
            mainHandler.post(() -> {
                if (worker != finished || destroyed) return;
                worker = null;
                if (restartRequested) launchWorkspace();
                else stopSelfResult(latestStartId);
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
        running.destroy();
        try {
            if (!running.waitFor(2, java.util.concurrent.TimeUnit.SECONDS)) {
                running.destroyForcibly();
                running.waitFor(2, java.util.concurrent.TimeUnit.SECONDS);
            }
        } catch (InterruptedException e) {
            running.destroyForcibly();
            Thread.currentThread().interrupt();
        }
    }
    @Override public void onDestroy() {
        synchronized (lifecycleLock) {
            destroyed = true;
            stopping = true;
            if (linux != null) linux.destroy();
            if (worker != null) worker.interrupt();
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
            wakeLock = null;
        }
        super.onDestroy();
        // The X server has native worker threads. This dedicated service process owns
        // them. Normal stop waits for Linux first; killing synchronously here prevents
        // an old delayed shutdown from killing a newly created service instance.
        android.os.Process.killProcess(android.os.Process.myPid());
    }
}
