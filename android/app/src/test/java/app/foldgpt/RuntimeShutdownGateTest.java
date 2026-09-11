package app.foldgpt;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import static app.foldgpt.RuntimeShutdownGate.Action.*;
import static org.junit.Assert.*;

public final class RuntimeShutdownGateTest {
    @Test public void workspaceExitDoesNotReleasePendingNativeOwner() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(STOP_SERVICE, gate.nativeCompleted(generation, null));
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
    }

    @Test public void nativeCompletionDoesNotReleaseRunningWorkspace() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
        assertEquals(STOP_SERVICE, gate.workspaceExited(generation));
        assertEquals(WAIT, gate.workspaceExited(generation));
    }

    @Test public void prepareOnlyShutdownStillWaitsForNativeCompletion() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(false);
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(STOP_SERVICE, gate.nativeCompleted(generation, null));
    }

    @Test public void pendingFutureKeepsForegroundUntilRealCompletion() throws Exception {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(false);
        CompletableFuture<Void> nativeStop = new CompletableFuture<>();
        AtomicInteger stopped = new AtomicInteger();
        CountDownLatch callback = new CountDownLatch(1);
        nativeStop.whenComplete((ignored, error) -> {
            if (gate.nativeCompleted(generation, error) == STOP_SERVICE) stopped.incrementAndGet();
            callback.countDown();
        });
        assertEquals(0, stopped.get());
        assertEquals(1L, callback.getCount());
        Thread cleanup = new Thread(() -> nativeStop.complete(null));
        cleanup.start();
        assertTrue(callback.await(5, TimeUnit.SECONDS));
        cleanup.join();
        assertEquals(1, stopped.get());
    }

    @Test public void exceptionalCleanupCannotReleaseOrRestart() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(WAIT, gate.nativeCompleted(generation, new IllegalStateException("no cleanup receipt")));
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(WAIT, gate.requestRestart());
        // A later duplicate success cannot rewrite the failed completion.
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
    }

    @Test public void timeoutIsNotCleanupSuccess() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(false);
        assertEquals(WAIT, gate.nativeCompleted(generation, new java.util.concurrent.TimeoutException()));
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(WAIT, gate.workspaceExited(generation));
    }

    @Test public void restartWaitsForBothPreviousLifetimes() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
        assertEquals(RESTART, gate.workspaceExited(generation));
        assertEquals(WAIT, gate.workspaceExited(generation));
    }

    @Test public void explicitStopCancelsQueuedRestart() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.requestRestart());
        gate.cancelRestart();
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(STOP_SERVICE, gate.nativeCompleted(generation, null));
    }

    @Test public void queuedStartAfterStopSelfRejectionCanStillRestart() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(false);
        assertEquals(STOP_SERVICE, gate.nativeCompleted(generation, null));
        // The OS had already accepted a newer startId before its callback arrived.
        assertEquals(RESTART, gate.requestRestart());
        assertEquals(WAIT, gate.requestRestart());
    }

    @Test public void queuedExplicitStopRetriesOnlyAnAlreadyCleanGeneration() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(false);
        assertEquals(WAIT, gate.cancelRestart());
        assertEquals(STOP_SERVICE, gate.nativeCompleted(generation, null));
        // The newer queued stop startId invalidated the first stopSelfResult.
        assertEquals(STOP_SERVICE, gate.cancelRestart());
    }

    @Test public void oldCompletionsCannotStopOrRestartNewGeneration() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long older = gate.begin(false);
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(RESTART, gate.nativeCompleted(older, null));
        long newer = gate.begin(true);
        assertTrue(newer > older);
        assertEquals(WAIT, gate.workspaceExited(older));
        assertEquals(WAIT, gate.nativeCompleted(older, null));
        assertEquals(WAIT, gate.nativeCompleted(newer, null));
        assertEquals(STOP_SERVICE, gate.workspaceExited(newer));
    }

    @Test public void destructionInvalidatesPendingActions() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.requestRestart());
        gate.destroy();
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(WAIT, gate.requestRestart());
        assertThrows(IllegalStateException.class, () -> gate.begin(false));
    }

    @Test public void rejectsOverlappingShutdownBegins() {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        gate.begin(true);
        assertThrows(IllegalStateException.class, () -> gate.begin(false));
    }

    @Test public void concurrentCompletionsReleaseExactlyOnce() throws Exception {
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        long generation = gate.begin(true);
        AtomicInteger stopped = new AtomicInteger();
        CountDownLatch ready = new CountDownLatch(2), go = new CountDownLatch(1);
        Thread nativeThread = new Thread(() -> {
            ready.countDown();
            try { go.await(); } catch (InterruptedException error) { throw new AssertionError(error); }
            if (gate.nativeCompleted(generation, null) == STOP_SERVICE) stopped.incrementAndGet();
        });
        Thread workspaceThread = new Thread(() -> {
            ready.countDown();
            try { go.await(); } catch (InterruptedException error) { throw new AssertionError(error); }
            if (gate.workspaceExited(generation) == STOP_SERVICE) stopped.incrementAndGet();
        });
        nativeThread.start(); workspaceThread.start();
        assertTrue(ready.await(5, TimeUnit.SECONDS));
        go.countDown();
        nativeThread.join(); workspaceThread.join();
        assertEquals(1, stopped.get());
    }
}
