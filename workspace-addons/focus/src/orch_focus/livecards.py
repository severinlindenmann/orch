"""The "Live now" cards of the start screen: one plain card per ticket whose agent is working right now.

A card is shaped from the same view the ticket page uses (`Tracker.view`), so the numbers, the steps and the
question always agree with the ticket page. Nothing here reads a file or starts anything. Text is already
redacted by events.make(); ids appear only where the page needs them for a link or an answer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import areas

MAX_CARDS = 8
WORKERS = 6  # views read at the same time
MAX_STEPS = 3
MAX_OPTIONS = 4
ACTIVE = ("active", "waiting")  # ticket statuses a running agent can have
FINISHED = (
    "review",
    "done",
)  # a helper whose ticket is finished can still have its session open (it shows, with Stop)
WORDS = {
    "working": "Working",
    "starting": "Starting",
    "you": "Waits for you",
    "waiting": "Waiting",
    "idle": "Idle",
    "stuck": "Stuck",
}
ORDER = list(WORDS)  # working first, stuck last: the order of the Helpers list on Home


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
        if data.get("source") == "hook" and kind in ("tool.start", "tool.end"):
            row["unchecked"] = "before" if data.get("before") else "agent"
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


def helper(v: dict) -> dict:
    """The core's one helper state (orch run status "helper"); the same fallback words as the dashboard for an older core."""
    run, t = v["run"], v["ticket"]
    h = run.get("helper")
    if isinstance(h, dict) and h.get("state") in WORDS:
        return {"state": h["state"], "word": WORDS[h["state"]], "detail": _one_line(h.get("detail"))}
    key = {"needs": "you", "waiting": "idle"}.get(v.get("state"), "working")
    detail = (
        "Your answer"
        if key == "you"
        and any(q.get("answer") is None for q in t.get("questions") or [] if isinstance(q, dict))
        else ""
    )
    return {"state": key, "word": WORDS[key], "detail": detail}


def _step(checklist: list[dict]) -> dict | None:
    """{n, of}: the task being done, else the first open one (the same count as the dashboard's Helpers list)."""
    tasks = [c for c in checklist if not c.get("wont_do")]
    at = next((i for i, c in enumerate(tasks) if c.get("state") == "doing"), None)
    if at is None:
        at = next((i for i, c in enumerate(tasks) if not c.get("done")), None)
    return {"n": at + 1, "of": len(tasks)} if tasks and at is not None else None


def card(v: dict) -> dict:
    t, run, board = v["ticket"], v["run"], v["board"]
    checklist = [c for c in t.get("checklist") or [] if isinstance(c, dict)]
    steps = _steps(v.get("events") or [])
    question = _question(t)
    state = helper(v)
    now = _one_line(board.get("step")) or (steps[0]["text"] if steps else "") or state["detail"]
    age, idle = run.get("age_seconds"), run.get("idle_seconds")
    return {
        **state, "step": _step(checklist), "finished": t.get("status") in FINISHED,
        "age_minutes": age // 60 if isinstance(age, int) else None,
        "idle_minutes": idle // 60 if isinstance(idle, int) else None,
        "ticket": t["id"], "key": t.get("key"), "title": _one_line(t.get("title")),
        "agent": _one_line(run.get("label") or "Agent", 60),
        "minutes": int(run.get("worked") or 0) // 60,
        "now": now, "why": _task_line(board, checklist),
        "progress": {"done": int(v.get("done") or 0), "total": int(v.get("total") or 0)},
        "steps": steps, "notes": list(v.get("record_notes") or [])[:3],
        "question": question, "working": v.get("state") == "working",
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
    """Cards for every ticket whose agent runs now, in the Helpers list order (working first, stuck last).

    The views are read side by side (each asks `orch` about its ticket): one after the other took a few seconds
    with four helpers at work, and the start page waits for this answer before it shows its lists."""
    root = getattr(tracker, "root", None)  # a finished ticket counts only while its session file is there
    claims = root / ".orch" / "run" / "tickets" if root is not None else None
    ids = [
        row["id"]
        for row in tracker.tickets_list()
        if row["status"] in ACTIVE
        or (claims is not None and row["status"] in FINISHED and (claims / f"{row['id']}.json").exists())
    ]
    if len(ids) > 1:
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(ids))) as pool:
            views = list(pool.map(tracker.view, ids))
    else:
        views = [tracker.view(t) for t in ids]
    out = [card(v) for v in views if v and v["run"]["running"]][:MAX_CARDS]
    areas.label(tracker.root, out)
    return sorted(out, key=lambda c: ORDER.index(c["state"]))
