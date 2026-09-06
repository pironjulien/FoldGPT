[CmdletBinding()]
param(
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$FixtureParent = '/tmp',
    [string]$NdkRoot = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865"
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$artifactDirectory = Join-Path $projectRoot 'downloads\native-abc-check'
$null = New-Item -ItemType Directory -Force -Path $artifactDirectory
$nativeCompiler = Join-Path $NdkRoot 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android35-clang.cmd'
$readelf = Join-Path $NdkRoot 'toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-readelf.exe'
if (!(Test-Path -LiteralPath $nativeCompiler -PathType Leaf)) {
    throw "Android NDK compiler not found: $nativeCompiler"
}
if (!$FixtureParent.StartsWith('/')) {
    throw 'FixtureParent must be an absolute path inside the named WSL distribution.'
}

$hostOutput = Join-Path $artifactDirectory 'host-result.txt'
$environmentOutput = Join-Path $artifactDirectory 'environment.txt'
"Recorded UTC: $([DateTime]::UtcNow.ToString('o'))" | Set-Content -LiteralPath $environmentOutput
& wsl.exe -d $Distribution -- uname -a | Add-Content -LiteralPath $environmentOutput
if ($LASTEXITCODE -ne 0) { throw 'WSL kernel query failed.' }
& wsl.exe -d $Distribution -- gcc --version | Add-Content -LiteralPath $environmentOutput
if ($LASTEXITCODE -ne 0) { throw 'WSL compiler query failed.' }
& $nativeCompiler --version | Add-Content -LiteralPath $environmentOutput
if ($LASTEXITCODE -ne 0) { throw 'Android compiler query failed.' }

& wsl.exe -d $Distribution --cd $projectRoot -- gcc -std=c11 -O2 -Wall -Wextra -Werror `
    tools/executor/native-abc-probe.c -o downloads/native-abc-check/native-abc-linux-x86_64
if ($LASTEXITCODE -ne 0) { throw 'Native WSL compilation failed.' }
& wsl.exe -d $Distribution --cd $projectRoot -- `
    ./downloads/native-abc-check/native-abc-linux-x86_64 $FixtureParent | Tee-Object -FilePath $hostOutput
if ($LASTEXITCODE -ne 0) { throw 'Native WSL A/B/C/A diagnostic failed.' }

& wsl.exe -d $Distribution --cd $projectRoot -- gcc -std=c11 -O2 -Wall -Wextra -Werror `
    tools/executor/native-abc-watchdog-test.c -o downloads/native-abc-check/native-abc-watchdog-test
if ($LASTEXITCODE -ne 0) { throw 'Native watchdog test compilation failed.' }
& wsl.exe -d $Distribution --cd $projectRoot -- `
    ./downloads/native-abc-check/native-abc-watchdog-test 2>&1 |
    Tee-Object -FilePath (Join-Path $artifactDirectory 'watchdog-result.txt')
if ($LASTEXITCODE -ne 0) { throw 'Native watchdog test failed.' }

$androidOutput = Join-Path $artifactDirectory 'native-abc-android-arm64'
& $nativeCompiler -std=c11 -O2 -Wall -Wextra -Werror `
    (Join-Path $PSScriptRoot 'native-abc-probe.c') -o $androidOutput
if ($LASTEXITCODE -ne 0) { throw 'Android ARM64 cross compilation failed.' }
& $readelf -h $androidOutput | Set-Content -LiteralPath (Join-Path $artifactDirectory 'android-elf-header.txt')
if ($LASTEXITCODE -ne 0) { throw 'Android ELF inspection failed.' }

$hashPaths = @(
    (Join-Path $PSScriptRoot 'native-abc-probe.c'),
    (Join-Path $artifactDirectory 'native-abc-linux-x86_64'),
    $androidOutput
)
Get-FileHash -Algorithm SHA256 -LiteralPath $hashPaths |
    Select-Object Path, Hash | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $artifactDirectory 'sha256.json')
Write-Output "Native WSL run passed; Android ARM64 compiled only. Evidence: $artifactDirectory"
