package app.foldgpt;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import org.json.JSONObject;

/** Strict request parsing, independent of Android. Never includes private input in errors. */
final class FoldSmsRequest {
    static final int MAX_RESULTS = 50;
    final String selection;
    final String[] selectionArgs;
    final int limit;

    private FoldSmsRequest(List<String> clauses, List<String> values, int limit) {
        this.selection = String.join(" AND ", clauses);
        this.selectionArgs = values.toArray(new String[0]);
        this.limit = limit;
    }

    static FoldSmsRequest search(JSONObject args, boolean readThread) {
        keys(args, readThread ? new String[]{"threadId", "limit", "beforeId"}
                : new String[]{"text", "address", "threadId", "dateAfter", "dateBefore", "limit", "beforeId"});
        List<String> clauses = new ArrayList<>(), values = new ArrayList<>();
        boolean filtered = false;
        if (args.has("text")) {
            String value = string(args, "text", 1024, false);
            if (value.trim().isEmpty()) throw invalid();
            // User percent/underscore characters are literal, never query wildcards.
            add(clauses, values, "body LIKE ? ESCAPE '\\'", "%" + like(value) + "%");
            filtered = true;
        }
        if (args.has("address")) {
            add(clauses, values, "address = ?", string(args, "address", 256, false));
            filtered = true;
        }
        for (String field : new String[]{"threadId", "dateAfter", "dateBefore"}) {
            if (!args.has(field)) continue;
            long value = integer(args, field, field.equals("threadId") ? 1 : 0, Long.MAX_VALUE);
            add(clauses, values, field.equals("threadId") ? "thread_id = ?"
                    : field.equals("dateAfter") ? "date >= ?" : "date < ?", Long.toString(value));
            filtered = true;
        }
        if (!filtered || (readThread && !args.has("threadId"))) throw invalid();
        if (args.has("dateAfter") && args.has("dateBefore")
                && integer(args, "dateAfter", 0, Long.MAX_VALUE) >= integer(args, "dateBefore", 0, Long.MAX_VALUE))
            throw invalid();
        if (args.has("beforeId")) add(clauses, values, "_id < ?",
                Long.toString(integer(args, "beforeId", 1, Long.MAX_VALUE)));
        int limit = args.has("limit") ? (int) integer(args, "limit", 1, MAX_RESULTS) : 20;
        return new FoldSmsRequest(clauses, values, limit);
    }

    static String recipient(JSONObject args) {
        String input = string(args, "recipient", 128, false);
        if (!input.matches("[+0-9 ()\\-.]+")) throw invalid();
        String result = input.replaceAll("[ ()\\-.]", "");
        if (!result.matches("\\+?[0-9]{3,15}")) throw invalid();
        return result;
    }

    static String body(JSONObject args) {
        String value = string(args, "body", 4096, false);
        if (value.trim().isEmpty()) throw invalid();
        return value;
    }

    static String string(JSONObject args, String key, int maximum, boolean emptyAllowed) {
        Object raw = args.opt(key);
        if (!(raw instanceof String)) throw invalid();
        String value = (String) raw;
        if ((!emptyAllowed && value.isEmpty()) || value.length() > maximum) throw invalid();
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == 0 || (Character.isHighSurrogate(c) && (i + 1 >= value.length()
                    || !Character.isLowSurrogate(value.charAt(++i)))) || Character.isLowSurrogate(c)) throw invalid();
        }
        return value;
    }

    static long integer(JSONObject args, String key, long minimum, long maximum) {
        Object value = args.opt(key);
        if (!(value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long))
            throw invalid();
        long result = ((Number) value).longValue();
        if (result < minimum || result > maximum) throw invalid();
        return result;
    }

    static void keys(JSONObject args, String... allowed) {
        if (args == null) throw invalid();
        Set<String> names = new HashSet<>(Arrays.asList(allowed));
        Iterator<String> keys = args.keys();
        while (keys.hasNext()) if (!names.contains(keys.next())) throw invalid();
    }

    private static String like(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    private static void add(List<String> clauses, List<String> values, String clause, String value) {
        clauses.add(clause);
        values.add(value);
    }

    static IllegalArgumentException invalid() { return new IllegalArgumentException("invalid_sms_arguments"); }
}
