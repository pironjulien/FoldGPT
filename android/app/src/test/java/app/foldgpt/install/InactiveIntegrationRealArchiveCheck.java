package app.foldgpt.install;

import java.io.*;
import java.nio.file.*;

/** Opt-in real archives on a NEW unprivileged Linux stage. Never runs ARM code,
 * installs a client, opens a vault, activates a root or talks to Android. */
public final class InactiveIntegrationRealArchiveCheck {
    public static void main(String[] args) throws Exception {
        if(args.length!=7) throw new IllegalArgumentException("files baseArchive integrationContainer integrationSha integrationBytes uid gid");
        Path files=Path.of(args[0]),base=Path.of(args[1]),archive=Path.of(args[2]);
        RootfsExtractor.Spec spec=new RootfsExtractor.Spec("dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
            327673156,958101116,977131520,20240);
        int uid=Integer.parseInt(args[5]),gid=Integer.parseInt(args[6]);
        long started=System.nanoTime();
        String format;
        try(InputStream input=Files.newInputStream(archive)) {
            format=InactiveIntegrationBundle.read(input,args[3],Long.parseLong(args[4])).format;
        }
        String id="28d0a1490b1e2913c219687f601a312386344597140276d379aab553f775b2fa";
        InactiveIntegrationInstaller.Result first;
        try(RootfsTransaction transaction=RootfsTransaction.open(files,spec,RootfsTransactionTest.POSIX)) {
            transaction.prepare(() -> Files.newInputStream(base));
            GuestAccountProvisioner.prepare(transaction,InactiveIntegrationInstallerTest.ACCOUNT_STORAGE,uid,gid);
            try(InputStream input=Files.newInputStream(archive)) {
                first=InactiveIntegrationInstaller.install(transaction,InactiveIntegrationInstallerTest.STORAGE,id,
                    InactiveIntegrationBundle.read(input,args[3],Long.parseLong(args[4])));
            }
        }
        try(RootfsTransaction transaction=RootfsTransaction.open(files,spec,RootfsTransactionTest.POSIX)) {
            transaction.prepare(() -> { throw new IOException("Reopening must not extract the base again"); });
            InactiveIntegrationInstaller.Result second;
            try(InputStream input=Files.newInputStream(archive)) {
                second=InactiveIntegrationInstaller.install(transaction,InactiveIntegrationInstallerTest.STORAGE,id,
                    InactiveIntegrationBundle.read(input,args[3],Long.parseLong(args[4])));
            }
            if(!first.root.equals(second.root) || !first.reportSha256.equals(second.reportSha256)
                    || !first.rootIdentity.equals(second.rootIdentity) || transaction.state()!=RootfsTransaction.State.PREPARED
                    || Files.exists(files.resolve("debian"),LinkOption.NOFOLLOW_LINKS)) throw new IOException("Inactive retry changed identity or activated");
        }
        System.out.println("PREPARED_INACTIVE_ROOT="+first.root);
        System.out.println("ROOT_IDENTITY="+first.rootIdentity);
        System.out.println("REPORT="+first.report);
        System.out.println("REPORT_SHA256="+first.reportSha256);
        System.out.println("BUNDLE_FORMAT="+format);
        System.out.println("SECONDS="+(System.nanoTime()-started)/1_000_000_000.0);
        System.out.println("PASS: real authenticated Debian, scripts and Mesa files installed and reopened; native XKB exact tree verified; no ARM/GPU execution, client/vault initialization or activation");
    }
}
