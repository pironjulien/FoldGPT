package app.foldgpt;

import android.app.KeyguardManager;
import android.content.Context;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.PowerManager;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** App-private Android tools. Same UID authentication is not isolation from guest processes. */
public final class FoldAndroidBridge {
    private static FoldAndroidBridge instance;
    private final Context context;
    private LocalServerSocket server;
    private FoldAndroidBridge(Context context) { this.context = context.getApplicationContext(); }
    public static synchronized void start(Context context) {
        if (instance != null) return;
        FoldAndroidBridge created = new FoldAndroidBridge(context);
        try {
            created.server = new LocalServerSocket("foldgpt-android-" + android.os.Process.myUid());
            Os.fcntlInt(created.server.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
            instance = created;
            new Thread(created::serve, "FoldGPT-Android-tools").start();
        } catch (Exception error) {
            android.util.Log.e("FoldGPT-Android", "Android tool endpoint unavailable");
        }
    }
    private void serve() {
        while (true) {
            try (LocalSocket socket = server.accept()) {
                Os.fcntlInt(socket.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
                if (socket.getPeerCredentials().getUid() != android.os.Process.myUid()) continue;
                socket.setSoTimeout(15000);
                ByteArrayOutputStream input = new ByteArrayOutputStream();
                boolean complete = false;
                for (int i = 0; i < 32768; i++) {
                    int value = socket.getInputStream().read();
                    if (value == -1) break;
                    if (value == '\n') { complete = true; break; }
                    input.write(value);
                }
                JSONObject reply;
                try {
                    if (!complete) throw new IllegalArgumentException("request_size_or_framing");
                    JSONObject request = new JSONObject(new String(input.toByteArray(), StandardCharsets.UTF_8));
                    if (request.getInt("version") != 1) throw new IllegalArgumentException("unsupported_version");
                    reply = new JSONObject().put("ok", true).put("result", dispatch(request.getString("op"), request.optJSONObject("args")));
                } catch (SecurityException error) {
                    reply = new JSONObject().put("ok", false).put("error", "permission_required");
                } catch (Exception error) {
                    // Only explicitly bounded error codes, never raw platform exceptions/data.
                    String code = error.getMessage();
                    if (code == null || !code.matches("[a-z][a-z0-9_]{0,79}")) code = "android_operation_failed";
                    reply = new JSONObject().put("ok", false).put("error", code);
                }
                socket.getOutputStream().write((reply.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (Exception error) {
                android.util.Log.w("FoldGPT-Android", "Android tool connection ended");
            }
        }
    }
    private JSONObject dispatch(String op, JSONObject args) throws Exception {
        if (args == null) args = new JSONObject();
        if ("status".equals(op)) return new JSONObject()
            .put("schema", "foldgpt.android.v1").put("androidUid", android.os.Process.myUid())
            .put("globalControlEnabled", FoldAccessibilityService.status().optBoolean("connected", false))
            .put("computer", FoldAccessibilityService.status()).put("sms", FoldSmsTools.status(context))
            .put("permissionRequests", FoldAndroidPermissionActivity.status());
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        PowerManager power = context.getSystemService(PowerManager.class);
        if (keyguard == null || keyguard.isDeviceLocked() || keyguard.isKeyguardLocked()
                || power == null || !power.isInteractive()) throw new IllegalStateException("device_locked_or_asleep");
        if ("request_access".equals(op)) {
            if (args.length() != 1 || !(args.opt("scope") instanceof String))
                throw new IllegalArgumentException("invalid_arguments");
            return FoldAndroidPermissionActivity.request(context, args.getString("scope"));
        }
        if (op.startsWith("sms_")) {
            if ("sms_status".equals(op)) return FoldSmsTools.status(context);
            return FoldSmsTools.execute(context, op, args);
        }
        if ("apps".equals(op)) {
            android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_MAIN)
                    .addCategory(android.content.Intent.CATEGORY_LAUNCHER);
            org.json.JSONArray apps = new org.json.JSONArray();
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (android.content.pm.ResolveInfo info : context.getPackageManager().queryIntentActivities(intent, 0)) {
                if (info.activityInfo != null && seen.add(info.activityInfo.packageName))
                    apps.put(new JSONObject().put("packageName", info.activityInfo.packageName)
                        .put("label", info.loadLabel(context.getPackageManager()).toString()));
            }
            return new JSONObject().put("apps", apps);
        }
        return FoldAccessibilityService.execute(op, args);
    }
}
