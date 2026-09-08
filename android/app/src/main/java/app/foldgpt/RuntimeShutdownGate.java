package app.foldgpt;

/** Keeps a foreground Service alive until both owned lifetimes actually end.
 * Completion callbacks may arrive in either order, or after a newer generation.
 * A failure or missing completion never releases the Service.
 */
public final class RuntimeShutdownGate {
    public enum Action { WAIT, STOP_SERVICE, RESTART }
    private long generation;
    private boolean active;
    private boolean nativeClean;
    private boolean workspaceExited;
    private boolean restart;
    private boolean stopReported;
    private boolean destroyed;
    private Throwable cleanupFailure;

    public synchronized long begin(boolean workspaceRunning) {
        if (destroyed) throw new IllegalStateException("Service was destroyed");
        if (active) throw new IllegalStateException("Shutdown already started");
        active = true;
        nativeClean = false;
        workspaceExited = !workspaceRunning;
        restart = false;
        stopReported = false;
        cleanupFailure = null;
        return ++generation;
    }

    public synchronized Action nativeCompleted(long expectedGeneration, Throwable error) {
        if (!current(expectedGeneration)) return Action.WAIT;
        if (nativeClean || cleanupFailure != null) return Action.WAIT;
        if (error == null) nativeClean = true;
        else cleanupFailure = error;
        return readyAction();
    }

    public synchronized Action workspaceExited(long expectedGeneration) {
        if (!current(expectedGeneration)) return Action.WAIT;
        workspaceExited = true;
        return readyAction();
    }

    public synchronized Action requestRestart() {
        if (!active || destroyed) return Action.WAIT;
        restart = true;
        return readyAction();
    }

    public synchronized Action cancelRestart() {
        restart = false;
        // A new explicit stop can carry the startId that made the previous
        // stopSelfResult fail. Retry only against already proven completion.
        stopReported = false;
        return readyAction();
    }
    public synchronized void destroy() { destroyed = true; restart = false; }

    private boolean current(long expectedGeneration) {
        return active && !destroyed && expectedGeneration == generation;
    }

    private Action readyAction() {
        if (destroyed || !active || !workspaceExited || !nativeClean || cleanupFailure != null) return Action.WAIT;
        if (restart) {
            active = false;
            return Action.RESTART;
        }
        // Keep the completed generation available: Android can reject stopSelfResult
        // because a newer startId is queued but onStartCommand has not arrived yet.
        if (!stopReported) {
            stopReported = true;
            return Action.STOP_SERVICE;
        }
        return Action.WAIT;
    }
}
