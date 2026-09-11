package app.foldgpt;

import org.json.JSONObject;

/** Durable user intent and bounded crash recovery, independent of display focus.
 * Times use Android elapsed realtime, so a wall-clock correction cannot postpone
 * recovery. A new boot is recognised by its identifier when the state is loaded.
 */
public final class RuntimeRecoveryPolicy {
    public static final long STABLE_WINDOW_MS = 90_000; // The actual client startup budget.
    private static final long FIRST_RETRY_MS = 1_618;
    private final String bootId;
    private boolean wanted;
    private int failures;
    private String state = "stopped";
    private long readyAt = -1, retryAt = -1, recoveryUntil = -1;

    public RuntimeRecoveryPolicy(String bootId) {
        if (bootId == null || bootId.isEmpty()) throw new IllegalArgumentException("Missing boot identity");
        this.bootId = bootId;
    }

    public static RuntimeRecoveryPolicy restore(JSONObject value, String bootId) throws Exception {
        RuntimeRecoveryPolicy policy = new RuntimeRecoveryPolicy(bootId);
        if (!"foldgpt.runtime.intent.v1".equals(value.getString("schema")))
            throw new IllegalArgumentException("Unknown runtime intent schema");
        policy.wanted = value.getBoolean("wanted");
        policy.failures = value.getInt("failures");
        policy.state = value.getString("state");
        policy.readyAt = value.getLong("readyAt");
        policy.retryAt = value.getLong("retryAt");
        policy.recoveryUntil = value.getLong("recoveryUntil");
        if (policy.failures < 0
                || !java.util.Set.of("stopped", "starting", "ready", "retry", "suspended").contains(policy.state)
                || policy.readyAt < -1 || policy.retryAt < -1 || policy.recoveryUntil < -1
                || (!policy.wanted && !"stopped".equals(policy.state))
                || ("ready".equals(policy.state) && policy.readyAt < 0)
                || ("retry".equals(policy.state) && policy.retryAt < 0))
            throw new IllegalArgumentException("Invalid runtime intent state");
        if (!bootId.equals(value.getString("bootId"))) {
            // There is no boot receiver: this only affects an Android service
            // recreation or a subsequent explicit app launch.
            policy.readyAt = -1;
            policy.recoveryUntil = -1;
            if (policy.wanted && !"suspended".equals(policy.state)) {
                policy.state = "retry";
                policy.retryAt = 0;
            }
        }
        return policy;
    }

    public JSONObject snapshot() throws Exception {
        return new JSONObject().put("schema", "foldgpt.runtime.intent.v1").put("bootId", bootId)
                .put("wanted", wanted).put("failures", failures).put("state", state)
                .put("readyAt", readyAt).put("retryAt", retryAt).put("recoveryUntil", recoveryUntil);
    }

    public boolean desiredRunning() { return wanted; }
    public boolean permitsRecovery() { return wanted && !"suspended".equals(state); }
    public int consecutiveFailures() { return failures; }

    /** A real launch/retry request is the only authority to clear suspension. */
    public void userStarted(long now, boolean sessionActive) {
        wanted = true;
        failures = 0;
        recoveryUntil = -1;
        if (!sessionActive) { state = "retry"; retryAt = now; readyAt = -1; }
    }

    /** Must be persisted before cancelling timers or starting cleanup. */
    public void userStopped() {
        wanted = false;
        failures = 0;
        state = "stopped";
        readyAt = retryAt = recoveryUntil = -1;
    }

    public void launching() {
        if (!permitsRecovery()) throw new IllegalStateException("Runtime launch has no user authority");
        state = "starting";
        readyAt = retryAt = -1;
    }

    public void ready(long now) {
        if (permitsRecovery() && !"ready".equals(state)) { state = "ready"; readyAt = now; }
    }

    public boolean stable(long now) {
        if (!"ready".equals(state) || readyAt < 0 || now - readyAt < STABLE_WINDOW_MS || failures == 0) return false;
        failures = 0;
        recoveryUntil = -1;
        return true;
    }

    /** Consumes a retry once per failed owner, never per observer/poll callback. */
    public long failed(long now) {
        if (!permitsRecovery()) return -1;
        stable(now);
        readyAt = -1;
        // One crash burst shares the existing 90-second client startup budget.
        // A fresh process cannot reset that budget and enter an endless loop.
        if (recoveryUntil < 0) recoveryUntil = Math.addExact(now, STABLE_WINDOW_MS);
        if (now >= recoveryUntil) return suspend();
        failures = Math.addExact(failures, 1);
        long delay = FIRST_RETRY_MS;
        for (int i = 1; i < failures && delay < STABLE_WINDOW_MS; i++)
            delay = Math.min(STABLE_WINDOW_MS, Math.round(delay * 1.618));
        if (delay >= recoveryUntil - now) return suspend();
        state = "retry";
        retryAt = Math.addExact(now, delay);
        return delay;
    }

    /** Null START_STICKY restarts carry no actions, callback URI, or model turn. */
    public long serviceRecreated(long now) {
        if (!permitsRecovery()) return -1;
        if ("starting".equals(state) || "ready".equals(state)) return failed(now);
        if (recoveryUntil >= 0 && now >= recoveryUntil) return suspend();
        if (!"retry".equals(state)) return -1;
        return Math.max(0, retryAt - now);
    }

    private long suspend() { state = "suspended"; retryAt = -1; return -1; }
}
