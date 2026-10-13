#!/usr/bin/env python3
"""devlog: session logs, feature memory and HTML reports for the projects under D:\\Game Dev.

Every project (Forge, each game, and the workspace itself for Pipeline/Setup/Tools work) has a
`devlog/` folder. session.json files are the source of truth; everything else here (session
pages, project index pages, WORKLOG.md, the workspace index) is generated from them.

Commands:
  init DIR [--name NAME]         scaffold DIR/devlog (idempotent)
  start [--project DIR] [--slug S] [--title T] [--transcript P]
                                 find or create this session's log; prints the session.json path
  media SESSION FILE [--caption C] [--feature F] [--move]
                                 copy a screenshot/video into SESSION/media and register it
  feature PROJECT_DIR SLUG [--name NAME] [--parent GROUP] [--order N]
                                 create devlog/features/SLUG.md, or regroup an existing one
  render [SESSION] [--transcript P] [--all]
                                 refresh auto fields from the transcript, write every HTML page and WORKLOG.md
  where [--transcript P]         show the current transcript, session id and its log
  skip --reason R [--transcript P]
                                 record that this session deliberately has no log (satisfies the Stop hook)
  hook                           Stop-hook entry point (reads the hook JSON on stdin)
  install                        link this checkout's skill into ~/.claude/skills and add the Stop hook (idempotent)
  serve [--port 8765] [--open]   the browser as a dev tool: set feature status, launch and track Claude sessions
                                 (devlog_server.py; Start-Devlog.bat in the workspace starts it)

Standard library only. Set GAMEDEV_ROOT to move the workspace.
"""
import argparse
import datetime as dt
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("GAMEDEV_ROOT", r"D:\Game Dev")).resolve()
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / "templates"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
SKIPPED = WORKSPACE / "devlog" / ".skipped.json"
RUNS_DIR = WORKSPACE / "devlog" / "runs"  # one JSON per Claude session launched from the devlog browser
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- time and paths

def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_from_ts(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def local(s, fmt="%Y-%m-%d %H:%M"):
    t = parse_ts(s)
    return t.astimezone().strftime(fmt) if t else ""


def duration(a, b):
    ta, tb = parse_ts(a), parse_ts(b)
    if not (ta and tb):
        return ""
    mins = int((tb - ta).total_seconds() // 60)
    return f"{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{mins} min"


def slugify(s, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:limit].rstrip("-") or "session"


def rel(p, base=WORKSPACE):
    try:
        return Path(p).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def is_corpus_path(p):
    """True for files inside a project's devlog/ corpus. The devlog tool itself (this skill, which lives in the
    workspace devlog repo) is code, so editing it is work."""
    try:
        rp = Path(p).resolve()
    except OSError:
        rp = Path(p)
    try:
        rp.relative_to(SKILL_DIR)
        return False
    except ValueError:
        pass
    return "devlog" in (x.lower() for x in rp.parts)


def in_workspace(p):
    try:
        Path(p).resolve().relative_to(WORKSPACE.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_work_path(p):
    return bool(p) and in_workspace(p) and not is_corpus_path(p)


# Folders never searched for project devlogs: engines, tool installs, build output, dependencies, engine caches.
SKIP_DIRS = {".git", ".svn", ".claude", ".vs", ".vscode", ".idea", ".godot", ".import", "node_modules", "target", "dist", "build",
             "bin", "obj", "Binaries", "Intermediate", "Saved", "DerivedDataCache", "Content", "Library", "Temp", "Logs",
             "UE_5.8", "Engine", "FeaturePacks", "Templates", "ComfyUI_windows_portable", "python_embeded", "venv", ".venv",
             "__pycache__", "devlog", "comfy-output", "Projects"}
PROJECT_DEPTH = 4  # how many folder levels below the workspace a project may sit
_PROJECTS = None


def projects():
    """Every folder under the workspace that has a devlog/: the workspace first, then the rest by path (cached per run)."""
    global _PROJECTS
    if _PROJECTS is None:
        found = []
        root_depth = len(WORKSPACE.parts)
        for dirpath, dirnames, _ in os.walk(WORKSPACE):
            here = Path(dirpath)
            if "devlog" in dirnames and here != WORKSPACE:
                found.append(here)
            depth = len(here.parts) - root_depth
            dirnames[:] = [] if depth >= PROJECT_DEPTH - 1 else sorted(
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith(("Godot_", "UE_")))
        _PROJECTS = ([WORKSPACE] if (WORKSPACE / "devlog").is_dir() else []) + sorted(found, key=lambda p: rel(p).lower())
    return list(_PROJECTS)


def forget_projects():
    global _PROJECTS
    _PROJECTS = None


def project_of(path):
    """The deepest project folder (with a devlog/) containing path; the workspace otherwise."""
    p = Path(path).resolve()
    best = WORKSPACE
    for proj in projects():
        try:
            p.relative_to(proj.resolve())
            if len(proj.parts) > len(best.parts):
                best = proj
        except ValueError:
            pass
    return best


def project_page(proj):
    """The project's human page. The workspace's own page is workspace.html; devlog/index.html there is the home."""
    proj = Path(proj)
    return proj / "devlog" / ("workspace.html" if proj == WORKSPACE else "index.html")


def href(from_dir, target):
    return os.path.relpath(target, from_dir).replace("\\", "/").replace(" ", "%20")


def project_name(proj):
    """Workspace, or the project's path below it (Forge, Games/Foo)."""
    return "Workspace" if Path(proj).resolve() == WORKSPACE.resolve() else rel(proj)


def git_root(path):
    p = Path(path).resolve()
    for d in [p] + list(p.parents):
        if (d / ".git").exists():
            return d
        if d == WORKSPACE.resolve():
            break
    return None


def git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- transcripts

def find_transcript():
    """The most recently written top-level transcript for a session under the workspace."""
    prefix = re.sub(r"[^A-Za-z0-9]", "-", str(WORKSPACE))
    cands = []
    if CLAUDE_PROJECTS.is_dir():
        for d in CLAUDE_PROJECTS.iterdir():
            if d.is_dir() and d.name.lower().startswith(prefix.lower()):
                cands += list(d.glob("*.jsonl"))
    return max(cands, key=lambda f: f.stat().st_mtime) if cands else None


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_transcript(path):
    """Pull what a session log needs out of a Claude Code transcript (.jsonl)."""
    info = {"session_id": Path(path).stem, "title": None, "model": None, "started": None, "ended": None,
            "cwd": None, "messages": [], "asked": [], "files": {}, "last_work": None}
    questions = {}

    def work(ts):
        if ts and (info["last_work"] is None or ts > info["last_work"]):
            info["last_work"] = ts

    def touched(p, ts):
        if is_work_path(p):
            info["files"][str(Path(p).resolve())] = ts
            work(ts)

    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return info
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            kind, ts = d.get("type"), d.get("timestamp")
            if kind in ("user", "assistant") and ts and not d.get("isSidechain"):
                info["started"] = info["started"] or ts
                info["ended"] = ts
            if kind == "custom-title":
                info["title"] = d.get("customTitle") or info["title"]
            if kind == "file-history-delta":
                parent = ((d.get("backup") or {}).get("realParentDir"))
                name = Path(d.get("trackingPath") or "").name
                if parent and name:
                    touched(Path(parent) / name, ts)
            msg = d.get("message") or {}
            if kind == "assistant" and msg.get("model") and not msg["model"].startswith("<"):
                info["model"] = msg["model"]
            if kind == "user" and (d.get("origin") or {}).get("kind") == "human":
                info["cwd"] = info["cwd"] or d.get("cwd")
                text = block_text(msg.get("content")).strip()
                if text:
                    info["messages"].append({"at": ts, "text": text})
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name, inp = b.get("name"), b.get("input") or {}
                    if name in EDIT_TOOLS:
                        touched(inp.get("file_path") or inp.get("notebook_path"), ts)
                    elif name in SHELL_TOOLS and re.search(r"\bgit\b[^\n|;&]*\bcommit\b", str(inp.get("command", ""))):
                        work(ts)
                    elif name == "AskUserQuestion":
                        questions[b.get("id")] = (ts, [q.get("question", "") for q in inp.get("questions") or []])
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in questions:
                    at, qs = questions.pop(b["tool_use_id"])
                    info["asked"].append({"at": at, "questions": qs, "answer": block_text(b.get("content")).strip()})
    return info


# ---------------------------------------------------------------- session logs

def find_run(session_id):
    """The devlog-browser launch (devlog/runs/*.json) that started this session, if any."""
    for f in sorted(RUNS_DIR.glob("*.json"), reverse=True) if RUNS_DIR.is_dir() else []:
        run = load_json(f, {}) or {}
        if run.get("session_id") == session_id or (run.get("bg_id") and session_id.startswith(run["bg_id"])):
            return run
    return None


def session_dirs():
    for proj in projects():
        sd = proj / "devlog" / "sessions"
        if sd.is_dir():
            yield from sorted(d for d in sd.iterdir() if (d / "session.json").is_file())


def find_log(session_id):
    for d in session_dirs():
        log = load_json(d / "session.json", {})
        if session_id in (log.get("session_ids") or []):
            return d
    return None


def new_log(sid, title):
    return {
        "schema": 1,
        "title": title,
        "summary": "",
        "outcome": "in-progress",
        "features": [],
        "decisions": [],
        "timeline": [],
        "media": [],
        "tests": [],
        "commit_notes": {},
        "uncommitted": "",
        "next_steps": [],
        "open_questions": [],
        "_auto": "Fields below are refreshed from the transcript and git by `devlog.py render`; edit the ones above.",
        "project": "",
        "session_ids": [sid],
        "transcripts": [],
        "agent": "",
        "started": "",
        "ended": "",
        "prompt": "",
        "followups": [],
        "asked": [],
        "files_changed": [],
        "commits": [],
        "git_status": [],
        "updated": "",
    }


def refresh(sdir, log):
    """Re-derive the auto fields from the session's transcripts and git."""
    proj = sdir.parent.parent.parent
    log["project"] = project_name(proj)
    infos = [read_transcript(p) for p in log.get("transcripts") or [] if Path(p).is_file()]
    if infos:
        log["session_ids"] = sorted(set(log.get("session_ids") or []) | {i["session_id"] for i in infos})
        log["started"] = min(i["started"] for i in infos if i["started"]) if any(i["started"] for i in infos) else log.get("started", "")
        log["ended"] = max(i["ended"] for i in infos if i["ended"]) if any(i["ended"] for i in infos) else log.get("ended", "")
        log["agent"] = next((i["model"] for i in reversed(infos) if i["model"]), log.get("agent", ""))
        log["cwd"] = next((i["cwd"] for i in infos if i["cwd"]), log.get("cwd", ""))  # needed to resume the session
        msgs = sorted((m for i in infos for m in i["messages"]), key=lambda m: m["at"] or "")
        if msgs:
            log["prompt"] = msgs[0]["text"]
            log["followups"] = msgs[1:]
        log["asked"] = sorted((a for i in infos for a in i["asked"]), key=lambda a: a["at"] or "")
        files = {}
        for i in infos:
            files.update(i["files"])
    else:
        files = {str(WORKSPACE / f): None for f in log.get("files_changed") or []}

    # Commits made in any repo this session touched, from its start to now.
    repos = {git_root(f) for f in files} | {git_root(proj)}
    repos.discard(None)
    commits, status = [], []
    since = parse_ts(log.get("started"))
    for repo in sorted(repos):
        if since:
            out = git(repo, "log", "--since=" + since.isoformat(), "--format=%H%x1f%h%x1f%aI%x1f%s")
            for line in out.splitlines():
                h, short, at, subject = (line.split("\x1f") + ["", "", "", ""])[:4]
                commits.append({"repo": rel(repo), "hash": h, "short": short, "at": at, "subject": subject})
        dirty = [l for l in git(repo, "status", "--porcelain").splitlines() if l.strip()]
        if dirty:
            status.append({"repo": rel(repo), "changes": len(dirty)})
        # Files written through the shell never show up as edit tools: take uncommitted files modified during the session.
        until = parse_ts(log.get("ended"))
        if since and until:
            lo, hi = since.timestamp() - 60, until.timestamp() + 600
            for l in git(repo, "status", "--porcelain", "-uall").splitlines():
                p = repo / l[3:].split(" -> ")[-1].strip('"')
                try:
                    if is_work_path(p) and lo <= p.stat().st_mtime <= hi:
                        files.setdefault(str(p.resolve()), None)
                except OSError:
                    pass
    if infos or files:
        log["files_changed"] = sorted(rel(f) for f in files)
    if commits or since:
        log["commits"] = sorted(commits, key=lambda c: c["at"])
    log["git_status"] = status
    return log


def resolve_transcript(arg):
    # Sessions launched from the devlog browser know their transcript exactly (several may run at once).
    p = Path(arg) if arg else Path(os.environ["DEVLOG_TRANSCRIPT"]) if os.environ.get("DEVLOG_TRANSCRIPT") else find_transcript()
    if not p or not p.is_file():
        sys.exit("devlog: no transcript found; pass --transcript <path to session .jsonl>")
    return p


def cmd_start(a):
    tp = resolve_transcript(a.transcript)
    info = read_transcript(tp)
    sdir = find_log(info["session_id"])
    if not sdir:
        if a.project:
            proj = Path(a.project).resolve()
        else:
            # The project most of this session's edits landed in.
            counts = {}
            for f in info["files"]:
                p = project_of(f)
                counts[p] = counts.get(p, 0) + 1
            proj = max(counts, key=counts.get) if counts else project_of(info["cwd"] or WORKSPACE)
        if not (proj / "devlog").is_dir():
            init_project(proj)
        title = a.title or info["title"] or (info["messages"][0]["text"].splitlines()[0][:80] if info["messages"] else "Session")
        day = local(info["started"], "%Y-%m-%d") or dt.date.today().isoformat()
        base = proj / "devlog" / "sessions" / f"{day}-{slugify(a.slug or title)}"
        sdir, n = base, 2
        while sdir.exists():
            sdir, n = Path(f"{base}-{n}"), n + 1
        (sdir / "media").mkdir(parents=True)
        log = new_log(info["session_id"], title)
    else:
        log = load_json(sdir / "session.json")
    run = find_run(info["session_id"])
    if run:
        log["run"] = {k: run.get(k) for k in ("id", "mode", "feature", "permission_mode", "started")}
    if str(tp) not in log["transcripts"]:
        log["transcripts"].append(str(tp))
    save_json(sdir / "session.json", refresh(sdir, log))
    print(sdir / "session.json")


def cmd_media(a):
    sdir = Path(a.session).resolve()
    sdir = sdir.parent if sdir.name == "session.json" else sdir
    src = Path(a.file)
    if not src.is_file():
        sys.exit(f"devlog: no such file {src}")
    (sdir / "media").mkdir(exist_ok=True)
    dest = sdir / "media" / src.name
    n = 2
    while dest.exists() and dest.resolve() != src.resolve():
        dest, n = sdir / "media" / f"{src.stem}-{n}{src.suffix}", n + 1
    if dest.resolve() != src.resolve():
        (shutil.move if a.move else shutil.copy2)(src, dest)
    log = load_json(sdir / "session.json")
    entry = {"file": "media/" + dest.name, "caption": a.caption or "", "feature": a.feature or "", "at": now_iso()}
    log["media"] = [m for m in log.get("media", []) if m.get("file") != entry["file"]] + [entry]
    save_json(sdir / "session.json", log)
    print(entry["file"])


def cmd_render(a):
    if a.all:
        targets = list(session_dirs())
    elif a.session:
        s = Path(a.session)
        targets = [(s.parent if s.name == "session.json" else s).resolve()]
    else:
        info = read_transcript(resolve_transcript(a.transcript))
        sdir = find_log(info["session_id"])
        if not sdir:
            sys.exit("devlog: this session has no log yet; run `devlog.py start` first")
        targets = [sdir]
    touched = set()
    for sdir in targets:
        log = load_json(sdir / "session.json")
        if log is None:
            print(f"devlog: skipping {sdir} (session.json missing or invalid JSON)", file=sys.stderr)
            continue
        log = refresh(sdir, log)
        log["updated"] = now_iso()
        save_json(sdir / "session.json", log)
        (sdir / "index.html").write_text(render_session(sdir, log), encoding="utf-8")
        touched.add(sdir.parent.parent.parent)
        print(sdir / "index.html")
    for proj in (projects() if a.all else touched):
        render_project(proj)
        print(project_page(proj))
    render_workspace()
    print(WORKSPACE / "devlog" / "index.html")


def cmd_where(a):
    tp = resolve_transcript(a.transcript)
    info = read_transcript(tp)
    sdir = find_log(info["session_id"])
    print(f"transcript: {tp}\nsession_id: {info['session_id']}\nstarted:    {info['started']}\n"
          f"log:        {sdir / 'session.json' if sdir else '(none yet: run devlog.py start)'}\n"
          f"edited:     {len(info['files'])} workspace files, last work at {info['last_work']}")


def cmd_skip(a):
    info = read_transcript(resolve_transcript(a.transcript))
    data = load_json(SKIPPED, {})
    data[info["session_id"]] = {"at": now_iso(), "reason": a.reason}
    save_json(SKIPPED, data)
    print(f"devlog: session {info['session_id']} marked as not needing a log")


def cmd_hook(_a):
    """Stop hook: block the first stop of a session that changed workspace files but has no up-to-date log."""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if data.get("stop_hook_active") or not in_workspace(data.get("cwd") or ""):
        return
    tp, sid = data.get("transcript_path"), data.get("session_id")
    if not tp or not Path(tp).is_file():
        return
    info = read_transcript(tp)
    last = parse_ts(info["last_work"])
    if not last:
        return
    skipped = load_json(SKIPPED, {}).get(sid)
    if skipped and parse_ts(skipped.get("at")) and parse_ts(skipped["at"]) >= last:
        return
    sdir = find_log(sid)
    updated = parse_ts((load_json(sdir / "session.json", {}) or {}).get("updated")) if sdir else None
    if updated and updated >= last:
        return
    script = Path(__file__).resolve()
    state = f"Its log at {sdir} is older than your latest changes." if sdir else "It has no log yet."
    print(json.dumps({"decision": "block", "reason": (
        f"devlog: this session changed files under {WORKSPACE}. {state} Before finishing, follow the devlog skill "
        f"({SKILL_DIR / 'SKILL.md'}): log the session, update the feature files, WORKLOG notes and HANDOFF.md, then render. "
        f"Use --transcript \"{tp}\" with the script ({script}). "
        f"If the user said not to log this, or the changes were trivial, run: python \"{script}\" skip "
        f"--transcript \"{tp}\" --reason \"<why>\""
    )}))


# ---------------------------------------------------------------- project scaffolding

def init_project(proj, name=None):
    proj = Path(proj).resolve()
    dv = proj / "devlog"
    forget_projects()  # a new corpus must show up in this run's pages
    name = name or project_name(proj)
    for sub in ("ideation", "planning", "features", "sessions"):
        (dv / sub).mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": "devlog-README.md",
        "OVERVIEW.md": "OVERVIEW.md",
        "HANDOFF.md": "HANDOFF.md",
        "ideation/README.md": "ideation-README.md",
        "planning/README.md": "planning-README.md",
    }
    for dest, tpl in files.items():
        out = dv / dest
        if not out.exists():
            text = (TEMPLATES / tpl).read_text(encoding="utf-8").replace("{{PROJECT}}", name).replace("{{DATE}}", dt.date.today().isoformat())
            out.write_text(text, encoding="utf-8")
    return dv


def cmd_install(a):
    """Set this PC up to use the devlog from this checkout: the user-level skill link and the Stop hook."""
    link = Path.home() / ".claude" / "skills" / "devlog"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or os.path.islink(link):
        try:
            same = link.resolve() == SKILL_DIR
        except OSError:
            same = False
        if not same:
            sys.exit(f"devlog: {link} exists and points elsewhere; remove it (rmdir \"{link}\") and run install again")
        print(f"skill link ok: {link} -> {SKILL_DIR}")
    else:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(SKILL_DIR)], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
    settings = Path.home() / ".claude" / "settings.json"
    data = load_json(settings, {}) or {}
    command = f'python "{(SKILL_DIR / "scripts" / "devlog.py").as_posix()}" hook'
    stop = data.setdefault("hooks", {}).setdefault("Stop", [])
    hooks = [h for entry in stop for h in entry.get("hooks", [])]
    old = [h for h in hooks if "devlog.py" in h.get("command", "") and h.get("command") != command]
    for h in old:  # an older checkout's path
        h["command"] = command
    if not any(h.get("command") == command for h in hooks):
        stop.append({"hooks": [{"type": "command", "command": command, "timeout": 30}]})
    save_json(settings, data)
    print(f"Stop hook ok in {settings}: {command}")
    print(f"workspace: {WORKSPACE} (set GAMEDEV_ROOT if this checkout is not <workspace>\\devlog)")
    print("for dictation: python -m pip install --user faster-whisper nvidia-cublas-cu12 \"nvidia-cudnn-cu12==9.*\" av==16.0.1")


def cmd_init(a):
    dv = init_project(a.dir, a.name)
    render_project(Path(a.dir).resolve())
    render_workspace()
    print(dv)


def cmd_feature(a):
    proj = Path(a.project).resolve()
    if not (proj / "devlog").is_dir():
        init_project(proj)
    out = proj / "devlog" / "features" / f"{slugify(a.slug)}.md"
    if not out.exists():
        if not a.name:
            sys.exit("devlog: --name is required for a new feature")
        text = (TEMPLATES / "FEATURE.md").read_text(encoding="utf-8")
        out.write_text(text.replace("{{NAME}}", a.name).replace("{{SLUG}}", slugify(a.slug)).replace("{{DATE}}", dt.date.today().isoformat()), encoding="utf-8")
    if a.parent is not None:
        parent = slugify(a.parent) if a.parent else ""
        if parent and not (proj / "devlog" / "features" / f"{parent}.md").exists():
            print(f"devlog: warning: no feature file for parent '{parent}' yet", file=sys.stderr)
        set_front_matter(out, "parent", parent)
    if a.order is not None:
        set_front_matter(out, "order", a.order)
    print(out)


def set_front_matter(path, key, value):
    """Set (or with an empty value, remove) one `key: value` line in a markdown file's front matter."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    lines = m.group(1).splitlines() if m else []
    lines = [l for l in lines if not re.match(rf"^{re.escape(key)}\s*:", l)]
    if str(value).strip():
        lines.append(f"{key}: {value}")
    body = text[m.end():] if m else text
    Path(path).write_text(("---\n" + "\n".join(lines) + "\n---\n" if lines else "") + body, encoding="utf-8")


# ---------------------------------------------------------------- markdown (just enough for the corpus)

def front_matter(text):
    """Split `---` key: value front matter off a markdown doc; HTML comments (template hints) are dropped."""
    text = re.sub(r"<!--.*?-->[ \t]*\n?", "", text, flags=re.S)
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text


def md_inline(s):
    codes = []

    def keep(m):
        codes.append("<code>" + html.escape(m.group(1)) + "</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep, s)
    s = html.escape(s, quote=False)

    def url(raw):
        u = raw.strip().strip("<>").replace(" ", "%20")
        if _LINK_BASE[0] and not re.match(r"^([a-z][a-z0-9+.-]*:|#|/)", u, re.I):
            u = posixpath.normpath(posixpath.join(_LINK_BASE[0], u))
        return html.escape(u)

    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: f'<img alt="{m.group(1)}" src="{url(m.group(2))}">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{url(m.group(2))}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


_LINK_BASE = [""]  # folder (relative to the page) that relative links in the markdown being rendered resolve from


def md(text, shift=0, base=None):
    if base is not None:
        saved, _LINK_BASE[0] = _LINK_BASE[0], base
        try:
            return md(text, shift)
        finally:
            _LINK_BASE[0] = saved
    _, text = front_matter(text)
    lines = text.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    block_start = re.compile(r"^(#{1,6} |```|>|\s*[-*+] |\s*\d+[.)] |\s*\|)")
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
        elif m := re.match(r"^(#{1,6}) (.*)", line):
            lvl = min(6, len(m.group(1)) + shift)
            out.append(f"<h{lvl}>{md_inline(m.group(2))}</h{lvl}>")
            i += 1
        elif re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            out.append("<hr>")
            i += 1
        elif line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].lstrip())
                i += 1
            out.append("<blockquote>" + md("\n".join(buf)) + "</blockquote>")
        elif re.match(r"^\s*\|", line) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
            head = "".join(f"<th>{md_inline(c)}</th>" for c in cells(line))
            i += 2
            rows = []
            while i < len(lines) and re.match(r"^\s*\|", lines[i]):
                rows.append("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            out.append(f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
        elif m := re.match(r"^(\s*)([-*+]|\d+[.)]) (.*)", line):
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            items = []
            while i < len(lines):
                m2 = re.match(r"^(\s*)([-*+]|\d+[.)]) (.*)", lines[i])
                if m2:
                    depth = len(m2.group(1).expandtabs(4)) // 2
                    items.append([depth, m2.group(3)])
                elif lines[i].strip() and lines[i].startswith(" ") and items:
                    items[-1][1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            body = "".join(f'<li{" class=sub" if d else ""}>{md_inline(t)}</li>' for d, t in items)
            out.append(f"<{tag}>{body}</{tag}>")
        elif not line.strip():
            i += 1
        else:
            buf = []
            while i < len(lines) and lines[i].strip() and not block_start.match(lines[i]):
                buf.append(lines[i].strip())
                i += 1
            if not buf:  # a line that looked like a block start but was not one
                buf.append(lines[i].strip())
                i += 1
            out.append("<p>" + md_inline(" ".join(buf)) + "</p>")
    return "\n".join(out)


def clip(text, n):
    """Shorten to n characters at a word boundary, dropping a cut-off emphasis marker."""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:.")
    if cut.count("*") % 2:
        cut = cut[:cut.rfind("*")].rstrip()
    if cut.count("`") % 2:
        cut = cut[:cut.rfind("`")].rstrip()
    return cut + "…"


def md_title(text, fallback):
    _, body = front_matter(text)
    m = re.search(r"^# (.+)$", body, re.M)
    return m.group(1).strip() if m else fallback


def md_lede(text):
    """First real paragraph of a markdown doc (skips the title and template hints)."""
    _, body = front_matter(text)
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if p and not p.startswith(("#", "<!--", "|", "-", "*", ">", "```")) and "{{" not in p:
            return p
    return ""


# ---------------------------------------------------------------- HTML

CSS = """
/* Dark by default; light only when a page sets data-theme=light. */
:root{--bg:#111113;--fg:#e9e9ee;--muted:#9a9aa5;--card:#1a1a1e;--line:#2b2b32;--accent:#f0875a;--soft:#2c1c14;
--code:#22222a;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--info:#7aa7ff;color-scheme:dark}
:root[data-theme=light]{--bg:#f7f6f2;--fg:#1c1c1e;--muted:#6a6a70;--card:#fff;--line:#e4e1d8;--accent:#b4441b;--soft:#fbeee6;
--code:#f0eee8;--ok:#1d7a3e;--warn:#a35a00;--bad:#b42318;--info:#2559a8;color-scheme:light}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 16px 96px}
a{color:var(--accent)}a:hover{text-decoration:none}
h1{font-size:30px;line-height:1.2;margin:6px 0 10px;letter-spacing:-.01em}
h2{font-size:19px;margin:40px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:16px;margin:20px 0 6px}h4,h5,h6{font-size:15px;margin:16px 0 4px}
p{margin:8px 0}ul,ol{margin:6px 0;padding-left:22px}li.sub{margin-left:20px;list-style:circle}
code{font:13px/1.4 Consolas,"Cascadia Mono",monospace;background:var(--code);padding:1px 5px;border-radius:4px}
pre{background:var(--code);padding:12px 14px;border-radius:8px;overflow-x:auto}pre code{padding:0;background:none}
blockquote{margin:10px 0;padding:2px 14px;border-left:3px solid var(--line);color:var(--muted)}
hr{border:0;border-top:1px solid var(--line);margin:20px 0}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.crumbs{font-size:13px;color:var(--muted)}.crumbs a{color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:13.5px;margin:4px 0 14px}
.lede{font-size:16.5px;max-width:760px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--code);color:var(--muted);white-space:nowrap}
.b-done{color:var(--ok)}.b-partial,.b-in-progress{color:var(--warn)}.b-blocked,.b-abandoned,.b-fail{color:var(--bad)}.b-pass{color:var(--ok)}
.b-idea,.b-planned{color:var(--info)}.b-parked,.b-skipped{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font-size:13px;padding:3px 10px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--fg);background:var(--card)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}
.prompt{white-space:pre-wrap;font-size:15px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:14px 16px;margin:8px 0;overflow-wrap:anywhere}
.decision h3{margin:0 0 4px}.decision .choice{font-weight:600}.decision .why{margin:4px 0}.decision .alt{color:var(--muted);font-size:14px}
.by{font-size:12px;color:var(--muted);float:right;margin-left:10px}
.timeline{list-style:none;padding:0;margin:0;border-left:2px solid var(--line)}
.timeline>li{position:relative;padding:2px 0 14px 18px}.timeline>li:before{content:"";position:absolute;left:-6px;top:9px;width:10px;height:10px;border-radius:50%;background:var(--accent)}
.timeline .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-right:6px}
.timeline .when{font-size:12px;color:var(--muted)}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin:10px 0}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
figure img,figure video{display:block;width:100%;height:auto;background:#000;max-height:520px;object-fit:contain}
figcaption{font-size:13.5px;padding:8px 10px;color:var(--fg)}figcaption .f{color:var(--muted);font-size:12px}
.thumbs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.thumbs img,.thumbs video{width:120px;height:72px;object-fit:cover;border-radius:6px;border:1px solid var(--line);background:#000}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.grid .card{margin:0}.card h3{margin:0 0 4px}.small{font-size:13px;color:var(--muted)}
details{margin:8px 0}summary{cursor:pointer;color:var(--muted);font-size:14px}
.files{columns:2 320px;font:12.5px/1.6 Consolas,monospace;color:var(--muted);padding-left:18px}
.msg{border-left:3px solid var(--line);padding:2px 12px;margin:10px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.empty{color:var(--muted);font-style:italic}
dialog{border:0;padding:0;background:transparent;max-width:96vw;max-height:96vh}dialog::backdrop{background:rgba(0,0,0,.85)}
dialog img{max-width:96vw;max-height:92vh;display:block}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted);margin-right:7px;vertical-align:1px}
.s-done{background:var(--ok)}.s-in-progress,.s-partial{background:var(--warn)}.s-planned,.s-idea{background:var(--info)}.s-blocked,.s-abandoned{background:var(--bad)}
.tag{font-size:12px;padding:1px 8px;margin-left:4px;border-radius:999px;background:var(--code);color:var(--muted);text-decoration:none;white-space:nowrap}
.tag:hover{color:var(--fg)}
.card.group{border-left:3px solid var(--accent)}
.fchildren{list-style:none;padding:0;margin:10px 0 0;border-top:1px solid var(--line)}
.fchildren li{padding:7px 0;border-bottom:1px solid var(--line)}.fchildren li:last-child{border-bottom:0}
.fchildren .small{margin-left:15px}
.subs{margin-top:10px}
details.sub{border:1px solid var(--line);border-radius:10px;padding:6px 12px;margin:8px 0;background:var(--bg)}
details.sub>summary{color:var(--fg);padding:2px 0}details.sub[open]>summary{margin-bottom:6px}
@media (max-width:600px){h1{font-size:24px}.by{float:none;display:block}}
"""

ZOOM_JS = """<dialog id=z onclick="this.close()"><img id=zi alt=""></dialog><script>
document.addEventListener('click',e=>{const a=e.target.closest('a.zoom');if(!a)return;e.preventDefault();
document.getElementById('zi').src=a.href;document.getElementById('z').showModal();});
function openTarget(){var t=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!t)return;
for(var e=t;e;e=e.parentElement)if(e.tagName==='DETAILS')e.open=true;t.scrollIntoView();}
addEventListener('hashchange',openTarget);openTarget();</script>"""


def esc(s):
    return html.escape(str(s or ""))


# Inside the browser (browse.html) a page reports its address so the sidebar follows links; on its own it shows a "Browse" link.
FRAME_JS = """<script>(function(){var r=document.documentElement;if(window.parent===window)return;r.classList.add('framed');
function tell(){try{parent.postMessage({devlog:location.href},'*')}catch(e){}}tell();addEventListener('hashchange',tell);
addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K')){e.preventDefault();parent.postMessage({devlogKey:'palette'},'*');return}
if(e.ctrlKey||e.metaKey||e.altKey||/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))return;
if(e.key==='j'||e.key==='k'||e.key==='/'){e.preventDefault();parent.postMessage({devlogKey:e.key},'*')}});})();</script>"""
BROWSE_CSS = (".browse{position:fixed;top:12px;right:14px;font-size:12.5px;padding:4px 11px;border:1px solid var(--line);border-radius:999px;"
              "background:var(--card);color:var(--fg);text-decoration:none;z-index:3}.browse:hover{border-color:var(--accent)}"
              ".framed .browse{display:none}@media (max-width:600px){.browse{position:static;display:inline-block;margin-bottom:8px}}")


def page(title, body, path=None):
    browse = ""
    if path is not None:
        dv = WORKSPACE / "devlog"
        browse = f'<a class="browse" href="{href(Path(path).parent, dv / "browse.html")}#/{href(dv, path)}">Browse all ›</a>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>{FRAME_JS}'
            f"<style>{CSS}{BROWSE_CSS}</style></head><body>{browse}<main>{body}</main>{ZOOM_JS}</body></html>\n")


def badge(text):
    return f'<span class="badge b-{slugify(text)}">{esc(text)}</span>' if text else ""


def media_tag(src, caption="", thumb=False):
    ext = Path(src).suffix.lower()
    if ext in VIDEO_EXT:
        attrs = "muted loop playsinline preload=metadata" if thumb else "controls preload=metadata"
        return f'<video src="{esc(src)}" {attrs} title="{esc(caption)}"></video>'
    return f'<a class="zoom" href="{esc(src)}"><img src="{esc(src)}" alt="{esc(caption)}" loading="lazy"></a>'


def figure(src, m):
    feat = f'<div class="f">{esc(m.get("feature"))}</div>' if m.get("feature") else ""
    return f'<figure>{media_tag(src, m.get("caption"))}<figcaption>{md_inline(m.get("caption") or Path(src).name)}{feat}</figcaption></figure>'


def section(title, inner, anchor=None):
    a = f' id="{anchor}"' if anchor else ""
    return f"<h2{a}>{esc(title)}</h2>{inner}" if inner else ""


def as_list(v):
    if not v:
        return []
    return v if isinstance(v, list) else [v]


def render_session(sdir, log):
    proj = sdir.parent.parent.parent
    media_by_file = {m.get("file"): m for m in log.get("media") or []}
    shown = set()
    ppage = href(sdir, project_page(proj))
    parts = [f'<div class="crumbs"><a href="{href(sdir, WORKSPACE / "devlog" / "index.html")}">Game Dev</a> › '
             f'<a href="{ppage}">{esc(log.get("project"))}</a> › session</div>']
    parts.append(f"<h1>{esc(log.get('title'))}</h1>")
    meta = [local(log.get("started"), "%a %d %b %Y, %H:%M")]
    if duration(log.get("started"), log.get("ended")):
        meta.append(duration(log.get("started"), log.get("ended")))
    if log.get("agent"):
        meta.append(esc(log["agent"]))
    if log.get("run"):
        r = log["run"]
        meta.append(f'launched from the devlog ({esc(r.get("mode"))}{", " + esc(r.get("feature")) if r.get("feature") else ""})')
    meta.append(badge(log.get("outcome")))
    parts.append('<div class="meta">' + "".join(f"<span>{m}</span>" for m in meta if m) + "</div>")
    if log.get("summary"):
        parts.append(f'<div class="lede">{md(log["summary"])}</div>')
    if log.get("features"):
        parts.append('<div class="chips">' + "".join(
            f'<a class="chip" href="{ppage}#f-{esc(f)}">{esc(f)}</a>' for f in log["features"]) + "</div>")

    parts.append(section("The prompt", f'<div class="prompt">{esc(log.get("prompt")) or "<span class=empty>not captured</span>"}</div>'))

    dec = []
    for d in log.get("decisions") or []:
        alts = as_list(d.get("alternatives"))
        alt = f'<div class="alt">Also considered: {"; ".join(md_inline(x) for x in alts)}</div>' if alts else ""
        by = f'<span class="by">decided by {esc(d.get("by"))}</span>' if d.get("by") else ""
        dec.append(f'<div class="card decision">{by}<h3>{md_inline(d.get("title", ""))}</h3>'
                   f'<div class="choice">{md_inline(d.get("choice", ""))}</div>'
                   f'<div class="why">{md_inline(d.get("why", ""))}</div>{alt}</div>')
    for q in log.get("asked") or []:
        dec.append(f'<div class="card decision"><span class="by">asked the user · {local(q.get("at"), "%H:%M")}</span>'
                   f'<h3>{"<br>".join(esc(x) for x in q.get("questions") or [])}</h3><div class="why msg">{esc(q.get("answer"))}</div></div>')
    parts.append(section("Decisions", "".join(dec)))

    tl = []
    for t in log.get("timeline") or []:
        thumbs = ""
        if t.get("media"):
            figs = []
            for f in as_list(t["media"]):
                shown.add(f)
                figs.append(figure(f, media_by_file.get(f, {"caption": ""})))
            thumbs = f'<div class="gallery">{"".join(figs)}</div>'
        when = f'<span class="when">{local(t.get("at"), "%H:%M")}</span> ' if t.get("at") else ""
        kind = f'<span class="k">{esc(t.get("kind"))}</span>' if t.get("kind") else ""
        tl.append(f"<li>{when}{kind}{md_inline(t.get('text', ''))}{thumbs}</li>")
    parts.append(section("How it was built", f'<ul class="timeline">{"".join(tl)}</ul>' if tl else ""))

    rest = [m for m in log.get("media") or [] if m.get("file") not in shown]
    parts.append(section("Screenshots and video" if not shown else "More screenshots and video",
                         f'<div class="gallery">{"".join(figure(m["file"], m) for m in rest)}</div>' if rest else ""))

    tests = "".join(f"<tr><td>{md_inline(t.get('what', ''))}</td><td>{badge(t.get('result'))}</td><td>{md_inline(t.get('detail', ''))}</td></tr>"
                    for t in log.get("tests") or [])
    parts.append(section("Verification", f'<div class="tablewrap"><table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{tests}</tbody></table></div>' if tests else ""))

    notes = log.get("commit_notes") or {}
    rows = []
    for c in log.get("commits") or []:
        n = notes.get(c["hash"]) or notes.get(c["short"]) or ""
        rows.append(f"<tr><td>{esc(c['repo'])}</td><td><code>{esc(c['short'])}</code></td><td>{esc(c['subject'])}</td><td>{md_inline(n)}</td></tr>")
    git_html = f'<div class="tablewrap"><table><thead><tr><th>Repo</th><th>Commit</th><th>Subject</th><th>Why</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>' if rows else ""
    if log.get("uncommitted"):
        git_html += f'<p><strong>Not committed:</strong> {md_inline(log["uncommitted"])}</p>'
    for s in log.get("git_status") or []:
        git_html += f'<p class="small">{esc(s["repo"])}: {s["changes"]} uncommitted change(s) when this page was rendered.</p>'
    parts.append(section("Commits", git_html))

    nxt = "".join(f"<li>{md_inline(x)}</li>" for x in log.get("next_steps") or [])
    oq = "".join(f"<li>{md_inline(x)}</li>" for x in log.get("open_questions") or [])
    parts.append(section("Next steps", f"<ul>{nxt}</ul>" if nxt else ""))
    parts.append(section("Open questions", f"<ul>{oq}</ul>" if oq else ""))

    fu = "".join(f'<div class="msg"><span class="small">{local(m.get("at"), "%H:%M")}</span>\n{esc(m.get("text"))}</div>' for m in log.get("followups") or [])
    parts.append(section("Later messages from you", fu))
    files = "".join(f"<li>{esc(f)}</li>" for f in log.get("files_changed") or [])
    if files:
        parts.append(f'<h2>Files changed</h2><details><summary>{len(log["files_changed"])} files</summary><ul class="files">{files}</ul></details>')
    parts.append(f'<p class="small" style="margin-top:40px">Session {", ".join(esc(s[:8]) for s in log.get("session_ids") or [])} · '
                 f'source: session.json · rendered {local(log.get("updated"))}</p>')
    return page(f"{log.get('title')} · {log.get('project')}", "".join(parts), sdir / "index.html")


def load_sessions(proj):
    out = []
    sd = Path(proj) / "devlog" / "sessions"
    if sd.is_dir():
        for d in sd.iterdir():
            log = load_json(d / "session.json") if (d / "session.json").is_file() else None
            if log:
                out.append((d, log))
    return sorted(out, key=lambda x: x[1].get("started") or "", reverse=True)


def load_features(proj):
    out = []
    fd = Path(proj) / "devlog" / "features"
    if fd.is_dir():
        for f in sorted(fd.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            meta, _ = front_matter(text)
            out.append({"slug": f.stem, "path": f, "text": text, "meta": meta, "name": md_title(text, f.stem)})
    return out


STATUS_ORDER = {"in-progress": 0, "done": 1, "planned": 2, "idea": 3, "parked": 4}


def feature_tree(features):
    """Nest features by their `parent:` front matter. A group is any feature others name as parent; groups can nest.
    Siblings sort by `order:` then name. An unknown parent or a cycle leaves the feature at the top level.
    Returns the top-level features; every feature gets children, parent, status and (for groups) rollup."""
    by = {f["slug"]: f for f in features}
    for f in features:
        f["children"], f["parent"] = [], None
    for f in features:
        p = (f["meta"].get("parent") or "").strip()
        q, hops = p, 0
        while q in by and q != f["slug"] and hops < 64:  # walk up to make sure f is not its own ancestor
            q, hops = (by[q]["meta"].get("parent") or "").strip(), hops + 1
        if p in by and q != f["slug"] and hops < 64:
            f["parent"] = p
            by[p]["children"].append(f)

    def order_key(f):
        try:
            o = float(f["meta"].get("order", ""))
        except ValueError:
            o = float("inf")
        return (o, f["name"].lower())

    def finish(f):
        f["children"].sort(key=order_key)
        for c in f["children"]:
            finish(c)
        leaves = [d for d in descendants(f) if not d["children"]]
        own = f["meta"].get("status", "")
        if leaves:
            counts = {}
            for d in leaves:
                counts[d["status"]] = counts.get(d["status"], 0) + 1
            f["rollup"] = counts
            done, total = counts.get("done", 0), len(leaves)
            derived = ("done" if done == total else "in-progress" if done or counts.get("in-progress")
                       else "planned" if counts.get("planned") else "idea")
            f["status"] = own or derived
        else:
            f["rollup"], f["status"] = None, own

    roots = [f for f in features if not f["parent"]]
    for f in roots:
        finish(f)
    roots.sort(key=lambda f: (0 if f["children"] else 1, STATUS_ORDER.get(f["status"], 9), order_key(f)))
    return roots


def descendants(f):
    for c in f["children"]:
        yield c
        yield from descendants(c)


def rollup_text(f):
    r = f.get("rollup")
    if not r:
        return ""
    total = sum(r.values())
    rest = ", ".join(f"{n} {k}" for k, n in sorted(r.items(), key=lambda kv: STATUS_ORDER.get(kv[0], 9)) if k != "done")
    return f"{r.get('done', 0)}/{total} done" + (f" · {rest}" if rest else "")


def feature_media(sdir, log, slugs):
    """Media of a session that belongs to any of slugs (tagged, or untagged in a single-feature session)."""
    slugs = {slugs} if isinstance(slugs, str) else set(slugs)
    feats = log.get("features") or []
    for m in log.get("media") or []:
        if m.get("feature") in slugs or (not m.get("feature") and len(feats) == 1 and feats[0] in slugs):
            yield f"sessions/{sdir.name}/{m['file']}", m


def render_project(proj):
    proj = Path(proj)
    dv = proj / "devlog"
    name = project_name(proj)
    sessions, features = load_sessions(proj), load_features(proj)
    overview = (dv / "OVERVIEW.md").read_text(encoding="utf-8") if (dv / "OVERVIEW.md").is_file() else ""
    handoff = (dv / "HANDOFF.md").read_text(encoding="utf-8") if (dv / "HANDOFF.md").is_file() else ""
    up = href(dv, WORKSPACE / "devlog" / "index.html")
    parts = [f'<div class="crumbs"><a href="{up}">Game Dev</a> › {esc(name)}</div>', f"<h1>{esc(name)}</h1>"]
    last = sessions[0][1].get("ended") if sessions else ""
    parts.append(f'<div class="meta"><span>{len(sessions)} sessions</span><span>{len(features)} features</span>'
                 f'{"<span>last activity " + local(last) + "</span>" if last else ""}</div>')
    lede = md_lede(overview)
    if lede:
        parts.append(f'<div class="lede">{md_inline(lede)}</div>')
    parts.append('<div class="chips" style="margin-top:12px"><a class="chip" href="#features">Features</a>'
                 '<a class="chip" href="#sessions">Sessions</a><a class="chip" href="#handoff">Current handoff</a>'
                 '<a class="chip" href="#docs">Ideation, planning, overview</a></div>')

    # Features: groups with their sub-features, then single features; then how each one was built.
    by_feature = {}
    for sdir, log in sessions:
        for slug in log.get("features") or []:
            by_feature.setdefault(slug, []).append((sdir, log))
    roots = feature_tree(features)
    names = {f["slug"]: f["name"] for f in features}

    def summary_of(f):
        return f["meta"].get("summary") or md_lede(f["text"])

    def count_text(f):
        n = len(by_feature.get(f["slug"], []))
        return rollup_text(f) or f"{n} session{'' if n == 1 else 's'}"

    def session_rows(f, whole_group):
        """Sessions for f (and, for a group, everything under it), newest first, labelled with the sub-features they touched."""
        slugs = {f["slug"]} | ({d["slug"] for d in descendants(f)} if whole_group else set())
        rows = []
        for sdir, log in sessions:
            tagged = [s for s in log.get("features") or [] if s in slugs]
            if not tagged:
                continue
            th = "".join(media_tag(src, m.get("caption"), thumb=True) for src, m in feature_media(sdir, log, slugs))
            tags = "".join(f'<a class="tag" href="#f-{esc(t)}">{esc(names.get(t, t))}</a>' for t in tagged if t != f["slug"])
            rows.append(f'<li><span class="when">{local(log.get("started"), "%d %b %Y")}</span> '
                        f'<a href="sessions/{esc(sdir.name)}/index.html">{esc(log.get("title"))}</a> {badge(log.get("outcome"))} {tags}'
                        f'<div>{md_inline(clip(log.get("summary"), 400))}</div>{f"<div class=thumbs>{th}</div>" if th else ""}</li>')
        return f'<ul class="timeline">{"".join(rows)}</ul>' if rows else '<p class="empty">No sessions logged yet.</p>'

    def notes_of(f):
        return f"<details><summary>Feature notes (features/{esc(f['slug'])}.md)</summary>{md(f['text'], 1, 'features')}</details>"

    def child_list(f, depth=0):
        out = ""
        for c in f["children"]:
            out += (f'<li style="margin-left:{depth * 20}px"><span class="dot s-{esc(c["status"])}"></span>'
                    f'<a href="#f-{esc(c["slug"])}">{esc(c["name"])}</a> {badge(c["status"])} <span class="small">{count_text(c)}</span>'
                    f'<div class="small">{md_inline(clip(summary_of(c), 180))}</div></li>') + child_list(c, depth + 1)
        return out

    def child_block(c):
        """A sub-feature inside its group's history: collapsed, with its own sessions, notes and children."""
        inner = session_rows(c, bool(c["children"])) + notes_of(c) + "".join(child_block(g) for g in c["children"])
        return (f'<details class="sub" id="f-{esc(c["slug"])}"><summary><b>{esc(c["name"])}</b> {badge(c["status"])} '
                f'<span class="small">{count_text(c)}</span></summary>{inner}</details>')

    group_cards, leaf_cards, hist, quiet = [], [], [], []
    for f in roots:
        if f["children"]:
            group_cards.append(f'<div class="card group"><h3><a href="#f-{esc(f["slug"])}">{esc(f["name"])}</a> {badge(f["status"])} '
                               f'<span class="small">{rollup_text(f)}</span></h3><p>{md_inline(clip(summary_of(f), 300))}</p>'
                               f'<ul class="fchildren">{child_list(f)}</ul></div>')
            hist.append(f'<div class="card group" id="f-{esc(f["slug"])}"><h3>{esc(f["name"])} {badge(f["status"])} '
                        f'<span class="small">{rollup_text(f)}</span></h3>{session_rows(f, True)}{notes_of(f)}'
                        f'<div class="subs">{"".join(child_block(c) for c in f["children"])}</div></div>')
        else:
            s = by_feature.get(f["slug"], [])
            leaf_cards.append(f'<div class="card"><h3><a href="#f-{esc(f["slug"])}">{esc(f["name"])}</a></h3>'
                              f'{badge(f["status"])} <span class="small">{count_text(f)}'
                              f'{" · last " + local(s[0][1].get("ended"), "%d %b") if s else ""}</span>'
                              f'<p>{md_inline(clip(summary_of(f), 280))}</p></div>')
            if s:
                hist.append(f'<div class="card" id="f-{esc(f["slug"])}"><h3>{esc(f["name"])} {badge(f["status"])}</h3>'
                            f"{session_rows(f, False)}{notes_of(f)}</div>")
            else:
                quiet.append(f'<details id="f-{esc(f["slug"])}"><summary>{esc(f["name"])} {badge(f["status"])}</summary>'
                             f'<div class="card">{md(f["text"], 1, "features")}</div></details>')
    orphans = sorted(k for k in by_feature if k not in names)
    feat_html = "".join(group_cards)
    if leaf_cards:
        feat_html += (f'<h3>{"Other features" if group_cards else ""}</h3>' if group_cards else "") + f'<div class="grid">{"".join(leaf_cards)}</div>'
    if not features:
        feat_html = '<p class="empty">No feature files yet.</p>'
    if orphans:
        feat_html += f'<p class="small">Tagged in sessions but missing a feature file: {", ".join(esc(o) for o in orphans)}</p>'
    parts.append(section("Features", feat_html, "features"))
    if quiet:
        hist.append('<h3>No sessions logged yet</h3>' + "".join(quiet))
    parts.append(section("How each feature was built", "".join(hist)))

    rows = "".join(f'<tr><td>{local(log.get("started"), "%Y-%m-%d")}</td><td><a href="sessions/{esc(d.name)}/index.html">{esc(log.get("title"))}</a></td>'
                   f'<td>{badge(log.get("outcome"))}</td><td>{esc(", ".join(log.get("features") or []))}</td><td>{len(log.get("commits") or [])}</td><td>{len(log.get("media") or [])}</td></tr>'
                   for d, log in sessions)
    parts.append(section("Sessions", f'<div class="tablewrap"><table><thead><tr><th>Date</th><th>Session</th><th>Outcome</th><th>Features</th><th>Commits</th><th>Media</th></tr></thead><tbody>{rows}</tbody></table></div>'
                         if rows else '<p class="empty">No sessions logged yet.</p>', "sessions"))
    parts.append(section("Current handoff", f'<div class="card">{md(handoff, 1)}</div>' if handoff else "", "handoff"))

    docs = []
    for label, path in (("Overview", dv / "OVERVIEW.md"),):
        if path.is_file():
            docs.append(f"<details open><summary>{label}</summary><div class='card'>{md(path.read_text(encoding='utf-8'), 1)}</div></details>")
    for sub in ("ideation", "planning"):
        for f in sorted((dv / sub).glob("*.md")) if (dv / sub).is_dir() else []:
            text = f.read_text(encoding="utf-8")
            docs.append(f"<details><summary>{sub} / {esc(md_title(text, f.stem))}</summary><div class='card'>{md(text, 1, sub)}</div></details>")
    parts.append(section("Ideation, planning, overview", "".join(docs), "docs"))
    parts.append(f'<p class="small" style="margin-top:40px">Generated by devlog.py from devlog/ · {local(now_iso())}. Agents: read devlog/README.md, not this page.</p>')
    project_page(proj).write_text(page(f"{name} devlog", "".join(parts), project_page(proj)), encoding="utf-8")
    write_worklog(proj, sessions)


def write_worklog(proj, sessions):
    """WORKLOG.md: commit-by-commit history for agents, newest first, generated from session.json files."""
    entries = []
    for sdir, log in sessions:
        notes = log.get("commit_notes") or {}
        link = f"sessions/{sdir.name}/session.json"
        for c in log.get("commits") or []:
            n = notes.get(c["hash"]) or notes.get(c["short"]) or ""
            entries.append((c.get("at") or "", f"### {c['at'][:10]} · `{c['short']}` · {c['subject']}\n\n"
                            f"- Repo: {c['repo']} · session: [{log.get('title')}]({link.replace(' ', '%20')})\n"
                            + (f"- Why / notes: {n}\n" if n else "")))
        if log.get("uncommitted") or not log.get("commits"):
            what = log.get("uncommitted") or "No commits in this session."
            entries.append((log.get("ended") or "", f"### {(log.get('ended') or '')[:10]} · (no commit) · {log.get('title')}\n\n"
                            f"- Session: [{log.get('title')}]({link.replace(' ', '%20')}) · outcome: {log.get('outcome')}\n"
                            f"- {what}\n"))
    head = (f"# {project_name(proj)} worklog\n\nGenerated by `devlog.py render` from `sessions/*/session.json`; do not edit by hand "
            "(put commit notes in the session's `commit_notes`). Newest first. One entry per commit, plus sessions that ended without one.\n\n")
    body = "\n".join(e for _, e in sorted(entries, key=lambda x: x[0], reverse=True)) or "_Nothing logged yet._\n"
    (Path(proj) / "devlog" / "WORKLOG.md").write_text(head + body, encoding="utf-8")


def render_workspace():
    dv = WORKSPACE / "devlog"
    if not dv.is_dir():
        return
    cards, recent = [], []
    for proj in projects():
        sessions, features = load_sessions(proj), load_features(proj)
        link = href(dv, project_page(proj))
        ov = proj / "devlog" / "OVERVIEW.md"
        lede = md_lede(ov.read_text(encoding="utf-8")) if ov.is_file() else ""
        active = sum(1 for f in features if f["meta"].get("status") == "in-progress")
        cards.append(f'<div class="card"><h3><a href="{link}">{esc(project_name(proj))}</a></h3>'
                     f'<div class="small">{len(sessions)} sessions · {len(features)} features{f" · {active} in progress" if active else ""}'
                     f'{" · last " + local(sessions[0][1].get("ended"), "%d %b") if sessions else ""}</div><p>{md_inline(clip(lede, 300))}</p></div>')
        base = href(dv, proj / "devlog") + "/"
        for d, log in sessions:
            recent.append((log.get("started") or "", f'<tr><td>{local(log.get("started"), "%Y-%m-%d")}</td><td>{esc(project_name(proj))}</td>'
                                                     f'<td><a href="{base}sessions/{esc(d.name)}/index.html">{esc(log.get("title"))}</a></td><td>{badge(log.get("outcome"))}</td></tr>'))
    recent.sort(reverse=True)
    rows = "".join(r for _, r in recent[:60])
    body = ('<div class="crumbs">Game Dev</div><h1>Game Dev devlog</h1>'
            '<p class="lede">Every Claude session across the workspace: what was asked, what was decided, what got built, with screenshots and video. '
            'Each project page also tracks features from idea to done.</p>'
            + section("Projects", f'<div class="grid">{"".join(cards)}</div>')
            + section("Recent sessions", f'<div class="tablewrap"><table><thead><tr><th>Date</th><th>Project</th><th>Session</th><th>Outcome</th></tr></thead><tbody>{rows}</tbody></table></div>'
                      if rows else '<p class="empty">No sessions logged yet.</p>')
            + f'<p class="small" style="margin-top:40px">Generated by devlog.py · {local(now_iso())}</p>')
    (dv / "index.html").write_text(page("Game Dev devlog", body, dv / "index.html"), encoding="utf-8")
    render_browser()


def render_browser():
    """devlog/browse.html: the sidebar browser over every generated page, with the page list embedded (file:// cannot list folders).
    The devlog server (devlog_server.py) serves the same file and adds live data and actions on top."""
    dv = WORKSPACE / "devlog"
    data = json.dumps(build_manifest(), ensure_ascii=False).replace("</", "<\\/")
    tpl = (TEMPLATES / "browse.html").read_text(encoding="utf-8")
    (dv / "browse.html").write_text(tpl.replace("/*__DATA__*/null", data, 1), encoding="utf-8")


def handoff_next_steps(proj):
    """The list items under `## Next steps` in a project's HANDOFF.md (plain text, without markdown markers)."""
    f = Path(proj) / "devlog" / "HANDOFF.md"
    if not f.is_file():
        return []
    m = re.search(r"^## Next steps[ \t]*\n(.*?)(?=^## |\Z)", f.read_text(encoding="utf-8"), re.M | re.S)
    steps = []
    for line in (m.group(1) if m else "").splitlines():
        s = re.match(r"^\s*(?:\d+[.)]|[-*+])\s+(.*)", line)
        if s:
            steps.append(re.sub(r"[*`]", "", s.group(1)).strip())
        elif steps and line.startswith("   ") and line.strip():
            steps[-1] += " " + line.strip()
    return steps[:20]


def build_manifest():
    """Every project, feature, session and media file, with hrefs relative to the workspace devlog/ folder."""
    dv = WORKSPACE / "devlog"
    out, projs = [{"kind": "home", "title": "Home", "href": "index.html", "search": "home"}], []
    for proj in projects():
        name = project_name(proj)
        sessions, features = load_sessions(proj), load_features(proj)
        ppage = href(dv, project_page(proj))
        projs.append({"name": name, "dir": str(proj)})
        ov = proj / "devlog" / "OVERVIEW.md"
        lede = md_lede(ov.read_text(encoding="utf-8")) if ov.is_file() else ""
        out.append({"kind": "project", "project": name, "title": name, "href": ppage, "summary": clip(lede, 300),
                    "next_steps": handoff_next_steps(proj), "search": f"{name} {lede}".lower()})
        roots = feature_tree(features)
        names = {f["slug"]: f["name"] for f in features}
        ordered = []
        for r in roots:  # tree order: each group followed by everything under it
            ordered += [r] + list(descendants(r))
        for f in ordered:
            summary = f["meta"].get("summary") or md_lede(f["text"])
            out.append({"kind": "feature", "project": name, "title": f["name"], "slug": f["slug"], "href": f"{ppage}#f-{f['slug']}",
                        "status": f["status"], "own_status": f["meta"].get("status", ""), "summary": summary,
                        "parent": f["parent"] or "", "rollup": rollup_text(f), "group": bool(f["children"]),
                        "search": " ".join([name, f["slug"], names.get(f["parent"] or "", ""), f["text"]]).lower()})
        for sdir, log in sessions:
            shref = href(dv, sdir / "index.html")
            base = href(dv, sdir) + "/"
            media = [{"src": base + m["file"].replace(" ", "%20"), "caption": m.get("caption", ""), "feature": m.get("feature", ""),
                      "kind": "video" if Path(m["file"]).suffix.lower() in VIDEO_EXT else "image"}
                     for m in log.get("media") or [] if m.get("file")]
            text = [name, log.get("title"), log.get("summary"), log.get("prompt"), " ".join(log.get("features") or [])]
            text += [" ".join(str(d.get(k, "")) for k in ("title", "choice", "why")) for d in log.get("decisions") or []]
            text += [t.get("text", "") for t in log.get("timeline") or []]
            text += [c.get("subject", "") + " " + c.get("short", "") for c in log.get("commits") or []]
            out.append({"kind": "session", "project": name, "title": log.get("title") or sdir.name, "href": shref,
                        "started": log.get("started"), "outcome": log.get("outcome"), "summary": clip(log.get("summary"), 300),
                        "features": log.get("features") or [], "media": media, "session_ids": log.get("session_ids") or [],
                        "cwd": log.get("cwd") or "", "run": (log.get("run") or {}).get("id", ""),
                        "search": " ".join(str(x or "") for x in text).lower()})
    return {"generated": now_iso(), "projects": projs, "pages": out}


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("dir"); p.add_argument("--name"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("start"); p.add_argument("--project"); p.add_argument("--slug"); p.add_argument("--title"); p.add_argument("--transcript"); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("media"); p.add_argument("session"); p.add_argument("file"); p.add_argument("--caption"); p.add_argument("--feature"); p.add_argument("--move", action="store_true"); p.set_defaults(fn=cmd_media)
    p = sub.add_parser("feature"); p.add_argument("project"); p.add_argument("slug"); p.add_argument("--name")
    p.add_argument("--parent", help="slug of the group feature this one belongs under ('' to ungroup)")
    p.add_argument("--order", help="sort position among its siblings"); p.set_defaults(fn=cmd_feature)
    p = sub.add_parser("render"); p.add_argument("session", nargs="?"); p.add_argument("--transcript"); p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("where"); p.add_argument("--transcript"); p.set_defaults(fn=cmd_where)
    p = sub.add_parser("skip"); p.add_argument("--reason", required=True); p.add_argument("--transcript"); p.set_defaults(fn=cmd_skip)
    p = sub.add_parser("hook"); p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("install", help="link the skill into ~/.claude/skills and add the Stop hook"); p.set_defaults(fn=cmd_install)
    p = sub.add_parser("serve", help="run the devlog browser as a local dev tool (status changes, Claude sessions)")
    p.add_argument("--port", type=int, default=8765); p.add_argument("--open", action="store_true")
    p.set_defaults(fn=lambda a: __import__("devlog_server").serve(a.port, a.open))
    p = sub.add_parser("launch", help="(internal) run one launched Claude session in this console")
    p.add_argument("run_id"); p.set_defaults(fn=lambda a: __import__("devlog_server").launch(a.run_id))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
