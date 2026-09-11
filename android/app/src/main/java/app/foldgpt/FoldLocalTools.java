package app.foldgpt;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.AtomicFile;
import app.foldgpt.install.GuestIdentity;
import org.json.JSONObject;
import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.UUID;

/** Installs only FoldGPT-owned tools/context, retaining the native runtime contract. */
public final class FoldLocalTools {
    private FoldLocalTools() {}

    public static File install(Context context, GuestIdentity identity, File shellHome) throws Exception {
        File files = context.getFilesDir().getCanonicalFile();
        int uid = context.getApplicationInfo().uid;
        File tools = directory(files, "foldgpt-tools", uid);
        File bin = directory(files, "foldgpt-tools/bin", uid);
        writeAsset(context, tools, "foldgpt_tools.py", "foldgpt-tools/foldgpt_tools.py", uid);
        JSONObject config = new JSONObject();
        config.put("schema", "foldgpt.local-tools.v1");
        config.put("uid", uid);
        config.put("filesDir", files.getPath());
        config.put("nativeLibraryDir", context.getApplicationInfo().nativeLibraryDir);
        config.put("guestHome", identity.home);
        config.put("guestUser", identity.user);
        config.put("guestIds", identity.prootIds());
        config.put("versionCode", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
        write(new File(tools, "installation.json"), (config.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);
        String target = context.getApplicationInfo().nativeLibraryDir + "/libfoldgpt_tools_launcher.so";
        if (!new File(target).isFile()) throw new IOException("FoldGPT tool launcher is absent from the APK");
        for (String name : new String[]{"foldgpt", "git", "make", "node", "npm", "npx", "gcc", "g++", "diff", "tar", "gzip", "xz",
                "workspace-node", "workspace-python3", "pnpm", "pdftoppm", "pdftotext", "pdfinfo", "libreoffice",
                "soffice", "heif-convert", "JxrDecApp"}) {
            File link = new File(bin, name);
            try {
                StructStat state = Os.lstat(link.getPath());
                if (!OsConstants.S_ISLNK(state.st_mode) || state.st_uid != uid)
                    throw new IOException("Tool alias is not an app-owned link: " + name);
                if (Os.readlink(link.getPath()).equals(target)) continue;
            } catch (ErrnoException absent) {
                if (absent.errno != OsConstants.ENOENT) throw absent;
            }
            File temporary = new File(bin, "." + name + "." + UUID.randomUUID());
            Os.symlink(target, temporary.getPath());
            Os.rename(temporary.getPath(), link.getPath());
        }
        File contextDir = directory(files, "debian/usr/local/lib/foldgpt", uid);
        File share = directory(files, "debian/usr/local/share/foldgpt", uid);
        writeAsset(context, contextDir, "foldgpt_agent_context.py", "foldgpt-tools/foldgpt_agent_context.py", uid);
        writeAsset(context, contextDir, "foldgpt-workspace-provider.cjs", "foldgpt-tools/foldgpt-workspace-provider.cjs", uid);
        writeAsset(context, contextDir, "install-workspace-provider.py", "foldgpt-tools/install-workspace-provider.py", uid);
        // Ship the admission-before-context ordering together with its adapter.
        // Updating Python alone would leave the previous guest launch order.
        File guestBin = directory(files, "debian/usr/local/bin", uid);
        writeAsset(context, guestBin, "foldgpt-session", "foldgpt-tools/foldgpt-session.sh", uid);
        // dbus-run-session re-executes this script, so it must be executable.
        Os.chmod(new File(guestBin, "foldgpt-session").getPath(), 0700);
        for (String name : new String[]{"workspace-node-check.cjs", "workspace-python-check.py", "workspace-render-check.py"})
            writeAsset(context, contextDir, name, "foldgpt-tools/" + name, uid);
        writeAsset(context, share, "agent-environment.v1.json", "foldgpt-tools/agent-environment.v1.json", uid);
        JSONObject bridge = new JSONObject().put("schema", "foldgpt.android.bridge.v1").put("androidUid", uid);
        write(new File(share, "android-bridge.json"), (bridge.toString() + "\n").getBytes(StandardCharsets.UTF_8), uid);
        // Plugin source is APK-owned and isolated from official plugin caches.
        File androidPlugin = directory(files, "debian/usr/local/share/foldgpt/plugins/foldgpt-android", uid);
        installPluginAssets(context, files, "foldgpt-android", "debian/usr/local/share/foldgpt/plugins/foldgpt-android", uid);
        if (!shellHome.getCanonicalFile().toPath().startsWith(files.toPath()))
            throw new IOException("Native shell home is outside FoldGPT files");
        installShellPath(new File(shellHome, ".profile"), bin, uid);
        installShellPath(new File(shellHome, ".bashrc"), bin, uid);
        return tools;
    }

    private static void installShellPath(File profile, File bin, int uid) throws Exception {
        String begin = "# foldgpt:local-tools:v1 begin\n";
        String end = "# foldgpt:local-tools:v1 end\n";
        String path = bin.getPath().replace("'", "'\"'\"'");
        String block = begin + "case :${PATH-}: in\n  *:'" + path + "':*) ;;\n"
                + "  *) export PATH='" + path + "'${PATH:+:$PATH} ;;\nesac\n" + end;
        String original = "";
        try {
            StructStat state = Os.lstat(profile.getPath());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1 || state.st_size > 65536)
                throw new IOException("Native shell profile is not an owned bounded regular file");
            byte[] bytes = Files.readAllBytes(profile.toPath());
            original = new String(bytes, StandardCharsets.UTF_8);
            if (!Arrays.equals(bytes, original.getBytes(StandardCharsets.UTF_8)))
                throw new IOException("Native shell profile is not UTF-8");
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        }
        int first = original.indexOf(begin), last = original.indexOf(end);
        if ((first < 0) != (last < 0) || (first >= 0 && (last < first
                || original.indexOf(begin, first + begin.length()) >= 0
                || original.indexOf(end, last + end.length()) >= 0)))
            throw new IOException("Ambiguous FoldGPT shell profile block");
        String merged = first < 0 ? original + (original.isEmpty() || original.endsWith("\n") ? "" : "\n") + block
                : original.substring(0, first) + block + original.substring(last + end.length());
        byte[] bytes = merged.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 65536) throw new IOException("Native shell profile exceeds its bound");
        write(profile, bytes, uid);
    }

    private static void installPluginAssets(Context context, File files, String asset, String relative, int uid) throws Exception {
        String[] children = context.getAssets().list(asset);
        if (children == null) throw new IOException("Missing Android plugin assets");
        File destination = directory(files, relative, uid);
        for (String child : children) {
            if (!child.matches("[A-Za-z0-9_.-]+")) throw new IOException("Unexpected Android plugin asset name");
            String entry = asset + "/" + child;
            String[] nested = context.getAssets().list(entry);
            if (nested != null && nested.length > 0) installPluginAssets(context, files, entry, relative + "/" + child, uid);
            else writeAsset(context, destination, child, entry, uid);
        }
    }

    private static File directory(File root, String relative, int uid) throws Exception {
        File current = root;
        for (String part : relative.split("/")) {
            current = new File(current, part);
            try { Os.mkdir(current.getPath(), 0700); }
            catch (ErrnoException exists) { if (exists.errno != OsConstants.EEXIST) throw exists; }
            StructStat state = Os.lstat(current.getPath());
            if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid)
                throw new IOException("FoldGPT tool directory is not app-owned: " + relative);
        }
        return current;
    }

    private static void writeAsset(Context context, File directory, String name, String asset, int uid) throws Exception {
        try (InputStream stream = context.getAssets().open(asset)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = stream.read(buffer)) != -1) {
                if (bytes.size() + count > 65536) throw new IOException("FoldGPT tool asset is too large");
                bytes.write(buffer, 0, count);
            }
            write(new File(directory, name), bytes.toByteArray(), uid);
        }
    }

    private static void write(File file, byte[] bytes, int uid) throws Exception {
        try {
            StructStat state = Os.lstat(file.getPath());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1)
                throw new IOException("FoldGPT tool destination is not an owned regular file: " + file.getName());
            if (Arrays.equals(Files.readAllBytes(file.toPath()), bytes)) return;
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        }
        AtomicFile atomic = new AtomicFile(file);
        FileOutputStream output = null;
        try {
            output = atomic.startWrite();
            output.write(bytes);
            Os.fchmod(output.getFD(), 0600);
            atomic.finishWrite(output);
        } catch (Exception error) {
            if (output != null) atomic.failWrite(output);
            throw error;
        }
    }
}
