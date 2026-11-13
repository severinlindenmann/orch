"""The run: next step, crew, changes, tiny changes, stops, ship. Everything is derived from authority again each call."""

import json
import re
from datetime import datetime

from . import authority, autopilot, commands, orchcli
from .render import clean
from .store import Refused, Store, clock, digest, validate

TINY_COUNT, TINY_MINUTES = 3, 30


def parse(data, definition):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise Refused(f"The {definition} must be valid JSON.", "invalid") from None
    validate(value, definition)
    return value


def freeze_ask(root, store, ticket, kind, data, value, ext=None):
    """Freeze the file (same bytes reuse their version), journal, ext, ask, journal. Safe to repeat."""
    folder, prefix, _ = authority.FOLDERS[kind]
    order, h = ticket["id"], digest(data)
    rows = store.journal_read()
    questions = {q["id"]: q for q in ticket.get("questions", [])}
    n = None
    base = store.path(f"{folder}/{order}")
    if base.exists():
        for p in sorted(base.iterdir()):
            m = re.fullmatch(rf"{prefix}([1-9][0-9]*)\.json", p.name)
            if not m or digest(store.read(f"{folder}/{order}/{p.name}")) != h:
                continue
            asked = [
                r
                for r in rows
                if r["type"] == "asked"
                and r["order"] == order
                and r.get("file") == f"{folder}/{order}/{p.name}"
            ]
            # An identical version is reused only while its question is still unanswered (or never asked).
            if all(questions.get(r["q"], {}).get("answer") is None for r in asked):
                n = int(m[1])
    if n is None:
        n = store.next_version(folder, order, prefix, "json")
    path = f"{folder}/{order}/{prefix}{n}.json"
    text, options, action = authority.expected(order, kind, path, h, value)
    store.write(path, data, frozen=True)
    entries = authority.entries(store, ticket)
    recorded = next(
        (r for r in rows if r["type"] == "asked" and r["order"] == order and r.get("file") == path), None
    )
    if recorded and any(e["q"]["id"] == recorded["q"] for e in entries):
        return {"order": order, "n": n, "question": recorded["q"], "file": path, "hash": h}
    if kind == "factory:autopilot":
        if not any(r["type"] == "proposed" and r["order"] == order and r.get("file") == path for r in rows):
            store.journal_append({"type": "proposed", "order": order, "file": path, "hash": h})
        for e in entries:
            if e["row"]["kind"] == kind and e["q"].get("action") != action and not authority.human(e["q"]):
                store.journal_append({"type": "superseded", "order": order, "q": e["q"]["id"], "kind": kind})
    if kind in ("factory:stop", "factory:change"):
        # A question only a non-person answered is burned (core takes no second answer): replace it.
        for e in entries:
            same = e["row"]["kind"] == kind and (
                kind == "factory:change" or e["data"]["stage"] == value["stage"]
            )
            q = e["q"]
            if same and q.get("answer") is not None and not authority.human(q):
                store.journal_append({"type": "superseded", "order": order, "q": q["id"], "kind": kind})
    if ext:
        if kind == "factory:autopilot":
            ext = {**ext, "proposal": {"n": n, "hash": h}}
        orchcli.set_ext(root, ticket, **ext)
    q = orchcli.call(
        root,
        "ask",
        order,
        text,
        "--kind",
        kind,
        *[x for o in options for x in ("--option", o)],
        "--action",
        json.dumps(action),
        write=True,
    )
    if q.get("kind") != kind or q.get("action") != action:
        raise Refused("Orch returned a question for a different file.", "conflict")
    store.journal_append(
        {"type": "asked", **{k: action[k] for k in ("order", "file", "hash")}, "q": q["id"], "kind": kind}
    )
    return {"order": order, "n": n, "question": q["id"], "file": path, "hash": h}


# ---- derivation -------------------------------------------------------------------------------------------


def derive(root, store, ticket, tickets=None):
    tickets = orchcli.tickets(root) if tickets is None else tickets
    tid = ticket["id"]
    journal = store.journal_read()  # once per derive; passed down
    ents = authority.entries(store, ticket, journal)
    rows = [r for r in journal if r["order"] == tid]
    consumed = {r.get("q") for r in rows if r["type"] == "consumed"}
    decided = {}
    for r in rows:
        if r["type"] == "decided":
            decided.setdefault(r["q"], r)  # the first row is the decision; later ones change nothing
    # every decided row in journal order, with the rows that precede it (max_orders counts those)
    all_decided = [r for r in journal if r["type"] == "decided"] if decided else []
    before_of = {id(r): all_decided[:i] for i, r in enumerate(all_decided)}
    granted = autopilot.grants(store, tickets, journal) if decided else []
    now = clock()

    def decided_ok(e, r):
        """A decided row counts only for the moment it was written: a grant covering that moment, the core's
        own log line after the grant began, and max_orders in journal order."""
        try:
            when = datetime.fromisoformat(r["at"])
        except (KeyError, ValueError):
            return False
        if when > now or e["row"]["kind"] != "factory:stop" or r.get("by") != "agent:factory":
            return False
        before = before_of.get(id(r), [])
        try:
            live = autopilot.check(e, r.get("answer"), granted, when, tid, before)
        except Refused:
            return False
        line = f"Decided by agent:factory · {r.get('why', '')}"
        for h in ticket.get("history", []):
            if h.get("text") != line:
                continue
            try:
                logged = datetime.fromisoformat(h["at"])
            except (KeyError, ValueError, TypeError):
                continue
            if any(logged >= g["from"] for g in live):
                return True
        return False

    def compute(e):
        q = e["q"]
        if authority.human(q):
            return q["answer"], q["answered_by"]
        r = decided.get(q["id"])
        if r and q.get("answer") is None and decided_ok(e, r):
            return r["answer"], "agent:factory"
        return None

    lead = [e for e in ents if e["row"]["kind"] in ("factory:start", "factory:autopilot")]
    answered = [e for e in lead if authority.human(e["q"])]
    start = next((e for e in answered if e["q"]["answer"] == "Start"), None)
    if start:
        phase = "started"
    elif lead and authority.human(lead[-1]["q"]):  # the newest proposal decides; an older Edit is history
        phase = {"Edit": "edit", "Not now": "parked"}.get(lead[-1]["q"]["answer"], "wait")
    else:
        phase = "wait"
    d = {
        "tid": tid,
        "ents": ents,
        "rows": rows,
        "kind": authority.order_kind(ents) or "run",
        "phase": phase,
        "lead": answered[-1] if answered else (lead[-1] if lead else None),
        "start": start,
        "ignored": [e for e in ents if e["q"].get("answer") is not None and not authority.human(e["q"])],
        "pending": [],
        "open": None,
        "decided_ok": set(),
        "shipped": False,
        "finished": False,
        "stage": None,
        "line": [],
        "tasks": {},
        "crew": {},
        "cap": 0,
        "used": ticket.get("ext", {}).get("factory", {}).get("budget", {}).get("active_min_used", 0),
        "edit": None,
        "last_answer": None,
        "last_stop": None,
    }
    effective_of = {e["q"]["id"]: compute(e) for e in ents}  # each entry evaluated once

    def effective(e):
        return effective_of[e["q"]["id"]]

    d["decided_ok"] = {qid for qid, eff in effective_of.items() if eff and eff[1] == "agent:factory"}
    d["pending"] = [e for e in ents if effective_of[e["q"]["id"]] and e["q"]["id"] not in consumed]
    d["effective"] = effective
    if phase != "started" or d["kind"] == "autopilot":
        return d
    p = start["data"]  # parsed from the bytes whose hash entries() checked; never read the file again
    accepted = [
        e
        for e in ents
        if e["row"]["kind"] == "factory:change" and authority.human(e["q"]) and e["q"]["answer"] == "Accept"
    ]
    tasks = {t["slug"]: dict(t) for t in p["tasks"]}
    cap = p["budget"]["active_min_cap"]
    for e in accepted:
        cap += e["data"]["adds_min"]
        for t in e["data"].get("adds_tasks", []):
            tasks.setdefault(t["slug"], dict(t))
    d.update(proposal=p, tasks=tasks, cap=cap)
    agents = {c["role"]: c["agent"] for c in p["crew"]}
    for t in tasks.values():
        t["agent"] = agents.get(t["role"])
    crew = {}
    for t in tickets:
        x = t.get("ext", {}).get("factory", {})
        if (
            x.get("role") == "crew"
            and x.get("order") == tid
            and t.get("parent") == tid
            and x.get("task") in tasks
        ):
            crew[x["task"]] = t
    d["crew"] = crew
    d["open"] = next(
        (
            e
            for e in reversed(ents)
            if e["row"]["kind"] in ("factory:change", "factory:stop")
            and effective(e) is None
            and e["q"].get("answer") is None  # an agent-answered question is burned, not open
        ),
        None,
    )
    changes = sorted((e for e in ents if e["row"]["kind"] == "factory:change"), key=lambda e: e["n"])
    if changes and authority.human(changes[-1]["q"]) and changes[-1]["q"]["answer"] == "Edit":
        d["edit"] = changes[-1]  # stays until the manager proposes a new change
    shipped_row = any(r["type"] == "shipped" for r in rows)
    line, current = [], None
    for st in p["line"]:
        name = st["stage"]
        if current is not None:
            line.append({"stage": name, "stop": st["stop"], "state": "todo"})
            continue
        stops = sorted(
            (e for e in ents if e["row"]["kind"] == "factory:stop" and e["data"]["stage"] == name),
            key=lambda e: e["n"],
        )
        last = stops[-1] if stops else None
        answer = effective(last) if last else None
        mine = [t for t in tasks.values() if t["stage"] == name]
        done_tasks = all(crew.get(t["slug"], {}).get("status") == "done" for t in mine)
        item = {"stage": name, "stop": st["stop"], "state": "todo"}
        if answer and answer[0] == ("Ship it" if name == "ship" else "Continue"):
            item.update(state="done", by=answer[1])
        elif not st["stop"] and done_tasks:
            item["state"] = "done"
        else:
            current = name
            d["last_stop"], d["last_answer"] = last, answer
            item["state"] = "waiting" if d["open"] and d["open"]["data"].get("stage") == name else "doing"
        line.append(item)
    d["line"], d["stage"] = line, current
    d["finished"] = current is None
    last_ship = max(
        (e for e in ents if e["row"]["kind"] == "factory:stop" and e["data"]["stage"] == "ship"),
        key=lambda e: e["n"],
        default=None,
    )
    ship_answer = effective(last_ship) if last_ship else None
    d["ship_ok"] = bool(ship_answer and ship_answer[0] == "Ship it" and ship_answer[1].startswith("human:"))
    d["ship_by"] = ship_answer[1] if d["ship_ok"] else None
    d["shipped"] = d["finished"] and shipped_row
    return d


def refresh(root, store, order, d):
    """Rewrite the ext cache from the derived state (it is only a cache for the dashboard)."""
    for _ in range(2):
        ticket = commands.order_ticket(root, order)
        ext = ticket["ext"]["factory"]
        want = {}
        if d["kind"] == "autopilot":
            grants_ = autopilot.grants_of(store, ticket)
            if grants_:
                last = max(grants_, key=lambda g: g["until"])
                want = {
                    "stage": "running" if clock() < last["until"] else "cancelled",
                    "grant_until": last["until"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
        elif d["phase"] == "started":
            rows = d["rows"]
            tiny = [r for r in rows if r["type"] == "tiny-change"]
            want = {
                "stage": "shipped" if d["shipped"] else "waiting" if d["open"] else "running",
                "line": d["line"],
                "crew": [t["id"] for t in d["crew"].values()],
                "budget": {**ext.get("budget", {}), "active_min_cap": d["cap"]},
                "tiny": {"count": len(tiny), "minutes": sum(_minutes(r) for r in tiny)},
            }
        if all(ext.get(k) == v for k, v in want.items()):
            return
        try:
            orchcli.set_ext(root, ticket, **want)
            return
        except Refused as error:
            if error.code != "conflict":
                raise


def _minutes(row):
    m = re.match(r"(\d+) min: ", row.get("why", ""))
    return int(m[1]) if m else 0


# ---- next ---------------------------------------------------------------------------------------------------


def _log_ignored(root, store, order, d):
    ticket = commands.order_ticket(root, order)
    for e in d["ignored"]:
        text = f"Factory ignored the agent answer to {e['q']['id']}; a person must answer."
        if e["row"]["kind"] == "factory:start":
            text = f"Factory ignored the agent answer to {e['q']['id']}; a person must press Start."
        if not any(h.get("text") == text for h in ticket.get("history", [])):
            orchcli.call(root, "log", order, text, write=True)
            ticket = commands.order_ticket(root, order)


def _step(d):
    base = {"order": d["tid"]}
    if d["kind"] == "autopilot":
        if d["phase"] != "started":
            return {**base, "step": {"edit": "edit", "parked": "parked"}.get(d["phase"], "wait")}
        return {**base, "step": "resume" if d.get("grant_valid") else "done"}
    if d["phase"] != "started":
        step = {"edit": "edit", "parked": "parked"}.get(d["phase"], "wait")
        out = {**base, "step": step}
        if step == "edit" and d["lead"]:
            out["file"] = d["lead"]["row"]["file"]
        return out
    budget = {"used": d["used"], "cap": d["cap"], "warn": d["cap"] > 0 and d["used"] * 5 >= d["cap"] * 4}
    if d["shipped"]:
        return {**base, "step": "done"}
    if d["open"]:
        return {**base, "step": "wait", "waiting_for": d["open"]["row"]["kind"].split(":")[1]}
    if d["edit"]:
        return {**base, "step": "edit", "file": d["edit"]["row"]["file"]}
    if d["finished"] and d["ship_ok"]:
        ship = d["proposal"]["ship"]
        return {**base, "step": "ship", "does": ship["does"], "undo": ship["undo"]}
    stage = d["stage"]
    sent_back = d["last_answer"] is not None and d["last_answer"][0] == "Send back"
    comments = None
    if sent_back:
        asked = d["last_stop"]["q"].get("comment")
        comments = (
            [clean(asked, 400)]
            if isinstance(asked, str) and clean(asked, 400)
            else [i["title"] for i in d["last_stop"]["data"]["items"]]
        )
    todo = [
        t
        for t in d["tasks"].values()
        if t["stage"] == stage and d["crew"].get(t["slug"], {}).get("status") != "done"
    ]
    if sent_back and not todo:
        return {**base, "step": "work", "stage": stage, "comments": comments}
    if todo:
        return {
            **base,
            **({"comments": comments} if sent_back else {}),
            "step": "start-crew",
            "stage": stage,
            "budget": budget,
            "tasks": [
                {
                    "slug": t["slug"],
                    "title": t["title"],
                    "role": t["role"],
                    "agent": t["agent"],
                    "ticket": d["crew"].get(t["slug"], {}).get("id"),
                }
                for t in todo
            ],
        }
    return {**base, "step": "stop", "stage": stage, "ship": stage == "ship", "budget": budget}


def next_step(root, order):
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        order = ticket["id"]
        tickets = orchcli.tickets(root)
        d = derive(root, store, ticket, tickets)
        _log_ignored(root, store, order, d)
        for e in d["pending"]:
            kind, q = e["row"]["kind"], e["q"]
            answer, by = d["effective"](e)
            store.journal_append(
                {"type": "consumed", "order": order, "q": q["id"], "kind": kind, "answer": answer, "by": by}
            )
            if kind == "factory:start" and answer == "Start":
                store.journal_append({"type": "started", "order": order, "q": q["id"], "by": by})
            elif kind == "factory:autopilot" and answer == "Start":
                g = next((x for x in autopilot.grants_of(store, ticket) if x["q"] == q["id"]), None)
                if g:
                    store.journal_append(
                        {
                            "type": "grant",
                            "order": order,
                            "q": q["id"],
                            "by": by,
                            "until": g["until"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
                    )
            elif kind == "factory:change":
                if answer == "Accept":
                    store.journal_append(
                        {
                            "type": "change-accepted",
                            "order": order,
                            "q": q["id"],
                            "file": e["row"]["file"],
                            "by": by,
                        }
                    )
            elif kind == "factory:stop":
                store.journal_append(
                    {"type": "stop-answered", "order": order, "q": q["id"], "answer": answer, "by": by}
                )
        d["rows"] = [r for r in store.journal_read() if r["order"] == order]
        if d["kind"] == "autopilot":
            d["grant_valid"] = any(clock() < g["until"] for g in autopilot.grants_of(store, ticket))
        refresh(root, store, order, d)
        return _step(d)


# ---- crew, change, tiny, stop, ship ---------------------------------------------------------------------------


def started_state(root, store, ticket, tickets=None):
    d = derive(root, store, ticket, tickets)
    if d["phase"] != "started" or d["kind"] == "autopilot":
        raise Refused("A person has not pressed Start on this order yet.", "not_allowed")
    if d["shipped"]:
        raise Refused("This order is already shipped.", "not_allowed")
    return d


def crew_add(root, order, task):
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        tickets = orchcli.tickets(root)
        d = started_state(root, store, ticket, tickets)
        t = d["tasks"].get(task)
        if t is None:
            raise Refused("That task is not in the proposal you approved.", "not_allowed")
        if t["agent"] is None:
            raise Refused("That task needs a crew role the proposal does not have.", "not_allowed")
        if task in d["crew"]:
            return {"order": d["tid"], "task": task, "ticket": d["crew"][task]["id"], "created": False}
        new = orchcli.call(root, "ticket", "new", t["title"], "--parent", d["tid"], write=True)
        orchcli.set_ext(
            root, new, role="crew", order=d["tid"], task=task, crew_role=t["role"], agent=t["agent"]
        )
        store.journal_append({"type": "crew-added", "order": d["tid"], "why": task})
        d = derive(root, store, commands.order_ticket(root, d["tid"]))
        refresh(root, store, d["tid"], d)
        return {"order": d["tid"], "task": task, "ticket": new["id"], "created": True}


def crew_start(root, order, task):
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        d = started_state(root, store, ticket)
        t = d["tasks"].get(task)
        if t is None:
            raise Refused("That task is not in the proposal you approved.", "not_allowed")
        if t["stage"] != d["stage"]:
            raise Refused("That task is not in the stage the run is at now.", "not_allowed")
        if d["open"]:
            raise Refused("The run waits for your answer first.", "not_allowed")
        crew = d["crew"].get(task)
        if crew is None:
            raise Refused("Add the crew ticket first (orch factory crew add).", "invalid")
        if d["cap"] and d["used"] >= d["cap"]:
            raise Refused(
                "The time budget is used up. Ask the owner for more time (a change proposal).", "refused"
            )
        orchcli.call(root, "run", "start", crew["id"], "--agent", t["agent"], write=True)
        return {"order": d["tid"], "task": task, "ticket": crew["id"], "agent": t["agent"]}


def change(root, order, data):
    value = parse(data, "change")
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        d = started_state(root, store, ticket)
        stages = [x["stage"] for x in d["proposal"]["line"]]
        roles = {c["role"] for c in d["proposal"]["crew"]}
        if value["lands_in"] not in stages:
            raise Refused("The change must land in a stage of the line.", "invalid")
        done = {x["stage"] for x in d["line"] if x["state"] == "done"}
        if value["lands_in"] in done or any(t["stage"] in done for t in value.get("adds_tasks", [])):
            raise Refused("That stage is already finished; a change cannot land there.", "invalid")
        for t in value.get("adds_tasks", []):
            if t["stage"] not in stages or t["slug"] in d["tasks"]:
                raise Refused("A new task needs a stage of the line and a new name.", "invalid")
            if t["role"] not in roles:
                raise Refused("A new task cannot use a crew role the proposal does not have.", "not_allowed")
        info = freeze_ask(root, store, ticket, "factory:change", data, value, ext={"stage": "waiting"})
        d = derive(root, store, commands.order_ticket(root, d["tid"]))
        refresh(root, store, d["tid"], d)
        return info


def tiny(root, order, minutes, what):
    what = clean(what, 200)
    if minutes < 1 or not what:
        raise Refused("Say what you changed and for how many minutes (1 or more).", "invalid")
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        d = started_state(root, store, ticket)
        rows = [r for r in d["rows"] if r["type"] == "tiny-change"]
        if len(rows) + 1 > TINY_COUNT or sum(_minutes(r) for r in rows) + minutes > TINY_MINUTES:
            raise Refused(
                f"Small changes are capped at {TINY_COUNT} changes or {TINY_MINUTES} minutes. Make a change proposal.",
                "refused",
            )
        store.journal_append({"type": "tiny-change", "order": d["tid"], "why": f"{minutes} min: {what}"})
        d = derive(root, store, commands.order_ticket(root, d["tid"]))
        refresh(root, store, d["tid"], d)
        return {
            "order": d["tid"],
            "count": len(rows) + 1,
            "minutes": sum(_minutes(r) for r in rows) + minutes,
        }


def stop(root, order, data):
    value = parse(data, "stop")
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        d = started_state(root, store, ticket)
        if value["stage"] != d["stage"]:
            raise Refused("That is not the stage the run is at now.", "not_allowed")
        if not next(x for x in d["proposal"]["line"] if x["stage"] == value["stage"])["stop"]:
            raise Refused("The proposal you approved has no stop at this stage.", "not_allowed")
        if any(i.get("recommend") and i["tag"] != "routine" for i in value["items"]):
            raise Refused("Only routine items can carry a recommended answer.", "not_allowed")
        if d["open"] and d["open"]["row"]["kind"] == "factory:stop":
            same = digest(data) == d["open"]["row"]["hash"]
            if not same:
                raise Refused("A stop for this stage is already waiting for your answer.", "conflict")
        info = freeze_ask(root, store, ticket, "factory:stop", data, value, ext={"stage": "waiting"})
        d = derive(root, store, commands.order_ticket(root, d["tid"]))
        refresh(root, store, d["tid"], d)
        return info


def ship(root, order):
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        d = started_state(root, store, ticket)
        if not d["finished"]:
            raise Refused("The owner has not said Ship it yet.", "not_allowed")
        if not d["ship_ok"]:
            raise Refused("Only a person's Ship it ships.", "not_allowed")
        store.journal_append({"type": "shipped", "order": d["tid"], "by": d["ship_by"]})
        d = derive(root, store, commands.order_ticket(root, d["tid"]))
        refresh(root, store, d["tid"], d)
        return {"order": d["tid"], "step": "done"}


def reconcile(root):
    store = Store(root)
    result = []
    with store.locked():
        tickets = orchcli.tickets(root)
        for t in tickets:
            ext = t.get("ext", {}).get("factory", {})
            if ext.get("role") != "order":
                continue
            item = {"order": t["id"], "problems": [], "consumed": [], "unconsumed": [], "orphans": []}
            try:
                recorded = {r.get("q") for r in store.journal_read() if r["type"] == "asked"}
            except Refused:
                recorded = None
            if recorded is not None:
                # Asked in core but never recorded (a crash between ask and journal): listed, never repaired.
                item["orphans"] = [
                    q["id"]
                    for q in t.get("questions", [])
                    if str(q.get("kind", "")).startswith("factory:") and q["id"] not in recorded
                ]
                for qid in item["orphans"]:
                    item["problems"].append(
                        f"Question {qid} has no Factory record (orphan); it has no authority."
                    )
            try:
                d = derive(root, store, t, tickets)
            except Refused as error:
                item["problems"].append(str(error))
                result.append(item)
                continue
            consumed = {r["q"] for r in d["rows"] if r["type"] == "consumed"}
            item["consumed"] = sorted(consumed)
            item["unconsumed"] = [e["q"]["id"] for e in d["pending"]]
            if d["phase"] == "started" and d["kind"] == "run":
                stage = "shipped" if d["shipped"] else "waiting" if d["open"] else "running"
                if ext.get("stage") != stage:
                    item["problems"].append(f"The cached stage is {ext.get('stage')}, derived {stage}.")
            elif d["phase"] != "started" and ext.get("stage") in ("running", "waiting", "shipped"):
                item["problems"].append("The cache says started but no person pressed Start.")
            known = {x["id"] for x in d["crew"].values()}
            for c in tickets:
                if c.get("parent") == t["id"] and c["id"] not in known:
                    item["problems"].append(
                        f"Sub-ticket {c['id']} is not a crew ticket of the approved tasks."
                    )
            result.append(item)
    return {"orders": result}
