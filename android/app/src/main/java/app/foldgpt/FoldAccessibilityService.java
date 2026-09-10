package app.foldgpt;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.app.ActivityOptions;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Base64;
import android.view.Display;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** On-demand Android UI access. No event contents, screenshots or text are persisted. */
public final class FoldAccessibilityService extends AccessibilityService {
    private static final long CALL_TIMEOUT_MS = 10_000;
    private static final long OBSERVATION_MAX_AGE_MS = 30_000;
    private static final int MAX_NODES = 512;
    private static final int MAX_DEPTH = 64;
    private static final int MAX_TEXT = 4096;
    private static final int MAX_SNAPSHOT_TEXT = 65_536;
    private static final int MAX_IMAGE_DIMENSION = 1600;
    private static volatile FoldAccessibilityService connected;

    private final Handler main = new Handler(Looper.getMainLooper());
    // These fields are accessed only on the service's main looper.
    private final Map<String, ObservedNode> observed = new LinkedHashMap<>();
    private final List<Rect> passwordBounds = new ArrayList<>();
    private final List<SemanticNode> observedSemantics = new ArrayList<>();
    private SemanticBudget semanticBudget = new SemanticBudget();
    private boolean observationDirty;
    private int childLookups;
    private String snapshotId;
    private long observedAt;
    private int observedWindow = -1;
    private String observedPackage;
    private Rect observedRootBounds;
    private long generation;
    private int visitedNodes;
    private boolean truncated;
    private int displayWidth;
    private int displayHeight;
    private int displayRotation;
    private int remainingText;
    private int lastInvalidatingEventType;
    private int lastInvalidatingWindow = -1;
    private LinuxInput input;
    private Context displayContext;

    @Override protected void onServiceConnected() {
        invalidateObservation();
        connected = this;
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        // Accessibility delivers events from other windows (status bar, launcher,
        // background apps). They must not expire a stable observed target.
        // Check the actual active window for global window signals; action dispatch
        // separately rechecks window, bounds and rotation before using a snapshot.
        if (snapshotId == null || event == null) return;
        int type = event.getEventType();
        if (type == AccessibilityEvent.TYPE_WINDOWS_CHANGED || type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            try { validateObservation(snapshotId, false); observationDirty = true; return; }
            catch (InvalidRequest changed) { /* The actual target changed. */ }
        } else if (event.getWindowId() != observedWindow) return;
        else if (type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            // Providers routinely announce unchanged content (for example the
            // calculator display). Recheck the bounded semantic tree at use time;
            // an event alone neither renews nor destroys the observation token.
            observationDirty = true;
            return;
        }
        lastInvalidatingEventType = type;
        lastInvalidatingWindow = event.getWindowId();
        invalidateObservation();
    }

    @Override public void onInterrupt() { invalidateObservation(); }

    @Override public boolean onUnbind(Intent intent) {
        disconnect();
        return super.onUnbind(intent);
    }

    @Override public void onDestroy() {
        disconnect();
        super.onDestroy();
    }

    private void disconnect() {
        if (connected == this) connected = null;
        invalidateObservation();
    }

    /** Permission can remain granted while Android has not bound this service. */
    public static boolean isConnected() { return connected != null; }

    /** Safe status: no active app title, page text or credentials. */
    public static JSONObject status() {
        FoldAccessibilityService service = connected;
        if (service == null) return unavailable();
        if (Looper.myLooper() == Looper.getMainLooper()) return service.statusOnMain();
        return execute("status", new JSONObject());
    }

    /** Call from the authenticated bridge's background thread, never its UI thread. */
    public static JSONObject execute(String operation, JSONObject arguments) {
        FoldAccessibilityService service = connected;
        if (service == null) return unavailable();
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return error("background_thread_required", "UI calls must originate on a bridge worker.");
        }
        Pending pending = new Pending();
        JSONObject args;
        try { args = arguments == null ? new JSONObject() : new JSONObject(arguments.toString()); }
        catch (JSONException e) { return error("invalid_arguments", "Arguments must be a JSON object."); }
        Runnable dispatch = () -> {
            if (!pending.canStart()) return;
            if (connected != service) {
                pending.finish(unavailable());
                return;
            }
            try { service.dispatch(operation, args, pending); }
            catch (InvalidRequest e) { pending.finish(error(e.code, e.getMessage())); }
            catch (SecurityException e) {
                pending.finish(error("android_permission_denied", "Android denied this operation."));
            } catch (Exception e) {
                // Exception strings can include application text: expose only a stable code.
                pending.finish(error("android_ui_error", "Android could not complete this operation."));
            }
        };
        if (!service.main.post(dispatch)) return error("service_stopping", "Accessibility service is stopping.");
        try {
            if (!pending.done.await(CALL_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
                service.main.removeCallbacks(dispatch);
                return pending.timeout();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            service.main.removeCallbacks(dispatch);
            return pending.timeout();
        }
        return pending.result();
    }

    private JSONObject statusOnMain() {
        boolean permissionFlowVisible = isPermissionFlowVisible();
        JSONObject result = object("ok", true, "connected", true,
                "interactive", isInteractive(), "locked", isLocked(),
                "available", isInteractive() && !isLocked() && !permissionFlowVisible,
                "permissionFlowVisible", permissionFlowVisible,
                "permission", "android_accessibility_service",
                "nodeScope", "visible_active_window", "coordinateSpace", "display_pixels",
                "snapshotMaxAgeMs", OBSERVATION_MAX_AGE_MS);
        result = withInvalidationMetadata(result);
        return result;
    }

    private JSONObject withInvalidationMetadata(JSONObject result) {
        try { return result.put("lastInvalidatingEventType", lastInvalidatingEventType)
                .put("lastInvalidatingWindowId", lastInvalidatingWindow)
                .put("snapshotDirty", snapshotId != null && observationDirty); }
        catch (JSONException impossible) { return result; }
    }

    private void dispatch(String operation, JSONObject args, Pending pending) throws Exception {
        if ("status".equals(operation)) { pending.finish(statusOnMain()); return; }
        requireUsable();
        if ("ui_input_status".equals(operation)) { pending.finish(inputStatus(args)); return; }
        if ("ui_cancel_input".equals(operation)) {
            JSONObject ignored = inputStatus(args);
            if (input != null && "running".equals(input.state)) input.finish("cancelled");
            pending.finish(inputStatus(args)); return;
        }
        if (!"ui_state".equals(operation) && !"ui_screenshot".equals(operation)) {
            requirePermissionFlowClear();
            if (input != null && "running".equals(input.state))
                throw invalid("input_in_progress", "Wait for ui_input_status or cancel input before another action.");
        }
        switch (operation == null ? "" : operation) {
            case "ui_state": pending.finish(observe(pending)); break;
            case "ui_screenshot": screenshot(pending); break;
            case "ui_click": nodeAction(args, AccessibilityNodeInfo.ACTION_CLICK, pending); break;
            case "ui_set_text": nodeAction(args, AccessibilityNodeInfo.ACTION_SET_TEXT, pending); break;
            case "ui_scroll": {
                String direction = requiredString(args, "direction");
                int action;
                switch (direction) {
                    case "forward": action = AccessibilityNodeInfo.ACTION_SCROLL_FORWARD; break;
                    case "backward": action = AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD; break;
                    case "up": action = AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_UP.getId(); break;
                    case "down": action = AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.getId(); break;
                    case "left": action = AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_LEFT.getId(); break;
                    case "right": action = AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_RIGHT.getId(); break;
                    default: throw invalid("invalid_direction", "Use forward, backward, up, down, left or right.");
                }
                nodeAction(args, action, pending);
                break;
            }
            case "ui_tap": gesture(args, false, pending); break;
            case "ui_swipe": gesture(args, true, pending); break;
            case "ui_global": global(args, pending); break;
            case "ui_launch": launch(args, pending); break;
            case "ui_type_text": linuxInput(args, false, pending); break;
            case "ui_press_keys": linuxInput(args, true, pending); break;
            default: throw invalid("unknown_operation", "Unknown Android UI operation.");
        }
    }

    private JSONObject observe(Pending pending) throws InvalidRequest {
        invalidateObservation();
        AccessibilityNodeInfo root = activeRoot();
        try {
            updateDisplaySize();
            snapshotId = UUID.randomUUID().toString();
            observedAt = SystemClock.elapsedRealtime();
            observedWindow = root.getWindowId();
            observedPackage = string(root.getPackageName());
            observedRootBounds = bounds(root);
            if (observedRootBounds.isEmpty()
                    || !Rect.intersects(observedRootBounds, new Rect(0, 0, displayWidth, displayHeight))) {
                invalidateObservation();
                throw invalid("no_visible_active_window", "The active window is outside the Android default display.");
            }
            JSONArray nodes = new JSONArray();
            visit(root, null, 0, nodes, pending);
            if (!pending.canStart()) {
                invalidateObservation();
                throw invalid("android_ui_timeout", "Android UI observation exceeded its deadline.");
            }
            return object("ok", true, "snapshotId", snapshotId,
                    "expiresInMs", OBSERVATION_MAX_AGE_MS, "packageName", observedPackage,
                    "windowId", observedWindow, "displayWidth", displayWidth,
                    "displayHeight", displayHeight, "displayRotationDegrees", displayRotation * 90,
                    "coordinateSpace", "display_pixels", "activeWindowBounds", rect(observedRootBounds),
                    "nodes", nodes, "truncated", truncated,
                    "protectedSurface", isProtectedPackage(observedPackage) || isPermissionFlowVisible(),
                    "passwordFieldsRedacted", passwordBounds.size(),
                    "passwordDetection", "android_accessibility_password_flag");
        } finally { root.recycle(); }
    }

    private void visit(AccessibilityNodeInfo node, String parent, int depth, JSONArray nodes, Pending pending) {
        if (!pending.canStart()) { truncated = true; return; }
        if (++visitedNodes > MAX_NODES || depth > MAX_DEPTH) { truncated = true; return; }
        if (!node.isVisibleToUser() || node.getWindowId() != observedWindow
                || !observedPackage.equals(string(node.getPackageName()))) return;
        Rect bounds = bounds(node);
        if (bounds.isEmpty() || !Rect.intersects(bounds, new Rect(0, 0, displayWidth, displayHeight))) return;
        String id = snapshotId + ":" + observed.size();
        boolean password = node.isPassword();
        if (password) passwordBounds.add(new Rect(bounds));
        AccessibilityNodeInfo retained = AccessibilityNodeInfo.obtain(node);
        observed.put(id, new ObservedNode(retained, bounds));
        observedSemantics.add(semanticNode(retained, parent, semanticBudget));
        JSONArray actions = new JSONArray();
        for (AccessibilityNodeInfo.AccessibilityAction action : node.getActionList()) {
            if (actions.length() == MAX_NODES) { truncated = true; break; }
            actions.put(action.getId());
        }
        nodes.put(object("nodeId", id, "parentNodeId", parent, "packageName", observedPackage,
                "className", snapshotText(node.getClassName()), "bounds", rect(bounds),
                "text", password ? "[redacted]" : snapshotText(node.getText()),
                "description", password ? "[redacted]" : snapshotText(node.getContentDescription()),
                "hint", password ? "[redacted]" : snapshotText(node.getHintText()),
                "password", password, "enabled", node.isEnabled(), "clickable", node.isClickable(),
                "editable", node.isEditable(), "scrollable", node.isScrollable(),
                "focused", node.isFocused(), "selected", node.isSelected(),
                "checkable", node.isCheckable(), "checked", node.isChecked(), "actions", actions));
        // A password subtree can contain provider-specific descendants exposing the value.
        if (password) return;
        for (int index = 0; index < node.getChildCount(); index++) {
            if (visitedNodes >= MAX_NODES || childLookups >= MAX_NODES - 1 || !pending.canStart()) { truncated = true; break; }
            childLookups++;
            AccessibilityNodeInfo child = node.getChild(index);
            if (child != null) {
                try { visit(child, id, depth + 1, nodes, pending); }
                finally { child.recycle(); }
            } else truncated = true; // An unavailable child cannot prove a complete redaction/semantic map.
        }
    }

    private void nodeAction(JSONObject args, int action, Pending pending) throws InvalidRequest {
        String id = requiredString(args, "nodeId");
        validateObservation(id.contains(":") ? id.substring(0, id.lastIndexOf(':')) : "");
        requireMutableSurface();
        ObservedNode item = observed.get(id);
        if (item == null) throw invalid("unknown_node", "Read ui_state again before acting.");
        AccessibilityNodeInfo node = item.node;
        if (!node.refresh() || !node.isVisibleToUser() || !node.isEnabled()
                || node.getWindowId() != observedWindow
                || !observedPackage.equals(string(node.getPackageName())) || !item.bounds.equals(bounds(node))) {
            invalidateObservation();
            throw invalid("stale_node", "The observed node changed. Read ui_state again.");
        }
        // refresh() can observe a change that happened after the tree walk.
        int nodeIndex = new ArrayList<>(observed.keySet()).indexOf(id);
        SemanticNode previous = observedSemantics.get(nodeIndex);
        SemanticBudget refreshedBudget = new SemanticBudget();
        if (!previous.equals(semanticNode(node, previous.parent(), refreshedBudget)) || !refreshedBudget.complete) {
            invalidateObservation();
            throw invalid("stale_node", "The observed node content or actions changed. Read ui_state again.");
        }
        Bundle extras = null;
        if (action == AccessibilityNodeInfo.ACTION_SET_TEXT) {
            if (node.isPassword() || hasPasswordAncestor(node)) {
                throw invalid("password_write_denied", "Password fields must be filled by the user or Android credential provider.");
            }
            if (!node.isEditable()) throw invalid("not_editable", "The observed node is not editable.");
            String text = requiredStringAllowEmpty(args, "text");
            if (text.length() > MAX_TEXT) throw invalid("text_too_long", "Text exceeds the 4096 character limit.");
            extras = new Bundle();
            extras.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        }
        boolean supported = false;
        for (AccessibilityNodeInfo.AccessibilityAction available : node.getActionList()) {
            if (available.getId() == action) { supported = true; break; }
        }
        if (!supported) throw invalid("action_not_supported", "The node does not expose the requested accessibility action.");
        pending.markIssued();
        boolean accepted;
        try { accepted = node.performAction(action, extras); }
        finally { invalidateObservation(); }
        pending.finish(object("ok", accepted, "accepted", accepted, "completed", false,
                "verificationRequired", true, "error", accepted ? null : "android_action_rejected"));
    }

    private boolean hasPasswordAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo parent = node.getParent();
        int remaining = MAX_DEPTH;
        while (parent != null) {
            AccessibilityNodeInfo next = null;
            try {
                if (parent.isPassword() || --remaining == 0) return true;
                next = parent.getParent();
            } finally { parent.recycle(); }
            parent = next;
        }
        return false;
    }

    private void gesture(JSONObject args, boolean swipe, Pending pending) throws InvalidRequest {
        validateObservation(requiredString(args, "snapshotId"));
        requireMutableSurface();
        float x1 = coordinate(args, swipe ? "x1" : "x", displayWidth);
        float y1 = coordinate(args, swipe ? "y1" : "y", displayHeight);
        float x2 = swipe ? coordinate(args, "x2", displayWidth) : x1;
        float y2 = swipe ? coordinate(args, "y2", displayHeight) : y1;
        if (!observedRootBounds.contains((int) x1, (int) y1)
                || !observedRootBounds.contains((int) x2, (int) y2)) {
            throw invalid("outside_active_window", "Gesture endpoints must remain inside the observed active window.");
        }
        long duration = swipe ? requiredInteger(args, "durationMs", 1, 2000) : 1;
        Path path = new Path();
        path.moveTo(x1, y1);
        if (swipe) path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, duration)).build();
        pending.markIssued();
        boolean accepted;
        try {
            accepted = dispatchGesture(gesture, new GestureResultCallback() {
                @Override public void onCompleted(GestureDescription description) {
                    pending.finish(object("ok", true, "accepted", true, "completed", true,
                            "verificationRequired", true));
                }
                @Override public void onCancelled(GestureDescription description) {
                    pending.finish(object("ok", false, "accepted", true, "completed", false,
                            "error", "android_gesture_cancelled"));
                }
            }, main);
        } finally { invalidateObservation(); }
        if (!accepted) pending.finish(object("ok", false, "accepted", false, "completed", false,
                "error", "android_gesture_rejected"));
    }

    private void global(JSONObject args, Pending pending) throws InvalidRequest {
        String requested = requiredString(args, "action");
        int action;
        switch (requested) {
            case "back": action = GLOBAL_ACTION_BACK; break;
            case "home": action = GLOBAL_ACTION_HOME; break;
            case "recents": action = GLOBAL_ACTION_RECENTS; break;
            default: throw invalid("unsupported_global_action", "Only back, home and recents are supported.");
        }
        pending.markIssued();
        boolean accepted;
        try { accepted = performGlobalAction(action); }
        finally { invalidateObservation(); }
        pending.finish(object("ok", accepted, "accepted", accepted, "completed", false,
                "verificationRequired", true, "error", accepted ? null : "android_global_action_rejected"));
    }

    private void linuxInput(JSONObject args, boolean chord, Pending pending) throws Exception {
        validateObservation(requiredString(args, "snapshotId"));
        requireMutableSurface();
        if (!getPackageName().equals(observedPackage) || !FoldActivity.isVisible())
            throw invalid("linux_surface_required", "Use ui_set_text on Android editable nodes. This operation targets the visible FoldGPT Linux surface only.");
        int[] keys = null;
        String text = null;
        if (chord) {
            JSONArray requested = args.optJSONArray("keys");
            if (requested == null || requested.length() < 1 || requested.length() > 4)
                throw invalid("invalid_keys", "Provide one key, optionally preceded by modifiers.");
            keys = new int[requested.length()];
            java.util.Set<Integer> seen = new java.util.HashSet<>();
            for (int i = 0; i < keys.length; i++) {
                Object value = requested.get(i);
                if (!(value instanceof String)) throw invalid("invalid_keys", "Use named keyboard keys.");
                String name = ((String)value).toUpperCase(java.util.Locale.ROOT);
                boolean modifier = java.util.Set.of("CTRL", "ALT", "SHIFT", "META").contains(name);
                if (i < keys.length - 1 && !modifier)
                    throw invalid("invalid_keys", "Only modifiers may precede the final key.");
                String code = switch (name) {
                    case "CTRL" -> "CTRL_LEFT"; case "ALT" -> "ALT_LEFT";
                    case "SHIFT" -> "SHIFT_LEFT"; case "META" -> "META_LEFT";
                    case "BACKSPACE" -> "DEL"; case "DELETE" -> "FORWARD_DEL";
                    case "UP", "DOWN", "LEFT", "RIGHT" -> "DPAD_" + name;
                    default -> name;
                };
                if (!modifier && !name.matches("[A-Z0-9]|F(?:[1-9]|1[0-2])|ENTER|TAB|ESCAPE|SPACE|BACKSPACE|DELETE|UP|DOWN|LEFT|RIGHT|MOVE_HOME|MOVE_END|PAGE_UP|PAGE_DOWN"))
                    throw invalid("invalid_keys", "Unsupported Linux keyboard key.");
                keys[i] = android.view.KeyEvent.keyCodeFromString("KEYCODE_" + code);
                if (keys[i] == android.view.KeyEvent.KEYCODE_UNKNOWN || !seen.add(keys[i]))
                    throw invalid("invalid_keys", "Unknown or duplicate key.");
            }
        } else {
            text = requiredString(args, "text");
            if (text.length() > MAX_TEXT || text.indexOf('\0') >= 0)
                throw invalid("invalid_text", "Text exceeds the bounded input limit.");
        }
        pending.markIssued();
        int[] codes = chord ? keys : text.codePoints().toArray();
        for (int code : codes) if (code >= 0xd800 && code <= 0xdfff)
            throw invalid("invalid_text", "Text contains an unpaired Unicode surrogate.");
        input = new LinuxInput(codes, !chord);
        invalidateObservation();
        main.post(input);
        pending.finish(input.report());
    }

    private JSONObject inputStatus(JSONObject args) throws InvalidRequest {
        String id = requiredString(args, "inputId");
        if (input == null || !input.id.equals(id))
            throw invalid("unknown_input", "Input record is unavailable. Observe the screen; never replay automatically.");
        return input.report();
    }

    /** Pace Unicode using the inherited 2.5ms inter-character gap, rounded to the
     * Handler's millisecond resolution. Native calls never sleep or block. */
    private final class LinuxInput implements Runnable {
        final String id = UUID.randomUUID().toString();
        final boolean unicode;
        int[] codes;
        final int count;
        final long deadline;
        final java.util.ArrayList<Integer> pressed = new java.util.ArrayList<>();
        int sent;
        String state = "running";
        boolean releaseFailed;
        LinuxInput(int[] codes, boolean unicode) {
            this.codes = codes; this.unicode = unicode;
            count = unicode ? codes.length : codes.length * 2;
            deadline = SystemClock.elapsedRealtime() + CALL_TIMEOUT_MS + count * 3L;
        }
        @Override public void run() {
            if (!"running".equals(state)) return;
            if (SystemClock.elapsedRealtime() >= deadline) { finish("timeout"); return; }
            try {
                requireUsable(); requirePermissionFlowClear();
                if (!FoldActivity.isVisible()) { finish("target_changed"); return; }
                AccessibilityNodeInfo root = activeRoot();
                try { if (!getPackageName().equals(string(root.getPackageName()))) { finish("target_changed"); return; } }
                finally { root.recycle(); }
                boolean down = unicode || sent < codes.length;
                int code = unicode || down ? codes[sent] : codes[count - 1 - sent];
                int result = FoldActivity.sendLinuxInput(code, unicode, down);
                if (result < 0) { finish("transport_failed"); return; }
                if (result == 1) {
                    sent++;
                    if (!unicode) { if (down) pressed.add(code); else pressed.remove((Integer)code); }
                }
                if (sent == count) { finish("sent_to_x11"); return; }
                main.postDelayed(this, 3);
            } catch (Exception stopped) { finish("target_unavailable"); }
        }
        void finish(String terminal) {
            state = terminal;
            main.removeCallbacks(this);
            for (int i = pressed.size() - 1; i >= 0; i--)
                if (FoldActivity.releaseLinuxKey(pressed.get(i)) != 1) releaseFailed = true;
            pressed.clear(); codes = null; // Do not retain input text after completion.
            invalidateObservation();
        }
        JSONObject report() {
            boolean normal = "running".equals(state) || "sent_to_x11".equals(state);
            return object("ok", normal, "inputId", id, "state", state, "framesSent", sent,
                    "framesTotal", count, "completed", false, "verificationRequired", true,
                    "outcomeUnknown", !normal && sent > 0, "keyReleaseFailed", releaseFailed,
                    "error", normal ? null : "linux_input_" + state);
        }
    }

    private void launch(JSONObject args, Pending pending) throws InvalidRequest {
        String target = requiredString(args, "packageName");
        if (!target.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")) {
            throw invalid("invalid_package", "A valid Android package name is required.");
        }
        if (isProtectedPackage(target)) throw invalid("protected_android_surface", "Android settings and permission management must be operated by the user.");
        Intent intent = getPackageManager().getLaunchIntentForPackage(target);
        if (intent == null) throw invalid("app_not_launchable", "Android did not expose a launcher activity for this package.");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        pending.markIssued();
        try {
            // Service launches otherwise inherit Android's last focused display,
            // which can be an unrelated scrcpy/desktop virtual display.
            startActivity(intent, ActivityOptions.makeBasic()
                    .setLaunchDisplayId(Display.DEFAULT_DISPLAY).toBundle());
        }
        finally { invalidateObservation(); }
        pending.finish(object("ok", true, "accepted", true, "completed", false,
                "verificationRequired", true, "packageName", target,
                "launchDisplayId", Display.DEFAULT_DISPLAY));
    }

    private void screenshot(Pending pending) throws InvalidRequest {
        JSONObject observation = observe(pending);
        if (truncated) {
            throw invalid("incomplete_redaction_map", "The active UI tree exceeds the bounded password-redaction scan.");
        }
        final long captureGeneration = generation;
        final String captureSnapshot = snapshotId;
        final int width = displayWidth;
        final int height = displayHeight;
        final Rect cropBounds = new Rect(observedRootBounds);
        cropBounds.intersect(0, 0, width, height);
        final List<Rect> redactions = new ArrayList<>();
        for (Rect rect : passwordBounds) redactions.add(new Rect(rect));
        takeScreenshot(Display.DEFAULT_DISPLAY, main::post, new TakeScreenshotCallback() {
            @Override public void onSuccess(ScreenshotResult result) {
                HardwareBuffer buffer = result.getHardwareBuffer();
                try {
                    if (generation != captureGeneration || !captureSnapshot.equals(snapshotId)) {
                        pending.finish(error("screen_changed_during_capture", "Read the UI again after the screen settles."));
                        return;
                    }
                    // Window events can arrive after this callback. Verify the actual display/window too.
                    validateObservation(captureSnapshot);
                    // Buffer ownership moves to the bridge worker; PNG encoding never blocks the main looper.
                    if (pending.finishCapture(result, observation, redactions, cropBounds, width, height)) buffer = null;
                } catch (InvalidRequest e) {
                    pending.finish(error(e.code, e.getMessage()));
                } catch (RuntimeException e) {
                    pending.finish(error("screen_changed_during_capture", "Android could not verify the captured window."));
                } finally { if (buffer != null) buffer.close(); }
            }
            @Override public void onFailure(int errorCode) {
                pending.finish(object("ok", false, "error", "android_screenshot_failed",
                        "androidErrorCode", errorCode, "message", "Android refused or could not capture this display."));
            }
        });
    }

    private void validateObservation(String token) throws InvalidRequest {
        validateObservation(token, true);
    }

    private void validateObservation(String token, boolean verifyTree) throws InvalidRequest {
        requireUsable();
        if (snapshotId == null || !snapshotId.equals(token)
                || SystemClock.elapsedRealtime() - observedAt > OBSERVATION_MAX_AGE_MS) {
            throw invalid("stale_snapshot", "Read ui_state or ui_screenshot again before acting.");
        }
        AccessibilityNodeInfo root = activeRoot();
        try {
            if (verifyTree && !root.refresh()) {
                invalidateObservation();
                throw invalid("stale_snapshot", "Android could not refresh the observed window. Observe it again.");
            }
            int previousWidth = displayWidth, previousHeight = displayHeight, previousRotation = displayRotation;
            updateDisplaySize();
            if (root.getWindowId() != observedWindow || !observedPackage.equals(string(root.getPackageName()))
                    || !observedRootBounds.equals(bounds(root))
                    || displayWidth != previousWidth || displayHeight != previousHeight
                    || displayRotation != previousRotation) {
                invalidateObservation();
                throw invalid("stale_snapshot", "The active window or display changed. Observe it again.");
            }
            if (verifyTree) {
                // Validate even before a queued content event is delivered. This
                // also protects screenshot callbacks using the old redaction map.
                try (SemanticScan scan = new SemanticScan()) {
                    scan.visit(root, null, 0);
                    if (!sameSemanticTree(observedSemantics, !truncated && semanticBudget.complete,
                            scan.nodes, scan.complete && scan.budget.complete)) {
                        invalidateObservation();
                        throw invalid("stale_snapshot", "The observed UI content changed or could not be verified completely. Observe it again.");
                    }
                    observationDirty = false;
                } catch (RuntimeException unavailable) {
                    invalidateObservation();
                    throw invalid("stale_snapshot", "Android could not verify the observed UI content. Observe it again.");
                }
                if (SystemClock.elapsedRealtime() - observedAt > OBSERVATION_MAX_AGE_MS) {
                    invalidateObservation();
                    throw invalid("stale_snapshot", "The observation expired during verification. Observe it again.");
                }
            }
        } finally { root.recycle(); }
    }

    /** In-memory semantics only; identity equality is Android's source-node identity. */
    static record SemanticNode(Object identity, String parent, Map<String, Object> properties) {
        SemanticNode { properties = Map.copyOf(properties); }
    }

    static boolean sameSemanticTree(List<SemanticNode> previous, boolean previousComplete,
            List<SemanticNode> current, boolean currentComplete) {
        return previousComplete && currentComplete && previous.equals(current);
    }

    static final class SemanticBudget {
        int remaining = MAX_SNAPSHOT_TEXT;
        boolean complete = true;
        String text(CharSequence value) {
            if (value == null) return "";
            int available = value.length();
            // The returned presentation truncates each field at MAX_TEXT. The
            // private comparison retains the full field when the total bounded
            // budget permits, so a changed suffix can never compare as equal.
            int length = Math.min(available, remaining);
            if (length < available) complete = false;
            remaining -= length;
            return value.subSequence(0, length).toString();
        }
    }

    private static SemanticNode semanticNode(AccessibilityNodeInfo node, String parent, SemanticBudget budget) {
        Rect bounds = bounds(node);
        boolean password = node.isPassword();
        Map<String, Object> values = new LinkedHashMap<>();
        values.put("window", node.getWindowId());
        values.put("package", budget.text(node.getPackageName()));
        values.put("class", budget.text(node.getClassName()));
        values.put("viewId", budget.text(node.getViewIdResourceName()));
        values.put("bounds", List.of(bounds.left, bounds.top, bounds.right, bounds.bottom));
        values.put("children", password ? 0 : node.getChildCount());
        values.put("password", password);
        if (!password) {
            values.put("text", budget.text(node.getText()));
            values.put("description", budget.text(node.getContentDescription()));
            values.put("hint", budget.text(node.getHintText()));
            values.put("error", budget.text(node.getError()));
            values.put("state", budget.text(node.getStateDescription()));
            values.put("tooltip", budget.text(node.getTooltipText()));
            values.put("pane", budget.text(node.getPaneTitle()));
            values.put("selection", List.of(node.getTextSelectionStart(), node.getTextSelectionEnd()));
        }
        values.put("flags", List.of(node.isVisibleToUser(), node.isEnabled(), node.isClickable(),
                node.isLongClickable(), node.isEditable(), node.isScrollable(), node.isFocused(),
                node.isAccessibilityFocused(), node.isSelected(), node.isCheckable(), node.isChecked(),
                node.isContentInvalid(), node.isDismissable(), node.isContextClickable(), node.isMultiLine(),
                node.isHeading(), node.isScreenReaderFocusable()));
        values.put("input", List.of(node.getInputType(), node.getMaxTextLength(), node.getMovementGranularities()));
        List<List<Object>> actions = new ArrayList<>();
        for (AccessibilityNodeInfo.AccessibilityAction action : node.getActionList()) {
            if (actions.size() == MAX_NODES) { budget.complete = false; break; }
            actions.add(List.of(action.getId(), password ? "" : budget.text(action.getLabel())));
        }
        actions.sort(java.util.Comparator.comparingInt(value -> (Integer)value.get(0)));
        values.put("actions", List.copyOf(actions));
        return new SemanticNode(node, parent, values);
    }

    private final class SemanticScan implements AutoCloseable {
        final List<SemanticNode> nodes = new ArrayList<>();
        final List<AccessibilityNodeInfo> retained = new ArrayList<>();
        final SemanticBudget budget = new SemanticBudget();
        final long deadline = SystemClock.elapsedRealtime() + CALL_TIMEOUT_MS;
        int visited, children;
        boolean complete = true;
        void visit(AccessibilityNodeInfo node, String parent, int depth) {
            if (SystemClock.elapsedRealtime() >= deadline || ++visited > MAX_NODES || depth > MAX_DEPTH) {
                complete = false; return;
            }
            if (!node.isVisibleToUser() || node.getWindowId() != observedWindow
                    || !observedPackage.equals(string(node.getPackageName()))) return;
            Rect bounds = bounds(node);
            if (bounds.isEmpty() || !Rect.intersects(bounds, new Rect(0, 0, displayWidth, displayHeight))) return;
            String id = snapshotId + ":" + nodes.size();
            AccessibilityNodeInfo copy = AccessibilityNodeInfo.obtain(node);
            retained.add(copy);
            nodes.add(semanticNode(copy, parent, budget));
            if (node.isPassword()) return;
            for (int index = 0; index < node.getChildCount(); index++) {
                if (visited >= MAX_NODES || children >= MAX_NODES - 1 || SystemClock.elapsedRealtime() >= deadline) {
                    complete = false; break;
                }
                children++;
                AccessibilityNodeInfo child = node.getChild(index);
                if (child == null) { complete = false; continue; }
                try {
                    if (!child.refresh()) { complete = false; continue; }
                    visit(child, id, depth + 1);
                }
                finally { child.recycle(); }
            }
        }
        @Override public void close() { for (AccessibilityNodeInfo node : retained) node.recycle(); }
    }

    private AccessibilityNodeInfo activeRoot() throws InvalidRequest {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) throw invalid("no_active_window", "Android did not expose an active window.");
        if (!root.isVisibleToUser() || root.getPackageName() == null) {
            root.recycle();
            throw invalid("no_visible_active_window", "Android did not expose a visible active window.");
        }
        AccessibilityWindowInfo window = root.getWindow();
        if (window != null) {
            try {
                if (window.getDisplayId() != Display.DEFAULT_DISPLAY) {
                    root.recycle();
                    throw invalid("unsupported_display", "Only the active window on the Android default display is supported.");
                }
            } finally { window.recycle(); }
        }
        return root;
    }

    private void requireUsable() throws InvalidRequest {
        if (connected != this) throw invalid("accessibility_not_connected", "Android accessibility access is not enabled.");
        if (!isInteractive()) throw invalid("screen_not_interactive", "The Android display is not interactive.");
        if (isLocked()) throw invalid("device_locked", "Unlock the Android device before UI access.");
    }

    private boolean isInteractive() {
        PowerManager power = getSystemService(PowerManager.class);
        return power != null && power.isInteractive();
    }

    private boolean isLocked() {
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        return keyguard == null || keyguard.isDeviceLocked() || keyguard.isKeyguardLocked();
    }

    private void requireMutableSurface() throws InvalidRequest {
        requirePermissionFlowClear();
        if (isProtectedPackage(observedPackage)) {
            throw invalid("protected_android_surface", "Android settings, system controls and permission management must be operated by the user.");
        }
    }

    private static boolean isPermissionFlowVisible() {
        return AndroidToolsActivity.isVisible() || FoldAndroidPermissionActivity.isVisible();
    }

    private static void requirePermissionFlowClear() throws InvalidRequest {
        if (isPermissionFlowVisible()) {
            throw invalid("protected_android_surface", "Android tool consent must be operated by the user.");
        }
    }

    private static boolean isProtectedPackage(String name) {
        if (name == null) return true;
        return name.equals("com.android.settings") || name.equals("com.android.systemui")
                || name.equals("com.samsung.android.settings") || name.endsWith(".permissioncontroller")
                || name.endsWith(".packageinstaller") || name.equals("com.android.managedprovisioning");
    }

    private void updateDisplaySize() throws InvalidRequest {
        DisplayManager manager = getSystemService(DisplayManager.class);
        Display display = manager == null ? null : manager.getDisplay(Display.DEFAULT_DISPLAY);
        if (display == null) throw invalid("display_unavailable", "Android default display is unavailable.");
        // getRealMetrics on the service's process Resources can retain another
        // display's compatibility bounds after a virtual-display launch. A window
        // context is attached to the requested display and receives its updates.
        if (displayContext == null) displayContext = createDisplayContext(display)
                .createWindowContext(WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY, null);
        WindowManager windows = displayContext.getSystemService(WindowManager.class);
        if (windows == null) throw invalid("display_unavailable", "Android window metrics are unavailable.");
        Rect metrics = windows.getMaximumWindowMetrics().getBounds();
        displayWidth = metrics.width();
        displayHeight = metrics.height();
        displayRotation = display.getRotation();
        if (displayWidth <= 0 || displayHeight <= 0) throw invalid("display_unavailable", "Android reported an empty display.");
    }

    private void invalidateObservation() {
        generation++;
        for (ObservedNode item : observed.values()) item.node.recycle();
        observed.clear();
        passwordBounds.clear();
        observedSemantics.clear();
        semanticBudget = new SemanticBudget();
        observationDirty = false;
        childLookups = 0;
        snapshotId = null;
        observedPackage = null;
        observedRootBounds = null;
        observedWindow = -1;
        observedAt = 0;
        visitedNodes = 0;
        truncated = false;
        remainingText = MAX_SNAPSHOT_TEXT;
    }

    private static final class ObservedNode {
        final AccessibilityNodeInfo node;
        final Rect bounds;
        ObservedNode(AccessibilityNodeInfo node, Rect bounds) { this.node = node; this.bounds = new Rect(bounds); }
    }

    private static final class Pending {
        final CountDownLatch done = new CountDownLatch(1);
        private final long deadline = SystemClock.elapsedRealtime() + CALL_TIMEOUT_MS;
        private boolean finished;
        private boolean issued;
        private JSONObject response;
        private ScreenshotResult capture;
        private JSONObject observation;
        private List<Rect> redactions;
        private Rect activeBounds;
        private int width, height;

        synchronized boolean canStart() { return !finished && SystemClock.elapsedRealtime() < deadline; }
        synchronized void markIssued() throws InvalidRequest {
            if (!canStart()) throw invalid("android_ui_timeout", "The operation expired before Android action dispatch.");
            issued = true;
        }
        synchronized void finish(JSONObject response) {
            if (finished) return;
            finished = true;
            this.response = response;
            done.countDown();
        }
        synchronized boolean finishCapture(ScreenshotResult capture, JSONObject observation,
                List<Rect> redactions, Rect activeBounds, int width, int height) {
            if (finished || SystemClock.elapsedRealtime() >= deadline) return false;
            this.capture = capture;
            this.observation = observation;
            this.redactions = redactions;
            this.activeBounds = activeBounds;
            this.width = width;
            this.height = height;
            finished = true;
            done.countDown();
            return true;
        }
        synchronized JSONObject timeout() {
            if (capture != null) { capture.getHardwareBuffer().close(); capture = null; }
            finished = true;
            return object("ok", false, "error", "android_ui_timeout", "issued", issued,
                    "outcomeUnknown", issued, "message", "Deadline exceeded. Observe the current state before retrying an action.");
        }
        synchronized JSONObject result() {
            if (capture == null) return response != null ? response : error("android_ui_error", "Missing Android response.");
            HardwareBuffer buffer = capture.getHardwareBuffer();
            Bitmap hardware = null, bitmap = null, scaled = null;
            try {
                hardware = Bitmap.wrapHardwareBuffer(buffer, capture.getColorSpace());
                if (hardware == null) return error("screenshot_decode_failed", "Android returned an unreadable screenshot.");
                if (hardware.getWidth() != width || hardware.getHeight() != height) {
                    return error("display_changed_during_capture", "Screenshot dimensions differ from the observed display.");
                }
                bitmap = hardware.copy(Bitmap.Config.ARGB_8888, true);
                if (bitmap == null) return error("screenshot_decode_failed", "Android screenshot conversion failed.");
                Canvas canvas = new Canvas(bitmap);
                Paint paint = new Paint();
                paint.setColor(Color.BLACK);
                // Only the observed active window is disclosed. Other windows may contain passwords.
                canvas.drawRect(0, 0, width, activeBounds.top, paint);
                canvas.drawRect(0, activeBounds.bottom, width, height, paint);
                canvas.drawRect(0, activeBounds.top, activeBounds.left, activeBounds.bottom, paint);
                canvas.drawRect(activeBounds.right, activeBounds.top, width, activeBounds.bottom, paint);
                for (Rect bounds : redactions) canvas.drawRect(bounds, paint);
                double scale = Math.min(1d, (double) MAX_IMAGE_DIMENSION / Math.max(width, height));
                int imageWidth = Math.max(1, (int) Math.round(width * scale));
                int imageHeight = Math.max(1, (int) Math.round(height * scale));
                scaled = Bitmap.createScaledBitmap(bitmap, imageWidth, imageHeight, true);
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                if (!scaled.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                    return error("screenshot_encode_failed", "Android PNG encoding failed.");
                }
                if (SystemClock.elapsedRealtime() >= deadline) return error("android_ui_timeout", "Screenshot encoding exceeded its deadline.");
                return object("ok", true, "snapshotId", observation.optString("snapshotId"),
                        "packageName", observation.optString("packageName"), "imageBase64", Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP),
                        "mimeType", "image/png", "width", imageWidth, "height", imageHeight,
                        "displayWidth", width, "displayHeight", height,
                        "displayRotationDegrees", observation.optInt("displayRotationDegrees"),
                        "displayPixelsPerImagePixelX", (double) width / imageWidth,
                        "displayPixelsPerImagePixelY", (double) height / imageHeight,
                        "coordinateSpace", "display_pixels", "activeWindowBounds", rect(activeBounds),
                        "outsideActiveWindowRedacted", true, "passwordFieldsRedacted", redactions.size(),
                        "passwordDetection", "android_accessibility_password_flag");
            } catch (RuntimeException e) {
                return error("screenshot_processing_failed", "Android screenshot processing failed.");
            } finally {
                if (scaled != null && scaled != bitmap) scaled.recycle();
                if (bitmap != null) bitmap.recycle();
                if (hardware != null) hardware.recycle();
                buffer.close();
                capture = null;
            }
        }
    }

    private static Rect bounds(AccessibilityNodeInfo node) { Rect bounds = new Rect(); node.getBoundsInScreen(bounds); return bounds; }
    private static JSONObject rect(Rect bounds) { return object("left", bounds.left, "top", bounds.top, "right", bounds.right, "bottom", bounds.bottom); }
    private static String string(CharSequence value) { return value == null ? "" : value.toString(); }
    private String snapshotText(CharSequence value) {
        if (value == null) return "";
        int length = Math.min(value.length(), Math.min(MAX_TEXT, remainingText));
        remainingText -= length;
        return value.subSequence(0, length).toString();
    }
    private static String requiredString(JSONObject args, String key) throws InvalidRequest {
        String value = requiredStringAllowEmpty(args, key);
        if (value.isEmpty()) throw invalid("invalid_arguments", key + " must not be empty.");
        return value;
    }
    private static String requiredStringAllowEmpty(JSONObject args, String key) throws InvalidRequest {
        Object value = args.opt(key);
        if (!(value instanceof String)) throw invalid("invalid_arguments", key + " must be a string.");
        return (String) value;
    }
    private static float coordinate(JSONObject args, String key, int limit) throws InvalidRequest {
        Object value = args.opt(key);
        if (!(value instanceof Number)) throw invalid("invalid_arguments", key + " must be a display coordinate.");
        double coordinate = ((Number) value).doubleValue();
        if (!Double.isFinite(coordinate) || coordinate < 0 || coordinate >= limit) {
            throw invalid("invalid_coordinate", key + " is outside the observed display.");
        }
        return (float) coordinate;
    }
    private static long requiredInteger(JSONObject args, String key, long minimum, long maximum) throws InvalidRequest {
        Object value = args.opt(key);
        if (!(value instanceof Number)) throw invalid("invalid_arguments", key + " must be an integer.");
        double number = ((Number) value).doubleValue();
        if (!Double.isFinite(number) || number != Math.rint(number) || number < minimum || number > maximum) {
            throw invalid("invalid_arguments", key + " is outside its allowed range.");
        }
        return (long) number;
    }
    private static JSONObject unavailable() { return object("ok", false, "connected", false, "available", false, "error", "accessibility_not_connected", "message", "The Android accessibility service is not connected. Its authorization may still be enabled in Android accessibility settings."); }
    private static JSONObject error(String code, String message) { return object("ok", false, "error", code, "message", message); }
    private static JSONObject object(Object... pairs) {
        JSONObject object = new JSONObject();
        try { for (int i = 0; i < pairs.length; i += 2) object.put((String) pairs[i], pairs[i + 1] == null ? JSONObject.NULL : pairs[i + 1]); }
        catch (JSONException impossible) { throw new IllegalArgumentException("Invalid JSON response", impossible); }
        return object;
    }
    private static InvalidRequest invalid(String code, String message) { return new InvalidRequest(code, message); }
    private static final class InvalidRequest extends Exception {
        final String code;
        InvalidRequest(String code, String message) { super(message); this.code = code; }
    }
}
