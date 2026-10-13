# How to use the devlog corpus (for agents)

Every project under `D:\Game Dev` records its history in a `devlog/` folder: why it exists, what was planned, what each feature is and how it was built, decisions and the reasons for them, and where the last agent stopped. This guide says how to read it efficiently. How to *write* it is in the `devlog` skill (`D:\Game Dev\devlog\skill\SKILL.md`).

## Where the corpora are

| Project | Corpus | Covers |
| --- | --- | --- |
| Workspace | `D:\Game Dev\devlog\` | Pipeline, Setup, Tools, ComfyUI, machines, cross-project work, this framework |
| Forge | `D:\Game Dev\Forge\devlog\` | The Forge desktop app (asset pipeline / render farm) |
| Extraction Game | `D:\Game Dev\Extraction Game\devlog\` | The game |
| Any new project | `<folder>\devlog\` | Created with `devlog.py init "<folder>"` |

Each corpus has the same shape:

```
README.md     reading order for this project
OVERVIEW.md   what the project is, how it is built, where things live      (kept current)
HANDOFF.md    state right now, in-flight work, next steps, landmines        (rewritten every session)
WORKLOG.md    one entry per commit, newest first                            (generated)
ideation/     early ideas and explorations                                 (append-only)
planning/     committed plans and specs, or links to them                  (edited with a ## Changes log)
features/     <slug>.md: the memory for one feature                         (kept current + dated history)
sessions/     <date>-<slug>/session.json (+ index.html, media/)             (one per Claude session)
```

## Start of a task: orient in this order

Read only as deep as the task needs. Most tasks stop at step 3.

1. **`HANDOFF.md`** of the project you are working in. Always. It tells you what is half-done and what not to break.
2. **`OVERVIEW.md`**, unless you already know the project well in this session.
3. **The feature files** your task touches. Find them by name in `features/`, or search: `grep -il "<keyword>" devlog/features/*.md`. The front matter `status:` tells you `idea`, `planned`, `in-progress`, `done` or `parked`. Features nest: `parent: <slug>` puts a feature under a group feature (find a group's members with `grep -l "^parent: <slug>" devlog/features/*.md`), and `order:` sorts siblings. Read the group file for the shared intent and decisions, then the member you are changing. Read *Current state*, *Design decisions*, *Gotchas* before changing that feature's code.
4. **The top of `WORKLOG.md`** when you need to know what changed recently or why a commit exists.
5. **A `session.json`** when you need the full story behind something: the exact prompt, every decision with alternatives, the timeline including dead ends, test results. Find the session from the feature's *History* or the WORKLOG link. Read the JSON, not the HTML.
6. **`planning/` and `ideation/`** when the task is about direction or scope: what the plan says the next step is, what was already considered and dropped.

## Answering particular questions

- *"Why is X built this way?"* Feature file *Design decisions*, then `grep -l "<X>" devlog/sessions/*/session.json` and read the `decisions` and `timeline` there.
- *"What happened last time / where did we leave off?"* `HANDOFF.md`, then the newest session folder.
- *"Has this been tried before?"* Search `timeline` entries of kind `problem` / `fix` and the feature *Gotchas*; check `ideation/` for dropped ideas.
- *"What did the user actually ask for?"* The `prompt` and `followups` fields are verbatim from the transcript. Prefer them over summaries.
- *"What is the plan?"* `planning/` (and the plans it links, e.g. `Forge/docs/`). Plans can be ahead of reality; HANDOFF and feature status say what is actually done.

## Trust and staleness

- **Code and git are the truth.** The devlog explains intent and history; it can lag. If a feature file names a file, function or flag, check it still exists before relying on it. If the devlog is wrong, fix it in your end-of-session update.
- `prompt`, `followups`, `asked`, `commits`, `files_changed` are machine-extracted and reliable. `summary`, `decisions`, `timeline` were written by the agent at the time: good for *why*, check *what* against the code.
- Newer beats older. A decision in a later session or a later dated line in a feature file supersedes an earlier one.
- Generated files (`WORKLOG.md`, `index.html`, `workspace.html`, `browse.html`) are never edited by hand; their content comes from `session.json` and the markdown.

## Humans read the HTML

`D:\Game Dev\devlog\browse.html` is the way in: a sidebar browser over every page (projects, sessions, features, a timeline, a media gallery, search). `D:\Game Dev\devlog\index.html` is the home page across all projects; each project has `devlog/index.html` (the workspace project: `devlog/workspace.html`) with features, their build history with screenshots and video, sessions, the handoff and the plans. Each session has its own page. When you finish a session, link the user to its page.

## Launched from the devlog

Sessions can be started from the devlog server (`Start-Devlog.bat`) on a feature or group. Their launch records live in `devlog/runs/*.json` (prompt, mode, permissions, session id, outcome), and their session logs carry a `run` field. A run prompt for a group lists its unfinished members in order: finish, verify and log each before the next.

## End of a task

Follow the `devlog` skill: log the session, update the feature files, rewrite HANDOFF.md, render. The Stop hook reminds you if you forget.
