<#
.SYNOPSIS
  Screenshot a window (by title or process name) or the screen to PNG, for devlog media.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File capture.ps1 -Out "D:\...\media\viewer.png" -Window Forge
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File capture.ps1 -Out shot.png            # primary screen
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Window,            # substring of the window title, or the exact process name
    [int]$Delay = 0,            # extra ms to wait after bringing the window forward (let it repaint)
    [switch]$AllScreens         # with no -Window: capture every monitor instead of the primary one
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_win.ps1')

if ($Window) {
    $rect = Get-DevlogRect (Find-DevlogWindow $Window) (350 + $Delay)
} else {
    if ($Delay) { Start-Sleep -Milliseconds $Delay }
    $rect = if ($AllScreens) { [System.Windows.Forms.SystemInformation]::VirtualScreen } else { [System.Windows.Forms.Screen]::PrimaryScreen.Bounds }
}
if ($rect.Width -le 0 -or $rect.Height -le 0) { throw "Window has no visible area: $rect" }

$dir = Split-Path -Parent ([System.IO.Path]::GetFullPath($Out))
if ($dir) { New-Item -ItemType Directory -Force $dir | Out-Null }
$bmp = New-Object System.Drawing.Bitmap $rect.Width, $rect.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
try {
    $g.CopyFromScreen($rect.Location, [System.Drawing.Point]::Empty, $rect.Size)
    $bmp.Save([System.IO.Path]::GetFullPath($Out), [System.Drawing.Imaging.ImageFormat]::Png)
} finally { $g.Dispose(); $bmp.Dispose() }
Write-Output "$([System.IO.Path]::GetFullPath($Out)) ($($rect.Width)x$($rect.Height))"
