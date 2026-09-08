package app.foldgpt.shizukuexec;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

/** The persisted contract is tested here; actual provider access requires Android. */
public final class AndroidBootEpochTest {
    @Test public void epochSurvivesRealJsonSerializationWithoutChangingItsSource() throws Exception {
        for (int count : new int[] {0, 8, Integer.MAX_VALUE}) {
            JSONObject value = new JSONObject(AndroidBootEpoch.metadata(count).toString());
            assertEquals(count, AndroidBootEpoch.readCount(value));
            assertEquals("android.provider.Settings.Global.BOOT_COUNT", value.getString("source"));
            AndroidBootEpoch.requireCurrent(value, count);
        }
        assertThrows(SecurityException.class, () -> AndroidBootEpoch.metadata(-1));
    }

    @Test public void rejectsCoercedMissingForeignAndAdditionalEpochFields() throws Exception {
        for (Object count : new Object[] {"8", 8.0, true, JSONObject.NULL, -1, 2147483648L}) {
            JSONObject value = AndroidBootEpoch.metadata(8).put("bootCount", count);
            assertThrows(SecurityException.class, () -> AndroidBootEpoch.readCount(value));
        }
        JSONObject additional = AndroidBootEpoch.metadata(8).put("allowRecovery", true);
        assertThrows(SecurityException.class, () -> AndroidBootEpoch.readCount(additional));
        JSONObject foreign = AndroidBootEpoch.metadata(8).put("source", "model");
        assertThrows(SecurityException.class, () -> AndroidBootEpoch.readCount(foreign));
        JSONObject schema = AndroidBootEpoch.metadata(8).put("schema", "foldgpt.android-boot-epoch.v2");
        assertThrows(SecurityException.class, () -> AndroidBootEpoch.readCount(schema));
        JSONObject missing = AndroidBootEpoch.metadata(8);
        missing.remove("bootCount");
        assertThrows(SecurityException.class, () -> AndroidBootEpoch.readCount(missing));
    }

    @Test public void aLaunchMustMatchTheFreshProviderReadExactly() throws Exception {
        JSONObject launch = AndroidBootEpoch.metadata(8);
        for (int observed : new int[] {-1, 0, 7, 9, Integer.MAX_VALUE})
            assertThrows(SecurityException.class, () -> AndroidBootEpoch.requireCurrent(launch, observed));
        // This establishes only freshness of input, never cleanup of a prior
        // owner. Same-boot process recovery is a separate owner-side decision.
        AndroidBootEpoch.requireCurrent(launch, 8);
    }
}
