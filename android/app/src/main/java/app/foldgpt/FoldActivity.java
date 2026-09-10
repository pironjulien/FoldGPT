package app.foldgpt;

import android.app.ActivityOptions;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.IntentSender;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.PowerManager;
import android.util.Log;
import android.view.View;
import android.widget.Toast;
import com.termux.x11.FoldRuntimeService;
import com.termux.x11.FoldDisplayActivity;

/** Display host with a peer-credential checked IME endpoint. No text crosses this bridge. */
public final class FoldActivity extends FoldDisplayActivity {
    private static volatile boolean visible;
    private static volatile boolean windowFocused;
    private static volatile FoldActivity current;
    public static boolean isVisible() { return visible && windowFocused; }
    /** One nonblocking input frame on the Android main looper. No text is logged. */
    public static int sendLinuxInput(int code, boolean unicode, boolean down) {
        FoldActivity activity = current;
        if (activity == null || !isVisible() || !activity.innerDisplay
                || !activity.canHandleDisplayTransition() || !activity.getLorieView().connected()) return -1;
        return activity.getLorieView().sendInputEventChecked(code, unicode, down);
    }
    /** Release an already issued key even when Android took focus in the meantime. */
    public static int releaseLinuxKey(int key) {
        FoldActivity activity = current;
        if (activity == null || !activity.getLorieView().connected()) return -1;
        return activity.getLorieView().sendInputEventChecked(key, false, false);
    }
    private volatile boolean resumed;
    private final FoldImeBridge imeBridge = FoldImeBridge.get();
    private final FoldUrlBridge urlBridge = FoldUrlBridge.get();
    private FoldPostureController posture;
    private boolean innerDisplay;
    private boolean redirecting;
    private String pendingConnectorCallback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        current = this;
        FoldAndroidBridge.start(this);
        acceptConnectorCallback(getIntent());
        // The desktop client enforces a minimum window height. Keep its canvas
        // and let LorieView follow the input cursor above the Android keyboard.
        prefs.Reseed.put(false);
        // Background computation uses the service's partial CPU wake lock.
        // The display must follow Android's normal idle/screen-off policy.
        prefs.screenIdleTimeout.put("system");
        if (!getPreferences(MODE_PRIVATE).getBoolean("configured", false)) {
            prefs.fullscreen.put(true);
            prefs.showAdditionalKbd.put(false);
            prefs.touchMode.put("3");
            getPreferences(MODE_PRIVATE).edit().putBoolean("configured", true).apply();
        }
        imeBridge.attach(this);
        urlBridge.attach(this);
        // Gate the containing view, since the X11 view manages its own visibility
        // when the server reconnects. Keep Linux private until inner-display proof.
        findViewById(android.R.id.content).setVisibility(View.INVISIBLE);
        posture = new FoldPostureController(this, this::onPostureChanged);
        posture.start();
    }
    @Override public void onResume() {
        super.onResume();
        resumed = true;
        visible = true;
        imeBridge.resume(this);
        urlBridge.resume(this);
        if (posture != null) {
            posture.refreshDisplay();
            onPostureChanged(posture.getState());
        }
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        acceptConnectorCallback(intent);
        requestRuntimeLaunch();
        if (posture != null) onPostureChanged(posture.getState());
    }
    @Override public void onPause() {
        resumed = false;
        visible = false;
        imeBridge.pause(this);
        urlBridge.pause(this);
        super.onPause();
    }
    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (posture != null) posture.refreshDisplay();
    }
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        windowFocused = hasFocus;
        // A posture notification may arrive while the screen is turning off or
        // the keyguard owns the window. Reconsider it when this Activity really
        // becomes interactive; never wake/unlock the device to finish a handoff.
        if (hasFocus && posture != null) onPostureChanged(posture.getState());
    }
    private boolean canHandleDisplayTransition() {
        PowerManager power = getSystemService(PowerManager.class);
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        return resumed && hasWindowFocus() && power != null && power.isInteractive()
                && keyguard != null && !keyguard.isKeyguardLocked() && !keyguard.isDeviceLocked();
    }
    private boolean isPostureBypassed() {
        return getIntent() != null && getIntent().getBooleanExtra("app.foldgpt.BYPASS_POSTURE", false);
    }
    private void acceptConnectorCallback(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction()) || intent.getData() == null) return;
        try {
            String callback = FoldConnectorCallback.validate(intent.getDataString());
            if (pendingConnectorCallback != null && !pendingConnectorCallback.equals(callback)) {
                intent.setData(android.net.Uri.parse(pendingConnectorCallback));
                Toast.makeText(this, "Un retour de connexion est déjà en attente. Reprenez cette connexion après le premier.", Toast.LENGTH_LONG).show();
                return;
            }
            pendingConnectorCallback = callback;
        } catch (IllegalArgumentException error) {
            intent.setData(pendingConnectorCallback == null ? null : android.net.Uri.parse(pendingConnectorCallback));
            Log.w("FoldGPT-Connector", "Rejected invalid connector callback");
            Toast.makeText(this, "Ce retour de connexion n’est pas reconnu par FoldGPT.", Toast.LENGTH_LONG).show();
        }
    }
    private void startRuntimeWithPendingActions() {
        if (!hasPendingRuntimeLaunch()) return;
        boolean sendCallback = pendingConnectorCallback != null && canHandleDisplayTransition();
        if (pendingConnectorCallback != null && !sendCallback) return;
        Intent start = new Intent(this, FoldRuntimeService.class).setAction(FoldRuntimeService.ACTION_START);
        String thread = getIntent().getStringExtra(FoldRuntimeService.EXTRA_THREAD);
        if (thread != null) start.putExtra(FoldRuntimeService.EXTRA_THREAD, thread);
        if (sendCallback) start.putExtra(FoldRuntimeService.EXTRA_CONNECTOR_CALLBACK, pendingConnectorCallback);
        try {
            startForegroundService(start);
            runtimeLaunchDispatched();
            getIntent().removeExtra(FoldRuntimeService.EXTRA_THREAD);
            if (sendCallback) {
                pendingConnectorCallback = null;
                getIntent().setData(null); // Activity recreation must not resubmit the callback.
            }
        } catch (RuntimeException error) {
            if (!sendCallback) throw error;
            // Android exceptions may include Intent extras; log no exception payload.
            Log.e("FoldGPT-Connector", "Could not start the runtime for the pending action");
            Toast.makeText(this, "ChatGPT n’a pas pu recevoir le retour de connexion. Réessayez après son démarrage.", Toast.LENGTH_LONG).show();
        }
    }
    @Override protected void onRuntimeRetryRequested() {
        if (posture != null) onPostureChanged(posture.getState());
    }
    private boolean isDesktopEnvironment() {
        Configuration config = getResources().getConfiguration();
        try {
            java.lang.reflect.Field field = config.getClass().getField("semDesktopModeEnabled");
            if (field.getInt(config) == 1) return true;
        } catch (Throwable ignored) { }
        android.app.UiModeManager uiModeManager = getSystemService(android.app.UiModeManager.class);
        if (uiModeManager != null && uiModeManager.getCurrentModeType() == Configuration.UI_MODE_TYPE_DESK) {
            return true;
        }
        return false;
    }
    private void onPostureChanged(FoldPostureController.State state) {
        if (isDestroyed() || isFinishing()) return;
        boolean bypassed = isPostureBypassed() || isDesktopEnvironment();
        innerDisplay = bypassed || state == FoldPostureController.State.INNER;
        findViewById(android.R.id.content).setVisibility(innerDisplay ? View.VISIBLE : View.INVISIBLE);
        if (innerDisplay) {
            if (canHandleDisplayTransition() || bypassed) {
                startRuntimeWithPendingActions();
            }
            return;
        }
        getLorieView().setKeyboardVisible(false);
        if (!canHandleDisplayTransition() || state == FoldPostureController.State.WAITING || redirecting) return;
        // A return from Android's browser also reaches the Linux client if the
        // phone was folded during authorization, before display handoff finishes.
        if (pendingConnectorCallback != null) startRuntimeWithPendingActions();
        redirecting = true;
        if (state == FoldPostureController.State.UNAVAILABLE) {
            Toast.makeText(this, "La détection de l’écran intérieur est indisponible.", Toast.LENGTH_LONG).show();
        }
        try {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                // Public API that is not filtered by package visibility. The
                // package was verified on the device; no exported class is fixed.
                IntentSender launch = getPackageManager().getLaunchIntentSenderForPackage("com.openai.chatgpt");
                Bundle options = null;
                if (android.os.Build.VERSION.SDK_INT >= 36) {
                    // Delegate only the authority this visible Activity already
                    // holds, as required by current PendingIntent launch rules.
                    options = ActivityOptions.makeBasic().setPendingIntentBackgroundActivityStartMode(
                            ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE).toBundle();
                }
                startIntentSender(launch, null, 0, 0, 0, options);
            } else {
                Intent launch = getPackageManager().getLaunchIntentForPackage("com.openai.chatgpt");
                if (launch != null) startActivity(launch);
            }
        } catch (IntentSender.SendIntentException | RuntimeException exception) {
            Log.w("FoldGPT-Posture", "Official Android client could not be opened", exception);
            Toast.makeText(this, "Ouvrez FoldGPT sur l’écran intérieur.", Toast.LENGTH_LONG).show();
        }
        // Finish only the display Activity. The independent started foreground
        // service keeps Linux/tasks alive until the explicit notification Stop.
        finish();
    }
    @Override protected void onDestroy() {
        if (current == this) current = null;
        resumed = false;
        if (posture != null) posture.close();
        imeBridge.detach(this);
        urlBridge.detach(this);
        super.onDestroy();
    }
    boolean applyImeVisibility(boolean show) {
        boolean allowed = !isDestroyed() && !isFinishing() && (!show || (innerDisplay && resumed && hasWindowFocus()));
        if (allowed) getLorieView().setKeyboardVisible(show);
        return allowed;
    }
}
