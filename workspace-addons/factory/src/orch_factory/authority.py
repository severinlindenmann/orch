"""Start authority comes only from recorded questions, frozen bytes and human answers."""

import json
import re
from datetime import datetime

from . import orchcli
from .render import clean, render
from .store import Refused, Store, digest, validate

FOLDERS = {
    "factory:start": ("proposals", "p", "run"),
    "factory:autopilot": ("proposals", "p", "autopilot"),
    "factory:change": ("changes", "c", "change"),
    "factory:stop": ("stops", "s", "stop"),
}


def _too_long(label, value, cap):
    if len(clean(value, None)) > cap:
        raise Refused(
            f"{label} is longer than {cap} characters; the owner would not see all of it.", "invalid"
        )


def _caps(d, kind):
    """Refuse any owner-visible field longer than its render cap, so render never has to cut frozen text."""

    def each(label, items, cap=120):
        for x in items or []:
            _too_long(label, x, cap)

    if kind == "run":
        _too_long("The title", d["title"], 120)
        _too_long("The goal", d["goal"], 120)
        each("A done-means point", d["done_means"])
        each("A won't-do point", d.get("wont_do"))
        _too_long("What shipping does", d["ship"]["does"], 120)
        _too_long("How to undo shipping", d["ship"]["undo"], 120)
        for a in d.get("assumptions", []):
            _too_long("An assumption", a["text"], 120)
        for t in d["tasks"]:
            _too_long("A task title", t["title"], 120)
    elif kind == "change":
        _too_long("The title", d["title"], 120)
        _too_long("What the change does", d["what"], 120)
        if d.get("asked_by_owner"):
            _too_long("The owner's words", d["asked_by_owner"], 120)
        each("A done-means point", d.get("adds_done_means"))
        for t in d.get("adds_tasks", []):
            _too_long("A task title", t["title"], 120)
        if d.get("new_eta"):
            _too_long("The new ETA", d["new_eta"], 40)
    elif kind == "stop":
        for i in d["items"]:
            _too_long("A stop item title", i["title"], 120)
            _too_long("A suggested answer", i.get("recommend", ""), 40)
            _too_long("A before reference", i.get("before", ""), 80)
            _too_long("An after reference", i.get("after", ""), 80)
        for key in ("checked", "not_checked", "changed_during_run"):
            each("A stop note", d.get(key))
    elif kind == "autopilot":
        _too_long("The title", d["title"], 120)
        _too_long("The goal", d["goal"], 120)
        each("An example", d.get("examples"))
        each("A done-means point", d["done_means"])


def check_run(value):
    """Invariants of a run proposal (schema checked first)."""
    validate(value, "proposal")
    names = [x["stage"] for x in value["line"]]
    if value["line"][-1]["stage"] != "ship" or value["line"][-1]["stop"] is not True:
        raise Refused("The last stage must be ship, with a stop for you.", "invalid")
    if len(set(names)) != len(names):
        raise Refused("Every stage name must be used only once.", "invalid")
    if any(t["stage"] not in names for t in value["tasks"]):
        raise Refused("Every task must belong to a stage in the line.", "invalid")
    if any(i >= len(value["done_means"]) for t in value["tasks"] for i in t.get("proves", [])):
        raise Refused("A task refers to a done-means point that does not exist.", "invalid")
    slugs = [t["slug"] for t in value["tasks"]]
    if len(set(slugs)) != len(slugs):
        raise Refused("Every task needs its own name.", "invalid")


def check_frozen(file_kind, value):
    """The same validation at freeze time and whenever a frozen file is read back."""
    if not isinstance(value, dict):
        raise Refused("A Factory file must be a JSON object.", "invalid")
    if file_kind == "run":
        check_run(value)
    else:
        validate(value, file_kind)
    if file_kind == "stop" and any(i.get("recommend") and i["tag"] != "routine" for i in value["items"]):
        raise Refused("Only routine items can carry a recommended answer.", "invalid")
    _caps(value, file_kind)


def expected(order, kind, rel, h, data):
    """(text, options, action) Factory must have asked for this frozen file; anything else has no authority."""
    folder, prefix, file_kind = FOLDERS[kind]
    m = re.fullmatch(rf"{folder}/{re.escape(order)}/{prefix}([1-9][0-9]*)\.json", rel)
    if not m or not isinstance(data, dict) or data.get("kind") != file_kind:
        raise Refused("A Factory question does not match its frozen file.", "tampered")
    check_frozen(file_kind, data)
    text, options = render(kind, data, int(m[1]))
    action = {"order": order, "file": rel, "hash": h}
    if kind == "factory:autopilot":
        action["days"] = data["limits"]["days"]
    elif kind == "factory:stop":
        action["stage"] = data["stage"]
    return text, options, action


def answered_at(ticket, q):
    """When a person answered: the core's own history line for that answer (never a Factory file)."""
    want = f"Answered {q['id']}: {q['answer']}"
    for h in history(ticket):
        if h.get("text") == want and h.get("by") == who(q):
            try:
                return datetime.fromisoformat(h["at"])
            except (KeyError, ValueError, TypeError):
                return None
    return None


LEAD = ("factory:start", "factory:autopilot")


def _when(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def history(ticket):
    """The order's history lines as the CLI shows them (`orch ticket show --json` is already the shown ticket)."""
    lines = ticket.get("history")
    return lines if isinstance(lines, list) else []


def who(q):
    """Who answered (core-recorded `answered_by` of the CLI JSON), "" when nobody did."""
    return str(q.get("answered_by") or "")


def human(q):
    return q.get("answer") is not None and who(q).startswith("human:")


def entries(store, ticket, journal=None):
    """Every valid Factory question with its journal row, frozen data and file number.
    `journal`: the rows already read by the caller (saves a re-read)."""
    journal = store.journal_read() if journal is None else journal
    rows = [r for r in journal if r["order"] == ticket["id"]]
    superseded = {r.get("q") for r in rows if r["type"] == "superseded"}
    asked = {r["q"]: r for r in rows if r["type"] == "asked"}
    present = {q["id"] for q in ticket.get("questions", [])}
    for r in rows:
        if r["type"] != "superseded":
            continue
        q = next((x for x in ticket.get("questions", []) if x["id"] == r.get("q")), None)
        if q is not None and human(q):
            # A person pressing a stale question after it was superseded is harmless; one who answered
            # BEFORE it was superseded (or cannot be dated) was hidden by it.
            at, when = answered_at(ticket, q), _when(r.get("at"))
            if at is None or when is None or at < when:
                raise Refused("A person's answer was hidden by a superseded row.", "tampered")
    if set(asked) - superseded - present:
        raise Refused("A recorded Factory question is missing.", "tampered")
    result = []
    for q in ticket.get("questions", []):
        row = asked.get(q["id"])
        if not row or q["id"] in superseded:
            continue
        if q.get("kind") != row.get("kind") or row.get("kind") not in FOLDERS:
            raise Refused("A Factory question no longer matches its journal.", "tampered")
        try:
            raw = store.read(row["file"])
            matches = digest(raw) == row["hash"]
        except FileNotFoundError:
            matches = False
        if not matches:
            raise Refused("The frozen Factory file has changed or is missing.", "tampered")
        try:
            data = json.loads(raw)
            text, options, action = expected(ticket["id"], row["kind"], row["file"], row["hash"], data)
        except (ValueError, UnicodeError):
            raise Refused("A frozen Factory file is not valid.", "tampered") from None
        except Refused as error:
            raise Refused("A frozen Factory file is not valid: " + str(error), "tampered") from None
        if q.get("action") != action:
            raise Refused("A Factory question no longer matches its journal.", "tampered")
        if q.get("text") != text or list(q.get("options") or []) != options:
            raise Refused("A Factory question's text does not match its frozen file.", "tampered")
        result.append(
            {"q": q, "row": row, "data": data, "n": int(re.search(r"(\d+)\.json$", row["file"])[1])}
        )
    leads = {e["row"]["kind"] for e in result if e["row"]["kind"] in LEAD}
    if len(leads) > 1:
        raise Refused("This order has both run and autopilot questions.", "tampered")
    start = next((e for e in result if e["row"]["kind"] == "factory:start" and human_start(e["q"])), None)
    if start:
        stages = {x["stage"] for x in start["data"]["line"]}
        for e in result:
            d = e["data"]
            bad = (e["row"]["kind"] == "factory:stop" and d["stage"] not in stages) or (
                e["row"]["kind"] == "factory:change"
                and (
                    d["lands_in"] not in stages
                    or any(t["stage"] not in stages for t in d.get("adds_tasks", []))
                )
            )
            if bad:
                raise Refused("A Factory file names a stage the approved line does not have.", "tampered")
    return result


def human_start(q):
    return q.get("kind") == "factory:start" and q.get("answer") == "Start" and human(q)


def order_kind(ents):
    """The kind of an order is that of its FIRST recorded lead question (never the ext cache)."""
    for e in ents:
        if e["row"]["kind"] in LEAD:
            return "autopilot" if e["row"]["kind"] == "factory:autopilot" else "run"
    return None


def questions(store, ticket):
    return [e["q"] for e in entries(store, ticket)]


def from_ticket(store, ticket):
    return any(
        q.get("kind") == "factory:start" and q.get("answer") == "Start" and human(q)
        for q in questions(store, ticket)
    )


def started(order, root=None):
    import os
    from pathlib import Path

    root = Path(root or os.environ.get("ORCH_ROOT", "."))
    return from_ticket(Store(root), orchcli.ticket(root, order))
