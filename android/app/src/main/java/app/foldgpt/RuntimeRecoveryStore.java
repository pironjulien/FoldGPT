package app.foldgpt;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Single writer: FoldRuntimeService in :runtime. The display cannot grant intent. */
public final class RuntimeRecoveryStore {
    private final AtomicFile file;
    private final String bootId;

    public RuntimeRecoveryStore(Context context) throws Exception {
        file = new AtomicFile(new File(context.getFilesDir(), "runtime-user-intent.json"));
        // The ordinary Android app cannot rely on proc sysctl visibility.
        // Reuse the same default-free provider epoch admitted by native startup.
        bootId = "android.provider.Settings.Global.BOOT_COUNT:"
                + app.foldgpt.shizukuexec.AndroidBootEpoch.capture(context).getInt("bootCount");
    }

    public RuntimeRecoveryPolicy load() throws Exception {
        if (!file.getBaseFile().exists() && !new File(file.getBaseFile() + ".bak").exists())
            return new RuntimeRecoveryPolicy(bootId);
        byte[] bytes = file.readFully();
        if (bytes.length > 4096) throw new IOException("Runtime intent exceeds its bound");
        return RuntimeRecoveryPolicy.restore(new JSONObject(new String(bytes, StandardCharsets.UTF_8)), bootId);
    }

    public RuntimeRecoveryPolicy empty() { return new RuntimeRecoveryPolicy(bootId); }

    public void save(RuntimeRecoveryPolicy policy) throws Exception {
        FileOutputStream output = null;
        try {
            byte[] bytes = (policy.snapshot().toString(2) + "\n").getBytes(StandardCharsets.UTF_8);
            output = file.startWrite();
            output.write(bytes);
            file.finishWrite(output);
        } catch (Exception error) {
            if (output != null) file.failWrite(output);
            throw error;
        }
    }
}
