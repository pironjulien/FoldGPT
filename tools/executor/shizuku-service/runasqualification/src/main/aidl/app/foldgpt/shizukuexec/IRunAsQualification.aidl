package app.foldgpt.shizukuexec;
interface IRunAsQualification {
    String preflight() = 1;
    void start(IBinder owner, String expectedInstallation) = 2;
    String status() = 3;
    void cancel() = 4;
    void destroy() = 16777114;
}
