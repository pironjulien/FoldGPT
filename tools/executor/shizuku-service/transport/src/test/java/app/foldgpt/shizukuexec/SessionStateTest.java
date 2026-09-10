package app.foldgpt.shizukuexec;

import org.junit.Test;
import static org.junit.Assert.*;

/** Tests the production ownership reducer. No native sandbox is mocked as passing. */
public final class SessionStateTest {
    @org.junit.Test public void nativeAdmissionRefusalRequiresBothRecordsAndActualWait() {
        SessionState state = new SessionState(2000, 10412);
        state.report("{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"setup_failed\",\"stage\":\"native_inventory\",\"errorType\":\"NativeAdmissionError\",\"errno\":null,\"source\":\"native-bootstrap.c\",\"line\":0,\"message\":\"runtime-data\"}");
        org.junit.Assert.assertFalse(state.releasable());
        state.report("{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"closed\",\"cleanupComplete\":true,\"exitCode\":70}");
        org.junit.Assert.assertFalse(state.releasable());
        state.reaped(70 << 8);
        org.junit.Assert.assertTrue(state.releasable());
    }
    private static final String PREFIX = "{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"";
    private static final String READY = PREFIX + "ready\"}";
    private static final String CLEAN = PREFIX + "closed\",\"cleanupComplete\":true,\"exitCode\":0}";
    private static final String SETUP = PREFIX + "setup_failed\",\"stage\":\"broker_open\",\"errorType\":\"NotImplementedError\","
        + "\"errno\":null,\"source\":\"private_exec_broker.py\",\"line\":98,\"message\":\"chmod: cannot use dir_fd and follow_symlinks together\"}";
    private static final String CLEANUP = PREFIX + "cleanup_failed\",\"stage\":\"backend_close\",\"errorType\":\"RuntimeError\","
        + "\"errno\":null,\"source\":\"ordinary_uid_files.py\",\"line\":98,\"message\":\"Unknown session identifier\"}";
    private static final String QUARANTINED = PREFIX + "quarantined\",\"cleanupComplete\":false}";
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
    @Test public void setupDiagnosticNeverReplacesActualCleanupAndWait() throws Exception {
        SessionState state = state(); state.report(SETUP);
        JSONObjectAssertions.requireSetup(state.json());
        assertFalse(state.releasable());
        state.reaped(70 << 8); assertFalse(state.releasable());
        state.report(CLEAN.replace(":0}", ":70}")); assertTrue(state.releasable());
        SessionState quarantined = state(); quarantined.report(SETUP);
        quarantined.report(PREFIX + "quarantined\",\"cleanupComplete\":false}");
        quarantined.reaped(70 << 8); assertFalse(quarantined.releasable());
        SessionState denied = state(); denied.report(SETUP.replace("NotImplementedError", "PermissionError").replace("null", "13"));
        assertEquals(13, new org.json.JSONObject(denied.json()).getJSONObject("setupError").getInt("errno"));
        assertFalse(denied.releasable());
    }
    @Test public void setupDiagnosticRejectsSuccessReadyDuplicatesAndLateFrames() {
        SessionState state = state(); state.report(SETUP);
        for (String invalid : new String[] {SETUP, READY, CLEAN})
            assertThrows(IllegalArgumentException.class, () -> state.report(invalid));
        SessionState ready = state(); ready.report(READY);
        assertThrows(IllegalArgumentException.class, () -> ready.report(SETUP));
        SessionState closed = state(); closed.report(CLEAN);
        assertThrows(IllegalArgumentException.class, () -> closed.report(SETUP));
    }
    @Test public void setupDiagnosticRejectsCoercionDuplicateKeysEscapesAndBounds() {
        for (String invalid : new String[] {
            SETUP.replace("broker_open", "arbitrary"), SETUP.replace("null", "\"null\""),
            SETUP.replace("null", "true"), SETUP.replace("null", "4096"), SETUP.replace("null", "01"),
            SETUP.replace("\"line\":98", "\"line\":98,\"line\":98"),
            SETUP.replace("\"line\":98", "\"line\":-1"), SETUP.replace("\"line\":98", "\"line\":1000000"),
            SETUP.replace("chmod: cannot use dir_fd and follow_symlinks together", "x".repeat(161)),
            SETUP.replace("chmod:", "\\nchmod:"), SETUP.replace("private_exec_broker.py", "../../file.py"), SETUP + "tail"
        }) {
            SessionState state = state();
            assertThrows(IllegalArgumentException.class, () -> state.report(invalid));
            assertFalse(state.releasable());
        }
    }
    @Test public void cleanupCauseSurvivesThreeFramesAndCannotReleaseOwnership() throws Exception {
        SessionState state = state();
        for (String frame : new String[] {READY, CLEANUP, QUARANTINED}) state.report(frame);
        state.reaped(0);
        assertFalse(state.releasable());
        org.json.JSONObject result = new org.json.JSONObject(state.json());
        assertTrue(result.isNull("setupError"));
        assertEquals("backend_close", result.getJSONObject("cleanupError").getString("stage"));
        assertEquals("Unknown session identifier", result.getJSONObject("cleanupError").getString("message"));
        assertTrue(result.getBoolean("quarantined"));
        assertTrue(result.getBoolean("ownerRetained"));
        assertFalse(result.getBoolean("cleanupComplete"));
        assertFalse(result.getBoolean("transportFailed"));
    }
    @Test public void setupAndCleanupCausesRemainSeparate() throws Exception {
        SessionState state = state(); state.report(SETUP);
        state.report(CLEANUP.replace("backend_close", "owner_close").replace("null", "13"));
        state.report(QUARANTINED); state.reaped(70 << 8);
        org.json.JSONObject result = new org.json.JSONObject(state.json());
        assertEquals("broker_open", result.getJSONObject("setupError").getString("stage"));
        assertEquals("owner_close", result.getJSONObject("cleanupError").getString("stage"));
        assertEquals(13, result.getJSONObject("cleanupError").getInt("errno"));
        assertFalse(state.releasable());
    }
    @Test public void cleanupDiagnosticRejectsEarlyDuplicateLateAndCleanClose() {
        assertThrows(IllegalArgumentException.class, () -> state().report(CLEANUP));
        SessionState state = state(); state.report(READY); state.report(CLEANUP);
        for (String invalid : new String[] {CLEANUP, READY, SETUP, CLEAN, CLEAN.replace(":0}", ":70}")})
            assertThrows(IllegalArgumentException.class, () -> state.report(invalid));
        state.report(QUARANTINED);
        assertThrows(IllegalArgumentException.class, () -> state.report(CLEANUP));
        SessionState closed = state(); closed.report(CLEAN);
        assertThrows(IllegalArgumentException.class, () -> closed.report(CLEANUP));
        assertFalse(state.releasable());
    }
    @Test public void cleanupDiagnosticRejectsUnboundedOrCoercedFields() {
        for (String invalid : new String[] {
            CLEANUP.replace("backend_close", "factory_construct"), CLEANUP.replace("null", "\"null\""),
            CLEANUP.replace("null", "4096"), CLEANUP.replace("null", "01"),
            CLEANUP.replace("\"line\":98", "\"line\":-1"),
            CLEANUP.replace("\"line\":98", "\"line\":1000000"),
            CLEANUP.replace("\"line\":98", "\"line\":98,\"line\":98"),
            CLEANUP.replace("Unknown session identifier", "x".repeat(161)),
            CLEANUP.replace("Unknown session identifier", "bad\\nmessage"),
            CLEANUP.replace("ordinary_uid_files.py", "../secret.py"), CLEANUP + "tail"
        }) {
            SessionState state = state(); state.report(READY);
            assertThrows(IllegalArgumentException.class, () -> state.report(invalid));
            assertFalse(state.releasable());
        }
    }
    private static final class JSONObjectAssertions {
        static void requireSetup(String raw) throws Exception {
            org.json.JSONObject value = new org.json.JSONObject(raw).getJSONObject("setupError");
            assertEquals("broker_open", value.getString("stage"));
            assertEquals("NotImplementedError", value.getString("errorType"));
            assertTrue(value.isNull("errno")); assertEquals(98, value.getInt("line"));
        }
    }
}
