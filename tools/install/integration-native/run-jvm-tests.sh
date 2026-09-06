#!/usr/bin/env bash
# Native filesystem tests on Linux only. Never contacts or modifies Android.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
deps="$repo/downloads/install/transaction-deps"
while read -r hash name; do
  printf '%s  %s\n' "$hash" "$deps/$name" | sha256sum -c -
done <<'DEPENDENCIES'
e1522945218456f3649a39bc4afd70ce4bd466221519dba7d378f2141a4642ca commons-compress-1.28.0.jar
df90bba0fe3cb586b7f164e78fe8f8f4da3f2dd5c27fa645f888100ccc25dd72 commons-io-2.20.0.jar
4eeeae8d20c078abb64b015ec158add383ac581571cddc45c68f0c9ae0230720 commons-lang3-3.18.0.jar
5c3881e4f556855e9c532927ee0c9dfde94cc66760d5805c031a59887070af5f commons-codec-1.19.0.jar
8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3 junit-4.13.2.jar
66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9 hamcrest-core-1.3.jar
DEPENDENCIES
work=$(mktemp -d /var/tmp/foldgpt-integration-java-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/classes" "$work/sources"
for name in RootfsExtractor RootfsTransaction ProotHardlinkStorage GuestIdentity GuestAccountProvisioner InactiveIntegrationBundle InactiveIntegrationInstaller; do
  cp "$repo/android/app/src/main/java/app/foldgpt/install/$name.java" "$work/sources/"
done
for name in RootfsTransactionTest InactiveIntegrationInstallerTest InactiveIntegrationRevisionTest InactiveIntegrationRealArchiveCheck; do
  cp "$repo/android/app/src/test/java/app/foldgpt/install/$name.java" "$work/sources/"
done
cp "$repo/tools/install/inactive_integration_bundle.py" "$repo/tools/install/integration-native/run-jvm-tests.sh" "$work/sources/"
javac -cp "$deps/*" -d "$work/classes" "$work/sources/"*.java
java -version 2> "$work/java-version.txt"
uname -a > "$work/kernel.txt"
if [ "$(id -u)" = 0 ]; then
  /usr/sbin/runuser -u nobody -- id > "$work/identity.txt"
  /usr/sbin/runuser -u nobody -- java -cp "$work/classes:$deps/*" org.junit.runner.JUnitCore app.foldgpt.install.InactiveIntegrationInstallerTest app.foldgpt.install.InactiveIntegrationRevisionTest | tee "$work/junit-result.txt"
else
  id > "$work/identity.txt"
  java -cp "$work/classes:$deps/*" org.junit.runner.JUnitCore app.foldgpt.install.InactiveIntegrationInstallerTest app.foldgpt.install.InactiveIntegrationRevisionTest | tee "$work/junit-result.txt"
fi
(cd "$work" && sha256sum sources/* > SHA256SUMS)
destination="$repo/downloads/install/integration-native/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'JVM evidence: %s\nHost classes: %s/classes\nNo Android execution performed.\n' "$destination" "$work"
