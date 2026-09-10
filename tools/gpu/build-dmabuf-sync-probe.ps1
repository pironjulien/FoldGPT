param([string]$Ndk = "$env:LOCALAPPDATA\Android\Sdk\ndk\29.0.14206865")
$ErrorActionPreference = 'Stop'
$syncProject = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$syncOutput = Join-Path $syncProject 'downloads\gpu\dmabuf-sync-probe'
$syncCompiler = Join-Path $Ndk 'toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android30-clang.cmd'
New-Item -ItemType Directory -Force (Split-Path -Parent $syncOutput) | Out-Null
# The public submodule stays pinned and clean. Extract only the complete new
# helper header from our versioned patch; never depend on a dirty vendor file.
$syncHeaderDirectory = Join-Path $syncProject 'downloads\gpu\dmabuf-sync-header'
New-Item -ItemType Directory -Force $syncHeaderDirectory | Out-Null
$syncPatchPath = Join-Path $PSScriptRoot 'termux-x11-dmabuf-sync.patch'
$syncPatchText = [IO.File]::ReadAllText($syncPatchPath).Replace("`r`n", "`n")
$syncHeaderMarker = 'diff --git a/lorie/src/main/cpp/lorie/dmabuf_sync.h b/lorie/src/main/cpp/lorie/dmabuf_sync.h'
$syncHeaderStart = $syncPatchText.IndexOf($syncHeaderMarker + "`n", [StringComparison]::Ordinal)
if ($syncHeaderStart -lt 0) { throw 'Versioned patch does not contain the complete DMA-BUF helper header' }
$syncHeaderBlock = $syncPatchText.Substring($syncHeaderStart)
$syncNextDiff = $syncHeaderBlock.IndexOf("`ndiff --git ", [StringComparison]::Ordinal)
if ($syncNextDiff -ge 0) { $syncHeaderBlock = $syncHeaderBlock.Substring(0, $syncNextDiff + 1) }
if ($syncHeaderBlock -notmatch '(?m)^--- /dev/null$') { throw 'Helper extraction requires a new-file patch, not a partial edit' }
$syncHunk = [regex]::Match($syncHeaderBlock, '(?m)^@@ -0,0 \+1,(\d+) @@\n')
if (-not $syncHunk.Success) { throw 'Helper patch must contain one complete new-file hunk' }
$syncLines = $syncHeaderBlock.Substring($syncHunk.Index + $syncHunk.Length).TrimEnd("`n") -split "`n"
if ($syncLines.Count -ne [int]$syncHunk.Groups[1].Value -or ($syncLines | Where-Object { -not $_.StartsWith('+') })) {
    throw 'Unexpected helper patch contents or line count'
}
$syncHeaderText = (($syncLines | ForEach-Object { $_.Substring(1) }) -join "`n") + "`n"
$syncHeaderPath = Join-Path $syncHeaderDirectory 'dmabuf_sync.h'
[IO.File]::WriteAllText($syncHeaderPath, $syncHeaderText, [Text.UTF8Encoding]::new($false))
$syncMemfdPatchPath = Join-Path $PSScriptRoot 'termux-x11-dmabuf-memfd.patch'
# Apply the same incremental correction as the X11 build, without touching the
# submodule. Stop Git repository discovery: a nested git apply would otherwise
# silently skip paths outside this directory relative to the repository root.
$syncPreviousCeiling = $env:GIT_CEILING_DIRECTORIES
try {
    $env:GIT_CEILING_DIRECTORIES = Split-Path -Parent $syncHeaderDirectory
    & git -C $syncHeaderDirectory apply --no-index -p6 --check $syncMemfdPatchPath
    if ($LASTEXITCODE -ne 0) { throw 'DMA-BUF memfd patch does not match the extracted header' }
    & git -C $syncHeaderDirectory apply --no-index -p6 $syncMemfdPatchPath
    if ($LASTEXITCODE -ne 0) { throw 'DMA-BUF memfd patch application failed' }
    & git -C $syncHeaderDirectory apply --no-index -p6 -R --check $syncMemfdPatchPath
    if ($LASTEXITCODE -ne 0) { throw 'DMA-BUF memfd patch verification failed' }
} finally {
    $env:GIT_CEILING_DIRECTORIES = $syncPreviousCeiling
}
if ([IO.File]::ReadAllText($syncHeaderPath).Replace("`r`n", "`n") -eq $syncHeaderText) {
    throw 'DMA-BUF memfd patch was unexpectedly skipped'
}
Get-FileHash -Algorithm SHA256 -LiteralPath $syncPatchPath, $syncMemfdPatchPath, $syncHeaderPath |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $syncHeaderDirectory 'provenance.json') -Encoding utf8
& $syncCompiler -O2 -Wall -Wextra -Werror `
    -I $syncHeaderDirectory `
    (Join-Path $PSScriptRoot 'dmabuf-sync-probe.c') -landroid -o $syncOutput
if ($LASTEXITCODE -ne 0) { throw 'DMA-BUF probe compilation failed' }
Get-FileHash -Algorithm SHA256 -LiteralPath $syncOutput
