#!/usr/bin/env bash
# Real TLS/HTTP/cache process checks with an ephemeral truststore confined to this JVM.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
deps="$repo/downloads/install/transaction-deps"
while read -r hash name; do
    printf '%s  %s\n' "$hash" "$deps/$name" | sha256sum -c -
done <<'DEPS'
8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3 junit-4.13.2.jar
66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9 hamcrest-core-1.3.jar
DEPS
work=$(mktemp -d /var/tmp/foldgpt-https-java-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/classes" "$work/sources" "$work/test-tls"
cp "$repo/android/app/src/main/java/app/foldgpt/install/TrustedHttpsArtifact.java" "$work/sources/"
cp "$repo/android/app/src/main/java/app/foldgpt/install/AndroidTrustedHttpsArtifact.java" "$work/sources/"
cp "$repo/android/app/src/test/java/app/foldgpt/install/TrustedHttpsArtifactTest.java" "$work/sources/"
cp "$repo/tools/install/https-acquisition/run-jvm-tests.sh" "$work/sources/"
for name in server untrusted; do
    keytool -genkeypair -alias server -keyalg EC -groupname secp256r1 -validity 2 -dname "CN=localhost" \
        -ext SAN=dns:localhost -storetype PKCS12 -keystore "$work/test-tls/$name.p12" \
        -storepass foldgpt-test-only -keypass foldgpt-test-only > "$work/test-tls/$name-keytool.txt" 2>&1
done
keytool -exportcert -alias server -keystore "$work/test-tls/server.p12" -storepass foldgpt-test-only \
    -file "$work/test-tls/server.cer" > "$work/test-tls/export.txt" 2>&1
keytool -importcert -noprompt -alias ephemeral-test-server -file "$work/test-tls/server.cer" \
    -storetype PKCS12 -keystore "$work/test-tls/trust.p12" -storepass foldgpt-test-only > "$work/test-tls/import.txt" 2>&1
javac --add-modules jdk.httpserver -cp "$deps/*" -d "$work/classes" \
    "$work/sources/TrustedHttpsArtifact.java" "$work/sources/TrustedHttpsArtifactTest.java"
# Compile the actual adapter and its actual referenced project classes against
# the configured Android SDK, without changing Gradle or executing an APK.
android_jar=${FOLDGPT_ANDROID_JAR:-}
if [ -z "$android_jar" ]; then
    matching_lines() {
        if command -v rg >/dev/null; then rg --no-heading "$1"; else grep -E "$1"; fi
    }
    sdk_setting=$(tr -d '\r' < "$repo/android/local.properties" | matching_lines '^sdk.dir=')
    sdk_directory=${sdk_setting#sdk.dir=}
    if [[ "$sdk_directory" =~ ^[A-Za-z]:/ ]]; then sdk_directory=$(wslpath -u "$sdk_directory"); fi
    compile_sdk=$(tr -d '\r' < "$repo/android/app/build.gradle" | matching_lines '^    compileSdk [0-9]+$' | awk '{print $2}')
    for candidate in "$sdk_directory/platforms/android-$compile_sdk/android.jar" "$sdk_directory/platforms/android-$compile_sdk.0/android.jar"; do
        if [ -f "$candidate" ]; then android_jar=$candidate; break; fi
    done
fi
[ -f "$android_jar" ] || { printf 'Set FOLDGPT_ANDROID_JAR to the configured SDK android.jar.\n' >&2; exit 1; }
mkdir "$work/android-classes"
javac -cp "$android_jar:$deps/*" -sourcepath "$repo/android/app/src/main/java" -d "$work/android-classes" \
    "$work/sources/TrustedHttpsArtifact.java" "$work/sources/AndroidTrustedHttpsArtifact.java" \
    > "$work/android-compile.txt" 2>&1
sha256sum "$android_jar" > "$work/android-sdk-sha256.txt"
java -version 2> "$work/java-version.txt"
uname -a > "$work/kernel.txt"
if [ "$(id -u)" = 0 ]; then
    run=(runuser -u nobody --)
else
    run=()
fi
"${run[@]}" id > "$work/test-identity.txt"
"${run[@]}" java --add-modules jdk.httpserver \
    -Djavax.net.ssl.trustStore="$work/test-tls/trust.p12" -Djavax.net.ssl.trustStorePassword=foldgpt-test-only \
    -Dfoldgpt.test.keyStore="$work/test-tls/server.p12" -Dfoldgpt.test.untrustedKeyStore="$work/test-tls/untrusted.p12" \
    -cp "$work/classes:$deps/*" org.junit.runner.JUnitCore app.foldgpt.install.TrustedHttpsArtifactTest \
    | tee "$work/junit-result.txt"
(cd "$work" && sha256sum sources/* > SHA256SUMS)
destination="$repo/downloads/install/https-acquisition/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
cp -a "$work" "$destination"
printf 'HTTPS acquisition evidence: %s\nNo Android execution or public network download performed.\n' "$destination"
