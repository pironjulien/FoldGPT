package app.foldgpt.shizukuexec;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.security.MessageDigest;

/** Fresh installed identities; there is no caller-selected package or path. */
public final class RunAsBrokerInstallation {
    public static final String TARGET = "app.foldgpt";
    public static final String QUALIFICATION = "app.foldgpt.runasbrokerqualification.v1";
    private static final String SIGNER = "30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16";
    private RunAsBrokerInstallation() {}

    public static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest());
    }
    private static String hex(byte[] value) {
        StringBuilder result = new StringBuilder();
        for (byte item : value) result.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return result.toString();
    }
    private static JSONObject installed(Context context, String name) throws Exception {
        PackageInfo info = context.getPackageManager().getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES);
        ApplicationInfo app = info.applicationInfo;
        if (app == null || app.uid < 10000 || (app.flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0
                || !name.equals(app.packageName) || info.signingInfo == null) {
            throw new SecurityException("Installed debug package identity is not admitted: " + name);
        }
        Signature[] signers = info.signingInfo.getApkContentsSigners();
        if (signers.length != 1 || !SIGNER.equals(hex(MessageDigest.getInstance("SHA-256").digest(signers[0].toByteArray())))) {
            throw new SecurityException("Installed package has a different preserved FoldGPT signer");
        }
        if (app.splitSourceDirs != null && app.splitSourceDirs.length != 0) {
            throw new SecurityException("This fixed qualification requires an unsplit reviewed APK");
        }
        String data = "/data/user/0/" + name;
        // The shell UserService cannot canonicalize the private directory before
        // run-as. Validate the PM string; the Bionic child verifies realpath/stat.
        if (!data.equals(app.dataDir)) throw new SecurityException("Unexpected canonical application data prefix");
        File source = new File(app.sourceDir).getCanonicalFile();
        File nativeDir = new File(app.nativeLibraryDir).getCanonicalFile();
        if (!source.getPath().startsWith("/data/app/") || !nativeDir.getPath().startsWith("/data/app/")) {
            throw new SecurityException("Unexpected package installation location");
        }
        return new JSONObject().put("packageName", name).put("uid", app.uid).put("dataDir", data)
            .put("sourceDir", source.getPath()).put("nativeLibraryDir", nativeDir.getPath())
            .put("versionCode", info.getLongVersionCode()).put("lastUpdateTime", info.lastUpdateTime)
            .put("debuggable", true).put("signerSha256", SIGNER).put("apkSha256", sha256(source));
    }
    public static JSONObject capture(Context context) throws Exception {
        JSONObject target = installed(context, TARGET), qualification = installed(context, QUALIFICATION);
        if (!QUALIFICATION.equals(context.getPackageName())) throw new SecurityException("Wrong qualification context");
        String directory = qualification.getString("nativeLibraryDir");
        JSONObject nativeFiles = new JSONObject();
        JSONObject config;
        try (java.io.InputStream input = context.getAssets().open("foldgpt-runas-broker-config.json")) {
            byte[] bytes = input.readNBytes(65537);
            if (bytes.length > 65536) throw new SecurityException("Installed broker config exceeds bound");
            config = new JSONObject(new String(bytes, java.nio.charset.StandardCharsets.UTF_8));
        }
        if (!"foldgpt.runas-broker-config.v1".equals(config.getString("schema"))
                || !QUALIFICATION.equals(config.getString("package"))) throw new SecurityException("Wrong broker config");
        JSONObject expected = config.getJSONObject("nativeLibraries");
        java.util.Iterator<String> names = expected.keys();
        while (names.hasNext()) {
            String name = names.next();
            if (!name.matches("lib[A-Za-z0-9_.]+\\.so") || name.contains("..")) throw new SecurityException("Native name invalid");
            File file = new File(directory, name);
            if (!file.getCanonicalFile().equals(file)) throw new SecurityException("Native alias refused");
            String actual = sha256(file);
            if (!actual.equals(expected.getString(name))) throw new SecurityException("Native digest mismatch: " + name);
            nativeFiles.put(name, actual);
        }
        return new JSONObject().put("schema", "foldgpt.runas.installation.v1").put("target", target)
            .put("qualification", qualification)
            .put("nativeLibraries", nativeFiles)
            .put("probeSha256", sha256(new File(directory, "libfoldgpt_runas_broker_bootstrap.so")))
            .put("transportSha256", sha256(new File(directory, "libfoldgpt_shizuku_transport.so")));
    }
    public static void requireSame(JSONObject expected, JSONObject actual) throws Exception {
        if (!expected.toString().equals(actual.toString())) {
            throw new SecurityException("Installed identities changed; this fixed attempt is refused");
        }
    }
}
