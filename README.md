# devlog

A documentation framework and dev tool for the projects under `D:\Game Dev`, for two readers: the person reviewing the work, and the Claude agents doing it. Every Claude session leaves an HTML report (the prompt, decisions, how it was built, screenshots and video) and updates per-project memory (overview, handoff, one file per feature, ideation, plans, a commit-by-commit worklog). A local server turns the pages into a dev tool: a command palette, typed or spoken, for navigating, setting feature status, starting ideation, describing and planning features, and launching Claude sessions.

This repo holds both halves:

```
devlog/                     this repo, cloned to <workspace>\devlog (D:\Game Dev\devlog)
  skill/                    the devlog skill and tool
    SKILL.md                what agents do during and at the end of a session
    reference/              session.json format, screenshot and video recipes
    scripts/devlog.py       init, start, media, feature, render, hook, serve, install
    scripts/devlog_server.py  the dev tool server (127.0.0.1:8765)
    scripts/devlog_stt.py   local Whisper dictation
    scripts/capture*.ps1, record.ps1, capture_web.mjs   screenshots and video
    templates/              feature, handoff, overview templates and the browser page
  GUIDE.md                  how agents read any project's devlog
  README.md, OVERVIEW.md, HANDOFF.md, WORKLOG.md, features/, ideation/, planning/, sessions/
                            the workspace's own devlog (Pipeline, Setup, Tools, and this tool)
  index.html, browse.html, workspace.html   generated pages
```

Each other project keeps its own corpus in its own repo (`Forge\devlog`, `Extraction Game\devlog`, ...). The tool finds every folder with a `devlog/` up to four levels below the workspace.

## Set up a PC

1. Clone this repo to `<workspace>\devlog` (here `D:\Game Dev\devlog`; elsewhere set `GAMEDEV_ROOT` to the workspace).
2. `python devlog\skill\scripts\devlog.py install`: links the skill into `%USERPROFILE%\.claude\skills\devlog` (so every Claude session can use it) and adds the Stop hook to `%USERPROFILE%\.claude\settings.json` (so every session that changes files logs itself).
3. Copy the workspace rules into `<workspace>\CLAUDE.md` if they are not there (the "Devlog: required in every project here" section).
4. Optional: dictation needs `python -m pip install --user faster-whisper nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" av==16.0.1`; video capture needs ffmpeg (`winget install --id Gyan.FFmpeg -e`); launching sessions needs Claude Code logged in once (`claude auth login`, or the palette's "Log in to Claude Code").

Use it: `Start-Devlog.bat` in the workspace (or `python devlog\skill\scripts\devlog.py serve --open`), then Ctrl+K. Without the server, `browse.html` opens read-only from disk.

## For agents reading this corpus

This folder is also the Workspace project's devlog. Read in this order:

1. `HANDOFF.md`: the current state, what is in flight, what to do next, what to watch out for. Always read it.
2. `OVERVIEW.md`: what the project is, how it is built, where things live.
3. `features/<slug>.md`: one file per feature, for the features your task touches. Status, decisions, key files, gotchas.
4. `WORKLOG.md`: commit-by-commit history, newest first.
5. `sessions/<date>-<slug>/session.json`: a single session in full. Only when you need the detail behind a decision.
6. `ideation/` and `planning/`: where things came from and the plans they are built against.

The full guide for every project's corpus is `GUIDE.md`; how to write to it is `skill/SKILL.md`. Do not edit `WORKLOG.md` or any `.html` by hand: change `session.json` or the markdown and run `devlog.py render`.
