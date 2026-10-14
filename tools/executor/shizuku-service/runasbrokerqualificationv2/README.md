# Run-as broker V2 qualification

**Run successfully on 8 September 2026: 12/12 real proofs.**
The supervisor and the worker exit with code 0; cleanup, absence of the PIDs,
unchanged boot and unchanged APK are cross-checked independently. Tracked
evidence: `recovery/verification/runas-broker-20260908`. The RUN_BROKER_V2
action is consumed: do not replay it or delete its marker. The instructions
below preserve the provenance of this qualification; they are not an invitation
to replay it.

New APK `app.foldgpt.runasbrokerqualification.v2`, new action
`RUN_BROKER_V2`, new Activity marker. No earlier attempt is replayed.
The FoldGPT package and the official app are not updated by this
qualification. Target: `run-as app.foldgpt`, UID attested by PackageManager.

The same frozen `NativeSpawn` JNI passes fd0..3. A dedicated Bionic launcher
checks, **before Python starts**, the private data and aliases under
`/data/user/0/app.foldgpt/files/runas-native-v2/python`, as well as every ELF
attested in the APK. The fingerprints are compiled from the authenticated
Python inventory. This launcher uses the official libcrypto already shipped
with Python, loaded from its own APK. It grants no privileges.

After admission, it execs the new Python CLI with an empty environment and
`-I -S -B -u`. The signed module receives the attested UID, parent and nonce;
no path or command comes from an RPC. It exclusively creates fresh
`runas-native-v2/workspace` and `runas-native-v2/broker` directories. The
protections, 12 kernel proofs and limits of `kernel-qualification` are identical
to those of the qKM94iHA supervisor, this time with the real FoldGPT UID.

The Python owner keeps the real backend and its marker in quarantine if native
cleanup cannot be proven. FD3 is the cancellation channel. The Java service
waits for the real owner and also checks the native cleanup receipt; the PID
exiting alone does not prove that descendants were cleaned up. A collection
timeout must never trigger a new attempt.

## PC preparation

```powershell
python -B runasbrokerqualificationv2/stage.py --python-cli <new-cli> --python-cli-sha256 <reviewed-sha>
gradle :runasbrokerqualificationv2:assembleDebug -PfoldgptFrozenTransportJni=C:/Dev/FoldGPT/tools/executor/shizuku-lab/build/frozen-transport-jni --no-daemon --console=plain
```

Required CLI: exact RUNPATH
`/data/user/0/app.foldgpt/files/runas-native-v2/python/lib:$ORIGIN`.
Current exclusive stage: `build/runasbrokerqualification-v2/stage-r2`.
The first stage, created before the CMake library name fix, is kept; it
produced no APK. R2 also distinguishes the launch request from the `started`
proof provided by the real supervisor.
Python sources: frozen snapshotPCv3 (identical qKM94iHA factory, repaired
listing); Android helpers/supervisor/worker: frozen qKM94iHA.

## Android preparation, to be done separately by the test owner

After reviewing and installing the separate APK, obtain `nativeLibraryDir` via
`COLLECT_INFO`. Copy only `stage/staged-python-data` into FoldGPT's private
Python prefix with correct owners; create the 81 exact aliases from
`stage/runtime-manifest.json` pointing to the `nativeLibraryDir` of this new APK.
The base and the Python folder must be 0700, ordinary private files 0600 and
subdirectories 0700. Do not create workspace/broker: the bootstrap must reserve
them exclusively.

Component:
`app.foldgpt.runasbrokerqualification.v2/app.foldgpt.runasbrokerqualification.RunAsBrokerQualificationActivity`.
Actions: prefix `app.foldgpt.runasbrokerqualification.v2.` followed by
`COLLECT_INFO`, `AUTHORIZE`, `PREFLIGHT` or `RUN_BROKER_V2`.
Private APK report: `files/runas-broker-v2/run_broker_v2.json`.

The Java preflight cross-checks the APKs; the private runtime check is done by
the native launcher after run-as, since shell cannot open that data.
A successful PC build is not proof of execution on Android.
