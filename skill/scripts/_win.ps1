# Shared Win32 helpers for capture.ps1 and record.ps1 (dot-sourced).
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
if (-not ('DevlogWin' -as [type])) {
    Add-Type @"
using System; using System.Runtime.InteropServices;
public static class DevlogWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int attr, out RECT r, int size);
}
"@
}
[DevlogWin]::SetProcessDPIAware() | Out-Null

# A visible top-level window whose title contains $Name, or whose process is named $Name.
function Find-DevlogWindow([string]$Name) {
    $procs = Get-Process | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero }
    $hit = $procs | Where-Object { $_.ProcessName -ieq $Name } | Select-Object -First 1
    if (-not $hit) { $hit = $procs | Where-Object { $_.MainWindowTitle -like "*$Name*" } | Select-Object -First 1 }
    if (-not $hit) {
        $titles = ($procs | Where-Object { $_.MainWindowTitle } | ForEach-Object { "  $($_.ProcessName): $($_.MainWindowTitle)" }) -join "`n"
        throw "No window matching '$Name'. Open windows:`n$titles"
    }
    return $hit.MainWindowHandle
}

# Bring a window forward and return its on-screen rectangle (physical pixels, no drop shadow).
function Get-DevlogRect([IntPtr]$Handle, [int]$SettleMs = 350) {
    if ([DevlogWin]::IsIconic($Handle)) { [DevlogWin]::ShowWindow($Handle, 9) | Out-Null }
    [DevlogWin]::SetForegroundWindow($Handle) | Out-Null
    Start-Sleep -Milliseconds $SettleMs
    $r = New-Object DevlogWin+RECT
    if ([DevlogWin]::DwmGetWindowAttribute($Handle, 9, [ref]$r, 16) -ne 0) { [DevlogWin]::GetWindowRect($Handle, [ref]$r) | Out-Null }
    return [System.Drawing.Rectangle]::FromLTRB($r.Left, $r.Top, $r.Right, $r.Bottom)
}
