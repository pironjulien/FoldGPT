package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class DeploymentOriginTest {
    @Test public void applicationOriginRequiresVersionTwoAndExactMarker() throws Exception {
        assertTrue(Deployment.applicationOrigin(new JSONObject()
                .put("schema", "foldgpt.native.deployment.v2").put("launchOrigin", "android-app")));
        for (Object origin : new Object[] {"run-as", "shell", true, JSONObject.NULL, "android-app "}) {
            JSONObject config = new JSONObject().put("schema", "foldgpt.native.deployment.v2").put("launchOrigin", origin);
            assertThrows(SecurityException.class, () -> Deployment.applicationOrigin(config));
        }
        assertThrows(org.json.JSONException.class, () -> Deployment.applicationOrigin(
                new JSONObject().put("schema", "foldgpt.native.deployment.v2")));
    }
    @Test public void legacyDeploymentRemainsSeparateAndRejectsMixedOrigin() throws Exception {
        for (String schema : new String[] {"foldgpt.native.deployment.v1", "foldgpt.shizuku.deployment.v1"}) {
            JSONObject config = new JSONObject().put("schema", schema);
            assertFalse(Deployment.applicationOrigin(config));
            config.put("launchOrigin", "android-app");
            assertThrows(SecurityException.class, () -> Deployment.applicationOrigin(config));
        }
        assertThrows(SecurityException.class, () -> Deployment.applicationOrigin(
                new JSONObject().put("schema", "foldgpt.native.deployment.v3").put("launchOrigin", "android-app")));
    }
}
