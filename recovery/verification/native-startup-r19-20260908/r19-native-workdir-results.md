# r19 native workdir observations

Real ordinary application launch, r19/versionCode9, frozen packagev7.

- `controller-link-8055df9e`: complete native Python and human qualification PASS.
  Independent `after-r19-full-device` confirms owner22200 reaped with wait0,
  no remaining PID, unchanged boot/properties/official Android and GNU files.
- `controller-link-643c6a89`: new workdir qualification PASS. Python executes in
  W/app while the original policy remains rooted at W; returns42, platform
  android, machine aarch64 and UID10412. Three actual attempts against denied
  W/private and protected W/.git fail; native host readback preserves original
  bytes and confirms app/result.txt contains42.
- `controller-link-062ed250`: additional test variant through the actual
  `bash -lc` invocation. Process exited0, closed without backend failure,
  stdout reports the same correct Android identity, W/app cwd, result42 and
  three refusals. The controller test reports FAIL because its inherited
  direct-Python assertion requires empty stderr. Actual Bash stderr contains
  two login-profile permission warnings, retained verbatim in its report:
  `/data/local/tmp/foldgpt-shizuku-lab/etc/profile` and
  `/data/user/0/app.foldgpt/files/projects/.bash_profile`.

The Bash variant used an explicitly narrow policy granting W only and denying
W/private. Both attempted startup files are outside that W. No permission was
broadened, no warning suppressed, and no passing test substituted for this
record. The old laboratory prefix in the compiled Bash is a separate observed
configuration issue. Its effect in the normal GUI policy remains unmeasured;
this process itself completed its requested work successfully. Ordinary cloud
conversation and editor remain unqualified pending the corrected Rust engine.
