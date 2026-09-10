package app.foldgpt.shizukuexec;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.File;

/** Keep PackageManager's native contract across Android's app mount spelling. */
public final class ApplicationDataPaths {
    public final File declared;
    private final File canonical;

    public ApplicationDataPaths(Context context) throws Exception {
        int uid = context.getApplicationInfo().uid;
        declared = new File(context.getApplicationInfo().dataDir);
        canonical = declared.getCanonicalFile();
        String expected = "/data/user/0/" + context.getPackageName();
        String applicationView = "/data/data/" + context.getPackageName();
        if (Os.getuid() != uid || uid < 10000 || !declared.getPath().equals(expected)
                || !(canonical.equals(declared) || canonical.getPath().equals(applicationView))) {
            throw new SecurityException("Unexpected installed application data path");
        }
        StructStat named = Os.lstat(declared.getPath());
        StructStat actual = Os.lstat(canonical.getPath());
        if (!OsConstants.S_ISDIR(named.st_mode) || !OsConstants.S_ISDIR(actual.st_mode)
                || named.st_uid != uid || named.st_gid != uid || (named.st_mode & 0077) != 0
                || named.st_dev != actual.st_dev || named.st_ino != actual.st_ino) {
            throw new SecurityException("Application path views do not identify the same private directory");
        }
    }

    /** The system prefix is the only alias admitted; every private suffix stays exact. */
    public boolean isExact(File file) throws Exception {
        String path = file.getPath();
        String prefix = declared.getPath();
        if (!file.isAbsolute() || !(path.equals(prefix) || path.startsWith(prefix + "/"))) return false;
        String suffix = path.substring(prefix.length());
        if (!suffix.isEmpty()) {
            for (String component : suffix.substring(1).split("/", -1)) {
                if (component.isEmpty() || component.equals(".") || component.equals("..")) return false;
            }
        }
        return file.getCanonicalPath().equals(canonical.getPath() + suffix);
    }

    /** Verified Android view used for the distinct application launch contract. */
    public File canonicalRoot() { return canonical; }

    /** No aliases are admitted beneath the measured canonical application root. */
    public boolean isCanonicalExact(File file) throws Exception { return canonicalExact(canonical, file); }

    static boolean canonicalExact(File root, File file) throws Exception {
        String prefix = root.getPath();
        String path = file.getPath();
        if (!file.isAbsolute() || !(path.equals(prefix) || path.startsWith(prefix + File.separator))) return false;
        String suffix = path.substring(prefix.length());
        if (!suffix.isEmpty()) {
            for (String component : suffix.substring(1).split(java.util.regex.Pattern.quote(File.separator), -1)) {
                if (component.isEmpty() || component.equals(".") || component.equals("..")) return false;
            }
        }
        return file.getCanonicalFile().equals(file);
    }
}
