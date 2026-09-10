package app.foldgpt.runtimequalification;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashSet;
import java.util.Set;

/** Runtime-only admission and evidence. Kernel probe JSON is never accepted. */
final class RuntimeContract {
    static final String PROCESS = "runtime-qualification";
    static final String PYTHON = "libfoldgpt_python_cli.so";
    static final String MARKER = "@nativeLibraryDir/" + PYTHON;
    static final Set<String> PROOFS = Set.of("projectCreated", "sourceEdited", "unittestPassed",
        "zipappBuilt", "zipappExecuted", "rpcStdin", "childStreams", "childEnvironment", "bashCwd",
        "pythonCwd", "privateReadDenied", "privateWriteDenied", "protectedWriteDenied",
        "networkIpv4Denied", "networkUnixDenied", "ioctlDenied", "supervisorSignalDenied", "privateCwdDenied");

    static void require(boolean value, String message) {
        if (!value) throw new IllegalStateException(message);
    }
    static void keys(JSONObject object, Set<String> expected) {
        Set<String> actual = new HashSet<>();
        java.util.Iterator<String> names = object.keys();
        while (names.hasNext()) actual.add(names.next());
        require(actual.equals(expected), "Unexpected runtime JSON fields");
    }
    static void integer(JSONObject object, String name, int value) throws Exception {
        require(object.get(name) instanceof Integer && object.getInt(name) == value, "Runtime integer differs: " + name);
    }
    static JSONObject frame(JSONObject plan, String name, int id, String method) throws Exception {
        JSONObject frame = plan.getJSONObject(name);
        keys(frame, Set.of("id", "method", "params"));
        integer(frame, "id", id);
        require(method.equals(frame.get("method")), "Unexpected fixed runtime RPC method");
        return frame.getJSONObject("params");
    }
    static JSONObject resolveRequests(byte[] encoded, String nativeDirectory) throws Exception {
        return resolveRequests(encoded, nativeDirectory, RuntimeProfile.forPackage(RuntimeProfile.PACKAGE));
    }
    static JSONObject resolveRequests(byte[] encoded, String nativeDirectory, RuntimeProfile profile) throws Exception {
        require(encoded.length <= 32768, "Runtime request asset exceeds bound");
        // PackageManager supplies the real installed directory. Validate its
        // Android path syntax without interpreting it as a Windows host path.
        require(nativeDirectory != null && nativeDirectory.startsWith("/data/app/")
            && nativeDirectory.endsWith("/lib/arm64") && !nativeDirectory.contains("//")
            && !nativeDirectory.contains("\\") && nativeDirectory.indexOf('\0') < 0,
            "Runtime interpreter directory is not an actual package location");
        for (String part : nativeDirectory.substring(1).split("/")) {
            require(!part.equals(".") && !part.equals(".."), "Runtime native directory is not canonical");
        }
        JSONObject plan = new JSONObject(new String(encoded, StandardCharsets.UTF_8));
        keys(plan, Set.of("schema", "start", "write", "read", "file"));
        require("foldgpt.runtime-qualification.requests.v1".equals(plan.get("schema")), "Wrong runtime request schema");
        JSONObject start = frame(plan, "start", 2, "process/start");
        keys(start, Set.of("processId", "argv", "cwd", "env", "pipeStdin", "tty", "sandbox"));
        require(PROCESS.equals(start.get("processId")) && Boolean.TRUE.equals(start.get("pipeStdin"))
                && Boolean.FALSE.equals(start.get("tty")), "Wrong fixed runtime process shape");
        require(("file://" + profile.base + "/workspace").equals(start.get("cwd")), "Wrong runtime cwd");
        JSONArray argv = start.getJSONArray("argv");
        require(argv.length() == 5 && "bash".equals(argv.get(0)) && "--noprofile".equals(argv.get(1))
                && "--norc".equals(argv.get(2)) && "-c".equals(argv.get(3))
                && argv.get(4) instanceof String && argv.getString(4).length() <= 16384,
                "Wrong fixed runtime shell invocation");
        JSONObject env = start.getJSONObject("env");
        keys(env, Set.of("FOLDGPT_WORKSPACE", "FOLDGPT_PYTHON_REAL", "FOLDGPT_EXPECTED_PLATFORM"));
        require((profile.base + "/workspace").equals(env.get("FOLDGPT_WORKSPACE"))
                && "android".equals(env.get("FOLDGPT_EXPECTED_PLATFORM"))
                && MARKER.equals(env.get("FOLDGPT_PYTHON_REAL")), "Wrong packaged runtime environment");
        // This one authenticated filename marker is the entire substitution surface.
        env.put("FOLDGPT_PYTHON_REAL", nativeDirectory + "/" + PYTHON);
        JSONObject write = frame(plan, "write", 3, "process/write");
        keys(write, Set.of("processId", "writeId", "chunk"));
        require(PROCESS.equals(write.get("processId")) && "qualification-input-v1".equals(write.get("writeId"))
                && "bmF0aXZlIGlucHV0Cg==".equals(write.get("chunk")), "Wrong fixed RPC stdin");
        JSONObject read = frame(plan, "read", 4, "process/read");
        keys(read, Set.of("processId")); require(PROCESS.equals(read.get("processId")), "Wrong fixed read");
        JSONObject file = frame(plan, "file", 5, "fs/readFile");
        keys(file, Set.of("path", "sandbox"));
        require(("file://" + profile.base + "/workspace/qualification-result.json").equals(file.get("path")),
                "Wrong material result path");
        return plan;
    }
    static byte[] decode(String value) {
        byte[] decoded = Base64.getDecoder().decode(value);
        require(Base64.getEncoder().encodeToString(decoded).equals(value), "Noncanonical runtime output encoding");
        return decoded;
    }
    static byte[][] streams(JSONObject read) throws Exception {
        ByteArrayOutputStream stdout = new ByteArrayOutputStream(), stderr = new ByteArrayOutputStream();
        JSONArray chunks = read.getJSONArray("chunks");
        for (int i = 0; i < chunks.length(); ++i) {
            JSONObject chunk = chunks.getJSONObject(i);
            String stream = chunk.getString("stream");
            require("stdout".equals(stream) || "stderr".equals(stream), "Unknown runtime output stream");
            byte[] bytes = decode(chunk.getString("chunk"));
            ("stdout".equals(stream) ? stdout : stderr).write(bytes);
            require(stdout.size() + stderr.size() <= 8192, "Runtime output exceeds bound");
        }
        return new byte[][] {stdout.toByteArray(), stderr.toByteArray()};
    }
    static JSONObject validateResult(byte[] stdout, byte[] stderr, JSONObject read,
                                     JSONObject material, String nativeDirectory) throws Exception {
        return validateResult(stdout, stderr, read, material, nativeDirectory, RuntimeProfile.forPackage(RuntimeProfile.PACKAGE));
    }
    static JSONObject validateResult(byte[] stdout, byte[] stderr, JSONObject read,
                                     JSONObject material, String nativeDirectory, RuntimeProfile profile) throws Exception {
        require(Boolean.TRUE.equals(read.get("exited")) && Boolean.TRUE.equals(read.get("closed"))
            && read.has("failure") && read.isNull("failure") && Boolean.FALSE.equals(read.get("sandboxDenied")),
            "Runtime process did not finish cleanly");
        integer(read, "exitCode", 0);
        require(stderr.length == 0 && stdout.length > 0 && stdout.length <= 8192
            && stdout[stdout.length - 1] == '\n', "Runtime must produce one bounded JSON line without stderr");
        String text = new String(stdout, StandardCharsets.UTF_8);
        require(text.indexOf('\n') == text.length() - 1 && text.indexOf('\r') < 0, "Unexpected runtime result lines");
        require(Arrays.equals(stdout, decode(material.getString("dataBase64"))), "Material RPC bytes differ from stdout");
        JSONObject worker = new JSONObject(text);
        keys(worker, Set.of("type", "success", "platform", "python", "executable", "workspace", "bashCwd", "pythonCwd",
            "proofs", "denials", "unittestCount", "unittestStderr", "sourceSha256", "initialSourceSha256",
            "zipappBytes", "zipappSha256", "zipappStdout", "childExitCode", "childStdoutBase64", "childStderr"));
        require("runtime-qualification".equals(worker.get("type")) && Boolean.TRUE.equals(worker.get("success"))
            && "android".equals(worker.get("platform")) && "3.14.7".equals(worker.get("python"))
            && (nativeDirectory + "/" + PYTHON).equals(worker.get("executable"))
            && (profile.base + "/workspace").equals(worker.get("workspace"))
            && (profile.base + "/workspace/directory").equals(worker.get("bashCwd"))
            && (profile.base + "/workspace/directory/project").equals(worker.get("pythonCwd")),
            "Runtime worker identity or actual cwd differs");
        JSONObject proofs = worker.getJSONObject("proofs"); keys(proofs, PROOFS);
        Set<String> denied = new HashSet<>();
        for (String proof : PROOFS) {
            require(Boolean.TRUE.equals(proofs.get(proof)), "Runtime proof failed: " + proof);
            if (proof.endsWith("Denied")) denied.add(proof);
        }
        JSONObject denials = worker.getJSONObject("denials"); keys(denials, denied);
        for (String name : denied) require(denials.get(name) instanceof Integer
            && (denials.getInt(name) == 1 || denials.getInt(name) == 13), "Wrong actual permission errno");
        integer(worker, "unittestCount", 3); integer(worker, "childExitCode", 23);
        require("42\n".equals(worker.get("zipappStdout")) && "AP9BQkM=".equals(worker.get("childStdoutBase64"))
            && "native stderr\n".equals(worker.get("childStderr")) && worker.get("zipappBytes") instanceof Integer
            && worker.getInt("zipappBytes") > 0 && worker.getInt("zipappBytes") <= 16777216,
            "Runtime build or child streams differ");
        String tests = worker.getString("unittestStderr");
        require(tests.contains("Ran 3 tests in ") && tests.endsWith("\nOK\n"), "Actual unittest completion missing");
        for (String name : Set.of("test_edited_answer", "test_signed_addition", "test_invalid_operand")) {
            require(tests.contains(name + " (test_calculator.CalculatorTests." + name + ") ... ok\n"), "Expected unittest pass missing");
        }
        return worker;
    }
}
