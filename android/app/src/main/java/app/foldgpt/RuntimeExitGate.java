package app.foldgpt;

import java.util.HashSet;
import java.util.Set;

/** Process-wide native ownership, including overlapping Service generations. */
final class RuntimeExitGate {
    private final Set<Long> owners = new HashSet<>();
    private long generation;
    private long pendingGeneration;
    private Runnable pendingExit;

    synchronized long register() {
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
        if (!owners.isEmpty() || pendingExit == null || pendingGeneration != generation) return false;
        Runnable exit = pendingExit; pendingExit = null;
        exit.run();
        return true;
    }
}
