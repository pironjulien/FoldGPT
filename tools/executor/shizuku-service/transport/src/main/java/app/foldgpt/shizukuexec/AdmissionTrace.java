package app.foldgpt.shizukuexec;

import android.system.ErrnoException;
import org.json.JSONObject;
import java.util.IdentityHashMap;
import java.util.Locale;

/** Bounded actual admission observations. None of these fields grants cleanup. */
final class AdmissionTrace {
    enum Stage { GUARD, DEPLOYMENT_ASSET, DEPLOYMENT_SCHEMA, NATIVE_DIRECTORY, INTERPRETER,
        NATIVE_INVENTORY, CWD_SHIM, PYTHON_DOMAIN, PYTHON_MANIFEST, PYTHON_ROOT,
        PYTHON_DATA, PYTHON_ALIASES, PYTHON_TREE, TRANSPORT_LOAD, OWNER_LINK,
        PIPE_CREATE, CONTROL_FLAGS, NATIVE_FORK, OBSERVER_START, COMPLETE }
    private Stage stage = Stage.GUARD;
    private String subject = "";
    private JSONObject facts = new JSONObject();
    void at(Stage value) { stage = value; subject = ""; facts = new JSONObject(); }
    void subject(String value) { subject = ascii(value, 192); facts = new JSONObject(); }
    void fact(String key, Object value) throws Exception {
        if (!java.util.Set.of("expected", "observed", "canonical", "uid", "mode").contains(key)) {
            throw new IllegalArgumentException("Unknown admission fact");
        }
        if (!(value instanceof String) && !(value instanceof Integer)) throw new IllegalArgumentException("Unbounded admission fact type");
        facts.put(key, value instanceof String ? ascii((String) value, 1024) : value);
    }
    JSONObject result(boolean admitted, Throwable error) {
        try {
            JSONObject result = new JSONObject().put("schema", "foldgpt.executor-admission.v1")
                .put("admitted", admitted).put("stage", stage.name().toLowerCase(Locale.ROOT))
                .put("subject", subject).put("facts", facts);
            result.put("error", error == null ? JSONObject.NULL : failure(error));
            return result;
        } catch (Exception unexpected) { throw new IllegalStateException("Admission diagnostic encoding failed", unexpected); }
    }
    static JSONObject failure(Throwable error) throws Exception {
        IdentityHashMap<Throwable, Boolean> seen = new IdentityHashMap<>();
        Throwable cause = error;
        for (int i = 0; i < 8; ++i) {
            seen.put(cause, true);
            Throwable next = cause.getCause();
            if (next == null || seen.containsKey(next)) break;
            cause = next;
        }
        String type = cause.getClass().getSimpleName();
        if (!type.matches("[A-Za-z_][A-Za-z0-9_]{0,63}")) type = "Throwable";
        StackTraceElement[] stack = cause.getStackTrace();
        StackTraceElement location = stack.length == 0 ? null : stack[0];
        String source = location == null ? "unknown" : location.getFileName();
        if (source == null || !source.matches("[A-Za-z0-9_.-]{1,64}")) source = "unknown";
        int line = location == null ? 0 : Math.max(0, Math.min(999999, location.getLineNumber()));
        Integer number = cause instanceof ErrnoException ? ((ErrnoException) cause).errno : null;
        if (number != null && (number < 1 || number > 4095)) number = null;
        return new JSONObject().put("errorType", type).put("errno", number == null ? JSONObject.NULL : number)
            .put("source", source).put("line", line).put("message", ascii(cause.getMessage(), 160));
    }
    static String ascii(String value, int limit) {
        if (value == null) return "";
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < Math.min(value.length(), limit); ++i) {
            char item = value.charAt(i);
            result.append(item >= 32 && item <= 126 && item != '"' && item != '\\' ? item : '?');
        }
        return result.toString();
    }
}
