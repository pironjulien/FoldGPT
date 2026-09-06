package app.foldgpt;

import android.content.Context;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;

/** Bounded extraction of APK-owned debug probe inputs into a new private root. */
final class NativeProbeFiles {
    private final Context context;
    private long bytes;
    private int files;
    NativeProbeFiles(Context context) { this.context=context; }

    void sources(String prefix,Path root,String[] names) throws IOException {
        for(String name:names) {
            Path target=root.resolve(name);
            Files.createDirectories(target.getParent());
            try(InputStream input=context.getAssets().open(prefix+"/"+name)) {
                byte[] content=input.readNBytes(1048577);
                if(content.length>1048576) throw new IOException("Probe source exceeds its bound");
                Files.write(target,content,StandardOpenOption.CREATE_NEW);
            }
        }
    }
    void python(Path root) throws IOException { copy("native-python",root); }

    private void copy(String source,Path target) throws IOException {
        String[] names=context.getAssets().list(source);
        if(names==null) throw new IOException("Missing Android Python assets");
        if(names.length>0) {
            Files.createDirectory(target);
            for(String name:names) {
                if(name.isEmpty() || name.equals(".") || name.equals("..") || name.contains("/") || name.contains("\\"))
                    throw new IOException("Invalid asset component");
                copy(source+"/"+name,target.resolve(name));
            }
        } else {
            if(++files>20000) throw new IOException("Python asset count exceeds its bound");
            try(InputStream input=context.getAssets().open(source);
                    var output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)) {
                byte[] buffer=new byte[65536]; int count;
                while((count=input.read(buffer))!=-1) {
                    bytes+=count;
                    if(bytes>256L*1024*1024) throw new IOException("Python asset bytes exceed their bound");
                    output.write(buffer,0,count);
                }
            }
        }
    }
}
