package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class InactiveClientInstallCommandTest {
    private static final String ID="a".repeat(64);
    @Test public void guestRootCommandUsesActualPackagedProotAndPrivateBindingsOnly() throws Exception {
        ProcessBuilder process=InactiveClientInstallCommand.create(Path.of("/apk/native"),Path.of("/private/stage/root"),
            Path.of("/private/cache/run"),ID,"1040:2123",1234);
        List<String> command=process.command();
        assertEquals("/apk/native/libproot.so",command.get(0));
        assertTrue(command.containsAll(List.of("--kill-on-exit","--link2symlink","--sysvipc","-0",
            "/private/cache/run/input:/tmp/foldgpt-client-input","/private/cache/run/tmp:/tmp",
            "/tmp/foldgpt-client-input/install_official_client.py",ID,"1040:2123")));
        assertEquals("2",command.get(command.size()-1));
        assertFalse(command.contains("--no-sandbox"));
        assertFalse(command.stream().anyMatch(value -> value.contains("DISPLAY=") || value.contains("LD_PRELOAD=")
            || value.contains("DBUS_SESSION_BUS_ADDRESS=") || value.contains("/home/foldgpt:")));
        assertEquals(Set.of("PATH","LD_LIBRARY_PATH","PROOT_LOADER","PROOT_LOADER_32","PROOT_TMP_DIR","TMPDIR"),
            process.environment().keySet());
        assertEquals("/apk/native/libproot-loader.so",process.environment().get("PROOT_LOADER"));
    }
    @Test public void ambiguousPathsAndInvalidBindingsAreRejected() throws Exception {
        for(Path path:List.of(Path.of("relative"),Path.of("/private/../escape"),Path.of("/private/bind:escape"),Path.of("/private/bad\nline"))) {
            try { InactiveClientInstallCommand.create(Path.of("/native"),path,Path.of("/work"),ID,"1:2",1000); fail(path.toString()); }
            catch(IOException expected) {}
        }
        for(String id:List.of("",ID+"\n","G".repeat(64))) {
            try { InactiveClientInstallCommand.create(Path.of("/native"),Path.of("/root"),Path.of("/work"),id,"1:2",1000); fail(id); }
            catch(IOException expected) {}
        }
        try { InactiveClientInstallCommand.create(Path.of("/native"),Path.of("/root"),Path.of("/work"),ID,"1:2",0); fail(); }
        catch(IOException expected) {}
    }
    @Test public void actualSubprocessReceivesEofAndKeepsPrivateFailureEvidence() throws Exception {
        Path directory=Files.createTempDirectory("foldgpt-client-command-test-");
        try {
            assertEquals("actual output\n",InactiveClientInstallCommand.run(new ProcessBuilder("/usr/bin/python3","-c",
                "import sys; assert sys.stdin.read() == ''; print('actual output')"),5000,directory.resolve("success.log"),Process::destroy));
            try { InactiveClientInstallCommand.run(new ProcessBuilder("/usr/bin/python3","-c",
                "import sys; print('failure evidence'); sys.exit(19)"),5000,directory.resolve("failure.log"),Process::destroy); fail(); }
            catch(IOException expected) { assertTrue(expected.getMessage().contains("exit=19")); }
            assertEquals("failure evidence\n",Files.readString(directory.resolve("failure.log")));
            assertEquals("rw-------",java.nio.file.attribute.PosixFilePermissions.toString(Files.getPosixFilePermissions(directory.resolve("failure.log"))));
        } finally {
            Files.deleteIfExists(directory.resolve("success.log")); Files.deleteIfExists(directory.resolve("failure.log")); Files.delete(directory);
        }
    }
    @Test public void outputFloodDeadlineAndInterruptionDoNotHang() throws Exception {
        long start=System.nanoTime();
        try { InactiveClientInstallCommand.run(new ProcessBuilder("/usr/bin/python3","-c","import time; time.sleep(30)"),100,null,Process::destroy); fail(); }
        catch(IOException expected) { assertTrue(expected.getMessage().contains("deadline")); }
        assertTrue(System.nanoTime()-start<java.util.concurrent.TimeUnit.SECONDS.toNanos(5));
        try { InactiveClientInstallCommand.run(new ProcessBuilder("/usr/bin/python3","-c","print('x'*65537)"),5000,null,Process::destroy); fail(); }
        catch(IOException expected) {}
        Thread.currentThread().interrupt();
        try { InactiveClientInstallCommand.run(new ProcessBuilder("/usr/bin/python3","-c","import time; time.sleep(30)"),5000,null,Process::destroy); fail(); }
        catch(InterruptedException expected) {}
        finally { Thread.interrupted(); }
    }
}
