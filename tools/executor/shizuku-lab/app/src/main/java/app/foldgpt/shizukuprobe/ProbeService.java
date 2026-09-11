package app.foldgpt.shizukuprobe;

import android.content.Context;
import android.os.Binder;
import android.os.Process;
import android.system.Os;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;

/** Fixed qualification operations. No caller-supplied command, path or arguments. */
public final class ProbeService extends IQualificationService.Stub {
    private static final int MAX_PROC_BYTES = 65536;
    private final int clientUid;

    public ProbeService(Context context) {
        if (!BuildConfig.APPLICATION_ID.equals(context.getPackageName())) {
            throw new SecurityException("Unexpected package context");
        }
        if (Os.getuid() != 2000) {
            throw new SecurityException("Qualification requires non-root shell UID 2000");
        }
        clientUid = context.getApplicationInfo().uid;
        if (clientUid < 10000 || clientUid == 2000) {
            throw new SecurityException("No distinct application UID");
        }
    }

    private void requireClient() {
        if (Binder.getCallingUid() != clientUid) {
            throw new SecurityException("Caller is not the qualification application");
        }
    }

    @Override public synchronized String collectContext() {
        requireClient();
        try {
            JSONObject report = new JSONObject();
            report.put("schema", "foldgpt.shizuku.context.v1");
            report.put("observedAtMillis", System.currentTimeMillis());
            report.put("serviceUid", Os.getuid());
            report.put("serviceGid", Os.getgid());
            report.put("servicePid", Os.getpid());
            report.put("parentPid", Os.getppid());
            report.put("authorizedClientUid", clientUid);
            report.put("callingUid", Binder.getCallingUid());
            report.put("callingPid", Binder.getCallingPid());
            JSONObject status = readText("/proc/self/status");
            JSONObject selinux = readText("/proc/self/attr/current");
            report.put("status", status);
            report.put("threadStatus", readText("/proc/thread-self/status"));
            report.put("selinux", selinux);
            report.put("cmdline", readText("/proc/self/cmdline"));
            report.put("cwd", readLink("/proc/self/cwd"));
            report.put("exe", readLink("/proc/self/exe"));
            report.put("parentStatus", readText("/proc/" + Os.getppid() + "/status"));
            report.put("parentCmdline", readText("/proc/" + Os.getppid() + "/cmdline"));
            report.put("limits", readText("/proc/self/limits"));
            JSONArray descriptors = new JSONArray();
            String[] names = new File("/proc/self/fd").list();
            if (names != null) {
                for (String name : names) {
                    JSONObject fd = readLink("/proc/self/fd/" + name);
                    fd.put("fd", name);
                    descriptors.put(fd);
                }
            }
            report.put("fileDescriptors", descriptors);
            report.put("commandsExecuted", 0);
            report.put("success", status.optBoolean("ok") && selinux.optBoolean("ok"));
            report.put("probeScope", "read-only context; no namespace/seccomp/ptrace installation");
            return report.toString(2);
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }

    private static JSONObject readText(String path) throws Exception {
        JSONObject result = new JSONObject().put("path", path);
        try (FileInputStream input = new FileInputStream(path)) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] bytes = new byte[4096];
            int count;
            while ((count = input.read(bytes)) != -1) {
                if (output.size() + count > MAX_PROC_BYTES) {
                    throw new IllegalStateException("Proc entry exceeded read budget");
                }
                output.write(bytes, 0, count);
            }
            result.put("ok", true);
            result.put("text", output.toString(StandardCharsets.UTF_8).replace('\0', ' ').trim());
        } catch (Exception error) {
            result.put("ok", false);
            result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage());
        }
        return result;
    }

    @Override public synchronized String runFixed() {
        requireClient();
        try {
            return FixedProbe.run(new JSONObject(collectContext())).toString(2);
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }

    private static JSONObject readLink(String path) throws Exception {
        JSONObject result = new JSONObject().put("path", path);
        try {
            result.put("ok", true);
            result.put("target", Os.readlink(path));
        } catch (Exception error) {
            result.put("ok", false);
            result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage());
        }
        return result;
    }

    @Override public synchronized void destroy() {
        int caller = Binder.getCallingUid();
        if (caller != clientUid && caller != 2000) {
            throw new SecurityException("Unauthorized service destruction");
        }
        if (FixedProbe.cleanupUnresolved()) {
            throw new IllegalStateException("Native cleanup is unresolved; retaining process ownership");
        }
        // Exit only this owned process after any fixed native run was cleaned up.
        Process.killProcess(Process.myPid());
    }
}
