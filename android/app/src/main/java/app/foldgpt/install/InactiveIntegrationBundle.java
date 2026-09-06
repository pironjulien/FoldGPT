package app.foldgpt.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Authenticated, bounded release container. No filesystem writes or tar parser.
 * The caller supplies the independently trusted release SHA, never a digest
 * read from this container or calculated from an untrusted download. */
public final class InactiveIntegrationBundle {
    public static final String FORMAT="foldgpt.inactive-integration.v1";
    public static final String GPU_PREFIX="opt/foldgpt-gpu/mesa-26.2.2-foldgpt5";
    public static final String GPU_SHA="e02091631e5f16efbc3678373b2c048ebf81b10d551caf210d61b1954b7671d4";
    public static final String XKB="usr/share/X11/xkb";
    static final String CONTRACT_PATH="usr/local/share/foldgpt/launch-contract.v1";
    static final String CONTRACT="foldgpt.launch-contract.v1\n"
        +"scope=declared-launch-inputs-only\nguest=/usr/local/bin/foldgpt-session\nguest-shell=/bin/bash\n"
        +"guest-identity=etc/foldgpt-user-and-passwd-and-group\nguest-display=:2\nnative-xkb=usr/share/X11/xkb\n"
        +"gpu-prefix=/"+GPU_PREFIX+"\ngpu-driver=zink\nvulkan-icd=/"+GPU_PREFIX+"/share/vulkan/icd.d/freedreno_icd.aarch64.json\n"
        +"cdp-loopback=127.0.0.1:9223\nscale=android-display-density\nbridges=android-process-uid\n"
        +"android-root=not-required\nactivation=separate-validator-required\n";
    public static final int MAX_BYTES=64*1024*1024;
    static final Map<String,Integer> FILES;
    static final Map<String,String> LINKS;
    static {
        Map<String,Integer> files=new TreeMap<>();
        files.put("usr/local/bin/foldgpt-session",0700); files.put("usr/local/bin/xdg-open",0755);
        for(String name:List.of("foldgpt_keyring.py","foldgpt_ime.py","keyboard-focus.js")) files.put("usr/local/lib/foldgpt/"+name,0644);
        for(String name:List.of("initialize_keyring.py","supervise_keyring.py")) files.put("usr/local/lib/foldgpt/install/"+name,0600);
        files.put("usr/local/share/doc/foldgpt/LICENSE",0644); files.put(CONTRACT_PATH,0644);
        for(String name:List.of("lib/dri/libdril_dri.so","lib/libEGL.so.1.0.0","lib/libgallium-26.2.2.so","lib/libGL.so.1.2.0",
                "lib/libGLESv1_CM.so.1.1.0","lib/libGLESv2.so.2.0.0","lib/libvulkan_freedreno.so")) files.put(GPU_PREFIX+"/"+name,0755);
        for(String name:List.of("share/drirc.d/00-mesa-defaults.conf","share/drirc.d/00-turnip-defaults.conf","share/drirc.d/00-zink-defaults.conf",
                "share/vulkan/icd.d/freedreno_icd.aarch64.json")) files.put(GPU_PREFIX+"/"+name,0644);
        FILES=Collections.unmodifiableMap(files);
        Map<String,String> links=new TreeMap<>();
        links.put("lib/dri/zink_dri.so","libdril_dri.so"); links.put("lib/libEGL.so","libEGL.so.1"); links.put("lib/libEGL.so.1","libEGL.so.1.0.0");
        links.put("lib/libGL.so","libGL.so.1"); links.put("lib/libGL.so.1","libGL.so.1.2.0");
        links.put("lib/libGLESv1_CM.so","libGLESv1_CM.so.1"); links.put("lib/libGLESv1_CM.so.1","libGLESv1_CM.so.1.1.0");
        links.put("lib/libGLESv2.so","libGLESv2.so.2"); links.put("lib/libGLESv2.so.2","libGLESv2.so.2.0.0");
        Map<String,String> prefixed=new TreeMap<>(); links.forEach((path,target) -> prefixed.put(GPU_PREFIX+"/"+path,target));
        LINKS=Collections.unmodifiableMap(prefixed);
    }
    static final class Entry {
        final String scope,kind,path,sha,link; final int mode,size; int offset;
        Entry(String[] fields) throws IOException {
            scope=fields[0]; kind=fields[1]; path=path(fields[5]); sha=fields[4]; link=fields[6];
            if(!fields[2].matches("0[0-7]{3}") || !fields[3].matches("0|[1-9][0-9]{0,7}")) throw new IOException("Invalid integration size or mode");
            try { mode=Integer.parseInt(fields[2],8); size=Integer.parseInt(fields[3]); }
            catch(NumberFormatException error) { throw new IOException("Integration number overflow",error); }
            if(size>32*1024*1024 || !(scope.equals("I") || scope.equals("V"))) throw new IOException("Invalid integration scope or file bound");
            if(kind.equals("F")) { if(!sha.matches("[0-9a-f]{64}") || !link.equals("-")) throw new IOException("Invalid regular integration entry"); }
            else if(kind.equals("D") || kind.equals("L")) {
                if(size!=0 || !sha.equals("-") || kind.equals("D") && !link.equals("-")) throw new IOException("Invalid non-file integration entry");
                if(kind.equals("L") && (!path(link).equals(link) || link.contains("/"))) throw new IOException("Only same-directory integration links are accepted");
            } else throw new IOException("Unknown integration entry kind");
        }
    }
    final byte[] bytes;
    final NavigableMap<String,Entry> entries;
    public final String sha256,baseSha256,guestSha256,manifestSha256;
    private InactiveIntegrationBundle(byte[] data,String sha,String base,String guest,String manifest,NavigableMap<String,Entry> entries) {
        bytes=data; sha256=sha; baseSha256=base; guestSha256=guest; manifestSha256=manifest; this.entries=entries;
    }
    public static InactiveIntegrationBundle read(InputStream input,String trustedSha256,long trustedBytes) throws IOException {
        if(trustedSha256==null || !trustedSha256.matches("[0-9a-f]{64}") || trustedBytes<=0 || trustedBytes>MAX_BYTES)
            throw new IOException("Independent integration digest and size are required");
        byte[] bytes=input.readNBytes((int)trustedBytes+1);
        if(bytes.length!=trustedBytes || !hash(bytes).equals(trustedSha256)) throw new IOException("Integration container authentication failed");
        DataInputStream stream=new DataInputStream(new ByteArrayInputStream(bytes));
        byte[] magic=(FORMAT+"\n").getBytes(StandardCharsets.US_ASCII);
        if(!Arrays.equals(magic,stream.readNBytes(magic.length))) throw new IOException("Invalid integration framing");
        int length=stream.readInt();
        if(length<=0 || length>512*1024) throw new IOException("Integration manifest exceeds bound");
        byte[] encoded=stream.readNBytes(length);
        if(encoded.length!=length) throw new IOException("Truncated integration manifest");
        for(byte value:encoded) if(value<0 || value==0 || value=='\r') throw new IOException("Integration manifest must be canonical ASCII");
        String[] lines=new String(encoded,StandardCharsets.US_ASCII).split("\n",-1);
        if(lines.length<8 || !lines[0].equals(FORMAT) || !lines[lines.length-1].isEmpty()) throw new IOException("Invalid integration manifest header");
        String base=binding(lines[1],"base"),guest=binding(lines[2],"guest"),gpu=binding(lines[3],"gpu");
        if(!gpu.equals(GPU_SHA)) throw new IOException("Only the reviewed foldgpt5 GPU artifact is accepted");
        NavigableMap<String,Entry> entries=new TreeMap<>(); String previous="";
        Set<String> files=new TreeSet<>(),links=new TreeSet<>();
        int offset=magic.length+4+length;
        for(int index=4;index<lines.length-1;index++) {
            String[] fields=lines[index].split("\t",-1);
            if(fields.length!=7) throw new IOException("Invalid integration record width");
            Entry entry=new Entry(fields);
            if(entry.path.compareTo(previous)<=0) throw new IOException("Integration entries must be unique and sorted"); previous=entry.path;
            if(entry.scope.equals("I")) {
                if(entry.kind.equals("F")) {
                    if(!Objects.equals(FILES.get(entry.path),entry.mode) || entry.size==0) throw new IOException("Unexpected installed integration file or mode");
                    files.add(entry.path); entry.offset=offset;
                    if((long)offset+entry.size>bytes.length || !hash(bytes,offset,entry.size).equals(entry.sha)) throw new IOException("Integration payload hash or length differs");
                    offset+=entry.size;
                } else if(entry.kind.equals("L") && entry.mode==0777 && Objects.equals(LINKS.get(entry.path),entry.link)) links.add(entry.path);
                else throw new IOException("Unexpected installed integration link or directory");
            } else {
                if(!entry.path.equals(XKB) && !entry.path.startsWith(XKB+"/")) throw new IOException("Verification scope is restricted to Debian XKB");
                if(entry.mode!=(entry.kind.equals("D")?0755:entry.kind.equals("L")?0777:0644)) throw new IOException("Unexpected reviewed XKB mode");
            }
            entries.put(entry.path,entry);
        }
        if(!files.equals(FILES.keySet()) || !links.equals(LINKS.keySet()) || offset!=bytes.length) throw new IOException("Missing payload or trailing integration bytes");
        for(String path:List.of(XKB,XKB+"/rules/base",XKB+"/rules/evdev")) {
            Entry entry=entries.get(path);
            if(entry==null || !entry.scope.equals("V") || !entry.kind.equals(path.equals(XKB)?"D":"F")) throw new IOException("Required XKB record absent");
        }
        for(Entry entry:entries.values()) if(entry.scope.equals("V")) {
            if(!entry.path.equals(XKB)) {
                Entry parent=entries.get(entry.path.substring(0,entry.path.lastIndexOf('/')));
                if(parent==null || !parent.kind.equals("D")) throw new IOException("XKB manifest parent is not a directory");
            }
            if(entry.kind.equals("L")) {
                Entry target=entries.get(entry.path.substring(0,entry.path.lastIndexOf('/')+1)+entry.link);
                if(target==null || !target.kind.equals("F")) throw new IOException("XKB native link target is not an inventoried file");
            }
        }
        Entry contract=entries.get(CONTRACT_PATH);
        if(!hash(CONTRACT.getBytes(StandardCharsets.US_ASCII)).equals(contract.sha)) throw new IOException("Launch contract differs from runtime integration contract");
        return new InactiveIntegrationBundle(bytes,trustedSha256,base,guest,hash(encoded),entries);
    }
    static String path(String value) throws IOException {
        if(!value.matches("[A-Za-z0-9_+./-]{1,256}") || value.startsWith("/") || value.endsWith("/")) throw new IOException("Invalid integration path");
        for(String part:value.split("/",-1)) if(part.isEmpty() || part.equals(".") || part.equals("..")) throw new IOException("Noncanonical integration path");
        return value;
    }
    private static String binding(String line,String name) throws IOException {
        if(!line.matches(name+"\t[0-9a-f]{64}")) throw new IOException("Invalid integration input binding"); return line.substring(name.length()+1);
    }
    static String hash(byte[] value) throws IOException { return hash(value,0,value.length); }
    static String hash(byte[] value,int offset,int size) throws IOException {
        try { MessageDigest digest=MessageDigest.getInstance("SHA-256"); digest.update(value,offset,size); return hex(digest.digest()); }
        catch(java.security.NoSuchAlgorithmException error) { throw new IOException("SHA-256 unavailable",error); }
    }
    static String hex(byte[] data) { StringBuilder value=new StringBuilder(); for(byte item:data) value.append(String.format(Locale.ROOT,"%02x",item&255)); return value.toString(); }
}
