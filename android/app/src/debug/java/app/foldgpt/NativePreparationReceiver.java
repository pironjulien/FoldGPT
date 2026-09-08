package app.foldgpt;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import com.termux.x11.FoldRuntimeService;

/** ADB-only entry to the real lifecycle; no alternate executor or input paths. */
public final class NativePreparationReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null) throw new IllegalArgumentException("Native lifecycle action is required");
        String action = intent.getAction();
        Intent service = new Intent(context, FoldRuntimeService.class);
        if (FoldExecutorRuntime.ACTION_PREPARE.equals(action)) {
            context.startForegroundService(service.setAction(FoldExecutorRuntime.ACTION_PREPARE));
        } else if ("app.foldgpt.action.STOP_NATIVE_EXECUTOR".equals(action)) {
            context.startForegroundService(service.setAction("stop"));
        } else throw new SecurityException("Only native prepare or stop is accepted");
    }
}
