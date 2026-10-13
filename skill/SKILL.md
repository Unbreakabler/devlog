---
name: devlog
description: Document a work session in the D:\Game Dev projects (Forge, the games, Pipeline/Setup/Tools) for human reviewers and future agents. Use at the end of every session that changed files there, before the final reply; when the Stop hook says "devlog"; when starting a new feature or project (feature file, ideation or planning doc); and when a visible feature changes and needs screenshots or video. Writes the session log (prompt, decisions, timeline, media, commits), updates feature memory, WORKLOG and HANDOFF, and renders the HTML pages.
---

# devlog

Every project under `D:\Game Dev` keeps a `devlog/` corpus: ideation, planning, overview, one memory file per feature, a commit-by-commit worklog, a handoff note, and one folder per session with a human-readable HTML report. `session.json` and the markdown files are the source; HTML and `WORKLOG.md` are generated.

Script: `python "D:\Game Dev\devlog\skill\scripts\devlog.py" <command>` (called `devlog.py` below). Corpus guide for reading: `D:\Game Dev\devlog\GUIDE.md`. Field-by-field format: [reference/session-schema.md](reference/session-schema.md). Screenshots and video: [reference/capture.md](reference/capture.md).

## Which project

The log goes in the project most of the work landed in: `Forge\devlog`, `<Game>\devlog`, or `D:\Game Dev\devlog` (the "Workspace" project) for Pipeline, Setup, Tools, ComfyUI and cross-project work. A new game or tool folder gets its corpus with `devlog.py init "<folder>"`. A session that touched two projects logs once, in the main one, and updates feature files and HANDOFF.md in both.

## While working

These make the end-of-session write-up accurate. Do them as you go, not from memory at the end.

- **New feature?** `devlog.py feature "<project dir>" <slug> --name "<Name>" [--parent <group slug>] [--order <n>]` and fill in *What it is*. Features nest: a feature whose front matter says `parent: <slug>` sits under that feature file (the group); groups roll up their children's status ("2/4 done") and show their combined history. Put slices, milestones or sub-parts of one capability under a group; a small standalone feature needs no parent. Regroup an existing feature with the same command (`--parent ""` ungroups). Tag sessions with the most specific feature they touched; the group picks them up. A substantial feature or a new project also gets a plan in `devlog/planning/` (or a link there to an existing plan); open-ended exploration goes in `devlog/ideation/`. See the READMEs in those folders.
- **Decisions.** When you or the user choose between real alternatives (approach, library, scope, trade-off), note the choice, the reason and the rejected options. Questions answered through AskUserQuestion are captured automatically.
- **Media.** When something visible is added or changes (UI, viewport, a game scene, a generated asset), capture it right after it works: a screenshot at minimum, a short video when motion or interaction is the point. Save straight into the session's `media/` folder (run `devlog.py start` early to create it) or register files with `devlog.py media`. Recipes per project are in [reference/capture.md](reference/capture.md). If capture is impossible (no display, app cannot run), say so in the timeline instead of skipping silently.

## At the end of the session

Run this before your final reply. It is not optional: the Stop hook blocks the first stop of any session that edited workspace files without an up-to-date log.

1. **Open the log.** `devlog.py start --project "<project dir>" --slug <short-slug> --title "<Title>"` (add `--transcript <path>` if the hook gave you one). It prints the `session.json` path, creating it or finding the existing one for this session. It fills the prompt, your later messages, questions asked, files changed, commits, model and times from the transcript and git: never type those in.
2. **Write the session.** Edit `session.json` (format in [reference/session-schema.md](reference/session-schema.md)):
   - `title`, `summary` (2 to 4 sentences: what was asked, what exists now), `outcome` (`done`, `partial`, `blocked`, `abandoned`).
   - `features`: slugs of the feature files touched.
   - `decisions`: every real choice, with `why` and `alternatives`, and `by` (`user` or `agent`).
   - `timeline`: the development process in order. Steps, discoveries, problems and how they were fixed, test runs. Attach media to the step that produced it. A reviewer should be able to follow how the feature came together, including dead ends.
   - `media` captions, `tests` (what was verified and how, including what was not), `commit_notes` (per commit hash: why, and anything the diff does not show), `uncommitted` (what is left in the working tree), `next_steps`, `open_questions`.
3. **Update feature memory.** For each feature touched, edit `devlog/features/<slug>.md`: front-matter `status` and `summary`, *Current state* (rewrite so it is true now), and append dated entries to *Design decisions*, *Key files*, *Gotchas*, *History* (link the session). This file is what the next agent reads, so put the non-obvious things here: why it is built this way, what broke, what to avoid.
4. **Rewrite `devlog/HANDOFF.md`** for the project: state right now, what is in flight (committed or not), next steps, what to watch out for. Replace, do not append; history lives in sessions and WORKLOG.
5. **Keep `OVERVIEW.md` true** if the project's shape, status or layout changed. New ideation or planning docs go in their folders.
6. **Render.** `devlog.py render` (or `devlog.py render "<session dir>"`). This refreshes the auto fields, writes the session page, the project page, `WORKLOG.md`, the workspace home `D:\Game Dev\devlog\index.html` and the browser `D:\Game Dev\devlog\browse.html`. Fix anything it reports.
7. **Tell the user** in your final reply where the session page is, as a link to `<project>/devlog/sessions/<dir>/index.html`, and mention `D:\Game Dev\devlog\browse.html` (sidebar browser over every page; `browse.html#/<path from devlog/>` opens it at a given page).

Commit the devlog changes with the code when you commit (WORKLOG lags one commit behind; that is expected). Do not commit when the user has not asked for commits.

## The devlog as a dev tool

`Start-Devlog.bat` (workspace root) runs `devlog.py serve`: the same browser at http://127.0.0.1:8765/ plus actions. From it the user sets a feature's status (header dropdown, or right-click a feature in the sidebar) and launches Claude sessions on a feature or group (▶ Run in Claude), a free prompt in a project, or a resume of a logged session. Launches run in a terminal window or in the background, are recorded in `D:\Game Dev\devlog\runs\<id>.json`, and show under **Runs** with live status and recent activity. Its command palette (Ctrl+K, or speak with Alt+M) does all of this by phrase: "brainstorm X in Forge", "new feature Y under Z", "describe the map stage", "plan slice 7", "mark this done", "what's next". Brainstorm, describe and plan open Claude sessions whose prompts ask you to interview the user and write the result into `ideation/`, the feature file, or `planning/`; follow them. Features created from the palette start from the template with only a name (and maybe a summary and parent): fill in the rest as you learn it. The user can dictate prompts and notes (mic buttons, Alt+M); speech is transcribed on this PC by Whisper (`scripts/devlog_stt.py`). Notes land in a feature file's `## Notes` section or as a new `ideation/` doc: treat them as the user's own words, and fold anything lasting into the feature's other sections when you work on it.

If you were started that way, your environment has `DEVLOG_RUN_ID` (and, in a terminal run, `DEVLOG_TRANSCRIPT`, which `devlog.py` uses automatically). Your prompt names the feature: work on it, keep its feature file's `status` true (`done` only when complete and verified), and log the session as usual; `start` links your session log to the run.

## Rules

- Write for two readers: the human reviewer (summary, decisions, timeline, media: plain language, why over what) and the next agent (feature files, HANDOFF: precise, file paths, gotchas).
- Never invent or reconstruct the prompt, messages, commits or test results. Auto fields come from the transcript and git; your fields describe what actually happened, including failures and what was not verified.
- One session, one log. A resumed session updates its existing log; `start` finds it by session id.
- Subagents do not write devlog entries. They return their decisions and findings to the main agent, which logs them.
- A session the user says not to log, or with only trivial edits: `devlog.py skip --reason "<why>"` (satisfies the hook).
- Edit only `session.json`, markdown, and `media/`. Never hand-edit `index.html`, `workspace.html`, `browse.html` or `WORKLOG.md`; page styling lives in `devlog.py` (`CSS`) and `templates/browse.html`.
- Pages are dark by default (the user's standing preference); keep any new styling dark-first.
