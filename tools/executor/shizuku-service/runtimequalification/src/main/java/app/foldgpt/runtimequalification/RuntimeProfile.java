package app.foldgpt.runtimequalification;

/** Two fixed APK-owned identities; no Intent or RPC selects an alternate base. */
final class RuntimeProfile {
    static final String PACKAGE = "app.foldgpt.runtimequalification.v1";
    static final String BASE = "/data/local/tmp/foldgpt-bionic-runtime-qualification-v1";
    private static final RuntimeProfile V1 = new RuntimeProfile(1, PACKAGE, BASE);
    private static final RuntimeProfile V2 = new RuntimeProfile(2, "app.foldgpt.runtimequalification.v2",
        "/data/local/tmp/foldgpt-bionic-runtime-qualification-v2");
    final String packageName, base, reportDirectory, runAction, serviceTag, processSuffix;
    final int serviceVersion, diagnosticVersion;
    private RuntimeProfile(int version, String name, String nativeBase) {
        packageName = name; base = nativeBase; diagnosticVersion = serviceVersion = version;
        reportDirectory = version == 1 ? "runtime-v1" : "runtime-v2";
        runAction = version == 1 ? ".RUNTIME_RUN_FIXED_V1" : ".RUNTIME_RUN_FIXED_V2";
        serviceTag = version == 1 ? "foldgpt-runtime-qualification-v1" : "foldgpt-runtime-qualification-v2";
        processSuffix = version == 1 ? "runtimequalificationv1" : "runtimequalificationv2";
    }
    static RuntimeProfile forPackage(String name) {
        if (V1.packageName.equals(name)) return V1;
        if (V2.packageName.equals(name)) return V2;
        throw new SecurityException("Unexpected runtime qualification application");
    }
}
