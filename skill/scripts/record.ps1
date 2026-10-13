<#
.SYNOPSIS
  Record a window or the screen to MP4 with ffmpeg (gdigrab), or convert a clip (Godot .avi, Playwright .webm) to MP4.
.EXAMPLE
  # 20 s of the Forge window; run in the background, then drive the app while it records
  powershell -NoProfile -ExecutionPolicy Bypass -File record.ps1 -Out "...\media\fanout.mp4" -Window Forge -Seconds 20
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File record.ps1 -From movie.avi -Out "...\media\movie.mp4"
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Window,            # title substring or process name; omit for the primary screen
    [int]$Seconds = 15,
    [int]$Fps = 30,
    [int]$StartDelay = 0,       # ms to wait before recording starts
    [string]$From               # convert this file instead of recording
)
$ErrorActionPreference = 'Stop'

function Find-Ffmpeg {
    $c = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe", "C:\ffmpeg\bin\ffmpeg.exe", "D:\Game Dev\Tools\ffmpeg\bin\ffmpeg.exe")) {
        if (Test-Path $p) { return $p }
    }
    $w = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($w) { return $w.FullName }
    return $null
}
$ffmpeg = Find-Ffmpeg
if (-not $ffmpeg) {
    Write-Error "ffmpeg not found. Install it once with:  winget install --id Gyan.FFmpeg -e   (then open a new shell). Until then, use capture.ps1 screenshots."
    exit 2
}
$OutFull = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force (Split-Path -Parent $OutFull) | Out-Null
$encode = @('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-movflags', '+faststart', '-an')

if ($From) {
    & $ffmpeg -hide_banner -loglevel error -y -i $From @encode $OutFull
} else {
    . (Join-Path $PSScriptRoot '_win.ps1')
    $rect = if ($Window) { Get-DevlogRect (Find-DevlogWindow $Window) } else { [System.Windows.Forms.Screen]::PrimaryScreen.Bounds }
    if ($StartDelay) { Start-Sleep -Milliseconds $StartDelay }
    $grab = @('-f', 'gdigrab', '-framerate', "$Fps", '-offset_x', "$($rect.X)", '-offset_y', "$($rect.Y)",
              '-video_size', "$($rect.Width)x$($rect.Height)", '-draw_mouse', '1', '-t', "$Seconds", '-i', 'desktop')
    & $ffmpeg -hide_banner -loglevel error -y @grab @encode $OutFull
}
if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed with exit code $LASTEXITCODE" }
Write-Output $OutFull
