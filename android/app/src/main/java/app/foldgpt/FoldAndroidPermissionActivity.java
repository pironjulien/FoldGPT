package app.foldgpt;

import android.Manifest;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Hosts one native Android permission request; never waits for the user's response on a socket. */
public final class FoldAndroidPermissionActivity extends Activity {
    public static final String EXTRA_SCOPE = "app.foldgpt.android.PERMISSION_SCOPE";
    private static final int REQUEST_SMS = 61;
    private static final int REQUEST_SCREEN = 62;
    private static final Object LOCK = new Object();
    private static final Map<String, String> OUTCOMES = new HashMap<>();
    private static String pendingScope;
    private static volatile boolean visible;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private String scope;
    private boolean launched;

    public static boolean isVisible() { return visible; }

    /** Called from a worker or the UI thread. Dispatch only is bounded; user input is asynchronous. */
    public static JSONObject request(Context context, String requestedScope) {
        if (!validScope(requestedScope)) return error("invalid_scope");
        if (isReady(context, requestedScope)) return response(true, "already_granted", requestedScope);
        synchronized (LOCK) {
            if (pendingScope != null) return pendingScope.equals(requestedScope)
                    ? response(true, "permission_request_pending", requestedScope) : error("permission_request_in_progress");
            String blocked = blockedOutcome(context, requestedScope);
            if (blocked != null) return error(blocked);
        }
        if (!FoldActivity.isVisible() && !AndroidToolsActivity.isVisible()) return error("foldgpt_not_visible");
        final Context app = context.getApplicationContext();
        final CountDownLatch dispatched = new CountDownLatch(1);
        final JSONObject[] result = new JSONObject[1];
        final boolean[] cancelled = {false};
        Runnable launch = () -> {
            synchronized (LOCK) {
                if (cancelled[0]) return;
                String blocked = blockedOutcome(app, requestedScope);
                if (pendingScope != null) {
                    result[0] = pendingScope.equals(requestedScope)
                            ? response(true, "permission_request_pending", requestedScope) : error("permission_request_in_progress");
                } else if (isReady(app, requestedScope)) {
                    result[0] = response(true, "already_granted", requestedScope);
                } else if (blocked != null) {
                    result[0] = error(blocked);
                } else if (!FoldActivity.isVisible() && !AndroidToolsActivity.isVisible()) {
                    result[0] = error("foldgpt_not_visible");
                } else {
                    pendingScope = requestedScope;
                    try {
                        app.startActivity(new Intent(app, FoldAndroidPermissionActivity.class)
                                .putExtra(EXTRA_SCOPE, requestedScope).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                        OUTCOMES.put(requestedScope, "permission_request_dispatched");
                        result[0] = response(true, "permission_request_dispatched", requestedScope);
                    } catch (RuntimeException failure) {
                        pendingScope = null;
                        OUTCOMES.put(requestedScope, "permission_prompt_unavailable");
                        result[0] = error("permission_prompt_unavailable");
                    }
                }
                dispatched.countDown();
            }
        };
        if (Looper.myLooper() == Looper.getMainLooper()) launch.run();
        else {
            if (!MAIN.post(launch)) return error("permission_dispatch_unavailable");
            try {
                if (!dispatched.await(2, TimeUnit.SECONDS)) {
                    synchronized (LOCK) {
                        if (result[0] == null) { cancelled[0] = true; return error("permission_dispatch_timeout"); }
                    }
                }
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                synchronized (LOCK) {
                    if (result[0] == null) { cancelled[0] = true; return error("permission_dispatch_interrupted"); }
                }
            }
        }
        return result[0];
    }

    /** Only the user's button can retry a refused request; model calls cannot create prompt loops. */
    static JSONObject requestFromPanel(Context context, String scope) {
        if (!AndroidToolsActivity.isVisible()) return error("foldgpt_not_visible");
        synchronized (LOCK) { if (pendingScope == null) OUTCOMES.remove(scope); }
        return request(context, scope);
    }

    /** Metadata only. Read actual permission state through android_status after the user responds. */
    public static JSONObject status() {
        synchronized (LOCK) {
            JSONObject out = response(true, pendingScope == null ? "idle" : "permission_request_pending", pendingScope);
            JSONObject outcomes = new JSONObject();
            try {
                for (Map.Entry<String, String> entry : OUTCOMES.entrySet()) outcomes.put(entry.getKey(), entry.getValue());
                return out.put("outcomes", outcomes);
            } catch (JSONException impossible) { throw new IllegalStateException("permission_status_failed"); }
        }
    }

    public static boolean isGranted(Context context, String scope) {
        if ("sms_read".equals(scope)) return context.checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED;
        if ("sms_send".equals(scope)) return context.checkSelfPermission(Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED;
        if (!"screen_control".equals(scope)) return false;
        ComponentName expected = new ComponentName(context, FoldAccessibilityService.class);
        try {
            // The enabled-service list returned by AccessibilityManager can omit
            // services still binding. Read the user's saved selection instead;
            // a missing setting means no grant, not a failed read.
            String enabled = Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            if (enabled == null || enabled.isEmpty()) return false;
            for (String component : enabled.split(":")) {
                if (expected.equals(ComponentName.unflattenFromString(component))) return true;
            }
            return false;
        } catch (SecurityException unavailable) {
            // An OEM may restrict this public read. Only then use the manager's
            // observed enabled services; never replace a definitive false.
        }
        AccessibilityManager manager = context.getSystemService(AccessibilityManager.class);
        if (manager == null) return false;
        for (AccessibilityServiceInfo info : manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)) {
            if (info.getResolveInfo() == null || info.getResolveInfo().serviceInfo == null) continue;
            android.content.pm.ServiceInfo service = info.getResolveInfo().serviceInfo;
            if (expected.equals(new ComponentName(service.packageName, service.name))) return true;
        }
        return false;
    }

    private static boolean isReady(Context context, String scope) {
        return isGranted(context, scope) && (!"screen_control".equals(scope) || FoldAccessibilityService.isConnected());
    }

    /** Called while holding LOCK. A failed return from settings cannot open a prompt loop. */
    private static String blockedOutcome(Context context, String scope) {
        String outcome = OUTCOMES.get(scope);
        if ("accessibility_not_connected".equals(outcome)) return outcome;
        return "permission_denied".equals(outcome) && !isGranted(context, scope) ? outcome : null;
    }

    private String currentOutcome() {
        if (!isGranted(this, scope)) return "permission_denied";
        return !"screen_control".equals(scope) || FoldAccessibilityService.isConnected()
                ? "granted" : "accessibility_not_connected";
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        scope = state == null ? getIntent().getStringExtra(EXTRA_SCOPE) : state.getString("scope");
        synchronized (LOCK) {
            // A stale or forged launch cannot bypass the foreground request path.
            if (!validScope(scope) || !scope.equals(pendingScope)) { finish(); return; }
        }
        launched = state != null && state.getBoolean("launched");
        if (isReady(this, scope)) { complete("already_granted"); return; }
        if (launched) return; // Native permission dialog/settings survives Activity recreation.
        launched = true;
        try {
            if ("screen_control".equals(scope)) startAccessibilitySettings(this, true);
            else requestPermissions(new String[]{"sms_read".equals(scope) ? Manifest.permission.READ_SMS : Manifest.permission.SEND_SMS}, REQUEST_SMS);
        } catch (RuntimeException unavailable) { complete("permission_prompt_unavailable"); }
    }

    @Override public void onResume() { super.onResume(); visible = true; }
    @Override public void onPause() { visible = false; super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putString("scope", scope); state.putBoolean("launched", launched);
        super.onSaveInstanceState(state);
    }
    @Override public void onRequestPermissionsResult(int requestCode, String[] names, int[] results) {
        super.onRequestPermissionsResult(requestCode, names, results);
        if (requestCode == REQUEST_SMS) complete(currentOutcome());
    }
    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_SCREEN) complete(currentOutcome());
    }
    @Override protected void onDestroy() {
        visible = false;
        if (isFinishing()) {
            synchronized (LOCK) {
                if (scope != null && scope.equals(pendingScope)) {
                    OUTCOMES.put(scope, "permission_request_cancelled"); pendingScope = null;
                }
            }
        }
        super.onDestroy();
    }

    private void complete(String outcome) {
        synchronized (LOCK) {
            if (scope != null && scope.equals(pendingScope)) { OUTCOMES.put(scope, outcome); pendingScope = null; }
        }
        finish();
    }

    static void openAccessibilitySettings(Activity activity) {
        try { startAccessibilitySettings(activity, false); }
        catch (RuntimeException unavailable) {
            android.widget.Toast.makeText(activity, "Les paramètres d’accessibilité Android sont indisponibles.", android.widget.Toast.LENGTH_LONG).show();
        }
    }

    private static void startAccessibilitySettings(Activity activity, boolean forResult) {
        // The public API is available to ordinary apps. The per-service details
        // route requires a privileged Android permission on current Samsung builds.
        Intent settings = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
        if (forResult) activity.startActivityForResult(settings, REQUEST_SCREEN); else activity.startActivity(settings);
    }

    private static boolean validScope(String scope) {
        return "sms_read".equals(scope) || "sms_send".equals(scope) || "screen_control".equals(scope);
    }
    private static JSONObject error(String code) {
        try { return new JSONObject().put("ok", false).put("error", code); }
        catch (JSONException impossible) { throw new IllegalStateException("permission_response_failed"); }
    }
    private static JSONObject response(boolean ok, String state, String scope) {
        try { return new JSONObject().put("ok", ok).put("status", state).put("scope", scope == null ? JSONObject.NULL : scope); }
        catch (JSONException impossible) { throw new IllegalStateException("permission_response_failed"); }
    }
}
