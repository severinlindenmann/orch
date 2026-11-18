"""The ONE source for every count and step a page shows (ORCH-476).

Every page counted on its own, so the same thing showed different numbers (4 vs 5 vs 6 "need you",
"Step 4 of 4" vs "Step 3 of 3", "4 working" vs "Running now (1)", "1 skipped" vs "won't do").
Every surface now reads these functions: Python directly, a page through the `counts` block its
server puts next to its data, the CLI through `orch counts --json`.

Pure functions over ticket dicts and run status dicts (`orch run status --json` per ticket);
nothing is stored.

- needs_you: one per open question plus one per ticket in Review, the same items the Review page shows as
  cards (review.stack); the hidden General conversation and finished tickets never count.
- progress / step: every task counts, a won't-do task too (it is finished, never "skipped"); the step is the
  task being done, else the first open one, "Step n of total".
- helper / working: the helper state of a LIVE run only (runwatch's one helper state); a ticket marked Working
  with no live process has no helper and is not working.
- stuck: the ticket rule (tickets.stuck_why) or a stuck helper, one reason.
"""

from __future__ import annotations

from datetime import datetime

OPEN_DONE = ("done", "dropped")
WONT_DO = "won't do"  # the one word for a task that will not be done (never "skipped")
HELPER_STATES = ("working", "starting", "you", "waiting", "idle", "stuck")
WORKING = ("working", "starting")  # what "N working" counts


def _tasks(ticket: dict) -> list[dict]:
    return [c for c in ticket.get("checklist") or [] if isinstance(c, dict)]


def progress(ticket: dict) -> dict:
    """{done, wont_do, doing, todo, finished, total}: done = finished with proof, wont_do = will not be done,
    finished = done + wont_do (the "3 of 4 tasks" of every page), doing = being worked on now."""
    tasks = _tasks(ticket)
    done = sum(1 for c in tasks if c.get("done") and not c.get("wont_do"))
    wont = sum(1 for c in tasks if c.get("wont_do"))
    doing = sum(1 for c in tasks if not c.get("done") and not c.get("wont_do") and c.get("state") == "doing")
    total = len(tasks)
    return {
        "done": done,
        "wont_do": wont,
        "doing": doing,
        "todo": total - done - wont - doing,
        "finished": done + wont,
        "total": total,
    }


def step(ticket: dict) -> dict | None:
    """{n, of}: the task being done, else the first open one, counted among ALL tasks (a won't-do one too, so
    "Step 4 of 4" sits beside "3 of 4 tasks"). None when no task is open or the ticket is finished."""
    if ticket.get("status") in OPEN_DONE:
        return None
    tasks = _tasks(ticket)
    open_ = [i for i, c in enumerate(tasks) if not c.get("done") and not c.get("wont_do")]
    at = next((i for i in open_ if tasks[i].get("state") == "doing"), open_[0] if open_ else None)
    return {"n": at + 1, "of": len(tasks)} if at is not None else None


def task_word(task: dict) -> str:
    """The one word of a task: Done, won't do, Working or To do."""
    if task.get("wont_do"):
        return WONT_DO
    if task.get("done"):
        return "Done"
    return "Working" if task.get("state") == "doing" else "To do"


def _counts(ticket: dict) -> bool:
    return isinstance(ticket.get("id"), str) and ticket.get("general") is not True


def needs_you_items(tickets: list[dict]) -> list[dict]:
    """[{ticket, question}] per open question, [{ticket, question: None}] per ticket in Review: exactly the
    Review page's cards (review.stack), in ticket order."""
    out = []
    for t in tickets:
        if not isinstance(t, dict) or not _counts(t):
            continue
        if t.get("status") not in OPEN_DONE:
            for q in t.get("questions") or []:
                if isinstance(q, dict) and q.get("answer") is None and isinstance(q.get("id"), str):
                    out.append({"ticket": t["id"], "question": q["id"]})
        if t.get("status") == "review":
            out.append({"ticket": t["id"], "question": None})
    return out


def needs_you(tickets: list[dict]) -> dict:
    """{count, questions, results, tickets, items}: the one "N things need you" number, its two parts and the
    items it counts (a page that hides a row for a moment, an answer being sent, takes that item off)."""
    items = needs_you_items(tickets)
    questions = sum(1 for i in items if i["question"])
    seen: list[str] = []
    for i in items:
        if i["ticket"] not in seen:
            seen.append(i["ticket"])
    return {
        "count": len(items),
        "questions": questions,
        "results": len(items) - questions,
        "tickets": seen,
        "items": items,
    }


def helper(run: dict | None) -> str | None:
    """The helper state key of a live run (orch run status "helper"), None when no process runs. A record with
    running false (or no record) never has a helper, whatever the ticket status says."""
    if not isinstance(run, dict):
        return None
    if run.get("running") is not True and run.get("state") != "maybe-stale":
        return None
    h = run.get("helper")
    if isinstance(h, dict) and h.get("state") in HELPER_STATES:
        return h["state"]
    return "stuck" if run.get("state") == "maybe-stale" else "working"


def stuck(ticket: dict, run: dict | None = None, now: datetime | None = None) -> str | None:
    """One reason: "helper" (its helper is stuck) or the ticket rule's "question" | "quiet" | "overdue"."""
    if not _counts(ticket) or ticket.get("status") in OPEN_DONE:
        return None
    if helper(run) == "stuck":
        return "helper"
    from orch import tickets as core

    try:
        return core.stuck_why(ticket, now)
    except (TypeError, ValueError, AttributeError):
        return None


def live_runs(root) -> dict:
    """{ticket id: {running, state, helper}} for every run this workspace knows (runwatch.list_runs)."""
    from orch import runwatch

    out: dict = {}
    for r in runwatch.list_runs(root):
        st = r.get("state")
        out.setdefault(r["ticket"], {"running": st == "alive", "state": st, "helper": r.get("helper")})
    return out


def now(root) -> dict:
    """summary over every ticket (as shown) and every live run of this workspace: `orch counts`."""
    from orch import history, tickets

    return summary(history.shown_json(root, tickets.list_all(root)), live_runs(root))


def summary(tickets: list[dict], runs: dict | None = None, now: datetime | None = None) -> dict:
    """Everything a page counts, from one pass: {needs_you, helpers: {state: n}, working, running, stuck,
    tickets: {id: {step, progress, helper, stuck}}}. runs: {ticket id: run status dict}."""
    runs = runs or {}
    per: dict[str, dict] = {}
    helpers = dict.fromkeys(HELPER_STATES, 0)
    stuck_ids: list[str] = []
    for t in tickets:
        if not isinstance(t, dict) or not _counts(t):
            continue
        run = runs.get(t["id"])
        h = helper(run)
        if h:
            helpers[h] += 1
        why = stuck(t, run, now)
        if why:
            stuck_ids.append(t["id"])
        per[t["id"]] = {"step": step(t), "progress": progress(t), "helper": h, "stuck": why}
    return {
        "needs_you": needs_you(tickets),
        "helpers": helpers,
        "working": sum(helpers[k] for k in WORKING),
        "running": sum(helpers.values()),  # every live helper process, whatever its state
        "stuck": len(stuck_ids),
        "stuck_tickets": stuck_ids,
        "tickets": per,
    }
