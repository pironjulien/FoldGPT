package app.foldgpt.shizukuexec;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Process;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;

/** System-reported Java app processes, pinned to their kernel start times.
 * This is an allowed population for recovery, never a claim that native
 * descendants are absent. The native owner must establish that independently.
 */
public final class AndroidProcessPopulation {
    private static final String SCHEMA = "foldgpt.android-process-population.v1";
    private static final String SOURCE = "android.app.ActivityManager.getRunningAppProcesses";
    // Linux PID_MAX_LIMIT for a 64-bit kernel; shared with the native contract.
    private static final int PID_UPPER_EXCLUSIVE = 4 * 1024 * 1024;
    private AndroidProcessPopulation() {}

    public static JSONObject capture(Context context) throws Exception {
        int uid = context.getApplicationInfo().uid;
        if (uid < 10000 || uid != Process.myUid())
            throw new SecurityException("Process population must belong to the application");
        ActivityManager manager = context.getSystemService(ActivityManager.class);
        var observed = manager.getRunningAppProcesses();
        if (observed == null) throw new SecurityException("Android process population is unavailable");
        JSONArray processes = new JSONArray();
        boolean hasRuntime = false;
        for (ActivityManager.RunningAppProcessInfo item : observed) {
            if (item.uid != uid) continue;
            if (!("app.foldgpt".equals(item.processName) || "app.foldgpt:runtime".equals(item.processName)))
                throw new SecurityException("Unexpected Android process shares the app UID");
            long ticks = startTime(Files.readString(Path.of("/proc", Integer.toString(item.pid), "stat")), item.pid);
            processes.put(new JSONObject().put("pid", item.pid).put("processName", item.processName)
                    .put("startTimeTicks", ticks));
            if (item.pid == Process.myPid() && "app.foldgpt:runtime".equals(item.processName)) hasRuntime = true;
        }
        if (!hasRuntime) throw new SecurityException("Current runtime is absent from Android's process population");
        JSONObject result = new JSONObject().put("schema", SCHEMA).put("source", SOURCE).put("processes", processes);
        validate(result);
        return result;
    }

    static long startTime(String stat, int pid) {
        int close = stat.lastIndexOf(')');
        if (pid <= 0 || !stat.startsWith(pid + " (") || close < 0 || close + 2 >= stat.length())
            throw new SecurityException("Malformed kernel process identity");
        String[] fields = stat.substring(close + 2).trim().split("\\s+");
        if (fields.length < 20 || !fields[19].matches("[0-9]+"))
            throw new SecurityException("Missing kernel process start time");
        long ticks = Long.parseLong(fields[19]);
        if (ticks <= 0) throw new SecurityException("Invalid kernel process start time");
        return ticks;
    }

    static void validate(JSONObject value) throws Exception {
        if (value.length() != 3 || !SCHEMA.equals(value.get("schema")) || !SOURCE.equals(value.get("source"))
                || !(value.get("processes") instanceof JSONArray))
            throw new SecurityException("Process population contract differs");
        JSONArray processes = value.getJSONArray("processes");
        if (processes.length() < 1 || processes.length() > 2)
            throw new SecurityException("Unexpected Android app process count");
        Set<Integer> pids = new HashSet<>();
        Set<String> names = new HashSet<>();
        for (int i = 0; i < processes.length(); i++) {
            JSONObject row = processes.getJSONObject(i);
            Object ticks = row.get("startTimeTicks");
            if (row.length() != 3 || !(row.get("pid") instanceof Integer) || row.getInt("pid") <= 0
                    || row.getInt("pid") >= PID_UPPER_EXCLUSIVE
                    || !(ticks instanceof Integer || ticks instanceof Long) || row.getLong("startTimeTicks") <= 0
                    || !(row.get("processName") instanceof String)
                    || !("app.foldgpt".equals(row.getString("processName")) || "app.foldgpt:runtime".equals(row.getString("processName")))
                    || !pids.add(row.getInt("pid")) || !names.add(row.getString("processName")))
                throw new SecurityException("Invalid or duplicated Android process identity");
        }
        if (!names.contains("app.foldgpt:runtime")) throw new SecurityException("Process population lacks runtime");
    }

    static void requireCurrent(Context context, JSONObject declared) throws Exception {
        validate(declared);
        JSONObject current = capture(context);
        JSONArray rows = declared.getJSONArray("processes"), now = current.getJSONArray("processes");
        if (rows.length() != now.length()) throw new SecurityException("Android app population changed before fork");
        for (int i = 0; i < rows.length(); i++) {
            boolean match = false;
            for (int j = 0; j < now.length(); j++) {
                JSONObject a = rows.getJSONObject(i), b = now.getJSONObject(j);
                if (a.getInt("pid") == b.getInt("pid") && a.getLong("startTimeTicks") == b.getLong("startTimeTicks")
                        && a.getString("processName").equals(b.getString("processName"))) match = true;
            }
            if (!match) throw new SecurityException("Android app identity changed before fork");
        }
    }
}
