package app.foldgpt.shizukuexec;
import app.foldgpt.shizukuexec.IExecutorSession;
interface IExecutorService {
    IExecutorSession open(IBinder owner) = 1;
    String status() = 2;
    String preflight() = 3;
    IExecutorSession openNative(IBinder owner, String launchPath, String nonce) = 4;
    void destroy() = 16777114;
}
