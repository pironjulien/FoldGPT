package com.termux.x11;

import android.app.*;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import androidx.core.content.ContextCompat;
import android.os.*;
import android.system.Os;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.util.Log;
import app.foldgpt.FoldActivity;
import app.foldgpt.FoldExecutorRuntime;
import app.foldgpt.RuntimeShutdownGate;
import app.foldgpt.RuntimeRecoveryPolicy;
import app.foldgpt.RuntimeRecoveryStore;
import app.foldgpt.RuntimeActivations;
import app.foldgpt.KeyringVault;
import app.foldgpt.FoldConversationMonitor;
import app.foldgpt.FoldLocalTools;
import app.foldgpt.ConversationActivity;
import app.foldgpt.PendingConnectorCallback;
import app.foldgpt.install.GuestIdentity;
import java.io.*;
import java.util.*;

/** Owns the X server and Linux process, independently of the display Activity. */
public final class FoldRuntimeService extends Service {
    public static final String ACTION_STATUS = "app.foldgpt.RUNTIME_STATUS";
    public static final String ACTION_QUERY_STATUS = "app.foldgpt.QUERY_RUNTIME_STATUS";
    public static final String ACTION_START = "app.foldgpt.START_RUNTIME";
    public static final String EXTRA_PHASE_TIME = "app.foldgpt.PHASE_TIME";
    public static final String EXTRA_THREAD = "app.foldgpt.OPEN_THREAD";
    public static final String EXTRA_CONNECTOR_CALLBACK = "app.foldgpt.CONNECTOR_CALLBACK";
    private String phase = "starting", phaseDetail = "";
    private long phaseAt = SystemClock.elapsedRealtimeNanos(), shutdownRequestedAt;
    private int activeResponses;
    private volatile String sessionToken = "";
    private volatile FileObserver readyObserver;
    private volatile FoldConversationMonitor conversations;
    private List<String> conversationCommand;
    private Map<String, String> conversationEnvironment;
    private String pendingThread;
    private final PendingConnectorCallback connectorCallbacks = new PendingConnectorCallback();
    private RuntimeActivations activations;
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
    private boolean shutdownComplete;
    private boolean destroyed;
    private boolean xReady;
    private int latestStartId;
    private FoldExecutorRuntime executorRuntime;
    private app.foldgpt.FoldAudioBridge audioBridge;
    private RuntimeRecoveryStore recoveryStore;
    private RuntimeRecoveryPolicy recovery;
    private Runnable pendingLaunch;
    private boolean automaticRecovery;
    private long restartDelay;
    private final BroadcastReceiver statusQuery = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { broadcastPhase(); }
    };
    @Override public void onCreate() {
        super.onCreate();
        audioBridge = new app.foldgpt.FoldAudioBridge(this);
        try {
            recoveryStore = new RuntimeRecoveryStore(this);
            recovery = recoveryStore.load();
        } catch (Exception error) {
            Log.e("FoldGPT", "Cannot restore runtime user intent; explicit launch is required", error);
            recovery = recoveryStore == null ? new RuntimeRecoveryPolicy("unavailable") : recoveryStore.empty();
        }
        executorRuntime = newExecutorRuntime();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.deleteNotificationChannel("foldgpt.display.v1");
        manager.createNotificationChannel(new NotificationChannel("workspace", "Fonctionnement de ChatGPT", NotificationManager.IMPORTANCE_LOW));
        manager.createNotificationChannel(new NotificationChannel("foldgpt.conversations.v1", "Conversations", NotificationManager.IMPORTANCE_DEFAULT));
        ContextCompat.registerReceiver(this, statusQuery, new IntentFilter(ACTION_QUERY_STATUS), ContextCompat.RECEIVER_NOT_EXPORTED);
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        startForeground(1, runtimeNotification());
        broadcastPhase();
        String action = intent == null ? null : intent.getAction();
        if ("stop".equals(action)) {
            requestStop();
            return START_NOT_STICKY;
        }
        if (intent == null) {
            // Android's sticky recreation contains no replayable launch extras.
            // A persisted explicit Stop or suspended crash burst forbids restart.
            if (worker != null || stopping) return startDisposition();
            long delay = recovery.serviceRecreated(SystemClock.elapsedRealtime());
            if (!saveRecovery()) { beginShutdown(); return START_NOT_STICKY; }
            if (delay < 0) {
                if (recovery.desiredRunning()) publishRecoveryExhausted();
                beginShutdown();
                return START_NOT_STICKY;
            }
            automaticRecovery = true;
            scheduleLaunch(delay);
            return startDisposition();
        }
        boolean prepareOnly = FoldExecutorRuntime.ACTION_PREPARE.equals(action);
        if (!ACTION_START.equals(action) && !prepareOnly) {
            // Display lifecycle events are not restart authority. Ignore obsolete
            // unqualified starts without disturbing an existing running session.
            if (!stopping && worker == null && pendingLaunch == null) beginShutdown();
            else if (shutdownComplete) stopSelfResult(latestStartId);
            return startDisposition();
        }
        if (!prepareOnly) {
            recovery.userStarted(SystemClock.elapsedRealtime(), worker != null && !stopping);
            if (!saveRecovery()) { beginShutdown(); return START_NOT_STICKY; }
            cancelPendingLaunch();
            automaticRecovery = false;
            restartDelay = 0;
        }
        String thread = intent.getStringExtra(EXTRA_THREAD);
        if (thread != null && thread.matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")) pendingThread = thread;
        String callback = intent == null ? null : intent.getStringExtra(EXTRA_CONNECTOR_CALLBACK);
        if (callback != null) {
            intent.removeExtra(EXTRA_CONNECTOR_CALLBACK);
            try {
                PendingConnectorCallback.Offer accepted = connectorCallbacks.offer(callback);
                if (accepted == PendingConnectorCallback.Offer.BUSY) connectorHandoffFailed();
            } catch (IllegalArgumentException error) { connectorHandoffFailed(); }
        }
        if (stopping) {
            restartWorkspace |= !prepareOnly;
            applyShutdownAction(shutdownGate.requestRestart());
            return startDisposition();
        }
        if (prepareOnly) {
            // Deliberate native preparation command. Its failure is explicit;
            // it never starts the old launcher as an implicit fallback.
            prepareNative(executorRuntime);
            return START_NOT_STICKY;
        }
        if (worker == null) launchWorkspace();
        else { openPendingConversation(); openPendingConnectorCallback(); }
        return startDisposition();
    }
    private int startDisposition() { return recovery.permitsRecovery() ? START_STICKY : START_NOT_STICKY; }
    private boolean saveRecovery() {
        try {
            if (recoveryStore == null) throw new IOException("Runtime intent storage is unavailable");
            recoveryStore.save(recovery);
            return true;
        } catch (Exception error) {
            recovery.userStopped();
            cancelPendingLaunch();
            Log.e("FoldGPT", "Cannot persist runtime user intent", error);
            publishPhase("error", "L’état de démarrage de ChatGPT n’a pas pu être enregistré. Réessayez l’ouverture de l’application.");
            return false;
        }
    }
    private FoldExecutorRuntime newExecutorRuntime() {
        FoldExecutorRuntime runtime = new FoldExecutorRuntime(this);
        runtime.failure().thenAccept(error -> mainHandler.post(() -> {
            if (!destroyed && runtime == executorRuntime && worker != null && !stopping)
                recoverWorkspace("L’exécution locale de ChatGPT s’est interrompue.");
        }));
        runtime.ownerDeath().thenRun(() -> mainHandler.post(() -> retireDeadOwner(runtime)));
        return runtime;
    }
    private void retireDeadOwner(FoldExecutorRuntime runtime) {
        if (destroyed || runtime != executorRuntime) return;
        // Reuse a retry already charged by the Linux exit callback. Persist it
        // BEFORE losing this VM; sticky recreation must not reset the budget.
        long delay = recovery.serviceRecreated(SystemClock.elapsedRealtime());
        if (!saveRecovery()) return;
        cancelPendingLaunch();
        if (delay < 0 && recovery.desiredRunning()) publishRecoveryExhausted();
        else if (delay >= 0) publishPhase("recovering", "Le moteur local s’est interrompu. Reprise de ChatGPT…");
        synchronized (lifecycleLock) { stopping = true; restartWorkspace = false; }
        interruptActivations();
        connectorCallbacks.cancelPending();
        if (audioBridge != null) audioBridge.stop();
        // A reaped owner cannot acknowledge cancellation. Keep its marker and
        // unclean receipt, end only this Java process, and let Android reap its
        // process group. The recreated owner refuses any surviving process.
        try {
            if (!runtime.retireProcessAfterOwnerDeath(() -> {
                Log.w("FoldGPT", "Native owner exited without cleanup; retiring Android runtime process group");
                android.os.Process.killProcess(android.os.Process.myPid());
            })) publishPhase("error", "La reprise n’a pas pu isoler l’ancienne session.");
        } catch (Exception | LinkageError error) {
            Log.e("FoldGPT", "Cannot retire dead native owner", error);
            publishPhase("error", "L’arrêt de l’ancienne session n’a pas pu être confirmé.");
        }
    }
    private void cancelPendingLaunch() {
        if (pendingLaunch != null) mainHandler.removeCallbacks(pendingLaunch);
        pendingLaunch = null;
    }
    private void scheduleLaunch(long delay) {
        cancelPendingLaunch();
        if (destroyed || stopping || !recovery.permitsRecovery()) return;
        if (delay == 0) { launchWorkspace(); return; }
        publishPhase("recovering", "ChatGPT s’est interrompu. Reprise de la session…");
        pendingLaunch = () -> {
            pendingLaunch = null;
            if (destroyed || stopping || worker != null || !recovery.permitsRecovery()) return;
            long remaining = recovery.serviceRecreated(SystemClock.elapsedRealtime());
            if (!saveRecovery() || remaining < 0) {
                publishRecoveryExhausted();
                beginShutdown();
            } else scheduleLaunch(remaining);
        };
        mainHandler.postDelayed(pendingLaunch, delay);
    }
    private void publishRecoveryExhausted() {
        publishPhase("error", "ChatGPT n’a pas réussi à reprendre dans son délai de démarrage de 90 secondes. Réessayez l’ouverture de l’application.");
    }
    private void recoverWorkspace(String detail) {
        if (destroyed || stopping) return;
        if (connectorCallbacks.cancelPending()) connectorHandoffFailed();
        long delay = recovery.failed(SystemClock.elapsedRealtime());
        boolean persisted = saveRecovery();
        automaticRecovery = persisted && delay >= 0;
        restartWorkspace = automaticRecovery;
        restartDelay = automaticRecovery ? delay : 0;
        if (automaticRecovery) publishPhase("recovering", detail);
        else if (persisted) publishRecoveryExhausted();
        // The retry cannot bypass either the native receipt or the actual Linux
        // wait. A surviving/quarantined owner therefore remains an explicit error.
        beginShutdown();
        if (automaticRecovery) applyShutdownAction(shutdownGate.requestRestart());
        synchronized (lifecycleLock) {
            if (linux != null) linux.destroy();
            if (worker != null) worker.interrupt();
        }
    }
    private PendingIntent openIntent(String thread) {
        Intent intent = new Intent(this, FoldActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (thread != null) intent.setData(android.net.Uri.parse("foldgpt://conversation/" + thread)).putExtra(EXTRA_THREAD, thread);
        return PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }
    private Notification runtimeNotification() {
        String text = "starting".equals(phase) ? "Ouverture de ChatGPT…" :
            "recovering".equals(phase) ? "Reprise de ChatGPT…" :
            "stopping".equals(phase) ? "Fermeture de ChatGPT…" :
            "error".equals(phase) ? "ChatGPT n’a pas pu démarrer" :
            activeResponses == 1 ? "Une conversation en cours" : activeResponses > 1 ? activeResponses + " conversations en cours" : "ChatGPT est en cours d’exécution";
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, FoldRuntimeService.class).setAction("stop"), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, "workspace").setSmallIcon(app.foldgpt.R.drawable.foldgpt_notification_icon)
            .setContentTitle("ChatGPT").setContentText(text).setContentIntent(openIntent(null))
            .setVisibility(Notification.VISIBILITY_PRIVATE).setOnlyAlertOnce(true).setShowWhen(false)
            .addAction(new Notification.Action.Builder(null, "Fermer ChatGPT", stop).build()).setOngoing(true).build();
    }
    private void broadcastPhase() {
        sendBroadcast(new Intent(ACTION_STATUS).setPackage(getPackageName()).putExtra("phase", phase)
                .putExtra("detail", phaseDetail).putExtra(EXTRA_PHASE_TIME, phaseAt));
    }
    private void publishPhase(String next, String detail) {
        if (Looper.myLooper() != Looper.getMainLooper()) { mainHandler.post(() -> publishPhase(next, detail)); return; }
        if (destroyed) return;
        phase = next; phaseDetail = detail == null ? "" : detail;
        phaseAt = "stopping".equals(next) && shutdownRequestedAt != 0
                ? shutdownRequestedAt : SystemClock.elapsedRealtimeNanos();
        getSystemService(NotificationManager.class).notify(1, runtimeNotification());
        broadcastPhase();
        if ("ready".equals(next)) {
            recovery.ready(SystemClock.elapsedRealtime());
            if (!saveRecovery()) { beginShutdown(); return; }
            automaticRecovery = false;
            String token = sessionToken;
            mainHandler.postDelayed(() -> {
                if (!destroyed && !stopping && sessionToken.equals(token)
                        && recovery.stable(SystemClock.elapsedRealtime())) saveRecovery();
            }, RuntimeRecoveryPolicy.STABLE_WINDOW_MS);
            openPendingConversation(); openPendingConnectorCallback();
        }
        if ("error".equals(next) && connectorCallbacks.cancelPending()) connectorHandoffFailed();
    }
    private void responseChanged(String thread, String title, ConversationActivity.Change change, int active) {
        activeResponses = active;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.notify(1, runtimeNotification());
        if (change == ConversationActivity.Change.STARTED) { manager.cancel(thread, 2); return; }
        Notification publicVersion = new Notification.Builder(this, "foldgpt.conversations.v1")
            .setSmallIcon(app.foldgpt.R.drawable.foldgpt_notification_icon).setContentTitle("ChatGPT").setContentText("Une conversation a été mise à jour").build();
        manager.notify(thread, 2, new Notification.Builder(this, "foldgpt.conversations.v1")
            .setSmallIcon(app.foldgpt.R.drawable.foldgpt_notification_icon).setContentTitle(title)
            .setContentText(change == ConversationActivity.Change.COMPLETED ? "Réponse disponible" : "Réponse interrompue")
            .setContentIntent(openIntent(thread)).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion).setCategory(Notification.CATEGORY_STATUS).build());
    }
    private void openPendingConversation() {
        if (!"ready".equals(phase) || stopping || destroyed || pendingThread == null
                || conversationCommand == null || conversationEnvironment == null || activations == null) return;
        String thread = pendingThread; pendingThread = null;
        List<String> args = new ArrayList<>(conversationCommand);
        args.add("/usr/bin/chatgpt"); args.add("codex://threads/" + thread);
        Map<String, String> environment = new HashMap<>(conversationEnvironment);
        activations.launch("FoldGPT-open-conversation", () -> {
                ProcessBuilder command = new ProcessBuilder(args);
                command.environment().putAll(environment);
                command.redirectOutput(new File("/dev/null")).redirectError(new File("/dev/null"));
                return command.start();
            }, (delivered, error) -> {
                if (!delivered && !(error instanceof InterruptedException))
                    Log.e("FoldGPT", "Could not open the notified conversation", error);
            });
    }
    private void connectorHandoffFailed() {
        // A transport failure does not say anything about OAuth authorization.
        // Never log exceptions here: subprocess/Intent diagnostics may carry the URI.
        Log.e("FoldGPT-Connector", "Connector callback handoff failed; reconnect from the client");
        android.widget.Toast.makeText(this, "Le retour de connexion n’a pas été transmis. Reprenez la connexion dans ChatGPT.", android.widget.Toast.LENGTH_LONG).show();
    }
    private void openPendingConnectorCallback() {
        String callback = connectorCallbacks.take("ready".equals(phase) && !stopping
                && !destroyed && conversationCommand != null && conversationEnvironment != null && activations != null);
        if (callback == null) return;
        List<String> args = new ArrayList<>(conversationCommand);
        // Fixed executable and one strictly validated URI argument, never a shell
        // command, option, project path, or generic codex deep-link dispatcher.
        args.add("/usr/bin/chatgpt"); args.add(callback);
        Map<String, String> environment = new HashMap<>(conversationEnvironment);
        boolean launched = activations.launch("FoldGPT-connector-callback", () -> {
                ProcessBuilder command = new ProcessBuilder(args);
                command.environment().putAll(environment);
                command.redirectOutput(new File("/dev/null")).redirectError(new File("/dev/null"));
                return command.start();
            }, (delivered, error) -> {
                // No automatic retry or exception logging: the invocation may
                // already have submitted this one-time callback to the client.
                connectorCallbacks.completed();
                mainHandler.post(() -> {
                    if (delivered) Log.i("FoldGPT-Connector", "Connector callback invocation completed; authorization result belongs to the client");
                    else if (!destroyed) connectorHandoffFailed();
                });
            });
        if (!launched) {
            connectorCallbacks.completed();
            connectorHandoffFailed();
        }
    }
    private void interruptActivations() {
        synchronized (lifecycleLock) { if (activations != null) activations.cancel(); }
    }
    private void startObservers(File root, String guestHome, File temporary, String token,
            java.util.concurrent.CompletableFuture<Void> clientReady) throws Exception {
        FoldConversationMonitor monitor = new FoldConversationMonitor(new File(root, guestHome.substring(1) + "/.codex"),
            (thread, title, change, active) -> mainHandler.post(() -> {
                if (!destroyed && !stopping && sessionToken.equals(token)) responseChanged(thread, title, change, active);
            }));
        conversations = monitor;
        monitor.start().get(10, java.util.concurrent.TimeUnit.SECONDS);
        File ready = new File(temporary, "foldgpt-client-ready");
        FileObserver observer = new FileObserver(temporary, FileObserver.CLOSE_WRITE | FileObserver.MOVED_TO) {
            @Override public void onEvent(int event, String path) {
                if (!"foldgpt-client-ready".equals(path)) return;
                try {
                    String value = java.nio.file.Files.readString(ready.toPath()).trim();
                    if (token.equals(value)) {
                        clientReady.complete(null);
                        mainHandler.post(() -> {
                            if (!destroyed && !stopping && sessionToken.equals(token)) publishPhase("ready", "");
                        });
                    }
                } catch (IOException error) { Log.w("FoldGPT", "Readiness event unavailable", error); }
            }
        };
        readyObserver = observer; observer.startWatching();
    }
    private void stopObservers() {
        FileObserver ready = readyObserver; readyObserver = null;
        FoldConversationMonitor monitor = conversations; conversations = null;
        if (ready != null) ready.stopWatching();
        if (monitor != null) monitor.close();
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
        if (destroyed || stopping || worker != null || !recovery.permitsRecovery()) return;
        recovery.launching();
        if (!saveRecovery()) { beginShutdown(); return; }
        activeResponses = 0;
        conversationCommand = null;
        conversationEnvironment = null;
        publishPhase("starting", "");
        synchronized (lifecycleLock) {
            if (destroyed || worker != null) return;
            stopping = false;
            restartWorkspace = false;
            FoldExecutorRuntime runtime = executorRuntime;
            // Both the group and native owner identify this workspace generation.
            RuntimeActivations generationActivations = new RuntimeActivations(lifecycleLock,
                    () -> runtime == executorRuntime && !destroyed && !stopping && linux != null && linux.isAlive());
            activations = generationActivations;
            workspaceClosed = new java.util.concurrent.CompletableFuture<>();
            java.util.concurrent.CompletableFuture<Void> completion = workspaceClosed;
            worker = new Thread(() -> startWorkspace(runtime, completion, generationActivations), "FoldGPT-runtime");
            worker.start();
        }
    }
    private void requestStop() {
        // Commit the user's authority before any callback can schedule a retry.
        recovery.userStopped();
        saveRecovery();
        cancelPendingLaunch();
        automaticRecovery = false;
        restartDelay = 0;
        shutdownRequestedAt = SystemClock.elapsedRealtimeNanos();
        phaseAt = shutdownRequestedAt;
        if ("error".equals(phase)) broadcastPhase();
        if (connectorCallbacks.cancelPending()) connectorHandoffFailed();
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
        if (shutdownRequestedAt == 0) shutdownRequestedAt = SystemClock.elapsedRealtimeNanos();
        if (!"error".equals(phase) && !automaticRecovery) publishPhase("stopping", "");
        synchronized (lifecycleLock) {
            if (destroyed || stopping) return;
            stopping = true;
            shutdownComplete = false;
            shutdownGeneration = shutdownGate.begin(worker != null);
        }
        interruptActivations();
        long generation = shutdownGeneration;
        FoldExecutorRuntime runtime = executorRuntime;
        try {
            runtime.requestStop().whenComplete((ignored, error) -> mainHandler.post(() -> {
                if (destroyed || runtime != executorRuntime) return;
                if (error != null) {
                    Log.e("FoldGPT", "Native cleanup is unconfirmed; retaining runtime service", error);
                    publishPhase("error", "L’arrêt de l’ancienne session n’est pas confirmé. La reprise attend la fin de ses processus.");
                }
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
            long delay = restartDelay;
            executorRuntime = newExecutorRuntime();
            stopping = false;
            shutdownComplete = false;
            shutdownRequestedAt = 0;
            restartWorkspace = false;
            restartDelay = 0;
            if (launch) {
                reapOwnedProcesses();
                if (delay > 0) delay = recovery.serviceRecreated(SystemClock.elapsedRealtime());
                if (delay < 0) { saveRecovery(); publishRecoveryExhausted(); beginShutdown(); }
                else scheduleLaunch(delay);
            }
            else {
                reapOwnedProcesses();
                prepareNative(executorRuntime);
            }
        } else if (action == RuntimeShutdownGate.Action.STOP_SERVICE) {
            reapOwnedProcesses();
            shutdownComplete = true;
            stopSelfResult(latestStartId);
        }
    }

    /**
     * PRoot and Electron intentionally create helpers which can outlive their
     * direct parent (PPID becomes 1). Waiting on the top-level Process is
     * therefore insufficient: those helpers keep the application UID in the
     * phantom-process budget and can make Android trim a later session. Once
     * both native cleanup and the workspace wait have completed, every process
     * of this UID except the two Java application processes belongs to the
     * current FoldGPT session and can be terminated before a restart/stop.
     */
    private void reapOwnedProcesses() {
        final int uid = android.os.Process.myUid();
        final int self = android.os.Process.myPid();
        ArrayList<Integer> candidates = new ArrayList<>();
        File proc = new File("/proc");
        File[] entries = proc.listFiles();
        if (entries == null) return;
        for (File entry : entries) {
            String name = entry.getName();
            if (!name.matches("[0-9]+")) continue;
            int pid;
            try { pid = Integer.parseInt(name); }
            catch (NumberFormatException ignored) { continue; }
            if (pid == self) continue;
            String command = readProcessCommand(entry);
            if (command == null || command.startsWith("app.foldgpt")) continue;
            if (processUid(entry) == uid) candidates.add(pid);
        }
        for (int pid : candidates) {
            try { Os.kill(pid, OsConstants.SIGTERM); }
            catch (ErrnoException ignored) { }
        }
        if (candidates.isEmpty()) return;
        SystemClock.sleep(150);
        for (int pid : candidates) {
            if (!new File("/proc", Integer.toString(pid)).exists()) continue;
            try { Os.kill(pid, OsConstants.SIGKILL); }
            catch (ErrnoException ignored) { }
        }
        Log.i("FoldGPT", "Reclaimed " + candidates.size() + " orphaned session processes");
    }

    private static String readProcessCommand(File entry) {
        try {
            byte[] bytes = java.nio.file.Files.readAllBytes(new File(entry, "cmdline").toPath());
            if (bytes.length == 0) return "";
            for (int i = 0; i < bytes.length; ++i) if (bytes[i] == 0) bytes[i] = ' ';
            return new String(bytes, java.nio.charset.StandardCharsets.UTF_8).trim();
        } catch (Exception ignored) { return null; }
    }

    private static int processUid(File entry) {
        try {
            for (String line : java.nio.file.Files.readAllLines(new File(entry, "status").toPath())) {
                if (!line.startsWith("Uid:")) continue;
                String[] parts = line.trim().split("\\s+");
                return Integer.parseInt(parts[1]);
            }
        } catch (Exception ignored) { }
        return -1;
    }
    private void startWorkspace(FoldExecutorRuntime runtime, java.util.concurrent.CompletableFuture<Void> completion,
            RuntimeActivations generationActivations) {
        java.lang.Process started = null;
        byte[] keyringPassword = null;
        String failureDetail = "ChatGPT s’est interrompu.";
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
            File localTools = nativeEndpoint != null && nativeEndpoint.directNative()
                    ? FoldLocalTools.install(this, identity, new File(nativeEndpoint.workspace())) : null;
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
            String token = UUID.randomUUID().toString();
            sessionToken = token;
            java.util.concurrent.CompletableFuture<Void> clientReady = new java.util.concurrent.CompletableFuture<>();
            startObservers(root, identity.home, temp, token, clientReady);
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
                args.add("-b"); args.add(localTools.getPath() + ":" + localTools.getPath());
            }
            args.addAll(Arrays.asList("/usr/bin/env", "-i", "HOME=" + identity.home, "USER=" + identity.user, "LOGNAME=" + identity.user,
                "LANG=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin" + (localTools == null ? "" : ":" + new File(localTools, "bin").getPath()),
                "DISPLAY=:2", "FOLDGPT_IME_UID=" + android.os.Process.myUid(),
                "FOLDGPT_URL_UID=" + android.os.Process.myUid(),
                "FOLDGPT_SCALE=" + getResources().getDisplayMetrics().density,
                "FOLDGPT_LAZY_MCP=1",
                "FOLDGPT_THREAD_UNLOAD_SECS=180"));
            args.add("FOLDGPT_SESSION_TOKEN=" + token);
            if (localTools != null) args.add("FOLDGPT_TOOLS_DIR=" + localTools.getPath());
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
            List<String> openArgs = new ArrayList<>(args.subList(0, args.size() - 2));
            Map<String, String> openEnvironment = new HashMap<>(builder.environment());
            mainHandler.post(() -> { conversationCommand = openArgs; conversationEnvironment = openEnvironment; });
            builder.redirectErrorStream(true).redirectOutput(new File(getFilesDir(), "runtime.log"));
            synchronized (lifecycleLock) {
                if (stopping || destroyed) throw new InterruptedException("Workspace stopped");
                started = builder.start();
                linux = started;
                wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FoldGPT:workspace");
                wakeLock.acquire();
                if (audioBridge != null) audioBridge.start();
            }
            try (OutputStream input = started.getOutputStream()) {
                input.write(keyringPassword);
            } finally {
                Arrays.fill(keyringPassword, (byte) 0);
                keyringPassword = null;
            }
            // Use the same bounded startup budget as native preparation. A live
            // client without a window must not leave an endless loading screen.
            long windowDeadline = SystemClock.elapsedRealtime() + java.util.concurrent.TimeUnit.SECONDS.toMillis(90);
            while (!clientReady.isDone()) {
                if (started.waitFor(1, java.util.concurrent.TimeUnit.SECONDS))
                    throw new IOException("ChatGPT s’est fermé avant l’ouverture de sa fenêtre (code " + started.exitValue() + ").");
                if (SystemClock.elapsedRealtime() >= windowDeadline)
                    throw new IOException("La fenêtre de ChatGPT n’est pas apparue dans les 90 secondes prévues. Réessayez le démarrage.");
            }
            int exit = started.waitFor();
            Log.i("FoldGPT", "Linux exited with " + exit);
            failureDetail = "ChatGPT s’est fermé (code " + exit + "). Reprise de la session…";
        } catch (InterruptedException e) {
            // Stop is expected; clear the flag while waiting for process cleanup below.
            Thread.interrupted();
        } catch (Exception | LinkageError e) {
            Log.e("FoldGPT", "Workspace failed", e);
            failureDetail = e.toString();
        } finally {
            // Close this generation before waiting for Linux. Every transient
            // activation must also finish before workspaceClosed is published.
            generationActivations.cancel();
            if (audioBridge != null) audioBridge.stop();
            if (keyringPassword != null) Arrays.fill(keyringPassword, (byte) 0);
            stopLinux(started);
            generationActivations.closeAndJoin();
            stopObservers();
            synchronized (lifecycleLock) {
                if (linux == started) linux = null;
                if (activations == generationActivations) activations = null;
                if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
                wakeLock = null;
            }
            completion.complete(null);
            Thread finished = Thread.currentThread();
            String observedFailure = failureDetail;
            mainHandler.post(() -> {
                if (worker != finished || destroyed) return;
                worker = null;
                if (stopping) applyShutdownAction(shutdownGate.workspaceExited(shutdownGeneration));
                else recoverWorkspace(observedFailure);
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
        if (audioBridge != null) audioBridge.stop();
        cancelPendingLaunch();
        unregisterReceiver(statusQuery);
        connectorCallbacks.cancelPending();
        interruptActivations();
        stopObservers();
        stopForeground(STOP_FOREGROUND_REMOVE);
        if (!"error".equals(phase)) {
            phase = "stopped";
            phaseAt = shutdownRequestedAt != 0 ? shutdownRequestedAt : SystemClock.elapsedRealtimeNanos();
            broadcastPhase();
        }
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
