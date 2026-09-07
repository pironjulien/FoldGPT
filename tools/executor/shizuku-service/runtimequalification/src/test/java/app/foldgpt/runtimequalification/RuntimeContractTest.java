package app.foldgpt.runtimequalification;

import org.junit.Test;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import static org.junit.Assert.*;

/** PC parser tests only; their synthetic package path is not device evidence. */
public final class RuntimeContractTest {
    private static final String DIRECTORY = "/data/app/test.package/lib/arm64";
    private JSONObject plan() throws Exception {
        return plan("/runtime-requests.json");
    }
    private JSONObject plan(String resource) throws Exception {
        try (InputStream input = getClass().getResourceAsStream(resource)) {
            assertNotNull(input);
            return new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }
    private JSONObject resolve(JSONObject value) throws Exception {
        return RuntimeContract.resolveRequests(value.toString().getBytes(StandardCharsets.UTF_8), DIRECTORY);
    }
    @Test public void onlyTheFixedFilenameMarkerIsResolved() throws Exception {
        JSONObject before = plan(), after = resolve(before);
        assertEquals(DIRECTORY + "/" + RuntimeContract.PYTHON,
            after.getJSONObject("start").getJSONObject("params").getJSONObject("env").get("FOLDGPT_PYTHON_REAL"));
        assertEquals(before.getJSONObject("start").getJSONObject("params").getJSONArray("argv").toString(),
            after.getJSONObject("start").getJSONObject("params").getJSONArray("argv").toString());
        assertEquals(before.getJSONObject("write").toString(), after.getJSONObject("write").toString());
    }
    @Test public void modifiedInputAndAlternateExecutableAreRefused() throws Exception {
        JSONObject changed = plan();
        changed.getJSONObject("write").getJSONObject("params").put("chunk", "d3Jvbmc=");
        try { resolve(changed); fail("Changed stdin was admitted"); } catch (IllegalStateException expected) { }
        changed = plan();
        changed.getJSONObject("start").getJSONObject("params").getJSONObject("env")
            .put("FOLDGPT_PYTHON_REAL", "/system/bin/sh");
        try { resolve(changed); fail("Alternate ELF was admitted"); } catch (IllegalStateException expected) { }
        changed = plan();
        changed.getJSONObject("start").getJSONObject("params").put("pipeStdin", 1);
        try { resolve(changed); fail("Coerced bool was admitted"); } catch (IllegalStateException expected) { }
    }
    @Test public void kernelResultCannotPassRuntimeValidation() throws Exception {
        byte[] bytes = "{\"type\":\"kernel-qualification\",\"success\":true}\n".getBytes(StandardCharsets.UTF_8);
        JSONObject read = new JSONObject().put("exited", true).put("closed", true).put("exitCode", 0)
            .put("failure", JSONObject.NULL).put("sandboxDenied", false);
        JSONObject material = new JSONObject().put("dataBase64", Base64.getEncoder().encodeToString(bytes));
        try { RuntimeContract.validateResult(bytes, new byte[0], read, material, DIRECTORY); fail("Kernel success was accepted"); }
        catch (IllegalStateException expected) { }
        read.put("exitCode", false);
        try { RuntimeContract.validateResult(bytes, new byte[0], read, material, DIRECTORY); fail("Coerced exit was accepted"); }
        catch (IllegalStateException expected) { }
    }
    @Test public void materialBytesMustEqualActualStdout() throws Exception {
        byte[] bytes = "{}\n".getBytes(StandardCharsets.UTF_8);
        JSONObject read = new JSONObject().put("exited", true).put("closed", true).put("exitCode", 0)
            .put("failure", JSONObject.NULL).put("sandboxDenied", false);
        JSONObject material = new JSONObject().put("dataBase64", "d3Jvbmc=");
        try { RuntimeContract.validateResult(bytes, new byte[0], read, material, DIRECTORY); fail("Different material accepted"); }
        catch (IllegalStateException expected) { assertTrue(expected.getMessage().contains("Material")); }
    }
    @Test public void binaryStreamsRemainSeparateAndBounded() throws Exception {
        JSONObject read = new JSONObject().put("chunks", new JSONArray()
            .put(new JSONObject().put("stream", "stdout").put("chunk", "AP9BQkM="))
            .put(new JSONObject().put("stream", "stderr").put("chunk", "ZXJyb3I=")));
        byte[][] streams = RuntimeContract.streams(read);
        assertArrayEquals(new byte[] {0, (byte)255, 65, 66, 67}, streams[0]);
        assertArrayEquals("error".getBytes(StandardCharsets.UTF_8), streams[1]);
        read.getJSONArray("chunks").getJSONObject(0).put("stream", "merged");
        try { RuntimeContract.streams(read); fail("Unknown stream accepted"); } catch (IllegalStateException expected) { }
        read.put("chunks", new JSONArray().put(new JSONObject().put("stream", "stdout")
            .put("chunk", Base64.getEncoder().encodeToString(new byte[8193]))));
        try { RuntimeContract.streams(read); fail("Unbounded output accepted"); } catch (IllegalStateException expected) { }
    }
    @Test public void v2RequestsCannotCrossTheV1ApplicationBoundary() throws Exception {
        RuntimeProfile v1 = RuntimeProfile.forPackage("app.foldgpt.runtimequalification.v1");
        RuntimeProfile v2 = RuntimeProfile.forPackage("app.foldgpt.runtimequalification.v2");
        byte[] request1 = plan().toString().getBytes(StandardCharsets.UTF_8);
        byte[] request2 = plan("/runtime-requests-v2.json").toString().getBytes(StandardCharsets.UTF_8);
        JSONObject resolved = RuntimeContract.resolveRequests(request2, DIRECTORY, v2);
        assertEquals("file://" + v2.base + "/workspace", resolved.getJSONObject("start").getJSONObject("params").get("cwd"));
        try { RuntimeContract.resolveRequests(request1, DIRECTORY, v2); fail("V1 request crossed into V2"); }
        catch (IllegalStateException expected) { }
        try { RuntimeContract.resolveRequests(request2, DIRECTORY, v1); fail("V2 request crossed into V1"); }
        catch (IllegalStateException expected) { }
    }
    @Test public void onlyTwoExplicitPackageIdentitiesSelectReportsAndActions() throws Exception {
        RuntimeProfile v1 = RuntimeProfile.forPackage("app.foldgpt.runtimequalification.v1");
        RuntimeProfile v2 = RuntimeProfile.forPackage("app.foldgpt.runtimequalification.v2");
        assertEquals(1, v1.diagnosticVersion); assertEquals("runtime-v1", v1.reportDirectory);
        assertEquals(".RUNTIME_RUN_FIXED_V1", v1.runAction);
        assertEquals(2, v2.diagnosticVersion); assertEquals("runtime-v2", v2.reportDirectory);
        assertEquals(".RUNTIME_RUN_FIXED_V2", v2.runAction);
        assertNotEquals(v1.base, v2.base); assertNotEquals(v1.serviceTag, v2.serviceTag);
        assertNotEquals(v1.processSuffix, v2.processSuffix);
        for (String name : new String[] {"app.foldgpt.runtimequalification.v3", "app.foldgpt.runtimequalification.v2.", "app.foldgpt"}) {
            try { RuntimeProfile.forPackage(name); fail("Unknown package admitted"); }
            catch (SecurityException expected) { }
        }
    }
}
