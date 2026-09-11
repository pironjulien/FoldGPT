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
    @Test public void ownerDeathRetiresExactlyOnceWithoutFabricatingCleanExit() {
        RuntimeExitGate gate = new RuntimeExitGate();
        long owner = gate.register();
        AtomicInteger retired = new AtomicInteger();
        assertTrue(gate.runExitAfterOwnerDeath(owner, retired::incrementAndGet));
        assertFalse(gate.runExitAfterOwnerDeath(owner, retired::incrementAndGet));
        assertFalse(gate.runExitIfClean());
        assertEquals(1, retired.get());
        assertThrows(IllegalStateException.class, gate::register);
        // The dead owner's cleanup was never claimed; its registration remains.
        gate.markClean(owner);
    }
    @Test public void delayedOwnerDeathCannotRetireAnotherGeneration() {
        RuntimeExitGate gate = new RuntimeExitGate();
        long older = gate.register(), newer = gate.register();
        AtomicInteger retired = new AtomicInteger();
        assertFalse(gate.runExitAfterOwnerDeath(older, retired::incrementAndGet));
        assertFalse(gate.runExitAfterOwnerDeath(newer, retired::incrementAndGet));
        gate.markClean(older);
        assertFalse(gate.runExitAfterOwnerDeath(older, retired::incrementAndGet));
        assertTrue(gate.runExitAfterOwnerDeath(newer, retired::incrementAndGet));
        assertEquals(1, retired.get());
    }
    @Test public void cleanGenerationDoesNotAuthoriseUncleanRetirement() {
        RuntimeExitGate gate = new RuntimeExitGate();
        long owner = gate.register();
        gate.markClean(owner);
        assertFalse(gate.runExitAfterOwnerDeath(owner, () -> fail("Clean owner cannot authorise retirement")));
    }
}
