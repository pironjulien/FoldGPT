package app.foldgpt.shizukuexec;

import org.junit.Test;
import static org.junit.Assert.*;

/** Tests the production ownership reducer. No native sandbox is mocked as passing. */
public final class SessionStateTest {
    private static final String PREFIX = "{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"";
    private static final String READY = PREFIX + "ready\"}";
    private static final String CLEAN = PREFIX + "closed\",\"cleanupComplete\":true,\"exitCode\":0}";
    private SessionState state() { return new SessionState(2000, 10412); }

    @Test public void authenticatesActualApplicationUidOnly() {
        SessionState state = state(); state.authenticate(10412);
        for (int uid : new int[] {0, 2000, 10350, 10413}) {
            assertThrows(SecurityException.class, () -> state.authenticate(uid));
        }
        assertThrows(SecurityException.class, () -> new SessionState(0, 10412));
        assertThrows(SecurityException.class, () -> new SessionState(2000, 2000));
    }
    @Test public void requiresIndependentReportAndRealWait() {
        SessionState state = state(); state.report(READY); state.report(CLEAN);
        assertFalse(state.releasable()); state.reaped(0); assertTrue(state.releasable());
        SessionState reverse = state(); reverse.reaped(0); assertFalse(reverse.releasable());
        reverse.report(CLEAN); assertTrue(reverse.releasable());
    }
    @Test public void processDeathAloneNeverReleasesDescendants() {
        for (int status : new int[] {0, 9, 15, 70 << 8}) {
            SessionState state = state(); state.report(READY); state.reaped(status);
            assertFalse(state.releasable());
        }
    }
    @Test public void incorrectExitCannotConfirmCleanup() {
        SessionState state = state(); state.report(CLEAN); state.reaped(9);
        assertFalse(state.releasable());
    }
    @Test public void cancellationRetainsOwnerUntilBothEvidenceSources() {
        SessionState state = state(); state.report(READY); state.cancel();
        assertFalse(state.releasable()); state.report(CLEAN); assertFalse(state.releasable());
        state.reaped(0); assertTrue(state.releasable());
    }
    @Test public void rejectsSpoofedOrCoercedLifecycleReports() {
        for (String line : new String[] {
                CLEAN.replace("true", "\"true\""), CLEAN.replace("true", "1"),
                CLEAN.replace("\"exitCode\":0", "\"exitCode\":0,\"exitCode\":0"),
                CLEAN + "tail", "{\"cleanupComplete\":true}", READY + "\n"}) {
            SessionState state = state();
            assertThrows(IllegalArgumentException.class, () -> state.report(line));
            assertFalse(state.releasable());
        }
    }
    @Test public void rejectsDuplicateAndLateControlFrames() {
        SessionState state = state(); state.report(READY);
        assertThrows(IllegalArgumentException.class, () -> state.report(READY));
        state.report(CLEAN);
        assertThrows(IllegalArgumentException.class, () -> state.report(CLEAN));
        assertThrows(IllegalArgumentException.class, () -> state.report(READY));
    }
    @Test public void quarantineCannotBeConvertedToSuccess() throws Exception {
        SessionState state = state();
        state.report(PREFIX + "quarantined\",\"cleanupComplete\":false}");
        state.reaped(0); assertFalse(state.releasable());
        assertTrue(new org.json.JSONObject(state.json()).getBoolean("quarantined"));
        assertThrows(IllegalArgumentException.class, () -> state.report(CLEAN));
    }
    @Test public void transportFailureRemainsVisibleDespiteCleanNativeExit() {
        SessionState state = state(); state.report(CLEAN); state.reaped(0); state.fail();
        assertFalse(state.releasable());
    }
    @Test public void preForkAdmissionDoesNotInventWaitEvidence() throws Exception {
        SessionState state = state(); state.admissionRefused(); assertTrue(state.releasable());
        org.json.JSONObject result = new org.json.JSONObject(state.json());
        assertFalse(result.getBoolean("bootstrapReaped"));
        assertTrue(result.getBoolean("refusedBeforeFork"));
    }
}
