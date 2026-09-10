package app.foldgpt.shizukuexec;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class AndroidProcessPopulationTest {
    private JSONObject row(int pid, String name) throws Exception {
        return new JSONObject().put("pid", pid).put("startTimeTicks", 1234L).put("processName", name);
    }
    private JSONObject population(JSONObject... rows) throws Exception {
        return new JSONObject().put("schema", "foldgpt.android-process-population.v1")
                .put("source", "android.app.ActivityManager.getRunningAppProcesses").put("processes", new JSONArray(rows));
    }
    @Test public void pinsStartTimeDespiteParenthesesAndSpacesInComm() {
        String tail = "S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 123456 20";
        assertEquals(123456, AndroidProcessPopulation.startTime("42 (name ) (test) " + tail, 42));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.startTime("42 (ok) " + tail, 43));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.startTime("42 (ok) S 1 2", 42));
    }
    @Test public void onlyExactBoundedJavaPopulationIsAccepted() throws Exception {
        AndroidProcessPopulation.validate(population(row(42, "app.foldgpt:runtime")));
        AndroidProcessPopulation.validate(new JSONObject(population(row(42, "app.foldgpt:runtime"), row(43, "app.foldgpt")).toString()));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population()));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population(row(43, "app.foldgpt"))));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population(row(42, "app.foldgpt:runtime"), row(42, "app.foldgpt"))));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population(row(42, "app.foldgpt:runtime"), row(43, "python"))));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population(row(42, "app.foldgpt:runtime"), row(43, "app.foldgpt:runtime"))));
    }
    @Test public void rejectsCoercionsAndAdditionalAuthority() throws Exception {
        for (Object ticks : new Object[] {"1234", 1.0, true, -1L, 0L}) {
            JSONObject value = population(row(42, "app.foldgpt:runtime").put("startTimeTicks", ticks));
            assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(value));
        }
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(population(row(42, "app.foldgpt:runtime").put("allowChildren", true))));
    }
    @Test public void requiresTheExactOsSourceAndKernelPidRange() throws Exception {
        JSONObject missing = population(row(42, "app.foldgpt:runtime"));
        missing.remove("source");
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(missing));
        assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(
                population(row(42, "app.foldgpt:runtime")).put("source", "model")));
        for (Object pid : new Object[] {"42", 42.0, true, 0, -1, 4 * 1024 * 1024, Integer.MAX_VALUE}) {
            JSONObject value = population(row(42, "app.foldgpt:runtime").put("pid", pid));
            assertThrows(SecurityException.class, () -> AndroidProcessPopulation.validate(value));
        }
        AndroidProcessPopulation.validate(population(row(4 * 1024 * 1024 - 1, "app.foldgpt:runtime")));
    }
}
