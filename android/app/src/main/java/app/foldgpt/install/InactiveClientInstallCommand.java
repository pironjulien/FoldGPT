package app.foldgpt.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;

/** Exact PRoot command for the trusted inactive package step. The guest UID 0
 * is PRoot presentation only; no Android root, display, keyring, namespace shim
 * or client command is requested. Files/native inputs are validated by caller. */
public final class InactiveClientInstallCommand {
    private InactiveClientInstallCommand() {}
    interface Stopper { void stop(Process child) throws IOException; }
    public static ProcessBuilder create(Path nativeDirectory,Path root,Path work,String installationId,
            String rootIdentity,long timeoutMillis) throws IOException {
        for(Path path:List.of(nativeDirectory,root,work)) {
            if(!path.isAbsolute() || !path.normalize().equals(path) || path.toString().contains(":")
                    || path.toString().contains("\n") || path.toString().contains("\r"))
                throw new IOException("PRoot installation paths must be absolute unambiguous paths");
        }
        if(installationId==null || !installationId.matches("[0-9a-f]{64}") || rootIdentity==null
                || !rootIdentity.matches("[0-9]+:[0-9]+") || timeoutMillis<=0 || timeoutMillis>Integer.MAX_VALUE)
            throw new IOException("Invalid inactive client identity or deadline");
        long seconds=(timeoutMillis+999)/1000;
        List<String> command=new ArrayList<>(List.of(nativeDirectory.resolve("libproot.so").toString(),
            "--kill-on-exit","--link2symlink","--sysvipc","-r",root.toString(),"-0","-w","/",
            "-b","/dev","-b","/proc","-b","/sys","-b","/system","-b","/apex",
            "-b",work.resolve("tmp")+":/tmp","-b",work.resolve("shm")+":/dev/shm",
            "-b",work.resolve("input")+":/tmp/foldgpt-client-input",
            "/usr/bin/env","-i","PATH=/usr/sbin:/usr/bin:/sbin:/bin","HOME=/root","USER=root","LOGNAME=root",
            "LANG=C.UTF-8","LC_ALL=C.UTF-8","DEBIAN_FRONTEND=noninteractive","PYTHONDONTWRITEBYTECODE=1",
            "/usr/bin/python3","-B","/tmp/foldgpt-client-input/install_official_client.py",
            "--installation-id",installationId,"--root-identity",rootIdentity,"--timeout",Long.toString(seconds)));
        ProcessBuilder builder=new ProcessBuilder(command);
        builder.environment().clear();
        builder.environment().put("PATH","/system/bin");
        builder.environment().put("LD_LIBRARY_PATH",work.resolve("native")+":"+nativeDirectory);
        builder.environment().put("PROOT_LOADER",nativeDirectory.resolve("libproot-loader.so").toString());
        builder.environment().put("PROOT_LOADER_32",nativeDirectory.resolve("libproot-loader32.so").toString());
        builder.environment().put("PROOT_TMP_DIR",work.resolve("tmp").toString());
        builder.environment().put("TMPDIR",work.resolve("tmp").toString());
        return builder;
    }
    static String run(ProcessBuilder builder,long timeoutMillis,Path diagnosticLog,Stopper stopper) throws IOException,InterruptedException {
        Objects.requireNonNull(stopper);
        if(timeoutMillis<=0 || builder.redirectInput()!=ProcessBuilder.Redirect.PIPE
                || builder.redirectOutput()!=ProcessBuilder.Redirect.PIPE || builder.redirectError()!=ProcessBuilder.Redirect.PIPE)
            throw new IOException("Inactive package runner requires bounded anonymous pipes");
        builder.redirectErrorStream(true);
        Process child=builder.start();
        ExecutorService reader=Executors.newSingleThreadExecutor(task -> {
            Thread thread=new Thread(task,"FoldGPT-client-install-output"); thread.setDaemon(true); return thread;
        });
        try {
            child.getOutputStream().close();
            Future<byte[]> output=reader.submit(() -> {
                try(InputStream stream=child.getInputStream()) {
                    byte[] bytes=stream.readNBytes(65537);
                    if(bytes.length>65536) { stopper.stop(child); throw new IOException("Inactive package output exceeded limit"); }
                    return bytes;
                }
            });
            if(!child.waitFor(timeoutMillis,TimeUnit.MILLISECONDS)) throw new IOException("Inactive package installation deadline expired");
            byte[] bytes;
            try { bytes=output.get(5,TimeUnit.SECONDS); }
            catch(ExecutionException|TimeoutException error) { throw new IOException("Inactive package output could not be collected",error); }
            if(diagnosticLog!=null) {
                try(java.nio.channels.FileChannel log=java.nio.channels.FileChannel.open(diagnosticLog,
                        Set.of(java.nio.file.StandardOpenOption.CREATE_NEW,java.nio.file.StandardOpenOption.WRITE,java.nio.file.LinkOption.NOFOLLOW_LINKS),
                        java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")))) {
                    java.nio.ByteBuffer data=java.nio.ByteBuffer.wrap(bytes); while(data.hasRemaining()) log.write(data); log.force(true);
                }
            }
            if(child.exitValue()!=0) throw new IOException("Inactive package step failed: exit="+child.exitValue()+" outputBytes="+bytes.length);
            return new String(bytes,StandardCharsets.UTF_8);
        } finally {
            boolean interrupted=Thread.interrupted();
            try {
                for(int phase=0;phase<2 && child.isAlive();phase++) {
                    // The packaged PRoot must route SIGTERM with --kill-on-exit
                    // through its tracee cleanup and reap loop. Android's public
                    // Process.destroy sends it without exposing a reusable PID.
                    // SIGKILL cannot run cleanup and is never substituted.
                    stopper.stop(child);
                    long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
                    while(child.isAlive() && System.nanoTime()<until) {
                        try { child.waitFor(Math.max(1,until-System.nanoTime()),TimeUnit.NANOSECONDS); }
                        catch(InterruptedException interruption) { interrupted=true; }
                    }
                }
                if(child.isAlive()) throw new IOException("Inactive package PRoot did not stop");
            } finally {
                reader.shutdownNow();
                if(interrupted) Thread.currentThread().interrupt();
            }
        }
    }
}
