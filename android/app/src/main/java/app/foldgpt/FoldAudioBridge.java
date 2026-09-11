package app.foldgpt;

import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.util.Log;
import androidx.core.content.ContextCompat;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * Native audio bridge connecting Samsung Galaxy Fold physical microphone
 * and stereo speakers to PulseAudio running inside the Linux guest environment.
 * Runs in unprivileged user-space non-root context.
 */
public final class FoldAudioBridge {
    private static final String TAG = "FoldAudioBridge";
    private static final int SAMPLE_RATE = 44100;
    private static final int MIC_PORT = 4714;
    private static final int SPK_PORT = 4715;

    private final Context context;
    private volatile boolean running;
    private Thread recordThread;
    private Thread playbackThread;

    public FoldAudioBridge(Context context) {
        this.context = context.getApplicationContext();
    }

    public synchronized void start() {
        if (running) return;
        running = true;
        Log.i(TAG, "Starting FoldAudioBridge");

        recordThread = new Thread(this::runRecordLoop, "FoldAudio-Record");
        recordThread.setDaemon(true);
        recordThread.start();

        playbackThread = new Thread(this::runPlaybackLoop, "FoldAudio-Playback");
        playbackThread.setDaemon(true);
        playbackThread.start();
    }

    public synchronized void stop() {
        if (!running) return;
        running = false;
        Log.i(TAG, "Stopping FoldAudioBridge");
        if (recordThread != null) {
            recordThread.interrupt();
            recordThread = null;
        }
        if (playbackThread != null) {
            playbackThread.interrupt();
            playbackThread = null;
        }
    }

    private void runRecordLoop() {
        if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "RECORD_AUDIO permission not yet granted; audio capture loop waiting");
        }

        final int channelConfig = AudioFormat.CHANNEL_IN_MONO;
        final int audioFormat = AudioFormat.ENCODING_PCM_16BIT;
        final int minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, channelConfig, audioFormat);
        final int bufSize = Math.max(minBuf, 4096);

        AudioRecord record = null;
        byte[] buffer = new byte[2048];

        while (running && !Thread.currentThread().isInterrupted()) {
            if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    break;
                }
                continue;
            }

            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1", MIC_PORT), 2000);
                Log.i(TAG, "Connected to PulseAudio microphone bridge on port " + MIC_PORT);
                OutputStream out = socket.getOutputStream();

                if (record == null) {
                    record = new AudioRecord(
                        MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                        SAMPLE_RATE,
                        channelConfig,
                        audioFormat,
                        bufSize
                    );
                    record.startRecording();
                }

                while (running && !Thread.currentThread().isInterrupted()) {
                    int read = record.read(buffer, 0, buffer.length);
                    if (read > 0) {
                        out.write(buffer, 0, read);
                    } else if (read < 0) {
                        Log.w(TAG, "AudioRecord read returned error code " + read);
                        break;
                    }
                }
            } catch (Exception e) {
                // PulseAudio not yet running or connection closed; retry after backoff
                if (running) {
                    try {
                        Thread.sleep(1000);
                    } catch (InterruptedException ie) {
                        break;
                    }
                }
            }
        }

        if (record != null) {
            try {
                record.stop();
                record.release();
            } catch (Exception ignored) {}
        }
        Log.i(TAG, "Exited record loop");
    }

    private void runPlaybackLoop() {
        final int channelConfig = AudioFormat.CHANNEL_OUT_STEREO;
        final int audioFormat = AudioFormat.ENCODING_PCM_16BIT;
        final int minBuf = AudioTrack.getMinBufferSize(SAMPLE_RATE, channelConfig, audioFormat);
        final int bufSize = Math.max(minBuf, 8192);

        AudioTrack track = null;
        byte[] buffer = new byte[4096];

        while (running && !Thread.currentThread().isInterrupted()) {
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1", SPK_PORT), 2000);
                Log.i(TAG, "Connected to PulseAudio speaker bridge on port " + SPK_PORT);
                InputStream in = socket.getInputStream();

                if (track == null) {
                    AudioAttributes attrs = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build();
                    AudioFormat format = new AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setEncoding(audioFormat)
                        .setChannelMask(channelConfig)
                        .build();
                    track = new AudioTrack(attrs, format, bufSize, AudioTrack.MODE_STREAM, AudioManager.AUDIO_SESSION_ID_GENERATE);
                    track.play();
                }

                while (running && !Thread.currentThread().isInterrupted()) {
                    int read = in.read(buffer);
                    if (read > 0) {
                        track.write(buffer, 0, read);
                    } else if (read < 0) {
                        break;
                    }
                }
            } catch (Exception e) {
                if (running) {
                    try {
                        Thread.sleep(1000);
                    } catch (InterruptedException ie) {
                        break;
                    }
                }
            }
        }

        if (track != null) {
            try {
                track.stop();
                track.release();
            } catch (Exception ignored) {}
        }
        Log.i(TAG, "Exited playback loop");
    }
}
