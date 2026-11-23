"""The ONE source for every count and step a page shows (ORCH-476).

Every page counted on its own, so the same thing showed different numbers (4 vs 5 vs 6 "need you",
"Step 4 of 4" vs "Step 3 of 3", "4 working" vs "Running now (1)", "1 skipped" vs "won't do").
Every surface now reads these functions: Python directly, a page through the `counts` block its
server puts next to its data, the CLI through `orch counts --json`.

Pure functions over ticket dicts and run status dicts (`orch run status --json` per ticket);
nothing is stored.

- needs_you: one per open question plus one per ticket in Review, the same items the Review page shows as
  cards (review.stack), plus one per ticket whose helper could not start (ORCH-1687: Home lists it with Try
  again, so the number counts it too); the hidden General conversation and finished tickets never count.
  ORCH-1741: a ticket in Review whose pull request the merge queue (or a working helper) still holds is not
  counted (its id is listed under "queue"), and a ticket's Check card gives way to its other card (an open
  question, a pull request to merge), so one ticket never shows two cards (`quiet`).
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
HELPER_STATES = ("working", "starting", "you", "waiting", "idle", "stuck", "limit")
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


def quiet(root, tickets: list[dict]) -> dict:
    """ORCH-1741: {"queue": [ids], "folded": [ids]}: the tickets in Review whose Check card does not show.
    queue = a linked pull request is open and waits or runs in the merge queue, or a helper is at work on it
    (the queue woke it to repair the pull request); it comes back once the queue gives up on it. folded = the
    ticket has another card already: an open question (the Check card follows once it is answered) or the
    "passed its checks but was not merged" row. Never raises: what cannot be read shows its card."""
    from orch import stuck
    from orch import tickets as core

    out: dict = {"queue": [], "folded": []}
    try:
        ready = stuck.unmerged_ids(root, tickets)
    except Exception:  # noqa: BLE001 - no cache, no row: the Check card shows
        ready = set()
    for t in tickets:
        if not isinstance(t, dict) or not _counts(t) or t.get("status") != "review":
            continue
        try:
            pulls = stuck.open_pulls(t)  # every open one in the queue: one left out still needs the person
            held = bool(pulls) and (
                all(core.in_merge_queue(root, [u]) for u in pulls) or stuck.helper_busy(root, t)
            )
        except Exception:  # noqa: BLE001 - a broken run record or ref: the Check card shows
            held = False
        if held:
            out["queue"].append(t["id"])
        elif t["id"] in ready or core._open_questions(t):
            out["folded"].append(t["id"])
    return out


def needs_you_items(tickets: list[dict], hidden: dict | None = None) -> list[dict]:
    """[{ticket, question}] per open question, [{ticket, question: None}] per ticket in Review (the Review
    page's cards, review.stack) and [{ticket, question: None, start: True}] per failed start, in ticket
    order. hidden: `quiet` (the Check cards not shown)."""
    skip = set((hidden or {}).get("queue") or ()) | set((hidden or {}).get("folded") or ())
    out = []
    for t in tickets:
        if not isinstance(t, dict) or not _counts(t):
            continue
        asked = 0
        if t.get("status") not in OPEN_DONE:
            for q in t.get("questions") or []:
                if isinstance(q, dict) and q.get("answer") is None and isinstance(q.get("id"), str):
                    out.append({"ticket": t["id"], "question": q["id"]})
                    asked += 1
        if t.get("status") == "review" and t["id"] not in skip:
            out.append({"ticket": t["id"], "question": None})
        elif failed_start(t) and not asked:  # its question is the row then, as on Home
            out.append({"ticket": t["id"], "question": None, "start": True})
    return out


def failed_start(ticket: dict) -> bool:
    """The ticket waits because its helper could not start (tickets.wait_for_start)."""
    w = ticket.get("waiting_on")
    return ticket.get("status") == "waiting" and isinstance(w, dict) and w.get("start") is True


def needs_you(tickets: list[dict], hidden: dict | None = None) -> dict:
    """{count, questions, results, failed, tickets, items}: the one "N things need you" number, its parts
    and the items it counts (a page that hides a row for a moment, an answer being sent, takes that item
    off)."""
    items = needs_you_items(tickets, hidden)
    questions = sum(1 for i in items if i["question"])
    failed = sum(1 for i in items if i.get("start"))
    seen: list[str] = []
    for i in items:
        if i["ticket"] not in seen:
            seen.append(i["ticket"])
    return {
        "count": len(items),
        "questions": questions,
        "results": len(items) - questions - failed,
        "failed": failed,
        "tickets": seen,
        "items": items,
        "queue": list((hidden or {}).get("queue") or []),  # ORCH-1741: in the merge queue, not waiting on you
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
    if not _counts(ticket) or ticket.get("status") in (*OPEN_DONE, "review"):
        return None  # a ticket in Review waits for the person's check, never stuck (as tickets.stuck_why)
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

    shown = history.shown_json(root, tickets.list_all(root))
    return summary(shown, live_runs(root), hidden=quiet(root, shown))


def summary(
    tickets: list[dict], runs: dict | None = None, now: datetime | None = None, hidden: dict | None = None
) -> dict:
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
        if h in ("idle", "stuck") and t.get("status") == "review":
            h = None  # a left-over session of a ticket in Review: its "Check result" row (ORCH-407)
        if h:
            helpers[h] += 1
        why = stuck(t, run, now)
        if why:
            stuck_ids.append(t["id"])
        per[t["id"]] = {"step": step(t), "progress": progress(t), "helper": h, "stuck": why}
    return {
        "needs_you": needs_you(tickets, hidden),
        "helpers": helpers,
        "working": sum(helpers[k] for k in WORKING),
        "running": sum(helpers.values()),  # every live helper process, whatever its state
        "stuck": len(stuck_ids),
        "stuck_tickets": stuck_ids,
        "tickets": per,
    }
