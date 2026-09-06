package app.foldgpt.install;

import java.io.IOException;
import java.nio.file.*;

/** Opt-in real Debian archive check on an isolated Linux filesystem; never activates or executes ARM code. */
public final class GuestAccountRealArchiveCheck {
    public static void main(String[] args) throws Exception {
        if(args.length!=9) throw new IllegalArgumentException("files archive sha256 compressed payload tarBytes members uid gid");
        Path files=Path.of(args[0]),archive=Path.of(args[1]);
        RootfsExtractor.Spec spec=new RootfsExtractor.Spec(args[2],Long.parseLong(args[3]),Long.parseLong(args[4]),Long.parseLong(args[5]),Integer.parseInt(args[6]));
        int uid=Integer.parseInt(args[7]),gid=Integer.parseInt(args[8]);
        GuestAccountProvisioner.Storage storage=new GuestAccountProvisioner.Storage() {
            public String identity(Path path) throws IOException { return RootfsTransactionTest.POSIX.identity(path); }
            public long linkCount(Path path) throws IOException { return RootfsTransactionTest.POSIX.linkCount(path); }
            public void syncDirectory(Path path) throws IOException { RootfsTransactionTest.POSIX.syncDirectory(path); }
        };
        Path root; String homeIdentity;
        try(RootfsTransaction transaction=RootfsTransaction.open(files,spec,RootfsTransactionTest.POSIX)) {
            root=transaction.prepare(() -> Files.newInputStream(archive)).root;
            GuestIdentity account=GuestAccountProvisioner.prepare(transaction,storage,uid,gid);
            if(!account.prootIds().equals(uid+":"+gid)) throw new IOException("Guest IDs differ");
            homeIdentity=storage.identity(root.resolve("home/foldgpt"));
            if(transaction.state()!=RootfsTransaction.State.PREPARED || Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Guest provisioning activated an incomplete runtime");
        }
        try(RootfsTransaction transaction=RootfsTransaction.open(files,spec,RootfsTransactionTest.POSIX)) {
            if(!transaction.prepare(() -> { throw new IOException("Resuming must not extract again"); }).root.equals(root))
                throw new IOException("Resumed root changed");
            GuestIdentity account=GuestAccountProvisioner.prepare(transaction,storage,uid,gid);
            if(account.uid!=uid || account.gid!=gid || !storage.identity(root.resolve("home/foldgpt")).equals(homeIdentity))
                throw new IOException("Resuming replaced the guest identity or home");
        }
        System.out.println("PREPARED_INACTIVE_ROOT="+root);
        System.out.println("GUEST_IDS="+uid+":"+gid);
        System.out.println("PASS: actual Debian account databases, locked credential, home and journal prepared/resumed; no activation, ARM execution or client/keyring provisioning");
    }
}
