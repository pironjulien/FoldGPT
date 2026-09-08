package app.foldgpt;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

/** Lifecycle interpretation only; these tests do not certify a native process. */
public final class NativeSessionObservationTest {
    private JSONObject active() throws Exception {
        return new JSONObject().put("transportFailed", false).put("quarantined", false)
                .put("refusedBeforeFork", false).put("setupError", JSONObject.NULL)
                .put("bootstrapReaped", false).put("cleanupComplete", false)
                .put("ownerRetained", true).put("waitStatus", -1);
    }
    private JSONObject closed() throws Exception {
        return active().put("bootstrapReaped", true).put("cleanupComplete", true)
                .put("ownerRetained", false).put("waitStatus", 0);
    }
    @Test public void cleanZeroExitAfterEofIsClosed() throws Exception {
        assertEquals(NativeSessionObservation.Outcome.CLOSED, NativeSessionObservation.outcome(closed()));
    }
    @Test public void reapingWithoutTerminalCleanupIsFailure() throws Exception {
        JSONObject status = active().put("bootstrapReaped", true).put("waitStatus", 0);
        assertEquals(NativeSessionObservation.Outcome.FAILED, NativeSessionObservation.outcome(status));
    }
    @Test public void cleanNonzeroExitIsFailure() throws Exception {
        assertEquals(NativeSessionObservation.Outcome.FAILED,
                NativeSessionObservation.outcome(closed().put("waitStatus", 70 << 8)));
    }
    @Test public void nativeFailureEvidenceCannotBeErasedByZeroWait() throws Exception {
        for (String flag : new String[] {"transportFailed", "quarantined", "refusedBeforeFork", "ownerRetained"}) {
            assertEquals(flag, NativeSessionObservation.Outcome.FAILED,
                    NativeSessionObservation.outcome(closed().put(flag, true)));
        }
        assertEquals(NativeSessionObservation.Outcome.FAILED,
                NativeSessionObservation.outcome(closed().put("setupError", new JSONObject().put("stage", "native_inventory"))));
    }
    @Test public void unReapedSessionRemainsActive() throws Exception {
        assertEquals(NativeSessionObservation.Outcome.ACTIVE, NativeSessionObservation.outcome(active()));
    }
}
