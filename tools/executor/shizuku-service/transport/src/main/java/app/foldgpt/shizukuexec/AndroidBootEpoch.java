package app.foldgpt.shizukuexec;

import android.content.Context;
import android.provider.Settings;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;

/** Android supplies the boot epoch before a model or controller can connect. */
public final class AndroidBootEpoch {
    static final String SCHEMA = "foldgpt.android-boot-epoch.v1";
    static final String SOURCE = "android.provider.Settings.Global.BOOT_COUNT";
    static final String LAUNCH_SCHEMA = "foldgpt.native-launch.v2";
    private AndroidBootEpoch() {}

    public static JSONObject capture(Context context) throws Exception {
        int uid = context.getApplicationInfo().uid;
        if (uid < 10000 || Os.getuid() != uid)
            throw new SecurityException("Boot epoch must be read by the actual application");
        // No default value: an absent, denied or malformed Android setting must
        // refuse startup rather than invent an epoch capable of releasing data.
        return metadata(Settings.Global.getInt(context.getContentResolver(), Settings.Global.BOOT_COUNT));
    }

    static JSONObject metadata(int count) throws Exception {
        if (count < 0) throw new SecurityException("Android boot count is invalid");
        return new JSONObject().put("schema", SCHEMA).put("source", SOURCE).put("bootCount", count);
    }

    static int readCount(JSONObject value) throws Exception {
        if (value.length() != 3 || !SCHEMA.equals(value.get("schema")) || !SOURCE.equals(value.get("source"))
                || !(value.get("bootCount") instanceof Integer) || value.getInt("bootCount") < 0)
            throw new SecurityException("Application boot epoch metadata differs from its exact contract");
        return value.getInt("bootCount");
    }

    static void requireCurrent(JSONObject value, int current) throws Exception {
        if (current < 0 || readCount(value) != current)
            throw new SecurityException("Application launch belongs to another or unknown Android boot");
    }

    /** Repeat the provider read against the private launch immediately before fork. */
    static void verifyLaunch(Context context, File launch) throws Exception {
        int current = readCount(capture(context));
        int uid = context.getApplicationInfo().uid;
        if (!launch.isAbsolute() || !launch.getCanonicalFile().equals(launch))
            throw new SecurityException("Boot metadata launch path is not canonical");
        StructStat named = Os.lstat(launch.getPath());
        FileDescriptor descriptor = Os.open(launch.getPath(), OsConstants.O_RDONLY | OsConstants.O_NOFOLLOW | OsConstants.O_CLOEXEC, 0);
        try (FileInputStream stream = new FileInputStream(descriptor)) {
            StructStat before = Os.fstat(descriptor);
            if (!OsConstants.S_ISREG(before.st_mode) || before.st_uid != uid || before.st_gid != uid
                    || before.st_nlink != 1 || (before.st_mode & 0077) != 0 || before.st_size > 65536
                    || named.st_dev != before.st_dev || named.st_ino != before.st_ino)
                throw new SecurityException("Boot metadata must belong to the private application launch");
            byte[] bytes = Deployment.readBounded(stream, 65536);
            StructStat after = Os.fstat(descriptor), stillNamed = Os.lstat(launch.getPath());
            if (bytes.length != before.st_size || before.st_dev != after.st_dev || before.st_ino != after.st_ino
                    || before.st_size != after.st_size || !before.st_mtim.equals(after.st_mtim)
                    || !before.st_ctim.equals(after.st_ctim)
                    || before.st_dev != stillNamed.st_dev || before.st_ino != stillNamed.st_ino)
                throw new SecurityException("Private boot metadata changed during admission");
            JSONObject value = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            if (value.length() != 6 || !LAUNCH_SCHEMA.equals(value.get("schema"))
                    || !value.has("workspace") || !value.has("socketPath") || !value.has("manifestPath")
                    || !value.has("controllerRoots"))
                throw new SecurityException("Application boot metadata requires the versioned app launch contract");
            requireCurrent(value.getJSONObject("bootEpoch"), current);
        }
    }
}
