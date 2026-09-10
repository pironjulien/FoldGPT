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
    final boolean directNative;
    final boolean applicationLaunch;
    final String workingDirectory;
    final int applicationUid;
    /** Read-only admission for an application owner before selecting Shizuku. */
    public static void verifyInstalledInputs(Context context) throws Exception {
        new Deployment(context, new AdmissionTrace(), null, null, null);
    }
    public static boolean isApplicationLaunch(Context context) throws Exception {
        return applicationOrigin(readConfig(context));
    }
    static Deployment forApplication(Context context, AdmissionTrace trace, String launchPath, String nonce) throws Exception {
        if (launchPath == null || nonce == null) throw new SecurityException("Application launch identity is required");
        return new Deployment(context, trace, launchPath, nonce, Boolean.TRUE);
    }
    private static JSONObject readConfig(Context context) throws Exception {
        try (InputStream input = context.getAssets().open(ASSET)) {
            return new JSONObject(new String(readBounded(input, 65536), StandardCharsets.UTF_8));
        }
    }
    static boolean applicationOrigin(JSONObject config) throws Exception {
        Object schema = config.get("schema");
        if ("foldgpt.native.deployment.v2".equals(schema)) {
            if (!"android-app".equals(config.get("launchOrigin")))
                throw new SecurityException("Unknown native application launch origin");
            return true;
        }
        if (!("foldgpt.native.deployment.v1".equals(schema) || "foldgpt.shizuku.deployment.v1".equals(schema))
                || config.has("launchOrigin")) throw new SecurityException("Unknown or mixed deployment origin");
        return false;
    }

    Deployment(Context context) throws Exception { this(context, new AdmissionTrace()); }
    Deployment(Context context, AdmissionTrace trace) throws Exception { this(context, trace, null, null); }
    Deployment(Context context, AdmissionTrace trace, String launchPath, String nonce) throws Exception {
        this(context, trace, launchPath, nonce, Boolean.FALSE);
    }
    private Deployment(Context context, AdmissionTrace trace, String launchPath, String nonce, Boolean expectedApp) throws Exception {
        trace.at(AdmissionTrace.Stage.DEPLOYMENT_ASSET);
        JSONObject config = readConfig(context);
        trace.at(AdmissionTrace.Stage.DEPLOYMENT_SCHEMA);
        applicationLaunch = applicationOrigin(config);
        directNative = applicationLaunch || "foldgpt.native.deployment.v1".equals(config.getString("schema"));
        if ((expectedApp != null && expectedApp.booleanValue() != applicationLaunch)
                || !context.getPackageName().equals(config.getString("packageName"))) {
            throw new SecurityException("Deployment does not identify this installed application");
        }
        applicationUid = context.getApplicationInfo().uid;
        ApplicationDataPaths dataPaths = applicationLaunch ? new ApplicationDataPaths(context) : null;
        workingDirectory = applicationLaunch ? dataPaths.canonicalRoot().getPath() : "/";
        String name = config.getString("pythonLibrary");
        trace.at(AdmissionTrace.Stage.NATIVE_DIRECTORY);
        trace.fact("observed", context.getApplicationInfo().nativeLibraryDir);
        File directory = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalFile();
        trace.fact("canonical", directory.getPath());
        trace.at(AdmissionTrace.Stage.INTERPRETER); trace.subject(name);
        File file = InstalledLibrary.verify(directory, name, config.getString("pythonSha256"));
        trace.at(AdmissionTrace.Stage.NATIVE_INVENTORY);
        InstalledLibrary.verifyInventory(config, directory, trace);
        trace.at(AdmissionTrace.Stage.CWD_SHIM);
        InstalledLibrary.verifyCwd(config.getJSONObject("backendOptions"), directory);
        // Shell-owned data are intentionally inaccessible to the application UID.
        // The real UserService repeats APK admission and checks them before fork.
        if (directNative) {
            if (android.system.Os.getuid() == context.getApplicationInfo().uid) PythonRuntime.verifyApplication(context, config, directory, trace);
            String bootstrapName = applicationLaunch ? "libfoldgpt_app_bootstrap.so" : "libfoldgpt_native_bootstrap.so";
            File bootstrap = InstalledLibrary.verify(directory, bootstrapName,
                    config.getJSONObject("nativeLibraries").getString(bootstrapName));
            executable = applicationLaunch ? bootstrap.getPath() : "/system/bin/run-as";
            if (launchPath == null && nonce == null) { argv = new String[0]; }
            else {
                if (nonce == null || !nonce.matches("[0-9a-f]{32}")) throw new SecurityException("Invalid native session nonce");
                String data = context.getApplicationInfo().dataDir;
                // Shell cannot traverse the app-private path. Its canonical identity
                // and contents are checked again by C after the run-as transition.
                String expected = (applicationLaunch ? workingDirectory : data) + "/app_foldgpt_exec/" + nonce + "/launch.json";
                if (!expected.equals(launchPath)) throw new SecurityException("Native launch path is outside the fixed private session");
                if (applicationLaunch && !dataPaths.isCanonicalExact(new File(launchPath)))
                    throw new SecurityException("Application launch path contains an unadmitted alias");
                if (applicationLaunch) AndroidBootEpoch.verifyLaunch(context, new File(launchPath));
                argv = applicationLaunch ? new String[] {executable, "--app-runtime-v1",
                    Integer.toString(applicationUid), data, Integer.toString(android.system.Os.getpid()),
                    nonce, context.getApplicationInfo().sourceDir, launchPath}
                    : new String[] {executable, context.getPackageName(), bootstrap.getPath(), "--native-runtime-v1",
                    Integer.toString(context.getApplicationInfo().uid), data, Integer.toString(android.system.Os.getpid()),
                    nonce, context.getApplicationInfo().sourceDir, launchPath};
            }
        } else {
            if (launchPath != null || nonce != null) throw new SecurityException("Native request requires the native deployment");
            if (android.system.Os.getuid() == 2000) PythonRuntime.verify(context, config, directory, trace);
            executable = file.getPath();
            argv = new String[] {executable, "-I", "-S", "-B", "-u", "-c", ENTRY, context.getApplicationInfo().sourceDir};
        }
        String transportName = applicationLaunch ? "libfoldgpt_app_transport.so" : "libfoldgpt_shizuku_transport.so";
        transportLibrary = applicationLaunch ? InstalledLibrary.verify(directory, transportName,
                config.getJSONObject("nativeLibraries").getString(transportName)).getPath()
                : new File(directory, transportName).getPath();
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
