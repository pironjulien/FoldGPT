package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import static org.junit.Assert.*;

public final class InstalledLibraryTest {
    private File directory;
    private File library;
    private String digest;

    @Before public void prepare() throws Exception {
        directory = Files.createTempDirectory("foldgpt-installed-library-").toFile().getCanonicalFile();
        library = new File(directory, InstalledLibrary.CWD_NAME);
        byte[] content = new byte[] {0x7f, 'E', 'L', 'F', 0, 1, 2, 3};
        Files.write(library.toPath(), content);
        StringBuilder value = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(content))
            value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        digest = value.toString();
    }

    @After public void close() throws Exception {
        Files.deleteIfExists(library.toPath());
        Files.deleteIfExists(directory.toPath());
    }

    private JSONObject options(String path, String hash) throws Exception {
        return new JSONObject().put("cwdShim", new JSONObject().put("path", path).put("sha256", hash));
    }

    @Test public void resolvesOnlyFixedNameAndActualInstalledBytes() throws Exception {
        InstalledLibrary.verifyCwd(options(InstalledLibrary.CWD_PATH, digest), directory);
        assertEquals(library, InstalledLibrary.verify(directory, InstalledLibrary.CWD_NAME, digest));
        Files.write(library.toPath(), new byte[] {9});
        SecurityException error = assertThrows(SecurityException.class,
                () -> InstalledLibrary.verifyCwd(options(InstalledLibrary.CWD_PATH, digest), directory));
        assertTrue(error.getMessage().contains("digest mismatch"));
    }

    @Test public void cannotSelectAbsoluteAlternateOrTraversingPath() throws Exception {
        for (String path : new String[] {library.getPath(), "/data/local/tmp/shim.so",
                "@nativeLibraryDir/../" + InstalledLibrary.CWD_NAME,
                "@nativeLibraryDir/libother.so"}) {
            assertThrows(SecurityException.class,
                    () -> InstalledLibrary.verifyCwd(options(path, digest), directory));
        }
    }

    @Test public void missingOrMalformedAttestationFails() throws Exception {
        assertThrows(SecurityException.class,
                () -> InstalledLibrary.verifyCwd(options(InstalledLibrary.CWD_PATH, "0".repeat(64)), directory));
        JSONObject extra = options(InstalledLibrary.CWD_PATH, digest);
        extra.getJSONObject("cwdShim").put("override", true);
        assertThrows(SecurityException.class, () -> InstalledLibrary.verifyCwd(extra, directory));
        Files.delete(library.toPath());
        assertThrows(SecurityException.class,
                () -> InstalledLibrary.verifyCwd(options(InstalledLibrary.CWD_PATH, digest), directory));
    }

    @Test public void absentOptionDoesNotSelectAnyShim() throws Exception {
        Files.delete(library.toPath());
        InstalledLibrary.verifyCwd(new JSONObject(), directory);
    }
}
