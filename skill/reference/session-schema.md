# session.json format

One file per session at `<project>/devlog/sessions/<YYYY-MM-DD>-<slug>/session.json`. Created by `devlog.py start`; the fields above `_auto` are yours, the ones below are overwritten by `devlog.py render` from the transcript and git. Text fields accept inline markdown (`code`, **bold**, [links](url)).

## Your fields

| Field | Type | What goes in it |
| --- | --- | --- |
| `title` | string | Short name of the work, e.g. "Slice 3: both GPUs". |
| `summary` | string | 2 to 4 sentences: what was asked, what exists now, anything important left undone. Shown on every index. |
| `outcome` | string | `done`, `partial`, `blocked`, `abandoned` (`in-progress` until set). |
| `features` | string[] | Slugs of `devlog/features/<slug>.md` this session worked on. Drives the per-feature history on the project page. |
| `decisions` | object[] | `{title, choice, why, alternatives: [..], by: "user"\|"agent"}`. One per real choice. `title` is the question ("Where do session logs live?"), `choice` the answer. |
| `timeline` | object[] | `{at?, kind?, text, media?: ["media/x.png"]}` in order. `kind`: `step`, `discovery`, `problem`, `fix`, `test`, `decision`. `at` is an ISO time if you know it. This is the development-process story. |
| `media` | object[] | `{file: "media/x.png", caption, feature?}`. Added by `devlog.py media` or by hand for files you saved into `media/`. Captions say what the reader is looking at and why it matters. `feature` tags it for the feature history (untagged media goes to the session's feature when it has exactly one). |
| `tests` | object[] | `{what, result: "pass"\|"fail"\|"skipped", detail}`. Include what was not verified. |
| `commit_notes` | object | `{"<hash or short hash>": "why, and what the diff does not show"}`. Rendered into the session page and WORKLOG.md. |
| `uncommitted` | string | What is left uncommitted in the working tree, if anything. |
| `next_steps` | string[] | Concrete next actions. |
| `open_questions` | string[] | Things that need the user's input or more investigation. |

## Auto fields (do not edit)

`project`, `session_ids`, `transcripts`, `agent` (model id), `started`, `ended`, `prompt` (first message, verbatim), `followups` (later user messages), `asked` (AskUserQuestion questions and answers), `files_changed`, `commits` (`{repo, hash, short, at, subject}` from `git log --since=<started>` in every repo touched), `git_status` (uncommitted change counts at render time), `updated`.

## Example

```json
{
  "schema": 1,
  "title": "Slice 3: both GPUs",
  "summary": "Implemented slice 3 of the MVP plan: jobs now fan out across the 5080 and the 4080 Super with model affinity and lost-machine fallback. Gates measured on both GPUs except the 85% utilisation gate, which needs the agent installed on the node.",
  "outcome": "partial",
  "features": ["render-farm", "forge-agent"],
  "decisions": [
    {"title": "How does Forge reach the node's GPU stats?", "choice": "A small `forge-agent.exe` on the node, polled over HTTP on :8190 with a token.",
     "why": "ComfyUI does not expose utilisation; nvidia-smi only runs locally.", "alternatives": ["WMI remoting", "SSH + nvidia-smi"], "by": "agent"}
  ],
  "timeline": [
    {"kind": "step", "text": "Added `forge-sched` machine registry with capability check (TRELLIS.2 excluded on the 4080)."},
    {"kind": "problem", "text": "Round of 4 landed 3 on the 5080: affinity outweighed spread when both were idle."},
    {"kind": "fix", "text": "Spread wins when the model is loaded on both; affinity only breaks ties.", "media": ["media/fanout-2x2.png"]}
  ],
  "media": [{"file": "media/fanout-2x2.png", "caption": "A round of 4: two options from each GPU (badges top-left).", "feature": "render-farm"}],
  "tests": [{"what": "cargo test --workspace", "result": "pass", "detail": "212 tests"},
            {"what": "Pull the node's network cable mid-round", "result": "pass", "detail": "jobs moved to the 5080, no error toast"}],
  "commit_notes": {"a1b2c3d": "Scheduler and agent; the UI status panel follows in the next commit."},
  "uncommitted": "",
  "next_steps": ["Install forge-agent on the node and run `npm run fanout` for the utilisation gate"],
  "open_questions": ["Should the 4080 take background 3D jobs when the 5080 is idle?"]
}
```
