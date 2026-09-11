package app.foldgpt;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

/** One owner's serial work. Close only after its native cleanup receipt.
 * Accepted callbacks drain normally; late observer ticks cannot resurrect the
 * worker or throw into Android's main looper after that owner has closed.
 */
final class RuntimeOwnerWorker implements AutoCloseable {
    private final ExecutorService executor;
    private boolean closed;

    RuntimeOwnerWorker(String name) { this(task -> new Thread(task, name)); }
    RuntimeOwnerWorker(ThreadFactory threads) { executor = Executors.newSingleThreadExecutor(threads); }

    synchronized boolean execute(Runnable task) {
        if (closed) return false;
        executor.execute(task);
        return true;
    }

    @Override public synchronized void close() {
        if (closed) return;
        closed = true;
        executor.shutdown();
    }
}
