package app.foldgpt;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.RuntimeShutdownGate.Action.*;

public final class RuntimeRecoveryPolicyTest {
    private static final String BOOT = "test-boot-one";
    private static RuntimeRecoveryPolicy started() {
        RuntimeRecoveryPolicy policy = new RuntimeRecoveryPolicy(BOOT);
        policy.userStarted(100, false);
        policy.launching();
        return policy;
    }
    private static RuntimeRecoveryPolicy reload(RuntimeRecoveryPolicy policy) throws Exception {
        // Serialise/parse independently, as after loss of every Java field.
        return RuntimeRecoveryPolicy.restore(new JSONObject(policy.snapshot().toString()), BOOT);
    }

    @Test public void absentIntentNeverAuthorisesStickyLaunch() {
        RuntimeRecoveryPolicy policy = new RuntimeRecoveryPolicy(BOOT);
        assertFalse(policy.desiredRunning());
        assertEquals(-1, policy.serviceRecreated(123));
        assertThrows(IllegalStateException.class, policy::launching);
    }

    @Test public void explicitLaunchSurvivesDeathBeforeWorkerWasCreated() throws Exception {
        RuntimeRecoveryPolicy policy = new RuntimeRecoveryPolicy(BOOT);
        policy.userStarted(100, false);
        RuntimeRecoveryPolicy recreated = reload(policy);
        assertEquals(0, recreated.serviceRecreated(110));
        assertEquals(0, recreated.consecutiveFailures());
        recreated.launching();
    }

    @Test public void processDeathDuringStartupConsumesOneRetry() throws Exception {
        RuntimeRecoveryPolicy recreated = reload(started());
        long delay = recreated.serviceRecreated(500);
        assertTrue(delay > 0);
        assertEquals(1, recreated.consecutiveFailures());
        assertEquals(delay - 1, recreated.serviceRecreated(501));
        assertEquals(1, recreated.consecutiveFailures());
    }

    @Test public void processDeathAfterReadyRestartsWithoutDisplayEvent() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.ready(200);
        RuntimeRecoveryPolicy recreated = reload(policy);
        long delay = recreated.serviceRecreated(1000);
        assertTrue(recreated.desiredRunning());
        assertTrue(delay > 0);
        assertEquals(0, recreated.serviceRecreated(1000 + delay));
        recreated.launching();
    }

    @Test public void stoppedStateSurvivesProcessAndAndroidBootChanges() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.userStopped();
        assertEquals(-1, reload(policy).serviceRecreated(500));
        RuntimeRecoveryPolicy reboot = RuntimeRecoveryPolicy.restore(policy.snapshot(), "next-boot");
        assertFalse(reboot.desiredRunning());
        assertEquals(-1, reboot.serviceRecreated(1));
    }

    @Test public void stopCancelsPersistedRetryBeforeAndAfterItsDeadline() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        long delay = policy.failed(300);
        policy.userStopped();
        assertEquals(-1, policy.serviceRecreated(300 + delay));
        assertEquals(-1, reload(policy).serviceRecreated(300 + delay + 1));
        assertFalse(policy.permitsRecovery());
    }

    @Test public void recreatingAnAlreadyScheduledRetryDoesNotConsumeAnother() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        long delay = policy.failed(1000);
        RuntimeRecoveryPolicy recreated = reload(policy);
        assertEquals(delay - 10, recreated.serviceRecreated(1010));
        assertEquals(1, recreated.consecutiveFailures());
        assertEquals(0, recreated.serviceRecreated(1000 + delay));
    }
    @Test public void deadOwnerDuringCleanupAndVmRecreationConsumeOnlyOneRetry() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.ready(200);
        long delay = policy.failed(1000); // The Linux child exits first.
        assertEquals(delay - 50, policy.serviceRecreated(1050)); // The owner wait arrives during cleanup.
        RuntimeRecoveryPolicy recreated = reload(policy);
        assertEquals(delay - 500, recreated.serviceRecreated(1500)); // Android recreated the retired VM.
        assertEquals(1, recreated.consecutiveFailures());
        assertEquals(-1, reload(recreated).serviceRecreated(1000 + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
        assertTrue(recreated.desiredRunning());
    }
    @Test public void stoppedOwnerDeathCannotRestartTheRetiredVm() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.failed(1000);
        policy.userStopped();
        assertEquals(-1, policy.serviceRecreated(1100));
        assertEquals(-1, reload(policy).serviceRecreated(1200));
        assertFalse(reload(policy).desiredRunning());
    }

    @Test public void repeatedFastCrashesShareTheActualStartupTimeBudget() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        long now = 500, previousDelay = 0;
        int failures = 0;
        while (policy.permitsRecovery()) {
            long delay = policy.failed(now);
            if (delay < 0) break;
            assertTrue(delay > previousDelay);
            previousDelay = delay;
            now += delay;
            assertTrue(now < 500 + RuntimeRecoveryPolicy.STABLE_WINDOW_MS);
            policy = reload(policy);
            assertEquals(0, policy.serviceRecreated(now));
            policy.launching();
            failures++;
        }
        assertTrue(failures > 1);
        assertTrue(policy.desiredRunning());
        assertFalse(policy.permitsRecovery());
        assertEquals(-1, reload(policy).serviceRecreated(now + 1));
    }

    @Test public void startupThatUsesRecoveryBudgetCannotStartAnotherLoop() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        long retryDelay = policy.failed(1000);
        policy.launching();
        assertEquals(-1, policy.failed(1000 + retryDelay + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
        assertFalse(reload(policy).permitsRecovery());
    }

    @Test public void delayedAndroidRecreationCannotExtendRecoveryBudget() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.failed(1000);
        assertEquals(-1, reload(policy).serviceRecreated(1000 + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
    }

    @Test public void briefReadinessDoesNotResetCrashBurst() {
        RuntimeRecoveryPolicy policy = started();
        long delay = policy.failed(1000);
        policy.launching();
        policy.ready(1000 + delay);
        assertFalse(policy.stable(1000 + delay + 1));
        assertTrue(policy.failed(1000 + delay + 2) > delay);
        assertEquals(2, policy.consecutiveFailures());
    }

    @Test public void stableReadinessResetsBudgetAcrossProcessDeath() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        long delay = policy.failed(1000);
        policy.launching();
        policy.ready(1000 + delay);
        policy = reload(policy);
        assertEquals(delay, policy.serviceRecreated(1000 + delay + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
        assertEquals(1, policy.consecutiveFailures());
    }

    @Test public void duplicateReadyDoesNotMoveStabilityWindow() {
        RuntimeRecoveryPolicy policy = started();
        policy.failed(1000);
        policy.launching();
        policy.ready(2000);
        policy.ready(3000);
        assertTrue(policy.stable(2000 + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
        assertEquals(0, policy.consecutiveFailures());
    }

    @Test public void explicitRetryClearsSuspension() {
        RuntimeRecoveryPolicy policy = started();
        policy.failed(1000);
        assertEquals(-1, policy.serviceRecreated(1000 + RuntimeRecoveryPolicy.STABLE_WINDOW_MS));
        policy.userStarted(100_000, false);
        assertTrue(policy.permitsRecovery());
        assertEquals(0, policy.serviceRecreated(100_000));
        assertEquals(0, policy.consecutiveFailures());
    }

    @Test public void rebootDoesNotReusePreviousElapsedRealtime() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        policy.ready(10_000_000);
        policy.failed(10_001_000);
        policy = RuntimeRecoveryPolicy.restore(policy.snapshot(), "next-boot");
        assertEquals(0, policy.serviceRecreated(1));
    }

    @Test public void malformedStoredIntentIsRejected() throws Exception {
        JSONObject value = started().snapshot();
        value.put("state", "anything");
        assertThrows(IllegalArgumentException.class, () -> RuntimeRecoveryPolicy.restore(value, BOOT));
        value.put("state", "starting").put("wanted", false);
        assertThrows(IllegalArgumentException.class, () -> RuntimeRecoveryPolicy.restore(value, BOOT));
    }

    @Test public void automaticRetryStillRequiresBothCleanupReceipts() {
        RuntimeRecoveryPolicy policy = started();
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        assertTrue(policy.failed(1000) > 0);
        long generation = gate.begin(true);
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(WAIT, gate.workspaceExited(generation));
        assertEquals(RESTART, gate.nativeCompleted(generation, null));
    }

    @Test public void uncertainNativeCleanupCannotReleaseAutomaticRetry() {
        RuntimeRecoveryPolicy policy = started();
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        policy.failed(1000);
        long generation = gate.begin(false);
        assertEquals(WAIT, gate.requestRestart());
        assertEquals(WAIT, gate.nativeCompleted(generation, new IllegalStateException("owner retained")));
        assertEquals(WAIT, gate.requestRestart());
    }

    @Test public void explicitStopWinsWhileBothCleanupCallbacksAreQueued() throws Exception {
        RuntimeRecoveryPolicy policy = started();
        RuntimeShutdownGate gate = new RuntimeShutdownGate();
        policy.failed(1000);
        long generation = gate.begin(true);
        gate.requestRestart();
        policy.userStopped();
        assertEquals(WAIT, gate.cancelRestart());
        assertEquals(WAIT, gate.nativeCompleted(generation, null));
        assertEquals(STOP_SERVICE, gate.workspaceExited(generation));
        assertEquals(-1, reload(policy).serviceRecreated(5000));
    }
}
