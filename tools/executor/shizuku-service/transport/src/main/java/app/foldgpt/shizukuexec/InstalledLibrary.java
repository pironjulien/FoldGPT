package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;

/** Resolve only inside PackageManager's canonical nativeLibraryDir. */
final class InstalledLibrary {
    static final String CWD_NAME = "libfoldgpt_bionic_cwd.so";
    static final String CWD_PATH = "@nativeLibraryDir/" + CWD_NAME;

    static File verify(File directory, String name, String expected) throws Exception {
        if (!directory.isAbsolute() || !directory.getCanonicalFile().equals(directory)
                || !directory.isDirectory() || !name.matches("lib[A-Za-z0-9_]+\\.so")) {
            throw new SecurityException("Invalid installed native library path");
        }
        File file = new File(directory, name);
        if (!file.getCanonicalFile().equals(file) || !file.isFile()) {
            throw new SecurityException("Native library is not an ordinary packaged file");
        }
        if (!expected.matches("[0-9a-f]{64}")) throw new SecurityException("Native library digest is missing");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] bytes = new byte[65536];
            int count;
            while ((count = input.read(bytes)) >= 0) digest.update(bytes, 0, count);
        }
        StringBuilder actual = new StringBuilder();
        for (byte value : digest.digest()) actual.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        if (!expected.contentEquals(actual)) throw new SecurityException("Packaged native library digest mismatch");
        return file;
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
