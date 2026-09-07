package app.foldgpt.kernelqualification;

/** APK/application identity selects one fixed diagnostic, never Intent extras. */
final class QualificationProfile {
    static final String V11_PACKAGE = "app.foldgpt.kernelqualification.v11";
    final String packageName, base, reportDirectory, runAction, serviceTag, processSuffix;
    final int diagnosticVersion, serviceVersion;
    final boolean independent;

    private QualificationProfile(String packageName, String base, String reportDirectory,
            String runAction, String serviceTag, String processSuffix, int diagnosticVersion,
            int serviceVersion, boolean independent) {
        this.packageName = packageName; this.base = base; this.reportDirectory = reportDirectory;
        this.runAction = runAction; this.serviceTag = serviceTag; this.processSuffix = processSuffix;
        this.diagnosticVersion = diagnosticVersion; this.serviceVersion = serviceVersion;
        this.independent = independent;
    }

    static QualificationProfile forPackage(String packageName) {
        if (V11_PACKAGE.equals(packageName)) {
            return new QualificationProfile(packageName,
                "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3", "kernel-v11",
                ".KERNEL_RUN_FIXED_V11", "foldgpt-kernel-qualification-v11", "kernelqualificationv11", 11, 11, true);
        }
        if ("app.foldgpt.shizukuprobe".equals(packageName)) {
            return new QualificationProfile(packageName,
                "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2", "kernel-v6",
                ".KERNEL_RUN_FIXED_V10", "foldgpt-kernel-qualification-v6", "kernelqualification", 10, 6, false);
        }
        throw new SecurityException("Unknown fixed qualification application identity");
    }
}
