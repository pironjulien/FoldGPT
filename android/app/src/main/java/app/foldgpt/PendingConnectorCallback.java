package app.foldgpt;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;

/** One in-memory handoff; never persists OAuth data or automatically retries it. */
public final class PendingConnectorCallback {
    public enum Offer { QUEUED, DUPLICATE, BUSY }
    private String pending;
    private byte[] pendingDigest, consumedDigest;
    private boolean inFlight;

    public synchronized Offer offer(String callback) {
        String validated = FoldConnectorCallback.validate(callback);
        byte[] digest = digest(validated);
        if (Arrays.equals(digest, pendingDigest) || Arrays.equals(digest, consumedDigest)) return Offer.DUPLICATE;
        if (pending != null || inFlight) return Offer.BUSY;
        pending = validated;
        pendingDigest = digest;
        return Offer.QUEUED;
    }

    public synchronized String take(boolean clientReady) {
        if (!clientReady || inFlight || pending == null) return null;
        String result = pending;
        pending = null;
        consumedDigest = pendingDigest;
        pendingDigest = null;
        inFlight = true;
        return result;
    }

    public synchronized void completed() { inFlight = false; }

    public synchronized boolean cancelPending() {
        boolean cancelled = pending != null;
        if (cancelled) consumedDigest = pendingDigest;
        pending = null;
        pendingDigest = null;
        return cancelled;
    }

    private static byte[] digest(String text) {
        try { return MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException("SHA-256 unavailable"); }
    }
}
