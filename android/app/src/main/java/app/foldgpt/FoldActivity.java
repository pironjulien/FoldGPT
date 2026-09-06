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
    private volatile boolean resumed;
    private final FoldImeBridge imeBridge = FoldImeBridge.get();
    private FoldPostureController posture;
    private boolean innerDisplay;
    private boolean redirecting;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
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
        // Gate the containing view, since the X11 view manages its own visibility
        // when the server reconnects. Keep Linux private until inner-display proof.
        findViewById(android.R.id.content).setVisibility(View.INVISIBLE);
        posture = new FoldPostureController(this, this::onPostureChanged);
        posture.start();
    }
    @Override public void onResume() {
        super.onResume();
        resumed = true;
        imeBridge.resume(this);
        if (posture != null) {
            posture.refreshDisplay();
            onPostureChanged(posture.getState());
        }
    }
    @Override public void onPause() {
        resumed = false;
        imeBridge.pause(this);
        super.onPause();
    }
    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (posture != null) posture.refreshDisplay();
    }
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
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
    private void onPostureChanged(FoldPostureController.State state) {
        if (isDestroyed() || isFinishing()) return;
        innerDisplay = state == FoldPostureController.State.INNER;
        findViewById(android.R.id.content).setVisibility(innerDisplay ? View.VISIBLE : View.INVISIBLE);
        if (innerDisplay) {
            if (canHandleDisplayTransition()) startForegroundService(new Intent(this, FoldRuntimeService.class));
            return;
        }
        getLorieView().setKeyboardVisible(false);
        if (!canHandleDisplayTransition() || state == FoldPostureController.State.WAITING || redirecting) return;
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
        resumed = false;
        if (posture != null) posture.close();
        imeBridge.detach(this);
        super.onDestroy();
    }
    boolean applyImeVisibility(boolean show) {
        boolean allowed = !isDestroyed() && !isFinishing() && (!show || (innerDisplay && resumed && hasWindowFocus()));
        if (allowed) getLorieView().setKeyboardVisible(show);
        return allowed;
    }
}
