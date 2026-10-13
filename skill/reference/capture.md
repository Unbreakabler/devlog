# Capturing screenshots and video

Save media straight into the session's `media/` folder (`devlog.py start` creates it) with a descriptive name (`viewer-700k-crate.png`, not `shot1.png`), then add a `media` entry with a caption, or register an outside file with `devlog.py media "<session dir>" <file> --caption "..." --feature <slug>`.

Prefer: PNG for stills, MP4 (H.264) for video, 5 to 30 seconds, one idea per clip. Keep files under ~20 MB; trim or lower the frame rate rather than skip the video.

Scripts are in `D:\Game Dev\devlog\skill\scripts\` (called `scripts\` below).

## Any desktop window (Forge, Godot, Unreal, Blender, ComfyUI in a browser)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\capture.ps1" -Out "<session>\media\name.png" -Window Forge
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\capture.ps1" -Out "<session>\media\screen.png"      # whole primary screen
```

`-Window` matches a process name exactly or a window-title substring; with no match it lists the open windows. The window is brought to the front first; `-Delay 1000` gives it time to repaint.

Video of a window uses ffmpeg (installed on jon-gaming via winget, `Gyan.FFmpeg`; `record.ps1` finds it even in shells started before the install). Start the recording in the background, then drive the app (computer-use, keyboard, a demo script) while it runs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\record.ps1" -Out "<session>\media\flow.mp4" -Window Forge -Seconds 20
```

`record.ps1 -From in.avi -Out out.mp4` converts a clip (Godot movie, Playwright webm) to a browser-friendly MP4.

Note: the computer-use and in-app browser screenshot tools return images to you but do not save files. Use the scripts here for anything that goes in the devlog.

## Forge

- **Real app:** `npm run dev` (or the mock: see Forge `README.md`), then `capture.ps1 -Window Forge` / `record.ps1 -Window Forge`. The demo scripts in `Forge/docs/demo-slice*.json` replay a scripted session, which makes a good recording.
- **UI only, no GPU:** `ui/bench/app.html` runs the UI in a browser with a stub IPC bridge. Start Vite (`npm --prefix ui run dev`), then:
  ```powershell
  node "scripts\capture_web.mjs" --url http://127.0.0.1:5173/bench/app.html --out "<session>\media\ui.png"
  node "scripts\capture_web.mjs" --url http://127.0.0.1:5173/bench/app.html --video "<session>\media\ui.webm" --steps steps.json
  ```
  `capture_web.mjs` uses Forge's `playwright-core` and the installed Edge. Steps format is in the script header. Video uses Playwright's ffmpeg (installed in `%LOCALAPPDATA%\ms-playwright`; after a Playwright upgrade reinstall with `node ui\node_modules\playwright-core\cli.js install ffmpeg`). Convert `.webm` to `.mp4` with `record.ps1 -From` if you like; browsers play both.
- **Real WebView2 over CDP:** start Forge with `$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222"`, then `capture_web.mjs --cdp http://127.0.0.1:9222 --out ...` (screenshots and steps; no video in this mode, use `record.ps1`).
- **3D viewport:** take the shot after the full mesh has loaded (the viewport badge shows the LOD), and say in the caption which backend (WebGPU or WebGL 2) rendered it.

## Godot games

- **Video, deterministic:** Movie Maker mode renders every frame at a fixed rate regardless of speed:
  ```powershell
  & "D:\Game Dev\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64_console.exe" --path "<game>" --write-movie "<session>\media\clip.avi" --fixed-fps 30 --quit-after 450 [res://scenes/x.tscn]
  ```
  Then `record.ps1 -From clip.avi -Out clip.mp4` and delete the `.avi`. `--quit-after` counts frames. Use a scene or a debug flag that plays the feature without input.
- **Screenshot from game code** (best for exact framing): `get_viewport().get_texture().get_image().save_png("user://shot.png")` behind a debug key or command-line flag, or `--write-movie shot.png --quit-after 1` for the first frame of a scene.
- **Interactive:** run the game and use `capture.ps1 -Window "<window title>"` / `record.ps1`.

## Unreal

`HighResShot 1920x1080` in the console writes to `Saved\Screenshots\`; copy the file into `media/`. For video, `record.ps1 -Window UnrealEditor` while in PIE, or render a Sequencer shot with Movie Render Queue.

## Generated assets (ComfyUI, Pipeline)

Copy representative outputs (concept images, turnarounds) into `media/` at a reasonable size. For a GLB, screenshot it in the Forge viewer or Blender rather than linking the model itself.
