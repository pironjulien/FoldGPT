package app.foldgpt;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class ConversationActivityTest {
    private JSONObject event(String type, String turn) throws Exception {
        return new JSONObject().put("type", "event_msg").put("payload", new JSONObject().put("type", type).put("turn_id", turn));
    }
    @Test public void completionRequiresObservedMatchingStart() throws Exception {
        ConversationActivity state = new ConversationActivity();
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("task_complete", "t1")));
        assertEquals(ConversationActivity.Change.STARTED, state.accept("a", event("task_started", "t1")));
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("task_complete", "old")));
        assertEquals(1, state.activeCount());
        assertEquals(ConversationActivity.Change.COMPLETED, state.accept("a", event("task_complete", "t1")));
        assertEquals(0, state.activeCount());
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("task_complete", "t1")));
    }
    @Test public void concurrentConversationsAndDuplicateStarts() throws Exception {
        ConversationActivity state = new ConversationActivity();
        state.accept("a", event("task_started", "t1"));
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("task_started", "t1")));
        state.accept("b", event("task_started", "t2"));
        assertEquals(2, state.activeCount());
        state.accept("a", event("task_complete", "t1"));
        assertEquals(1, state.activeCount());
        assertEquals(ConversationActivity.Change.INTERRUPTED, state.accept("b", event("turn_aborted", "t2")));
        assertEquals(0, state.activeCount());
    }
    @Test public void replacementTurnDoesNotCompleteOnOldEvent() throws Exception {
        ConversationActivity state = new ConversationActivity();
        state.accept("a", event("task_started", "t1"));
        state.accept("a", event("task_started", "t2"));
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("turn_aborted", "t1")));
        assertEquals(ConversationActivity.Change.NONE, state.accept("a", event("task_complete", "")));
        assertEquals(1, state.activeCount());
    }
}
