package app.foldgpt.shizukuexec;

final class NativeSpawn {
    private NativeSpawn() {}
    static synchronized void load(String path) { System.load(path); }
    static native int launch(String executable, String[] argv, int input, int output, int report, int control);
    /** Returns the real waitpid status; reaps exactly this direct child, once. */
    static native int waitChild(int pid);
}
