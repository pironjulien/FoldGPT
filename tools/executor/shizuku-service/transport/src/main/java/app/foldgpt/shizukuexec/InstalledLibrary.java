package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;

/** Resolve only inside PackageManager's canonical nativeLibraryDir. */
final class InstalledLibrary {
    static final String PREFIX = "@nativeLibraryDir/";
    static final String CWD_NAME = "libfoldgpt_bionic_cwd.so";
    static final String CWD_PATH = "@nativeLibraryDir/" + CWD_NAME;

    static File verify(File directory, String name, String expected) throws Exception {
        if (!directory.isAbsolute() || !directory.getCanonicalFile().equals(directory)
                || !directory.isDirectory() || !name.matches("lib[A-Za-z0-9_.]+\\.so") || name.contains("..")) {
            throw new SecurityException("Invalid installed native library path");
        }
        File file = new File(directory, name);
        if (!file.getCanonicalFile().equals(file) || !file.isFile() || file.length() > 16777216) {
            throw new SecurityException("Native library is not an ordinary packaged file");
        }
        if (!expected.matches("[0-9a-f]{64}")) throw new SecurityException("Native library digest is missing");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] bytes = new byte[65536];
            int count, consumed = 0;
            while ((count = input.read(bytes)) >= 0) {
                consumed += count;
                if (consumed > 16777216) throw new SecurityException("Native library grew beyond its bound");
                digest.update(bytes, 0, count);
            }
        }
        StringBuilder actual = new StringBuilder();
        for (byte value : digest.digest()) actual.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        if (!expected.contentEquals(actual)) throw new SecurityException("Packaged native library digest mismatch");
        return file;
    }

    static void verifyInventory(JSONObject config, File directory) throws Exception {
        if (!config.has("nativeLibraries")) return;
        JSONObject files = config.getJSONObject("nativeLibraries");
        if (files.length() == 0 || files.length() > 128) throw new SecurityException("Invalid native inventory size");
        java.util.Iterator<String> names = files.keys();
        while (names.hasNext()) {
            String name = names.next();
            if (!(files.get(name) instanceof String)) throw new SecurityException("Native digest is not a string");
            verify(directory, name, files.getString(name));
        }
        String python = config.getString("pythonLibrary");
        if (!config.getString("pythonSha256").equals(files.getString(python))) {
            throw new SecurityException("Interpreter differs from native inventory");
        }
        JSONObject options = config.getJSONObject("backendOptions");
        for (String key : new String[] {"helper", "handleHelper", "processRunner"}) {
            requireMarker(options.getString(key), files);
        }
        JSONObject executables = options.getJSONObject("executables");
        names = executables.keys();
        while (names.hasNext()) requireMarker(executables.getString(names.next()), files);
        org.json.JSONArray runtime = options.getJSONArray("runtime");
        for (int i = 0; i < runtime.length(); ++i) {
            String path = runtime.getJSONObject(i).getString("path");
            if (path.startsWith("@")) requireMarker(path, files);
        }
    }

    private static void requireMarker(String path, JSONObject files) throws Exception {
        if (!path.startsWith(PREFIX) || !files.has(path.substring(PREFIX.length()))) {
            throw new SecurityException("Executable must identify an attested installed library");
        }
    }

    static void verifyCwd(JSONObject backendOptions, File directory) throws Exception {
        if (!backendOptions.has("cwdShim")) return;
        JSONObject shim = backendOptions.getJSONObject("cwdShim");
        if (shim.length() != 2 || !CWD_PATH.equals(shim.get("path"))
                || !(shim.get("sha256") instanceof String)) {
            throw new SecurityException("cwdShim must name the fixed installed library and its digest");
        }
        verify(directory, CWD_NAME, shim.getString("sha256"));
    }
}
