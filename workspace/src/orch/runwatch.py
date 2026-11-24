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
    if _base(words[0]) == "orch" and words[1:3] == ["github", "wait"]:
        kind = next((w for w in words[3:] if not w.startswith("-")), "")
        if kind in ("merge", "pr", "comment", "other"):  # waits for GitHub's write limit, not for checks
            return f"the GitHub {'merge' if kind == 'merge' else kind} limit"
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


_TEST_PROGRAMS = {"pytest", "jest", "vitest", "mocha", "ava", "playwright", "xctest", "rspec", "phpunit"}
_BUILD_PROGRAMS = {"make", "xcodebuild", "tsc", "webpack", "vite", "esbuild", "gradle", "mvn", "msbuild"}
_WAIT_PROGRAMS = {"sleep", "wait", "timeout"}
_SCRIPT_ENDS = (".sh", ".py", ".js", ".cjs", ".mjs", ".ts", ".rb", ".ps1")


def doing(cmd: str) -> str:
    """What a helper does with one command, in plain words for every page (ORCH-407: never a program name
    such as orch, sleep or walk.cjs): Running tests, Building, Waiting, Waiting for the pull request checks,
    Updating the ticket, Working on the code, Running a script, else Running a command. Takes a whole command
    or its label(). Arguments are only matched, never shown."""
    text = " ".join(str(cmd or "").split())
    if text.startswith("the "):  # label() already said what it waits for
        return "Waiting for " + text
    if text.startswith("helper: "):
        return "Working with its own helper"
    words = [w for w in text.split() if "=" not in w or w.startswith("-")]
    bases = [_base(w).lower() for w in words if not w.startswith("-")]
    if not bases:
        return "Running a command"
    if is_check_wait(text):
        return "Waiting for the pull request checks"
    first = next((b for b in bases if b not in _INTERPRETERS and b not in ("run", "exec")), bases[0])
    orch_waits = first in ("orch", "orch.exe") and "--wait" in words  # any orch command that waits
    if first in _WAIT_PROGRAMS or orch_waits:
        return "Waiting"
    tests = first in _TEST_PROGRAMS or "test" in bases or "--test" in words
    if tests or any(b.startswith("test_") or ".test." in b or ".spec." in b for b in bases):
        return "Running tests"
    if first in _BUILD_PROGRAMS or "build" in bases:
        return "Building"
    if first in ("orch", "orch.exe"):
        return "Updating the ticket"
    if first in ("git", "gh"):
        return "Working on the code"
    if first.endswith(_SCRIPT_ENDS):
        return "Running a script"
    return "Running a command"


_CHECK_WAITS = {("ref", "wait"), ("github", "wait")}


def is_check_wait(cmd: str) -> bool:
    """True for orch's own waits on checks or the GitHub write limit (`orch ref wait`, `orch github wait`):
    they only poll. Anything else (tests, builds, a script) is real work."""
    words = cmd.split()
    for i, w in enumerate(words):
        if _base(w) in ("orch", "orch.exe"):
            return tuple([x for x in words[i + 1 :] if not x.startswith("-")][:2]) in _CHECK_WAITS
    return False


def only_waits_for_checks(agent_pid: int | None, table: list | None = None) -> bool:
    """The agent runs commands, and every one of them is a wait on checks (is_check_wait)."""
    cmds = tool_commands(agent_pid, table)
    return bool(cmds) and all(c["check_wait"] for c in cmds)


def runs_check_wait(agent_pid: int | None, table: list | None = None) -> bool:
    """One of the commands the agent runs is a wait on checks (is_check_wait). Such a wait ends by itself
    (its own timeout) and merges on green: the idle close must not kill it (ORCH-221)."""
    return any(c["check_wait"] for c in tool_commands(agent_pid, table))


def tool_commands(agent_pid: int | None, table: list | None = None) -> list[dict]:
    """The commands the agent runs right now through its shell tool (a test run, a CI watcher), oldest
    first: [{"label", "seconds", "pid", "check_wait"}]. One entry per tool shell: the program under it, else
    the shell."""
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
        out.append(
            {
                "label": name,
                "doing": doing(inner[3]) if inner else "Running a command",
                "seconds": secs,
                "pid": pid,
                "check_wait": bool(inner) and is_check_wait(inner[3]),
            }
        )
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
    commands it runs. [{"kind": "person"|"time"|"ticket"|"pr"|"external"|"command", "what": "<words>"...}]"""
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
    if isinstance(w, dict) and w.get("kind") in ("time", "ticket", "pr", "external"):
        ref = str((w.get("until") if w["kind"] == "time" else None) or w.get("ref") or "")  # time: "until"
        if w["kind"] == "time":
            from orch import net

            out.append({"kind": "time", "what": f"until {net.when(ref)}", "ref": ref})
        elif w["kind"] == "ticket":
            out.append({"kind": "ticket", "what": f"ticket {runs_live.ref(root, ref)}", "ref": ref})
        elif w["kind"] == "pr":
            out.append({"kind": "pr", "what": f"pull request #{ref.rsplit('/', 1)[-1]}", "ref": ref})
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
                    "doing": c.get("doing") or doing(c["label"]),
                    "seconds": c["seconds"],
                }
            )
        from orch import bgwork

        for a in bgwork.subagents(root, rec):  # ORCH-267: its own helpers in the background, prompt idle
            out.append(
                {
                    "kind": "command",
                    "what": f"a helper of its own: {a['what']} (running {span(a['seconds'])})",
                    "label": f"helper: {a['what']}",
                    "seconds": a["seconds"],
                    "subagent": True,
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
    "you": "Needs you",
    "waiting": "On hold",  # never a bare "Waiting": the owner's word for a waiting ticket is Needs you
    "idle": "Idle",
    "stuck": "Stuck",
    "limit": "Stopped: usage limit",  # ORCH-643: noted by the watcher (limitstop); it continues by itself
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
            # plain words for what it does (ORCH-407), never the program's name
            cmds = [f"{_doing(w)} · {span(w.get('seconds'))}" for w in waits if _is_cmd(w)]
            other = [w["what"] for w in waits if not _is_cmd(w) and w.get("what") and not _time_passed(w)]
            # a time wait already says "until 07:50": "Waiting until 07:50", never "Waiting for until 07:50";
            # a time that has passed is no reason to be on hold (ORCH-1465 follow-up)
            if other:
                lead = "Waiting " if all(x.startswith("until ") for x in other) else "Waiting for "
                cmds.append(lead + ", ".join(other))
            detail = ", ".join(cmds)
    elif sig == "starting":
        key = "starting"
    else:
        key = "working"
        detail = ", ".join(dict.fromkeys(_doing(w) for w in waits if _is_cmd(w)))
    return {"state": key, "word": HELPER_WORDS[key], "detail": detail}


def limit_state(root: Path, tid: str, rec: dict | None = None, now: float | None = None) -> dict | None:
    """ORCH-643: the helper state of a ticket the watcher noted as stopped on the usage limit (limitstop),
    with the time orch starts it again; None when the ticket is not noted, or when its helper started working
    again after the note (a person's prompt or start; the note stays until the reset). Home showed such a
    helper as working or as waiting for an OK on the screen (report r-1118-1812-ws)."""
    from orch import limitstop

    data = limitstop.read(root)
    noted = (data.get("tickets") or {}).get(tid)
    if not isinstance(noted, dict):
        return None
    live = (rec or {}).get("live") or {}
    if live.get("state") in ("working", "starting"):
        try:
            if runs._parse(live.get("since")) > float(noted.get("at") or 0):
                return None  # it went on after the note
        except (TypeError, ValueError):
            pass
    now = time.time() if now is None else now
    at = limitstop.until(data)  # the reset plus the short wait: when the watcher starts it again
    detail = f"Continues at {limitstop.clock(at)}" if at is not None and at > now else "Continues shortly"
    return {"state": "limit", "word": HELPER_WORDS["limit"], "detail": detail}


def _time_passed(w: dict) -> bool:
    """A time wait whose time is already behind us (the ticket stays waiting until its helper looks again)."""
    import datetime as dt

    if w.get("kind") != "time":
        return False
    try:
        at = dt.datetime.fromisoformat(str(w.get("ref") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.astimezone()
    return at <= dt.datetime.now(dt.UTC)


def _is_cmd(w: dict) -> bool:
    return w.get("kind") == "command" and bool(w.get("label") or w.get("doing"))


def _doing(w: dict) -> str:
    return str(w.get("doing") or doing(str(w.get("label") or "")))


_SETTINGS_WRITE = re.compile(r"(Set|Removed) ext\.[a-z][a-z0-9-]*(\.[\w-]+)?")


def last_activity(root: Path, ticket: dict | None) -> dict | None:
    """When a helper last wrote to the ticket and what (its newest history line, as shown), or None.
    An add-on settings write (`Set ext.focus`) is bookkeeping, not work: it is skipped."""
    from orch import history

    for h in reversed(history.lines(root, ticket)):
        if isinstance(h, dict) and str(h.get("by") or "").startswith("agent:") and h.get("at"):
            if _SETTINGS_WRITE.fullmatch(str(h.get("text") or "").strip()):
                continue
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
    helper = helper_state(sig, waits, _age(since))
    if helper is not None:
        helper = limit_state(root, tid, rec) or helper
    return {
        "signal": sig,
        "helper": helper,
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


def line_text(line: list[dict]) -> str:
    """The tickets waiting for a free helper place, in the order they start ('' when none)."""
    if not line:
        return ""
    names = ", ".join(
        q["key"] + (f" ({q['priority']})" if q.get("priority") not in (None, "normal") else "") for q in line
    )
    return f"Waiting for a free helper place, in this order: {names}."


def list_text(rows: list[dict], line: list[dict] | None = None) -> str:
    waits = line_text(line or [])
    if not rows:
        return "No runs right now." + (f"\n{waits}" if waits else "")
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
    return "\n".join(fmt.format(*row) for row in [head, *body]) + (f"\n\n{waits}" if waits else "")


LOG_TAIL_BYTES = 64 * 1024  # how much of a one-step run's log is read for its last lines


def log_tail(root: Path, rec: dict, lines: int = SCREEN_LINES) -> list[str]:
    """The last lines of a one-step run's output (its log under .orch/run/logs), as a screen shows them: no
    colours or control characters, CRLF read as one line end, anything that looks like a key hidden (R5.2).
    [] when there is no log yet. Read-only (ORCH-1797: Focus shows it where no live screen can be had)."""
    from orch.phone_view import redact

    rel = rec.get("log") if isinstance(rec, dict) else None
    if not isinstance(rel, str) or not rel:
        return []
    path = root / rel
    with contextlib.suppress(OSError, ValueError):
        if not path.resolve().is_relative_to((root / ".orch" / "run" / "logs").resolve()):
            return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            start = max(0, f.tell() - LOG_TAIL_BYTES)
            f.seek(start)
            data = f.read()
    except OSError:
        return []
    raw = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if start:
        raw = raw[1:]  # the first line was cut by the read
    rows = [runs_live.clean(_ANSI.sub("", ln)).rstrip() for ln in raw]
    rows = [r for i, r in enumerate(rows) if r.strip() or (i and rows[i - 1].strip())]
    while rows and not rows[-1].strip():
        rows.pop()
    n = max(1, min(int(lines), SCREEN_MAX_LINES))
    return [redact(r) for r in rows[-n:]]


def screen(root: Path, tid: str, lines: int = SCREEN_LINES) -> dict:
    """The last lines of a live session's screen, read-only (tmux capture-pane; nothing is typed). A run that
    works one step at a time has no screen: its log's last lines instead, with `log` naming the file."""
    from orch.errors import Refused

    rec = runs.read(root, tid)
    name = runs_live.ref(root, tid)
    if rec and rec.get("mode") != "live":
        if not rec.get("log"):
            raise Refused(f"The agent on {name} works one step at a time, so there is no screen to show.")
        rows = log_tail(root, rec, lines)
        return {"ticket": tid, "key": name, "run": rec["run"], "lines": rows, "log": rec["log"], **describe(root, tid, rec)}
    if not rec or not runs_live.session_exists(root, tid):
        why = "" if shutil.which("tmux") else " Live sessions need tmux, which is not installed here."
        raise Refused(f"No live session on {name}.{why}")
    n = max(1, min(int(lines), SCREEN_MAX_LINES))
    r = runs_live.tmux(
        root, "capture-pane", "-e", "-p", "-J", "-S", f"-{n + 50}", "-t", runs_live.target(tid), timeout=5
    )
    if r.returncode != 0:
        raise Refused(f"Could not read the screen of {name}: {r.stderr.strip() or 'unknown error'}")
    rows, hint = _rows(r.stdout, n)
    out = {"ticket": tid, "key": name, "run": rec["run"], "lines": rows, **describe(root, tid, rec)}
    if hint is not None:
        out["suggestion"] = hint
    return out


def _rows(text: str, n: int) -> tuple[list[str], str | None]:
    """The captured pane as plain lines: no colours or control characters, a greyed-out suggestion said as
    such, no empty lines at the end, the last n. (rows, suggestion or None)."""
    raw = text.rstrip("\n").split("\n")
    rows = [runs_live.clean(_ANSI.sub("", ln)).rstrip() for ln in raw]
    hint = _suggestion(raw, rows)
    rows = _below_frame_dropped(rows)
    rows = _banner_dropped(rows)
    rows = [r for r in rows if not (_is_frame(r) or _is_notice(r) or _is_tip(r))]
    # at most one blank row in a row: padding must not fill a short view
    rows = [r for i, r in enumerate(rows) if r.strip() or (i and rows[i - 1].strip())]
    while rows and not rows[-1].strip():
        rows.pop()
    return rows[-n:], hint


_PROMPT = re.compile(r"^\s*[>\u276f\u203a]")


def _below_frame_dropped(rows: list[str]) -> list[str]:
    """The tool's status rows under its prompt box (model, usage, mode, shortcuts) are frame, not work.
    Only when the box is found (a rule, a prompt row, a rule) are the rows under it dropped."""
    rules = [i for i, r in enumerate(rows) if _RULE.match(r)]
    for b in reversed(rules):
        a = next((i for i in reversed(rules) if i < b), None)
        if a is not None and _PROMPT.match(rows[a + 1]) and b - a <= 12:
            return rows[: b + 1]
    return rows


_RULE = re.compile(r"^[\s\u2500-\u257f\-=_~]{3,}$")  # a row of box lines or dashes
_EMPTY_PROMPT = re.compile(r"^\s*[>\u276f\u203a]\s*$")
_FOOTER = re.compile(r"^\s*(\? for shortcuts|\u23f5\u23f5)")


def _is_frame(row: str) -> bool:
    """The tool's own prompt frame (rows of rules, an empty prompt, the shortcut footer) says nothing about
    the work, and fills the last lines of a narrow or short view. Typed or suggested prompt text stays."""
    return bool(_RULE.match(row) or _EMPTY_PROMPT.match(row) or _FOOTER.match(row))


# ORCH-707: a fresh session starts with the tool's banner (a block-glyph logo or a rounded box beside its
# name, version and the full folder path), orch's own notice line at the prompt and tool tips. None of it is
# work, and ids, a path and commands must not reach a person in the last lines.
_BANNER_START = re.compile(r"^\s*[\u2580-\u259f\u256d]")  # logo block glyphs, or a rounded box top
_BANNER_ROW = re.compile(r"^\s*[\u2580-\u259f\u256d\u2502\u2570]")  # ... and its sides and bottom
_VERSION = re.compile(r"\bv\d+\.\d+|\b\d+\.\d+\.\d+\b")
_NOTICE_ROW = re.compile(
    r"^\s*(?:[>\u276f\u203a]\s*)?(?:"
    + "|".join(
        re.escape(t).replace(re.escape("{tid}"), r"t_[a-z0-9]{6,16}") for t in runs_live._NOTICE.values()
    )
    + r")\s*$"
)
_TIP = re.compile(r"^[\s\W]*(Tip:|tmux focus-events off\b)")


def _banner_dropped(rows: list[str]) -> list[str]:
    """Drop each run of banner rows (logo block glyphs, or a rounded box) that names a version (v2.1 or
    1.2.3). A progress bar or a table drawn with straight corners stays."""
    out: list[str] = []
    i = 0
    while i < len(rows):
        j = i
        if _BANNER_START.match(rows[i]):
            j = i + 1
            while j < len(rows) and _BANNER_ROW.match(rows[j]):
                j += 1
        if j > i and any(_VERSION.search(r) for r in rows[i:j]):
            i = j
            continue
        out.extend(rows[i : max(j, i + 1)])
        i = max(j, i + 1)
    return out


def _is_notice(row: str) -> bool:
    """orch's own start or new-input notice (runs_live.notice_line), typed at the prompt."""
    return bool(_NOTICE_ROW.match(row))


def _is_tip(row: str) -> bool:
    """A tool's tip row (for example "Tip: ..." or the terminal focus-events advice)."""
    return bool(_TIP.search(row))


_TAIL_MARK = "@@orch-tail "


def tails(root: Path, tids: list[str], lines: int = SCREEN_LINES) -> dict[str, dict]:
    """The last lines of several live sessions in ONE tmux call (the dashboard asks for every session every
    few seconds; a process per session was the cost with 24 of them).
    {ticket: {"lines": [...], "suggestion"?}} for each ticket whose live session exists; the others are left
    out. Read-only, like screen(). A run that works one step at a time gives its log's last lines, with
    `"log": true` (ORCH-1797)."""
    n = max(1, min(int(lines), SCREEN_MAX_LINES))
    todo = []
    out: dict[str, dict] = {}
    for tid in dict.fromkeys(tids):
        if not tickets._ID_RE.fullmatch(tid or ""):
            continue
        rec = runs.read(root, tid)
        if not rec or runs.state(rec) != "alive":
            continue
        if rec.get("mode") == "live":
            todo.append(tid)
        elif rec.get("log"):
            out[tid] = {"lines": log_tail(root, rec, n), "log": True}
    if not todo or not shutil.which("tmux"):
        return out
    for _ in range(len(todo)):  # tmux stops a chain at the first session that is gone: drop it, read the rest
        args: list[str] = []
        for tid in todo:
            args += ["display-message", "-p", _TAIL_MARK + tid, ";"]
            args += ["capture-pane", "-e", "-p", "-J", "-S", f"-{n + 50}", "-t", runs_live.target(tid), ";"]
        try:
            r = runs_live.tmux(root, *args[:-1], timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return out
        got: list[str] = []
        for part in r.stdout.split(_TAIL_MARK)[1:]:
            tid, _, body = part.partition("\n")
            if tid in todo:
                got.append(tid)
                rows, hint = _rows(body, n)
                out[tid] = {"lines": rows, **({"suggestion": hint} if hint is not None else {})}
        if r.returncode == 0:
            break
        # the last marked session failed (its capture printed nothing): it is gone; go on after it
        if not got:  # no tmux server here (no session at all)
            break
        out.pop(got[-1], None)
        todo = todo[len(got) :]
        if not todo:
            break
    return out


_RAW_GLYPH = re.compile(r"^((?:\x1b\[[0-9;]*m)*)(\s*[>\u276f\u203a]\s?)")
SUGGESTION = "(greyed-out suggestion from the tool, not typed: {text})"


def _suggestion(raw: list[str], rows: list[str]) -> str | None:
    """ORCH-190: a tool may show a greyed-out suggestion for the next message in its empty prompt box (for
    example "go ahead", "check if the PR merged"). Without its colour it reads like a message typed but never
    sent. When the last prompt row holds only such hint-styled text, that row is rewritten in place (rows) to
    say so, and the suggestion is returned; None when there is none or any doubt."""
    for i in range(len(raw) - 1, -1, -1):
        m = _RAW_GLYPH.match(raw[i])
        if not m:
            continue
        tail = raw[i][m.end() :]
        text = runs_live.clean(_ANSI.sub("", tail)).strip()
        if not text or runs_live._is_hint(tail) is not True:
            return None
        glyph = runs_live.clean(_ANSI.sub("", raw[i][: m.end()]))
        rows[i] = glyph + SUGGESTION.format(text=text)
        return text
    return None
