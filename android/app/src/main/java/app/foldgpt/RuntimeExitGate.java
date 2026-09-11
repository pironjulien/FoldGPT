package app.foldgpt;

import java.util.HashSet;
import java.util.Set;

/** Process-wide native ownership, including overlapping Service generations. */
final class RuntimeExitGate {
    private final Set<Long> owners = new HashSet<>();
    private long generation;
    private long pendingGeneration;
    private Runnable pendingExit;
    private boolean retiring;

    synchronized long register() {
        if (retiring) throw new IllegalStateException("Runtime process retirement has begun");
        owners.add(++generation);
        pendingExit = null;
        return generation;
    }
    synchronized void requestExit(long owner, Runnable exit) {
        if (owner <= 0 || owner > generation) throw new IllegalArgumentException("Unknown runtime generation");
        if (owner == generation) {
            pendingGeneration = owner;
            pendingExit = java.util.Objects.requireNonNull(exit);
        }
    }
    synchronized void markClean(long owner) {
        if (!owners.remove(owner)) throw new IllegalStateException("Runtime ownership was already released or never registered");
    }
    /** Call on the Android main thread; registration and the final kill are atomic. */
    synchronized boolean runExitIfClean() {
        if (retiring || !owners.isEmpty() || pendingExit == null || pendingGeneration != generation) return false;
        Runnable exit = pendingExit; pendingExit = null;
        exit.run();
        return true;
    }

    /** Separate from clean exit: the caller has freshly waited its dead native
     * owner. Never mark that generation clean or retire another retained owner.
     * Android process-group teardown and the next admission supply the evidence. */
    synchronized boolean runExitAfterOwnerDeath(long owner, Runnable exit) {
        if (retiring || owner != generation || owners.size() != 1 || !owners.contains(owner)) return false;
        java.util.Objects.requireNonNull(exit);
        retiring = true;
        pendingExit = null;
        exit.run();
        return true;
    }
}
