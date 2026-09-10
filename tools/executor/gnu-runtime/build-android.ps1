param(
    [string]$Ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865",
    [string]$OutputParent = "$PSScriptRoot\..\..\..\downloads\gnu-runtime"
)
$ErrorActionPreference = 'Stop'
$gnuBuild = Join-Path $OutputParent ('android-' + [guid]::NewGuid().ToString('N'))
$gnuSource = Join-Path $gnuBuild 'sources'
New-Item -ItemType Directory -Path $gnuSource -Force | Out-Null
foreach ($gnuName in @('gnu-project.c', 'gnu-project.generated.h', 'project.py', 'prepare-launcher.py', 'derivation.json', 'verify-host.py', 'run-linux-tests.sh', 'build-android.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $gnuName) -Destination (Join-Path $gnuSource $gnuName)
}
$gnuToolchain = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin'
$gnuCompiler = Join-Path $gnuToolchain 'aarch64-linux-android35-clang.cmd'
$gnuBinary = Join-Path $gnuBuild 'libfoldgpt-gnu-project.so'
& $gnuCompiler -O2 -Wall -Wextra -Werror '-Wl,-z,max-page-size=16384,-z,common-page-size=16384' (Join-Path $gnuSource 'gnu-project.c') -o $gnuBinary
if ($LASTEXITCODE -ne 0) { throw 'GNU project Android launcher compilation failed' }
& (Join-Path $gnuToolchain 'llvm-readelf.exe') -h -l -d $gnuBinary | Set-Content -LiteralPath (Join-Path $gnuBuild 'elf.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'GNU project launcher ELF inspection failed' }
$gnuHashes = [ordered]@{}
foreach ($gnuFile in Get-ChildItem -LiteralPath $gnuSource -File) {
    $gnuHashes['sources/' + $gnuFile.Name] = (Get-FileHash -LiteralPath $gnuFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$gnuHashes['libfoldgpt-gnu-project.so'] = (Get-FileHash -LiteralPath $gnuBinary -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{ scope = 'ARM64 compilation only'; ndk = $Ndk; files = $gnuHashes } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $gnuBuild 'manifest.json') -Encoding utf8
Write-Output $gnuBuild
