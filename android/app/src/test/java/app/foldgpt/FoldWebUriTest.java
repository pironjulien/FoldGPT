package app.foldgpt;

import java.nio.charset.StandardCharsets;
import org.junit.Test;
import static org.junit.Assert.*;

public class FoldWebUriTest {
    @Test public void acceptsOrdinaryWebUrisWithoutChangingEscapesOrQuery() {
        for (String value : new String[] {
                "https://example.com", "http://localhost:1455/auth/callback?code=not-a-secret&state=fixture",
                "https://127.0.0.1:443/a%20b", "https://[::1]:1455/", "https://xn--bcher-kva.example/",
                "https://example.com./a#anchor", "https://example.com/auth?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fx",
                "https://example.com/%F0%9F%93%96", "https://example.com/a?encoded=%252F"}) {
            assertEquals(value, FoldWebUri.validate(value));
        }
        assertEquals("https://example.com/%C3%A9", FoldWebUri.validate("HTTPS://example.com/é"));
    }

    @Test public void rejectsUnsafeAndAmbiguousHostsAndAuthorities() {
        for (String value : new String[] {
                "file:///etc/passwd", "intent://example.com", "javascript:alert(1)", "//example.com/x",
                "https:///x", "https://", "https://u:p@example.com", "https://@example.com",
                "https://example.com@evil.test", "https://%65xample.com/", "https://x%40y/",
                "https://bücher.example/", "https://a_b.example/", "https://-bad.example/",
                "https://bad-.example/", "https://a..b/", "https://example.com:/", "https://example.com:0/",
                "https://example.com:65536/", "https://example.com:+80/", "https://example.com:no/",
                "https://[broken]/", "https://[fe80::1%25wlan0]/", "http://127.1/", "http://0177.0.0.1/",
                "http://2130706433/", "http://0x7f000001/", "http://999.1.1.1/", "https://example.123/"}) reject(value);
    }

    @Test public void rejectsRawAndEncodedControlsMalformedUnicodeAndEscapes() {
        for (String value : new String[] {
                " https://example.com", "https://example.com/ ", "https://example.com/\n",
                "https://example.com/\u0000", "https://example.com/\u0085", "https://example.com/\u202e",
                "https://example.com/\\evil", "https://example.com/%0a", "https://example.com/%0D",
                "https://example.com/%00", "https://example.com/%7f", "https://example.com/%C2%85",
                "https://example.com/%E2%80%AE", "https://example.com/%5c", "https://example.com/%",
                "https://example.com/%gg", "https://example.com/%C0%AF", "https://example.com/%ED%A0%80",
                "https://example.com/%E9", "https://example.com/\ud800", "https://example.com/{bad}"}) reject(value);
        reject("https://example.com/" + "a".repeat(FoldWebUri.MAX_URL_BYTES));
        reject("https://example.com/" + "é".repeat(1500)); // ASCII transport expansion also bounded.
    }

    @Test public void strictSingleFieldJsonPreservesOnlyTheUrl() {
        assertEquals("https://example.com/x", FoldWebUri.parseRequest(
                " { \"url\" : \"https:\\/\\/example.com/x\" } ".getBytes(StandardCharsets.UTF_8)));
        for (String request : new String[] {"{'url':'https://example.com'}", "{url:\"https://example.com\"}",
                "{\"url\":\"https://example.com\",\"url\":\"https://evil.test\"}",
                "{\"url\":\"https://example.com\",\"other\":true}", "{\"url\":true}",
                "{\"url\":\"https://example.com\"}{}", "{\"url\":\"https://example.com\",}",
                "{\"url\":\"\\u００６８ttps://example.com\"}",
                "{\"url\":\"https://example.com/\\u000a\"}", "{\"url\":\"https://example.com/\\ud800\"}"}) {
            try { FoldWebUri.parseRequest(request.getBytes(StandardCharsets.UTF_8)); fail("Invalid request accepted"); }
            catch (IllegalArgumentException expected) { assertFalse(expected.getMessage().contains("example")); }
        }
        try { FoldWebUri.parseRequest(new byte[] {(byte) 0xff}); fail("Invalid UTF-8 accepted"); }
        catch (IllegalArgumentException expected) { }
    }

    private static void reject(String value) {
        try { FoldWebUri.validate(value); fail("Invalid URL accepted: " + value); }
        catch (IllegalArgumentException expected) { assertFalse(expected.getMessage().contains("example")); }
    }
}
