package app.foldgpt;

import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.PendingConnectorCallback.Offer.*;

public class PendingConnectorCallbackTest {
    private static final String FIRST = "codex://connector/oauth_callback?error=fixture_one";
    private static final String SECOND = "codex://connector/oauth_callback?error=fixture_two";

    @Test public void coldStartWaitsForClientAndDeliversOnce() {
        PendingConnectorCallback pending = new PendingConnectorCallback();
        assertEquals(QUEUED, pending.offer(FIRST));
        assertNull(pending.take(false));
        assertEquals(DUPLICATE, pending.offer(FIRST));
        assertEquals(FIRST, pending.take(true));
        assertNull(pending.take(true));
        pending.completed();
        assertNull(pending.take(true));
        assertEquals(DUPLICATE, pending.offer(FIRST));
    }

    @Test public void competingReturnCannotReplacePendingOrRunningHandoff() {
        PendingConnectorCallback pending = new PendingConnectorCallback();
        assertEquals(QUEUED, pending.offer(FIRST));
        assertEquals(BUSY, pending.offer(SECOND));
        assertEquals(FIRST, pending.take(true));
        assertEquals(BUSY, pending.offer(SECOND));
        pending.completed();
        assertEquals(QUEUED, pending.offer(SECOND));
        assertEquals(SECOND, pending.take(true));
    }

    @Test public void uncertainTransportFailureDoesNotAutomaticallyReplay() {
        PendingConnectorCallback pending = new PendingConnectorCallback();
        pending.offer(FIRST);
        assertEquals(FIRST, pending.take(true));
        // Completion deliberately has no retry flag: timeout may race actual
        // dispatch. A new authorization flow supplies a distinct callback.
        pending.completed();
        assertEquals(DUPLICATE, pending.offer(FIRST));
        assertNull(pending.take(true));
        assertEquals(QUEUED, pending.offer(SECOND));
    }

    @Test public void explicitStopDiscardsPendingCallbackAndInvalidInputCannotOverwriteIt() {
        PendingConnectorCallback pending = new PendingConnectorCallback();
        pending.offer(FIRST);
        try { pending.offer("codex://threads/new?prompt=fixture"); fail(); }
        catch (IllegalArgumentException expected) { }
        assertEquals(DUPLICATE, pending.offer(FIRST));
        assertTrue(pending.cancelPending());
        assertFalse(pending.cancelPending());
        assertNull(pending.take(true));
        assertEquals(QUEUED, pending.offer(SECOND));
    }
}
