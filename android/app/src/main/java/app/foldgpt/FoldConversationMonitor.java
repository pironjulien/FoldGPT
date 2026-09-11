package app.foldgpt;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.FileObserver;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONObject;

/** Watches the official local history without another Linux process or database write. */
public final class FoldConversationMonitor implements AutoCloseable {
    public interface Listener { void changed(String thread, String title, ConversationActivity.Change change, int active); }
    private static final Pattern ROLLOUT = Pattern.compile("rollout-.*-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\\.jsonl");
    private static final int MAX_LINE = 8 * 1024 * 1024;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> new Thread(r, "FoldGPT-conversations"));
    private final Map<File, FileObserver> watches = new HashMap<>();
    private final Map<File, Tail> tails = new HashMap<>();
    private final ConversationActivity activity = new ConversationActivity();
    private final File home;
    private final Listener listener;
    private volatile boolean closed;
    private final long since = System.currentTimeMillis();
    private static final class Tail {
        long offset;
        boolean oversized;
        final ByteArrayOutputStream pending = new ByteArrayOutputStream();
    }
    public FoldConversationMonitor(File home, Listener listener) {
        this.home = home; this.listener = listener;
    }
    public java.util.concurrent.CompletableFuture<Void> start() {
        return java.util.concurrent.CompletableFuture.runAsync(() -> {
            // The first client launch can create sessions after this monitor starts.
            // Observe its parent too, while keeping unrelated profile data out of the scan.
            if (!home.isDirectory() && !home.mkdirs())
                throw new IllegalStateException("Conversation profile is unavailable");
            FileObserver parent = new FileObserver(home, FileObserver.CREATE | FileObserver.MOVED_TO) {
                @Override public void onEvent(int event, String path) {
                    if (closed || !"sessions".equals(path)) return;
                    try { worker.execute(() -> scan(new File(home, "sessions"), 0, false)); }
                    catch (java.util.concurrent.RejectedExecutionException ignored) { }
                }
            };
            watches.put(home, parent); parent.startWatching();
            scan(new File(home, "sessions"), 0, true);
        }, worker);
    }
    private void scan(File directory, int depth, boolean baseline) {
        if (closed || depth > 3 || Files.isSymbolicLink(directory.toPath()) || !directory.isDirectory()) return;
        if (!watches.containsKey(directory)) {
            FileObserver observer = new FileObserver(directory, FileObserver.CREATE | FileObserver.MOVED_TO | FileObserver.MODIFY | FileObserver.CLOSE_WRITE) {
                @Override public void onEvent(int event, String path) {
                    if (closed || path == null || path.contains("/") || path.equals("..")) return;
                    try { worker.execute(() -> {
                        File child = new File(directory, path);
                        if (child.isDirectory()) scan(child, depth + 1, false);
                        else read(child, false);
                    }); } catch (java.util.concurrent.RejectedExecutionException ignored) { }
                }
            };
            watches.put(directory, observer);
            observer.startWatching();
        }
        File[] children = directory.listFiles();
        if (children == null) return;
        for (File child : children) {
            if (child.isDirectory()) scan(child, depth + 1, baseline);
            else read(child, baseline);
        }
    }
    private void read(File file, boolean baseline) {
        Matcher match = ROLLOUT.matcher(file.getName());
        if (closed || !match.matches() || Files.isSymbolicLink(file.toPath()) || !file.isFile()) return;
        String thread = match.group(1);
        Tail tail = tails.computeIfAbsent(file, key -> new Tail());
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            if (baseline) { tail.offset = input.length(); return; }
            if (input.length() < tail.offset) { tail.offset = 0; tail.pending.reset(); tail.oversized = false; }
            input.seek(tail.offset);
            byte[] buffer = new byte[16384];
            int count;
            while (!closed && (count = input.read(buffer)) > 0) {
                tail.offset += count;
                for (int i = 0; i < count; i++) {
                    if (buffer[i] == '\n') {
                        if (!tail.oversized) event(thread, tail.pending.toString(StandardCharsets.UTF_8.name()));
                        tail.pending.reset(); tail.oversized = false;
                    } else if (!tail.oversized) {
                        if (tail.pending.size() == MAX_LINE) { tail.pending.reset(); tail.oversized = true; }
                        else tail.pending.write(buffer[i]);
                    }
                }
            }
        } catch (Exception error) { Log.w("FoldGPT-conversations", "History observation failed", error); }
    }
    private void event(String thread, String line) {
        if (!line.contains("\"event_msg\"")) return;
        try {
            JSONObject record = new JSONObject(line);
            if (java.time.Instant.parse(record.getString("timestamp")).toEpochMilli() < since) return;
            ConversationActivity.Change change = activity.accept(thread, record);
            if (change != ConversationActivity.Change.NONE && !closed)
                listener.changed(thread, title(thread), change, activity.activeCount());
        } catch (org.json.JSONException | java.time.format.DateTimeParseException error) { Log.w("FoldGPT-conversations", "Invalid history event"); }
    }
    private String title(String thread) {
        // The client persists renamed/generated titles in its session index;
        // the runtime database can retain the original first-message title.
        String indexedTitle = "";
        try (java.io.BufferedReader reader = Files.newBufferedReader(new File(home, "session_index.jsonl").toPath(), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.contains(thread)) continue;
                try {
                    JSONObject entry = new JSONObject(line);
                    if (thread.equals(entry.optString("id"))) {
                        String candidate = cleanTitle(entry.optString("thread_name"));
                        if (!candidate.isEmpty()) indexedTitle = candidate;
                    }
                } catch (org.json.JSONException ignored) { }
            }
        } catch (java.io.IOException ignored) { }
        if (!indexedTitle.isEmpty()) return indexedTitle;
        File database = new File(home, "state_5.sqlite");
        if (database.isFile()) try (SQLiteDatabase db = SQLiteDatabase.openDatabase(database.getPath(), null, SQLiteDatabase.OPEN_READONLY);
                                   Cursor cursor = db.rawQuery("SELECT title FROM threads WHERE id=? LIMIT 1", new String[] {thread})) {
            if (cursor.moveToFirst()) {
                String title = cleanTitle(cursor.getString(0));
                if (!title.isEmpty()) return title;
            }
        } catch (RuntimeException error) { Log.w("FoldGPT-conversations", "Conversation title unavailable"); }
        return "Conversation ChatGPT";
    }
    private static String cleanTitle(String value) {
        if (value == null) return "";
        String title = value.replaceAll("[\\r\\n\\t]+", " ").trim();
        return title.length() > 160 ? title.substring(0, 157) + "…" : title;
    }
    @Override public synchronized void close() {
        if (closed) return;
        closed = true;
        worker.execute(() -> { for (FileObserver observer : watches.values()) observer.stopWatching(); watches.clear(); tails.clear(); });
        worker.shutdown();
    }
}
