package app.foldgpt.shizukuexec;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;

/** Admit fixed Python data before the interpreter can import any staged file. */
final class PythonRuntime {
    static void verify(Context context, JSONObject config, File nativeDirectory) throws Exception {
        if (!config.has("pythonRuntime")) return;
        try (InputStream input = new FileInputStream("/proc/self/attr/current")) {
            String label = new String(Deployment.readBounded(input, 4096), StandardCharsets.US_ASCII).replace("\0", "").trim();
            if (!label.equals("u:r:shell:s0")) throw new SecurityException("Python bootstrap requires the actual shell SELinux domain");
        }
        JSONObject runtime = config.getJSONObject("pythonRuntime");
        if (runtime.length() != 3) throw new SecurityException("Invalid Python runtime contract");
        String asset = runtime.getString("manifestAsset");
        if (!asset.equals("foldgpt-python-runtime.json")) throw new SecurityException("Unexpected runtime manifest asset");
        byte[] bytes;
        try (InputStream input = context.getAssets().open(asset)) { bytes = Deployment.readBounded(input, 2097152); }
        requireDigest(bytes, runtime.getString("manifestSha256"));
        JSONObject manifest = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
        File root = new File(runtime.getString("path"));
        if (!root.isAbsolute() || !root.getCanonicalFile().equals(root)) throw new SecurityException("Invalid Python runtime root");
        StructStat rootStat = Os.lstat(root.getPath());
        if (!OsConstants.S_ISDIR(rootStat.st_mode) || rootStat.st_uid != 2000 || (rootStat.st_mode & 0077) != 0) {
            throw new SecurityException("Python runtime must be an owner-only shell directory");
        }
        Set<String> expected = new HashSet<>();
        JSONArray data = manifest.getJSONArray("dataFiles");
        for (int i = 0; i < data.length(); ++i) {
            JSONObject entry = data.getJSONObject(i);
            File file = descendant(root, entry.getString("path"), expected);
            if (!file.getCanonicalFile().equals(file)) throw new SecurityException("Python data alias is not admitted");
            StructStat info = Os.lstat(file.getPath());
            if (!OsConstants.S_ISREG(info.st_mode) || info.st_uid != 2000 || (info.st_mode & 0022) != 0
                    || info.st_size != entry.getLong("bytes") || info.st_size > 16777216) {
                throw new SecurityException("Python data differs from bounded runtime inventory");
            }
            try (InputStream input = new FileInputStream(file)) {
                requireDigest(Deployment.readBounded(input, 16777216), entry.getString("sha256"));
            }
        }
        JSONArray aliases = manifest.getJSONArray("runtimeAliases");
        JSONObject nativeFiles = config.getJSONObject("nativeLibraries");
        for (int i = 0; i < aliases.length(); ++i) {
            JSONObject entry = aliases.getJSONObject(i);
            File file = descendant(root, entry.getString("path"), expected);
            String name = entry.getString("nativeLibrary");
            if (!entry.getString("sha256").equals(nativeFiles.getString(name))) throw new SecurityException("Python ELF alias digest differs");
            File target = new File(nativeDirectory, name);
            if (!OsConstants.S_ISLNK(Os.lstat(file.getPath()).st_mode)
                    || !Os.readlink(file.getPath()).equals(target.getPath()) || !file.getCanonicalFile().equals(target)) {
                throw new SecurityException("Python ELF alias must target the actual installed APK library");
            }
        }
        Set<String> actual = new HashSet<>();
        walk(root, root, actual);
        if (!actual.equals(expected)) throw new SecurityException("Unexpected or missing staged Python file");
    }
    private static File descendant(File root, String relative, Set<String> paths) throws Exception {
        if (relative.isEmpty() || relative.startsWith("/") || relative.contains("\\") || relative.indexOf('\0') >= 0
                || java.util.Arrays.stream(relative.split("/", -1)).anyMatch(x -> x.isEmpty() || x.equals(".") || x.equals(".."))
                || !paths.add(relative)) throw new SecurityException("Invalid Python inventory path");
        return new File(root, relative);
    }
    private static void walk(File root, File directory, Set<String> files) throws Exception {
        StructStat info = Os.lstat(directory.getPath());
        if (!OsConstants.S_ISDIR(info.st_mode) || info.st_uid != 2000 || (info.st_mode & 0022) != 0) {
            throw new SecurityException("Python runtime directory is not admitted");
        }
        File[] children = directory.listFiles();
        if (children == null) throw new SecurityException("Cannot inspect Python runtime directory");
        for (File child : children) {
            if (OsConstants.S_ISDIR(Os.lstat(child.getPath()).st_mode)) walk(root, child, files);
            else files.add(root.toPath().relativize(child.toPath()).toString());
        }
    }
    private static void requireDigest(byte[] data, String expected) throws Exception {
        if (!expected.matches("[0-9a-f]{64}")) throw new SecurityException("Invalid Python runtime digest");
        StringBuilder actual = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(data)) actual.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        if (!expected.contentEquals(actual)) throw new SecurityException("Python runtime digest mismatch");
    }
}
