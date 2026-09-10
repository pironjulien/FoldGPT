package app.foldgpt;

import android.Manifest;
import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Telephony;
import android.telephony.SmsManager;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Android SMS provider access. RCS, Google Messages archives and organization belong to its UI. */
public final class FoldSmsTools {
    private static final int MAX_DRAFTS = 32;
    private static final long RECORD_TTL_MS = 24 * 60 * 60 * 1000L;
    private static final Map<String, FoldSmsDraft> DRAFTS = new LinkedHashMap<>();
    private static final Map<String, BroadcastReceiver> RECEIVERS = new LinkedHashMap<>();
    private static final String[] PROJECTION = {"_id", "thread_id", "address", "date", "date_sent", "type", "read", "body", "sub_id"};
    private FoldSmsTools() { }

    public static JSONObject status(Context context) {
        try {
            JSONObject out = ok().put("scope", "android_sms_provider")
                    .put("readPermission", permitted(context, Manifest.permission.READ_SMS))
                    .put("sendPermission", permitted(context, Manifest.permission.SEND_SMS))
                    .put("phoneStatePermission", permitted(context, Manifest.permission.READ_PHONE_STATE))
                    .put("defaultSmsPackage", nullable(Telephony.Sms.getDefaultSmsPackage(context)))
                    .put("defaultSubscriptionId", SubscriptionManager.getDefaultSmsSubscriptionId())
                    .put("nativeOrganization", false).put("archiveMetadata", false).put("rcs", false)
                    .put("scopeNote", "SMS provider rows only. Archived SMS may be returned, but archive membership and RCS are not exposed. Use the messaging application's visible UI for archives, RCS and organization.")
                    .put("sendSemantics", "Explicitly requested sends only; prepare an immutable draft before sms_send. Sent is not a delivery receipt. Never retry an unknown or partially sent outcome.");
            JSONArray subscriptions = new JSONArray();
            if (permitted(context, Manifest.permission.READ_PHONE_STATE)) {
                SubscriptionManager manager = context.getSystemService(SubscriptionManager.class);
                List<SubscriptionInfo> active = manager == null ? null : manager.getActiveSubscriptionInfoList();
                if (active != null) for (SubscriptionInfo info : active) {
                    subscriptions.put(new JSONObject().put("subscriptionId", info.getSubscriptionId())
                            .put("simSlotIndex", info.getSimSlotIndex()));
                }
            }
            return out.put("activeSubscriptions", subscriptions);
        } catch (SecurityException error) { return failure("permission_denied", "Android denied SMS capability metadata access."); }
        catch (Exception error) { return failure("status_unavailable", "Android SMS capability metadata could not be read."); }
    }

    /** Call off the UI thread. Arguments and message bodies must never be logged by the transport. */
    public static JSONObject execute(Context context, String operation, JSONObject args) {
        try {
            if (args == null) throw FoldSmsRequest.invalid();
            Context app = context.getApplicationContext();
            switch (operation) {
                case "sms_search": return query(app, FoldSmsRequest.search(args, false));
                case "sms_read": return query(app, FoldSmsRequest.search(args, true));
                case "sms_prepare": return prepare(app, args);
                case "sms_send": return send(app, args);
                case "sms_send_status": return sendStatus(app, args);
                case "sms_status": FoldSmsRequest.keys(args); return status(app);
                default: return failure("unsupported_operation", "Unsupported SMS operation; provider modification is not supported.");
            }
        } catch (SecurityException error) {
            return failure("permission_denied", "Android denied the SMS operation. Enable only the corresponding permission in Android settings.");
        } catch (IllegalArgumentException error) {
            return failure("invalid_arguments", "Invalid SMS arguments. Use a bounded search filter or threadId, literal search text, and valid numeric identifiers.");
        } catch (Exception error) {
            return failure("sms_operation_failed", "Android could not complete this SMS operation. No private exception details are returned.");
        }
    }

    private static JSONObject query(Context context, FoldSmsRequest request) throws JSONException {
        if (!permitted(context, Manifest.permission.READ_SMS)) return missing("android.permission.READ_SMS");
        // Query limit is supplied through Android's provider API; also stop cursor iteration
        // ourselves because providers may ignore optional query arguments. Id order gives
        // stable, strict keyset pagination even when several messages share a timestamp.
        android.os.Bundle query = new android.os.Bundle();
        query.putString(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION, request.selection);
        query.putStringArray(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, request.selectionArgs);
        query.putString(android.content.ContentResolver.QUERY_ARG_SQL_SORT_ORDER, "_id DESC");
        query.putInt(android.content.ContentResolver.QUERY_ARG_LIMIT, request.limit + 1);
        JSONArray messages = new JSONArray();
        boolean more = false;
        long lastId = -1;
        try (Cursor cursor = context.getContentResolver().query(Telephony.Sms.CONTENT_URI, PROJECTION, query, null)) {
            if (cursor == null) return failure("provider_unavailable", "Android's SMS provider returned no cursor.");
            while (cursor.moveToNext()) {
                if (messages.length() >= request.limit) { more = true; break; }
                lastId = cursor.getLong(0);
                messages.put(new JSONObject().put("id", lastId).put("threadId", cursor.getLong(1))
                        .put("address", nullable(cursor.getString(2))).put("date", cursor.getLong(3))
                        .put("dateSent", cursor.getLong(4)).put("type", cursor.getInt(5))
                        .put("read", cursor.getInt(6) != 0).put("body", nullable(cursor.getString(7)))
                        .put("subscriptionId", cursor.isNull(8) ? JSONObject.NULL : cursor.getInt(8)));
            }
        }
        return ok().put("messages", messages).put("hasMore", more)
                .put("nextBeforeId", more && lastId > 0 ? lastId : JSONObject.NULL)
                .put("sort", "id_desc").put("scope", "sms_only_archive_membership_unknown")
                .put("mutatedReadState", false);
    }

    private static JSONObject prepare(Context context, JSONObject args) throws JSONException {
        FoldSmsRequest.keys(args, "recipient", "body", "subscriptionId");
        String recipient = FoldSmsRequest.recipient(args), body = FoldSmsRequest.body(args);
        int defaultId = SubscriptionManager.getDefaultSmsSubscriptionId();
        int selected = args.has("subscriptionId")
                ? (int) FoldSmsRequest.integer(args, "subscriptionId", 0, Integer.MAX_VALUE - 1L) : defaultId;
        if (!SubscriptionManager.isValidSubscriptionId(selected))
            return failure("subscription_selection_required", "Choose an active SMS subscription explicitly or set Android's default SMS SIM.");
        // An explicit non-default subscription must be proven active. READ_PHONE_STATE
        // is optional otherwise; neither status nor drafts read phone numbers or SIM identities.
        if (selected != defaultId || permitted(context, Manifest.permission.READ_PHONE_STATE)) {
            if (!permitted(context, Manifest.permission.READ_PHONE_STATE)) return missing("android.permission.READ_PHONE_STATE");
            SubscriptionManager manager = context.getSystemService(SubscriptionManager.class);
            if (manager == null || manager.getActiveSubscriptionInfo(selected) == null)
                return failure("inactive_subscription", "The selected SMS subscription is not active.");
        }
        SmsManager manager = managerFor(context, selected);
        if (manager == null) return failure("telephony_unavailable", "This device has no SMS manager.");
        int parts = manager.divideMessage(body).size();
        if (parts < 1 || parts > 30) return failure("message_too_large", "The message exceeds the supported multipart SMS limit.");
        FoldSmsDraft draft = new FoldSmsDraft(UUID.randomUUID().toString(), recipient, body,
                selected, parts, SystemClock.elapsedRealtime());
        synchronized (DRAFTS) {
            prune(context);
            if (DRAFTS.size() >= MAX_DRAFTS) return failure("draft_capacity", "The bounded SMS draft store is full. Existing send records are retained to prevent retries.");
            DRAFTS.put(draft.id, draft);
        }
        // Returning the exact destination/body here is intentional: this is the reviewable
        // proposal. Status endpoints use masked metadata and do not repeat message content.
        return record(draft).put("recipient", recipient).put("body", body)
                .put("expiresAfterMs", FoldSmsDraft.PREPARE_TTL_MS)
                .put("requiresExplicitUserSendRequest", true).put("sent", false);
    }

    private static JSONObject send(Context context, JSONObject args) throws JSONException {
        FoldSmsRequest.keys(args, "draftId");
        String id = FoldSmsRequest.string(args, "draftId", 64, false);
        FoldSmsDraft draft;
        synchronized (DRAFTS) { prune(context); draft = DRAFTS.get(id); }
        if (draft == null) return unknownDraft();
        // No permission request or SMS-role takeover is ever initiated by a model call.
        if (!permitted(context, Manifest.permission.SEND_SMS)) return missing("android.permission.SEND_SMS");
        synchronized (draft) {
            if (draft.attempted()) return record(draft).put("duplicateSuppressed", true);
            if (!"prepared".equals(draft.state(SystemClock.elapsedRealtime()))) return record(draft);
            int currentDefault = SubscriptionManager.getDefaultSmsSubscriptionId();
            if (permitted(context, Manifest.permission.READ_PHONE_STATE)) {
                SubscriptionManager subscriptions = context.getSystemService(SubscriptionManager.class);
                if (subscriptions == null || subscriptions.getActiveSubscriptionInfo(draft.subscriptionId) == null)
                    return failure("inactive_subscription", "The prepared SMS subscription is no longer active. Prepare a new draft after selecting a SIM.");
            } else if (currentDefault != draft.subscriptionId) {
                return failure("subscription_changed", "The default SMS SIM changed. Prepare a new draft or explicitly verify the chosen subscription.");
            }
            SmsManager manager = managerFor(context, draft.subscriptionId);
            if (manager == null) return failure("telephony_unavailable", "This device has no SMS manager.");
            ArrayList<String> parts = manager.divideMessage(draft.body);
            if (parts.size() != draft.parts) return failure("encoding_changed", "SMS segmentation changed. Prepare and review a new draft.");
            String action = context.getPackageName() + ".SMS_SENT." + UUID.randomUUID();
            BroadcastReceiver receiver = new BroadcastReceiver() {
                @Override public void onReceive(Context receivedContext, Intent intent) {
                    if (!action.equals(intent.getAction())) return;
                    int part = intent.getIntExtra("part", -1);
                    draft.callback(part, getResultCode());
                    if (draft.callbacksComplete()) unregister(context, draft.id);
                }
            };
            // The PendingIntents are app-created and package-bound. The receiver is private;
            // no exported SMS receiver, default-handler role, or incoming-message interception.
            if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(receiver, new IntentFilter(action), Context.RECEIVER_NOT_EXPORTED);
            else context.registerReceiver(receiver, new IntentFilter(action));
            ArrayList<PendingIntent> sent = new ArrayList<>();
            try {
                for (int part = 0; part < parts.size(); part++) {
                    Intent callback = new Intent(action).setPackage(context.getPackageName()).putExtra("part", part);
                    sent.add(PendingIntent.getBroadcast(context, part, callback,
                            PendingIntent.FLAG_ONE_SHOT | PendingIntent.FLAG_IMMUTABLE));
                }
                synchronized (RECEIVERS) { RECEIVERS.put(draft.id, receiver); }
                if (!draft.claim(SystemClock.elapsedRealtime())) { unregister(context, draft.id); return record(draft); }
                // Claim precedes the binder call. Any thrown exception is an unknown outcome,
                // never a justification to retry and potentially send a duplicate paid SMS.
                try {
                    manager.sendMultipartTextMessage(draft.recipient, null, parts, sent, null);
                } catch (Exception error) {
                    draft.uncertain();
                }
            } catch (RuntimeException error) {
                for (PendingIntent pending : sent) pending.cancel();
                try { context.unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) { }
                synchronized (RECEIVERS) { RECEIVERS.remove(draft.id); }
                throw error;
            }
            return record(draft);
        }
    }

    private static JSONObject sendStatus(Context context, JSONObject args) throws JSONException {
        FoldSmsRequest.keys(args, "draftId");
        String id = FoldSmsRequest.string(args, "draftId", 64, false);
        synchronized (DRAFTS) {
            prune(context);
            FoldSmsDraft draft = DRAFTS.get(id);
            return draft == null ? unknownDraft() : record(draft);
        }
    }

    private static JSONObject record(FoldSmsDraft draft) throws JSONException {
        JSONArray results = new JSONArray();
        Integer[] codes = draft.results();
        for (int i = 0; i < codes.length; i++) results.put(new JSONObject().put("part", i)
                .put("resultCode", codes[i] == null ? JSONObject.NULL : codes[i])
                .put("state", codes[i] == null ? "unconfirmed" : codes[i] == Activity.RESULT_OK ? "sent" : "failed"));
        String masked = "…" + draft.recipient.substring(Math.max(0, draft.recipient.length() - 2));
        return ok().put("draftId", draft.id).put("state", draft.state(SystemClock.elapsedRealtime()))
                .put("recipientMasked", masked).put("bodyCharacters", draft.body.length())
                .put("subscriptionId", draft.subscriptionId).put("partCount", draft.parts)
                .put("partResults", results).put("delivery", "not_requested")
                .put("tracking", "in_memory_until_app_process_exit_or_24_hours")
                .put("retryAllowed", false);
    }

    private static void prune(Context context) {
        long now = SystemClock.elapsedRealtime();
        java.util.Iterator<Map.Entry<String, FoldSmsDraft>> iterator = DRAFTS.entrySet().iterator();
        while (iterator.hasNext()) {
            FoldSmsDraft draft = iterator.next().getValue();
            if (now - draft.created >= RECORD_TTL_MS || (!draft.attempted() && now - draft.created >= FoldSmsDraft.PREPARE_TTL_MS)) {
                unregister(context, draft.id);
                iterator.remove();
            }
        }
    }

    private static void unregister(Context context, String id) {
        BroadcastReceiver receiver;
        synchronized (RECEIVERS) { receiver = RECEIVERS.remove(id); }
        if (receiver != null) try { context.unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) { }
    }

    private static SmsManager managerFor(Context context, int subscription) {
        if (Build.VERSION.SDK_INT >= 31) {
            SmsManager manager = context.getSystemService(SmsManager.class);
            return manager == null ? null : manager.createForSubscriptionId(subscription);
        }
        return SmsManager.getSmsManagerForSubscriptionId(subscription);
    }

    private static boolean permitted(Context context, String permission) {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }
    private static Object nullable(String value) { return value == null ? JSONObject.NULL : value; }
    private static JSONObject ok() throws JSONException { return new JSONObject().put("ok", true); }
    private static JSONObject missing(String permission) throws JSONException {
        return failure("permission_required", "The corresponding Android runtime permission has not been granted.").put("permission", permission);
    }
    private static JSONObject unknownDraft() {
        return failure("unknown_draft", "Draft not found or process restarted. A prior send outcome cannot be inferred; do not recreate and resend automatically.");
    }
    private static JSONObject failure(String code, String detail) {
        try { return new JSONObject().put("ok", false).put("error", code).put("message", detail); }
        catch (JSONException impossible) { throw new IllegalStateException("SMS response construction failed"); }
    }
}
