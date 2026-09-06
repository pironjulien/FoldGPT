package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** Opt-in host integration check. Prepares the actual authenticated Debian base
 * and resumes it; deliberately never activates that incomplete runtime. */
public final class RootfsRealArchiveCheck {
    public static void main(String[] args) throws Exception {
        if (args.length != 7) throw new IllegalArgumentException("files archive sha256 compressed payload tarBytes members");
        Path files = Path.of(args[0]), archive = Path.of(args[1]);
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(args[2], Long.parseLong(args[3]), Long.parseLong(args[4]), Long.parseLong(args[5]), Integer.parseInt(args[6]));
        Path root;
        long started = System.nanoTime();
        try (RootfsTransaction transaction = RootfsTransaction.open(files, spec, RootfsTransactionTest.POSIX)) {
            root = transaction.prepare(() -> Files.newInputStream(archive)).root;
            if (transaction.state() != RootfsTransaction.State.PREPARED || Files.exists(files.resolve("debian"), LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Pristine base must remain inactive");
            for (String required : new String[]{"usr/bin/env", "usr/bin/dash", "usr/share/X11/xkb/rules/evdev", "var/lib/dpkg/status"})
                if (!Files.isRegularFile(root.resolve(required), LinkOption.NOFOLLOW_LINKS) || !Files.isReadable(root.resolve(required)))
                    throw new IOException("Missing actual base input: " + required);
        }
        try (RootfsTransaction transaction = RootfsTransaction.open(files, spec, RootfsTransactionTest.POSIX)) {
            Path resumed = transaction.prepare(() -> { throw new IOException("Already prepared base must not redownload"); }).root;
            if (!resumed.equals(root)) throw new IOException("Prepared identity changed after reopening");
        }
        System.out.println("PREPARED_INACTIVE_ROOT=" + root);
        System.out.println("SECONDS=" + (System.nanoTime() - started) / 1_000_000_000.0);
        System.out.println("PASS: actual Debian archive prepared and resumed; no activation, ARM execution, client or keyring initialization");
    }
}
