param(
    [string]$Ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865",
    [string]$OutputDirectory = "$env:TEMP\FoldGPT-codex-offline-probe"
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$probeCompiler = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android35-clang.cmd'
$probePython = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'probe-codex-offline.py')).Replace("`r`n", "`n")
$probeLines = foreach ($probeLine in ($probePython -split "`n")) {
    '"' + $probeLine.Replace('\', '\\').Replace('"', '\"') + '\n"'
}
$probeHeader = 'static const char codex_offline_script[] =' + "`n" + ($probeLines -join "`n") + ";`n"
$probeHeaderPath = Join-Path $OutputDirectory 'probe-codex-offline.generated.h'
[IO.File]::WriteAllText($probeHeaderPath, $probeHeader, [Text.UTF8Encoding]::new($false))
$probeBinary = Join-Path $OutputDirectory 'libfoldgpt-codex-probe.so'
& $probeCompiler -O2 -Wall -Wextra -Werror -I $OutputDirectory (Join-Path $PSScriptRoot 'probe-landlock-codex.c') -o $probeBinary
if ($LASTEXITCODE -ne 0) { throw 'Offline official Codex probe compilation failed' }
Write-Output $probeBinary
Write-Output 'Fixed offline fixture only. No APK installation or runtime configuration change performed.'
