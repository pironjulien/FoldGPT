package app.foldgpt;

import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

/** All transient client activations belong to one workspace generation.
 * Process creation and cancellation share the service's lifecycle lock. A
 * closed generation never admits a delayed runnable, even after a new session
 * starts. Joining requires real process exits, including after timeout.
 */
public final class RuntimeActivations {
    @FunctionalInterface public interface Starter { Process start() throws Exception; }
    @FunctionalInterface public interface Completion { void completed(boolean success, Exception failure); }
    private final Object lock;
    private final BooleanSupplier sessionReady;
    private final ThreadFactory threads;
    private final Set<Activation> active = new HashSet<>();
    private boolean accepting = true;

    public RuntimeActivations(Object lock, BooleanSupplier sessionReady) {
        this(lock, sessionReady, Thread::new);
    }

    RuntimeActivations(Object lock, BooleanSupplier sessionReady, ThreadFactory threads) {
        this.lock = lock;
        this.sessionReady = sessionReady;
        this.threads = threads;
    }

    public boolean launch(String name, Starter starter, Completion completion) {
        synchronized (lock) {
            if (!accepting || !sessionReady.getAsBoolean()) return false;
            Activation activation = new Activation(starter, completion);
            activation.thread = threads.newThread(activation);
            activation.thread.setName(name);
            active.add(activation);
            // Starting under the same lock prevents cleanup from joining a
            // registered but not-yet-started thread and falsely completing.
            try { activation.thread.start(); }
            catch (RuntimeException | Error error) { active.remove(activation); throw error; }
            return true;
        }
    }

    public void cancel() {
        synchronized (lock) {
            accepting = false;
            for (Activation activation : active) {
                if (activation.process != null) activation.process.destroy();
                activation.thread.interrupt();
            }
        }
    }

    public void closeAndJoin() {
        cancel();
        Activation[] joining;
        synchronized (lock) { joining = active.toArray(new Activation[0]); }
        boolean interrupted = false;
        for (Activation activation : joining) {
            for (;;) {
                try { activation.thread.join(); break; }
                catch (InterruptedException error) { interrupted = true; cancel(); }
            }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }

    private final class Activation implements Runnable {
        private final Starter starter;
        private final Completion completion;
        private Thread thread;
        private Process process;
        Activation(Starter starter, Completion completion) { this.starter = starter; this.completion = completion; }

        @Override public void run() {
            boolean success = false;
            Exception failure = null;
            try {
                synchronized (lock) {
                    if (!accepting || !sessionReady.getAsBoolean()) throw new InterruptedException("Workspace activation cancelled");
                    process = starter.start();
                }
                process.getOutputStream().close();
                if (!process.waitFor(15, TimeUnit.SECONDS)) throw new IOException("Client activation timed out");
                if (process.exitValue() != 0) throw new IOException("Client activation failed: " + process.exitValue());
                success = true;
            } catch (Exception error) {
                failure = error;
                Thread.interrupted();
            } finally {
                stopAndWait(process);
                try { completion.completed(success, failure); }
                finally { synchronized (lock) { active.remove(this); } }
            }
        }
    }

    /** Neither a timeout nor an interrupt is a process-exit receipt. */
    public static void stopAndWait(Process process) {
        if (process == null) return;
        boolean interrupted = false;
        if (process.isAlive()) {
            process.destroy();
            try {
                if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly();
            } catch (InterruptedException error) {
                process.destroyForcibly();
                interrupted = true;
            }
        }
        for (;;) {
            try { process.waitFor(); break; }
            catch (InterruptedException error) { interrupted = true; process.destroyForcibly(); }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }
}
