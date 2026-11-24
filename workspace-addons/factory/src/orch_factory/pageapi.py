"""The JSON answers of the Factory page (read only). Every state comes from flow.derive / authority / autopilot,
never from the ext cache or raw journal rows. Shapes: contracts/addons/factory/README.md, section Page."""

from __future__ import annotations

import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path

from . import ask, authority, autopilot, flow, handover, orchcli, render, service, watch
from .render import clean
from .store import Refused, Store, clock, no_links

MAX_DRAFT = 256 * 1024
MAX_IMAGE = 10 * 1024 * 1024
ORDER_ID = re.compile(r"t_[a-z0-9]{6,16}")
IMAGE_NAME = re.compile(r"(?:s[1-9][0-9]{0,3}/)?[A-Za-z0-9._-]{1,80}\.(png|jpg|jpeg|webp|gif)")
IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
# A built task's own proof files (core copies them into the ticket's evidence folder): pictures of the screens and a
# short demo (an animated picture or a small video). Only these names are ever served, and only for the order's crew.
RESULT_FILE = re.compile(
    r"\.orch/tickets/(t_[a-z0-9]{6,16})/evidence/([A-Za-z0-9._-]{1,80}\.(png|jpg|jpeg|webp|gif|mp4|webm))"
)
RESULT_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}\.(png|jpg|jpeg|webp|gif|mp4|webm)")
PICTURES = ("png", "jpg", "jpeg", "webp")
RESULT_TYPES = {**IMAGE_TYPES, "mp4": "video/mp4", "webm": "video/webm"}
MAX_DEMO = 25 * 1024 * 1024
PULL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+")
TIME_Z = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
CHANGE_STATES = {"Accept": "accepted", "Edit": "edit", "Save for later": "later"}
ACTIVITY_MAX = 50
DECISIONS_MAX = 100


def _iso(when):
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value, cap=120):
    return clean(value, cap) if isinstance(value, str) else ""


def _order_tickets(tickets):
    return [t for t in tickets if t.get("ext", {}).get("factory", {}).get("role") == "order"]


def _lead(d):
    return [e for e in d["ents"] if e["row"]["kind"] in authority.LEAD]


def _open_question(e):
    q = e["q"]
    kind = e["row"]["kind"].split(":")[1]
    out = {
        "q": q["id"],
        "kind": kind,
        "text": q.get("text", ""),
        "options": list(q.get("options") or []),
    }
    if kind in ("stop", "change"):
        out["data"] = e[
            "data"
        ]  # frozen structured data: the page titles the question from it, never the raw text
    return out


def _plain_questions(ticket):
    """The questions your helper asked on the order itself (no Factory kind) that still wait for you: the draft's open
    questions as cards, each with its options and its suggestion. Text from the record is cut and cleaned."""
    out = []
    for q in ticket.get("questions") or []:
        if not isinstance(q, dict) or q.get("kind") is not None or q.get("answer") is not None:
            continue
        if not isinstance(q.get("id"), str):
            continue
        options = [_text(o, 80) for o in (q.get("options") or []) if isinstance(o, str)][:6]
        rec = _text(q.get("recommended"), 80) if q.get("recommended") else None
        out.append({"q": q["id"], "text": _text(q.get("text"), 300), "options": options, "recommended": rec})
    return out[:10]


def _results(d):
    """The crew's results that wait for your Looks good (core: the ticket is in Check), one row each."""
    out = []
    for slug, t in (d.get("crew") or {}).items():
        if t.get("status") == "review" and slug in d["tasks"]:
            out.append({"ticket": t["id"], "title": _text(d["tasks"][slug]["title"])})
    return out[:10]


def _evidence(t):
    return [
        ev
        for c in t.get("checklist") or []
        if isinstance(c, dict)
        for ev in (c.get("evidence") if isinstance(c.get("evidence"), list) else [])
        if isinstance(ev, dict)
    ]


def _proof_files(t):
    """(pictures, demo) of one built task: its own evidence files, newest last; a gif/mp4/webm is the demo."""
    pictures, demo, seen = [], None, set()
    for ev in _evidence(t):
        m = RESULT_FILE.fullmatch(ev.get("ref") or "") if ev.get("type") == "file" else None
        if not m or m[1] != t.get("id") or m[2] in seen:
            continue
        seen.add(m[2])
        row = {"ticket": t["id"], "name": m[2], "title": _text(ev.get("title"), 80) or None}
        if m[3].lower() in PICTURES:
            pictures.append(row)
        else:
            demo = row
    return pictures, demo


def _tests(t):
    """Each step's newest recorded run: passed (exit 0) or failed. A step without a recorded run is not counted."""
    passed, failing = 0, []
    for c in t.get("checklist") or []:
        if not isinstance(c, dict):
            continue
        runs = [
            e
            for e in (c.get("evidence") if isinstance(c.get("evidence"), list) else [])
            if isinstance(e, dict) and e.get("type") == "command" and type(e.get("exit")) is int
        ]
        if not runs:
            continue
        if runs[-1]["exit"] == 0:
            passed += 1
        else:
            failing.append(_text(c.get("text"), 120))
    return passed, failing


def _code(t):
    """The task's pull requests: how many are merged and how many are not (yet). Core keeps each one's state on
    the ticket's links; a pull request named only in the evidence counts as not merged. One closed without merging
    (replaced by another) waits for nothing and is not counted (ORCH-419)."""
    state = {}
    for r in t.get("refs") or []:
        url = r.get("url") if isinstance(r, dict) else None
        if isinstance(url, str) and PULL.fullmatch(url):
            state[url] = r.get("status")
    for ev in _evidence(t):
        url = ev.get("ref") if ev.get("type") == "pr" else None
        if isinstance(url, str) and PULL.fullmatch(url):
            state.setdefault(url, None)
    merged = sum(1 for s in state.values() if s == "merged")
    return merged, sum(1 for s in state.values() if s not in ("merged", "closed"))


def _reviews(d):
    """One review per stage over the crew's results that wait for your Looks good: pictures of the built screens, a
    short demo, the tests (passed or failed) and whether the code is merged, summed over the stage's tasks."""
    stages = {}
    for slug, t in (d.get("crew") or {}).items():
        if t.get("status") != "review" or slug not in d["tasks"]:
            continue
        stages.setdefault(d["tasks"][slug]["stage"], []).append((d["tasks"][slug], t))
    order = [x["stage"] for x in d.get("line") or []]
    out = []
    for stage in sorted(stages, key=lambda s: order.index(s) if s in order else len(order)):
        rows = stages[stage][:10]
        tasks, pictures, demo, passed, failing, merged, waiting = [], [], None, 0, [], 0, 0
        for task, t in rows:
            pics, dem = _proof_files(t)
            ok, bad = _tests(t)
            m, w = _code(t)
            tasks.append(
                {
                    "ticket": t["id"],
                    "title": _text(task["title"]),
                    "pictures": len(pics),
                    "tests": {"passed": ok, "failed": len(bad)},
                    "code": {"merged": m, "waiting": w},
                }
            )
            pictures += [{**p, "task": _text(task["title"])} for p in pics]
            demo = demo or dem
            passed, merged, waiting = passed + ok, merged + m, waiting + w
            failing += [{"task": _text(task["title"]), "step": s} for s in bad]
        out.append(
            {
                "stage": stage,
                "tickets": [t["ticket"] for t in tasks],
                "tasks": tasks,
                "pictures": pictures[:12],
                "demo": demo,
                "tests": {"passed": passed, "failed": len(failing), "failing": failing[:5]},
                "code": {"merged": merged, "waiting": waiting},
            }
        )
    return out


def _starting(d):
    """The stage the run is about to start: nothing waits for you and none of its crew tickets has been started yet."""
    if d.get("open") or d.get("shipped") or not d.get("stage"):
        return None
    mine = [slug for slug, t in d["tasks"].items() if t["stage"] == d["stage"]]
    if not mine:
        return None
    started = [d["crew"][slug] for slug in mine if slug in d["crew"]]
    if any(t.get("status") not in (None, "open") for t in started):
        return None
    return d["stage"]  # also the first stage (ORCH-277): right after Start nothing else says what comes


def _open_asks(t):
    return flow.open_question(t)


def _waits_on(t):
    w = t.get("waiting_on") if t.get("status") == "waiting" else None
    return w if isinstance(w, dict) else None


TICKET_REF = re.compile(r"\b(?:t_[a-z0-9]{6,16}|[A-Z][A-Z0-9]{0,9}-[0-9]{1,6})\b")


def _held_words(why):
    """Core's refusal without ticket ids: "ORCH-9 waits in line: the computer is very busy. It starts ..." -> "the
    computer is very busy. It starts ..."; any other id becomes "it"."""
    text = _text(why, 200)
    text = re.sub(r"^\S+ waits in line: ", "", text)
    return TICKET_REF.sub("it", text)


def _waiting(ticket, d, held=None, watcher=True, stuck=False):
    """Why no helper works on a started run right now (ORCH-277), or None while one works (the order or a crew
    ticket is Working) or when the order is no started run. {"kind", "task"?, "until"?, "why"?}; the page words it:
    you (a question or a result waits for the person), time (a ticket waits until a time), ticket (a crew ticket waits
    on something else), held (core did not start the manager: the computer is busy, the helper limit ...), watcher
    (the workspace's Factory process is not running, so nothing wakes the manager; the summary adds the workspace's
    name so the page can say where it is started again), starting (the next stage is about to start), idle."""
    if d["phase"] != "started" or d["kind"] != "run" or d["shipped"] or ticket.get("status") == "dropped":
        return None
    crew = [(slug, t) for slug, t in d["crew"].items() if t.get("status") not in ("done", "dropped")]
    if ticket.get("status") == "active" or any(t.get("status") == "active" for _, t in crew):
        return None

    def title(slug):
        return _text(d["tasks"].get(slug, {}).get("title")) or None

    if d["open"] or _results(d) or _plain_questions(ticket):  # Factory's own superseded asks do not count
        return {"kind": "you"}
    for slug, t in crew:
        if _open_asks(t):
            return {"kind": "you", "task": title(slug)}
    for task, t in [(None, ticket), *crew]:
        w = _waits_on(t)
        if w is None:
            continue
        name = title(task) if task else None
        if w.get("kind") == "time" and isinstance(w.get("until"), str):
            return {"kind": "time", "task": name, "until": w["until"]}
        return {"kind": "ticket", "task": name}
    if held:
        return {"kind": "held", "why": _held_words(held.get("why")), "since": held.get("at")}
    if not watcher:
        return {"kind": "watcher"}
    if stuck:  # Factory started the manager again several times and nothing moved
        return {"kind": "stuck"}
    if _starting(d):
        return {"kind": "starting"}
    return {"kind": "idle"}


def _labelled(line, proposal):
    """Stage items with the proposal's own `label` when it gave one (a short, plain name for the owner)."""
    labels = {x["stage"]: x["label"] for x in (proposal or {}).get("line", []) if x.get("label")}
    return [{**x, "label": _text(labels[x["stage"]], 60)} if x["stage"] in labels else x for x in line]


def _eta(d, proposal):
    eta = (proposal.get("time") or {}).get("eta_to") if proposal else None
    for e in sorted(d["ents"], key=lambda x: x["n"]):
        if (
            e["row"]["kind"] == "factory:change"
            and authority.human(e["q"])
            and e["q"]["answer"] == "Accept"
            and e["data"].get("new_eta")
        ):
            eta = e["data"]["new_eta"]
    return eta


def _summary(ticket, d, root=None, held=None, watcher=True, stuck=False, workspace=None):
    """One order summary from a derived state `d`. `held`: the watcher's kept reason why core did not start the
    manager; `watcher`: whether the Factory watcher runs; `workspace`: this workspace's shown name."""
    leads = _lead(d)
    proposal = d.get("proposal") or (leads[-1]["data"] if leads else None)
    kind, phase = d["kind"], "draft"
    if leads:
        phase = {"started": "started", "edit": "edit", "parked": "parked"}.get(d["phase"], "proposed")
    if phase == "started":
        if kind == "run" and d["shipped"]:
            phase = "shipped"
        elif kind == "autopilot" and not any(
            clock() < g["until"] for g in autopilot.grants_of(d["store"], ticket)
        ):
            phase = "cancelled"
    if ticket.get("status") == "dropped" and phase != "shipped":
        phase = "cancelled"
    started_run = d["phase"] == "started" and kind == "run"
    cap = d["cap"] if started_run else ((proposal or {}).get("budget") or {}).get("active_min_cap", 0)
    used = d["used"] if started_run else 0
    if started_run:
        line = d["line"]
    else:
        line = [
            {"stage": x["stage"], "stop": x["stop"], "state": "todo"}
            for x in (proposal or {}).get("line", [])
        ]
    line = _labelled(line, proposal)
    open_ = None
    if started_run and d["open"]:
        open_ = _open_question(d["open"])
    elif leads and d["phase"] != "started":
        latest = leads[-1]
        if latest["q"].get("answer") is None:
            open_ = _open_question(latest)
    stage = "shipped" if phase == "shipped" else (d["stage"] if started_run else None)
    out = {
        "id": ticket["id"],
        "title": _text((proposal or {}).get("title") or ticket.get("title") or "Untitled") or "Untitled",
        "kind": kind,
        "phase": phase,
        "stage": stage,
        "line": line,
        "budget": {"used": used, "cap": cap, "warn": cap > 0 and used * 5 >= cap * 4},
        "eta": _eta(d, proposal),
        "due": (proposal or {}).get("due"),
        "open": open_,
        "owner_min": ((proposal or {}).get("time") or {}).get("owner_min"),
        "working": _working(root, ticket, phase),
        "agent_draft": _agent_draft(ticket, d.get("store")),
        "draft_v": _draft_v(ticket),
        "closed": authority.closed(ticket),  # a finished order's draft waits for nobody (as needs())
        "questions": _plain_questions(ticket),
        "results": _results(d) if started_run else [],
        "reviews": _reviews(d) if started_run else [],
        "starting": _starting(d) if started_run else None,
        "waiting": _waiting(ticket, d, held, watcher, stuck) if started_run else None,
    }
    if out["waiting"] and out["waiting"]["kind"] == "watcher":
        # where `orch factory start` is run again (ORCH-1857): the page never sends the viewer to "this computer"
        out["waiting"]["workspace"] = workspace or _workspace_name(root)
    return out


IDLE = ("idle", "attention")  # a live session whose turn ended, or that waits for a person


def _working(root, ticket, phase):
    """An agent works on the order right now. Core keeps the ticket Working while a run is on it (Ready again when a
    one-step run ends), but a LIVE session stays open after its turn: idle at the prompt, or asking the person
    (attention). For a draft that turn's end is what counts, so the draft waits for you: Plan the run / Ask for changes
    (sent into that same session). Asked only for an order in draft that is Working (one `orch run status`)."""
    if ticket.get("status") != "active":
        return False
    if phase != "draft" or root is None:
        return True
    try:
        st = orchcli.call(root, "run", "status", ticket["id"])
    except Refused:
        return True  # unreadable: as core says (Working)
    claim = st.get("claim") if isinstance(st.get("claim"), dict) else {}
    if not st.get("running"):
        return False
    return not (claim.get("mode") == "live" and (claim.get("live") or {}).get("state") in IDLE)


def _agent_draft(ticket, store=None):
    """The newest draft is the agent's: an idea-box order starts with the person's own words as v1, so only v2 and later
    count (an order an agent filed with `orch factory idea` has the agent's v1). Until then Plan the run is not offered.
    An empty draft file never counts (persona test 18 Nov: an order from before ORCH-231 kept an empty v1, so Factory
    said it waited for you and offered Plan the run on "This draft is empty")."""
    x = (ticket.get("ext") or {}).get("factory") or {}
    v = _draft_v(ticket) or 0
    if v < (2 if x.get("idea_box") is True else 1):
        return False
    return store is None or _written(store, ticket["id"], v)


def _written(store, order_id, v):
    """Whether draft v of an order has any text (an unreadable file counts as not written)."""
    try:
        return bool(_read_regular(store.path(f"drafts/{order_id}/v{v}.md"), 4096).strip())
    except (OSError, Refused):
        return False


def _draft_v(ticket):
    """The newest draft version (from the ext cache; only used for a link, the draft itself is read from its file)."""
    v = ((ticket.get("ext") or {}).get("factory") or {}).get("draft")
    return v if type(v) is int and v > 0 else None


def _broken(ticket, error):
    return {
        "id": ticket["id"],
        "title": _text(ticket.get("title") or "Untitled") or "Untitled",
        "kind": "run",
        "phase": "broken",
        "stage": None,
        "line": [],
        "budget": {"used": 0, "cap": 0, "warn": False},
        "eta": None,
        "due": None,
        "open": None,
        "owner_min": None,
        "working": False,
        "agent_draft": False,
        "draft_v": None,
        "closed": authority.closed(ticket),
        "questions": [],
        "results": [],
        "reviews": [],
        "starting": None,
        "waiting": None,
        "problem": _text(str(error), 200),
    }


MEASURE_TTL = 20  # seconds a page keeps an order's measured active time (the record is read per crew ticket)
_measured: dict = {}


def _derive(root, store, ticket, tickets):
    d = flow.derive(root, store, ticket, tickets)
    d["store"] = store
    _show_measured(root, d)
    return d


def _show_measured(root, d):
    """The shown active time is measured from core's record, as `next` and the watcher do; the cached value is only
    what is left when nobody measured (watcher off) or the record can't be read (never a made-up 0 %)."""
    if d.get("phase") != "started" or d.get("kind") != "run":
        return
    key = (str(root), d["tid"])
    seen = _measured.get(key)
    if seen and time.monotonic() - seen[0] < MEASURE_TTL:
        d["used"] = seen[1]
        return
    flow._measure(root, d)
    if d.get("measured"):
        _measured[key] = (time.monotonic(), d["used"])


def _day(row):
    try:
        return datetime.fromisoformat(row["at"]).astimezone().date()
    except (KeyError, TypeError, ValueError):
        return None


def _decisions(journal, ok):
    rows = [
        {"order": r["order"], "q": r["q"], "answer": r.get("answer"), "why": r.get("why", ""), "at": r["at"]}
        for r in journal
        if r["type"] == "decided" and r["q"] in ok
    ]
    return rows[::-1][:DECISIONS_MAX]


def _grants(store, tickets, journal):
    now = clock()
    return [
        {
            "order": g["order"],
            "until": _iso(g["until"]),
            "may": list(g["may"]),
            "limits": g["limits"],
            "live": g["from"] <= now < g["until"],
        }
        for g in autopilot.grants(store, tickets, journal)
    ]


def _all(root, own=False):
    """(summaries, ok decided question ids, store, tickets, journal): one pass over every order. `own`: read
    only the tickets with Factory's data (orders, crew), enough for orders, crew and grants (ORCH-603)."""
    store = Store(root)
    tickets = orchcli.own_tickets(root) if own else orchcli.tickets(root)
    journal = store.journal_read()
    summaries, ok = [], set()
    held, on, stuck = watch.held(store), _watcher_on(root), watch.stuck(store)
    name = None if on else _workspace_name(root)  # read once, not once per order
    for t in _order_tickets(tickets):
        try:
            d = _derive(root, store, t, tickets)
        except Refused as error:
            summaries.append(_broken(t, error))
            continue
        summaries.append(_summary(t, d, root, held.get(t["id"]), on, t["id"] in stuck, name))
        ok |= d["decided_ok"]
    return summaries, ok, store, tickets, journal


def _watcher_on(root):
    return service.running_pid(root, clean=False) is not None


def _workspace_name(root):
    """The name a person knows this workspace by: its own name (`orch config set workspace.name`), else its folder's
    name. A standalone Factory (no core to ask) uses the folder's name."""
    name = None
    try:
        from orch import config

        name = config.workspace_name(Path(root))
    except Exception:  # noqa: BLE001 - no core, or an unreadable config: the folder's name
        name = None
    return _text(name or Path(root).resolve().name, 64) or None


def _day_limit(root, store, tickets, journal):
    status = autopilot.day_status(root, store, tickets, journal)
    if status is None:
        return None
    return {**status, "warning": autopilot.day_warning(status)}


def home(root):
    # orders, crew and grants read only Factory's own tickets (ORCH-1621: the full list took 2 s at 10,000)
    summaries, ok, store, tickets, journal = _all(root, own=True)
    grants = _grants(store, tickets, journal)
    on = _watcher_on(root)
    auto = None
    if grants:
        today = datetime.now().astimezone().date()
        auto = {
            "on": any(g["live"] for g in grants),
            "until": max(g["until"] for g in grants),
            "decided_today": sum(
                1 for r in journal if r["type"] == "decided" and r["q"] in ok and _day(r) == today
            ),
        }
    return {
        "generated_at": _iso(clock()),
        "orders": summaries,
        "autopilot": auto,
        "day_limit": _day_limit(root, store, tickets, journal),
        "watcher": on,
        "workspace": _workspace_name(root),
    }


DRAFT_TEXT = "Your draft is ready. Read it, then plan the run or ask for changes."


def needs(root):
    """`orch factory needs`: one row per draft that waits for you, and one per stage review that waits for the person's Looks good (contracts/needs.schema.json),
    the same review the Factory page shows (ORCH-419). In a terminal the person answers it with core's own commands:
    Looks good = each built task to done (`cli`), a change = words to the helper on the order."""
    summaries, _ok, store, tickets, _journal = _all(root, own=True)  # fast at 10,000 tickets (ORCH-603)
    changed = {t["id"]: t.get("updated_at") for t in tickets}
    closed = {t["id"] for t in tickets if authority.closed(t)}
    now = _iso(clock())
    out = []
    for o in summaries:
        # a draft that waits for you, by the page's own rule (draftWaiting: phase draft, the agent's own version, its
        # turn ended), so Home and Review list and count what the Factory page lists (ORCH-479)
        if (
            o["phase"] == "draft"
            and o["agent_draft"]
            and not o["working"]
            and o["id"] not in closed
            and ORDER_ID.fullmatch(o["id"])
        ):
            drafts = _drafts(store, o["id"])
            v = o["draft_v"] or (drafts[-1]["v"] if drafts else 1)
            since = drafts[-1]["at"] if drafts else (changed.get(o["id"]) or now)
            out.append(
                {
                    "id": f"factory:draft:{o['id']}:v{v}",
                    "source": "factory",
                    "kind": "factory:draft",
                    "ticket": o["id"],
                    "title": _text(o["title"], 200) or "Untitled",
                    "text": DRAFT_TEXT,
                    "tone": "needs-you",
                    "since": since,
                    "draft": v,
                }
            )
        for r in o.get("reviews") or []:
            ids = [t for t in r.get("tickets") or [] if ORDER_ID.fullmatch(t)]
            if not ids or not ORDER_ID.fullmatch(o["id"]):
                continue
            item = next((x for x in o.get("line") or [] if x.get("stage") == r["stage"]), {})
            stage = _text(item.get("label"), 60) or (r["stage"][:1].upper() + r["stage"][1:])
            n = len(ids)
            text = (
                f"{stage}: what your crew built. {n} {'task waits' if n == 1 else 'tasks wait'} for your Looks good. "
                f'For a change: orch run send {o["id"]} "Change at {stage}: <what should change>"'
            )
            since = min(
                (w for t in ids if isinstance(w := changed.get(t), str) and TIME_Z.fullmatch(w)), default=now
            )
            row = {
                "id": f"factory:review:{o['id']}:{r['stage']}",
                "source": "factory",
                "kind": "factory:review",
                "ticket": o["id"],
                "title": _text(o["title"], 200) or "Untitled",
                "text": text[:500],
                "tone": "needs-you",
                "since": since,
                "order": o["id"],
                "stage": r["stage"],
                "tickets": ids,
            }
            cli = " && ".join(f"orch ticket status {t} done" for t in ids)
            if len(cli) <= 300:
                row["cli"] = cli
            out.append(row)
    return out


def autopilot_view(root):
    _, ok, store, tickets, journal = _all(root, own=True)
    return {"grants": _grants(store, tickets, journal), "decisions": _decisions(journal, ok)}


def _drafts(store, order):
    base = store.path(f"drafts/{order}")
    found = []
    try:
        names = list(base.iterdir())
    except OSError:
        return []
    for p in names:
        m = re.fullmatch(r"v([1-9][0-9]*)\.md", p.name)
        if not m:
            continue
        try:
            st = p.lstat()
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            found.append({"v": int(m[1]), "at": _iso(datetime.fromtimestamp(st.st_mtime, UTC))})
    return sorted(found, key=lambda x: x["v"])


def _tiny(d):
    out = []
    for r in d["rows"]:
        if r["type"] == "tiny-change":
            m = re.match(r"(\d+) min: (.*)", r.get("why", ""), re.DOTALL)
            out.append({"what": _text(m[2], 200) if m else "", "minutes": int(m[1]) if m else 0})
    return out


def _stops(d, root=None, tickets=()):
    out = []
    outbox = None
    named = ask.names(root) if root is not None else {}
    for e in sorted((e for e in d["ents"] if e["row"]["kind"] == "factory:stop"), key=lambda e: e["n"]):
        eff = d["effective"](e)
        if eff:
            state, answer, by = ("decided" if eff[1] == "agent:factory" else "answered"), eff[0], eff[1]
        elif e["q"].get("answer") is not None:
            state, answer, by = "ignored", None, authority.who(e["q"]) or None
        else:
            state, answer, by = "open", None, None
        asks = ask.view(root, tickets, d["tid"], e["n"], named, outbox) if root is not None else []
        if any(a["state"] == "queued" for a in asks) and outbox is None:
            outbox = _outbox(root)  # one look at what waits to be sent, only when an ask says it is queued
            asks = ask.view(root, tickets, d["tid"], e["n"], named, outbox)
        out.append(
            {
                "n": e["n"],
                "stage": e["data"]["stage"],
                "data": e["data"],
                "state": state,
                "answer": answer,
                "by": by,
                "asks": asks,
                "autopilot_waits": state == "open"
                and any(a["state"] != "failed" and a["state"] != "closed" for a in asks),
            }
        )
    return out


def _outbox(root):
    try:
        return orchcli.call(root, "relay", "outbox").get("waiting") or []
    except Refused:
        return []


def reach(root):
    """Workspaces a stop may be shared with (empty when the relay is off, so the page shows no button)."""
    return ask.reach(root)


def scan(root, order_id, n):
    if not ORDER_ID.fullmatch(order_id):
        return None
    try:
        return ask.scan_stop(root, order_id, n)
    except Refused:
        return None


def _changes(d):
    out = []
    for e in sorted((e for e in d["ents"] if e["row"]["kind"] == "factory:change"), key=lambda e: e["n"]):
        q = e["q"]
        state = CHANGE_STATES.get(q.get("answer"), "open") if authority.human(q) else "open"
        out.append(
            {
                "n": e["n"],
                "title": _text(e["data"]["title"]),
                "adds_min": e["data"].get("adds_min", 0),
                "state": state,
            }
        )
    return out


def _crew(d, root, store):
    out = []
    handovers = {h["task"]: h for h in d.get("proposal", {}).get("handovers", [])}
    for slug, task in d["tasks"].items():
        t = d["crew"].get(slug)
        row = {
            "ticket": t["id"] if t else None,
            "title": _text(task["title"]),
            "role": task["role"],
            "agent": task.get("agent"),
            "status": (t.get("status") if t else None) or ("open" if t else "todo"),
        }
        h = handover.of(d, slug)
        if h is not None:
            mine = handover.cached(t) if t else None
            name = handover.display_name(root, h["workspace"])
            state = (mine or {}).get("state")
            row["with"] = {
                "name": name,
                "state": state,
                "words": render.handover_words(name, state) if state else "Goes to " + name,
                "since": handover.sent_at(store, t["id"]) if t else None,
            }
        elif slug in handovers and t and handover.cached(t):
            row["with"] = {
                "name": handover.cached(t).get("name"),
                "state": "not_needed",
                "words": "Done here instead",
                "since": None,
            }
        out.append(row)
    return out


def _activity(ticket):
    lines = [
        {"at": h.get("at"), "text": _text(h.get("text"), 300)}
        for h in authority.history(ticket)
        if isinstance(h, dict)
        and isinstance(h.get("text"), str)
        and (h["text"].startswith("Factory") or h["text"].startswith("Decided by agent:factory"))
    ]
    return lines[-ACTIVITY_MAX:]


def order(root, order_id):
    """The order page answer, or None when this is no Factory order."""
    if not ORDER_ID.fullmatch(order_id):
        return None
    store = Store(root)
    tickets = orchcli.tickets(root)
    ticket = next((t for t in _order_tickets(tickets) if t["id"] == order_id), None)
    if ticket is None:
        return None
    try:
        d = _derive(root, store, ticket, tickets)
    except Refused as error:
        return {**_broken(ticket, error), "proposal": None, "drafts": _drafts(store, order_id)}
    leads = _lead(d)
    proposal = d.get("proposal") or (leads[-1]["data"] if leads else None)
    return {
        **_summary(
            ticket,
            d,
            root,
            watch.held(store).get(order_id),
            _watcher_on(root),
            order_id in watch.stuck(store),
        ),
        "proposal": proposal,
        "drafts": _drafts(store, order_id),
        "crew": _crew(d, root, store),
        "handover": handover.lines(root, proposal) if proposal and proposal.get("kind") == "run" else [],
        "changes": _changes(d),
        "tiny": _tiny(d),
        "stops": _stops(d, root, tickets),
        "activity": _activity(ticket),
    }


def _read_regular(path: Path, cap: int):
    """The bytes of a regular file (no link anywhere on the way, never follows one), at most cap+1 bytes."""
    no_links(path)
    # O_NONBLOCK: a FIFO planted in the folder must fail the regular-file check, never block the open
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("not a regular file")
        return stream.read(cap + 1)


def draft(root, order_id, v):
    """{"v", "text"} (plain text, at most 256 KB; "truncated" when longer), or None."""
    if not ORDER_ID.fullmatch(order_id) or not re.fullmatch(r"[1-9][0-9]{0,5}", v):
        return None
    try:
        data = _read_regular(Store(root).path(f"drafts/{order_id}/v{v}.md"), MAX_DRAFT)
    except (OSError, Refused):
        return None
    out = {"v": int(v), "text": data[:MAX_DRAFT].decode("utf-8", "replace")}
    if len(data) > MAX_DRAFT:
        out["truncated"] = True
    return out


def image(root, order_id, name):
    """(bytes, content type) of a stop image, or None. Only names of IMAGE_NAME inside stops/<id>/."""
    if not ORDER_ID.fullmatch(order_id) or not IMAGE_NAME.fullmatch(name):
        return None
    try:
        data = _read_regular(Store(root).path(f"stops/{order_id}/{name}"), MAX_IMAGE)
    except (OSError, Refused):
        return None
    if len(data) > MAX_IMAGE:
        return None
    return data, IMAGE_TYPES[name.rsplit(".", 1)[1].lower()]


def result_file(root, order_id, ticket_id, name):
    """(bytes, content type) of a picture or the demo of one of the order's built tasks, or None. Only a file the
    task's own evidence names, inside that ticket's evidence folder; never another ticket's file."""
    if (
        not ORDER_ID.fullmatch(order_id)
        or not ORDER_ID.fullmatch(ticket_id)
        or not RESULT_NAME.fullmatch(name)
    ):
        return None
    try:
        tickets = orchcli.tickets(root)
    except Refused:
        return None
    crew = next(
        (
            t
            for t in tickets
            if t.get("id") == ticket_id
            and t.get("parent") == order_id
            and (t.get("ext") or {}).get("factory", {}).get("role") == "crew"
            and (t.get("ext") or {}).get("factory", {}).get("order") == order_id
        ),
        None,
    )
    if crew is None:
        return None
    pictures, demo = _proof_files(crew)
    if not any(x["name"] == name for x in [*pictures, *([demo] if demo else [])]):
        return None
    ext = name.rsplit(".", 1)[1].lower()
    cap = MAX_DEMO if ext in ("gif", "mp4", "webm") else MAX_IMAGE
    try:
        data = _read_regular(Path(root) / ".orch" / "tickets" / ticket_id / "evidence" / name, cap)
    except (OSError, Refused):
        return None
    if len(data) > cap:
        return None
    return data, RESULT_TYPES[ext]
