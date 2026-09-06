package app.foldgpt.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Strict, hash-bound debug fixture data. Contains no Android/host path or command. */
final class CombinedPreparationFixture {
    static final Set<String> KEYS=Set.of("schema","fixture","archiveSha256","archiveBytes","archivePayloadBytes",
        "archiveTarBytes","archiveMembers","clientVersion","clientSha256","clientBytes","clientTarBytes","clientMembers",
        "initializerSha256","supervisorSha256","verifierSha256","installerSha256","packageDeadlineMillis","totalDeadlineMillis");
    private final Map<String,String> values;
    private CombinedPreparationFixture(Map<String,String> values) { this.values=Map.copyOf(values); }
    static boolean validId(String value) { return value!=null && value.matches("[0-9a-f]{32}"); }
    static CombinedPreparationFixture parse(byte[] bytes,String expectedHash,String expectedId) throws IOException {
        if(!validId(expectedId) || expectedHash==null || !expectedHash.matches("[0-9a-f]{64}") || bytes.length>16384
                || !sha256(bytes).equals(expectedHash)) throw new IOException("Unbound combined fixture");
        String text=StandardCharsets.US_ASCII.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
        if(!text.endsWith("\n") || text.indexOf('\r')>=0 || text.indexOf('\0')>=0) throw new IOException("Invalid fixture encoding");
        Map<String,String> values=new TreeMap<>();
        for(String line:text.split("\n")) {
            int at=line.indexOf('=');
            if(at<=0 || at==line.length()-1 || values.put(line.substring(0,at),line.substring(at+1))!=null)
                throw new IOException("Invalid fixture fields");
        }
        if(!values.keySet().equals(KEYS) || !values.get("schema").equals("foldgpt.combined-preparation-fixture.v1")
                || !values.get("fixture").equals(expectedId) || !values.get("clientVersion").matches("[0-9][A-Za-z0-9.+:~\\-]*"))
            throw new IOException("Unsupported combined fixture");
        CombinedPreparationFixture fixture=new CombinedPreparationFixture(values);
        for(String key:KEYS) if(key.endsWith("Sha256") && !fixture.get(key).matches("[0-9a-f]{64}"))
            throw new IOException("Invalid fixture digest");
        for(String key:List.of("archiveBytes","archivePayloadBytes","archiveTarBytes","archiveMembers",
                "clientBytes","clientTarBytes","clientMembers","packageDeadlineMillis","totalDeadlineMillis")) fixture.number(key);
        if(fixture.number("archiveMembers")>Integer.MAX_VALUE || fixture.number("clientMembers")>Integer.MAX_VALUE
                || fixture.number("packageDeadlineMillis")>Integer.MAX_VALUE || fixture.number("totalDeadlineMillis")>43200000L
                || fixture.number("totalDeadlineMillis")<2*fixture.number("packageDeadlineMillis")+120000L)
            throw new IOException("Unbounded fixture deadline or member count");
        return fixture;
    }
    String get(String key) { return values.get(key); }
    long number(String key) throws IOException {
        String value=values.get(key);
        if(value==null || !value.matches("[1-9][0-9]{0,18}")) throw new IOException("Invalid fixture numeric field");
        try { return Long.parseLong(value); } catch(NumberFormatException error) { throw new IOException("Fixture numeric overflow",error); }
    }
    private static String sha256(byte[] bytes) {
        try {
            StringBuilder value=new StringBuilder();
            for(byte item:MessageDigest.getInstance("SHA-256").digest(bytes)) value.append(String.format(Locale.ROOT,"%02x",item&255));
            return value.toString();
        } catch(java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
