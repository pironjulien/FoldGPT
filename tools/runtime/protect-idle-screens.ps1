[CmdletBinding()]
param(
    [switch]$ActivateNow,
    [string]$Serial = 'R3GL808JN4A'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$evidenceDirectory = Join-Path $projectRoot 'downloads\overnight\screen-protection'
New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
$adbPath = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
$desktopPath = 'HKCU:\Control Panel\Desktop'
$saverPath = Join-Path $env:WINDIR 'System32\scrnsave.scr'
if (!(Test-Path -LiteralPath $saverPath)) { throw 'Windows blank screensaver is unavailable' }
$snapshotPath = Join-Path $evidenceDirectory 'before.json'
if (!(Test-Path -LiteralPath $snapshotPath)) {
    $desktop = Get-ItemProperty -LiteralPath $desktopPath
    $before = [ordered]@{
        timestamp = (Get-Date).ToString('o')
        screenSaveActive = $desktop.ScreenSaveActive
        screenSaveTimeOut = $desktop.ScreenSaveTimeOut
        screenSaverExe = $desktop.'SCRNSAVE.EXE'
        videoIdle = @(& powercfg /query SCHEME_CURRENT SUB_VIDEO VIDEOIDLE)
        androidStayOn = @(& $adbPath -s $Serial shell -T settings get global stay_on_while_plugged_in)
        androidScreenTimeout = @(& $adbPath -s $Serial shell -T settings get system screen_off_timeout)
    }
    $before | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $snapshotPath -Encoding utf8
}
if (-not ('FoldGptScreenProtection' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FoldGptScreenProtection {
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool SystemParametersInfo(uint action, uint parameter, IntPtr value, uint flags);
    [DllImport("user32.dll", SetLastError=true)]
    public static extern IntPtr SendMessageTimeout(IntPtr window, uint message, UIntPtr parameter,
        IntPtr value, uint flags, uint timeout, out UIntPtr result);
}
'@
}
# Use the PC's existing three-minute battery display timeout for AC and saver.
Set-ItemProperty -LiteralPath $desktopPath -Name 'SCRNSAVE.EXE' -Value $saverPath
$currentDesktop = Get-ItemProperty -LiteralPath $desktopPath
if ($currentDesktop.ScreenSaveTimeOut -ne '180' -and
    ![FoldGptScreenProtection]::SystemParametersInfo(15, 180, [IntPtr]::Zero, 3)) {
    throw "Setting the screensaver idle timeout failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
if ($currentDesktop.ScreenSaveActive -ne '1' -and
    ![FoldGptScreenProtection]::SystemParametersInfo(17, 1, [IntPtr]::Zero, 3)) {
    throw "Enabling the screensaver failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
& powercfg /change monitor-timeout-ac 3
if ($LASTEXITCODE -ne 0) { throw 'Setting the display idle timeout failed' }
# This developer setting only controls keeping the display awake while charging.
& $adbPath -s $Serial shell -T settings put global stay_on_while_plugged_in 0
if ($LASTEXITCODE -ne 0) { throw 'Restoring the Fold display idle policy failed' }
$displayOffRequestAccepted = $false
if ($ActivateNow) {
    & $adbPath -s $Serial shell -T input keyevent 223
    if ($LASTEXITCODE -ne 0) { throw 'Putting the Fold display to sleep failed' }
    # A visible saver was explicitly requested; no interactive action is needed.
    if (!(Get-Process -Name scrnsave -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $saverPath -ArgumentList '/s' -WindowStyle Normal
    }
    # Request display standby as well; background builds continue. This is an
    # OS acknowledgement, not an independent measurement of the physical panel.
    [UIntPtr]$messageResult = [UIntPtr]::Zero
    $displayOffRequestAccepted = [FoldGptScreenProtection]::SendMessageTimeout(
        [IntPtr]0xffff, 0x0112, [UIntPtr]::new([UInt64]0xf170), [IntPtr]2, 2, 1000,
        [ref]$messageResult) -ne [IntPtr]::Zero
}
$after = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    activatedNow = [bool]$ActivateNow
    displayOffRequestAccepted = $displayOffRequestAccepted
    saverPids = @(Get-Process -Name scrnsave -ErrorAction SilentlyContinue | ForEach-Object Id)
    desktop = Get-ItemProperty -LiteralPath $desktopPath | Select-Object ScreenSaveActive,ScreenSaveTimeOut,'SCRNSAVE.EXE'
    videoIdle = @(& powercfg /query SCHEME_CURRENT SUB_VIDEO VIDEOIDLE)
    androidStayOn = @(& $adbPath -s $Serial shell -T settings get global stay_on_while_plugged_in)
    androidPower = @(& $adbPath -s $Serial shell -T dumpsys power | Select-String 'mWakefulness=|mStayOn=' | ForEach-Object Line)
}
$after | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evidenceDirectory 'after.json') -Encoding utf8
$after | ConvertTo-Json -Depth 4
