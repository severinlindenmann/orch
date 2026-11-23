"""Live sessions (ORCH-359): one list of every session that the live page (draft D: the wall, the bar and the
panes) reads, served as GET /api/sessions and polled while Focus is shown.

Nothing here asks orch anything new. Status, what a session waits on, tool, model and open time come from the
state the page already polls (the state cache: `orch run status` rows, the tickets and the start line); the
last lines come from ONE `orch run screen <id> <id> ... --lines n --json` for every live session (one tmux call
in the core, answered in this process). The lines are kept for a moment, so several open pages share one read.

The shape (the wall builds on it; keep it in step with the PR text):

    {"sessions": [Session, ...], "groups": [Group, ...], "lines": n, "now": "<ISO time>", "age_ms": <age of the state it was built from>}

    Session = {
      "id": "t_7k3f9q", "key": "ORCH-12", "title": "...",
      "status": "needs-you" | "working" | "in-line" | "idle" | "closed",
      "word": "Needs you" | "Working" | "Starting" | "On hold" | "Stuck" | "Stopped: usage limit" | "In line" | "Idle" | "No session",
      "detail": "Your answer" | "Running pytest" | "" ...,          # the core's one-line detail
      "step": "<the step it works on now>" | "",                    # orch check start; the live line when no detail
      "waiting_on": [{"kind": "person"|"time"|"ticket"|"external"|"command"|"hold", "what": "<plain words>"}],
      "question": "<the open question>" | null,                    # what Needs you shows
      "lines": ["<last screen line>", ...],                        # [] when nothing is live or no screen
      "tool": "<the tool's name>" | null, "model": "Opus" | null,
      "mode": "live" | "oneshot" | null,
      "opened_at": "<ISO>" | null, "open_seconds": int | null,     # when the session opened
      "idle_seconds": int | null, "closes_in_seconds": int | null, # idle close countdown (live sessions)
      "last_at": "<ISO>" | null,                                   # the ticket's last history line
      "pinned": bool, "name": "<own name>" | null,                 # kept in the workspace (sessionprefs, ORCH-361)
      "kind": "" | "empty" | "chat" | "terminal" | "manager",      # "" = a ticket's; else a session without a
                                                                   # ticket (ORCH-364), named by its title
      "parent": "t_..." | null,                                    # the ticket's parent (epic, factory order)
      "small": [{"what": "<plain words>", "seconds": int | null}],  # small helpers the helper started inside its
    }                                                              # session (ORCH-345), watch only

Groups (ORCH-345): an epic or a factory order whose tree has a session. One Group per top ticket of a parent chain:

    Group = {
      "id": "t_..." (the top ticket), "key": "ORCH-261", "title": "...", "kind": "factory" | "epic",
      "members": [Member, ...],                                    # the top ticket first, then its open sub-tickets
    }                                                              # depth first, by key number
    Member = {"id", "key", "title", "depth": 0.., "main": bool,    # main = the top ticket (the main helper)
              "status", "word", "small": [...]}                    # as in Session; "closed" = no session yet

A group is listed when two or more of its members have a session (in line counts), or one has small helpers.

A session without a ticket is listed only while it is open; a plain terminal has no helper and shows as idle,
word "Open", until it is closed.

Sessions come in the order needs you, working, in line, idle, closed; inside one status by key number.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from . import sessionprefs
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


def _needs_person(ticket: dict) -> bool:
    """The ticket waits for the person: a result to check, an open question, or a helper that could not start (the
    one needs-you number counts each, ORCH-1687)."""
    if ticket.get("general") is True or ticket.get("status") in ("done", "dropped"):
        return False
    failed = ticket.get("status") == "waiting" and (ticket.get("waiting_on") or {}).get("start") is True
    return ticket.get("status") == "review" or _question(ticket) is not None or failed


def _key_number(t: dict) -> int:
    try:
        return int(str(t.get("key") or "").rsplit("-", 1)[-1])
    except ValueError:
        return 0


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _step(ticket: dict) -> str:
    """The step the helper marked it works on now (orch check start), in one line; '' when none (ORCH-463)."""
    for c in ticket.get("checklist") or []:
        if isinstance(c, dict) and c.get("state") == "doing" and not c.get("done") and not c.get("wont_do"):
            return " ".join(str(c.get("text") or c.get("title") or "").split())[:200]
    return ""


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
        status, word = "needs-you", "Needs you"
    elif hs == "idle":
        status, word = "idle", "Idle"
    elif alive:
        status = "working"
        word = helper.get("word") if isinstance(helper.get("word"), str) and helper.get("word") else "Working"
    elif in_line:
        status, word = "in-line", "In line"
    else:
        status, word = "closed", "No session"
    if status == "working" and _question(ticket) is not None:
        # ORCH-1657: the ticket's open question is on the layer and in the need-you number at once, while the core
        # marks the helper "you" only on its next look at the screen (30-60 s later): the tile follows the question
        status, word = "needs-you", "Needs you"
    if status in ("idle", "closed") and ticket.get("status") == "review":
        # ORCH-674: a quiet session whose result waits for the person reads Check, as its ticket does everywhere else
        word = "Check"
    elif (
        status == "closed"
        and ticket.get("status") == "waiting"
        and (ticket.get("waiting_on") or {}).get("start") is True
    ):
        word = "Could not start"  # ORCH-1687: as Home's row says it
    elif status == "closed" and _question(ticket) is not None:
        word = "Needs you"  # ORCH-1687: listed in the Needs you band for its question, not "No session"
    # ORCH-790: a quiet or closed session whose ticket asks a question or waits for a result still needs the person;
    # the wall puts it in the Needs you band so the band and the "N need you" count agree.
    needs = status in ("idle", "closed") and _needs_person(ticket)
    waits = [
        {"kind": str(w.get("kind") or ""), "what": " ".join(str(w.get("what") or "").split())[:200]}
        for w in run.get("waiting_on") or []
        if isinstance(w, dict) and w.get("what")
    ]
    if alive and isinstance(run.get("hold"), str) and run["hold"]:
        waits.append({"kind": "hold", "what": run["hold"]})
    small = [
        {"what": _small_name(w), "seconds": _int(w.get("seconds"))}
        for w in run.get("waiting_on") or []
        if isinstance(w, dict) and w.get("subagent") is True
    ]
    last = run.get("last_activity") if isinstance(run.get("last_activity"), dict) else {}
    warmth = ticket.get("warmth") if isinstance(ticket.get("warmth"), dict) else {}
    return {
        "id": str(ticket.get("id")),
        "key": ticket.get("key") if isinstance(ticket.get("key"), str) else "",
        "title": " ".join(str(ticket.get("title") or "").split()) or "Untitled",
        "status": status,
        "word": word,
        "needs": needs,
        "detail": helper.get("detail") if alive and isinstance(helper.get("detail"), str) else "",
        "waiting_on": waits if alive else [],
        "step": _step(ticket) if alive else "",
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
        "kind": "",
        "parent": ticket.get("parent")
        if isinstance(ticket.get("parent"), str) and ticket.get("parent")
        else None,
        "small": small if alive else [],
    }


def _small_name(w: dict) -> str:
    """The plain name of a small helper from its waiting_on row (runwatch: label "helper: <what>")."""
    label = w.get("label") if isinstance(w.get("label"), str) else ""
    name = label[len("helper: ") :] if label.startswith("helper: ") else label or str(w.get("what") or "")
    return " ".join(name.split())[:120] or "Small helper"


GROUP_DEPTH = 8  # parent chains longer than this are cut (and a loop in them is never followed)
_OPEN = ("done", "dropped", "superseded")


def _top(tid: str, by_id: dict) -> str:
    """The top ticket of a parent chain; in a loop the smallest id of the loop, so every member finds the same one."""
    chain = [tid]
    for _ in range(GROUP_DEPTH):
        p = by_id.get(chain[-1], {}).get("parent")
        if not isinstance(p, str) or p not in by_id:
            break
        if p in chain:
            return min(chain[chain.index(p) :])
        chain.append(p)
    return chain[-1]


def _members(top: dict, kids: dict[str, list[dict]], by_sess: dict[str, dict]) -> list[dict]:
    """The top ticket, then its sub-tickets depth first (by key number): open ones and any with a session."""
    out: list[dict] = []
    stack: list[tuple[dict, int]] = [(top, 0)]
    seen: set[str] = set()
    while stack:
        t, depth = stack.pop()
        tid = t["id"]
        if tid in seen or depth > GROUP_DEPTH:
            continue
        seen.add(tid)
        s = by_sess.get(tid)
        if depth == 0 or s or t.get("status") not in _OPEN:
            out.append(
                {
                    "id": tid,
                    "key": t.get("key") if isinstance(t.get("key"), str) else "",
                    "title": " ".join(str(t.get("title") or "").split()) or "Untitled",
                    "depth": depth,
                    "main": depth == 0,
                    "status": s["status"] if s else "closed",
                    "word": s["word"] if s else "No session",
                    "small": list(s.get("small") or []) if s else [],
                }
            )
        stack.extend((k, depth + 1) for k in sorted(kids.get(tid, []), key=_key_number, reverse=True))
    return out


def groups(state: dict, sessions: list[dict]) -> list[dict]:
    """The epics and factory orders with sessions in their tree (see the module text), in the sessions' order of
    their first member."""
    tickets = [t for t in state.get("tickets") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)]
    by_id = {t["id"]: t for t in tickets}
    kids: dict[str, list[dict]] = {}
    for t in tickets:
        p = t.get("parent")
        if isinstance(p, str) and p in by_id and p != t["id"]:
            kids.setdefault(p, []).append(t)
    by_sess = {s["id"]: s for s in sessions if not s.get("kind")}
    tops: list[str] = []
    for s in sessions:
        if s.get("kind") or s["id"] not in by_id:
            continue
        top = _top(s["id"], by_id)
        if top in kids and top not in tops:
            tops.append(top)
    out = []
    for top in tops:
        members = _members(by_id[top], kids, by_sess)
        with_session = [m for m in members if m["status"] != "closed"]
        if len(with_session) < 2 and not any(m["small"] for m in members):
            continue
        t = by_id[top]
        fac = (t.get("ext") or {}).get("factory") if isinstance(t.get("ext"), dict) else None
        out.append(
            {
                "id": top,
                "key": t.get("key") if isinstance(t.get("key"), str) else "",
                "title": " ".join(str(t.get("title") or "").split()) or "Untitled",
                "kind": "factory" if isinstance(fac, dict) and fac.get("role") == "order" else "epic",
                "members": members,
            }
        )
    return out


def no_ticket(x: dict, run: dict | None, tool_of) -> dict | None:
    """One open session without a ticket (state["sessions"], data.shape_sessions), or None when it is closed."""
    if not (isinstance(x, dict) and isinstance(x.get("id"), str) and x.get("open") is True):
        return None
    kind = x.get("kind") if x.get("kind") in ("empty", "chat", "terminal", "manager") else None
    if not kind:
        return None
    t = {"id": x["id"], "key": "", "title": x.get("title") or "Session"}
    if kind == "terminal":
        s = session(t, None, False, None)
        s.update(status="idle", word="Open")
        if x.get("signin") is True:  # a sign-in card's window is in front (ORCH-865): the pane says Sign-in
            s["signin"] = True
    else:
        claim = (run or {}).get("claim") if isinstance((run or {}).get("claim"), dict) else {}
        s = session(t, run, False, tool_of(claim.get("agent")))
        if s["status"] == "closed":
            return None
        # A session nobody asked anything of (Manager, Chat, Empty helper) that sits at its prompt is Idle, never
        # Stuck in the working colour: Stuck is for a ticket's helper that stopped (idle 20 min, or no update).
        if s["word"] == "Stuck" and (run or {}).get("state") != "maybe-stale":
            s.update(status="idle", word="Idle")
    s["kind"] = kind
    return s


def _ever_ran(run: dict | None) -> bool:
    """A helper has worked on this ticket: a run claim is on record, or an agent wrote to it."""
    run = run if isinstance(run, dict) else {}
    return isinstance(run.get("claim"), dict) or isinstance(run.get("last_activity"), dict)


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
        if s["status"] == "closed" and not _ever_ran(run):
            continue  # ORCH-701: a ticket no helper ever worked on has no session: no tile, no kept conversation
        out.append(s)
        if s["mode"] == "live":
            live.append(tid)
    for x in state.get("sessions") or []:  # sessions without a ticket (ORCH-364): their tickets are hidden
        s = no_ticket(
            x, runs.get(x.get("id")) if isinstance(x, dict) else None, lambda a: tool_label(root, a)
        )
        if s and all(o["id"] != s["id"] for o in out):
            out.append(s)
            if s["mode"] == "live":
                live.append(s["id"])
    shots = tails(root, orch_bin, live, n)
    for s in out:
        s["lines"] = shots.get(s["id"], [])
    rank = {k: i for i, k in enumerate(ORDER)}
    keys = {str(t.get("id")): _key_number(t) for t in state.get("tickets") or [] if isinstance(t, dict)}
    out.sort(key=lambda s: (rank[s["status"]], keys.get(s["id"], 0)))
    return out


def answer(root: Path, orch_bin: str | None, state: dict, age: float, lines: int = LINES) -> dict:
    n = max(1, min(int(lines), LINES_MAX))
    sessions = sessionprefs.apply(root, build(root, orch_bin, state, n))
    return {
        "sessions": sessions,
        "groups": groups(state, sessions),
        "lines": n,
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_ms": int(age * 1000),
    }
