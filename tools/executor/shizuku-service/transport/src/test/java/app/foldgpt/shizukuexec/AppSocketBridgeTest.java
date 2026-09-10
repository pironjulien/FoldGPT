package app.foldgpt.shizukuexec;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.concurrent.*;

/** Real bounded pipe copy checks; Binder/SELinux remain Android qualification. */
public final class AppSocketBridgeTest {
    @Test public void preservesBinaryDataAndEofUnderPipeBackpressure() throws Exception {
        byte[] data = new byte[1024 * 1024];
        for (int index = 0; index < data.length; ++index) data[index] = (byte)index;
        PipedInputStream source = new PipedInputStream(4096);
        PipedOutputStream sourceWriter = new PipedOutputStream(source);
        PipedInputStream destination = new PipedInputStream(4096);
        PipedOutputStream destinationWriter = new PipedOutputStream(destination);
        java.util.concurrent.ExecutorService workers = Executors.newFixedThreadPool(3);
        try {
            Future<?> writer = workers.submit(() -> {
                try (OutputStream stream = sourceWriter) { stream.write(data); }
                catch (IOException error) { throw new UncheckedIOException(error); }
            });
            Future<?> relay = workers.submit(() -> {
                try (OutputStream stream = destinationWriter) { AppSocketBridge.copy(source, stream); }
                catch (IOException error) { throw new UncheckedIOException(error); }
            });
            Future<byte[]> reader = workers.submit(() -> destination.readAllBytes());
            assertArrayEquals(data, reader.get(5, TimeUnit.SECONDS));
            writer.get(5, TimeUnit.SECONDS); relay.get(5, TimeUnit.SECONDS);
        } finally {
            source.close(); sourceWriter.close(); destination.close(); destinationWriter.close();
            workers.shutdownNow();
        }
    }
    @Test public void neverTurnsDestinationFailureIntoCompletedCopy() {
        OutputStream refused = new OutputStream() {
            @Override public void write(int value) throws IOException { throw new IOException("closed peer"); }
        };
        assertThrows(IOException.class, () -> AppSocketBridge.copy(new ByteArrayInputStream(new byte[]{0, 1, -1}), refused));
    }
}
