package app.foldgpt;

import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import static org.junit.Assert.*;

public final class RuntimeActivationsTest {
    /** Explicit test-controlled exit receipt; destroy is deliberately not one. */
    private static final class HeldProcess extends Process {
        final CountDownLatch waited = new CountDownLatch(1), killed = new CountDownLatch(1), exited = new CountDownLatch(1);
        final boolean timeout;
        HeldProcess(boolean timeout) { this.timeout = timeout; }
        @Override public OutputStream getOutputStream() { return OutputStream.nullOutputStream(); }
        @Override public InputStream getInputStream() { return InputStream.nullInputStream(); }
        @Override public InputStream getErrorStream() { return InputStream.nullInputStream(); }
        @Override public int waitFor() throws InterruptedException { waited.countDown(); exited.await(); return 0; }
        @Override public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException {
            if (unit.toSeconds(timeout) == 2 || this.timeout) return false;
            waited.countDown(); exited.await(); return true;
        }
        @Override public int exitValue() { if (isAlive()) throw new IllegalThreadStateException(); return 0; }
        @Override public void destroy() { }
        @Override public Process destroyForcibly() { killed.countDown(); return this; }
        @Override public boolean isAlive() { return exited.getCount() != 0; }
    }

    @Test public void delayedOldRunnableCannotStartInANewGeneration() throws Exception {
        Object lock = new Object();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), completed = new CountDownLatch(1);
        AtomicInteger oldStarts = new AtomicInteger();
        RuntimeActivations old = new RuntimeActivations(lock, () -> true, action -> new Thread(() -> {
            entered.countDown();
            boolean interrupted = false;
            for (;;) {
                try { release.await(); break; } catch (InterruptedException error) { interrupted = true; }
            }
            if (interrupted) Thread.currentThread().interrupt();
            action.run();
        }));
        assertTrue(old.launch("old", () -> { oldStarts.incrementAndGet(); throw new AssertionError("stale process created"); },
                (success, error) -> { assertFalse(success); assertTrue(error instanceof InterruptedException); completed.countDown(); }));
        assertTrue(entered.await(5, TimeUnit.SECONDS));
        old.cancel();
        assertFalse(old.launch("rejected", () -> { throw new AssertionError(); }, (success, error) -> {}));
        RuntimeActivations next = new RuntimeActivations(lock, () -> true);
        HeldProcess nextProcess = new HeldProcess(false);
        nextProcess.exited.countDown();
        CountDownLatch nextCompleted = new CountDownLatch(1);
        assertTrue(next.launch("new", () -> nextProcess, (success, error) -> nextCompleted.countDown()));
        assertTrue(nextCompleted.await(5, TimeUnit.SECONDS));
        release.countDown();
        old.closeAndJoin();
        next.closeAndJoin();
        assertEquals(0, oldStarts.get());
        assertEquals(0, completed.getCount());
    }

    @Test public void everyActivationMustExitBeforeTheWorkspaceJoinCompletes() throws Exception {
        RuntimeActivations group = new RuntimeActivations(new Object(), () -> true);
        HeldProcess one = new HeldProcess(false), two = new HeldProcess(false);
        AtomicInteger callbacks = new AtomicInteger();
        group.launch("one", () -> one, (success, error) -> callbacks.incrementAndGet());
        group.launch("two", () -> two, (success, error) -> callbacks.incrementAndGet());
        assertTrue(one.waited.await(5, TimeUnit.SECONDS));
        assertTrue(two.waited.await(5, TimeUnit.SECONDS));
        CountDownLatch joined = new CountDownLatch(1);
        Thread cleanup = new Thread(() -> { group.closeAndJoin(); joined.countDown(); });
        cleanup.start();
        try {
            assertTrue(one.killed.await(5, TimeUnit.SECONDS));
            assertTrue(two.killed.await(5, TimeUnit.SECONDS));
            assertEquals(1, joined.getCount());
            assertEquals(0, callbacks.get());
            one.exited.countDown();
            assertEquals(1, joined.getCount());
            cleanup.interrupt();
            assertEquals(1, joined.getCount());
        } finally { one.exited.countDown(); two.exited.countDown(); cleanup.join(5000); }
        assertFalse(cleanup.isAlive());
        assertEquals(0, joined.getCount());
        assertTrue(cleanup.isInterrupted());
        assertEquals(2, callbacks.get());
        group.closeAndJoin();
    }

    @Test public void timeoutWaitsForRealExitAndReportsFailureExactlyOnce() throws Exception {
        RuntimeActivations group = new RuntimeActivations(new Object(), () -> true);
        HeldProcess process = new HeldProcess(true);
        AtomicInteger callbacks = new AtomicInteger();
        AtomicBoolean reportedSuccess = new AtomicBoolean(true);
        group.launch("timeout", () -> process, (success, error) -> { reportedSuccess.set(success); callbacks.incrementAndGet(); });
        try {
            assertTrue(process.killed.await(5, TimeUnit.SECONDS));
            assertEquals(0, callbacks.get());
        } finally { process.exited.countDown(); group.closeAndJoin(); }
        assertEquals(1, callbacks.get());
        assertFalse(reportedSuccess.get());
    }

    @Test public void sessionLossBeforeCreationRefusesWithoutLosingCompletion() throws Exception {
        Object lock = new Object();
        AtomicInteger checks = new AtomicInteger(), starts = new AtomicInteger(), completions = new AtomicInteger();
        CountDownLatch completed = new CountDownLatch(1);
        RuntimeActivations group = new RuntimeActivations(lock, () -> checks.incrementAndGet() == 1);
        assertTrue(group.launch("gone", () -> { starts.incrementAndGet(); throw new AssertionError(); },
                (success, error) -> { completions.incrementAndGet(); completed.countDown(); }));
        assertTrue(completed.await(5, TimeUnit.SECONDS));
        group.closeAndJoin();
        assertEquals(2, checks.get());
        assertEquals(0, starts.get());
        assertEquals(1, completions.get());
    }

    @Test public void realChildProcessesAreWaitedAndDoNotSurviveCancellation() throws Exception {
        RuntimeActivations group = new RuntimeActivations(new Object(), () -> true);
        List<Process> children = new ArrayList<>();
        CountDownLatch started = new CountDownLatch(2);
        String java = Path.of(System.getProperty("java.home"), "bin", "java").toString();
        try {
            for (int i = 0; i < 2; i++) group.launch("real-child", () -> {
                Process child = new ProcessBuilder(java, "-cp", System.getProperty("java.class.path"), Child.class.getName()).start();
                children.add(child); started.countDown(); return child;
            }, (success, error) -> {});
            assertTrue(started.await(5, TimeUnit.SECONDS));
        } finally { group.closeAndJoin(); }
        assertEquals(2, children.size());
        for (Process child : children) { assertFalse(child.isAlive()); child.exitValue(); }
    }

    public static final class Child {
        public static void main(String[] args) throws InterruptedException { new CountDownLatch(1).await(); }
    }
}
