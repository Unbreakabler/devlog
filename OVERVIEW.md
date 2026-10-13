# Workspace: overview

The shared side of `D:\Game Dev`: the two-PC asset pipeline (concept to 3D to export), ComfyUI and its MCP, machine setup scripts, the engines, and the conventions that apply to every project, including this devlog framework.

## Status

Workstation (jon-gaming, RTX 5080) and generation node (RTX 4080 Super, mapped as `P:`) are set up; ComfyUI runs on both and Forge drives them. The devlog framework was added on 2026-10-13.

## How it is built

- Machine setup: `Setup\Run-Setup.bat` / `Setup-Workstation.ps1` (idempotent), node setup via `Setup\Prompt-For-Generation-Node.md`. Overview and daily flow: `README - Pipeline Setup.md`.
- Asset pipeline folders: `Pipeline\00_Concept` to `06_Export`, shared as `\\jon-gaming\Pipeline`; `Pipeline\_Forge` holds Forge's agent and node files.
- ComfyUI portable: `Tools\ComfyUI_windows_portable`, started by `Start-ComfyUI.bat`; MCP server in `Tools\comfy-mcp`; saved workflows in `Tools\workflows` and `Pipeline\_Workflows`.
- Engines: `Godot_v4.7.2-stable_mono_win64`, `UE_5.8`.

## Where things live

- Rules for agents in every project: `CLAUDE.md` (this folder).
- devlog skill, scripts and templates: `devlog\skill\` (also linked at `%USERPROFILE%\.claude\skills\devlog`); Stop hook in `%USERPROFILE%\.claude\settings.json`.
- Corpus guide: `devlog\GUIDE.md`. Browser over every page: `devlog\browse.html`. Home page across projects: `devlog\index.html`; this project's page: `devlog\workspace.html`.

## Conventions

- Every project folder that gets real work has a `devlog\` (create with `devlog.py init`).
- Pipeline and setup changes are logged here, not in a game's devlog.
