package app.foldgpt.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.junit.Test;
import static org.junit.Assert.*;

public class SecretPipeProcessTest {
    private static ProcessBuilder python(String program) {
        ProcessBuilder builder=new ProcessBuilder("/usr/bin/python3","-c",program);
        builder.environment().clear(); builder.environment().put("PATH","/usr/bin:/bin"); return builder;
    }
    @Test public void transfersOnlyThroughStdinAndErasesOwnedArray() throws Exception {
        byte[] password="test-only private credential".getBytes(StandardCharsets.UTF_8);
        String expected=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(password));
        String result=SecretPipeProcess.run(python("import os,sys,hashlib\np=sys.stdin.buffer.read()\n"
            +"assert p not in open('/proc/self/cmdline','rb').read()\nassert p not in open('/proc/self/environ','rb').read()\n"
            +"assert os.read(0,1)==b''\nprint(hashlib.sha256(p).hexdigest())"),password,10000);
        assertEquals(expected+"\n",result); assertArrayEquals(new byte[password.length],password);
    }
    @Test public void failureDoesNotIncludeChildOutputAndStillErasesCredential() throws Exception {
        byte[] password="test-only should never be in exception".getBytes(StandardCharsets.UTF_8);
        try {
            SecretPipeProcess.run(python("import sys\np=sys.stdin.buffer.read()\nsys.stderr.buffer.write(p)\nsys.exit(7)"),password,10000);
            fail("Child failure accepted");
        } catch(SecretPipeProcess.ProcessFailure expected) {
            assertEquals(7,expected.exitCode); assertEquals(password.length,expected.capturedOutputBytes);
            assertEquals(SecretPipeProcess.FailureStage.UNKNOWN,expected.stage);
            assertEquals(SecretPipeProcess.FailureCode.NO_RECOGNIZED_DIAGNOSTIC,expected.code);
            assertFalse(expected.getMessage().contains("test-only"));
        }
        assertArrayEquals(new byte[password.length],password);
    }
    @Test public void reportsOnlyFixedLegacyStagesWithoutChangingThePinnedSupervisor() throws Exception {
        String[][] cases={
            {"FoldGPT inactive keyring preparation failed\\n","SUPERVISOR","SUPERVISOR_REPORTED_FAILURE"},
            {"FoldGPT keyring initialization failed; existing credentials were not replaced\\nFoldGPT inactive keyring preparation failed\\n","INITIALIZER","INITIALIZER_REFUSED"},
            {"FoldGPT keyring connection cleanup failed\\nFoldGPT inactive keyring preparation failed\\n","INITIALIZER_CLEANUP","INITIALIZER_CLEANUP_FAILURE"},
            {"CANNOT LINK EXECUTABLE hidden-name: hidden-context\\n","NATIVE_LOADER","NATIVE_LINKER_FAILURE"},
            {"proot error: hidden-context\\n","PROOT","PROOT_REPORTED_ERROR"},
            {"/usr/bin/python3: can't open file hidden-path\\n","PYTHON","PYTHON_CANNOT_OPEN_SOURCE"},
            {"ModuleNotFoundError: hidden-module\\n","PYTHON","PYTHON_IMPORT_FAILURE"},
            {"SyntaxError: hidden-source\\n","PYTHON","PYTHON_SOURCE_FAILURE"}
        };
        for(String[] item:cases) {
            byte[] password="test-only secret fixture".getBytes(StandardCharsets.UTF_8);
            // The fixed diagnostic is test data. Credential bytes reach the
            // subprocess only on stdin, including the deliberately noisy prefix.
            ProcessBuilder builder=python("import sys\np=sys.stdin.buffer.read()\nsys.stderr.buffer.write(p+b'\\n')\n"
                +"sys.stderr.write(sys.argv[1].replace('\\\\n','\\n'))\nsys.exit(9)");
            builder.command().add(item[0]);
            try { SecretPipeProcess.run(builder,password,10000); fail("Child failure accepted"); }
            catch(SecretPipeProcess.ProcessFailure expected) {
                assertEquals(9,expected.exitCode); assertEquals(item[1],expected.stage.name()); assertEquals(item[2],expected.code.name());
                assertFalse(expected.getMessage().contains("hidden-")); assertFalse(expected.getMessage().contains("test-only"));
                assertNull(expected.getCause());
            }
            assertArrayEquals(new byte[password.length],password);
        }
    }
    @Test public void arbitraryMarkerLikePayloadIsNotCopiedOrAcceptedAsAnExactHelperLine() throws Exception {
        byte[] password="test-only secret fixture".getBytes(StandardCharsets.UTF_8);
        ProcessBuilder builder=python("import sys\np=sys.stdin.buffer.read()\nsys.stderr.buffer.write("
            +"b'FoldGPT inactive keyring preparation failed '+p+b'\\nXFoldGPT keyring connection cleanup failed\\n')\nsys.exit(11)");
        try { SecretPipeProcess.run(builder,password,10000); fail("Child failure accepted"); }
        catch(SecretPipeProcess.ProcessFailure expected) {
            assertEquals(SecretPipeProcess.FailureStage.UNKNOWN,expected.stage);
            assertFalse(expected.getMessage().contains("test-only"));
        }
        assertArrayEquals(new byte[password.length],password);
    }
    @Test public void earlyChildExitPreservesItsStatusAndErasesTheUnconsumedCredential() throws Exception {
        byte[] password=new byte[8192]; Arrays.fill(password,(byte)'s');
        try { SecretPipeProcess.run(python("import sys\nsys.exit(19)"),password,10000); fail("Early exit accepted"); }
        catch(SecretPipeProcess.ProcessFailure expected) {
            assertEquals(19,expected.exitCode); assertEquals(0,expected.capturedOutputBytes);
            assertEquals(SecretPipeProcess.FailureStage.UNKNOWN,expected.stage);
        }
        assertArrayEquals(new byte[password.length],password);
    }
    @Test public void unresponsiveChildCannotHoldInputOrDeadlineForever() throws Exception {
        byte[] password=new byte[8192]; Arrays.fill(password,(byte)'p');
        long start=System.nanoTime();
        try {
            SecretPipeProcess.run(python("import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)"),password,250);
            fail("Unresponsive child accepted");
        } catch(IOException expected) { assertTrue(expected.getMessage().contains("deadline")); }
        assertTrue("Deadline/cleanup was unbounded",System.nanoTime()-start<15_000_000_000L);
        assertArrayEquals(new byte[password.length],password);
    }
    @Test public void refusesPlaintextFileRedirectionAndOversizedOutput() throws Exception {
        byte[] password="test-only credential".getBytes(StandardCharsets.UTF_8);
        ProcessBuilder redirected=python("pass").redirectInput(ProcessBuilder.Redirect.INHERIT);
        try { SecretPipeProcess.run(redirected,password,10000); fail("Inherited input accepted"); }
        catch(IOException expected) { assertTrue(expected.getMessage().contains("anonymous")); }
        assertArrayEquals(new byte[password.length],password);
        byte[] second="test-only credential".getBytes(StandardCharsets.UTF_8);
        try { SecretPipeProcess.run(python("import sys\nsys.stdin.buffer.read()\nsys.stdout.write('x'*100000)"),second,10000); fail("Output flood accepted"); }
        catch(IOException expected) { assertTrue(expected.getMessage().contains("output exceeds")); }
        assertArrayEquals(new byte[second.length],second);
    }
}
