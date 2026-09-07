package app.foldgpt.shizukuexec;

import android.content.Context;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** All execution inputs come from the installed APK, never from Binder/RPC. */
final class Deployment {
    static final String ASSET = "foldgpt-executor-deployment.json";
    // -I excludes caller env/cwd; -S excludes site initialization; -u avoids
    // interpreter shutdown flushing a disconnected RPC channel indefinitely.
    private static final String ENTRY = "import sys;sys.path.insert(0,sys.argv[1]+'/assets/foldgpt-executor');"
            + "from foldgpt_shizuku_bootstrap import main;main(sys.argv[1])";
    final String executable;
    final String[] argv;

    Deployment(Context context) throws Exception {
        JSONObject config;
        try (InputStream input = context.getAssets().open(ASSET)) {
            config = new JSONObject(new String(readBounded(input, 65536), StandardCharsets.UTF_8));
        }
        if (!"foldgpt.shizuku.deployment.v1".equals(config.getString("schema"))
                || !context.getPackageName().equals(config.getString("packageName"))) {
            throw new SecurityException("Deployment does not identify this installed application");
        }
        String name = config.getString("pythonLibrary");
        if (!name.matches("lib[A-Za-z0-9_]+\\.so")) throw new SecurityException("Invalid packaged interpreter");
        File directory = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalFile();
        File file = new File(directory, name);
        if (!file.getCanonicalFile().equals(file) || !file.isFile()) {
            throw new SecurityException("Interpreter is not an ordinary packaged library");
        }
        String expected = config.getString("pythonSha256");
        if (!expected.matches("[0-9a-f]{64}")) throw new SecurityException("Interpreter digest is missing");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] bytes = new byte[65536];
            int count;
            while ((count = input.read(bytes)) >= 0) digest.update(bytes, 0, count);
        }
        StringBuilder actual = new StringBuilder();
        for (byte value : digest.digest()) actual.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        if (!expected.contentEquals(actual)) throw new SecurityException("Packaged interpreter digest mismatch");
        executable = file.getPath();
        argv = new String[] {executable, "-I", "-S", "-u", "-c", ENTRY, context.getApplicationInfo().sourceDir};
        NativeSpawn.load(new File(directory, "libfoldgpt_shizuku_transport.so").getPath());
    }
    static byte[] readBounded(InputStream input, int limit) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int count;
        while ((count = input.read(chunk)) >= 0) {
            if (bytes.size() + count > limit) throw new IllegalStateException("Installed configuration exceeds its bound");
            bytes.write(chunk, 0, count);
        }
        return bytes.toByteArray();
    }
}
