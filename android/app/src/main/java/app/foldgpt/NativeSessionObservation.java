package app.foldgpt;

import org.json.JSONObject;

/** Interpret an actual session response without treating transport EOF as cleanup. */
final class NativeSessionObservation {
    enum Outcome { ACTIVE, CLOSED, FAILED }

    static Outcome outcome(JSONObject status) throws Exception {
        if (status.getBoolean("transportFailed") || status.getBoolean("quarantined")
                || status.getBoolean("refusedBeforeFork") || !status.isNull("setupError")
                || !status.isNull("cleanupError")) return Outcome.FAILED;
        if (!status.getBoolean("bootstrapReaped")) return Outcome.ACTIVE;
        // A successful native terminal record and the real zero wait status
        // are both required; reaping alone is not successful cleanup.
        return status.getBoolean("cleanupComplete") && !status.getBoolean("ownerRetained")
                && status.getInt("waitStatus") == 0 ? Outcome.CLOSED : Outcome.FAILED;
    }
}
