package app.foldgpt;

import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Pure URI/request validation. Error messages deliberately contain no input. */
final class FoldWebUri {
    static final int MAX_URL_BYTES = 8192;
    static final int MAX_REQUEST_BYTES = 16384;
    private FoldWebUri() { }

    static String validate(String value) {
        if (value == null || value.isEmpty()) throw invalid();
        try {
            if (StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                    .encode(java.nio.CharBuffer.wrap(value)).remaining() > MAX_URL_BYTES) throw invalid();
            rejectControls(value, true);
            for (int i = 0; i < value.length(); i++) {
                if (value.charAt(i) != '%') continue;
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                while (i < value.length() && value.charAt(i) == '%') {
                    if (i + 2 >= value.length()) throw invalid();
                    int high = hex(value.charAt(i + 1));
                    int low = hex(value.charAt(i + 2));
                    if (high < 0 || low < 0) throw invalid();
                    bytes.write((high << 4) | low);
                    i += 3;
                }
                rejectControls(decode(bytes.toByteArray()), false);
                i--;
            }
            URI uri = new URI(value).parseServerAuthority();
            String scheme = uri.getScheme();
            if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))
                    || uri.isOpaque() || uri.getRawUserInfo() != null || uri.getHost() == null
                    || uri.getRawAuthority() == null || uri.getRawAuthority().contains("%")
                    || uri.getRawAuthority().endsWith(":")) throw invalid();
            String host = uri.getHost();
            for (int i = 0; i < host.length(); i++) if (host.charAt(i) > 127) throw invalid();
            if (uri.getPort() != -1 && (uri.getPort() < 1 || uri.getPort() > 65535)) throw invalid();
            if (!host.startsWith("[")) {
                String dns = host.endsWith(".") ? host.substring(0, host.length() - 1) : host;
                if (dns.isEmpty() || dns.length() > 253) throw invalid();
                for (String label : dns.split("\\.", -1)) {
                    if (!label.matches("[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")) throw invalid();
                }
                // Avoid browser-dependent short/octal/hex IPv4 interpretations.
                String last = dns.substring(dns.lastIndexOf('.') + 1);
                if (last.matches("[0-9]+") || last.matches("(?i)0x[0-9a-f]+")) {
                    String[] parts = dns.split("\\.");
                    if (parts.length != 4) throw invalid();
                    for (String part : parts) {
                        if (!part.matches("0|[1-9][0-9]{0,2}") || Integer.parseInt(part) > 255) throw invalid();
                    }
                }
            }
            String ascii = uri.toASCIIString();
            if (ascii.length() > MAX_URL_BYTES) throw invalid();
            return scheme.toLowerCase(Locale.ROOT) + ascii.substring(scheme.length());
        } catch (URISyntaxException | CharacterCodingException error) {
            throw invalid();
        }
    }

    private static void rejectControls(String value, boolean raw) {
        value.codePoints().forEach(point -> {
            if (Character.isISOControl(point) || Character.getType(point) == Character.FORMAT
                    || point == '\\' || (raw && (Character.isWhitespace(point)
                    || Character.isSpaceChar(point) || "\"<>^`{|}".indexOf(point) >= 0))) throw invalid();
        });
    }

    private static String decode(byte[] bytes) throws CharacterCodingException {
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
    }

    private static int hex(char value) {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'A' && value <= 'F') return value - 'A' + 10;
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        return -1;
    }

    static String parseRequest(byte[] bytes) {
        if (bytes.length > MAX_REQUEST_BYTES) throw invalid();
        try {
            Json request = new Json(decode(bytes));
            request.take('{');
            if (!request.string().equals("url")) throw invalid();
            request.take(':');
            String url = request.string();
            request.take('}');
            request.space();
            if (request.offset != request.text.length()) throw invalid();
            return validate(url);
        } catch (CharacterCodingException error) { throw invalid(); }
    }

    // One exact JSON field; reject duplicates, permissive JSON syntax and tails.
    private static final class Json {
        final String text;
        int offset;
        Json(String text) { this.text = text; }
        void space() {
            while (offset < text.length() && " \r\n\t".indexOf(text.charAt(offset)) >= 0) offset++;
        }
        void take(char wanted) {
            space();
            if (offset >= text.length() || text.charAt(offset++) != wanted) throw invalid();
        }
        String string() {
            take('"');
            StringBuilder result = new StringBuilder();
            while (offset < text.length()) {
                char next = text.charAt(offset++);
                if (next == '"') return result.toString();
                if (next < 32) throw invalid();
                if (next == '\\') {
                    if (offset >= text.length()) throw invalid();
                    next = text.charAt(offset++);
                    switch (next) {
                        case '"': case '\\': case '/': break;
                        case 'b': next = '\b'; break;
                        case 'f': next = '\f'; break;
                        case 'n': next = '\n'; break;
                        case 'r': next = '\r'; break;
                        case 't': next = '\t'; break;
                        case 'u':
                            if (offset + 4 > text.length()) throw invalid();
                            int code = 0;
                            for (int i = 0; i < 4; i++) {
                                int digit = hex(text.charAt(offset++));
                                if (digit < 0) throw invalid();
                                code = (code << 4) | digit;
                            }
                            next = (char) code;
                            break;
                        default: throw invalid();
                    }
                }
                result.append(next);
            }
            throw invalid();
        }
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("Invalid HTTP(S) URL or bridge request");
    }
}
