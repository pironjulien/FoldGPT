package app.foldgpt.shizukuexec;
import android.os.ParcelFileDescriptor;
interface IExecutorSession {
    ParcelFileDescriptor takeInput() = 1;
    ParcelFileDescriptor takeOutput() = 2;
    void cancel() = 3;
    String status() = 4;
}
