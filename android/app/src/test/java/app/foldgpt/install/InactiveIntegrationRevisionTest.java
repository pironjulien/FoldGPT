package app.foldgpt.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.After;
import org.junit.Test;
import static org.junit.Assert.*;
import static app.foldgpt.install.RootfsTransactionTest.*;
import static app.foldgpt.install.InactiveIntegrationInstallerTest.*;

/** Versioned integration mechanics using real nonroot files and killed JVMs.
 * Fixtures are not working GPU/context programs and are never executed. */
public class InactiveIntegrationRevisionTest {
    final List<Path> owned=new ArrayList<>();
    Path temporary() throws IOException { Path path=Files.createTempDirectory("foldgpt-integration-revision-test-"); owned.add(path); return path; }
    @After public void cleanup() throws IOException { for(Path path:owned) removeFixture(path); }
    static byte[] contextContainer(String baseSha) throws IOException { return contextContainer(baseSha,InactiveIntegrationBundle.CONTEXT_CONTRACT); }
    static byte[] contextContainer(String baseSha,String contract) throws IOException {
        TreeMap<String,String> records=new TreeMap<>(); TreeMap<String,byte[]> payload=new TreeMap<>();
        for(var item:InactiveIntegrationBundle.FILES_WITH_CONTEXT.entrySet()) {
            byte[] data=(item.getKey().equals(InactiveIntegrationBundle.CONTEXT_CONTRACT_PATH)?contract:"fixture "+item.getKey()+"\n").getBytes(StandardCharsets.US_ASCII);
            payload.put(item.getKey(),data); records.put(item.getKey(),record("I","F",item.getValue(),data,item.getKey(),"-"));
        }
        InactiveIntegrationBundle.LINKS.forEach((path,target) -> records.put(path,"I\tL\t0777\t0\t-\t"+path+"\t"+target));
        for(String path:List.of(XKB,XKB+"/rules")) records.put(path,"V\tD\t0755\t0\t-\t"+path+"\t-");
        for(String name:List.of("base","evdev")) records.put(XKB+"/rules/"+name,record("V","F",0644,("fixture "+name+" rules\n").getBytes(StandardCharsets.US_ASCII),XKB+"/rules/"+name,"-"));
        records.put(XKB+"/rules/xorg","V\tL\t0777\t0\t-\t"+XKB+"/rules/xorg\tbase");
        String manifest=InactiveIntegrationBundle.FORMAT_WITH_CONTEXT+"\nbase\t"+baseSha+"\nguest\t"+"a".repeat(64)+"\ngpu\t"+InactiveIntegrationBundle.GPU_SHA+"\n"+String.join("\n",records.values())+"\n";
        return contextFrame(manifest,payload.values());
    }
    static byte[] contextFrame(String manifest,Collection<byte[]> payload) throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); DataOutputStream out=new DataOutputStream(bytes);
        out.write((InactiveIntegrationBundle.FORMAT_WITH_CONTEXT+"\n").getBytes(StandardCharsets.US_ASCII));
        byte[] encoded=manifest.getBytes(StandardCharsets.US_ASCII); out.writeInt(encoded.length); out.write(encoded);
        for(byte[] item:payload) out.write(item);
        return bytes.toByteArray();
    }
    @Test public void formatsSelectTwoExactIndependentFileAndContractSets() throws Exception {
        var legacy=parse(container("f".repeat(64)));
        var current=parse(contextContainer("f".repeat(64)));
        assertEquals(InactiveIntegrationBundle.FORMAT,legacy.format);
        assertEquals(InactiveIntegrationBundle.FORMAT_WITH_CONTEXT,current.format);
        assertEquals(20,InactiveIntegrationBundle.FILES.size()); assertEquals(22,InactiveIntegrationBundle.FILES_WITH_CONTEXT.size());
        assertFalse(legacy.entries.containsKey(InactiveIntegrationBundle.CONTEXT_HELPER));
        assertFalse(current.entries.containsKey(InactiveIntegrationBundle.CONTRACT_PATH));
        for(String path:List.of(InactiveIntegrationBundle.CONTEXT_HELPER,InactiveIntegrationBundle.CONTEXT_MANIFEST,InactiveIntegrationBundle.CONTEXT_CONTRACT_PATH))
            assertEquals(0644,current.entries.get(path).mode);
        for(byte[] data:List.of(container("f".repeat(64)),contextContainer("f".repeat(64)))) {
            // Relabel only the two version bytes. Preserve binary length and all
            // payload bytes, so rejection checks the other version's exact set.
            int version=InactiveIntegrationBundle.FORMAT.length()-1;
            byte[] changed=data.clone();
            changed[version]=(byte)(changed[version]=='1'?'2':'1');
            changed[version+2+4+version]=changed[version];
            fails(() -> parse(changed));
        }
        fails(() -> parse(contextContainer("f".repeat(64),InactiveIntegrationBundle.CONTRACT)));
    }
    @Test public void contextRecordsCannotBeMissingExtraWrongModeOrPairedWithAnotherHeader() throws Exception {
        byte[] data=contextContainer("f".repeat(64));
        int start=(InactiveIntegrationBundle.FORMAT_WITH_CONTEXT+"\n").length()+4;
        int size=java.nio.ByteBuffer.wrap(data,start-4,4).getInt();
        String manifest=new String(data,start,size,StandardCharsets.US_ASCII);
        byte[] payload=Arrays.copyOfRange(data,start+size,data.length);
        String helper=Arrays.stream(manifest.split("\n")).filter(line -> line.contains("\t"+InactiveIntegrationBundle.CONTEXT_HELPER+"\t")).findFirst().orElseThrow();
        for(String changed:List.of(manifest.replace(helper+"\n",""),manifest.replace(helper,helper.replace("I\tF\t0644","I\tF\t0700")),
                manifest.replace(InactiveIntegrationBundle.CONTEXT_MANIFEST,"usr/local/share/foldgpt/unlisted.json"),
                manifest.replace(InactiveIntegrationBundle.FORMAT_WITH_CONTEXT,InactiveIntegrationBundle.FORMAT)))
            fails(() -> parse(contextFrame(changed,List.of(payload))));
    }
    @Test public void newFilesInstallAndReopenWithoutExecutingContextOrChangingAGENTS() throws Exception {
        Fixture base=base(); Path files=temporary(); var bundle=parse(contextContainer(base.spec.sha256));
        String reportHash,reportIdentity,helperIdentity;
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            var first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            reportHash=first.reportSha256; reportIdentity=STORAGE.identity(first.report);
            helperIdentity=STORAGE.identity(root.resolve(InactiveIntegrationBundle.CONTEXT_HELPER));
            assertFalse(Files.exists(root.resolve("home/foldgpt/.codex")));
            String report=Files.readString(first.report);
            assertTrue(report.startsWith("foldgpt.inactive-integration-report.v2\n"));
            assertTrue(report.contains("agentContext\tfiles-installed-only\nmodelDelivery\tnot-verified\n"));
        }
        try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
            transaction.prepare(() -> { throw new IOException("Reopen cannot extract source"); });
            var second=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,bundle);
            assertEquals(reportHash,second.reportSha256); assertEquals(reportIdentity,STORAGE.identity(second.report));
            assertEquals(helperIdentity,STORAGE.identity(second.root.resolve(InactiveIntegrationBundle.CONTEXT_HELPER)));
            assertEquals(RootfsTransaction.State.PREPARED,transaction.state()); assertFalse(Files.exists(files.resolve("debian")));
        }
    }
    @Test public void bothCrossRevisionRetriesFailBeforeMutatingBoundLegacyOrNewEvidence() throws Exception {
        for(boolean legacyFirst:List.of(true,false)) {
            Fixture base=base(); Path files=temporary();
            var legacy=parse(container(base.spec.sha256)); var current=parse(contextContainer(base.spec.sha256));
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                Path root=prepare(transaction,base);
                var first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,legacyFirst?legacy:current);
                byte[] report=Files.readAllBytes(first.report); String reportIdentity=STORAGE.identity(first.report);
                Path intent=first.report.resolveSibling("intent.v1"); byte[] intentBytes=Files.readAllBytes(intent);
                fails(() -> InactiveIntegrationInstaller.install(transaction,STORAGE,ID,legacyFirst?current:legacy));
                assertArrayEquals(report,Files.readAllBytes(first.report)); assertArrayEquals(intentBytes,Files.readAllBytes(intent));
                assertEquals(reportIdentity,STORAGE.identity(first.report));
                assertEquals(legacyFirst,!Files.exists(root.resolve(InactiveIntegrationBundle.CONTEXT_HELPER)));
                assertEquals(legacyFirst,Files.exists(root.resolve(InactiveIntegrationBundle.CONTRACT_PATH)));
                assertEquals(first.reportSha256,InactiveIntegrationInstaller.install(transaction,STORAGE,ID,legacyFirst?legacy:current).reportSha256);
            }
        }
    }
    @Test public void newRevisionRecoversEveryDurableBoundaryAndEachContextFileAfterRealJvmDeath() throws Exception {
        for(String point:List.of("intent-pending","intent-written","directory-created","file-pending","file-written","link-written",
                "context-helper-written","context-manifest-written","report-pending","report-written")) {
            Path files=temporary(); Fixture base=base();
            Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-cp",System.getProperty("java.class.path"),
                InactiveIntegrationRevisionTest.class.getName(),files.toString(),point).redirectErrorStream(true).start();
            if(!child.waitFor(30,TimeUnit.SECONDS)) { child.destroyForcibly(); fail("Context integration child timed out at "+point); }
            assertEquals(point+": "+new String(child.getInputStream().readAllBytes(),StandardCharsets.UTF_8),71,child.exitValue());
            try(RootfsTransaction transaction=RootfsTransaction.open(files,base.spec,POSIX)) {
                transaction.prepare(() -> { throw new IOException("Recovery cannot extract source"); });
                var first=InactiveIntegrationInstaller.install(transaction,STORAGE,ID,parse(contextContainer(base.spec.sha256)));
                assertEquals(first.reportSha256,InactiveIntegrationInstaller.install(transaction,STORAGE,ID,parse(contextContainer(base.spec.sha256))).reportSha256);
                assertEquals(0644,STORAGE.mode(first.root.resolve(InactiveIntegrationBundle.CONTEXT_HELPER))&07777);
                assertEquals(0644,STORAGE.mode(first.root.resolve(InactiveIntegrationBundle.CONTEXT_MANIFEST))&07777);
                try(var paths=Files.walk(first.root)) { assertFalse(paths.anyMatch(path -> path.getFileName().toString().endsWith(".pending"))); }
            }
        }
    }
    public static void main(String[] args) throws Exception {
        Fixture base=base();
        try(RootfsTransaction transaction=RootfsTransaction.open(Path.of(args[0]),base.spec,POSIX)) {
            Path root=prepare(transaction,base);
            InactiveIntegrationInstaller.install(transaction,STORAGE,ID,parse(contextContainer(base.spec.sha256)),name -> {
                boolean contextPoint=name.equals("file-written") && (
                    args[1].equals("context-helper-written") && Files.exists(root.resolve(InactiveIntegrationBundle.CONTEXT_HELPER))
                    || args[1].equals("context-manifest-written") && Files.exists(root.resolve(InactiveIntegrationBundle.CONTEXT_MANIFEST)));
                if(name.equals(args[1]) || contextPoint) Runtime.getRuntime().halt(71);
            });
        }
        throw new AssertionError("Context crash checkpoint was not reached");
    }
}
