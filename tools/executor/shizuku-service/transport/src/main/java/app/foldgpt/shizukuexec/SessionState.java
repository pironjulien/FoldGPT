package app.foldgpt.shizukuexec;

import org.json.JSONObject;

/** Process ownership can be released only after a private report AND waitpid. */
final class SessionState {
    private final int clientUid;
    private boolean ready, terminal, clean, reaped, cancelled, failed, refusedBeforeFork;
    private int expectedExit = -1, waitStatus = -1;

    SessionState(int serviceUid, int clientUid) {
        if (serviceUid != 2000 || clientUid < 10000) throw new SecurityException("Invalid Shizuku identities");
        this.clientUid = clientUid;
    }
    void authenticate(int caller) {
        if (caller != clientUid) throw new SecurityException("Caller is not this executor application");
    }
    synchronized void cancel() { cancelled = true; }
    synchronized void fail() { failed = true; }
    synchronized void admissionRefused() { refusedBeforeFork = true; }
    synchronized void report(String line) {
        // Deliberately canonical, narrow private protocol. No permissive JSON
        // coercions, duplicate keys, partial frames, output matching or logs.
        String prefix = "{\"schema\":\"foldgpt.shizuku.session.v1\",\"event\":\"";
        if (line.equals(prefix + "ready\"}")) {
            if (ready || terminal) throw new IllegalArgumentException("Duplicate or late ready report");
            ready = true;
        } else if (line.equals(prefix + "quarantined\",\"cleanupComplete\":false}")) {
            if (terminal) throw new IllegalArgumentException("Duplicate final report");
            terminal = true;
        } else if (line.equals(prefix + "closed\",\"cleanupComplete\":true,\"exitCode\":0}")
                || line.equals(prefix + "closed\",\"cleanupComplete\":true,\"exitCode\":70}")) {
            if (terminal) throw new IllegalArgumentException("Duplicate final report");
            terminal = clean = true;
            expectedExit = line.endsWith(":70}") ? 70 : 0;
        } else throw new IllegalArgumentException("Malformed private lifecycle report");
    }
    synchronized void reaped(int status) {
        if (reaped) throw new IllegalStateException("Bootstrap was already reaped");
        reaped = true; waitStatus = status;
    }
    synchronized boolean releasable() {
        return refusedBeforeFork || (!failed && terminal && clean && reaped && waitStatus == (expectedExit << 8));
    }
    synchronized String json() {
        try {
            return new JSONObject().put("schema", "foldgpt.shizuku.transport.v1")
                .put("ready", ready).put("cancelRequested", cancelled).put("bootstrapReaped", reaped)
                .put("cleanupComplete", releasable()).put("ownerRetained", !releasable())
                .put("refusedBeforeFork", refusedBeforeFork)
                .put("transportFailed", failed).put("waitStatus", waitStatus).toString();
        } catch (Exception error) { throw new IllegalStateException(error); }
    }
}
