package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import org.junit.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.junit.Assert.*;

/** Actual host admission failures exercise diagnosis, never Android sandbox success. */
public final class AdmissionTraceTest {
    @Test public void recordsActualPackagedLibraryFailureAndNestedCause() throws Exception {
        Path directory = Files.createTempDirectory("foldgpt-admission-").toRealPath();
        Path library = directory.resolve("libtest.so");
        AdmissionTrace trace = new AdmissionTrace();
        trace.at(AdmissionTrace.Stage.NATIVE_INVENTORY); trace.subject(library.getFileName().toString());
        try {
            Files.write(library, new byte[] {0x7f, 'E', 'L', 'F'});
            Exception failure = assertThrows(SecurityException.class,
                () -> InstalledLibrary.verify(directory.toFile(), "libtest.so", "0".repeat(64)));
            JSONObject report = trace.result(false, new IllegalStateException("outer transport wrapper", failure));
            assertFalse(report.getBoolean("admitted"));
            assertEquals("native_inventory", report.getString("stage"));
            assertEquals("libtest.so", report.getString("subject"));
            JSONObject cause = report.getJSONObject("error");
            assertEquals("SecurityException", cause.getString("errorType"));
            assertEquals("Packaged native library digest mismatch", cause.getString("message"));
            assertEquals("InstalledLibrary.java", cause.getString("source"));
            assertTrue(cause.getInt("line") > 0); assertTrue(cause.isNull("errno"));
            assertFalse(report.has("cleanupComplete")); assertFalse(report.has("ownerRetained"));
        } finally { Files.deleteIfExists(library); Files.delete(directory); }
    }
    @Test public void diagnosesActualIoFailureWithoutExposingStackOrUnboundedMessage() throws Exception {
        Path directory = Files.createTempDirectory("foldgpt-admission-io-");
        Exception missing;
        try { missing = assertThrows(java.nio.file.NoSuchFileException.class, () -> Files.readAllBytes(directory.resolve("absent"))); }
        finally { Files.delete(directory); }
        JSONObject actual = AdmissionTrace.failure(missing);
        assertEquals("NoSuchFileException", actual.getString("errorType"));
        assertTrue(actual.getString("message").length() <= 160);
        assertEquals(5, actual.length());
        String dangerous = "\n\u2603\"\\" + "x".repeat(1000);
        JSONObject bounded = AdmissionTrace.failure(new IllegalArgumentException(dangerous));
        assertEquals(160, bounded.getString("message").length());
        assertTrue(bounded.getString("message").startsWith("????"));
        assertFalse(bounded.toString().contains("\\n"));
        assertFalse(bounded.has("stackTrace"));
    }
    @Test public void factsAreBoundedAndNeverSurviveIntoAnotherStageOrSubject() throws Exception {
        AdmissionTrace trace = new AdmissionTrace();
        trace.at(AdmissionTrace.Stage.PYTHON_ALIASES); trace.subject("x".repeat(1000));
        trace.fact("expected", "y".repeat(4000)); trace.fact("mode", 41471);
        JSONObject first = trace.result(false, new SecurityException("alias differs"));
        assertEquals(192, first.getString("subject").length());
        assertEquals(1024, first.getJSONObject("facts").getString("expected").length());
        assertThrows(IllegalArgumentException.class, () -> trace.fact("environment", "private"));
        assertThrows(IllegalArgumentException.class, () -> trace.fact("observed", new JSONObject()));
        trace.subject("next"); assertEquals(0, trace.result(false, null).getJSONObject("facts").length());
        trace.at(AdmissionTrace.Stage.COMPLETE);
        JSONObject last = trace.result(true, null);
        assertEquals("", last.getString("subject")); assertTrue(last.isNull("error"));
        assertFalse(last.has("cleanupComplete"));
    }
    @Test public void causeCyclesCannotMakeDiagnosticUnbounded() throws Exception {
        Exception a = new Exception("first"), b = new Exception("second"); a.initCause(b); b.initCause(a);
        assertEquals("second", AdmissionTrace.failure(a).getString("message"));
    }
}
