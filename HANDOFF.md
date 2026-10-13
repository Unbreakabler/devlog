# Workspace: handoff

Updated 2026-10-13, after turning the devlog browser into a dev tool.

## State right now

- This folder is its own repo (github.com/Unbreakabler/devlog) and now also holds the tool: `skill/` (moved from `D:\Game Dev\.claude\skills\devlog`). The move and the latest corpus updates are **not committed yet**.

- devlog framework live: skill, scripts, rules (`CLAUDE.md`), corpus guide (`devlog/GUIDE.md`), Stop hook in the user settings. Corpora for Workspace, Forge (backfilled, slices grouped under three features) and Extraction Game; any folder with a `devlog/` up to 4 levels deep is picked up.
- `Start-Devlog.bat` runs the devlog server (http://127.0.0.1:8765/): status changes, Claude launches per feature or group (terminal window or background), resume, a Runs view with live activity. Tested end to end, including security checks.
- Dictation in the dev tool: mic buttons on launch prompts, search and notes (Alt+M), transcribed locally by Whisper large-v3-turbo on the 5080 (faster-whisper 1.2.1 + PyAV 16.0.1 in Python 3.12's user site; model in the Hugging Face cache). Notes save into a feature's `## Notes` or a new ideation doc.
- Command palette (Ctrl+K / Alt+M to speak) replaces the sidebar search: navigate, set status, create and describe features, move them between groups, brainstorm, plan, run, resume, next steps, open in Explorer/VS Code. 27 example phrases checked; actions tested end to end and reverted.
- **Blocker for launches:** the Claude Code CLI on this PC is not logged in (`claude auth status` → loggedIn false). Jon signs in once with the "Log in to Claude Code" button (opens `claude auth login` in a terminal).
- ffmpeg 9.0.2 and Playwright's ffmpeg are installed. `D:\Game Dev` is not a Git repo; Forge's and Extraction Game's `devlog/` folders are untracked in their repos.

## In flight

Nothing.

## Next steps

1. Jon: log the CLI in, then launch a real session on a planned slice (e.g. Forge slice 4) and check its run links to its devlog entry.
2. First live check of the Stop hook happens in the next working session.

## Watch out for

- Restart the server after editing `devlog.py` or `devlog_server.py`.
- `claude --bg` ignores `--session-id`; the server maps the short id it prints to the real session (`resolve_bg`).
- Never hand-edit generated files (`index.html`, `workspace.html`, `browse.html`, `WORKLOG.md`); keep styling dark-first.
- Write text containing Windows paths with the Write/Edit tools, not shell heredocs.
- The in-app browser pane cannot run `browse.html` (static `file://` snapshot); test in Edge via Playwright, or against the server.
