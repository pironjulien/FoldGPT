package app.foldgpt;

import org.junit.Test;
import static org.junit.Assert.*;
import java.util.concurrent.atomic.AtomicInteger;

public final class RuntimeExitGateTest {
    @Test public void requiresActualOwnerCleanup() {
        RuntimeExitGate gate = new RuntimeExitGate();
        AtomicInteger killed = new AtomicInteger();
        long owner = gate.register();
        gate.requestExit(owner, killed::incrementAndGet);
        assertFalse(gate.runExitIfClean());
        gate.markClean(owner);
        assertTrue(gate.runExitIfClean());
        assertEquals(1, killed.get());
        assertFalse(gate.runExitIfClean());
    }
    @Test public void newerShutdownCannotKillOlderUnresolvedOwner() {
        RuntimeExitGate gate = new RuntimeExitGate();
        AtomicInteger killed = new AtomicInteger();
        long older = gate.register(), newer = gate.register();
        gate.requestExit(newer, killed::incrementAndGet);
        gate.markClean(newer);
        assertFalse(gate.runExitIfClean());
        gate.markClean(older);
        assertTrue(gate.runExitIfClean());
        assertEquals(1, killed.get());
    }
    @Test public void oldDelayedShutdownCannotKillNewService() {
        RuntimeExitGate gate = new RuntimeExitGate();
        AtomicInteger stale = new AtomicInteger(), current = new AtomicInteger();
        long older = gate.register(); gate.requestExit(older, stale::incrementAndGet); gate.markClean(older);
        long newer = gate.register();
        assertFalse(gate.runExitIfClean());
        gate.requestExit(older, stale::incrementAndGet);
        gate.markClean(newer);
        assertFalse(gate.runExitIfClean());
        gate.requestExit(newer, current::incrementAndGet);
        assertTrue(gate.runExitIfClean());
        assertEquals(0, stale.get()); assertEquals(1, current.get());
    }
    @Test public void rejectsInventedAndDoubleCleanup() {
        RuntimeExitGate gate = new RuntimeExitGate(); long owner = gate.register();
        assertThrows(IllegalStateException.class, () -> gate.markClean(owner + 1));
        gate.markClean(owner);
        assertThrows(IllegalStateException.class, () -> gate.markClean(owner));
    }
}
