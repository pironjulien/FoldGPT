package app.foldgpt.shizukuprobe;

import rikka.shizuku.ShizukuProvider;

/** Keep the standard provider protocol, explicitly excluding Sui initialization. */
public final class ProbeProvider extends ShizukuProvider {
    @Override public boolean onCreate() {
        ShizukuProvider.disableAutomaticSuiInitialization();
        return super.onCreate();
    }
}
