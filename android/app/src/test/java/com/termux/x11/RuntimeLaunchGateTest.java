package com.termux.x11;

import org.junit.Test;
import static org.junit.Assert.*;
import com.termux.x11.FoldDisplayActivity.RuntimeLaunchGate;

public final class RuntimeLaunchGateTest {
    @Test public void launchIsConsumedBeforeFocusOrPostureCanRepeatIt() {
        RuntimeLaunchGate gate = new RuntimeLaunchGate(false, false, false, 10);
        assertTrue(gate.pending());
        gate.dispatched();
        gate.phaseChanged("ready", 20);
        assertFalse(gate.pending());
        gate.phaseChanged("stopping", 30);
        gate.phaseChanged("stopped", 30);
        assertFalse(gate.pending());
    }

    @Test public void stopCancelsAnUndeliveredOpeningWhileDisplayIsUnavailable() {
        RuntimeLaunchGate gate = new RuntimeLaunchGate(false, false, false, 10);
        gate.phaseChanged("stopping", 20);
        assertFalse(gate.pending());
        gate.phaseChanged("stopped", 20);
        assertFalse(gate.pending());
    }

    @Test public void explicitRetryDuringCleanupSurvivesDelayedOldStopStatus() {
        RuntimeLaunchGate gate = new RuntimeLaunchGate(false, false, false, 10);
        gate.dispatched();
        gate.phaseChanged("stopping", 20);
        gate.request(30);
        gate.phaseChanged("stopping", 20);
        gate.phaseChanged("stopped", 20);
        assertTrue(gate.pending());
        gate.dispatched();
        assertFalse(gate.pending());
    }

    @Test public void newStopCancelsRetryAndOldErrorCannotCancelNewRetry() {
        RuntimeLaunchGate gate = new RuntimeLaunchGate(false, false, false, 10);
        gate.phaseChanged("error", 20);
        assertFalse(gate.pending());
        gate.request(30);
        gate.phaseChanged("error", 20);
        assertTrue(gate.pending());
        gate.phaseChanged("stopping", 40);
        assertFalse(gate.pending());
    }

    @Test public void activityRecreationPreservesOnlyAnUndeliveredRequest() {
        RuntimeLaunchGate opening = new RuntimeLaunchGate(false, false, false, 10);
        RuntimeLaunchGate waiting = new RuntimeLaunchGate(true, false, opening.pending(), opening.requestedAt());
        assertTrue(waiting.pending());
        waiting.dispatched();
        RuntimeLaunchGate restored = new RuntimeLaunchGate(true, false, waiting.pending(), waiting.requestedAt());
        assertFalse(restored.pending());
        restored.phaseChanged("ready", 20);
        assertFalse(restored.pending());
    }

    @Test public void restoredTaskFromHistoryDoesNotRearmAnOldLaunch() {
        assertFalse(new RuntimeLaunchGate(false, true, false, 10).pending());
        assertFalse(new RuntimeLaunchGate(true, true, true, 10).pending());
        RuntimeLaunchGate history = new RuntimeLaunchGate(true, true, false, 10);
        history.request(20);
        assertTrue(history.pending());
    }
}
