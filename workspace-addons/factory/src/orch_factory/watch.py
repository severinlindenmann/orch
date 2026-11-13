"""The Factory watcher: wakes the manager run of an order when something needs it.

Wake reasons (all decided through authority/flow, never from the ext cache or raw rows):
  a) a person answered a question Factory asked and `next` has not consumed it yet;
  b) a crew sub-ticket of a started order became done or failed since the last pass;
  c) autopilot: a live grant covers an open stop the manager could decide (once per stop).
Agent answers never wake anything. A run is started only through `orch run start` and only when none is live.
State in .orch/addons/factory/watch.json: per order the crew statuses seen and the ids already woken for."""

from __future__ import annotations

import json
import sys
import time

from . import authority, autopilot, flow, orchcli
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


def _reasons(root, store, ticket, tickets, entry, granted, decided):
    """(why, [ids to remember], new crew statuses) for one order; nothing when it needs no wake."""
    d = flow.derive(root, store, ticket, tickets)
    woken = set(entry.get("woken", []))
    why, ids = [], []
    for e in d["pending"]:
        q = e["q"]
        if authority.human(q) and q["id"] not in woken:
            why.append(f"{authority.who(q).split(':', 1)[1]} answered {e['row']['kind'].split(':')[1]}")
            ids.append(q["id"])
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
        op = d["open"]
        if op and op["row"]["kind"] == "factory:stop" and f"stop:{op['q']['id']}" not in woken:
            options = list(op["q"].get("options") or [])
            if any(autopilot.allowed(op, o, granted, clock(), ticket["id"], decided) for o in options):
                why.append("autopilot may decide a stop")
                ids.append(f"stop:{op['q']['id']}")
    return why, ids, crew


def _role(ticket):
    ext = ticket.get("ext") if isinstance(ticket, dict) else None
    x = ext.get("factory") if isinstance(ext, dict) else None
    return x.get("role") if isinstance(x, dict) else None


def run_live(root, order):
    return bool(orchcli.call(root, "run", "status", order).get("running"))


def once(root):
    """One pass. Returns [{"order", "why"}] for the runs it started."""
    store = Store(root)
    tickets = orchcli.tickets(root)
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
                why, ids, crew = _reasons(root, store, t, tickets, entry, granted, decided)
                live = run_live(root, t["id"]) if why else False
            except Refused:
                continue  # a broken order or an unreachable core: next pass
            except Exception as error:  # noqa: BLE001 - a malformed ticket must not stop the other orders
                print(f"order skipped: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                continue
            if live and why:
                continue  # the live run reads the order itself; ask again when it ends (nothing saved)
            new = {"crew": crew, "woken": sorted(set(entry.get("woken", [])) | set(ids))}
            if new != entry:
                orders[t["id"]] = new
                changed = True
            if why:
                todo.append((t["id"], "; ".join(why), entry))
        if changed or todo:
            _save(store, orders)  # BEFORE any start: a crash never starts the same wake twice
    woke = []
    for order, why, old in todo:
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


def loop(root, sleep=time.sleep):
    while True:
        try:
            for w in once(root):
                print(f"woke {w['order']}: {w['why']}", flush=True)
        except Exception as error:  # noqa: BLE001 - nothing a pass meets may end the watcher
            print(
                f"pass failed: {type(error).__name__}: {' '.join(str(error).split())}",
                file=sys.stderr,
                flush=True,
            )
        sleep(INTERVAL)
