package app.foldgpt.install;

import java.io.IOException;
import java.nio.channels.Channels;
import java.nio.channels.SeekableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Explicit guest account contract shared by provisioning and runtime startup.
 * PRoot IDs describe guest identity only; Android remains the kernel owner. */
public final class GuestIdentity {
    public final String user, home, shell;
    public final int uid, gid;
    private GuestIdentity(String user, int uid, int gid, String home, String shell) {
        this.user=user; this.uid=uid; this.gid=gid; this.home=home; this.shell=shell;
    }
    public String prootIds() { return uid+":"+gid; }

    public static GuestIdentity load(Path root) throws IOException {
        Path etc=root.resolve("etc");
        if (!Files.isDirectory(etc, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Guest etc must be a directory");
        String selected=read(etc.resolve("foldgpt-user"),128);
        if (!selected.endsWith("\n") || !selected.substring(0,selected.length()-1).matches("[a-z_][a-z0-9_-]{0,31}"))
            throw new IOException("Invalid guest account selection");
        GuestIdentity result=parse(selected.trim(),read(etc.resolve("passwd"),1048576),read(etc.resolve("group"),1048576));
        Path home=root;
        for (String part:result.home.substring(1).split("/")) {
            home=home.resolve(part);
            if (!Files.isDirectory(home,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Guest home must use real directories");
        }
        return result;
    }
    private static String read(Path path,int limit) throws IOException {
        if (!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Missing or linked guest identity file: "+path.getFileName());
        try (SeekableByteChannel channel=Files.newByteChannel(path,Set.of(StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS))) {
            byte[] bytes=Channels.newInputStream(channel).readNBytes(limit+1);
            if(bytes.length>limit) throw new IOException("Oversized guest identity file");
            String text=new String(bytes,StandardCharsets.UTF_8);
            if(text.indexOf('\0')>=0 || text.indexOf('\r')>=0) throw new IOException("Invalid guest identity encoding");
            return text;
        }
    }
    static GuestIdentity parse(String selected,String passwd,String groups) throws IOException {
        if(!selected.matches("[a-z_][a-z0-9_-]{0,31}")) throw new IOException("Invalid guest username");
        GuestIdentity found=null;
        Set<Integer> identities=new HashSet<>();
        for(String line:passwd.split("\n")) {
            if(line.isEmpty()) continue;
            String[] fields=line.split(":",-1);
            if(fields.length!=7) throw new IOException("Malformed guest passwd");
            int uid=number(fields[2]),gid=number(fields[3]);
            if(!identities.add(uid)) throw new IOException("Ambiguous guest UID");
            if(!fields[0].equals(selected)) continue;
            if(found!=null || uid==0 || gid==0 || !fields[5].equals("/home/"+selected) || !fields[6].equals("/bin/bash"))
                throw new IOException("Invalid or ambiguous interactive guest account");
            found=new GuestIdentity(selected,uid,gid,fields[5],fields[6]);
        }
        if(found==null) throw new IOException("Selected guest account is missing");
        int matches=0;
        for(String line:groups.split("\n")) {
            if(line.isEmpty()) continue;
            String[] fields=line.split(":",-1);
            if(fields.length!=4) throw new IOException("Malformed guest group");
            int gid=number(fields[2]);
            if(gid==found.gid) {
                if(!fields[0].equals(selected)) throw new IOException("Guest primary group differs");
                matches++;
            } else if(fields[0].equals(selected)) throw new IOException("Ambiguous guest group name");
        }
        if(matches!=1) throw new IOException("Guest primary group is missing or ambiguous");
        return found;
    }
    private static int number(String value) throws IOException {
        if(!value.matches("0|[1-9][0-9]{0,9}")) throw new IOException("Invalid guest numeric identity");
        try { return Integer.parseInt(value); }
        catch(NumberFormatException error) { throw new IOException("Guest numeric identity overflow",error); }
    }
}
