package app.foldgpt;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import static org.junit.Assert.*;

public class FoldSmsDraftTest {
    private FoldSmsDraft draft(int parts) { return new FoldSmsDraft("test", "+33123456789", "fixture", 1, parts, 100); }

    @Test public void onlyOneConcurrentAttemptCanClaimDraft() throws Exception {
        FoldSmsDraft draft = draft(1);
        AtomicInteger attempts = new AtomicInteger();
        CountDownLatch gate = new CountDownLatch(1);
        Thread[] threads = new Thread[8];
        for (int i = 0; i < threads.length; i++) {
            threads[i] = new Thread(() -> {
                try { gate.await(); } catch (InterruptedException e) { throw new AssertionError(e); }
                if (draft.claim(101)) attempts.incrementAndGet();
            });
            threads[i].start();
        }
        gate.countDown();
        for (Thread thread : threads) thread.join();
        assertEquals(1, attempts.get());
        assertEquals("submitted", draft.state(102));
        assertFalse(draft.claim(103));
    }

    @Test public void expiryPreventsSendAndDoesNotInventDelivery() {
        FoldSmsDraft draft = draft(1);
        assertFalse(draft.claim(100 + FoldSmsDraft.PREPARE_TTL_MS));
        assertEquals("expired", draft.state(100 + FoldSmsDraft.PREPARE_TTL_MS));
        FoldSmsDraft valid = draft(2);
        valid.claim(101);
        valid.callback(0, -1);
        assertEquals("submitted", valid.state(102));
        valid.callback(1, -1);
        assertEquals("sent", valid.state(103));
        assertTrue(valid.callbacksComplete());
    }

    @Test public void callbackFailuresAndAmbiguousBinderOutcomesCannotBeRetried() {
        FoldSmsDraft partial = draft(2);
        partial.claim(101);
        partial.callback(0, -1);
        partial.callback(1, 4);
        assertEquals("partially_sent", partial.state(102));
        assertFalse(partial.claim(103));
        FoldSmsDraft unknown = draft(1);
        unknown.claim(101);
        unknown.uncertain();
        assertEquals("outcome_unknown", unknown.state(102));
        assertFalse(unknown.claim(103));
        unknown.callback(0, 4);
        assertEquals("failed", unknown.state(104));
        unknown.callback(0, -1); // A duplicated callback cannot rewrite the first result.
        assertEquals(Integer.valueOf(4), unknown.results()[0]);
        assertEquals("failed", unknown.state(105));
    }

    @Test public void ignoresCallbacksForUnsentOrWrongPart() {
        FoldSmsDraft draft = draft(1);
        draft.callback(0, -1);
        assertEquals("prepared", draft.state(100));
        assertNull(draft.results()[0]);
        draft.claim(101);
        draft.callback(-1, -1);
        draft.callback(1, -1);
        assertEquals("submitted", draft.state(102));
    }
}
