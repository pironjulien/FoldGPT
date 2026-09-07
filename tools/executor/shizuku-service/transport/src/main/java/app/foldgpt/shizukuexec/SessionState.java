package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Process ownership can be released only after a private report AND waitpid. */
final class SessionState {
    private final int clientUid;
    private boolean ready, terminal, clean, reaped, cancelled, failed, refusedBeforeFork;
    private int expectedExit = -1, waitStatus = -1;
    private JSONObject setupError;
    private static final Pattern SETUP_ERROR = Pattern.compile(
        "\\{\"schema\":\"foldgpt\\.shizuku\\.session\\.v1\",\"event\":\"setup_failed\",\"stage\":\""
        + "(imports|control|deployment|native_inventory|broker_open|workspace_claim|factory_import|factory_construct|workspace_verify|server_construct)"
        + "\",\"errorType\":\"([A-Za-z_][A-Za-z0-9_]{0,63})\",\"errno\":(null|[1-9][0-9]{0,3}),"
        + "\"source\":\"([A-Za-z0-9_.-]{1,64})\",\"line\":(0|[1-9][0-9]{0,5}),"
        + "\"message\":\"([\\x20-\\x21\\x23-\\x5b\\x5d-\\x7e]{0,160})\"\\}");

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
        Matcher diagnostic = SETUP_ERROR.matcher(line);
        if (line.length() <= 512 && diagnostic.matches()) {
            if (ready || terminal || setupError != null) throw new IllegalArgumentException("Duplicate or late setup failure");
            String number = diagnostic.group(3);
            if (!number.equals("null") && Integer.parseInt(number) > 4095) throw new IllegalArgumentException("Invalid setup errno");
            try {
                setupError = new JSONObject().put("stage", diagnostic.group(1)).put("errorType", diagnostic.group(2))
                    .put("errno", number.equals("null") ? JSONObject.NULL : Integer.parseInt(number))
                    .put("source", diagnostic.group(4)).put("line", Integer.parseInt(diagnostic.group(5)))
                    .put("message", diagnostic.group(6));
            } catch (org.json.JSONException error) { throw new IllegalArgumentException("Invalid setup failure", error); }
        } else if (line.equals(prefix + "ready\"}")) {
            if (ready || terminal || setupError != null) throw new IllegalArgumentException("Duplicate or late ready report");
            ready = true;
        } else if (line.equals(prefix + "quarantined\",\"cleanupComplete\":false}")) {
            if (terminal) throw new IllegalArgumentException("Duplicate final report");
            terminal = true;
        } else if (line.equals(prefix + "closed\",\"cleanupComplete\":true,\"exitCode\":0}")
                || line.equals(prefix + "closed\",\"cleanupComplete\":true,\"exitCode\":70}")) {
            if (terminal) throw new IllegalArgumentException("Duplicate final report");
            if (setupError != null && !line.endsWith(":70}")) throw new IllegalArgumentException("Setup failure cannot report success");
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
                .put("quarantined", terminal && !clean)
                .put("refusedBeforeFork", refusedBeforeFork)
                .put("setupError", setupError == null ? JSONObject.NULL : setupError)
                .put("transportFailed", failed).put("waitStatus", waitStatus).toString();
        } catch (Exception error) { throw new IllegalStateException(error); }
    }
}
