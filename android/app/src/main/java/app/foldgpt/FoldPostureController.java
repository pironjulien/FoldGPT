package app.foldgpt;

import android.app.Activity;
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Display;
import android.view.WindowManager;
import androidx.core.util.Consumer;
import androidx.window.WindowSdkExtensions;
import androidx.window.java.layout.WindowInfoTrackerCallbackAdapter;
import androidx.window.layout.DisplayFeature;
import androidx.window.layout.FoldingFeature;
import androidx.window.layout.WindowInfoTracker;
import androidx.window.layout.WindowLayoutInfo;

/**
 * Read-only inner-display gate using the OEM's public WindowManager extension.
 *
 * The display-area WindowContext is deliberately independent from the Activity:
 * an inner-screen split window may not intersect the hinge and must not be
 * classified as folded. No dimensions, Samsung state IDs, sensors with guessed
 * thresholds, hidden DeviceStateManager APIs or device-state requests are used.
 */
final class FoldPostureController implements AutoCloseable {
    enum State { WAITING, INNER, NO_INNER_FEATURE, UNAVAILABLE }
    interface Listener { void onPostureChanged(State state); }

    private final Activity activity;
    private final Listener listener;
    private final DisplayManager displays;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final WindowInfoTrackerCallbackAdapter tracker;
    private final Consumer<WindowLayoutInfo> layoutListener = this::onLayout;
    private final DisplayManager.DisplayListener displayListener = new DisplayManager.DisplayListener() {
        @Override public void onDisplayAdded(int id) { refreshDisplay(); }
        @Override public void onDisplayRemoved(int id) { refreshDisplay(); }
        @Override public void onDisplayChanged(int id) { refreshDisplay(); }
    };
    private Context displayArea;
    private int trackedDisplay = Display.INVALID_DISPLAY;
    private boolean running;
    private boolean supported;
    private State state = State.WAITING;

    FoldPostureController(Activity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
        displays = activity.getSystemService(DisplayManager.class);
        tracker = new WindowInfoTrackerCallbackAdapter(WindowInfoTracker.getOrCreate(activity));
    }

    State getState() { return state; }

    void start() {
        if (running) return;
        running = true;
        int extension = WindowSdkExtensions.getInstance().getExtensionVersion();
        Log.i("FoldGPT-Posture", "Window extension=" + extension);
        // Context listeners need extension 2. Do not interpret an unsupported
        // API's empty response as evidence that the physical device is folded.
        if (Build.VERSION.SDK_INT < 31 || extension < 2 || displays == null) {
            publish(State.UNAVAILABLE);
            return;
        }
        supported = true;
        displays.registerDisplayListener(displayListener, main);
        refreshDisplay();
    }

    void refreshDisplay() {
        if (!running || !supported) return;
        Display display = activity.getDisplay();
        if (display == null || !display.isValid()) {
            detachContext();
            publish(State.WAITING);
            return;
        }
        if (displayArea != null && trackedDisplay == display.getDisplayId()) return;
        detachContext();
        publish(State.WAITING);
        try {
            // No overlay/window is added and no overlay permission is requested.
            // Android associates this context with the display's application area.
            displayArea = activity.getApplicationContext().createWindowContext(
                    display, WindowManager.LayoutParams.TYPE_APPLICATION, null);
            trackedDisplay = display.getDisplayId();
            tracker.addWindowLayoutInfoListener(displayArea, activity.getMainExecutor(), layoutListener);
        } catch (RuntimeException exception) {
            detachContext();
            Log.w("FoldGPT-Posture", "Display-area posture API unavailable", exception);
            publish(State.UNAVAILABLE);
        }
    }

    private void onLayout(WindowLayoutInfo info) {
        if (!running) return;
        boolean inner = false;
        for (DisplayFeature feature : info.getDisplayFeatures()) {
            if (!(feature instanceof FoldingFeature)) continue;
            FoldingFeature.State fold = ((FoldingFeature) feature).getState();
            if (fold == FoldingFeature.State.FLAT || fold == FoldingFeature.State.HALF_OPENED) {
                inner = true;
                break;
            }
        }
        Log.i("FoldGPT-Posture", "Display-area layout=" + info + " inner=" + inner);
        // Empty layout means there is no usable inner folding feature on this
        // display, not a claim about a Samsung physical posture identifier.
        publish(inner ? State.INNER : State.NO_INNER_FEATURE);
    }

    private void publish(State next) {
        if (state == next) return;
        state = next;
        listener.onPostureChanged(next);
    }

    private void detachContext() {
        if (displayArea != null) tracker.removeWindowLayoutInfoListener(layoutListener);
        displayArea = null;
        trackedDisplay = Display.INVALID_DISPLAY;
    }

    @Override public void close() {
        running = false;
        if (supported) displays.unregisterDisplayListener(displayListener);
        supported = false;
        detachContext();
    }
}
