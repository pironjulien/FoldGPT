package app.foldgpt;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.io.ByteArrayOutputStream;

/** Transport validation only. The official client owns OAuth claim/state checks. */
public final class FoldConnectorCallback {
    public static final int MAX_URI_BYTES = 8192;
    private FoldConnectorCallback() { }

    public static String validate(String value) {
        if (value == null || value.isEmpty()) throw invalid();
        try {
            if (StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                    .encode(CharBuffer.wrap(value)).remaining() > MAX_URI_BYTES) throw invalid();
            rejectControls(value);
            URI uri = new URI(value).parseServerAuthority();
            if (!"codex".equals(uri.getScheme()) || !"connector".equals(uri.getRawAuthority())
                    || !"/oauth_callback".equals(uri.getRawPath()) || uri.isOpaque()
                    || uri.getRawUserInfo() != null || uri.getPort() != -1
                    || uri.getRawFragment() != null) throw invalid();
            // Reject malformed encoded text and controls without decoding or
            // rewriting opaque OAuth query values on their way to the client.
            for (int i = 0; i < value.length(); i++) {
                if (value.charAt(i) != '%') continue;
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                while (i < value.length() && value.charAt(i) == '%') {
                    if (i + 2 >= value.length()) throw invalid();
                    int high = Character.digit(value.charAt(i + 1), 16);
                    int low = Character.digit(value.charAt(i + 2), 16);
                    if (high < 0 || low < 0) throw invalid();
                    bytes.write((high << 4) | low);
                    i += 3;
                }
                rejectControls(StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString());
                i--;
            }
            String ascii = uri.toASCIIString();
            if (ascii.length() > MAX_URI_BYTES) throw invalid();
            return ascii;
        } catch (URISyntaxException | CharacterCodingException error) { throw invalid(); }
    }

    private static void rejectControls(String text) {
        text.codePoints().forEach(point -> {
            if (Character.isISOControl(point) || Character.getType(point) == Character.FORMAT || point == '\\') throw invalid();
        });
    }

    private static IllegalArgumentException invalid() {
        // Never place the callback, authorization code or state in an exception.
        return new IllegalArgumentException("Invalid connector callback");
    }
}
