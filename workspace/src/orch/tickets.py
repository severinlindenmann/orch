"""Tickets: one JSON file per ticket in .orch/tickets/<id>.json.

Unknown fields are kept: a ticket is loaded as a plain dict, changed, saved whole.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from orch.errors import Refused

STATUSES = ("open", "active", "waiting", "done", "dropped")
EVIDENCE_TYPES = ("pr", "commit", "file", "url", "command", "note")
WAIT_KINDS = ("question", "workspace", "webhook", "person", "other")
_ID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> str:
    """Any ISO 8601 time -> UTC RFC 3339 ending in Z. Without offset = UTC."""
    t = text.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise Refused(f"'{text}' is not a time. Use e.g. 2026-11-05T08:00:00+01:00") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_actor(explicit: str | None = None) -> str:
    """--by, else the agent tool seen in the environment, else human:<os user>."""
    if explicit:
        who = explicit
    elif os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        who = "agent:claude-code"
    elif any(k.startswith("CODEX_") for k in os.environ):
        who = "agent:codex"
    else:
        try:
            user = getpass.getuser()
        except Exception:
            user = "user"
        who = "human:" + re.sub(r"[^A-Za-z0-9_.@ -]", "_", user)[:64]
    if not re.fullmatch(r"(agent|human):[A-Za-z0-9_.@ -]{1,64}", who):
        raise Refused(f"'{who}' is not a valid actor. Use agent:<tool> or human:<name>.")
    return who


def tickets_dir(root: Path) -> Path:
    return root / ".orch" / "tickets"


def ticket_path(root: Path, tid: str) -> Path:
    if not _ID_RE.match(tid):
        raise Refused(f"'{tid}' is not a ticket id (like t_7k3f9q).")
    return tickets_dir(root) / f"{tid}.json"


def new_id(root: Path) -> str:
    for _ in range(100):
        tid = "t_" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not ticket_path(root, tid).exists():
            return tid
    raise Refused("Could not find a free ticket id.")


def load(root: Path, tid: str) -> dict:
    p = ticket_path(root, tid)
    if not p.exists():
        raise Refused(f"There is no ticket {tid}.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(root: Path, ticket: dict) -> None:
    """Atomic: write a temp file in the same folder, then rename over the target."""
    p = ticket_path(root, ticket["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    ticket["updated_at"] = now()
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(ticket, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_all(root: Path) -> list[dict]:
    d = tickets_dir(root)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("t_*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    out.sort(key=lambda t: t.get("created_at", ""))
    return out


def add_history(ticket: dict, by: str, text: str) -> None:
    ticket["history"].append({"at": now(), "by": by, "text": text})


def create(root: Path, title: str, by: str, recurring: str | None = None) -> dict:
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "title": title,
        "type": "recurring" if recurring else "task",
        "status": "open",
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "links": [],
        "questions": [],
        "history": [{"at": t, "by": by, "text": "Created"}],
    }
    if recurring:
        ticket["ext"] = {"scheduler": {"cron": recurring}}
    save(root, ticket)
    return ticket


def checks_done(ticket: dict) -> tuple[int, int]:
    c = ticket.get("checklist", [])
    return sum(1 for x in c if x.get("done")), len(c)


def set_status(root: Path, tid: str, status: str, by: str) -> dict:
    if status not in STATUSES:
        raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
    ticket = load(root, tid)
    if status == "done":
        bad = [c["id"] for c in ticket["checklist"] if c.get("done") and not c.get("evidence")]
        if bad:
            raise Refused(f"Not done: {', '.join(bad)} is checked without evidence.")
    if status != "waiting":
        ticket["waiting_on"] = None
    old = ticket["status"]
    ticket["status"] = status
    if status in ("done", "dropped"):
        ticket["wake_at"] = None
    if old != status:
        add_history(ticket, by, f"Status {old} -> {status}")
    save(root, ticket)
    return ticket


def edit(root: Path, tid: str, title: str | None, by: str) -> dict:
    ticket = load(root, tid)
    if title is not None:
        title = title.strip()
        if not title or len(title) > 200:
            raise Refused("A title needs 1 to 200 characters.")
        ticket["title"] = title
        add_history(ticket, by, "Title changed")
    save(root, ticket)
    return ticket


def _next_id(items: list[dict], prefix: str) -> str:
    nums = [int(i["id"][1:]) for i in items if re.fullmatch(prefix + r"[0-9]+", str(i.get("id", "")))]
    return f"{prefix}{max(nums, default=0) + 1}"


def check_add(root: Path, tid: str, text: str, by: str) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A checklist item needs text.")
    ticket = load(root, tid)
    item = {"id": _next_id(ticket["checklist"], "c"), "text": text.strip(), "done": False, "evidence": []}
    ticket["checklist"].append(item)
    add_history(ticket, by, f"Added check {item['id']}")
    save(root, ticket)
    return ticket, item


def parse_evidence(raw: str) -> dict:
    try:
        ev = json.loads(raw)
    except ValueError:
        raise Refused('Evidence must be JSON, e.g. \'{"type":"pr","ref":"PR #88"}\'.') from None
    if not isinstance(ev, dict) or ev.get("type") not in EVIDENCE_TYPES:
        raise Refused(f"Evidence type must be one of: {', '.join(EVIDENCE_TYPES)}.")
    if not isinstance(ev.get("ref"), str) or not ev["ref"].strip():
        raise Refused("Evidence needs a ref (PR, commit, file, URL, command or note text).")
    if "text" in ev and not isinstance(ev["text"], str):
        raise Refused("Evidence text must be a string.")
    return ev


def check_done(root: Path, tid: str, cid: str, evidence: list[str], by: str) -> tuple[dict, dict]:
    if not evidence:
        raise Refused('Done needs evidence: --evidence \'{"type":"command","ref":"pytest -q"}\'.')
    evs = [parse_evidence(e) for e in evidence]
    ticket = load(root, tid)
    item = next((c for c in ticket["checklist"] if c["id"] == cid), None)
    if item is None:
        raise Refused(f"Ticket {tid} has no check {cid}.")
    item["evidence"].extend(evs)
    item["done"] = True
    add_history(ticket, by, f"Check {cid} done")
    save(root, ticket)
    return ticket, item


def log(root: Path, tid: str, text: str, by: str) -> dict:
    if not text.strip():
        raise Refused("A history entry needs text.")
    ticket = load(root, tid)
    add_history(ticket, by, text.strip())
    save(root, ticket)
    return ticket


def link_add(root: Path, tid: str, type_: str, url: str, title: str | None, by: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{1,32}", type_):
        raise Refused("A link type is lowercase letters, digits and dashes, e.g. github, jira, teams.")
    if not url.strip():
        raise Refused("A link needs a url.")
    ticket = load(root, tid)
    link = {"type": type_, "url": url.strip()}
    if title:
        link["title"] = title
    ticket["links"].append(link)
    add_history(ticket, by, f"Linked {title or type_}")
    save(root, ticket)
    return ticket


def ext_set(root: Path, tid: str, addon: str, data: str, by: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", addon):
        raise Refused("An add-on key is lowercase letters, digits, - or _.")
    try:
        obj = json.loads(data)
    except ValueError:
        raise Refused("ext data must be a JSON object.") from None
    if not isinstance(obj, dict):
        raise Refused("ext data must be a JSON object.")
    ticket = load(root, tid)
    ext = ticket.setdefault("ext", {})
    cur = ext.get(addon)
    if isinstance(cur, dict):  # merge: keep fields this call does not mention
        cur.update(obj)
    else:
        ext[addon] = obj
    if ticket["type"] == "recurring" and not isinstance(ext.get("scheduler", {}).get("cron"), str):
        raise Refused("A recurring ticket needs ext.scheduler.cron.")
    add_history(ticket, by, f"Set ext.{addon}")
    save(root, ticket)
    return ticket


def ask(
    root: Path, tid: str, text: str, options: list[str], recommended: str | None, by: str
) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A question needs text.")
    if recommended is not None and options and recommended not in options:
        raise Refused("The recommended answer must be one of the options.")
    ticket = load(root, tid)
    q = {
        "id": _next_id(ticket["questions"], "q"),
        "text": text.strip(),
        "options": list(options),
        "recommended": recommended,
        "answer": None,
        "answered_by": None,
        "via": None,
    }
    ticket["questions"].append(q)
    ticket["status"] = "waiting"
    ticket["waiting_on"] = {"kind": "question", "ref": q["id"]}
    add_history(ticket, by, f"Asked {q['id']}, waiting")
    save(root, ticket)
    return ticket, q


def answer(root: Path, tid: str, qid: str, text: str, by: str, via: str) -> tuple[dict, dict]:
    if via not in ("cli", "phone", "relay"):
        raise Refused("via must be cli, phone or relay.")
    if not text.strip():
        raise Refused("An answer needs text.")
    ticket = load(root, tid)
    q = next((x for x in ticket["questions"] if x["id"] == qid), None)
    if q is None:
        raise Refused(f"Ticket {tid} has no question {qid}.")
    if q["answer"] is not None:
        raise Refused(f"{qid} is already answered.")
    if q["options"] and text not in q["options"]:
        raise Refused(f"Answer must be one of: {', '.join(q['options'])}.")
    q["answer"], q["answered_by"], q["via"] = text, by, via
    w = ticket.get("waiting_on")
    if w and w.get("kind") == "question" and w.get("ref") == qid:
        ticket["waiting_on"] = None
        if ticket["status"] == "waiting":
            ticket["status"] = "active"
    add_history(ticket, by, f"Answered {qid}: {text}")
    save(root, ticket)
    return ticket, q


def wait(root: Path, tid: str, until: str | None, on: str | None, by: str) -> dict:
    if bool(until) == bool(on):
        raise Refused("Use exactly one of --until <time> or --on <kind>:<ref>.")
    ticket = load(root, tid)
    if until:
        ticket["wake_at"] = parse_time(until)
        ticket["waiting_on"] = None
        note = f"Waiting until {ticket['wake_at']}"
    else:
        kind, sep, ref = on.partition(":")
        if not sep or kind not in WAIT_KINDS or not ref.strip():
            raise Refused(f"--on needs <kind>:<ref> with kind one of: {', '.join(WAIT_KINDS)}.")
        ticket["waiting_on"] = {"kind": kind, "ref": ref.strip()}
        note = f"Waiting on {kind} {ref.strip()}"
    ticket["status"] = "waiting"
    add_history(ticket, by, note)
    save(root, ticket)
    return ticket
