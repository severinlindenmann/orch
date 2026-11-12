"""The "Live now" cards of the start screen: one plain card per ticket whose agent is working right now.

A card is shaped from the same view the ticket page uses (`Tracker.view`), so the numbers, the steps and the
question always agree with the ticket page. Nothing here reads a file or starts anything. Text is already
redacted by events.make(); ids appear only where the page needs them for a link or an answer.
"""

from __future__ import annotations

from . import areas

MAX_CARDS = 8
MAX_STEPS = 3
MAX_OPTIONS = 4
ACTIVE = ("active", "waiting")  # ticket statuses a running agent can have


def _one_line(text, limit: int = 200) -> str:
    return " ".join(str(text or "").split())[:limit]


def _steps(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in reversed(events):
        kind, text = e.get("kind"), _one_line(e.get("text"))
        if not text:
            continue
        data = e.get("data") or {}
        if kind == "tool.start":
            row = {"kind": "step", "text": text, "ok": True}
        elif kind == "tool.end":
            row = {"kind": "step", "text": text, "ok": data.get("ok") is not False}
        elif kind == "task.done":
            row = {"kind": "done", "text": "Task done: " + text, "ok": True}
        elif kind == "ask":
            row = {"kind": "ask", "text": "Asked you a question", "ok": True}
        elif kind in ("helper.start", "helper.end"):
            row = {
                "kind": "helper",
                "text": ("Helper finished: " if kind == "helper.end" else "Helper: ") + text,
                "ok": True,
            }
        else:
            continue
        out.append({"at": e.get("at"), **row})
        if len(out) == MAX_STEPS:
            break
    return out


def question_digest(q: dict) -> str | None:
    """The core's digest of a question as shown (an answer sends it back; the person's proof binds it).
    Without the core: None, and an answer without a digest is refused (fail closed)."""
    try:
        from orch.tickets import question_digest as digest
    except ImportError:
        return None
    return digest(q)


def _question(ticket: dict) -> dict | None:
    for q in ticket.get("questions") or []:
        if isinstance(q, dict) and q.get("answer") is None and isinstance(q.get("id"), str):
            opts = [_one_line(o, 120) for o in (q.get("options") or []) if isinstance(o, str) and o.strip()]
            rec = _one_line(q.get("recommended"), 120) if isinstance(q.get("recommended"), str) else None
            return {
                "id": q["id"], "text": _one_line(q.get("text"), 400), "options": opts[:MAX_OPTIONS],
                "recommended": rec if rec in opts else None, "digest": question_digest(q),
            }  # fmt: skip
    return None


def _task_line(board: dict, checklist: list[dict]) -> str:
    """'Task 2 of 3: Put the days in order' from the task the agent is on; empty when it is on none."""
    total = len(checklist)
    for n, c in enumerate(checklist, 1):
        if not (c.get("done") or c.get("wont_do")) and c.get("state") == "doing":
            return f"Task {n} of {total}: {_one_line(c.get('text'), 120)}"
    return ""


def card(v: dict) -> dict:
    t, run, board = v["ticket"], v["run"], v["board"]
    checklist = [c for c in t.get("checklist") or [] if isinstance(c, dict)]
    steps = _steps(v.get("events") or [])
    question = _question(t)
    now = _one_line(board.get("step")) or (steps[0]["text"] if steps else "") or "Getting started"
    return {
        "ticket": t["id"], "key": t.get("key"), "title": _one_line(t.get("title")),
        "agent": _one_line(run.get("label") or "Agent", 60),
        "minutes": int(run.get("worked") or 0) // 60,
        "now": now, "why": _task_line(board, checklist),
        "progress": {"done": int(v.get("done") or 0), "total": int(v.get("total") or 0)},
        "steps": steps, "question": question, "working": v.get("state") == "working",
        "files": [{"path": f["path"], "how": f["how"], "at": f.get("at")} for f in board.get("files") or []][:50],
    }  # fmt: skip


def same_file(cards: list[dict]) -> list[dict]:
    """Files two or more running tickets have touched, when at least one of them changed it. Display only."""
    by: dict[str, list[dict]] = {}
    for c in cards:
        for f in c.get("files") or []:
            by.setdefault(f["path"], []).append(
                {
                    "ticket": c["ticket"],
                    "key": c.get("key") or c["title"],
                    "title": c["title"],
                    "agent": c["agent"],
                    "how": f["how"],
                    "at": f.get("at"),
                }
            )
    return [
        {"path": p, "tickets": t[:4]}
        for p, t in sorted(by.items())
        if len(t) >= 2 and any(x["how"] == "changed" for x in t)
    ][:5]


def cards(tracker) -> list[dict]:
    """Cards for every ticket whose agent runs now, those that wait for you first."""
    out: list[dict] = []
    for row in tracker.tickets_list():
        if row["status"] not in ACTIVE:
            continue
        v = tracker.view(row["id"])
        if v and v["run"]["running"]:
            out.append(card(v))
        if len(out) == MAX_CARDS:
            break
    areas.label(tracker.root, out)
    return sorted(out, key=lambda c: c["question"] is None)
