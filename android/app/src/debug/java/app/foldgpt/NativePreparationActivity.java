package app.foldgpt;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;
import com.termux.x11.FoldRuntimeService;

/** Debug-only foreground entry to the actual native service lifecycle. */
public final class NativePreparationActivity extends Activity {
    private boolean dispatched;
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        TextView label = new TextView(this);
        label.setText("FoldGPT — validation native en cours");
        setContentView(label);
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        dispatched = false;
    }
    @Override protected void onResume() {
        super.onResume();
        if (dispatched) return;
        dispatched = true;
        String action = getIntent().getAction();
        Intent service = new Intent(this, FoldRuntimeService.class);
        if (FoldExecutorRuntime.ACTION_PREPARE.equals(action)) {
            startForegroundService(service.setAction(action));
        } else if ("app.foldgpt.action.STOP_NATIVE_EXECUTOR".equals(action)) {
            startForegroundService(service.setAction("stop"));
        } else throw new SecurityException("Only fixed native lifecycle actions are accepted");
    }
}
