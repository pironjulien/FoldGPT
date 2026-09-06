package app.foldgpt.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.*;

/** Owns one bounded child and the credential array transferred to its stdin.
 * No credential String, argv/environment argument, log or plaintext file exists.
 * The writer is separate so a child that never reads cannot stall cancellation.
 */
public final class SecretPipeProcess {
    private SecretPipeProcess() {}
    public enum FailureStage { NATIVE_LOADER, PROOT, PYTHON, SUPERVISOR, INITIALIZER, INITIALIZER_CLEANUP, UNKNOWN }
    public enum FailureCode {
        NATIVE_LINKER_FAILURE, PROOT_REPORTED_ERROR, PYTHON_CANNOT_OPEN_SOURCE, PYTHON_IMPORT_FAILURE,
        PYTHON_SOURCE_FAILURE, SUPERVISOR_REPORTED_FAILURE, INITIALIZER_REFUSED, INITIALIZER_CLEANUP_FAILURE,
        NO_RECOGNIZED_DIAGNOSTIC
    }
    /** Safe structural fields only. No failed output, exception/RPC payload,
     * filename, argument, environment value or credential is retained here. */
    public static final class ProcessFailure extends IOException {
        public final int exitCode,capturedOutputBytes;
        public final FailureStage stage;
        public final FailureCode code;
        private ProcessFailure(int exitCode,int bytes,FailureStage stage,FailureCode code) {
            super("Private provisioning process failed: exit="+exitCode+" stage="+stage.name()+" code="+code.name()+" bytes="+bytes);
            this.exitCode=exitCode; this.capturedOutputBytes=bytes; this.stage=stage; this.code=code;
        }
    }
    public static String run(ProcessBuilder builder,byte[] credential,long timeoutMillis) throws IOException,InterruptedException {
        if(credential==null) throw new NullPointerException("credential");
        Process child=null;
        ExecutorService workers=null;
        Future<Void> writer=null;
        Future<byte[]> reader=null;
        Throwable failure=null;
        try {
            if(credential.length==0 || credential.length>8192 || timeoutMillis<=0)
                throw new IOException("Invalid private provisioning input or deadline");
            for(byte value:credential) if(value==0) throw new IOException("Invalid private credential encoding");
            if(builder.redirectInput()!=ProcessBuilder.Redirect.PIPE || builder.redirectOutput()!=ProcessBuilder.Redirect.PIPE
                    || builder.redirectError()!=ProcessBuilder.Redirect.PIPE)
                throw new IOException("Private provisioning requires anonymous process pipes");
            builder.redirectErrorStream(true);
            child=builder.start();
            final Process running=child;
            workers=Executors.newFixedThreadPool(2,runnable -> {
                Thread thread=new Thread(runnable,"FoldGPT-private-install-pipe"); thread.setDaemon(true); return thread;
            });
            writer=workers.submit(() -> {
                try(OutputStream input=running.getOutputStream()) { input.write(credential); }
                finally { Arrays.fill(credential,(byte)0); }
                return null;
            });
            reader=workers.submit(() -> {
                try(InputStream output=running.getInputStream(); WipedOutput bytes=new WipedOutput()) {
                    byte[] buffer=new byte[4096]; int count;
                    while((count=output.read(buffer))!=-1) {
                        if(bytes.size()+count>65536) {
                            running.destroyForcibly();
                            throw new IOException("Private provisioning output exceeds limit");
                        }
                        bytes.write(buffer,0,count);
                    }
                    return bytes.toByteArray();
                }
            });
            if(!child.waitFor(timeoutMillis,TimeUnit.MILLISECONDS)) throw new IOException("Private provisioning deadline expired");
            byte[] result=await(reader);
            // An early child exit can also break the input pipe. Preserve the
            // actual child status/structural diagnostic instead of losing it
            // behind the secondary writer error. Cleanup still joins the writer
            // and erases its exact credential buffer on every path.
            if(child.exitValue()!=0) throw processFailure(child.exitValue(),result);
            await(writer);
            return new String(result,StandardCharsets.UTF_8);
        } catch(IOException|InterruptedException|RuntimeException|Error error) {
            failure=error;
            throw error;
        } finally {
            // Destroy before waiting on the writer: it may be blocked on a full
            // pipe. Cancellation cannot release a still-live credential buffer.
            boolean interrupted=Thread.interrupted();
            IOException cleanup=null;
            try {
                if(child!=null) {
                    if(child.isAlive()) {
                        child.destroy();
                        if(!child.waitFor(5000,TimeUnit.MILLISECONDS)) {
                            child.destroyForcibly();
                            if(!child.waitFor(5000,TimeUnit.MILLISECONDS)) cleanup=new IOException("Private provisioning child did not stop");
                        }
                    }
                }
            } catch(InterruptedException stopped) {
                interrupted=true;
                if(child!=null) child.destroyForcibly();
                cleanup=new IOException("Private provisioning cleanup interrupted",stopped);
            } finally {
                // Every cleanup runs even if an earlier stream close fails.
                if(child!=null) for(Closeable stream:new Closeable[]{child.getOutputStream(),child.getInputStream(),child.getErrorStream()}) {
                    try { stream.close(); }
                    catch(IOException error) { if(cleanup==null) cleanup=error; else cleanup.addSuppressed(error); }
                }
                try {
                    if(workers!=null) {
                        workers.shutdown();
                        if(!workers.awaitTermination(5000,TimeUnit.MILLISECONDS)) {
                            workers.shutdownNow();
                            if(!workers.awaitTermination(5000,TimeUnit.MILLISECONDS)) {
                                IOException error=new IOException("Private provisioning pipe did not stop");
                                if(cleanup==null) cleanup=error; else cleanup.addSuppressed(error);
                            }
                        }
                    }
                    if(reader!=null && reader.isDone() && !reader.isCancelled()) {
                        try { Arrays.fill(reader.get(),(byte)0); }
                        catch(ExecutionException ignored) { /* no successful output array was returned */ }
                    }
                } catch(InterruptedException stopped) {
                    interrupted=true;
                    if(workers!=null) workers.shutdownNow();
                    IOException error=new IOException("Private provisioning pipe cleanup interrupted",stopped);
                    if(cleanup==null) cleanup=error; else cleanup.addSuppressed(error);
                } finally {
                    Arrays.fill(credential,(byte)0);
                    if(interrupted) Thread.currentThread().interrupt();
                }
            }
            if(cleanup!=null) { if(failure!=null) failure.addSuppressed(cleanup); else throw cleanup; }
        }
    }
    private static final class WipedOutput extends ByteArrayOutputStream {
        WipedOutput() { super(65536); }
        @Override public void close() { Arrays.fill(buf,(byte)0); reset(); }
    }
    private static ProcessFailure processFailure(int exitCode,byte[] output) {
        // Compatibility with the existing, hash-bound helper: recognize only
        // its exact static lines and fixed runtime error prefixes. Never decode
        // arbitrary failed bytes to String, copy their suffix or treat this hint
        // as a security/installation success. Unknown output stays unknown.
        if(line(output,"FoldGPT keyring connection cleanup failed",true))
            return new ProcessFailure(exitCode,output.length,FailureStage.INITIALIZER_CLEANUP,FailureCode.INITIALIZER_CLEANUP_FAILURE);
        if(line(output,"FoldGPT keyring initialization failed; existing credentials were not replaced",true))
            return new ProcessFailure(exitCode,output.length,FailureStage.INITIALIZER,FailureCode.INITIALIZER_REFUSED);
        if(line(output,"FoldGPT inactive keyring preparation failed",true))
            return new ProcessFailure(exitCode,output.length,FailureStage.SUPERVISOR,FailureCode.SUPERVISOR_REPORTED_FAILURE);
        if(line(output,"CANNOT LINK EXECUTABLE ",false))
            return new ProcessFailure(exitCode,output.length,FailureStage.NATIVE_LOADER,FailureCode.NATIVE_LINKER_FAILURE);
        if(line(output,"proot error:",false))
            return new ProcessFailure(exitCode,output.length,FailureStage.PROOT,FailureCode.PROOT_REPORTED_ERROR);
        if(line(output,"/usr/bin/python3: can't open file ",false) || line(output,"python3: can't open file ",false))
            return new ProcessFailure(exitCode,output.length,FailureStage.PYTHON,FailureCode.PYTHON_CANNOT_OPEN_SOURCE);
        if(line(output,"ModuleNotFoundError:",false) || line(output,"ImportError:",false))
            return new ProcessFailure(exitCode,output.length,FailureStage.PYTHON,FailureCode.PYTHON_IMPORT_FAILURE);
        if(line(output,"SyntaxError:",false))
            return new ProcessFailure(exitCode,output.length,FailureStage.PYTHON,FailureCode.PYTHON_SOURCE_FAILURE);
        return new ProcessFailure(exitCode,output.length,FailureStage.UNKNOWN,FailureCode.NO_RECOGNIZED_DIAGNOSTIC);
    }
    private static boolean line(byte[] bytes,String literal,boolean complete) {
        byte[] marker=literal.getBytes(StandardCharsets.US_ASCII);
        for(int start=0;start+marker.length<=bytes.length;start++) {
            if(start!=0 && bytes[start-1]!='\n') continue;
            int index=0; while(index<marker.length && bytes[start+index]==marker[index]) index++;
            if(index!=marker.length) continue;
            int end=start+marker.length;
            if(!complete || end==bytes.length || bytes[end]=='\n'
                    || bytes[end]=='\r' && end+1<bytes.length && bytes[end+1]=='\n') return true;
        }
        return false;
    }
    private static <T> T await(Future<T> value) throws IOException,InterruptedException {
        try { return value.get(5000,TimeUnit.MILLISECONDS); }
        catch(ExecutionException failure) {
            if(failure.getCause() instanceof IOException) throw (IOException)failure.getCause();
            throw new IOException("Private provisioning pipe failed",failure.getCause());
        } catch(TimeoutException failure) { throw new IOException("Private provisioning pipe cleanup expired",failure); }
    }
}
