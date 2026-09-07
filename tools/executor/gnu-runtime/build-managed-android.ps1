param(
    [string]$Ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865",
    [string]$OutputParent = "$PSScriptRoot\..\..\..\downloads\gnu-runtime"
)
$ErrorActionPreference = 'Stop'
$gnuBuild = Join-Path $OutputParent ('managed-android-' + [guid]::NewGuid().ToString('N'))
$gnuExecutor = Join-Path $gnuBuild 'sources\tools\executor'
$gnuSource = Join-Path $gnuExecutor 'gnu-runtime'
New-Item -ItemType Directory -Path $gnuSource -Force | Out-Null
foreach ($gnuName in @('gnu-managed-runner.c', 'gnu-managed-filter.h', 'gnu-managed-operations.h',
        'gnu-managed-runtime.h', 'gnu_process_adapter.py', 'gnu_runtime_capacity.py', 'gnu_runtime_address.py', 'test_gnu_process_adapter.py',
        'managed_android_fixture.py', 'prepare-managed-gnu.py', 'managed-derivation.json', 'build-managed-android.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $gnuName) -Destination (Join-Path $gnuSource $gnuName)
}
foreach ($gnuName in @('native-runner.c', 'native-runner-seccomp.h', 'native-runner-memory-contract.h',
        'native-managed-filter.h', 'native-managed-runner.c', 'native_processes.py', 'native_process_policy.py',
        'native_environment.py', 'native_environment_unicode.py', 'native_files.py', 'exec_server.py', 'policy_intent.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\$gnuName") -Destination (Join-Path $gnuExecutor $gnuName)
}
$gnuPolicy = Join-Path $gnuBuild 'sources\tools\policy'
New-Item -ItemType Directory -Path $gnuPolicy | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\..\policy\managed_policy.py') -Destination $gnuPolicy
$gnuToolchain = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin'
$gnuCompiler = Join-Path $gnuToolchain 'aarch64-linux-android35-clang.cmd'
$gnuBinary = Join-Path $gnuBuild 'libfoldgpt-gnu-managed.so'
& $gnuCompiler -O2 -Wall -Wextra -Werror '-Wl,-z,max-page-size=16384,-z,common-page-size=16384' (Join-Path $gnuSource 'gnu-managed-runner.c') -o $gnuBinary
if ($LASTEXITCODE -ne 0) { throw 'Managed GNU Android compilation failed' }
& (Join-Path $gnuToolchain 'llvm-readelf.exe') -h -l -d $gnuBinary | Set-Content -LiteralPath (Join-Path $gnuBuild 'elf.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Managed GNU ELF inspection failed' }
$gnuHashes = [ordered]@{}
foreach ($gnuFile in Get-ChildItem -LiteralPath (Join-Path $gnuBuild 'sources') -File -Recurse) {
    $gnuHashes[[IO.Path]::GetRelativePath($gnuBuild, $gnuFile.FullName).Replace('\','/')] = (Get-FileHash -LiteralPath $gnuFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$gnuHashes['libfoldgpt-gnu-managed.so'] = (Get-FileHash -LiteralPath $gnuBinary -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{ scope = 'ARM64 compilation only'; ndk = $Ndk; files = $gnuHashes } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $gnuBuild 'manifest.json') -Encoding utf8
Write-Output $gnuBuild
