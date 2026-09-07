package app.foldgpt.shizukuexec;
import app.foldgpt.shizukuexec.IExecutorSession;
interface IExecutorService {
    IExecutorSession open(IBinder owner) = 1;
    String status() = 2;
    String preflight() = 3;
    void destroy() = 16777114;
}
