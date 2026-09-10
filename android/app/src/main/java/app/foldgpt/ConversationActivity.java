package app.foldgpt;

import java.util.HashMap;
import java.util.Map;
import org.json.JSONObject;

/** Only paired, real engine events change the live response state. */
public final class ConversationActivity {
    public enum Change { NONE, STARTED, COMPLETED, INTERRUPTED }
    private final Map<String, String> active = new HashMap<>();
    public int activeCount() { return active.size(); }
    public Change accept(String thread, JSONObject record) {
        if (!"event_msg".equals(record.optString("type"))) return Change.NONE;
        JSONObject event = record.optJSONObject("payload");
        if (event == null) return Change.NONE;
        String type = event.optString("type"), turn = event.optString("turn_id");
        if ("task_started".equals(type) && !turn.isEmpty()) {
            if (turn.equals(active.put(thread, turn))) return Change.NONE;
            return Change.STARTED;
        }
        String running = active.get(thread);
        if (running == null || (!turn.isEmpty() && !running.equals(turn))) return Change.NONE;
        if ("task_complete".equals(type)) {
            if (turn.isEmpty()) return Change.NONE;
            active.remove(thread);
            return Change.COMPLETED;
        }
        if ("turn_aborted".equals(type)) {
            active.remove(thread);
            return Change.INTERRUPTED;
        }
        return Change.NONE;
    }
}
