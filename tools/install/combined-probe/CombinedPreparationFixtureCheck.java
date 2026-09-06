package app.foldgpt.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
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
        if(parsed.number("packageDeadlineMillis")!=900000 || parsed.hasIntegration()) throw new AssertionError("Legacy numeric field or scope changed"); checks++;
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
        Map<String,String> integrated=new TreeMap<>(good);
        integrated.put("schema","foldgpt.combined-preparation-fixture.v2");
        integrated.put("integrationSha256",HASH); integrated.put("integrationBytes","41116761"); integrated.put("integrationManifestSha256",HASH);
        byte[] release=bytes(integrated);
        CombinedPreparationFixture nativeFixture=CombinedPreparationFixture.parse(release,hash(release),ID);
        if(!nativeFixture.hasIntegration() || nativeFixture.number("integrationBytes")!=41116761) throw new AssertionError("Native fixture scope or bytes differ"); checks++;
        for(String key:CombinedPreparationFixture.INTEGRATION_KEYS) {
            Map<String,String> changed=new TreeMap<>(integrated); changed.remove(key); byte[] value=bytes(changed); refused(value,hash(value),ID);
        }
        for(var change:List.of(Map.entry("schema","foldgpt.combined-preparation-fixture.v1"),Map.entry("schema","foldgpt.combined-preparation-fixture.v3"),
                Map.entry("integrationSha256","x"),Map.entry("integrationManifestSha256","-"),Map.entry("integrationBytes","0"),
                Map.entry("integrationBytes","041116761"),Map.entry("integrationBytes","67108865"),Map.entry("integrationBytes","9223372036854775808"),
                Map.entry("integrationPath","/tmp/untrusted"),Map.entry("command","/bin/sh"))) {
            Map<String,String> changed=new TreeMap<>(integrated); changed.put(change.getKey(),change.getValue()); byte[] value=bytes(changed); refused(value,hash(value),ID);
        }
        for(String key:List.of("integrationSha256","integrationBytes","integrationManifestSha256")) {
            Map<String,String> changed=new TreeMap<>(good); changed.put(key,integrated.get(key)); byte[] value=bytes(changed); refused(value,hash(value),ID);
        }
        Map<String,String> wrongScope=new TreeMap<>(good); wrongScope.put("schema","foldgpt.combined-preparation-fixture.v2");
        byte[] value=bytes(wrongScope); refused(value,hash(value),ID);
        if(args.length!=0) {
            if(args.length!=3) throw new IllegalArgumentException("Optional arguments: actual fixture path descriptor SHA fixture ID");
            CombinedPreparationFixture actual=CombinedPreparationFixture.parse(Files.readAllBytes(Path.of(args[0])),args[1],args[2]);
            System.out.println("ACTUAL_FIXTURE="+actual.get("fixture")+" SCHEMA="+actual.get("schema")+" INTEGRATION="+actual.hasIntegration());
            checks++;
        }
        System.out.println("PASS "+checks+" strict fixture parser checks; no Android/runtime execution");
    }
}
