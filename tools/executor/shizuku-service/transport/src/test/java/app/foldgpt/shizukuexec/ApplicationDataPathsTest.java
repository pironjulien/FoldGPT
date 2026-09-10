package app.foldgpt.shizukuexec;

import java.io.File;
import java.nio.file.Files;
import org.junit.Test;
import static org.junit.Assert.*;

/** Real host path resolution tests; Android's DATA inode admission is device-only. */
public final class ApplicationDataPathsTest {
    @Test public void canonicalPathsAdmitOnlyTheRootAndExactDescendants() throws Exception {
        File root = Files.createTempDirectory("foldgpt-canonical-data-").toFile().getCanonicalFile();
        try {
            assertTrue(ApplicationDataPaths.canonicalExact(root, root));
            assertTrue(ApplicationDataPaths.canonicalExact(root, new File(root, "app_foldgpt_exec/session/launch.json")));
            assertFalse(ApplicationDataPaths.canonicalExact(root, new File(root.getParentFile(), root.getName() + "-other/file")));
            assertFalse(ApplicationDataPaths.canonicalExact(root, new File(root, "../other/file")));
            assertFalse(ApplicationDataPaths.canonicalExact(root, new File(root, "inside/../launch.json")));
            assertFalse(ApplicationDataPaths.canonicalExact(root, new File(root, "./launch.json")));
            assertFalse(ApplicationDataPaths.canonicalExact(root, new File("relative/launch.json")));
        } finally { Files.delete(root.toPath()); }
    }
}
