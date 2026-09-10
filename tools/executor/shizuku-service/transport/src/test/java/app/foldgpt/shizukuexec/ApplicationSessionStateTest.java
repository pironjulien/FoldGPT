package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class ApplicationSessionStateTest {
    private static final int APP_UID = 10412;
    private static final String PREFIX = "{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"";
    private static final String READY = PREFIX + "ready\"}";
    private static final String CLOSED = PREFIX + "closed\",\"cleanupComplete\":true,\"exitCode\":0}";

    @Test public void applicationConstructorDoesNotAdmitShellRootOrDifferentApplication() {
        SessionState state = SessionState.forApplication(APP_UID, APP_UID);
        state.authenticate(APP_UID);
        for (int uid : new int[] {0, 2000, 9999, APP_UID + 1}) {
            assertThrows(SecurityException.class, () -> SessionState.forApplication(uid, APP_UID));
            assertThrows(SecurityException.class, () -> state.authenticate(uid));
        }
        assertThrows(SecurityException.class, () -> SessionState.forApplication(2000, 2000));
        assertThrows(SecurityException.class, () -> new SessionState(APP_UID, APP_UID));
    }
    @Test public void cancellationCannotReleaseAnApplicationOwnerBeforeReportsAndWait() throws Exception {
        SessionState state = SessionState.forApplication(APP_UID, APP_UID);
        state.report(READY); state.cancel();
        assertFalse(state.releasable());
        state.report(CLOSED); assertFalse(state.releasable());
        state.reaped(0); assertTrue(state.releasable());
        JSONObject value = new JSONObject(state.json());
        assertTrue(value.getBoolean("cancelRequested"));
        assertFalse(value.getBoolean("ownerRetained"));
    }
    @Test public void applicationFailureOrQuarantineRetainsOwnershipAfterWait() {
        SessionState failed = SessionState.forApplication(APP_UID, APP_UID);
        failed.report(CLOSED); failed.reaped(0); failed.fail();
        assertFalse(failed.releasable());
        SessionState quarantined = SessionState.forApplication(APP_UID, APP_UID);
        quarantined.report(PREFIX + "quarantined\",\"cleanupComplete\":false}");
        quarantined.reaped(0); assertFalse(quarantined.releasable());
    }
}
