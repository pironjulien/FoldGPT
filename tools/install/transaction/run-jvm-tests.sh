#!/usr/bin/env bash
# Real host JVM/POSIX checks only. Never install an APK or touch the phone.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
deps="$repo/downloads/install/transaction-deps"
mkdir -p "$deps"
while read -r hash relative; do
  file=${relative##*/}
  if [ ! -f "$deps/$file" ]; then
    temporary=$(mktemp "$deps/.maven-download-XXXXXXXX")
    curl -fLsS "https://repo.maven.apache.org/maven2/$relative" -o "$temporary"
    printf '%s  %s\n' "$hash" "$temporary" | sha256sum -c -
    ln "$temporary" "$deps/$file"
    rm "$temporary"
  fi
  printf '%s  %s\n' "$hash" "$deps/$file" | sha256sum -c -
done <<'DEPENDENCIES'
e1522945218456f3649a39bc4afd70ce4bd466221519dba7d378f2141a4642ca org/apache/commons/commons-compress/1.28.0/commons-compress-1.28.0.jar
df90bba0fe3cb586b7f164e78fe8f8f4da3f2dd5c27fa645f888100ccc25dd72 commons-io/commons-io/2.20.0/commons-io-2.20.0.jar
4eeeae8d20c078abb64b015ec158add383ac581571cddc45c68f0c9ae0230720 org/apache/commons/commons-lang3/3.18.0/commons-lang3-3.18.0.jar
5c3881e4f556855e9c532927ee0c9dfde94cc66760d5805c031a59887070af5f commons-codec/commons-codec/1.19.0/commons-codec-1.19.0.jar
8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3 junit/junit/4.13.2/junit-4.13.2.jar
66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9 org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar
DEPENDENCIES
work=$(mktemp -d /var/tmp/foldgpt-install-java-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/classes" "$work/sources"
cp "$repo/android/app/src/main/java/app/foldgpt/install/"*.java "$work/sources/"
cp "$repo/android/app/src/test/java/app/foldgpt/install/"*.java "$work/sources/"
cp "$repo/tools/install/transaction/run-jvm-tests.sh" "$work/sources/"
java -version 2> "$work/java-version.txt"
uname -a > "$work/kernel.txt"
javac -cp "$deps/*" -d "$work/classes" "$work/sources/RootfsExtractor.java" \
  "$work/sources/RootfsTransaction.java" "$work/sources/RootfsTransactionTest.java" \
  "$work/sources/ProotHardlinkStorage.java" \
  "$work/sources/GuestIdentity.java" "$work/sources/GuestIdentityTest.java" \
  "$work/sources/GuestAccountProvisioner.java" "$work/sources/GuestAccountProvisionerTest.java" \
  "$work/sources/GuestAccountRealArchiveCheck.java" \
  "$work/sources/RootfsRealArchiveCheck.java"
if [ "$(id -u)" = 0 ]; then
  runuser -u nobody -- java -cp "$work/classes:$deps/*" org.junit.runner.JUnitCore \
    app.foldgpt.install.RootfsTransactionTest app.foldgpt.install.GuestIdentityTest app.foldgpt.install.GuestAccountProvisionerTest | tee "$work/junit-result.txt"
else
  java -cp "$work/classes:$deps/*" org.junit.runner.JUnitCore app.foldgpt.install.RootfsTransactionTest app.foldgpt.install.GuestIdentityTest app.foldgpt.install.GuestAccountProvisionerTest | tee "$work/junit-result.txt"
fi
(cd "$work" && sha256sum sources/* > SHA256SUMS)
sha256sum "$deps/"*.jar > "$work/dependency-sha256.txt"
destination="$repo/downloads/install/transaction-check/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'JVM/POSIX evidence: %s\nHost classes for optional real archive check: %s/classes\nNo Android execution performed.\n' "$destination" "$work"
