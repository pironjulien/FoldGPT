package app.foldgpt.shizukuexec;

/** Official Binder delivery only. No Sui/root initialization or ADB settings. */
public final class ExecutorProvider extends rikka.shizuku.ShizukuProvider {
    @Override public boolean onCreate() {
        rikka.shizuku.ShizukuProvider.disableAutomaticSuiInitialization();
        rikka.shizuku.ShizukuProvider.enableMultiProcessSupport(true);
        return super.onCreate();
    }
}
