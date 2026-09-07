package app.foldgpt.shizukuprobe;

import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** One exact reviewed executable. The native program owns policy and descendants. */
final class FixedProbe {
    private static final String DIRECTORY = "/data/local/tmp/foldgpt-shizuku-lab";
    private static final String EXECUTABLE = DIRECTORY + "/probe";
    private static final long JAVA_DEADLINE_SECONDS = 45;
    // JSON escaping and Binder's UTF-16 wire representation can expand bytes.
    private static final int MAX_OUTPUT_BYTES = 32768;
    private static final long MAX_EXECUTABLE_BYTES = 67108864;
    private static final AtomicBoolean started = new AtomicBoolean();
    private static volatile java.lang.Process process;
    private static volatile boolean unresolved;

    private FixedProbe() {}

    static boolean cleanupUnresolved() {
        return unresolved || (process != null && process.isAlive());
    }

    static JSONObject run(JSONObject context) throws Exception {
        JSONObject result = new JSONObject().put("schema", "foldgpt.shizuku.fixed-probe.v1")
                .put("context", context).put("success", false).put("cleanup_complete", true)
                .put("nativeLaunches", 0).put("probePath", EXECUTABLE)
                .put("expectedSha256", BuildConfig.PROBE_SHA256)
                .put("observedAtMillis", System.currentTimeMillis());
        if (!started.compareAndSet(false, true)) {
            return result.put("error", "This service already attempted its fixed native qualification")
                    .put("cleanup_complete", !cleanupUnresolved());
        }
        if (BuildConfig.PROBE_SHA256.isEmpty()) {
            return result.put("error", "This build has no pinned native probe hash; execution refused");
        }
        if (!context.optBoolean("success", false)) {
            return result.put("error", "Actual service context could not be collected; execution refused");
        }
        try {
            StructStat directory = Os.lstat(DIRECTORY);
            StructStat binary = Os.lstat(EXECUTABLE);
            if (!OsConstants.S_ISDIR(directory.st_mode) || directory.st_uid != 2000
                    || (directory.st_mode & 0022) != 0) {
                throw new SecurityException("Probe directory must be a real shell-owned directory without group/other write");
            }
            if (!OsConstants.S_ISREG(binary.st_mode) || binary.st_uid != 2000
                    || (binary.st_mode & 0022) != 0 || (binary.st_mode & 0100) == 0
                    || binary.st_size <= 0 || binary.st_size > MAX_EXECUTABLE_BYTES) {
                throw new SecurityException("Probe must be a regular executable owned by shell, without group/other write");
            }
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (FileInputStream input = new FileInputStream(EXECUTABLE)) {
                byte[] buffer = new byte[8192];
                int count;
                long consumed = 0;
                while ((count = input.read(buffer)) != -1) {
                    consumed += count;
                    if (consumed > MAX_EXECUTABLE_BYTES) throw new SecurityException("Probe grew during hash read");
                    digest.update(buffer, 0, count);
                }
            }
            StringBuilder hex = new StringBuilder();
            for (byte value : digest.digest()) {
                hex.append(Character.forDigit((value >>> 4) & 15, 16));
                hex.append(Character.forDigit(value & 15, 16));
            }
            result.put("actualSha256", hex.toString());
            if (!BuildConfig.PROBE_SHA256.contentEquals(hex)) {
                throw new SecurityException("Fixed native probe hash differs from this APK");
            }
            ProcessBuilder builder = new ProcessBuilder(EXECUTABLE);
            builder.directory(new File(DIRECTORY));
            builder.environment().clear();
            // The audited native guard ignores this input and constructs fixture env.
            builder.environment().put("PATH", "/system/bin");
            unresolved = true;
            try {
                process = builder.start();
            } catch (Exception startError) {
                unresolved = false; // No Process was returned and no native run is claimed.
                throw startError;
            }
            // java.lang.Process on Android does not expose pid(); native output
            // supplies its actual identity. Starting a process is not fixture success.
            result.put("nativeLaunches", 1);
            process.getOutputStream().close();
            Capture stdout = new Capture(process.getInputStream(), "fixed-probe-stdout");
            Capture stderr = new Capture(process.getErrorStream(), "fixed-probe-stderr");
            stdout.start();
            stderr.start();
            boolean exited = process.waitFor(JAVA_DEADLINE_SECONDS, TimeUnit.SECONDS);
            result.put("processExited", exited).put("javaDeadlineSeconds", JAVA_DEADLINE_SECONDS);
            if (exited) {
                stdout.join(1000);
                stderr.join(1000);
                result.put("exitCode", process.exitValue());
            }
            result.put("stdout", stdout.snapshot()).put("stderr", stderr.snapshot());
            result.put("stdoutComplete", stdout.complete).put("stderrComplete", stderr.complete);
            result.put("stdoutTruncated", stdout.truncated).put("stderrTruncated", stderr.truncated);
            JSONObject nativeFinal = null;
            int finalRecords = 0;
            for (String line : stdout.snapshot().split("\n")) {
                try {
                    JSONObject entry = new JSONObject(line);
                    if ("probe-result".equals(entry.optString("type"))) {
                        finalRecords++;
                        nativeFinal = entry;
                    }
                } catch (Exception ignored) { /* Non-JSON native text is retained verbatim. */ }
            }
            if (nativeFinal != null) result.put("nativeFinal", nativeFinal);
            boolean finalShape = finalRecords == 1 && nativeFinal != null
                    && nativeFinal.opt("cleanup_complete") instanceof Boolean
                    && nativeFinal.opt("success") instanceof Boolean
                    && nativeFinal.opt("setupCompleted") instanceof Boolean
                    && isIntegral(nativeFinal.opt("exitCode"))
                    && isIntegral(nativeFinal.opt("signal"))
                    && nativeFinal.opt("outcome") instanceof String;
            boolean nativeSuccess = finalShape && nativeFinal.getBoolean("success");
            boolean finalCoherent = finalShape && exited && (nativeSuccess
                    ? nativeFinal.getBoolean("cleanup_complete") && nativeFinal.getBoolean("setupCompleted")
                        && nativeFinal.getLong("exitCode") == 0 && nativeFinal.getLong("signal") == 0
                        && "exited".equals(nativeFinal.getString("outcome")) && process.exitValue() == 0
                    : process.exitValue() != 0);
            result.put("nativeFinalRecords", finalRecords).put("nativeFinalValid", finalCoherent);
            boolean cleanup = exited && stdout.complete && stderr.complete
                    && finalCoherent && nativeFinal.getBoolean("cleanup_complete");
            unresolved = !cleanup;
            result.put("cleanup_complete", cleanup);
            result.put("success", cleanup && nativeSuccess
                    && !stdout.truncated && !stderr.truncated);
            if (!exited) {
                result.put("error", "Native guard exceeded its outer deadline; service retains process ownership and will not retry");
            } else if (!cleanup) {
                result.put("error", "Native exit did not prove complete descendant cleanup; service is retained");
            }
            return result;
        } catch (Exception error) {
            return result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage())
                    .put("cleanup_complete", !cleanupUnresolved());
        }
    }

    private static boolean isIntegral(Object value) {
        return value instanceof Integer || value instanceof Long;
    }

    private static final class Capture extends Thread {
        private final InputStream input;
        private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        volatile boolean complete;
        volatile boolean truncated;
        Capture(InputStream input, String name) { super(name); this.input = input; setDaemon(true); }
        @Override public void run() {
            try (InputStream stream = input) {
                byte[] bytes = new byte[4096];
                int count;
                while ((count = stream.read(bytes)) != -1) {
                    synchronized (buffer) {
                        int keep = Math.min(count, MAX_OUTPUT_BYTES - buffer.size());
                        if (keep > 0) buffer.write(bytes, 0, keep);
                        if (keep != count) truncated = true;
                    }
                }
                complete = true;
            } catch (Exception ignored) { complete = false; }
        }
        String snapshot() {
            synchronized (buffer) { return buffer.toString(StandardCharsets.UTF_8); }
        }
    }
}
