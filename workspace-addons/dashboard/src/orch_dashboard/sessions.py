"""Live sessions (ORCH-359): one list of every session that the new Focus (draft D: the wall, the bar and the
panes) reads, served as GET /api/sessions and polled while the Preview switch is on.

Nothing here asks orch anything new. Status, what a session waits on, tool, model and open time come from the
state the page already polls (the state cache: `orch run status` rows, the tickets and the start line); the
last lines come from ONE `orch run screen <id> <id> ... --lines n --json` for every live session (one tmux call
in the core, answered in this process). The lines are kept for a moment, so several open pages share one read.

The shape (the wall builds on it; keep it in step with the PR text):

    {"sessions": [Session, ...], "lines": n, "now": "<ISO time>", "age_ms": <age of the state it was built from>}

    Session = {
      "id": "t_7k3f9q", "key": "ORCH-12", "title": "...",
      "status": "needs-you" | "working" | "in-line" | "idle" | "closed",
      "word": "Waits for you" | "Working" | "Starting" | "On hold" | "Stuck" | "In line" | "Idle" | "No session",
      "detail": "Your answer" | "Running pytest" | "" ...,          # the core's one-line detail
      "waiting_on": [{"kind": "person"|"time"|"ticket"|"external"|"command"|"hold", "what": "<plain words>"}],
      "question": "<the open question>" | null,                    # what Needs you shows
      "lines": ["<last screen line>", ...],                        # [] when nothing is live or no screen
      "tool": "<the tool's name>" | null, "model": "Opus" | null,
      "mode": "live" | "oneshot" | null,
      "opened_at": "<ISO>" | null, "open_seconds": int | null,     # when the session opened
      "idle_seconds": int | null, "closes_in_seconds": int | null, # idle close countdown (live sessions)
      "last_at": "<ISO>" | null,                                   # the ticket's last history line
    }

Sessions come in the order needs you, working, in line, idle, closed; inside one status by key number.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .data import run_orch

LINES = 8  # the last lines a tile or a pane shows by default
LINES_MAX = 40
TAILS_TTL = 1.5  # seconds one screen read is shared by every open page
ORDER = ("needs-you", "working", "in-line", "idle", "closed")
_TAILS: dict[tuple[str, int], tuple[float, tuple[str, ...], dict]] = {}
_LOCK = threading.Lock()
_TOOLS: dict[tuple[str, str], str | None] = {}


def tool_label(root: Path, agent: str | None) -> str | None:
    """The tool's own name from its adapter (core adapters), kept per agent name."""
    if not isinstance(agent, str) or not agent:
        return None
    key = (str(root), agent)
    if key not in _TOOLS:
        label = None
        try:
            from orch import adapters

            label = adapters.load(agent, root).get("label")
        except Exception:  # noqa: BLE001  an unknown or older adapter: the plain name
            label = None
        _TOOLS[key] = label if isinstance(label, str) and label else agent
    return _TOOLS[key]


def model_label(ticket: dict, run: dict) -> str | None:
    """The model of the session: a switch in this run, else the ticket's choice (orch's pick or a person's)."""
    name = ((run.get("claim") or {}) if isinstance(run.get("claim"), dict) else {}).get("model")
    if not isinstance(name, str) or not name:
        m = ticket.get("model")
        name = m.get("name") if isinstance(m, dict) else None
    if not isinstance(name, str) or not name:
        return None
    try:
        from orch.modelpick import LABELS
    except ImportError:
        LABELS = {}
    return LABELS.get(name, name.capitalize())


def tails(root: Path, orch_bin: str | None, ids: list[str], n: int) -> dict[str, list[str]]:
    """The last n lines of these live sessions, one read for all, shared for TAILS_TTL seconds."""
    if not ids:
        return {}
    key, want, now = (str(root), n), tuple(sorted(ids)), time.monotonic()
    with _LOCK:
        hit = _TAILS.get(key)
        if hit and hit[1] == want and now - hit[0] < TAILS_TTL:
            return hit[2]
    got = run_orch(orch_bin, ["run", "screen", *want, "--lines", str(n), "--json"], root, timeout=6.0)
    if isinstance(got, dict) and len(want) == 1 and isinstance(got.get("lines"), list):
        got = {"screens": {want[0]: {"lines": got["lines"]}}}  # one session: the command's own answer
    shots = got.get("screens") if isinstance(got, dict) else None
    out: dict[str, list[str]] = {}
    for tid, v in (shots if isinstance(shots, dict) else {}).items():
        rows = v.get("lines") if isinstance(v, dict) else None
        if tid in want and isinstance(rows, list):
            out[tid] = [r[:400] for r in rows if isinstance(r, str)][-n:]
    with _LOCK:
        _TAILS[key] = (now, want, out)
    return out


def _question(ticket: dict) -> str | None:
    for q in ticket.get("questions") or []:
        if isinstance(q, dict) and q.get("answer") is None and isinstance(q.get("text"), str):
            return " ".join(q["text"].split())[:300] or None
    return None


def _key_number(t: dict) -> int:
    try:
        return int(str(t.get("key") or "").rsplit("-", 1)[-1])
    except ValueError:
        return 0


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def session(ticket: dict, run: dict | None, in_line: bool, tool: str | None) -> dict:
    """One session from the state: the ticket, its `orch run status` row and whether it waits in line."""
    run = run if isinstance(run, dict) else {}
    claim = run.get("claim") if isinstance(run.get("claim"), dict) else {}
    helper = run.get("helper") if isinstance(run.get("helper"), dict) else {}
    alive = run.get("running") is True or run.get("state") == "maybe-stale"
    hs = helper.get("state") if alive else None
    if alive and run.get("state") == "maybe-stale" and not hs:
        hs = "stuck"
    if hs == "you":
        status, word = "needs-you", "Waits for you"
    elif hs == "idle":
        status, word = "idle", "Idle"
    elif alive:
        status = "working"
        word = helper.get("word") if isinstance(helper.get("word"), str) and helper.get("word") else "Working"
    elif in_line:
        status, word = "in-line", "In line"
    else:
        status, word = "closed", "No session"
    waits = [
        {"kind": str(w.get("kind") or ""), "what": " ".join(str(w.get("what") or "").split())[:200]}
        for w in run.get("waiting_on") or []
        if isinstance(w, dict) and w.get("what")
    ]
    if alive and isinstance(run.get("hold"), str) and run["hold"]:
        waits.append({"kind": "hold", "what": run["hold"]})
    last = run.get("last_activity") if isinstance(run.get("last_activity"), dict) else {}
    warmth = ticket.get("warmth") if isinstance(ticket.get("warmth"), dict) else {}
    return {
        "id": str(ticket.get("id")),
        "key": ticket.get("key") if isinstance(ticket.get("key"), str) else "",
        "title": " ".join(str(ticket.get("title") or "").split()) or "Untitled",
        "status": status,
        "word": word,
        "detail": helper.get("detail") if alive and isinstance(helper.get("detail"), str) else "",
        "waiting_on": waits if alive else [],
        "question": _question(ticket) if status == "needs-you" else None,
        "lines": [],
        "tool": tool if alive else None,
        "model": model_label(ticket, run),
        "mode": claim.get("mode") if alive and claim.get("mode") in ("live", "oneshot") else None,
        "opened_at": claim.get("started_at") if alive and isinstance(claim.get("started_at"), str) else None,
        "open_seconds": _int(run.get("age_seconds")) if alive else None,
        "idle_seconds": _int(run.get("idle_seconds")) if alive else None,
        "closes_in_seconds": _int(warmth.get("seconds_left")) if alive else None,
        "last_at": last.get("at") if isinstance(last.get("at"), str) else None,
    }


def build(root: Path, orch_bin: str | None, state: dict, lines: int = LINES) -> list[dict]:
    """Every session of the state, with the last lines of the live ones."""
    n = max(1, min(int(lines), LINES_MAX))
    runs = state.get("runs") if isinstance(state.get("runs"), dict) else {}
    line = state.get("start_line") if isinstance(state.get("start_line"), dict) else {}
    waiting = {str(x) for x in line.get("waiting") or [] if isinstance(x, str)}
    out, live = [], []
    for t in state.get("tickets") or []:
        if not isinstance(t, dict) or not t.get("id") or t.get("status") == "dropped":
            continue
        tid, run = str(t["id"]), runs.get(t["id"])
        if not isinstance(run, dict) and tid not in waiting:
            continue  # a done ticket with no session left
        claim = (run or {}).get("claim") if isinstance((run or {}).get("claim"), dict) else {}
        s = session(t, run, tid in waiting, tool_label(root, claim.get("agent")))
        if s["status"] == "closed" and t.get("status") == "done":
            continue
        out.append(s)
        if s["mode"] == "live":
            live.append(tid)
    shots = tails(root, orch_bin, live, n)
    for s in out:
        s["lines"] = shots.get(s["id"], [])
    rank = {k: i for i, k in enumerate(ORDER)}
    keys = {str(t.get("id")): _key_number(t) for t in state.get("tickets") or [] if isinstance(t, dict)}
    out.sort(key=lambda s: (rank[s["status"]], keys.get(s["id"], 0)))
    return out


def answer(root: Path, orch_bin: str | None, state: dict, age: float, lines: int = LINES) -> dict:
    n = max(1, min(int(lines), LINES_MAX))
    return {
        "sessions": build(root, orch_bin, state, n),
        "lines": n,
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_ms": int(age * 1000),
    }
