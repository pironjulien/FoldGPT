package app.foldgpt.install;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.ContextWrapper;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/** Fixed debug-only extraction probe. No path/command/spec from Intent extras,
 * no network, guest execution, credentials, runtime restart or activation.
 * Register only in debug with android.permission.DUMP and a private process.
 */
public final class RootfsProbeService extends Service {
    private static final String TAG = "FoldGPT-RootfsProbe";
    private static final String CHANNEL = "foldgpt.rootfs-probe";
    private static final int NOTIFICATION = 1620;
    // This exact artifact is already local, authenticated and independently
    // inspected; source manifest and counts are documented alongside the probe.
    private static final RootfsExtractor.Spec SPEC = new RootfsExtractor.Spec(
            "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
            327673156L, 958101116L, 977131520L, 20240);
    // Two archived hardlink groups each add one intermediate and one backing
    // name. The independent archive verifier checks every added path/target.
    private static final int PHYSICAL_MEMBERS = SPEC.members + 2 * 2;
    private static final long DEADLINE_MS = 10 * 60 * 1000L;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private volatile Thread worker;
    private PowerManager.WakeLock wakeLock;
    private int latestStartId;
    private final Runnable timeout = () -> {
        cancelled.set(true);
        Thread current = worker;
        if (current != null) current.interrupt();
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (worker != null) return START_NOT_STICKY;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,
                "Diagnostic de l’installation", NotificationManager.IMPORTANCE_LOW));
        startForeground(NOTIFICATION, new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .setContentTitle("FoldGPT — test de l’installation")
                .setContentText("Vérification isolée de Debian, sans activation")
                .setOngoing(true).build());
        cancelled.set(false);
        wakeLock = getSystemService(PowerManager.class).newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "FoldGPT:RootfsProbe");
        wakeLock.acquire(DEADLINE_MS);
        worker = new Thread(this::runProbe, "FoldGPT-rootfs-probe");
        main.postDelayed(timeout, DEADLINE_MS);
        worker.start();
        return START_NOT_STICKY;
    }

    private void runProbe() {
        Path report = null;
        JSONObject result = new JSONObject();
        long started = SystemClock.elapsedRealtime();
        String runId = UUID.randomUUID().toString();
        try {
            result.put("schema", "foldgpt.rootfs-probe.v1");
            result.put("runId", runId);
            result.put("status", "RUNNING");
            result.put("uid", android.os.Process.myUid());
            result.put("pid", android.os.Process.myPid());
            result.put("archiveSha256", SPEC.sha256);
            result.put("activationAttempted", false);
            result.put("guestExecuted", false);
            Path realFiles = getFilesDir().toPath().toRealPath();
            Path workspace = realFiles.resolve(".rootfs-proot-install-probe");
            privateDirectory(workspace);
            report = workspace.resolve("report.json");
            Path lockPath = workspace.resolve("probe.lock");
            if (Files.exists(lockPath, LinkOption.NOFOLLOW_LINKS)) ownedRegular(lockPath);
            try (FileChannel lockFile = FileChannel.open(lockPath,
                    java.util.Set.of(StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                            LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                 FileLock lease = lockFile.tryLock()) {
                ownedRegular(lockPath);
                if (lease == null) throw new IOException("Another rootfs probe holds the lease");
                writeReport(report, result);
                verifyNativeLinkTimes(workspace);
                result.put("nativeLinkTimestampChecks", "PASS");
                Path protectedRuntime = realFiles.resolve("debian");
                String runtimeBefore = identityOrAbsent(protectedRuntime);
                result.put("existingRuntimeBefore", runtimeBefore);
                Path sandboxFiles = workspace.resolve("files");
                privateDirectory(sandboxFiles);
                syncDirectory(workspace);
                requireAbsent(sandboxFiles.resolve("debian"));

                Path input = getCacheDir().toPath().toRealPath().resolve("rootfs-probe-input.tar.gz");
                ownedRegular(input);
                ContextWrapper isolated = new ContextWrapper(this) {
                    @Override public File getFilesDir() { return sandboxFiles.toFile(); }
                };
                // Keep one no-follow source fd alive; the production extractor
                // takes and authenticates its own private byte snapshot.
                Path root;
                try (FileChannel source = FileChannel.open(input,
                        StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                    if (source.size() != SPEC.compressedBytes) throw new IOException("Imported archive size differs");
                    String importedHash = hash(Channels.newInputStream(source));
                    if (!SPEC.sha256.equals(importedHash)) throw new IOException("Imported archive SHA-256 differs");
                    source.position(0);
                    try (RootfsTransaction transaction = AndroidRootfsTransaction.open(isolated, SPEC)) {
                        root = transaction.prepare(() -> Channels.newInputStream(source)).root;
                        if (transaction.state() != RootfsTransaction.State.PREPARED)
                            throw new IOException("Expected inactive PREPARED state");
                    }
                }
                checkCancelled();
                result.put("root", realFiles.relativize(root).toString());
                result.put("rootAbsolute", root.toString());
                result.put("phase", "prepared");
                writeReport(report, result);
                // Reopen through the real Android adapter and prove that a
                // completed preparation resumes without accessing its source.
                try (RootfsTransaction transaction = AndroidRootfsTransaction.open(isolated, SPEC)) {
                    Path resumed = transaction.prepare(() -> {
                        throw new IOException("Resume unexpectedly requested a download");
                    }).root;
                    if (!root.equals(resumed) || transaction.state() != RootfsTransaction.State.PREPARED)
                        throw new IOException("Prepared root failed resume validation");
                }
                result.put("resumedWithoutDownload", true);
                requireAbsent(sandboxFiles.resolve("debian"));
                // Real lstat, mode, inode and all regular bytes. The coordinator
                // compares this inventory independently against Python tarfile.
                List<Path> paths = new ArrayList<>();
                collect(root, paths);
                paths.sort(Comparator.comparing(path -> root.relativize(path).toString()));
                JSONArray inventory = new JSONArray();
                long bytes = 0;
                for (Path path : paths) {
                    checkCancelled();
                    StructStat info = Os.lstat(path.toString());
                    if (info.st_uid != android.os.Process.myUid()) throw new IOException("Foreign owner in prepared root");
                    String name = root.relativize(path).toString();
                    JSONObject member = new JSONObject();
                    member.put("path", name.isEmpty() ? "." : name);
                    member.put("mode", info.st_mode & 07777);
                    member.put("mtimeSeconds", Long.toString(info.st_mtim.tv_sec));
                    member.put("mtimeNanoseconds", info.st_mtim.tv_nsec);
                    member.put("device", Long.toUnsignedString(info.st_dev));
                    member.put("inode", Long.toUnsignedString(info.st_ino));
                    if (OsConstants.S_ISDIR(info.st_mode)) {
                        member.put("type", "directory");
                    } else if (OsConstants.S_ISLNK(info.st_mode)) {
                        member.put("type", "symlink");
                        member.put("target", Files.readSymbolicLink(path).toString());
                    } else if (OsConstants.S_ISREG(info.st_mode)) {
                        member.put("type", "regular");
                        member.put("size", info.st_size);
                        member.put("links", info.st_nlink);
                        try (FileChannel file = FileChannel.open(path,
                                StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                            member.put("sha256", hash(Channels.newInputStream(file)));
                        }
                        bytes += info.st_size;
                    } else throw new IOException("Unexpected special file in prepared root");
                    inventory.put(member);
                }
                if (paths.size() != PHYSICAL_MEMBERS) throw new IOException("Prepared physical tree member count differs");
                JSONObject inventoryDocument = new JSONObject();
                inventoryDocument.put("schema", "foldgpt.rootfs-inventory.v1");
                inventoryDocument.put("runId", runId);
                inventoryDocument.put("archiveSha256", SPEC.sha256);
                inventoryDocument.put("members", inventory);
                Path inventoryPath = workspace.resolve("inventory.json");
                writeReport(inventoryPath, inventoryDocument);
                result.put("inventorySha256", hashFile(inventoryPath));
                result.put("members", paths.size());
                result.put("logicalMembers", SPEC.members);
                result.put("storageBackend", ProotHardlinkStorage.BACKEND);
                result.put("allRegularPathBytes", bytes);
                String runtimeAfter = identityOrAbsent(protectedRuntime);
                result.put("existingRuntimeAfter", runtimeAfter);
                if (!runtimeBefore.equals(runtimeAfter)) throw new IOException("Existing runtime identity changed during probe");
                requireAbsent(sandboxFiles.resolve("debian"));
                checkCancelled();
                result.put("status", "PASS_PREPARED_INACTIVE");
                result.put("elapsedMs", SystemClock.elapsedRealtime() - started);
                writeReport(report, result);
                Log.i(TAG, "PASS_PREPARED_INACTIVE run=" + runId + " members=" + paths.size());
            }
        } catch (Exception failure) {
            Log.e(TAG, "Rootfs probe failed run=" + runId, failure);
            try {
                result.put("status", cancelled.get() ? "CANCELLED" : "FAIL");
                result.put("exception", failure.getClass().getName());
                result.put("message", failure.getMessage());
                JSONArray causes = new JSONArray();
                for (Throwable cause = failure.getCause(); cause != null && causes.length() < 8; cause = cause.getCause())
                    causes.put(cause.getClass().getName() + ": " + cause.getMessage());
                result.put("causes", causes);
                result.put("elapsedMs", SystemClock.elapsedRealtime() - started);
                if (report != null) writeReport(report, result);
            } catch (Exception reportFailure) { Log.e(TAG, "Could not persist diagnostic failure", reportFailure); }
        } finally {
            main.post(() -> {
                main.removeCallbacks(timeout);
                if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
                worker = null;
                if (stopSelfResult(latestStartId)) stopForeground(STOP_FOREGROUND_REMOVE);
            });
        }
    }

    private static void verifyNativeLinkTimes(Path workspace) throws Exception {
        Path directory = Files.createTempDirectory(workspace, "link-time-");
        Path target = directory.resolve("target"), link = directory.resolve("link");
        try {
            Files.writeString(target, "unchanged-target");
            Files.setLastModifiedTime(target, java.nio.file.attribute.FileTime.fromMillis(123000));
            Files.createSymbolicLink(link, target.getFileName());
            NativeInstallFiles.setSymlinkModified(link, java.nio.file.attribute.FileTime.from(
                    java.time.Instant.ofEpochSecond(456, 123456789)));
            StructStat targetStat = Os.lstat(target.toString()), linkStat = Os.lstat(link.toString());
            if (targetStat.st_mtim.tv_sec != 123 || targetStat.st_mtim.tv_nsec != 0
                    || linkStat.st_mtim.tv_sec != 456 || linkStat.st_mtim.tv_nsec != 123456789
                    || !Files.readString(target).equals("unchanged-target"))
                throw new IOException("Native link timestamp changed its target or lost precision");
            boolean rejected = false;
            try { NativeInstallFiles.setSymlinkModified(target, java.nio.file.attribute.FileTime.fromMillis(0)); }
            catch (IOException expected) { rejected = true; }
            if (!rejected || Os.lstat(target.toString()).st_mtim.tv_sec != 123)
                throw new IOException("Native link timestamp failed to reject a regular file");
        } finally {
            Files.deleteIfExists(link);
            Files.deleteIfExists(target);
            Files.delete(directory);
        }
    }

    private void checkCancelled() throws IOException {
        if (cancelled.get() || Thread.currentThread().isInterrupted())
            throw new java.io.InterruptedIOException("Rootfs diagnostic cancelled or deadline exceeded");
    }

    private void collect(Path path, List<Path> result) throws Exception {
        checkCancelled();
        StructStat info = Os.lstat(path.toString());
        result.add(path);
        if (result.size() > PHYSICAL_MEMBERS) throw new IOException("Prepared tree has excess members");
        if (OsConstants.S_ISDIR(info.st_mode)) {
            try (var children = Files.newDirectoryStream(path)) {
                for (Path child : children) collect(child, result);
            }
        }
    }

    private String hashFile(Path path) throws Exception {
        try (FileChannel file = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            return hash(Channels.newInputStream(file));
        }
    }

    private String hash(InputStream input) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] block = new byte[65536];
        for (int count; (count = input.read(block)) != -1;) {
            checkCancelled();
            digest.update(block, 0, count);
        }
        StringBuilder result = new StringBuilder();
        for (byte value : digest.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    private static void privateDirectory(Path directory) throws Exception {
        try { Files.createDirectory(directory,
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
        catch (java.nio.file.FileAlreadyExistsException present) { /* validate actual type and ownership */ }
        StructStat info = Os.lstat(directory.toString());
        if (!OsConstants.S_ISDIR(info.st_mode) || info.st_uid != android.os.Process.myUid()
                || (info.st_mode & 07777) != 0700) throw new IOException("Unsafe private diagnostic directory");
    }

    private static void ownedRegular(Path path) throws Exception {
        StructStat info = Os.lstat(path.toString());
        if (!OsConstants.S_ISREG(info.st_mode) || info.st_uid != android.os.Process.myUid()
                || info.st_nlink != 1 || (info.st_mode & 0022) != 0)
            throw new IOException("Input or diagnostic metadata is not an owned private regular file");
    }

    private static String identityOrAbsent(Path path) throws Exception {
        try {
            StructStat info = Os.lstat(path.toString());
            return Long.toUnsignedString(info.st_dev) + ":" + Long.toUnsignedString(info.st_ino)
                    + ":" + (info.st_mode & 0177777)
                    + (OsConstants.S_ISLNK(info.st_mode) ? ":" + Files.readSymbolicLink(path) : "");
        } catch (android.system.ErrnoException error) {
            if (error.errno == OsConstants.ENOENT) return "absent";
            throw error;
        }
    }

    private static void requireAbsent(Path path) throws Exception {
        if (!identityOrAbsent(path).equals("absent")) throw new IOException("Probe must never activate a rootfs");
    }

    private static void writeReport(Path destination, JSONObject report) throws Exception {
        if (Files.exists(destination, LinkOption.NOFOLLOW_LINKS)) ownedRegular(destination);
        Path pending = destination.resolveSibling(destination.getFileName() + ".next");
        if (Files.exists(pending, LinkOption.NOFOLLOW_LINKS)) { ownedRegular(pending); Files.delete(pending); }
        try (FileChannel output = FileChannel.open(pending,
                java.util.Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes = ByteBuffer.wrap((report.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
            while (bytes.hasRemaining()) output.write(bytes);
            output.force(true);
        }
        Files.move(pending, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        syncDirectory(destination.getParent());
    }

    private static void syncDirectory(Path directory) throws Exception {
        java.io.FileDescriptor fd = Os.open(directory.toString(),
                OsConstants.O_RDONLY | OsConstants.O_NOFOLLOW | OsConstants.O_CLOEXEC, 0);
        try { Os.fsync(fd); } finally { Os.close(fd); }
    }

    @Override public void onDestroy() {
        cancelled.set(true);
        Thread current = worker;
        if (current != null) current.interrupt();
        main.removeCallbacks(timeout);
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }
}
