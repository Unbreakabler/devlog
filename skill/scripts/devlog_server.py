#!/usr/bin/env python3
"""devlog server: the devlog browser as a local dev tool.

Serves the generated devlog pages from D:\\Game Dev on http://127.0.0.1:<port>/ and adds an API the browser uses to
  - set a feature's status (front matter in devlog/features/<slug>.md, then re-render),
  - launch a Claude Code session for a feature or group, in a terminal window or in the background,
  - resume a logged session, and follow every launched session (status, recent activity, its devlog entry).

Each launch is recorded in devlog/runs/<id>.json with a pre-assigned session id, so the run, the transcript and the
session's devlog entry link to each other. Launched sessions get DEVLOG_RUN_ID and DEVLOG_TRANSCRIPT in their environment.

Security: binds to 127.0.0.1 only, accepts only Host 127.0.0.1/localhost on its port (no DNS rebinding), and every
/api call (except /api/ping) needs the random token the server writes into the browser page it serves (no CSRF from
other sites). Static files: only under the workspace, no dot-folders, an allowlist of extensions.

Run:  python devlog.py serve [--port 8765] [--open]      (or Start-Devlog.bat in the workspace)
Standard library only.
"""
import ctypes
import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import devlog as D
import devlog_stt as STT

WORKSPACE = D.WORKSPACE
DEVLOG_DIR = WORKSPACE / "devlog"
RUNS_DIR = D.RUNS_DIR
DEVLOG_PY = Path(D.__file__).resolve()
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(24)
STATUSES = ["idea", "planned", "in-progress", "done", "parked"]
# bypassPermissions is deliberately not offered from a web page.
PERMISSION_MODES = ["auto", "acceptEdits", "manual", "plan", "dontAsk"]
MODES = ["terminal", "background"]
SERVE_EXT = {".html", ".htm", ".md", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg",
             ".mp4", ".webm", ".mov", ".m4v", ".css", ".js", ".pdf"}
MIME = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".md": "text/plain; charset=utf-8",
        ".txt": "text/plain; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
        ".avif": "image/avif", ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".m4v": "video/mp4", ".pdf": "application/pdf"}
CREATE_NEW_CONSOLE = 0x00000010


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- Claude Code

def find_claude():
    """The Claude Code CLI: $DEVLOG_CLAUDE, `claude` on PATH, or the newest copy bundled with the Claude desktop app."""
    env = os.environ.get("DEVLOG_CLAUDE")
    if env and Path(env).is_file():
        return env
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    bundled = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    cands = sorted(bundled.glob("*/*/claude.exe"), key=lambda p: p.stat().st_mtime, reverse=True) if bundled.is_dir() else []
    return str(cands[0]) if cands else None


def transcript_path(cwd, session_id):
    return D.CLAUDE_PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", str(cwd)) / f"{session_id}.jsonl"


_agents = {"at": 0.0, "data": {}}


def agents():
    """Sessions Claude Code knows about (interactive and background), by session id; cached a few seconds."""
    if time.time() - _agents["at"] < 4:
        return _agents["data"]
    data, claude = {}, find_claude()
    if claude:
        try:
            r = subprocess.run([claude, "agents", "--json", "--all"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for a in json.loads(r.stdout or "[]"):
                if a.get("sessionId"):
                    data[a["sessionId"]] = a
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _agents.update(at=time.time(), data=data)
    return data


_auth = {"at": 0.0, "data": None}


def auth_status():
    """`claude auth status`: whether the CLI can start sessions on this PC (cached; reset after a login attempt)."""
    if time.time() - _auth["at"] < 30 and _auth["data"] is not None:
        return _auth["data"]
    data, claude = {"loggedIn": None}, find_claude()
    if claude:
        try:
            r = subprocess.run([claude, "auth", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(r.stdout or "{}")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _auth.update(at=time.time(), data={"loggedIn": data.get("loggedIn"), "authMethod": data.get("authMethod")})
    return _auth["data"]


def pid_alive(pid):
    if not pid:
        return False
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    except (AttributeError, OSError):
        return False


# ---------------------------------------------------------------- projects, features, prompts

def project_by_name(name):
    D.forget_projects()
    for p in D.projects():
        if D.project_name(p) == name:
            return p
    raise ApiError(404, f"no project named {name!r}")


def feature_entry(proj, slug):
    if not slug or slug != D.slugify(slug):
        raise ApiError(400, f"bad feature slug {slug!r}")
    feats = D.load_features(proj)
    D.feature_tree(feats)
    by = {f["slug"]: f for f in feats}
    if slug not in by:
        raise ApiError(404, f"no feature {slug!r} in {D.project_name(proj)}")
    return by[slug], by


def default_prompt(proj, slug):
    f, by = feature_entry(proj, slug)
    dv = proj / "devlog"
    read = [dv / "HANDOFF.md"] + ([by[f["parent"]]["path"]] if f["parent"] else []) + [f["path"]]
    lines = [f'Work on the {D.project_name(proj)} feature "{f["name"]}" (`{slug}`, status: {f["status"] or "none"}).']
    summary = f["meta"].get("summary") or D.md_lede(f["text"])
    if summary:
        lines += ["", summary]
    if f["children"]:
        todo = [d for d in D.descendants(f) if not d["children"] and d["status"] != "done"]
        lines += ["", "This is a feature group. Work through its unfinished members in this order, finishing, verifying and "
                      "logging each one before starting the next (stop and ask if one is blocked):"]
        lines += [f'- `{d["slug"]}`: {d["name"]} ({d["status"] or "no status"})' for d in todo] or ["- (all members are done)"]
    lines += ["", "Before starting, read " + ", ".join(f"`{D.rel(p)}`" for p in read)
              + f", the members' feature files if it is a group, and any plan in `{D.rel(dv / 'planning')}` that covers this work.",
              "", "Then plan, implement and test it. Capture screenshots or video of anything visible "
                  "(devlog skill, reference/capture.md). Ask me before decisions that are mine to make.",
              "", "When you finish, follow the devlog skill: log this session with the features you worked on, set each feature "
                  "file's status (done only when it is complete and verified), rewrite HANDOFF.md, and render."]
    return "\n".join(lines)


def vocabulary():
    """Words Whisper should expect: project and feature names plus the stack's jargon (passed as its initial prompt)."""
    words = ["devlog", "Claude", "ComfyUI", "Godot", "Unreal", "Blender", "GLB", "LOD", "VRAM", "GPU", "RTX 5080",
             "4080 Super", "Tauri", "Rust", "React", "TypeScript", "three.js", "WebGPU", "Whisper", "slice", "handoff"]
    for proj in D.projects():
        words.append(D.project_name(proj))
        for f in D.load_features(proj):
            # Only the distinctive words: numbers and version tags in the hint get echoed back as if spoken.
            name = re.sub(r"^(slice|milestone|phase|step)\s*\d+\s*:\s*", "", f["name"], flags=re.I)
            name = re.sub(r"\s*\((v?\d[\d.]*[^)]*)\)", "", name).strip()
            if name:
                words.append(name)
    out, seen = [], set()
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ("Game development notes. Terms: " + ", ".join(out) + ".")[:800]


def add_note(proj, slug, text, target, title="", dictated=False):
    """A quick note from the browser: appended to a feature file's Notes section, or saved as a new ideation doc."""
    text = re.sub(r"\s*\n\s*", " ", (text or "").strip())
    if not text:
        raise ApiError(400, "the note is empty")
    stamp, label = time.strftime("%Y-%m-%d %H:%M"), "voice note" if dictated else "note"
    with LOCK:
        if target == "feature":
            f, _ = feature_entry(proj, slug)
            body = f["path"].read_text(encoding="utf-8").rstrip("\n") + "\n"
            line = f"- {stamp} ({label}): {text}\n"
            if re.search(r"^## Notes\s*$", body, re.M):
                # append at the end of the Notes section (before the next heading, if any)
                m = re.search(r"^## Notes\s*$", body, re.M)
                nxt = re.search(r"^## ", body[m.end():], re.M)
                at = m.end() + nxt.start() if nxt else len(body)
                head, tail = body[:at].rstrip("\n"), body[at:]
                body = head + "\n" + ("\n" if head.endswith("## Notes") else "") + line + ("\n" + tail if tail else "")
            else:
                h = re.search(r"^## History\s*$", body, re.M)
                section = f"## Notes\n\n{line}\n"
                body = body[:h.start()] + section + body[h.start():] if h else body + "\n" + section
            f["path"].write_text(body, encoding="utf-8")
            where = D.rel(f["path"])
        elif target == "ideation":
            title = (title or "").strip() or (re.split(r"(?<=[.!?])\s", text)[0][:70].rstrip(" .!?") or "Idea")
            d = proj / "devlog" / "ideation"
            d.mkdir(parents=True, exist_ok=True)
            base = f"{time.strftime('%Y-%m-%d')}-{D.slugify(title, 50)}"
            out, n = d / f"{base}.md", 2
            while out.exists():
                out, n = d / f"{base}-{n}.md", n + 1
            src = ""
            if slug:
                f, _ = feature_entry(proj, slug)
                src = f" · from [{f['name']}](../features/{slug}.md)"
            out.write_text(f"# {title}\n\n{stamp} · {label}{src}\n\n{text}\n", encoding="utf-8")
            where = D.rel(out)
        else:
            raise ApiError(400, "target must be feature or ideation")
        rerender(proj)
    return where


WHAT_RE = re.compile(r"^## What it is[ \t]*\n(.*?)(?=^## |\Z)", re.M | re.S)


def new_feature(proj, name, parent="", summary=""):
    name = (name or "").strip()
    if not name:
        raise ApiError(400, "the feature needs a name")
    slug = D.slugify(name, 40)
    path = proj / "devlog" / "features" / f"{slug}.md"
    if path.exists():
        raise ApiError(409, f"a feature named {slug!r} already exists")
    if parent:
        feature_entry(proj, parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (D.TEMPLATES / "FEATURE.md").read_text(encoding="utf-8")
    path.write_text(text.replace("{{NAME}}", name).replace("{{SLUG}}", slug).replace("{{DATE}}", time.strftime("%Y-%m-%d")), encoding="utf-8")
    D.set_front_matter(path, "summary", re.sub(r"\s+", " ", summary or "").strip())
    if parent:
        D.set_front_matter(path, "parent", parent)
    rerender(proj)
    return slug


def get_description(proj, slug):
    f, _ = feature_entry(proj, slug)
    m = WHAT_RE.search(f["path"].read_text(encoding="utf-8"))
    what = re.sub(r"<!--.*?-->\s*", "", m.group(1), flags=re.S).strip() if m else ""
    return {"name": f["name"], "summary": f["meta"].get("summary", ""), "what": what}


def set_description(proj, slug, summary, what):
    f, _ = feature_entry(proj, slug)
    with LOCK:
        D.set_front_matter(f["path"], "summary", re.sub(r"\s+", " ", summary or "").strip())
        text = f["path"].read_text(encoding="utf-8")
        block = "## What it is\n\n" + (what or "").strip() + "\n\n"
        m = WHAT_RE.search(text)
        if m:
            text = text[:m.start()] + block + text[m.end():]
        else:  # right after the title
            t = re.search(r"^# .*\n", text, re.M)
            at = t.end() if t else len(text)
            text = text[:at] + "\n" + block + text[at:]
        f["path"].write_text(text, encoding="utf-8")
        rerender(proj)


def set_parent(proj, slug, parent):
    f, by = feature_entry(proj, slug)
    if parent:
        if parent not in by:
            raise ApiError(404, f"no feature {parent!r}")
        if parent == slug or parent in {d["slug"] for d in D.descendants(f)}:
            raise ApiError(400, "a feature cannot go under itself or one of its own members")
    with LOCK:
        D.set_front_matter(f["path"], "parent", parent or "")
        rerender(proj)


def open_in(proj, app):
    if app == "explorer":
        subprocess.Popen(["explorer", str(proj)])
    elif app == "code":
        code = shutil.which("code") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe")
        if not Path(code).exists() and not shutil.which("code"):
            raise ApiError(404, "VS Code not found")
        subprocess.Popen([code, str(proj)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        raise ApiError(400, "app must be explorer or code")


def session_prompt(kind, proj, slug="", text=""):
    """Prompts for the palette's Claude actions. `feature` is the Run prompt; the rest shape a conversation."""
    pname, dv = D.project_name(proj), proj / "devlog"
    end = "When you finish, follow the devlog skill: log this session, update the feature files you touched, rewrite HANDOFF.md, and render."
    if kind == "feature":
        return default_prompt(proj, slug)
    if kind == "brainstorm":
        topic = (text or "").strip()
        return "\n".join([
            f"Let's brainstorm {('about: ' + topic) if topic else 'a new idea'} for {pname}.", "",
            f"First skim `{D.rel(dv / 'OVERVIEW.md')}`, `{D.rel(dv / 'HANDOFF.md')}` and `{D.rel(dv / 'ideation')}` so you know what exists and what was already dropped.",
            "Then work it through with me: ask one or two questions at a time, offer options with their trade-offs, and push back on weak spots. Do not write code.",
            f"When we converge, write it up as `{D.rel(dv / 'ideation')}/<date>-<slug>.md`: the idea in my words, the directions we considered and why we dropped them, and open questions. "
            "Then propose feature files (grouped under a parent feature when they belong together) and create them only once I agree.", "", end])
    f, by = feature_entry(proj, slug)
    files = ", ".join(f"`{D.rel(p)}`" for p in [f["path"]] + ([by[f["parent"]]["path"]] if f["parent"] else []))
    if kind == "describe":
        return "\n".join([
            f'Help me write the description of the {pname} feature "{f["name"]}".', "",
            f"Read {files}, `{D.rel(dv / 'HANDOFF.md')}` and any code or plan it relates to. Then interview me briefly, a few questions at a time: "
            "what it does and for whom, what is in and out of scope, and what done looks like.",
            "Then rewrite the front-matter `summary` (one sentence) and the `## What it is` section, and list anything unresolved under `## Open questions`. "
            "Do not change code.", "", end])
    if kind == "plan":
        return "\n".join([
            f'Write an implementation plan for the {pname} feature "{f["name"]}".', "",
            f"Read {files}, `{D.rel(dv / 'HANDOFF.md')}`, the existing plans in `{D.rel(dv / 'planning')}` and the code it touches.",
            f"Write `{D.rel(dv / 'planning')}/<date>-{slug}.md`: goal, approach, steps that can each be tested, risks, and how we will verify it is done; "
            "link it from the feature file and set its status to planned if it was an idea. Ask me about decisions that are mine. Do not implement yet.", "", end])
    raise ApiError(400, f"unknown prompt kind {kind!r}")


def set_status(proj, slug, status):
    f, _ = feature_entry(proj, slug)
    if status not in STATUSES and not (status == "" and f["children"]):
        raise ApiError(400, f"status must be one of {STATUSES} (or empty for a group, to roll up from its members)")
    with LOCK:
        D.set_front_matter(f["path"], "status", status)
        rerender(proj)


def rerender(proj=None):
    with LOCK:
        D.forget_projects()
        for p in ([proj] if proj else D.projects()):
            D.render_project(p)
        D.render_workspace()


# ---------------------------------------------------------------- runs

def run_path(run_id):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,40}", run_id or ""):
        raise ApiError(400, "bad run id")
    return RUNS_DIR / f"{run_id}.json"


def load_run(run_id):
    run = D.load_json(run_path(run_id))
    if not run:
        raise ApiError(404, f"no run {run_id}")
    return run


def save_run(run):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RUNS_DIR / f".{run['id']}.tmp"
    tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, RUNS_DIR / f"{run['id']}.json")


def claude_args(run, claude):
    a = [claude]
    if run["mode"] == "background":
        a.append("--bg")  # --bg picks its own session id (it ignores --session-id); start_run reads it back
    if run.get("resume"):
        a += ["--resume", run["session_id"]]
    else:
        a += ([] if run["mode"] == "background" else [f"--session-id={run['session_id']}"]) + [f"--name={run['name']}"]
    a.append(f"--permission-mode={run['permission_mode']}")
    if run.get("remote_control") and run["mode"] == "terminal":
        a.append(f"--remote-control={run['name']}")
    prompt = (run.get("prompt") or "").strip()
    if prompt:
        a.append(("Task: " + prompt) if prompt.startswith("-") else prompt)
    return a


def run_env(run):
    env = dict(os.environ)
    env["DEVLOG_RUN_ID"] = run["id"]
    if run["mode"] == "terminal":  # a --bg session gets its own id, so its transcript path is not known up front
        env["DEVLOG_TRANSCRIPT"] = run["transcript"]
    return env


def start_run(proj, *, prompt, mode, permission_mode, feature="", name="", remote_control=False, resume_id=None, cwd=None, kind=""):
    claude = find_claude()
    if not claude:
        raise ApiError(503, "Claude Code CLI not found (install it, or set DEVLOG_CLAUDE to claude.exe)")
    if mode not in MODES:
        raise ApiError(400, f"mode must be one of {MODES}")
    if permission_mode not in PERMISSION_MODES:
        raise ApiError(400, f"permission mode must be one of {PERMISSION_MODES}")
    if not resume_id and not (prompt or "").strip():
        raise ApiError(400, "the prompt is empty")
    cwd = Path(cwd or proj)
    if not D.in_workspace(cwd) or not cwd.is_dir():
        raise ApiError(400, f"working folder must be an existing folder in {WORKSPACE}")
    sid = resume_id or str(uuid.uuid4())
    run = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + D.slugify(feature or kind or ("resume" if resume_id else "prompt"), 40),
        "kind": "resume" if resume_id else (kind if kind not in ("", "feature") else ("feature" if feature else "prompt")),
        "project": D.project_name(proj), "feature": feature, "name": name or f"{D.project_name(proj)} devlog run",
        "prompt": prompt or "", "mode": mode, "permission_mode": permission_mode, "remote_control": bool(remote_control),
        "resume": bool(resume_id), "cwd": str(cwd), "session_id": sid, "transcript": str(transcript_path(cwd, sid)),
        "started": D.now_iso(), "status": "starting",
    }
    save_run(run)
    if mode == "terminal":
        p = subprocess.Popen([sys.executable, str(DEVLOG_PY), "launch", run["id"]], cwd=str(cwd), env=run_env(run),
                             creationflags=CREATE_NEW_CONSOLE)
        run.update(status="running", launcher_pid=p.pid)
    else:
        try:
            r = subprocess.run(claude_args(run, claude), cwd=str(cwd), env=run_env(run), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            run["launch_output"] = (r.stdout + r.stderr).strip()[-4000:]
            run["status"] = "running" if r.returncode == 0 else "failed"
            if r.returncode:
                run["exit_code"] = r.returncode
            m = re.search(r"backgrounded\W+([0-9a-f]{6,12})\b", run["launch_output"])
            if m and not run.get("resume"):
                run["bg_id"] = m.group(1)
                for _ in range(12):  # the session registers within a moment; adopt its real id and transcript
                    _agents["at"] = 0
                    if resolve_bg(run):
                        break
                    time.sleep(0.5)
        except (OSError, subprocess.SubprocessError) as e:
            run.update(status="failed", launch_output=str(e))
    save_run(run)
    _agents["at"] = 0
    return run


def resolve_bg(run):
    """Point a background run at the session `claude --bg` actually created (matched by its short id)."""
    bg = run.get("bg_id")
    a = next((x for x in agents().values() if bg and (x.get("id") == bg or x["sessionId"].startswith(bg))), None)
    if a and a["sessionId"] != run["session_id"]:
        run["session_id"] = a["sessionId"]
        run["transcript"] = str(transcript_path(a.get("cwd") or run["cwd"], a["sessionId"]))
        return True
    return bool(a)


def launch(run_id):
    """Entry point of the console window a terminal run opens: run Claude here, record how it ended."""
    run = load_run(run_id)
    claude = find_claude()
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(f"Claude: {run['name']}")
    except (AttributeError, OSError):
        pass
    print(f"devlog run {run['id']}\n{run['name']}\nfolder: {run['cwd']}\npermissions: {run['permission_mode']}\n")
    code = -1
    if not claude:
        print("Claude Code CLI not found.")
    else:
        try:
            code = subprocess.call(claude_args(run, claude), cwd=run["cwd"], env=run_env(run))
        except (OSError, KeyboardInterrupt) as e:
            print(e)
    run = load_run(run_id)
    run.update(status="ended", exit_code=code, ended=D.now_iso())
    save_run(run)
    try:
        input("\nThe Claude session has ended (it is logged in the devlog if it changed files). Press Enter to close.")
    except (EOFError, KeyboardInterrupt):
        pass


def tail_transcript(path, n=14):
    """The last few things said and done in a session: user and assistant text, and tool calls."""
    items = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-600:]
    except OSError:
        return []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain") or d.get("type") not in ("user", "assistant"):
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        if d["type"] == "user" and (d.get("origin") or {}).get("kind") == "human":
            items.append({"at": d.get("timestamp"), "who": "you", "text": D.block_text(content).strip()[:1500]})
        elif d["type"] == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    items.append({"at": d.get("timestamp"), "who": "claude", "text": b["text"].strip()[:1500]})
                elif b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    what = inp.get("description") or inp.get("file_path") or inp.get("command") or inp.get("pattern") or ""
                    items.append({"at": d.get("timestamp"), "who": "tool", "text": f"{b.get('name')}: {str(what)[:200]}"})
    return items[-n:]


def runs_state(limit=60):
    if not RUNS_DIR.is_dir():
        return []
    logs = {}
    for sdir in D.session_dirs():
        for sid in (D.load_json(sdir / "session.json", {}) or {}).get("session_ids") or []:
            logs[sid] = sdir
    live = agents()
    out = []
    for f in sorted(RUNS_DIR.glob("*.json"), reverse=True)[:limit]:
        run = D.load_json(f)
        if not run:
            continue
        if run.get("bg_id") and not run["session_id"].startswith(run["bg_id"]) and resolve_bg(run):
            save_run(run)
        a = live.get(run["session_id"])
        if run["mode"] == "terminal" and run["status"] in ("starting", "running") and not pid_alive(run.get("launcher_pid")):
            run.update(status="ended", ended=run.get("ended") or D.now_iso(), note="window closed")
            save_run(run)
        state = run["status"]
        tp = Path(run["transcript"])
        if state == "running":
            state = {"busy": "working", "idle": "waiting"}.get((a or {}).get("status"), "running" if a else "starting")
            if (a or {}).get("state") == "blocked":
                state = "waiting"
            if run["mode"] == "background" and not a and tp.is_file():
                state = "ended"
            if tp.is_file() and any(i["who"] == "claude" and i["text"].startswith("Not logged in") for i in tail_transcript(tp, 4)):
                state = "failed"
                run["note"] = "Claude Code is not logged in on this PC: use “Log in to Claude Code”, then start it again."
        run.update(state=state, agent=a or None,
                   last_activity=D.iso_from_ts(tp.stat().st_mtime) if tp.is_file() else "",
                   log_href=D.href(DEVLOG_DIR, logs[run["session_id"]] / "index.html") if run["session_id"] in logs else "")
        out.append(run)
    return out


# ---------------------------------------------------------------- HTTP

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "devlog"

    def log_message(self, fmt, *args):  # quiet: only errors
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("devlog: " + (fmt % args) + "\n")

    # -- plumbing
    def allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers={"Cache-Control": "no-store"})

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ApiError(413, "request too large")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ApiError(400, "body is not JSON")

    def check_api(self):
        if not hmac.compare_digest(self.headers.get("X-Devlog-Token", ""), TOKEN):
            raise ApiError(403, "missing or wrong token (reload the page)")
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            raise ApiError(403, "cross-origin request refused")

    def handle_any(self, method):
        if not self.allowed_host():
            return self.send(421, b"wrong host", "text/plain")
        url = urlparse(self.path)
        try:
            if url.path == "/api/ping":
                return self.send_json({"ok": True, "app": "devlog"})
            if url.path.startswith("/api/"):
                self.check_api()
                return self.send_json(self.api(method, url.path, parse_qs(url.query)))
            if method != "GET":
                raise ApiError(405, "method not allowed")
            return self.static(url.path)
        except ApiError as e:
            return self.send_json({"error": str(e)}, e.code)
        except Exception as e:  # keep the server up; report the error to the page
            sys.stderr.write(f"devlog: {type(e).__name__}: {e}\n")
            return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    # -- static files
    def static(self, path):
        if path == "/favicon.ico":
            return self.send(204, b"", "image/x-icon")
        if path in ("/", "", "/devlog", "/devlog/"):
            return self.send(302, b"", "text/plain", {"Location": "/devlog/browse.html"})
        rel = unquote(path).lstrip("/")
        p = (WORKSPACE / rel).resolve()
        try:
            parts = p.relative_to(WORKSPACE).parts
        except ValueError:
            raise ApiError(403, "outside the workspace")
        if any(x.startswith(".") for x in parts) or p.suffix.lower() not in SERVE_EXT:
            raise ApiError(403, "not served")
        if not p.is_file():
            raise ApiError(404, "not found")
        ctype = MIME.get(p.suffix.lower(), "application/octet-stream")
        if p == (DEVLOG_DIR / "browse.html").resolve():
            cfg = json.dumps({"token": TOKEN, "port": self.server.server_address[1]})
            html = p.read_text(encoding="utf-8").replace("/*__SERVER__*/null", cfg, 1)
            return self.send(200, html.encode("utf-8"), ctype, {"Cache-Control": "no-store"})
        size = p.stat().st_size
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        cache = {"Cache-Control": "no-cache", "Accept-Ranges": "bytes"}
        if rng and (rng.group(1) or rng.group(2)):
            start = int(rng.group(1)) if rng.group(1) else max(0, size - int(rng.group(2)))
            end = min(size - 1, int(rng.group(2))) if rng.group(1) and rng.group(2) else size - 1
            if start >= size:
                return self.send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            with open(p, "rb") as fh:
                fh.seek(start)
                data = fh.read(end - start + 1)
            return self.send(206, data, ctype, {**cache, "Content-Range": f"bytes {start}-{end}/{size}"})
        return self.send(200, p.read_bytes(), ctype, cache)

    # -- API
    def api(self, method, path, q):
        if method == "GET" and path == "/api/state":
            with LOCK:
                D.forget_projects()
                manifest = D.build_manifest()
            return {"manifest": manifest, "runs": runs_state(), "claude": find_claude(), "auth": auth_status(),
                    "stt": STT.status(), "statuses": STATUSES,
                    "permission_modes": PERMISSION_MODES, "modes": MODES, "workspace": str(WORKSPACE)}
        if method == "GET" and path == "/api/prompt":
            proj = project_by_name((q.get("project") or [""])[0])
            return {"prompt": session_prompt((q.get("kind") or ["feature"])[0], proj, (q.get("slug") or [""])[0],
                                             (q.get("text") or [""])[0])}
        if method == "GET" and path == "/api/feature/description":
            return get_description(project_by_name((q.get("project") or [""])[0]), (q.get("slug") or [""])[0])
        m = re.fullmatch(r"/api/runs/([^/]+)/activity", path)
        if method == "GET" and m:
            run = load_run(m.group(1))
            return {"items": tail_transcript(run["transcript"])}
        if method != "POST":
            raise ApiError(404, "no such endpoint")
        if path == "/api/transcribe":  # raw audio body from the browser's recorder
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 40_000_000:
                raise ApiError(413 if n else 400, "audio missing or larger than 40 MB")
            audio = self.rfile.read(n)
            try:
                with LOCK:
                    D.forget_projects()
                    prompt = vocabulary()
                return STT.transcribe(audio, prompt)
            except RuntimeError as e:
                raise ApiError(503, str(e))
        if path == "/api/stt/warm":
            STT.warm()
            return STT.status()
        b = self.body_json()
        if path == "/api/note":
            where = add_note(project_by_name(b.get("project", "")), b.get("slug") or "", b.get("text", ""),
                             b.get("target", ""), b.get("title", ""), bool(b.get("dictated")))
            return {"ok": True, "path": where}
        if path == "/api/feature/status":
            set_status(project_by_name(b.get("project", "")), b.get("slug", ""), b.get("status", ""))
            return {"ok": True}
        if path == "/api/feature/new":
            proj = project_by_name(b.get("project", ""))
            slug = new_feature(proj, b.get("name", ""), b.get("parent") or "", b.get("summary") or "")
            return {"ok": True, "slug": slug, "href": D.href(DEVLOG_DIR, D.project_page(proj)) + f"#f-{slug}"}
        if path == "/api/feature/description":
            set_description(project_by_name(b.get("project", "")), b.get("slug", ""), b.get("summary", ""), b.get("what", ""))
            return {"ok": True}
        if path == "/api/feature/parent":
            set_parent(project_by_name(b.get("project", "")), b.get("slug", ""), b.get("parent") or "")
            return {"ok": True}
        if path == "/api/open":
            open_in(project_by_name(b.get("project", "")), b.get("app", ""))
            return {"ok": True}
        if path == "/api/run":
            proj = project_by_name(b.get("project", ""))
            slug, kind = b.get("slug") or "", b.get("kind") or ""
            if kind not in ("", "feature", "ask", "brainstorm", "describe", "plan"):
                raise ApiError(400, "unknown run kind")
            verb = {"brainstorm": "Brainstorm", "describe": "Describe", "plan": "Plan"}.get(kind, "")
            name = f"{D.project_name(proj)}: {verb or 'Session'}"
            if slug:
                f, _ = feature_entry(proj, slug)
                name = f"{D.project_name(proj)}: {(verb + ' ') if verb else ''}{f['name']}"
                if b.get("mark_in_progress") and kind in ("", "feature") and f["status"] != "in-progress" and not f["children"]:
                    set_status(proj, slug, "in-progress")
            run = start_run(proj, prompt=b.get("prompt", ""), mode=b.get("mode", "terminal"),
                            permission_mode=b.get("permission_mode", "auto"), feature=slug, name=name,
                            remote_control=b.get("remote_control"), kind=kind)
            return {"run": run}
        if path == "/api/resume":
            proj = project_by_name(b.get("project", ""))
            sid = b.get("session_id", "")
            if not re.fullmatch(r"[0-9a-f-]{36}", sid):
                raise ApiError(400, "bad session id")
            sdir = D.find_log(sid)
            log = D.load_json(sdir / "session.json", {}) if sdir else {}
            # Claude looks a session up by the folder it ran in, so resume it from that folder.
            from_run = load_run(b["run_id"]) if b.get("run_id") else {}
            cwd = from_run.get("cwd") or log.get("cwd") or str(proj)
            run = start_run(proj, prompt=b.get("prompt", ""), mode=b.get("mode", "terminal"),
                            permission_mode=b.get("permission_mode", "auto"), name=f"Resume: {log.get('title') or sid[:8]}",
                            resume_id=sid, cwd=cwd)
            return {"run": run}
        m = re.fullmatch(r"/api/runs/([^/]+)/(stop|attach)", path)
        if m:
            run, claude = load_run(m.group(1)), find_claude()
            if m.group(2) == "stop":
                if run["mode"] == "background" and claude:
                    subprocess.run([claude, "stop", run["session_id"]], capture_output=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                elif run.get("launcher_pid") and pid_alive(run["launcher_pid"]):
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(run["launcher_pid"])], capture_output=True, timeout=30)
                run.update(status="ended", ended=D.now_iso(), note="stopped from the devlog")
                save_run(run)
                _agents["at"] = 0
                return {"ok": True}
            if not claude:
                raise ApiError(503, "Claude Code CLI not found")
            subprocess.Popen([claude, "attach", run["session_id"]], cwd=run["cwd"], creationflags=CREATE_NEW_CONSOLE)
            return {"ok": True}
        if path == "/api/login":
            # Opens `claude auth login` in a console window; the user signs in there (the server never sees credentials).
            claude = find_claude()
            if not claude:
                raise ApiError(503, "Claude Code CLI not found")
            subprocess.Popen(["cmd", "/k", claude, "auth", "login"], cwd=str(WORKSPACE), creationflags=CREATE_NEW_CONSOLE)
            _auth["at"] = 0
            return {"ok": True}
        if path == "/api/render":
            rerender()
            return {"ok": True}
        raise ApiError(404, "no such endpoint")


def serve(port=8765, open_browser=False):
    url = f"http://127.0.0.1:{port}/"
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"devlog: port {port} is in use; if the devlog server is already running, open {url}")
        if open_browser:
            webbrowser.open(url)
        return
    httpd.daemon_threads = True
    rerender()  # pages and browse.html current before the first request
    print(f"devlog server on {url}  (Claude Code: {find_claude() or 'not found'})\nClose this window or press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
