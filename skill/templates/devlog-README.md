# {{PROJECT}} devlog

The working memory of this project: why it exists, what was planned, what each feature is and how it got built, and where the last agent left off. Agents read the markdown and JSON here. Humans open `index.html` (or `workspace.html` for the workspace), which is generated.

Full guide to this corpus, for every project: `D:\Game Dev\devlog\GUIDE.md`.

## Read in this order

1. `HANDOFF.md`: the current state, what is in flight, what to do next, what to watch out for. Always read it.
2. `OVERVIEW.md`: what the project is, how it is built, where things live.
3. `features/<slug>.md`: one file per feature, for the features your task touches. Status, decisions, key files, gotchas.
4. `WORKLOG.md`: commit-by-commit history, newest first. Skim the top when you need recent context.
5. `sessions/<date>-<slug>/session.json`: a single session in full (the prompt, decisions, timeline, tests). Only when you need the detail behind a decision.
6. `ideation/` and `planning/`: where the project and its big features came from, and the plans they are built against.

## Layout

```
devlog/
  README.md        this file
  OVERVIEW.md      what the project is (kept current)
  HANDOFF.md       current state and next steps (rewritten at the end of every session)
  WORKLOG.md       generated: one entry per commit
  ideation/        early ideas, pitches, references, open-ended exploration
  planning/        plans, specs, slice/milestone breakdowns
  features/        <slug>.md per feature: the agent memory for that feature
  sessions/        <YYYY-MM-DD>-<slug>/ session.json (source), index.html (generated), media/
  index.html       generated human view
```

Do not edit `WORKLOG.md` or any `.html` by hand: change `session.json` or the markdown and run `devlog.py render`.
