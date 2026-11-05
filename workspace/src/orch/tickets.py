"""Tickets: one JSON file per ticket in .orch/tickets/<id>.json.

Unknown fields are kept: a ticket is loaded as a plain dict, changed, saved whole.
"""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from orch.errors import Refused

STATUSES = ("open", "active", "waiting", "done", "dropped")
EVIDENCE_TYPES = ("pr", "commit", "file", "url", "command", "note")
WAIT_KINDS = ("time", "ticket", "question", "external")
PATCH_FIELDS = ("title", "status", "waiting_on")
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


def agent_tool() -> str | None:
    """The agent tool this process runs under (from the environment), else None."""
    from orch import adapters

    return adapters.detect_env(os.environ)


def require_human(question: str, what: str) -> None:
    """Human-only step. Under an agent it needs a yes typed at a terminal; otherwise refused (exit 2)."""
    if agent_tool() is None:
        return
    if sys.stdin.isatty():
        sys.stderr.write(f"{question} [y/N] ")
        sys.stderr.flush()
        if sys.stdin.readline().strip().lower() in ("y", "yes"):
            return
        raise Refused(f"Not confirmed. {what} was not done.")
    raise Refused(f"Only a human can do this ({what}). Ask the human to run it themselves.")


def current_actor(explicit: str | None = None) -> str:
    """--by, else the agent tool seen in the environment, else human:<os user>."""
    if explicit:
        who = explicit
        if who.startswith("human:"):
            require_human(f"Record this as done by {who}?", f"acting as {who}")
    elif agent_tool():
        who = "agent:" + str(agent_tool())
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
        raise Refused(f"Ticket {tid} doesn't exist. Run `orch ticket list` to see your tickets.")
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
        raise Refused(f"Ticket {tid} doesn't exist. Run `orch ticket list` to see your tickets.")
    return json.loads(p.read_text(encoding="utf-8"))


def _break_stale(lock: Path) -> bool:
    """Claim a stale lock by renaming it to a name only we know (atomic: just one waiter wins), then check
    that what we took is really old. If it was a fresh lock a faster waiter had just made, put it back."""
    mine = lock.with_name(f"{lock.name}.{secrets.token_hex(4)}")
    try:
        os.replace(lock, mine)
    except OSError:
        return False
    try:
        if time.time() - mine.stat().st_mtime > 30:
            return True
        with contextlib.suppress(OSError):
            os.link(mine, lock)  # no-clobber put-back
        return False
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


@contextlib.contextmanager
def _locked(root: Path, tid: str):
    """One writer at a time per ticket: an exclusive lock file next to it (stale after 30 s)."""
    lock = tickets_dir(root) / f".lock-{tid}"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + 5
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > 30
            except OSError:
                continue
            if stale and _break_stale(lock):
                continue
            if time.monotonic() > end:
                raise Refused(f"Ticket {tid} is being changed right now. Try again.") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def revision(ticket: dict) -> int:
    r = ticket.get("revision", 0)
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 0 else 0


def save(root: Path, ticket: dict) -> None:
    """Atomic and checked: under a lock, refused when the file changed since this ticket was loaded
    (no lost updates between agents and add-ons); `revision` goes up by 1 on every write."""
    p = ticket_path(root, ticket["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with _locked(root, ticket["id"]):
        if p.exists():
            try:
                on_disk = revision(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                on_disk = revision(ticket)
            if on_disk != revision(ticket):
                raise Refused(
                    f"Ticket {ticket['id']} changed while you worked on it. Read it again and retry."
                )
        ticket["revision"] = revision(ticket) + 1
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


def load_checked(root: Path, tid: str, if_revision: int | None) -> dict:
    ticket = load(root, tid)
    if if_revision is not None and revision(ticket) != if_revision:
        raise Refused(
            f"Ticket {tid} is at revision {revision(ticket)}, not {if_revision}. Read it again and retry."
        )
    return ticket


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


def create(root: Path, title: str, by: str) -> dict:
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "title": title,
        "status": "open",
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "links": [],
        "questions": [],
        "history": [{"at": t, "by": by, "text": "Created"}],
    }
    save(root, ticket)
    return ticket


def checks_done(ticket: dict) -> tuple[int, int]:
    c = ticket.get("checklist", [])
    return sum(1 for x in c if x.get("done")), len(c)


def _check_can_finish(ticket: dict) -> None:
    open_ = [c["id"] for c in ticket["checklist"] if not c.get("done")]
    if open_:
        raise Refused(f"Not done: {', '.join(open_)} is not checked yet.")
    bad = [c["id"] for c in ticket["checklist"] if not c.get("evidence")]
    if bad:
        raise Refused(f"Not done: {', '.join(bad)} is checked without evidence.")


def set_status(root: Path, tid: str, status: str, by: str) -> dict:
    if status not in STATUSES:
        raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
    ticket = load(root, tid)
    if status == "done":
        _check_can_finish(ticket)
    if status != "waiting":
        ticket["waiting_on"] = None
    old = ticket["status"]
    ticket["status"] = status
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
    ticket = load(root, tid)  # a missing ticket is reported before anything else
    if not evidence:
        raise Refused(
            "A check is done only with proof. Say what shows it, for example "
            f'`orch check done {tid} {cid} --command "pytest -q"` or `--note "what you saw"` '
            "(also --pr, --commit, --file, --url)."
        )
    evs = [parse_evidence(e) for e in evidence]
    item = next((c for c in ticket["checklist"] if c["id"] == cid), None)
    if item is None:
        raise Refused(f"Ticket {tid} has no check {cid}. Run `orch ticket show {tid}` to see its checks.")
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


def validate_ext(schema: dict, obj: dict, addon: str) -> None:
    import jsonschema

    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        where = ".".join(str(x) for x in e.path)
        raise Refused(f"ext.{addon}{'.' + where if where else ''}: {e.message}")


def ext_set(
    root: Path,
    tid: str,
    addon: str,
    data: str,
    by: str,
    if_revision: int | None = None,
    schema: dict | None = None,
) -> dict:
    """Merge `data` into ext.<addon>. `schema` = the ticket_ext schema of the add-on when it is active."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", addon):
        raise Refused("An add-on key is lowercase letters, digits or -.")
    try:
        obj = json.loads(data)
    except ValueError:
        raise Refused("ext data must be a JSON object.") from None
    if not isinstance(obj, dict):
        raise Refused("ext data must be a JSON object.")
    ticket = load_checked(root, tid, if_revision)
    ext = ticket.setdefault("ext", {})
    cur = ext.get(addon)
    merged = {**cur, **obj} if isinstance(cur, dict) else obj  # keep fields this call does not mention
    if schema is not None:
        validate_ext(schema, merged, addon)
    ext[addon] = merged
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
    for old in ticket["questions"]:  # the same open question is not asked twice
        if old["answer"] is None and old["text"] == text.strip() and old["options"] == list(options):
            return ticket, old
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
    text = text.strip()
    for opt in q["options"]:  # an option matches case-insensitively: store its spelling; else free text
        if opt.casefold() == text.casefold():
            text = opt
            break
    q["answer"], q["answered_by"], q["via"] = text, by, via
    w = ticket.get("waiting_on")
    if w and w.get("kind") == "question" and w.get("ref") == qid:
        ticket["waiting_on"] = None
        if ticket["status"] == "waiting":
            ticket["status"] = "active"
    add_history(ticket, by, f"Answered {qid}: {text}")
    save(root, ticket)
    return ticket, q


def waiting_value(kind: str, ref: str | None = None, until: str | None = None) -> dict:
    if kind not in WAIT_KINDS:
        raise Refused(f"A wait kind is one of: {', '.join(WAIT_KINDS)}.")
    if kind == "time":
        if not until:
            raise Refused("Waiting for a time needs until.")
        return {"kind": "time", "until": parse_time(until)}
    if not isinstance(ref, str) or not ref.strip() or len(ref.strip()) > 200:
        raise Refused(f"Waiting on {kind} needs a ref (1 to 200 characters).")
    return {"kind": kind, "ref": ref.strip()}


def wait(root: Path, tid: str, until: str | None, on: str | None, by: str, clear: bool = False) -> dict:
    """Generic waiting: the core records waiting_on and never promises that something wakes the ticket."""
    if clear:
        if until or on:
            raise Refused("--clear cannot be combined with --until or --on.")
        ticket = load(root, tid)
        ticket["waiting_on"] = None
        if ticket["status"] == "waiting":
            ticket["status"] = "active"
        add_history(ticket, by, "Wait cleared")
        save(root, ticket)
        return ticket
    if bool(until) == bool(on):
        raise Refused("Use exactly one of --until <time> or --on <kind>:<ref>.")
    ticket = load(root, tid)
    if until:
        w = waiting_value("time", until=until)
        note = f"Waiting until {w['until']}"
    else:
        kind, sep, ref = on.partition(":")
        if not sep or kind not in WAIT_KINDS or kind == "time":
            raise Refused("--on needs <kind>:<ref>, kind ticket, question or external. For a time: --until.")
        w = waiting_value(kind, ref)
        note = f"Waiting on {kind} {w['ref']}"
    ticket["waiting_on"] = w
    ticket["status"] = "waiting"
    add_history(ticket, by, note)
    save(root, ticket)
    return ticket


def patch(root: Path, tid: str, if_revision: int, data: str, by: str) -> dict:
    """Atomic change of several fields (title, status, waiting_on); refused when `revision` changed."""
    try:
        obj = json.loads(data)
    except ValueError:
        raise Refused('A patch is a JSON object, e.g. \'{"title": "New"}\'.') from None
    if not isinstance(obj, dict) or not obj:
        raise Refused("A patch is a JSON object with at least one field.")
    bad = sorted(set(obj) - set(PATCH_FIELDS))
    if bad:
        raise Refused(f"A patch can change only: {', '.join(PATCH_FIELDS)} (not {bad[0]}).")
    ticket = load_checked(root, tid, if_revision)
    if "title" in obj:
        t = obj["title"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > 200:
            raise Refused("A title needs 1 to 200 characters.")
        ticket["title"] = t.strip()
    w = obj.get("waiting_on")
    if "waiting_on" in obj and w is not None:
        if not isinstance(w, dict) or set(w) - {"kind", "until", "ref"}:
            raise Refused("waiting_on is {kind, until} or {kind, ref}, or null.")
        w = waiting_value(str(w.get("kind")), w.get("ref"), w.get("until"))
    status = obj.get("status", ticket["status"])
    if status not in STATUSES:
        raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
    if status == "done":
        _check_can_finish(ticket)
    if "waiting_on" in obj:
        ticket["waiting_on"] = w
    if status != "waiting":
        ticket["waiting_on"] = None
    old, ticket["status"] = ticket["status"], status
    note = f" (status {old} -> {status})" if old != status else ""
    add_history(ticket, by, "Patched " + ", ".join(sorted(obj)) + note)
    save(root, ticket)
    return ticket
