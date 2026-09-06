package app.foldgpt.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Parser tests only: no synthetic package, keyring or Android success. */
public final class CombinedPreparationFixtureCheck {
    private static final String ID="0123456789abcdef0123456789abcdef",HASH="0123456789abcdef".repeat(4);
    private static int checks;
    private static byte[] bytes(Map<String,String> fields) {
        StringBuilder text=new StringBuilder(); for(var field:new TreeMap<>(fields).entrySet()) text.append(field.getKey()).append('=').append(field.getValue()).append('\n');
        return text.toString().getBytes(StandardCharsets.US_ASCII);
    }
    private static String hash(byte[] bytes) throws Exception {
        StringBuilder value=new StringBuilder(); for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes)) value.append(String.format(Locale.ROOT,"%02x",b&255)); return value.toString();
    }
    private static void refused(byte[] value,String digest,String id) throws Exception {
        try { CombinedPreparationFixture.parse(value,digest,id); throw new AssertionError("invalid fixture accepted"); }
        catch(IOException expected) { checks++; }
    }
    public static void main(String[] args) throws Exception {
        Map<String,String> good=new TreeMap<>();
        for(String key:CombinedPreparationFixture.KEYS) good.put(key,key.endsWith("Sha256")?HASH:"1");
        good.put("schema","foldgpt.combined-preparation-fixture.v1"); good.put("fixture",ID); good.put("clientVersion","26.901.41600");
        good.put("packageDeadlineMillis","900000"); good.put("totalDeadlineMillis","3600000");
        byte[] canonical=bytes(good);
        CombinedPreparationFixture parsed=CombinedPreparationFixture.parse(canonical,hash(canonical),ID);
        if(parsed.number("packageDeadlineMillis")!=900000) throw new AssertionError("numeric field changed"); checks++;
        refused(canonical,HASH,ID); refused(canonical,hash(canonical),"../outside");
        for(String key:CombinedPreparationFixture.KEYS) {
            Map<String,String> changed=new TreeMap<>(good); changed.remove(key); byte[] value=bytes(changed); refused(value,hash(value),ID);
        }
        for(var change:List.of(Map.entry("command","/bin/sh"),Map.entry("fixture","../outside"),Map.entry("clientSha256","x"),
                Map.entry("clientVersion","26\ncommand=x"),Map.entry("archiveMembers","2147483648"),Map.entry("archiveBytes","9223372036854775808"),
                Map.entry("archiveBytes","0"),Map.entry("archiveBytes","01"),Map.entry("totalDeadlineMillis","43200001"),
                Map.entry("totalDeadlineMillis","120000"),Map.entry("packageDeadlineMillis","2147483648"))) {
            Map<String,String> changed=new TreeMap<>(good); changed.put(change.getKey(),change.getValue()); byte[] value=bytes(changed); refused(value,hash(value),ID);
        }
        byte[] duplicate=(new String(canonical,StandardCharsets.US_ASCII)+"fixture="+ID+"\n").getBytes(StandardCharsets.US_ASCII);
        refused(duplicate,hash(duplicate),ID);
        byte[] crlf=new String(canonical,StandardCharsets.US_ASCII).replace("\n","\r\n").getBytes(StandardCharsets.US_ASCII); refused(crlf,hash(crlf),ID);
        System.out.println("PASS "+checks+" strict fixture parser checks; no Android/runtime execution");
    }
}
