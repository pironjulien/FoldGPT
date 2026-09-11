package app.foldgpt;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import static org.junit.Assert.*;

public final class RuntimeOwnerWorkerTest {
    @Test public void closingDrainsEveryAcceptedReceiptWithoutInterruptingIt() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger receipts = new AtomicInteger();
        AtomicReference<Thread> thread = new AtomicReference<>();
        RuntimeOwnerWorker worker = new RuntimeOwnerWorker(task -> {
            Thread created = new Thread(task); thread.set(created); return created;
        });
        try {
            assertTrue(worker.execute(() -> {
                entered.countDown();
                try { release.await(); } catch (InterruptedException error) { throw new AssertionError(error); }
            }));
            assertTrue(entered.await(5, TimeUnit.SECONDS));
            assertTrue(worker.execute(receipts::incrementAndGet));
            assertTrue(worker.execute(receipts::incrementAndGet));
            worker.close();
            worker.close();
            assertFalse(worker.execute(() -> { throw new AssertionError("late observer ran"); }));
            assertTrue(thread.get().isAlive());
            assertEquals(0, receipts.get());
        } finally { release.countDown(); worker.close(); }
        thread.get().join(5000);
        assertFalse(thread.get().isAlive());
        assertEquals(2, receipts.get());
    }

    @Test public void repeatedCleanGenerationsLeaveNoOwnerThreads() throws Exception {
        List<Thread> threads = new ArrayList<>();
        for (int generation = 0; generation < 5; generation++) {
            RuntimeOwnerWorker worker = new RuntimeOwnerWorker(task -> {
                Thread thread = new Thread(task, "fixture-owner"); threads.add(thread); return thread;
            });
            CountDownLatch receipt = new CountDownLatch(1);
            assertTrue(worker.execute(() -> { worker.close(); receipt.countDown(); }));
            assertTrue(receipt.await(5, TimeUnit.SECONDS));
            Thread thread = threads.get(generation);
            thread.join(5000);
            assertFalse("old generation retained its worker", thread.isAlive());
            assertFalse(worker.execute(() -> { throw new AssertionError("old tick ran"); }));
        }
    }

    @Test public void stoppingAnUnusedOwnerDoesNotCreateAThread() {
        RuntimeOwnerWorker worker = new RuntimeOwnerWorker(task -> { throw new AssertionError("worker created after close"); });
        worker.close();
        worker.close();
        assertFalse(worker.execute(() -> {}));
    }
}
