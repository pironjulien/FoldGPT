package app.foldgpt.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.*;

/** Durable progress for the bounded INACTIVE base/account/vault/collection flow.
 * Call only while holding the enclosing RootfsTransaction lease. This journal
 * neither edits that transaction nor contains an activation or readiness state.
 * Bindings are the coordinator's independently verified component descriptors.
 */
public final class InactivePreparationJournal {
    public enum Step { ROOT_PREPARED, ACCOUNT_PREPARED, VAULT_PREPARED, COLLECTION_PREPARED }
    interface Checkpoint { void at(String name) throws IOException; }
    private static final String SCHEMA="foldgpt.inactive-preparation.v1";
    private final Path file;
    private final GuestAccountProvisioner.Storage storage;
    private final UserPrincipal owner;
    private final Checkpoint checkpoint;
    private Map<String,String> values;

    public static InactivePreparationJournal open(Path file,Map<String,String> bindings,GuestAccountProvisioner.Storage storage) throws IOException {
        return open(file,bindings,storage,name -> {});
    }
    static InactivePreparationJournal open(Path file,Map<String,String> bindings,GuestAccountProvisioner.Storage storage,Checkpoint checkpoint) throws IOException {
        return new InactivePreparationJournal(file,bindings,storage,checkpoint);
    }
    private InactivePreparationJournal(Path file,Map<String,String> bindings,GuestAccountProvisioner.Storage storage,Checkpoint checkpoint) throws IOException {
        this.file=file; this.storage=storage; this.checkpoint=checkpoint;
        if(!Files.isDirectory(file.getParent(),LinkOption.NOFOLLOW_LINKS)
                || !Files.getPosixFilePermissions(file.getParent(),LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rwx------")))
            throw new IOException("Inactive preparation journal needs a real private directory");
        owner=Files.getOwner(file.getParent(),LinkOption.NOFOLLOW_LINKS);
        Map<String,String> expected=new TreeMap<>();
        expected.put("schema",SCHEMA);
        for(Map.Entry<String,String> item:bindings.entrySet()) {
            if(!item.getKey().matches("[a-z][a-zA-Z0-9]{0,31}") || !safe(item.getValue())) throw new IOException("Invalid inactive preparation binding");
            expected.put("bind."+item.getKey(),item.getValue());
        }
        if(bindings.isEmpty()) throw new IOException("Inactive preparation requires component bindings");
        if(exists(file)) {
            regular(file);
            byte[] bytes;
            try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer=ByteBuffer.allocate(8193);
                while(buffer.hasRemaining() && input.read(buffer)!=-1) {}
                bytes=new byte[buffer.position()]; buffer.flip(); buffer.get(bytes);
            }
            if(bytes.length>8192) throw new IOException("Oversized inactive preparation journal");
            String text=StandardCharsets.US_ASCII.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
            int checksumAt=text.lastIndexOf("checksum=");
            if(checksumAt<0 || !text.substring(checksumAt).equals("checksum="+sha256(text.substring(0,checksumAt).getBytes(StandardCharsets.US_ASCII))+"\n"))
                throw new IOException("Inactive preparation journal checksum differs");
            values=new TreeMap<>();
            for(String line:text.substring(0,checksumAt).split("\n")) {
                int delimiter=line.indexOf('=');
                if(delimiter<=0 || !safe(line.substring(delimiter+1)) || values.put(line.substring(0,delimiter),line.substring(delimiter+1))!=null)
                    throw new IOException("Malformed inactive preparation journal");
            }
            for(Map.Entry<String,String> entry:expected.entrySet()) if(!entry.getValue().equals(values.get(entry.getKey())))
                throw new IOException("Inactive preparation component or root binding differs: "+entry.getKey());
            Set<String> keys=new HashSet<>(expected.keySet());
            keys.addAll(Set.of("installationId","step","vaultSha256","collectionIntentSha256","collectionInstallationId","collectionPath","dataIdentity"));
            if(!values.keySet().equals(keys) || !values.get("installationId").matches("[0-9a-f]{64}"))
                throw new IOException("Unknown inactive preparation journal fields");
            validateState(values);
            storage.syncDirectory(file.getParent());
        } else {
            values=expected;
            byte[] random=new byte[32]; new SecureRandom().nextBytes(random);
            values.put("installationId",hex(random)); values.put("step",Step.ROOT_PREPARED.name());
            for(String key:Set.of("vaultSha256","collectionIntentSha256","collectionInstallationId","collectionPath","dataIdentity")) values.put(key,"-");
            write(values);
        }
    }
    public Step step() throws IOException {
        try { return Step.valueOf(values.get("step")); }
        catch(IllegalArgumentException invalid) { throw new IOException("Unknown inactive preparation step",invalid); }
    }
    public String value(String key) { return values.get(key); }
    public void accountPrepared() throws IOException {
        if(step()!=Step.ROOT_PREPARED) throw new IOException("Inactive account step is out of order");
        Map<String,String> next=new TreeMap<>(values); next.put("step",Step.ACCOUNT_PREPARED.name()); write(next);
    }
    public void vaultPrepared(String ciphertextSha256) throws IOException {
        if(step()!=Step.ACCOUNT_PREPARED || !digest(ciphertextSha256)) throw new IOException("Inactive vault step is out of order or unverified");
        Map<String,String> next=new TreeMap<>(values); next.put("step",Step.VAULT_PREPARED.name()); next.put("vaultSha256",ciphertextSha256); write(next);
    }
    public void collectionPrepared(String intentSha256,String installationId,String path,String dataIdentity) throws IOException {
        if(step()!=Step.VAULT_PREPARED) throw new IOException("Inactive collection step is out of order");
        Map<String,String> next=new TreeMap<>(values); next.put("step",Step.COLLECTION_PREPARED.name());
        next.put("collectionIntentSha256",intentSha256); next.put("collectionInstallationId",installationId);
        next.put("collectionPath",path); next.put("dataIdentity",dataIdentity); write(next);
    }
    private void write(Map<String,String> next) throws IOException {
        validateState(next);
        StringBuilder text=new StringBuilder();
        for(Map.Entry<String,String> item:new TreeMap<>(next).entrySet()) text.append(item.getKey()).append('=').append(item.getValue()).append('\n');
        String checksum=sha256(text.toString().getBytes(StandardCharsets.US_ASCII));
        text.append("checksum=").append(checksum).append('\n');
        Path pending=file.resolveSibling(file.getFileName()+".next");
        if(exists(pending)) { regular(pending); Files.delete(pending); }
        try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes=ByteBuffer.wrap(text.toString().getBytes(StandardCharsets.US_ASCII));
            while(bytes.hasRemaining()) output.write(bytes);
            output.force(true);
        }
        checkpoint.at("ready-"+next.get("step"));
        if(exists(file)) regular(file);
        Files.move(pending,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        storage.syncDirectory(file.getParent()); values=new TreeMap<>(next);
        checkpoint.at("written-"+next.get("step"));
    }
    private static void validateState(Map<String,String> values) throws IOException {
        Step step;
        try { step=Step.valueOf(values.get("step")); }
        catch(RuntimeException invalid) { throw new IOException("Invalid inactive preparation step",invalid); }
        if(step.ordinal()>=Step.VAULT_PREPARED.ordinal() ? !digest(values.get("vaultSha256")) : !"-".equals(values.get("vaultSha256")))
            throw new IOException("Inactive preparation vault evidence differs");
        if(step==Step.COLLECTION_PREPARED) {
            if(!digest(values.get("collectionIntentSha256")) || !digest(values.get("collectionInstallationId"))
                    || !values.get("collectionPath").matches("/org/freedesktop/secrets/collection/[A-Za-z0-9_]+")
                    || values.get("collectionPath").endsWith("/session") || !values.get("dataIdentity").matches("[0-9]+:[0-9]+"))
                throw new IOException("Inactive preparation collection evidence differs");
        } else for(String key:Set.of("collectionIntentSha256","collectionInstallationId","collectionPath","dataIdentity"))
            if(!"-".equals(values.get(key))) throw new IOException("Unexpected collection evidence before preparation");
    }
    private void regular(Path path) throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || storage.linkCount(path)!=1
                || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(owner)
                || !Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rw-------"))
                || Files.size(path)>8192) throw new IOException("Unsafe inactive preparation journal");
    }
    static boolean exists(Path path) throws IOException {
        try { Files.readAttributes(path,java.nio.file.attribute.BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS); return true; }
        catch(NoSuchFileException absent) { return false; }
    }
    private static boolean safe(String value) { return value!=null && value.matches("[A-Za-z0-9_./:+ -]{1,1024}"); }
    private static boolean digest(String value) { return value!=null && value.matches("[0-9a-f]{64}"); }
    static String sha256(byte[] bytes) {
        try { return hex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch(java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static String hex(byte[] bytes) {
        StringBuilder result=new StringBuilder(); for(byte b:bytes) result.append(String.format(Locale.ROOT,"%02x",b&255)); return result.toString();
    }
}
