#!/usr/bin/env bash
# Host-only comparison of separately prepared v1/v2 stages using real archives.
# No Android, ARM execution, client, vault, activation or historical-stage writes.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
classes=${1:?Pass the classes directory from run-jvm-tests.sh}
[ -f "$classes/app/foldgpt/install/InactiveIntegrationRealArchiveCheck.class" ]
work=$(mktemp -d /var/tmp/foldgpt-integration-context-XXXXXXXX)
chmod 755 "$work"
uid=12345
gid=23456
if [ "$(id -u)" = 0 ]; then
  chown "$uid:$gid" "$work"
  run=(setpriv --reuid "$uid" --regid "$gid" --clear-groups --)
else
  [ "$(id -u)" = "$uid" ] && [ "$(id -g)" = "$gid" ]
  run=()
fi
base="$repo/downloads/install/debian-13-arm64-dd0aac2065057596/debian-13-arm64-rootfs.tar.gz"
legacy_sha=d0d9f2edce1c194ae2188556922373bb8e66d9ae30e8f34197da54a51945c16c
legacy="$repo/downloads/install/integration-native/$legacy_sha.fgi"
"${run[@]}" id | tee "$work/identity.txt"
printf 'Host work: %s\nJVM snapshot: %s\n' "$work" "${classes%/classes}" | tee "$work/java-evidence.txt"
cp -a "${classes%/classes}/sources" "$work/java-sources"
# Preserve the exact text sources that define the new guest bundle. No account
# or profile state is read. These are local build inputs, not a remote release.
"${run[@]}" python3 -B - "$repo" "$work" <<'PY'
import json
from pathlib import Path
import sys
repo, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(repo / "tools/install"))
import guest_bundle
import inactive_integration_bundle as integration
data = guest_bundle.build(repo)
guest_sha = guest_bundle.digest(data)
guest = work / ("guest-" + guest_sha + ".tar")
guest_bundle.write_new_archive(guest, data)
container, manifest = integration.build(guest, guest_sha,
    repo / "downloads/gpu/foldgpt-mesa-26.2.2-arm64.tar.gz",
    repo / "downloads/install/debian-13-arm64-dd0aac2065057596/debian-13-arm64-rootfs.tar.gz")
sha = integration.digest(container)
guest_bundle.write_new_archive(work / (sha + ".fgi"), container)
guest_bundle.write_new_archive(work / (sha + ".manifest"), manifest)
result = {"format": integration.FORMAT, "bytes": len(container), "sha256": sha,
          "guestBundleSha256": guest_sha, "manifestSha256": integration.digest(manifest),
          "baseSha256": integration.BASE_SHA, "gpuSha256": integration.GPU_SHA,
          "scope": "host-archive-assembly-only", "activated": False,
          "modelDeliveryVerified": False}
(work / "assembly.json").write_text(json.dumps(result, indent=2) + "\n")
(work / "bundle-args.txt").write_text(sha + "\n" + str(len(container)) + "\n")
sources = work / "sources"
for name in (*guest_bundle.SOURCES, "tools/install/guest_bundle.py",
             "tools/install/inactive_integration_bundle.py",
             "tools/install/test_inactive_integration_bundle.py",
             "tools/install/integration-native/check-context-revision.sh"):
    target = sources / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(guest_bundle.read_bounded(repo / name, guest_bundle.MAX_FILE_BYTES))
print(json.dumps(result))
PY
mapfile -t bundle_args < "$work/bundle-args.txt"
cp="$classes:$repo/downloads/install/transaction-deps/*"
"${run[@]}" mkdir -m 700 "$work/stage-v1" "$work/stage-v2"
"${run[@]}" java -cp "$cp" app.foldgpt.install.InactiveIntegrationRealArchiveCheck \
  "$work/stage-v1" "$base" "$legacy" "$legacy_sha" 41116761 "$uid" "$gid" | tee "$work/legacy-result.txt"
"${run[@]}" java -cp "$cp" app.foldgpt.install.InactiveIntegrationRealArchiveCheck \
  "$work/stage-v2" "$base" "$work/${bundle_args[0]}.fgi" "${bundle_args[0]}" "${bundle_args[1]}" "$uid" "$gid" | tee "$work/context-result.txt"
"${run[@]}" python3 -B -m unittest discover -s "$repo/tools/install" -p test_inactive_integration_bundle.py -v 2>&1 | tee "$work/python-result.txt"
destination="$repo/downloads/install/integration-native/$(basename "$work")"
[ ! -e "$destination" ]
mkdir "$destination"
# Stage trees stay in /var/tmp; copy only input/source snapshots and structural
# reports. The historical v1 archive and its earlier evidence are never changed.
cp -a "$work/sources" "$work/java-sources" "$destination/"
cp "$work/"*.txt "$work/"*.json "$work/"*.fgi "$work/"*.manifest "$work/"*.tar "$destination/"
for revision in v1 v2; do
  result=context
  if [ "$revision" = v1 ]; then result=legacy; fi
  report=$(sed -n 's/^REPORT=//p' "$work/$result-result.txt")
  cp "$report" "$destination/report-$revision.txt"
done
(cd "$destination" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
printf 'Context revision evidence: %s\nHost-only inactive stages: %s\n' "$destination" "$work"
