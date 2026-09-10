package app.foldgpt.recovery;

import android.app.ActivityManager;
import android.app.ActivityOptions;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;

/** Separate test APK. It creates a real orphan; all recovery is production code. */
public final class HardCrashInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }

    private static String hash(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) out.append(String.format("%02x", value & 255));
        return out.toString();
    }
    private static JSONObject json(File file) throws Exception { return new JSONObject(Files.readString(file.toPath())); }
    private static void require(boolean value, String message) { if (!value) throw new IllegalStateException(message); }
    private JSONObject waitReady(File files, int oldBroker, long deadline) throws Exception {
        while (SystemClock.elapsedRealtime() < deadline) {
            try {
                JSONObject owner = json(new File(files, "native-executor-status.json"));
                JSONObject intent = json(new File(files, "runtime-user-intent.json"));
                int broker = owner.getJSONObject("lastNativeSessionStatus").getInt("bootstrapPid");
                if ("ready".equals(owner.getString("state")) && "ready".equals(intent.getString("state"))
                        && intent.getBoolean("wanted") && broker > 0 && broker != oldBroker) return owner;
            } catch (Exception ignored) { /* A partially written or absent observation is not readiness. */ }
            SystemClock.sleep(250);
        }
        throw new IllegalStateException("Production client did not become ready within the test deadline");
    }
    @Override public void onStart() {
        Context target = getTargetContext();
        File output = new File(target.getFilesDir(), "hard-crash-instrumentation.json");
        JSONObject result = new JSONObject();
        Bundle summary = new Bundle();
        try {
            result.put("schema", "foldgpt.real-hard-crash-test.v1").put("success", false)
                    .put("uid", Os.getuid()).put("package", target.getPackageName());
            require("app.foldgpt".equals(target.getPackageName()) && Os.getuid() == target.getApplicationInfo().uid, "Wrong test target");
            Intent launch = new Intent().setClassName("app.foldgpt", "app.foldgpt.FoldActivity")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ActivityOptions options = ActivityOptions.makeBasic(); options.setLaunchDisplayId(0);
            startActivitySync(launch, options.toBundle());
            File files = target.getFilesDir();
            JSONObject before = waitReady(files, -1, SystemClock.elapsedRealtime() + 90_000);
            int broker = before.getJSONObject("lastNativeSessionStatus").getInt("bootstrapPid");
            int runtime = -1;
            for (ActivityManager.RunningAppProcessInfo process : target.getSystemService(ActivityManager.class).getRunningAppProcesses()) {
                if (process.uid == Os.getuid() && "app.foldgpt:runtime".equals(process.processName)) runtime = process.pid;
            }
            require(runtime > 0 && runtime != Os.getpid() && broker != Os.getpid(), "Wrong runtime identity");
            File directory = new File(files.getParentFile(), "app_foldgpt_exec");
            File marker = new File(directory, "process-session.json");
            byte[] original = Files.readAllBytes(marker.toPath());
            JSONObject originalMarker = new JSONObject(new String(original, java.nio.charset.StandardCharsets.UTF_8));
            require(originalMarker.getInt("brokerPid") == broker && originalMarker.getInt("uid") == Os.getuid(), "Marker/owner mismatch");
            android.system.StructStat identity = Os.lstat(marker.getPath());
            String digest = hash(original);
            result.put("oldBroker", broker).put("oldRuntime", runtime).put("oldMarkerSha256", digest)
                    .put("markerDevice", identity.st_dev).put("markerInode", identity.st_ino);
            Files.writeString(output.toPath(), result.toString(2));
            // Abruptly kill the owner before its Java parent, leaving no chance
            // to remove its marker on control-pipe EOF. Android owns group exit.
            // No marker, project, preference or history file is repaired here.
            long at = SystemClock.elapsedRealtime();
            Os.kill(broker, OsConstants.SIGKILL);
            Os.kill(runtime, OsConstants.SIGKILL);
            JSONObject after = waitReady(files, broker, at + 90_000);
            result.put("clientReadyAfterMs", SystemClock.elapsedRealtime() - at)
                    .put("newBroker", after.getJSONObject("lastNativeSessionStatus").getInt("bootstrapPid"));
            JSONObject receipt = null;
            File[] archives = directory.listFiles(file -> file.isDirectory() && file.getName().startsWith("recovered-same-boot-"));
            require(archives != null, "Cannot enumerate recovery receipts");
            for (File archive : archives) {
                JSONObject candidate = json(new File(archive, "recovery.json"));
                if (!digest.equals(candidate.optString("markerSha256"))) continue;
                File archived = new File(archive, "process-session.json");
                android.system.StructStat moved = Os.lstat(archived.getPath());
                require(hash(Files.readAllBytes(archived.toPath())).equals(digest), "Marker bytes changed");
                require(moved.st_dev == identity.st_dev && moved.st_ino == identity.st_ino, "Marker inode changed");
                receipt = candidate;
                result.put("archiveName", archive.getName());
            }
            require(receipt != null && !receipt.getBoolean("previousCleanupClaimed") && !receipt.getBoolean("previousBootEnded"), "No honest same-boot recovery receipt");
            result.put("receipt", receipt).put("success", true).put("productFilesRepairedByTest", false)
                    .put("explicitStartAfterCrash", false).put("signals", "SIGKILL old broker and old runtime");
            summary.putString("result", "PASS");
        } catch (Throwable error) {
            try { result.put("success", false).put("error", error.toString()); } catch (Exception ignored) { }
            summary.putString("result", "FAIL: " + error);
        } finally {
            try { Files.writeString(output.toPath(), result.toString(2)); }
            catch (Exception error) { summary.putString("writeError", error.toString()); }
            finish(result.optBoolean("success") ? -1 : 0, summary);
        }
    }
}
