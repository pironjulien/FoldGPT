param([string]$Ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865")
$ErrorActionPreference = 'Stop'
$probeProject = Split-Path -Parent $PSScriptRoot
$probeOutput = Join-Path $probeProject 'android\native\debug\arm64-v8a'
New-Item -ItemType Directory -Force -Path $probeOutput | Out-Null
$probeCompiler = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android35-clang.cmd'
& $probeCompiler -O2 -Wall -Wextra -Werror (Join-Path $PSScriptRoot 'probe-landlock-enforcement.c') -o (Join-Path $probeOutput 'libfoldgpt-landlock-probe.so')
if ($LASTEXITCODE -ne 0) { throw 'Landlock probe compilation failed' }
& $probeCompiler -O2 -Wall -Wextra -Werror (Join-Path $PSScriptRoot 'probe-landlock-broker.c') -o (Join-Path $probeOutput 'libfoldgpt-broker-probe.so')
if ($LASTEXITCODE -ne 0) { throw 'Landlock broker probe compilation failed' }
& $probeCompiler -O2 -Wall -Wextra -Werror (Join-Path $PSScriptRoot 'probe-landlock-proot.c') -o (Join-Path $probeOutput 'libfoldgpt-proot-probe.so')
if ($LASTEXITCODE -ne 0) { throw 'Landlock PRoot probe compilation failed' }
& $probeCompiler -O2 -Wall -Wextra -Werror (Join-Path $PSScriptRoot 'probe-landlock-shell.c') -o (Join-Path $probeOutput 'libfoldgpt-shell-probe.so')
if ($LASTEXITCODE -ne 0) { throw 'Landlock shell probe compilation failed' }
Write-Output 'Built debug-only ARM64 Landlock experiment. Rebuild the debug APK to deploy.'
