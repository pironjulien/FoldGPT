package app.foldgpt.shizukuexec;

import android.content.Context;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** All execution inputs come from the installed APK, never from Binder/RPC. */
public final class Deployment {
    static final String ASSET = "foldgpt-executor-deployment.json";
    // -I excludes caller env/cwd; -S excludes site initialization; -u avoids
    // interpreter shutdown flushing a disconnected RPC channel indefinitely.
    private static final String ENTRY = "import sys;sys.path.insert(0,sys.argv[1]+'/assets/foldgpt-executor');"
            + "from foldgpt_shizuku_bootstrap import main;main(sys.argv[1])";
    final String executable;
    final String transportLibrary;
    final String[] argv;
    /** Read-only admission for an application owner before selecting Shizuku. */
    public static void verifyInstalledInputs(Context context) throws Exception { new Deployment(context); }

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
        File directory = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalFile();
        File file = InstalledLibrary.verify(directory, name, config.getString("pythonSha256"));
        InstalledLibrary.verifyInventory(config, directory);
        InstalledLibrary.verifyCwd(config.getJSONObject("backendOptions"), directory);
        // Shell-owned data are intentionally inaccessible to the application UID.
        // The real UserService repeats APK admission and checks them before fork.
        if (android.system.Os.getuid() == 2000) PythonRuntime.verify(context, config, directory);
        executable = file.getPath();
        argv = new String[] {executable, "-I", "-S", "-B", "-u", "-c", ENTRY, context.getApplicationInfo().sourceDir};
        transportLibrary = new File(directory, "libfoldgpt_shizuku_transport.so").getPath();
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
