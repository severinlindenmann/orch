"""What a monitor needs to tell a stuck helper from a busy or waiting one, read-only: every run in one list,
the last lines of a live session's screen, what a run waits on and since when it has been idle.

Nothing here writes a run record, types into a session or stops a process."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from orch import modelpick, runs, runs_live, tickets

SCREEN_LINES = 40
SCREEN_MAX_LINES = 500
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
_INTERPRETERS = _SHELLS | {
    "env",
    "python",
    "python3",
    "node",
    "uv",
    "uvx",
    "npx",
    "ruby",
    "perl",
    "deno",
    "bun",
}
_ANSI = re.compile(r"\x1b(\[[0-9;:?]*[A-Za-z]|\][^\x07]*\x07)")  # colours, titles
_ETIME = re.compile(r"^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$")


def _etime_seconds(text: str) -> int | None:
    """`ps -o etime` ([[dd-]hh:]mm:ss) -> seconds."""
    m = _ETIME.match(text.strip())
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


_CACHE: dict = {}
CACHE_SECONDS = 2.0  # one `ps` for many tickets in one call (the dashboard asks for every run at once)


def _table() -> list[tuple[int, int, int | None, str]]:
    """(pid, ppid, seconds running, command line) for every process; empty where ps is missing (Windows)."""
    if os.name == "nt" or not shutil.which("ps"):
        return []
    if _CACHE and time.monotonic() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["rows"]
    rows = _ps_rows()
    _CACHE.update(at=time.monotonic(), rows=rows)
    return rows


def _ps_rows() -> list[tuple[int, int, int | None, str]]:
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,etime=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        rows.append(
            (int(parts[0]), int(parts[1]), _etime_seconds(parts[2]), parts[3] if len(parts) > 3 else "")
        )
    return rows


def _base(word: str) -> str:
    return word.rsplit("/", 1)[-1].lstrip("-")


def _is_tool_shell(cmd: str) -> bool:
    """A shell the agent started to run one command (`zsh -c ...`, `bash -lc ...`): what a Bash tool call is.
    MCP servers and other helpers the agent keeps open are not shells, so they never count."""
    words = cmd.split()
    if len(words) < 2 or _base(words[0]) not in _SHELLS:
        return False
    return any(w.startswith("-") and "c" in w[1:] and not w.startswith("--") for w in words[1:3])


def label(cmd: str) -> str:
    """A short, safe name for a command: the program's file name, or the script's when the program is an
    interpreter (`bash ~/x/pr-green.sh 12 repo` -> pr-green.sh). Arguments are never shown (they may carry
    tokens). `orch ref wait` / `orch github wait` is the wait for the pull request checks."""
    words = [w for w in cmd.split() if "=" not in w or w.startswith("-")]  # drops leading VAR=value
    if not words:
        return "a command"
    if _base(words[0]) == "orch" and words[1:3] in (["ref", "wait"], ["github", "wait"]):
        return "the pull request checks"
    for (
        w
    ) in words:  # `uv run python -m pytest` -> pytest: interpreters, their flags and verbs are looked past
        b = _base(w)
        if w.startswith("-") or b in _INTERPRETERS or b in ("run", "exec") or not b:
            continue
        return b[:60]
    return _base(words[0])[:60] or "a command"


def tool_commands(agent_pid: int | None, table: list | None = None) -> list[dict]:
    """The commands the agent runs right now through its shell tool (a test run, a CI watcher), oldest
    first: [{"label", "seconds", "pid"}]. One entry per tool shell: the program under it, else the shell."""
    if not isinstance(agent_pid, int) or agent_pid <= 0:
        return []
    rows = _table() if table is None else table
    kids: dict[int, list[tuple[int, int, int | None, str]]] = {}
    for row in rows:
        kids.setdefault(row[1], []).append(row)
    out = []
    for pid, _ppid, secs, cmd in kids.get(agent_pid, []):
        if not _is_tool_shell(cmd):
            continue
        under = sorted(kids.get(pid, []))  # lowest pid first: the left end of a pipeline, the main program
        # the work the shell started; a nested `sh -c` wrapper is looked through once
        inner = next((r for r in under if not _is_tool_shell(r[3])), None)
        if inner is None and under:
            inner = next(iter(sorted(kids.get(under[0][0], []))), None)
        name = label(inner[3]) if inner else "a shell command"
        out.append({"label": name, "seconds": secs, "pid": pid})
    out.sort(key=lambda d: -(d["seconds"] or 0))
    return out


def _age(iso: str | None, now: float | None = None) -> int | None:
    try:
        return max(0, int((time.time() if now is None else now) - runs._parse(iso)))
    except (TypeError, ValueError):
        return None


def span(seconds: int | None) -> str:
    """12 s, 4 min, 2 h 5 min, 3 d."""
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        h, m = divmod(seconds // 60, 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{seconds // 86400} d"


def waiting_on(root: Path, rec: dict | None, ticket: dict | None, table: list | None = None) -> list[dict]:
    """Everything a run waits on, in plain words: a person's answer or OK, a time or another ticket, and the
    commands it runs. [{"kind": "person"|"time"|"ticket"|"external"|"command", "what": "<words>", ...}]"""
    out: list[dict] = []
    t = ticket or {}
    open_q = [
        q["id"]
        for q in t.get("questions") or []
        if q.get("answer") is None and q.get("kind") in (None, "plain")
    ]
    if open_q:
        out.append({"kind": "person", "what": "an answer from the person", "ref": open_q[0]})
    w = t.get("waiting_on") if t.get("status") == "waiting" else None
    if isinstance(w, dict) and w.get("kind") in ("time", "ticket", "external"):
        ref = str((w.get("until") if w["kind"] == "time" else None) or w.get("ref") or "")  # time: "until"
        if w["kind"] == "time":
            from orch import net

            out.append({"kind": "time", "what": f"until {net.when(ref)}", "ref": ref})
        elif w["kind"] == "ticket":
            out.append({"kind": "ticket", "what": f"ticket {runs_live.ref(root, ref)}", "ref": ref})
        elif not open_q or ref not in open_q:
            out.append({"kind": "external", "what": ref or "something outside", "ref": ref})
    live = (rec or {}).get("live") or {}
    if rec and rec.get("mode") == "live" and live.get("state") == "attention":
        out.append({"kind": "person", "what": "the person's OK on the screen"})
    if rec and runs.state(rec) == "alive":
        for c in tool_commands(rec.get("agent_pid"), table):
            out.append(
                {
                    "kind": "command",
                    "what": f"{c['label']} (running {span(c['seconds'])})",
                    "label": c["label"],
                    "seconds": c["seconds"],
                }
            )
    return out


def idle_since(rec: dict | None) -> str | None:
    """When a live run went quiet at its prompt (UTC, ...Z); None while it works or for a one-step run."""
    live = (rec or {}).get("live") or {}
    if rec and rec.get("mode") == "live" and live.get("state") == "idle":
        return live.get("since")
    return None


def signal(rec: dict | None, waits: list[dict]) -> str:
    """One word a monitor can act on: working | waiting | idle | starting | stale | ended | none.
    idle = at its prompt with nothing to wait on: the one that may be stuck."""
    if not rec:
        return "none"
    st = runs.state(rec)
    if st == "dead":
        return "ended"
    if st == "maybe-stale":
        return "stale"
    state = ((rec.get("live") or {}).get("state")) if rec.get("mode") == "live" else "working"
    if state == "starting":
        return "starting"
    if state == "working":
        return "working"
    return "waiting" if waits else "idle"


STUCK_MINUTES = 20  # idle at its prompt this long with nothing to wait on: Stuck, not Idle
HELPER_WORDS = {
    "working": "Working",
    "starting": "Starting",
    "you": "Waits for you",
    "waiting": "On hold",  # never a bare "Waiting": the owner's word for a waiting ticket is Needs you
    "idle": "Idle",
    "stuck": "Stuck",
}


def helper_state(sig: str, waits: list[dict], idle_seconds: int | None) -> dict | None:
    """The ONE state of a helper that every page shows (Home, the ticket page, Focus): a key, its word and a
    plain detail line. None when no helper runs (signal none or ended)."""
    if sig in ("none", "ended"):
        return None
    detail = ""
    if sig == "stale":
        key, detail = "stuck", "No update for a while"
    elif sig == "idle":
        idle = idle_seconds or 0
        key = "stuck" if idle >= STUCK_MINUTES * 60 else "idle"
        detail = f"Nothing running for {span(idle)}" if idle_seconds is not None else "Nothing running"
    elif sig == "waiting":
        person = [w for w in waits if w.get("kind") == "person"]
        if person:
            key = "you"
            answer, ok = any(w.get("ref") for w in person), any(not w.get("ref") for w in person)
            detail = {
                (True, False): "Your answer",
                (False, True): "Your OK on the screen",
                (True, True): "Your answer and your OK on the screen",
            }[(answer, ok)]
        else:
            key = "waiting"
            parts = [
                f"{w['label']} · {span(w.get('seconds'))}"
                if w.get("kind") == "command" and w.get("label")
                else w["what"]
                for w in waits
                if w.get("what")
            ]
            detail = "Waiting for " + ", ".join(parts)
    elif sig == "starting":
        key = "starting"
    else:
        key = "working"
        cmds = [w["label"] for w in waits if w.get("kind") == "command" and w.get("label")]
        if cmds:
            detail = "Running " + ", ".join(cmds)
    return {"state": key, "word": HELPER_WORDS[key], "detail": detail}


def last_activity(root: Path, ticket: dict | None) -> dict | None:
    """When a helper last wrote to the ticket and what (its newest history line, as shown), or None."""
    from orch import history

    for h in reversed(history.lines(root, ticket)):
        if isinstance(h, dict) and str(h.get("by") or "").startswith("agent:") and h.get("at"):
            text = " ".join(str(h.get("text") or "").split())[:200]
            return {"at": h["at"], "text": text, "seconds": _age(h["at"])}
    return None


def describe(root: Path, tid: str, rec: dict | None = None, table: list | None = None) -> dict:
    """The monitor fields of one ticket's run (orch run status and orch run list share them)."""
    rec = runs.read(root, tid) if rec is None else rec
    ticket = None
    with contextlib.suppress(Exception):
        ticket = tickets.load(root, tid)
    waits = waiting_on(root, rec, ticket, table)
    since = idle_since(rec)
    sig = signal(rec, waits)
    return {
        "signal": sig,
        "helper": helper_state(sig, waits, _age(since)),
        "last_activity": last_activity(root, ticket),
        "waiting_on": waits,
        "idle_since": since,
        "idle_seconds": _age(since),
        "age_seconds": _age((rec or {}).get("started_at")),
    }


def line(info: dict) -> str:
    """The plain sentence for orch run status: what it waits on, or since when it is idle."""
    waits = [w["what"] for w in info.get("waiting_on") or []]
    sig = info.get("signal")
    if sig == "idle":
        return f"Idle at its prompt for {span(info.get('idle_seconds'))}, nothing running."
    if sig == "waiting":
        idle = f" (quiet for {span(info['idle_seconds'])})" if info.get("idle_seconds") is not None else ""
        return "Waiting on: " + ", ".join(waits) + idle + "."
    if waits and sig == "working":
        return "Running: " + ", ".join(w["what"] for w in info["waiting_on"] if w["kind"] == "command") + "."
    return ""


def list_runs(root: Path) -> list[dict]:
    """Every run this workspace knows (alive or ended without finishing), newest first."""
    table = _table()
    out = []
    for rec in runs_live.records(root):
        tid = rec["ticket"]
        if tickets.is_general(root, tid):
            continue
        info = describe(root, tid, rec, table)
        model = None
        with contextlib.suppress(Exception):
            model = (modelpick.chosen(tickets.load(root, tid)) or {}).get("name")
        out.append(
            {
                "ticket": tid,
                "key": runs_live.ref(root, tid),
                "run": rec["run"],
                "agent": rec.get("agent"),
                "model": model,
                "mode": rec.get("mode"),
                "by": rec.get("by"),
                "state": runs.state(rec),
                "live_state": (rec.get("live") or {}).get("state"),
                "started_at": rec.get("started_at"),
                **info,
            }
        )
    out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return out


def list_text(rows: list[dict]) -> str:
    if not rows:
        return "No runs right now."
    head = ("TICKET", "RUN", "MODEL", "AGE", "SIGNAL", "IDLE", "WAITING ON")
    body = [
        (
            r["key"],
            r["run"],
            modelpick.LABELS.get(r.get("model") or "", "-"),
            span(r["age_seconds"]),
            r["signal"],
            span(r["idle_seconds"]) if r["idle_seconds"] is not None else "-",
            ", ".join(w["what"] for w in r["waiting_on"]) or "-",
        )
        for r in rows
    ]
    widths = [max(len(str(x[i])) for x in [head, *body]) for i in range(len(head) - 1)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths) + "  {}"
    return "\n".join(fmt.format(*row) for row in [head, *body])


def screen(root: Path, tid: str, lines: int = SCREEN_LINES) -> dict:
    """The last lines of a live session's screen, read-only (tmux capture-pane; nothing is typed)."""
    from orch.errors import Refused

    rec = runs.read(root, tid)
    name = runs_live.ref(root, tid)
    if rec and rec.get("mode") != "live":
        log = f" Its output: {rec['log']}" if rec.get("log") else ""
        raise Refused(f"The agent on {name} works one step at a time, so there is no screen to show.{log}")
    if not rec or not runs_live.session_exists(root, tid):
        why = "" if shutil.which("tmux") else " Live sessions need tmux, which is not installed here."
        raise Refused(f"No live session on {name}.{why}")
    n = max(1, min(int(lines), SCREEN_MAX_LINES))
    r = runs_live.tmux(
        root, "capture-pane", "-p", "-J", "-S", f"-{n + 50}", "-t", runs_live.target(tid), timeout=5
    )
    if r.returncode != 0:
        raise Refused(f"Could not read the screen of {name}: {r.stderr.strip() or 'unknown error'}")
    rows = runs_live.clean(_ANSI.sub("", r.stdout)).rstrip("\n").split("\n")
    rows = [r.rstrip() for r in rows]
    while rows and not rows[-1].strip():
        rows.pop()
    rows = rows[-n:]
    return {"ticket": tid, "key": name, "run": rec["run"], "lines": rows, **describe(root, tid, rec)}
