package app.foldgpt.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;

/** Real Java anonymous-pipe -> production Python supervisor -> DBus/GNOME.
 * Uses only an ephemeral test credential. Does not simulate Android Keystore,
 * execute ARM code or claim the full Android coordinator passed on a host JVM.
 */
public final class InactiveKeyringHostCheck {
    public static void main(String[] args) throws Exception {
        if(args.length!=1) throw new IllegalArgumentException("production supervisor source path");
        Path script=Path.of(args[0]).toAbsolutePath();
        Path work=Files.createTempDirectory("foldgpt-pipe-keyring-",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        try {
            Path home=Files.createDirectory(work.resolve("home"),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            String first=invoke(script,work,home,"first");
            byte[] intent=Files.readAllBytes(home.resolve(".local/share/.foldgpt-keyring-intent.json"));
            String resumed=invoke(script,work,home,"resumed");
            if(!first.equals(resumed) || !Arrays.equals(intent,Files.readAllBytes(home.resolve(".local/share/.foldgpt-keyring-intent.json"))))
                throw new IOException("Real supervised collection or journal changed on restart");
            System.out.println("PASS: Java transferred/erased the private pipe credential; real GNOME collection and intent survived a complete supervised daemon/bus restart");
        } finally { RootfsTransactionTest.removeFixture(work); }
    }
    private static String invoke(Path script,Path work,Path home,String name) throws Exception {
        Path runtime=Files.createDirectory(work.resolve(name),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        ProcessBuilder builder=new ProcessBuilder("/usr/bin/python3","-B",script.toString());
        builder.environment().clear(); builder.environment().putAll(Map.of("PATH","/usr/bin:/bin","HOME",home.toString(),
            "XDG_RUNTIME_DIR",runtime.toString(),"USER","foldgpt-test","PYTHONDONTWRITEBYTECODE","1"));
        byte[] credential="fixture-only Java pipe credential".getBytes(StandardCharsets.UTF_8);
        String output=SecretPipeProcess.run(builder,credential,30000);
        if(!Arrays.equals(credential,new byte[credential.length])) throw new IOException("Java retained the transferred credential");
        for(String line:output.split("\n")) if(line.startsWith("FOLDGPT_KEYRING_RECEIPT=")) return line;
        throw new IOException("Real keyring supervisor returned no receipt");
    }
}
