package app.foldgpt;

/** In-memory, one-use send record. A lost/unknown token is never reconstructed or resent. */
final class FoldSmsDraft {
    static final long PREPARE_TTL_MS = 30 * 60 * 1000L;
    final String id, recipient, body;
    final int subscriptionId, parts;
    final long created;
    private boolean attempted;
    private boolean uncertain;
    private Integer[] resultCodes;

    FoldSmsDraft(String id, String recipient, String body, int subscriptionId, int parts, long created) {
        this.id = id; this.recipient = recipient; this.body = body;
        this.subscriptionId = subscriptionId; this.parts = parts; this.created = created;
        this.resultCodes = new Integer[parts];
    }

    synchronized boolean claim(long now) {
        if (attempted || now < created || now - created >= PREPARE_TTL_MS) return false;
        attempted = true;
        return true;
    }

    synchronized void callback(int part, int code) {
        if (attempted && part >= 0 && part < parts && resultCodes[part] == null) resultCodes[part] = code;
    }

    synchronized void uncertain() { if (attempted) uncertain = true; }

    synchronized boolean callbacksComplete() {
        for (Integer code : resultCodes) if (code == null) return false;
        return true;
    }

    synchronized String state(long now) {
        if (!attempted) return now - created >= PREPARE_TTL_MS ? "expired" : "prepared";
        int sent = 0, failed = 0;
        for (Integer code : resultCodes) {
            if (code != null) { if (code == -1) sent++; else failed++; }
        }
        if (sent + failed < parts) return uncertain ? "outcome_unknown" : "submitted";
        return failed == 0 ? "sent" : sent == 0 ? "failed" : "partially_sent";
    }

    synchronized Integer[] results() { return resultCodes.clone(); }
    synchronized boolean attempted() { return attempted; }
}
