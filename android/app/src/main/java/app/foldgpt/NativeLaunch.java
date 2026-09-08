package app.foldgpt;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;

/** App-owned paths and signed Python data. This class never executes a command. */
final class NativeLaunch {
    private final app.foldgpt.shizukuexec.ApplicationDataPaths dataPaths;
    final String nonce, launchPath, manifestPath, socketPath, workspace, endpointRoot, pythonRoot, nativeRoot;

    NativeLaunch(Context context, String controllerHome) throws Exception {
        File declaredFiles = context.getFilesDir();
        File declaredData = new File(context.getApplicationInfo().dataDir);
        dataPaths = new app.foldgpt.shizukuexec.ApplicationDataPaths(context);
        File files = declaredFiles;
        File data = declaredData;
        if (!files.getParentFile().equals(data) || !dataPaths.isExact(files)) throw new SecurityException("Unexpected application files location");
        int uid = context.getApplicationInfo().uid;
        workspace = privateDirectory(new File(files, "projects"), uid).getPath();
        File endpoint = endpointDirectory(data, uid);
        endpointRoot = endpoint.getPath();
        nonce = UUID.randomUUID().toString().replace("-", "");
        File session = new File(endpoint, nonce);
        if (session.exists()) throw new SecurityException("Native session already exists");
        privateDirectory(session, uid);
        socketPath = new File(session, "owner.sock").getPath();
        manifestPath = new File(session, "startup.json").getPath();
        launchPath = new File(session, "launch.json").getPath();
        if (socketPath.getBytes(StandardCharsets.UTF_8).length >= 108) throw new SecurityException("Native socket path exceeds Unix limit");
        nativeRoot = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalPath();
        pythonRoot = new File(privateDirectory(new File(files, "native-runtime-v1"), uid), "python").getPath();
        JSONObject config = new JSONObject(new String(asset(context, "foldgpt-executor-deployment.json", 65536), StandardCharsets.UTF_8));
        JSONObject runtime = config.getJSONObject("pythonRuntime");
        if (!pythonRoot.equals(runtime.getString("path"))) {
            JSONObject paths = new JSONObject().put("actual", boundedPath(pythonRoot))
                    .put("expected", boundedPath(runtime.getString("path")))
                    .put("dataDir", boundedPath(declaredData.getPath())).put("filesDir", boundedPath(declaredFiles.getPath()))
                    .put("canonicalDataDir", boundedPath(data.getPath())).put("canonicalFilesDir", boundedPath(files.getPath()));
            throw new SecurityException("Runtime path differs from the application-owned prefix: " + paths);
        }
        byte[] inventory = asset(context, runtime.getString("manifestAsset"), 2097152);
        requireHash(inventory, runtime.getString("manifestSha256"));
        installRuntime(context, new JSONObject(new String(inventory, StandardCharsets.UTF_8)), uid);
        if (controllerHome == null || !controllerHome.startsWith("/") || controllerHome.contains("..")
                || controllerHome.equals("/") || controllerHome.startsWith(data.getPath() + "/")) {
            throw new SecurityException("Invalid controller HOME");
        }
        JSONObject launch = new JSONObject().put("schema", "foldgpt.native-launch.v1")
            .put("workspace", workspace).put("socketPath", socketPath).put("manifestPath", manifestPath)
            .put("controllerRoots", new JSONArray().put(uri(controllerHome)).put("file:///tmp"));
        writeNew(new File(launchPath), (launch.toString() + "\n").getBytes(StandardCharsets.UTF_8));
    }

    private void installRuntime(Context context, JSONObject manifest, int uid) throws Exception {
        File root = privateDirectory(new File(pythonRoot), uid);
        JSONArray files = manifest.getJSONArray("dataFiles");
        for (int i = 0; i < files.length(); ++i) {
            JSONObject item = files.getJSONObject(i);
            String relative = item.getString("path");
            File file = descendant(root, relative, uid);
            byte[] bytes = asset(context, "bionic-python/" + relative, 16777216);
            if (bytes.length != item.getLong("bytes")) throw new SecurityException("Python asset size differs");
            requireHash(bytes, item.getString("sha256"));
            if (file.exists()) {
                StructStat stat = Os.lstat(file.getPath());
                if (!OsConstants.S_ISREG(stat.st_mode) || stat.st_uid != uid || (stat.st_mode & 0022) != 0
                        || !dataPaths.isExact(file)) throw new SecurityException("Existing runtime file is not private regular data");
                try (InputStream input = new FileInputStream(file)) { requireHash(read(input, 16777216), item.getString("sha256")); }
            } else writeNew(file, bytes);
        }
        JSONArray aliases = manifest.getJSONArray("runtimeAliases");
        for (int i = 0; i < aliases.length(); ++i) {
            JSONObject item = aliases.getJSONObject(i);
            File alias = descendant(root, item.getString("path"), uid);
            String name = item.getString("nativeLibrary");
            if (!name.matches("lib[A-Za-z0-9_.]+\\.so") || name.contains("..")) throw new SecurityException("Invalid runtime alias target");
            String target = new File(nativeRoot, name).getPath();
            try {
                StructStat stat = Os.lstat(alias.getPath());
                if (!OsConstants.S_ISLNK(stat.st_mode) || stat.st_uid != uid) throw new SecurityException("Existing runtime alias is not an owned symlink");
                if (Os.readlink(alias.getPath()).equals(target)) continue;
            } catch (android.system.ErrnoException absent) { if (absent.errno != OsConstants.ENOENT) throw absent; }
            File temporary = new File(alias.getParentFile(), alias.getName() + "." + nonce);
            Os.symlink(target, temporary.getPath());
            Os.rename(temporary.getPath(), alias.getPath());
        }
    }
    private static String boundedPath(String path) { return path.length() <= 512 ? path : path.substring(0, 512) + "[truncated]"; }
    private File descendant(File root, String relative, int uid) throws Exception {
        if (relative.isEmpty() || relative.startsWith("/") || relative.contains("\\") || relative.indexOf('\0') >= 0)
            throw new SecurityException("Invalid native runtime path");
        String[] parts = relative.split("/", -1);
        File parent = root;
        for (int i = 0; i < parts.length; ++i) {
            if (parts[i].isEmpty() || parts[i].equals(".") || parts[i].equals("..")) throw new SecurityException("Invalid native runtime component");
            File next = new File(parent, parts[i]);
            if (i == parts.length - 1) return next;
            parent = privateDirectory(next, uid);
        }
        throw new SecurityException("Empty runtime path");
    }
    private File privateDirectory(File file, int uid) throws Exception {
        try { Os.mkdir(file.getPath(), 0700); }
        catch (android.system.ErrnoException exists) { if (exists.errno != OsConstants.EEXIST) throw exists; }
        StructStat stat = Os.lstat(file.getPath());
        if (!dataPaths.isExact(file) || !OsConstants.S_ISDIR(stat.st_mode) || stat.st_uid != uid
                || stat.st_gid != uid || (stat.st_mode & 0077) != 0) throw new SecurityException("Native directory must be private and app-owned: " + file.getName());
        return file;
    }
    private File endpointDirectory(File data, int uid) throws Exception {
        File endpoint = new File(data, "app_foldgpt_exec");
        // Context.getDir(..., MODE_PRIVATE) creates 0771 on this Android build.
        // Own the fixed endpoint directory explicitly instead. Only the empty,
        // actual app-owned legacy directory may have its mode restricted here.
        try { Os.mkdir(endpoint.getPath(), 0700); }
        catch (android.system.ErrnoException exists) { if (exists.errno != OsConstants.EEXIST) throw exists; }
        StructStat named = Os.lstat(endpoint.getPath());
        if (!dataPaths.isExact(endpoint) || !OsConstants.S_ISDIR(named.st_mode)
                || named.st_uid != uid || named.st_gid != uid) throw new SecurityException("Native endpoint directory identity differs");
        if ((named.st_mode & 07777) == 0771) {
            java.io.FileDescriptor descriptor = Os.open(endpoint.getPath(), OsConstants.O_RDONLY | OsConstants.O_NONBLOCK
                    | OsConstants.O_NOFOLLOW | OsConstants.O_CLOEXEC, 0);
            try {
                StructStat opened = Os.fstat(descriptor);
                String[] children = endpoint.list();
                if (!OsConstants.S_ISDIR(opened.st_mode) || opened.st_dev != named.st_dev || opened.st_ino != named.st_ino
                        || opened.st_uid != uid || opened.st_gid != uid
                        || (opened.st_mode & 07777) != 0771 || children == null || children.length != 0) {
                    throw new SecurityException("Legacy native endpoint must be the same empty owned directory");
                }
                // fchmod changes only the verified opened inode, never a path
                // that could have become a symlink between checks.
                Os.fchmod(descriptor, 0700);
                StructStat after = Os.lstat(endpoint.getPath());
                if (after.st_dev != opened.st_dev || after.st_ino != opened.st_ino) throw new SecurityException("Native endpoint changed during migration");
            } finally { Os.close(descriptor); }
        }
        return privateDirectory(endpoint, uid);
    }
    private static void writeNew(File file, byte[] bytes) throws Exception {
        java.io.FileDescriptor fd = Os.open(file.getPath(), OsConstants.O_WRONLY | OsConstants.O_CREAT | OsConstants.O_EXCL | OsConstants.O_NOFOLLOW, 0600);
        try (FileOutputStream output = new FileOutputStream(fd)) { output.write(bytes); output.getFD().sync(); }
    }
    JSONObject verifyReady(int pid, int uid) throws Exception {
        File file = new File(manifestPath);
        StructStat info = Os.lstat(file.getPath());
        if (!OsConstants.S_ISREG(info.st_mode) || info.st_uid != uid || (info.st_mode & 0077) != 0
                || !dataPaths.isExact(file)) throw new SecurityException("Native startup manifest is not private app data");
        JSONObject manifest;
        try (InputStream input = new FileInputStream(file)) { manifest = new JSONObject(new String(read(input, 65536), StandardCharsets.UTF_8)); }
        JSONObject peer = manifest.getJSONObject("peer");
        if (!"foldgpt.native-startup.v1".equals(manifest.getString("schema")) || !socketPath.equals(manifest.getString("socketPath"))
                || !uri(workspace).equals(manifest.getString("workspaceRoot")) || peer.getInt("pid") != pid
                || peer.getInt("uid") != uid || peer.getInt("gid") != uid) throw new SecurityException("Native startup peer does not match the reaped child owner");
        JSONArray shared = manifest.getJSONArray("sharedPaths");
        java.util.Set<String> expected = new java.util.HashSet<>(java.util.Arrays.asList(workspace, pythonRoot, nativeRoot));
        for (int i = 0; i < shared.length(); ++i) {
            JSONObject entry = shared.getJSONObject(i);
            String path = new File(java.net.URI.create(entry.getString("path"))).getPath();
            if (!expected.remove(path)) throw new SecurityException("Unexpected or duplicate shared native root");
            StructStat stat = Os.stat(path);
            if (entry.getLong("device") != stat.st_dev || entry.getLong("inode") != stat.st_ino) throw new SecurityException("Shared root identity differs");
        }
        if (!expected.isEmpty()) throw new SecurityException("Shared native roots are incomplete");
        return manifest;
    }
    static String uri(String path) { return "file://" + new File(path).toURI().getRawPath().replaceAll("/$", ""); }
    private static byte[] asset(Context context, String path, int bound) throws Exception {
        try (InputStream input = context.getAssets().open(path)) { return read(input, bound); }
    }
    private static byte[] read(InputStream input, int bound) throws Exception {
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[65536]; int count;
        while ((count = input.read(block)) >= 0) {
            if (output.size() + count > bound) throw new SecurityException("Native data exceeds bound");
            output.write(block, 0, count);
        }
        return output.toByteArray();
    }
    private static void requireHash(byte[] data, String expected) throws Exception {
        StringBuilder hash = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(data)) hash.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        if (!expected.matches("[0-9a-f]{64}") || !expected.contentEquals(hash)) throw new SecurityException("Native data hash mismatch");
    }
}
