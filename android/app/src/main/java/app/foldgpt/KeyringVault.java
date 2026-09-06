package app.foldgpt;

import android.content.Context;
import android.os.UserManager;
import android.app.KeyguardManager;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.AtomicFile;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.Arrays;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

/** Device-bound encryption for the Linux keyring password; never logs plaintext. */
public final class KeyringVault {
    private static final String ALIAS = "app.foldgpt.keyring.v1";
    private static final byte[] AAD = ALIAS.getBytes(StandardCharsets.US_ASCII);
    private static final byte[] MAGIC = {'F', 'G', 'K', '1'};
    private static final int MAX_PASSWORD = 8192;
    private KeyringVault() {}

    /** Caller owns the returned array and must overwrite it immediately after pipe transfer. */
    public static synchronized byte[] loadPassword(Context context) throws Exception {
        if (!context.getSystemService(UserManager.class).isUserUnlocked()
                || context.getSystemService(KeyguardManager.class).isDeviceLocked()) {
            throw new GeneralSecurityException("Unlock Android before opening the Linux keyring");
        }
        File directory = new File(context.getNoBackupFilesDir(), "foldgpt-keyring");
        if (!existsWithoutFollowingLinks(directory)) Os.mkdir(directory.getAbsolutePath(), 0700);
        requirePrivate(directory, true);
        File pending = new File(directory, "keyring-password.import");
        File encrypted = new File(directory, "keyring-password.v1");
        boolean hasPending = existsWithoutFollowingLinks(pending);
        boolean hasEncrypted = existsWithoutFollowingLinks(encrypted);
        if (!hasPending && !hasEncrypted) throw new IOException("Linux keyring credential is not provisioned");
        if (hasPending) requirePrivate(pending, false);
        if (hasEncrypted) requirePrivate(encrypted, false);
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            if (hasEncrypted) throw new GeneralSecurityException("Keyring vault key is missing; recovery required");
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setUnlockedDeviceRequired(true).build());
            generator.generateKey();
        }
        SecretKey key = (SecretKey) store.getKey(ALIAS, null);
        byte[] imported = null;
        byte[] password = null;
        try {
            if (hasPending) imported = readPrivate(pending, MAX_PASSWORD);
            if (hasEncrypted) {
                password = decrypt(key, readPrivate(encrypted, MAX_PASSWORD + 64));
                // A matching import can remain after a crash between commit and deletion.
                if (imported != null && !MessageDigest.isEqual(imported, password)) {
                    throw new GeneralSecurityException("Refusing to replace the existing Linux keyring credential");
                }
            } else {
                validatePassword(imported);
                byte[] payload = encrypt(key, imported);
                AtomicFile atomic = new AtomicFile(encrypted);
                FileOutputStream output = null;
                try {
                    output = atomic.startWrite();
                    Os.fchmod(output.getFD(), 0600);
                    output.write(payload);
                    atomic.finishWrite(output);
                    output = null;
                } finally {
                    if (output != null) atomic.failWrite(output);
                }
                requirePrivate(encrypted, false);
                password = decrypt(key, readPrivate(encrypted, MAX_PASSWORD + 64));
                if (!MessageDigest.isEqual(imported, password)) throw new GeneralSecurityException("Keyring vault verification failed");
            }
            validatePassword(password);
            if (hasPending) Os.remove(pending.getAbsolutePath());
            byte[] result = password;
            password = null;
            return result;
        } finally {
            if (imported != null) Arrays.fill(imported, (byte) 0);
            if (password != null) Arrays.fill(password, (byte) 0);
        }
    }

    private static byte[] encrypt(SecretKey key, byte[] password) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        cipher.updateAAD(AAD);
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(password);
        return ByteBuffer.allocate(MAGIC.length + 1 + iv.length + ciphertext.length)
                .put(MAGIC).put((byte) iv.length).put(iv).put(ciphertext).array();
    }

    private static byte[] decrypt(SecretKey key, byte[] payload) throws GeneralSecurityException {
        if (payload.length < 4 + 1 + 12 + 16 || !Arrays.equals(MAGIC, Arrays.copyOf(payload, 4))
                || payload[4] != 12) throw new GeneralSecurityException("Invalid keyring vault format");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, payload, 5, 12));
        cipher.updateAAD(AAD);
        return cipher.doFinal(payload, 17, payload.length - 17);
    }

    private static void validatePassword(byte[] value) throws IOException {
        if (value == null || value.length == 0 || value.length > MAX_PASSWORD) throw new IOException("Invalid keyring credential length");
        for (byte b : value) if (b == 0) throw new IOException("Invalid keyring credential encoding");
    }

    private static boolean existsWithoutFollowingLinks(File file) throws ErrnoException {
        try { Os.lstat(file.getAbsolutePath()); return true; }
        catch (ErrnoException e) { if (e.errno == OsConstants.ENOENT) return false; throw e; }
    }

    private static void requirePrivate(File file, boolean directory) throws Exception {
        StructStat stat = Os.lstat(file.getAbsolutePath());
        if (stat.st_uid != android.os.Process.myUid()
                || (directory ? !OsConstants.S_ISDIR(stat.st_mode) : !OsConstants.S_ISREG(stat.st_mode))
                || (stat.st_mode & 0077) != 0 || (!directory && stat.st_nlink != 1)) {
            throw new GeneralSecurityException("Unsafe keyring vault file permissions or type");
        }
    }

    private static byte[] readPrivate(File file, int limit) throws Exception {
        FileDescriptor fd = Os.open(file.getAbsolutePath(), OsConstants.O_RDONLY | OsConstants.O_NOFOLLOW | OsConstants.O_CLOEXEC, 0);
        try (FileInputStream input = new FileInputStream(fd)) {
            StructStat stat = Os.fstat(fd);
            if (stat.st_uid != android.os.Process.myUid() || !OsConstants.S_ISREG(stat.st_mode)
                    || (stat.st_mode & 0077) != 0 || stat.st_nlink != 1 || stat.st_size < 1 || stat.st_size > limit) {
                throw new GeneralSecurityException("Unsafe keyring vault input");
            }
            byte[] data = new byte[(int) stat.st_size];
            int count = 0;
            try {
                while (count < data.length) {
                    int read = input.read(data, count, data.length - count);
                    if (read < 0) throw new EOFException("Incomplete keyring vault input");
                    count += read;
                }
                if (input.read() != -1) throw new IOException("Keyring vault input changed during read");
                return data;
            } catch (Exception error) { Arrays.fill(data, (byte) 0); throw error; }
        }
    }
}
