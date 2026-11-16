"""The Factory watcher: wakes the manager run of an order when something needs it.

Wake reasons (all decided through authority/flow, never from the ext cache or raw rows):
  a) a person answered a question Factory asked and `next` has not consumed it yet;
  b) a crew sub-ticket of a started order became done or failed since the last pass;
  c) autopilot: a live grant covers an open stop the manager could decide (once per stop);
  d) a task handed to another workspace was denied, failed or done there (once per task and reason, no timer).
When the only news is that a stage is done (the crew's last result is OK, or a person said Continue at its stop) and the
next stage is a plain stage of the plan the person accepted, Factory starts that stage's crew itself at once (#47): no
manager run, no new question. The manager is woken only when something does not fit the plan.
Agent answers never wake anything. A run is started only through `orch run start` and only when none is live.
State in .orch/addons/factory/watch.json: per order the crew statuses seen and the ids already woken for."""

from __future__ import annotations

import json
import sys
import time

from . import ask, authority, autopilot, flow, handover, orchcli
from .store import Refused, Store, clock

INTERVAL = 20
STATE = "watch.json"
FINISHED = ("done", "failed", "dropped")


def _load(store):
    try:
        data = json.loads(store.read(STATE))
    except (FileNotFoundError, ValueError, UnicodeError):
        return {}
    orders = data.get("orders") if isinstance(data, dict) else None
    return orders if isinstance(orders, dict) else {}


def _save(store, orders):
    store.write(STATE, json.dumps({"orders": orders}).encode())


def ready_stage(d):
    """The next stage Factory may start by itself, or None: a started run whose earlier stage is done, nothing open or
    being edited, and a fresh stage of the accepted plan (no crew ticket yet, every task has its crew agent, none is
    handed to another workspace)."""
    if d["phase"] != "started" or d["kind"] != "run" or d["shipped"] or d["finished"]:
        return None
    if d["open"] or d["edit"] or not d["stage"] or not any(x["state"] == "done" for x in d["line"]):
        return None
    mine = [t for t in d["tasks"].values() if t["stage"] == d["stage"]]
    handed = {h["task"] for h in d["proposal"].get("handovers", [])}
    if not mine or any(t["slug"] in d["crew"] or t["slug"] in handed or not t.get("agent") for t in mine):
        return None
    return d["stage"]


def _reasons(root, store, ticket, tickets, entry, granted, decided):
    """(why, [ids to remember], new crew statuses, stage) for one order; nothing when it needs no wake. `stage`: the next
    stage Factory starts itself, only when every reason just says a stage moved on (a crew task done, a person's answer
    at a stop) and `ready_stage` allows it."""
    d = flow.derive(root, store, ticket, tickets)
    states = {}
    if d["phase"] == "started" and d["kind"] == "run" and d.get("proposal", {}).get("handovers"):
        states, changed = handover.settle(root, store, d)
        if changed:  # a finished hand-over made its crew ticket done: rule (b) must see it
            d = flow.derive(root, store, ticket, orchcli.tickets(root))
    woken = set(entry.get("woken", []))
    why, ids, plain = [], [], True
    for e in d["pending"]:
        q = e["q"]
        if authority.human(q) and q["id"] not in woken:
            why.append(f"{authority.who(q).split(':', 1)[1]} answered {e['row']['kind'].split(':')[1]}")
            ids.append(q["id"])
            plain = plain and e["row"]["kind"] == "factory:stop"
    crew = {t["ext"]["factory"]["task"]: t.get("status") for t in d["crew"].values()}
    if d["phase"] == "started" and d["kind"] == "run" and not d["shipped"]:
        seen = entry.get("crew")
        for task, status in crew.items():
            if seen is None:
                # First sight of this order (watcher started late or restarted with no record): a crew task that
                # already ended with no stop open means the manager may be waiting for news nobody will send.
                # It is recorded below like any wake, so it never repeats.
                first = status in ("done", "failed") and not d["open"]
            else:
                first = status in FINISHED and seen.get(task) != status
            if first:
                why.append(f"crew task {task} is {status}")
                plain = plain and status == "done"
        for (
            task,
            state,
        ) in states.items():  # d) a hand-over was said no to, failed or came back done (core leaves the crew ticket in review for the person): once per task and reason
            if state in ("denied", "failed", "done") and f"handover:{task}:{state}" not in woken:
                why.append(f"handover task {task} is {state}")
                ids.append(f"handover:{task}:{state}")
                plain = False
        op = d["open"]
        if op and op["row"]["kind"] == "factory:stop" and f"stop:{op['q']['id']}" not in woken:
            options = list(op["q"].get("options") or [])
            if not ask.has_ask(tickets, ticket["id"], op["n"]) and any(
                autopilot.allowed(op, o, granted, clock(), ticket["id"], decided) for o in options
            ):
                why.append("autopilot may decide a stop")
                ids.append(f"stop:{op['q']['id']}")
                plain = False
    stage = ready_stage(d) if why and plain else None
    return why, ids, crew, stage


MEASURE_EVERY = 60  # seconds between two measurements of an order's active time


def _keep_budget(root, store, ticket, tickets, entry):
    """Keep the order's shown active time current while the crew works (the manager may be idle for a long while): the
    measured minutes go into the same cache `next` writes. Returns the time of this measurement (or the old one)."""
    seen = entry.get("measured")
    if isinstance(seen, (int, float)) and time.time() - seen < MEASURE_EVERY:
        return seen
    d = flow.derive(root, store, ticket, tickets)
    if d["phase"] != "started" or d["kind"] != "run" or d["shipped"]:
        return None
    flow._measure(root, d)
    if d.get("measured"):
        flow.refresh(root, store, ticket["id"], d)
    return time.time()


def _role(ticket):
    ext = ticket.get("ext") if isinstance(ticket, dict) else None
    x = ext.get("factory") if isinstance(ext, dict) else None
    return x.get("role") if isinstance(x, dict) else None


def run_live(root, order):
    return bool(orchcli.call(root, "run", "status", order).get("running"))


def once(root):
    """One pass. Returns [{"order", "why"}] for the runs it started, and [{"order", "why", "stage", "crew"}] for each next
    stage it started itself."""
    store = Store(root)
    tickets = orchcli.tickets(root)
    ask.resume(root, tickets)  # asks that waited for the relay go on
    todo = []
    with store.locked():
        orders = _load(store)
        granted = autopilot.grants(store, tickets)
        decided = [r for r in store.journal_read() if r["type"] == "decided"]
        changed = False
        for t in tickets:
            try:
                if _role(t) != "order":
                    continue
                entry = orders.get(t["id"], {})
                why, ids, crew, stage = _reasons(root, store, t, tickets, entry, granted, decided)
                measured = _keep_budget(root, store, t, tickets, entry)
                live = run_live(root, t["id"]) if why else False
            except Refused:
                continue  # a broken order or an unreachable core: next pass
            except Exception as error:  # noqa: BLE001 - a malformed ticket must not stop the other orders
                print(f"order skipped: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                continue
            if live and why:
                continue  # the live run reads the order itself; ask again when it ends (nothing saved)
            new = {"crew": crew, "woken": sorted(set(entry.get("woken", [])) | set(ids))}
            if measured is not None:
                new["measured"] = measured
            if new != entry:
                orders[t["id"]] = new
                changed = True
            if why:
                todo.append((t["id"], "; ".join(why), entry, stage))
        if changed or todo:
            _save(store, orders)  # BEFORE any start: a crash never starts the same wake twice
    woke = []
    for order, why, old, stage in todo:
        if stage is not None:
            done = start_stage(root, order, stage)
            if isinstance(done, dict):
                woke.append(done)
                continue
            why = f"{why}; Factory could not start the {stage} stage itself: {done}"
        try:
            orchcli.call(root, "run", "start", order, write=True)
        except Refused:
            with store.locked():  # the start did not happen: allow the next pass to try again
                orders = _load(store)
                orders[order] = old
                _save(store, orders)
            continue
        try:
            orchcli.call(root, "log", order, f"Factory woke the manager: {why}", write=True)
        except Refused:
            pass
        woke.append({"order": order, "why": why})
    return woke


def start_stage(root, order, stage):
    """Start the crew of `stage` as the accepted plan says, right after the stage before it is done (#47). Goes through
    the same `next` / `crew add` / `crew start` as the manager, so every check still holds. Returns the started stage
    ({"order", "why", "stage", "crew"}) or, when anything does not fit, the reason in plain words (the caller then wakes
    the manager as before)."""
    try:
        # takes in the person's answers and refreshes the order, as the manager's `next` would
        step = flow.next_step(root, order)
        if step.get("step") != "start-crew" or step.get("stage") != stage or step.get("comments"):
            return "the plan's next step is different now"
        crew = []
        for t in step["tasks"]:
            flow.crew_add(root, order, t["slug"])
            crew.append(flow.crew_start(root, order, t["slug"])["ticket"])
    except Refused as error:
        return str(error)
    titles = ", ".join(t["title"] for t in step["tasks"])
    why = f"started the {stage} stage as planned"
    try:
        orchcli.call(root, "log", order, f"Factory {why}: {titles}.", write=True)
    except Refused:
        pass
    return {"order": order, "why": why, "stage": stage, "crew": crew}


def loop(root, sleep=time.sleep):
    while True:
        try:
            for w in once(root):
                print(f"{'started' if 'stage' in w else 'woke'} {w['order']}: {w['why']}", flush=True)
        except Exception as error:  # noqa: BLE001 - nothing a pass meets may end the watcher
            print(
                f"pass failed: {type(error).__name__}: {' '.join(str(error).split())}",
                file=sys.stderr,
                flush=True,
            )
        sleep(INTERVAL)
