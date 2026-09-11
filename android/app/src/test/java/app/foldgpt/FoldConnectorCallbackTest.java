package app.foldgpt;

import org.junit.Test;
import static org.junit.Assert.*;

public class FoldConnectorCallbackTest {
    private static final String BASE = "codex://connector/oauth_callback";

    @Test public void preservesOpaqueSuccessAndErrorParametersForOfficialValidation() {
        for (String uri : new String[] {
                BASE, BASE + "?code=fixture&state=fixture%2F%3D&returnTo=%2Fwelcome",
                BASE + "?error=access_denied&error_description=User%20cancelled",
                BASE + "?claim=eyJmaXh0dXJlIjp0cnVlfQ&unknown=future%252Fvalue",
                BASE + "?state=fixture&code=%24%28printf%20fixture%29;literal=--eval"}) {
            // Query contents remain one argument. They are not commands or
            // transport assertions that a claim is valid.
            assertEquals(uri, FoldConnectorCallback.validate(uri));
        }
    }

    @Test public void rejectsOtherRoutesSchemesAuthoritiesAndArguments() {
        for (String uri : new String[] {null, "", "--eval", "/tmp/fixture", "codex://threads/new?prompt=fixture",
                "codex://launch", "codex-dev://connector/oauth_callback", "https://connector/oauth_callback",
                "codex://connector/oauth_callback/extra", "codex://connector//oauth_callback",
                "codex://connector/%6fauth_callback", "codex://connector/../oauth_callback",
                "codex://user@connector/oauth_callback", "codex://connector:1/oauth_callback",
                "codex://connector.evil/oauth_callback", "codex://%63onnector/oauth_callback",
                "codex://CONNECTOR/oauth_callback", "CODEX://connector/oauth_callback",
                BASE + "#fragment", BASE + "?code=fixture#", " " + BASE,
                BASE + "?code=fixture --eval arbitrary"}) reject(uri);
    }

    @Test public void rejectsMalformedEncodingControlsAndOversizedCallbacksWithoutEchoingInput() {
        for (String suffix : new String[] {"\n", "\u0000", "\ud800", "\\fixture", "%0A", "%00", "%7f",
                "%C2%85", "%E2%80%AE", "%5c", "%", "%zz", "%E9", "%ED%A0%80"}) reject(BASE + "?code=" + suffix);
        reject(BASE + "?code=" + "a".repeat(FoldConnectorCallback.MAX_URI_BYTES));
        reject(BASE + "?code=" + "é".repeat(2000));
    }

    private static void reject(String uri) {
        try { FoldConnectorCallback.validate(uri); fail("Unexpected callback acceptance"); }
        catch (IllegalArgumentException expected) { assertEquals("Invalid connector callback", expected.getMessage()); }
    }
}
