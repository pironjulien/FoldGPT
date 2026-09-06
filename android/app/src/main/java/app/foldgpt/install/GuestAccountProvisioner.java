package app.foldgpt.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.util.*;

/** Creates the local, password-locked guest account in a leased PREPARED root.
 *
 * This edits Debian's actual account databases; it never executes an unconfined
 * guest tool or claims that PRoot identities grant kernel privileges. The caller
 * must pass the Android process UID/GID and retain the installation lease. The
 * intent binds original/result hashes to the staged root inode before changing
 * any database. Replays accept only those exact versions, including after a
 * process death between atomic replacements. Like Debian useradd, it preserves
 * whether shadow/gshadow databases are present: an absent shadow means the new
 * account is locked directly with ! in passwd. It never converts existing
 * accounts, creates a password or copies a profile.
 *
 * The component owns account creation only, not activation, persistent-home
 * binding, skeleton configuration, DNS, client installation or vault creation.
 * Account validation should precede later package/user-data changes; once the
 * installer advances past identity provisioning it must validate that identity
 * using GuestIdentity rather than replaying old whole-database hashes.
 */
public final class GuestAccountProvisioner {
    private GuestAccountProvisioner() {}
    public interface Storage {
        String identity(Path directory) throws IOException;
        long linkCount(Path file) throws IOException;
        void syncDirectory(Path directory) throws IOException;
    }
    interface Checkpoint { void at(String name) throws IOException; }
    private static final String USER="foldgpt";
    private static final String[] DATABASES={"group","gshadow","passwd","shadow"};
    private static final int[] MODES={0644,0600,0644,0600};
    private static final int MAX_DATABASE=1024*1024;
    private static final Set<PosixFilePermission> PRIVATE=PosixFilePermissions.fromString("rwx------");

    public static GuestIdentity prepare(RootfsTransaction transaction, Storage storage, int androidUid, int androidGid) throws IOException {
        return prepare(transaction,storage,androidUid,androidGid,name -> {});
    }

    static GuestIdentity prepare(RootfsTransaction transaction, Storage storage, int uid, int gid, Checkpoint checkpoint) throws IOException {
        Objects.requireNonNull(transaction); Objects.requireNonNull(storage); Objects.requireNonNull(checkpoint);
        if(uid<=0 || gid<=0) throw new IOException("A non-root Android process identity is required");
        synchronized(transaction) {
            if(transaction.state()!=RootfsTransaction.State.PREPARED)
                throw new IOException("Guest account provisioning requires the inactive PREPARED transaction lease");
            Path root=transaction.prepare(() -> { throw new IOException("Identity provisioning cannot extract a base"); }).root;
            return new Preparation(root,storage,uid,gid,checkpoint).run();
        }
    }

    private static final class Preparation {
        final Path root,etc,home,journal;
        final Storage storage;
        final UserPrincipal owner;
        final int uid,gid;
        final Checkpoint checkpoint;
        final String[] additions;
        Preparation(Path root,Storage storage,int uid,int gid,Checkpoint checkpoint) throws IOException {
            this.root=root; this.etc=root.resolve("etc"); this.home=root.resolve("home");
            this.journal=etc.resolve("foldgpt-account.v1"); this.storage=storage;
            this.uid=uid; this.gid=gid; this.checkpoint=checkpoint;
            this.owner=Files.getOwner(root,LinkOption.NOFOLLOW_LINKS);
            boolean shadow=exists(etc.resolve("shadow")),gshadow=exists(etc.resolve("gshadow"));
            additions=new String[]{USER+(gshadow?":x:":":!:")+gid+":\n",gshadow?USER+":!::\n":null,
                USER+(shadow?":x:":":!:")+uid+":"+gid+":FoldGPT:/home/foldgpt:/bin/bash\n",shadow?USER+":!:0:0:99999:7:::\n":null};
        }
        GuestIdentity run() throws IOException {
            directory(root,false); directory(etc,false);
            if(exists(home)) directory(home,false);
            String identity=storage.identity(root);
            if(!identity.matches("[0-9]+:[0-9]+")) throw new IOException("Invalid staged root inode identity");
            String[] originals=new String[4],results=new String[4];
            if(exists(journal)) {
                requireMode(journal,0600);
                String value=read(journal,4096);
                String[] lines=value.split("\n",-1);
                if(lines.length!=10 || !lines[0].equals("foldgpt.guest-account.v1")
                        || !lines[1].equals(identity) || !lines[2].equals(uid+":"+gid)
                        || !lines[3].equals("foldgpt:/home/foldgpt:/bin/bash") || !lines[9].isEmpty()
                        || !lines[8].equals(hash(String.join("\n",Arrays.copyOf(lines,8))+"\n")))
                    throw new IOException("Guest account intent or staged root identity differs");
                for(int i=0;i<4;i++) {
                    String[] fields=lines[4+i].split(" ",-1);
                    if(fields.length!=3 || !fields[0].equals(DATABASES[i])
                            || !(fields[1].matches("[0-9a-f]{64}") && fields[2].matches("[0-9a-f]{64}")
                            || (i==1 || i==3) && fields[1].equals("-") && fields[2].equals("-")))
                        throw new IOException("Invalid guest database intent");
                    originals[i]=fields[1]; results[i]=fields[2];
                }
            } else {
                if(exists(etc.resolve("foldgpt-user")) || exists(home.resolve(USER)))
                    throw new IOException("An unprovisioned account selection or guest home already exists");
                String[] databases=new String[4];
                for(int i=0;i<4;i++) databases[i]=readDatabase(i);
                validateOriginals(databases);
                StringBuilder value=new StringBuilder("foldgpt.guest-account.v1\n"+identity+"\n"+uid+":"+gid
                        +"\nfoldgpt:/home/foldgpt:/bin/bash\n");
                for(int i=0;i<4;i++) {
                    originals[i]=databases[i]==null?"-":hash(databases[i]);
                    results[i]=databases[i]==null?"-":hash(databases[i]+additions[i]);
                    value.append(DATABASES[i]).append(' ').append(originals[i]).append(' ').append(results[i]).append('\n');
                }
                value.append(hash(value.toString())).append('\n');
                replace(journal,value.toString(),0600,"intent");
            }
            // Check every input before making progress, so a conflicting late
            // database cannot result in new partial writes on this invocation.
            String[] next=new String[4],base=new String[4];
            for(int i=0;i<4;i++) {
                String current=readDatabase(i);
                if(originals[i].equals("-") && current==null) continue;
                if(current==null || originals[i].equals("-") || additions[i]==null)
                    throw new IOException("Guest shadow database presence differs from provisioning intent");
                if(hash(current).equals(originals[i])) { base[i]=current; next[i]=current+additions[i]; }
                else if(hash(current).equals(results[i]) && current.endsWith(additions[i])) {
                    base[i]=current.substring(0,current.length()-additions[i].length()); next[i]=current;
                } else throw new IOException("Guest database changed outside its provisioning intent: "+DATABASES[i]);
                if(!hash(base[i]).equals(originals[i]) || !hash(next[i]).equals(results[i]))
                    throw new IOException("Guest account intent cannot reproduce its database");
            }
            validateOriginals(base);
            Path selection=etc.resolve("foldgpt-user");
            if(exists(selection) && !read(selection,128).equals(USER+"\n"))
                throw new IOException("Guest account selection conflicts with provisioning intent");
            if(exists(home.resolve(USER))) directory(home.resolve(USER),true);
            for(int i=0;i<4;i++) {
                if(next[i]==null) continue;
                Path file=etc.resolve(DATABASES[i]);
                if(!read(file,MAX_DATABASE).equals(next[i]) || !hasMode(file,MODES[i]))
                    replace(file,next[i],MODES[i],DATABASES[i]);
                requireMode(file,MODES[i]);
            }
            createDirectory(home,0755,false);
            createDirectory(home.resolve(USER),0700,true);
            checkpoint.at("home-created");
            if(!exists(selection) || !hasMode(selection,0644)) replace(selection,USER+"\n",0644,"selection");
            requireMode(selection,0644);
            GuestIdentity selected=GuestIdentity.load(root);
            if(selected.uid!=uid || selected.gid!=gid || !selected.user.equals(USER))
                throw new IOException("Provisioned guest identity differs");
            for(int i=0;i<4;i++) {
                String current=readDatabase(i);
                if(!(current==null?"-":hash(current)).equals(results[i]))
                    throw new IOException("Guest account verification changed during provisioning");
            }
            if(!storage.identity(root).equals(identity)) throw new IOException("Staged root changed during provisioning");
            checkpoint.at("verified");
            return selected;
        }
        void validateOriginals(String[] databases) throws IOException {
            int[] widths={4,4,7,9};
            for(int i=0;i<4;i++) {
                String text=databases[i];
                if(text==null && (i==1 || i==3)) continue;
                if(!text.endsWith("\n")) throw new IOException("Guest database lacks its final newline: "+DATABASES[i]);
                Set<String> names=new HashSet<>(); Set<Integer> ids=new HashSet<>();
                for(String line:text.split("\n")) {
                    String[] fields=line.split(":",-1);
                    if(fields.length!=widths[i] || !fields[0].matches("[a-zA-Z_][a-zA-Z0-9_.-]*[$]?") || !names.add(fields[0]))
                        throw new IOException("Malformed or duplicate guest database entry: "+DATABASES[i]);
                    if(fields[0].equals(USER)) throw new IOException("Guest account name already exists: "+DATABASES[i]);
                    if(i==2 && databases[3]==null && fields[1].equals("x"))
                        throw new IOException("A guest account requires a missing shadow database");
                    if(i==0 || i==2) {
                        int id=number(fields[2]);
                        if(!ids.add(id) || id==(i==0?gid:uid)) throw new IOException("Guest numeric identity conflicts: "+DATABASES[i]);
                        if(i==2 && number(fields[3])==gid)
                            throw new IOException("Existing guest account already uses the requested primary group");
                    }
                    if(i==0 && Arrays.asList(fields[3].split(",")).contains(USER))
                        throw new IOException("Unprovisioned guest already belongs to a group");
                    if(i==1 && (Arrays.asList(fields[2].split(",")).contains(USER) || Arrays.asList(fields[3].split(",")).contains(USER)))
                        throw new IOException("Unprovisioned guest appears in group administrators or members");
                }
                if(!names.contains("root")) throw new IOException("Guest database is missing root: "+DATABASES[i]);
            }
        }
        void replace(Path target,String text,int mode,String step) throws IOException {
            Path pending=etc.resolve(".foldgpt-account-"+step+".next");
            if(exists(pending)) { regular(pending); Files.delete(pending); }
            try(FileChannel output=FileChannel.open(pending,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(permissions(mode)))) {
                ByteBuffer bytes=ByteBuffer.wrap(text.getBytes(StandardCharsets.UTF_8));
                while(bytes.hasRemaining()) output.write(bytes);
                // Creation permissions are filtered by the process umask on
                // Android too. Set the exact mode on our exclusive staged file
                // before fsync/publication, without changing the process umask.
                Files.getFileAttributeView(pending,java.nio.file.attribute.PosixFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS).setPermissions(permissions(mode));
                requireMode(pending,mode);
                output.force(true);
            }
            checkpoint.at(step+"-ready");
            if(exists(target)) regular(target);
            Files.move(pending,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            storage.syncDirectory(etc);
            checkpoint.at(step+"-written");
        }
        void createDirectory(Path path,int mode,boolean privateHome) throws IOException {
            if(!exists(path)) {
                Files.createDirectory(path,PosixFilePermissions.asFileAttribute(permissions(mode)));
                Files.getFileAttributeView(path,java.nio.file.attribute.PosixFileAttributeView.class,
                    LinkOption.NOFOLLOW_LINKS).setPermissions(permissions(mode));
            }
            directory(path,privateHome);
            storage.syncDirectory(path);
            storage.syncDirectory(path.getParent());
        }
        void directory(Path path,boolean privateHome) throws IOException {
            if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(owner))
                throw new IOException("Guest account path must be a real owned directory: "+path.getFileName());
            Set<PosixFilePermission> mode=Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS);
            if(mode.contains(PosixFilePermission.GROUP_WRITE) || mode.contains(PosixFilePermission.OTHERS_WRITE)
                    || (privateHome && !mode.equals(PRIVATE))) throw new IOException("Unsafe guest account directory permissions");
        }
        void regular(Path path) throws IOException {
            if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || storage.linkCount(path)!=1
                    || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(owner))
                throw new IOException("Guest account metadata must be an owned, unlinked regular file: "+path.getFileName());
            Set<PosixFilePermission> mode=Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS);
            if(mode.contains(PosixFilePermission.GROUP_WRITE) || mode.contains(PosixFilePermission.OTHERS_WRITE))
                throw new IOException("Unsafe guest account metadata permissions");
        }
        String read(Path file,int limit) throws IOException {
            regular(file);
            try(FileChannel input=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
                if(input.size()>limit) throw new IOException("Guest account metadata exceeds size limit");
                ByteBuffer bytes=ByteBuffer.allocate(limit+1);
                while(bytes.hasRemaining() && input.read(bytes)!=-1) {}
                if(bytes.position()>limit) throw new IOException("Guest account metadata exceeds size limit");
                bytes.flip();
                String value=StandardCharsets.UTF_8.newDecoder().decode(bytes).toString();
                if(value.indexOf('\0')>=0 || value.indexOf('\r')>=0) throw new IOException("Invalid guest account metadata encoding");
                return value;
            }
        }
        String readDatabase(int index) throws IOException {
            Path file=etc.resolve(DATABASES[index]);
            if((index==1 || index==3) && !exists(file)) return null;
            return read(file,MAX_DATABASE);
        }
        void requireMode(Path file,int mode) throws IOException {
            if(!hasMode(file,mode))
                throw new IOException("Guest account file permissions differ: "+file.getFileName());
        }
        boolean hasMode(Path file,int mode) throws IOException {
            return Files.getPosixFilePermissions(file,LinkOption.NOFOLLOW_LINKS).equals(permissions(mode));
        }
    }
    private static boolean exists(Path path) throws IOException {
        try { Files.readAttributes(path,java.nio.file.attribute.BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS); return true; }
        catch(NoSuchFileException absent) { return false; }
    }
    private static Set<PosixFilePermission> permissions(int mode) {
        return PosixFilePermissions.fromString(mode==0600?"rw-------":mode==0644?"rw-r--r--":mode==0700?"rwx------":"rwxr-xr-x");
    }
    private static int number(String value) throws IOException {
        if(!value.matches("0|[1-9][0-9]{0,9}")) throw new IOException("Invalid guest numeric identity");
        try { return Integer.parseInt(value); }
        catch(NumberFormatException error) { throw new IOException("Guest numeric identity overflow",error); }
    }
    private static String hash(String value) {
        try {
            StringBuilder result=new StringBuilder();
            for(byte b:MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)))
                result.append(String.format(Locale.ROOT,"%02x",b&255));
            return result.toString();
        } catch(java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
