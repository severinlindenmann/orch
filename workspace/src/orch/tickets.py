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

from orch import procs
from orch.errors import Refused

STATUSES = ("open", "active", "waiting", "done", "dropped")
EVIDENCE_TYPES = ("pr", "commit", "file", "url", "command", "note")
WAIT_KINDS = ("time", "ticket", "question", "external")
PATCH_FIELDS = ("title", "status", "waiting_on", "owner", "due", "note", "summary")
VIA_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")
KIND_RE = re.compile(r"^(plain|[a-z][a-z0-9-]{1,31}:[a-z][a-z0-9-]{1,31})$")
DOING_STALE_SECONDS = 2 * 3600
MAX_PROOF_BYTES = 25 * 1024 * 1024
ROLES = ("result", "check", "support")
_WIN_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
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
        try:
            holder = mine.read_text(encoding="utf-8")
        except OSError:
            holder = ""
        # old enough, and its holder (if it named itself) is gone: a live or unverifiable holder keeps it
        if time.time() - mine.stat().st_mtime > 30 and (not holder.strip() or procs.owner_dead(holder)):
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
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(procs.own_token())
            break
        except (
            FileExistsError,
            PermissionError,
        ):  # Windows: a lock being deleted refuses with PermissionError
            if time.monotonic() > end:
                raise Refused(f"Ticket {tid} is busy (retried for 5 s). Try again.") from None
            try:
                stale = time.time() - lock.stat().st_mtime > 30
            except OSError:
                time.sleep(0.02)
                continue
            if stale and _break_stale(lock):
                continue
            if time.monotonic() > end:
                raise Refused(f"Ticket {tid} is busy (retried for 5 s). Try again.") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            procs.unlink(lock)


def revision(ticket: dict) -> int:
    r = ticket.get("revision", 0)
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 0 else 0


class Conflict(Refused):
    """An edit of something a person saw that changed meanwhile: exit 2 plus revision, changed_by, current."""

    def __init__(self, message: str, extra: dict):
        super().__init__(message)
        self.extra = extra


def _changed_by(ticket: dict) -> str:
    h = ticket.get("history") or [{}]
    return h[-1].get("by", "unknown")


def _conflict(ticket: dict, what: str, current) -> Conflict:
    by = _changed_by(ticket)
    h = (ticket.get("history") or [{}])[-1]
    when = f" at {h['at'][11:16]}" if h.get("at") else ""
    return Conflict(
        f"{what} was changed by {by}{when}.",
        {"revision": revision(ticket), "changed_by": by, "current": current},
    )


def _get(ticket: dict, path: str):
    """'checklist.c2.text' / 'title' / 'due': the value at a path (list items found by their id)."""
    cur = ticket
    for part in path.split("."):
        if isinstance(cur, list):
            cur = next((x for x in cur if isinstance(x, dict) and x.get("id") == part), None)
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _write(root: Path, ticket: dict) -> None:
    """Lock-free atomic write (tmp + os.replace). Callers hold the lock."""
    p = ticket_path(root, ticket["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(ticket, f, indent=2, ensure_ascii=False)
            f.write("\n")
        procs.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply_op(
    root: Path, tid: str, fn, *, expect: tuple[str, object] | None = None, if_revision: int | None = None
):
    """The one write path: load, change and write under ONE lock, so concurrent plain ops all land on the
    latest revision. `fn(ticket)` changes the dict (no subprocess, nothing slow) and returns a result.
    Only an edit of something a person saw passes `expect=(path, old value)` or `if_revision`;
    it is refused (Conflict, exit 2) when that changed. Returns (ticket, result)."""
    ticket_path(root, tid)  # id shape check, same friendly refusal
    with _locked(root, tid):
        ticket = load(root, tid)
        if if_revision is not None and revision(ticket) != if_revision:
            raise _conflict(ticket, f"Ticket {tid}", {k: ticket.get(k) for k in PATCH_FIELDS})
        if expect is not None and _get(ticket, expect[0]) != expect[1]:
            parent, _, leaf = expect[0].rpartition(".")
            raise _conflict(ticket, parent.split(".")[-1] or leaf, _get(ticket, parent or leaf))
        result = fn(ticket)
        ticket["revision"] = revision(ticket) + 1
        ticket["updated_at"] = now()
        _write(root, ticket)
        return ticket, result


def save(root: Path, ticket: dict) -> None:
    """Write a ticket loaded earlier: refused when the file changed since (create and tests use it;
    every op goes through apply_op instead)."""
    with _locked(root, ticket["id"]):
        p = ticket_path(root, ticket["id"])
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
        _write(root, ticket)


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


def add_history(ticket: dict, by: str, text: str, via: str = "cli") -> None:
    ticket["history"].append({"at": now(), "by": by, "via": via, "text": text})


def parse_ext_args(pairs: list[str] | None, schema_for=None) -> dict[str, dict]:
    """`--ext <addon>=<json object>` (repeatable) -> {addon: object}; checked like `orch ext set`."""
    out: dict[str, dict] = {}
    for pair in pairs or []:
        addon, _, data = pair.partition("=")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", addon):
            raise Refused("--ext needs <add-on>=<json>, the add-on key is lowercase letters, digits or -.")
        try:
            obj = json.loads(data)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            raise Refused("ext data must be a JSON object.")
        schema = schema_for(addon) if schema_for else None
        if schema is not None:
            validate_ext(schema, obj, addon)
        out[addon] = obj
    return out


def create(
    root: Path, title: str, by: str, parent: str | None = None, ext: dict[str, dict] | None = None
) -> dict:
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    if parent is not None:
        load(root, parent)  # the parent must exist (cycles are impossible: it is set only here)
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
        "history": [
            {"at": t, "by": by, "via": "cli", "text": "Created" + (f" under {parent}" if parent else "")}
        ],
    }
    if parent is not None:
        ticket["parent"] = parent
    if ext:  # add-on data in the same write as the ticket (no half-made ticket)
        ticket["ext"] = ext
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

    def op(ticket):
        if status == "done":
            _check_can_finish(ticket)
        if status != "waiting":
            ticket["waiting_on"] = None
        old = ticket["status"]
        ticket["status"] = status
        if old != status:
            add_history(ticket, by, f"Status {old} -> {status}")

    return apply_op(root, tid, op)[0]


# ---------------------------------------------------------------- plain fields (owner, due, note, summary)


def clean_field(key: str, value):
    """Validate owner, due, note or summary (None or empty clears it); returns the value to store."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise Refused(f"{key} must be text.")
    v = value.strip()
    if key == "owner" and len(v) > 64:
        raise Refused("An owner is at most 64 characters.")
    if key == "note" and len(v) > 2000:
        raise Refused("A note is at most 2000 characters.")
    if key == "summary" and len(v) > 200:
        raise Refused("A summary is at most 200 characters.")
    if key == "due":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise Refused("due must be a date like 2026-11-10.") from None
    return v


def _set_field(ticket: dict, key: str, value) -> None:
    v = clean_field(key, value)
    if v is None:
        ticket.pop(key, None)
    else:
        ticket[key] = v


def edit(
    root: Path,
    tid: str,
    title: str | None,
    by: str,
    fields: dict | None = None,
    if_revision: int | None = None,
) -> dict:
    """Rename and/or set owner, due, note (`fields`)."""
    if title is not None:
        title = title.strip()
        if not title or len(title) > 200:
            raise Refused("A title needs 1 to 200 characters.")
    fields = fields or {}
    for k, v in fields.items():
        clean_field(k, v)

    def op(ticket):
        if title is not None:
            ticket["title"] = title
            add_history(ticket, by, "Title changed")
        for k, v in fields.items():
            _set_field(ticket, k, v)
        if fields:
            add_history(ticket, by, "Edited " + ", ".join(sorted(fields)))

    return apply_op(root, tid, op, if_revision=if_revision)[0]


def set_summary(root: Path, tid: str, text: str, by: str) -> dict:
    """No history line: it would double the history on every run."""
    clean_field("summary", text)
    return apply_op(root, tid, lambda t: _set_field(t, "summary", text))[0]


def _next_id(items: list[dict], prefix: str) -> str:
    nums = [int(i["id"][1:]) for i in items if re.fullmatch(prefix + r"[0-9]+", str(i.get("id", "")))]
    return f"{prefix}{max(nums, default=0) + 1}"


# ---------------------------------------------------------------- checklist


def _item(ticket: dict, cid: str) -> dict:
    item = next((c for c in ticket["checklist"] if c["id"] == cid), None)
    if item is None:
        raise Refused(
            f"Ticket {ticket['id']} has no check {cid}. "
            f"Run `orch ticket show {ticket['id']}` to see its checks."
        )
    return item


def proof_label(ev: dict) -> str:
    """Short name of one piece of proof: title, else file name, else the ref; plus its result text."""
    if ev.get("title"):
        label = str(ev["title"])
    elif ev.get("type") == "file":
        label = str(ev.get("ref", "")).replace("\\", "/").rsplit("/", 1)[-1]
    else:
        label = str(ev.get("ref", ""))
    if ev.get("text"):
        label += f" ({ev['text']})" if ev.get("type") == "file" else f" · {ev['text']}"
    return label


def check_add(root: Path, tid: str, text: str, by: str) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A checklist item needs text.")

    def op(ticket):
        item = {"id": _next_id(ticket["checklist"], "c"), "text": text.strip(), "done": False, "evidence": []}
        ticket["checklist"].append(item)
        add_history(ticket, by, f"Added check {item['id']}")
        return item

    return apply_op(root, tid, op)


def parse_evidence(raw: str) -> dict:
    try:
        ev = json.loads(raw)
    except ValueError:
        raise Refused('Evidence must be JSON, e.g. \'{"type":"pr","ref":"PR #88"}\'.') from None
    if not isinstance(ev, dict) or ev.get("type") not in EVIDENCE_TYPES:
        raise Refused(f"Evidence type must be one of: {', '.join(EVIDENCE_TYPES)}.")
    if not isinstance(ev.get("ref"), str) or not ev["ref"].strip():
        raise Refused("Evidence needs a ref (PR, commit, file, URL, command or note text).")
    if "role" in ev and ev["role"] not in ROLES:
        raise Refused(f"A proof role is one of: {', '.join(ROLES)}.")
    if "text" in ev and not isinstance(ev["text"], str):
        raise Refused("Evidence text must be a string.")
    return ev


def _clear_doing(item: dict) -> None:
    for k in ("state", "by", "at"):
        item.pop(k, None)


def check_done(root: Path, tid: str, cid: str, evidence: list[str], by: str) -> tuple[dict, dict]:
    ticket = load(root, tid)  # a missing ticket is reported before anything else
    if not evidence:
        raise Refused(
            "A check is done only with proof. Say what shows it, for example "
            f'`orch check done {tid} {cid} --command "pytest -q"` or `--note "what you saw"` '
            "(also --pr, --commit, --file, --url)."
        )
    evs = [parse_evidence(e) for e in evidence]
    _item(ticket, cid)

    def op(t):
        item = _item(t, cid)
        for ev in evs:
            ev.setdefault("by", by)
            ev.setdefault("at", now())
        item["evidence"].extend(evs)
        item["done"] = True
        _clear_doing(item)
        add_history(t, by, f"Check {cid} done")
        return item

    return apply_op(root, tid, op)


def check_exists(root: Path, tid: str, cid: str) -> None:
    _item(load(root, tid), cid)


def check_edit(
    root: Path, tid: str, cid: str, text: str, by: str, if_revision: int | None = None, was: str | None = None
) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A checklist item needs text.")

    def op(t):
        item = _item(t, cid)
        item["text"] = text.strip()
        add_history(t, by, f"Renamed {cid}")
        return item

    expect = (f"checklist.{cid}.text", was) if was is not None else None
    return apply_op(root, tid, op, expect=expect, if_revision=if_revision)


def check_move(root: Path, tid: str, cid: str, after: str, by: str) -> tuple[dict, dict]:
    def op(t):
        item = _item(t, cid)
        _item(t, after)
        if after == cid:
            raise Refused("A check cannot follow itself.")
        t["checklist"].remove(item)
        idx = next(i for i, c in enumerate(t["checklist"]) if c["id"] == after)
        t["checklist"].insert(idx + 1, item)
        add_history(t, by, f"Moved {cid} after {after}")
        return item

    return apply_op(root, tid, op)


def check_remove(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Always allowed. The history line keeps the step text and its proof."""

    def op(t):
        item = _item(t, cid)
        t["checklist"].remove(item)
        proof = ", ".join(proof_label(e) for e in item.get("evidence", []))
        state = "was done" if item.get("done") else "was open"
        add_history(
            t, by, f"Removed step {cid} '{item['text']}' ({state}" + (f"; proof: {proof})" if proof else ")")
        )
        return item

    return apply_op(root, tid, op)


def check_reopen(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Open again; the old proof stays in the history line."""

    def op(t):
        item = _item(t, cid)
        proof = ", ".join(proof_label(e) for e in item.get("evidence", []))
        item["done"] = False
        item["evidence"] = []
        _clear_doing(item)
        add_history(t, by, f"Reopened {cid}" + (f" (old proof: {proof})" if proof else ""))
        return item

    return apply_op(root, tid, op)


def check_start(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Mark a step as being worked on; the mark on any other step goes."""

    def op(t):
        item = _item(t, cid)
        if item.get("done"):
            raise Refused(f"{cid} is already done. Reopen it first: orch check reopen {tid} {cid}")
        for c in t["checklist"]:
            _clear_doing(c)
        item.update({"state": "doing", "by": by, "at": now()})
        return item

    return apply_op(root, tid, op)


def check_stop(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    def op(t):
        item = _item(t, cid)
        _clear_doing(item)
        return item

    return apply_op(root, tid, op)


def doing_stale(root: Path, ticket: dict, item: dict, at: float | None = None) -> bool:
    """A 'doing' mark that is older than 2 h, or while a run record exists without a live process."""
    try:
        age = (at or time.time()) - datetime.strptime(item["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        ).timestamp()
    except (KeyError, ValueError):
        return True
    if age > DOING_STALE_SECONDS:
        return True
    if not _ID_RE.match(str(ticket.get("id", ""))):
        return False  # never build a path from anything that is not a ticket id
    rec = root / ".orch" / "run" / "tickets" / f"{ticket['id']}.json"
    if rec.is_file():
        from orch import services

        try:
            pid = json.loads(rec.read_text(encoding="utf-8")).get("pid")
        except (OSError, ValueError, AttributeError):
            return False
        return not services.pid_alive(pid)
    return False


def log(root: Path, tid: str, text: str, by: str) -> dict:
    if not text.strip():
        raise Refused("A history entry needs text.")
    return apply_op(root, tid, lambda t: add_history(t, by, text.strip()))[0]


def link_add(root: Path, tid: str, type_: str, url: str, title: str | None, by: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{1,32}", type_):
        raise Refused("A link type is lowercase letters, digits and dashes, e.g. github, jira, teams.")
    if not url.strip():
        raise Refused("A link needs a url.")

    def op(t):
        link = {"type": type_, "url": url.strip()}
        if title:
            link["title"] = title
        t["links"].append(link)
        add_history(t, by, f"Linked {title or type_}")

    return apply_op(root, tid, op)[0]


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

    def op(ticket):
        ext = ticket.setdefault("ext", {})
        cur = ext.get(addon)
        merged = {**cur, **obj} if isinstance(cur, dict) else obj  # keep fields this call does not mention
        if schema is not None:
            validate_ext(schema, merged, addon)  # small schema check; no subprocess
        ext[addon] = merged
        add_history(ticket, by, f"Set ext.{addon}")

    return apply_op(root, tid, op, if_revision=if_revision)[0]


def ask(
    root: Path,
    tid: str,
    text: str,
    options: list[str],
    recommended: str | None,
    by: str,
    kind: str | None = None,
    action: str | None = None,
    check: str | None = None,
) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A question needs text.")
    if recommended is not None and options and recommended not in options:
        raise Refused("The recommended answer must be one of the options.")
    if kind is not None and not KIND_RE.fullmatch(kind):
        raise Refused("A question kind is plain or <add-on>:<name>, lowercase.")
    act = None
    if action is not None:
        try:
            act = json.loads(action)
        except ValueError:
            act = None
        if not isinstance(act, dict):
            raise Refused("--action must be a JSON object.")

    def op(ticket):
        for old in ticket["questions"]:  # the same open question is not asked twice
            if old["answer"] is None and old["text"] == text.strip() and old["options"] == list(options):
                return old
        if check is not None:
            _item(ticket, check)
        q = {
            "id": _next_id(ticket["questions"], "q"),
            "text": text.strip(),
            "options": list(options),
            "recommended": recommended,
            "answer": None,
            "answered_by": None,
            "via": None,
        }
        if kind is not None:
            q["kind"] = kind
        if act is not None:
            q["action"] = act
        if check is not None:
            q["check"] = check
        ticket["questions"].append(q)
        ticket["status"] = "waiting"
        ticket["waiting_on"] = {"kind": "question", "ref": q["id"]}
        add_history(ticket, by, f"Asked {q['id']}, waiting")
        return q

    return apply_op(root, tid, op)


def answer(root: Path, tid: str, qid: str, text: str, by: str, via: str) -> tuple[dict, dict]:
    if not VIA_RE.fullmatch(via):
        raise Refused("via must be a short word (a-z, 0-9, -), e.g. cli or dashboard.")
    if not text.strip():
        raise Refused("An answer needs text.")
    text = text.strip()

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}.")
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered.")
        ans = text
        for opt in q["options"]:  # an option matches case-insensitively: store its spelling; else free text
            if opt.casefold() == ans.casefold():
                ans = opt
                break
        q["answer"], q["answered_by"], q["via"] = ans, by, via
        w = ticket.get("waiting_on")
        if w and w.get("kind") == "question" and w.get("ref") == qid:
            ticket["waiting_on"] = None
            if ticket["status"] == "waiting":
                ticket["status"] = "active"
        add_history(ticket, by, f"Answered {qid}: {ans}", via)
        return q

    return apply_op(root, tid, op)


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

        def op(ticket):
            ticket["waiting_on"] = None
            if ticket["status"] == "waiting":
                ticket["status"] = "active"
            add_history(ticket, by, "Wait cleared")

        return apply_op(root, tid, op)[0]
    if bool(until) == bool(on):
        raise Refused("Use exactly one of --until <time> or --on <kind>:<ref>.")
    if until:
        w = waiting_value("time", until=until)
        note = f"Waiting until {w['until']}"
    else:
        kind, sep, ref = on.partition(":")
        if not sep or kind not in WAIT_KINDS or kind == "time":
            raise Refused("--on needs <kind>:<ref>, kind ticket, question or external. For a time: --until.")
        w = waiting_value(kind, ref)
        note = f"Waiting on {kind} {w['ref']}"

    def op2(ticket):
        ticket["waiting_on"] = w
        ticket["status"] = "waiting"
        add_history(ticket, by, note)

    load(root, tid)
    return apply_op(root, tid, op2)[0]


def patch(root: Path, tid: str, if_revision: int, data: str, by: str) -> dict:
    """Atomic change of several fields; refused (exit 2 + current values) when `revision` changed."""
    try:
        obj = json.loads(data)
    except ValueError:
        raise Refused('A patch is a JSON object, e.g. \'{"title": "New"}\'.') from None
    if not isinstance(obj, dict) or not obj:
        raise Refused("A patch is a JSON object with at least one field.")
    bad = sorted(set(obj) - set(PATCH_FIELDS))
    if bad:
        raise Refused(f"A patch can change only: {', '.join(PATCH_FIELDS)} (not {bad[0]}).")
    if "title" in obj:
        t = obj["title"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > 200:
            raise Refused("A title needs 1 to 200 characters.")
    for k in ("owner", "due", "note", "summary"):
        if k in obj:
            clean_field(k, obj[k])
    w = obj.get("waiting_on")
    if "waiting_on" in obj and w is not None:
        if not isinstance(w, dict) or set(w) - {"kind", "until", "ref"}:
            raise Refused("waiting_on is {kind, until} or {kind, ref}, or null.")
        w = waiting_value(str(w.get("kind")), w.get("ref"), w.get("until"))

    def op(ticket):
        if "title" in obj:
            ticket["title"] = obj["title"].strip()
        status = obj.get("status", ticket["status"])
        if status not in STATUSES:
            raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
        if status == "done":
            _check_can_finish(ticket)
        for k in ("owner", "due", "note", "summary"):
            if k in obj:
                _set_field(ticket, k, obj[k])
        if "waiting_on" in obj:
            ticket["waiting_on"] = w
        if status != "waiting":
            ticket["waiting_on"] = None
        old, ticket["status"] = ticket["status"], status
        note = f" (status {old} -> {status})" if old != status else ""
        add_history(ticket, by, "Patched " + ", ".join(sorted(obj)) + note)

    return apply_op(root, tid, op, if_revision=if_revision)[0]


# ---------------------------------------------------------------- agent sessions (used by the run lane)


def record_session(root: Path, tid: str, agent: str, sid: str, host: str) -> dict:
    """Remember the agent session for this agent and machine (updates last_used when it is known)."""

    def op(t):
        sessions = t.setdefault("sessions", [])
        for s in sessions:
            if s.get("agent") == agent and s.get("host") == host:
                s["id"], s["last_used"] = sid, now()
                break
        else:
            sessions.append({"agent": agent, "id": sid, "host": host, "last_used": now()})
            if len(sessions) > 32:
                sessions.sort(key=lambda s: s.get("last_used", ""))
                del sessions[0 : len(sessions) - 32]

    return apply_op(root, tid, op)[0]


def sessions_for(ticket: dict, agent: str, host: str) -> str | None:
    """The session id to resume for this agent on this machine, else None. No age limit."""
    for s in ticket.get("sessions") or []:
        if s.get("agent") == agent and s.get("host") == host:
            return s.get("id")
    return None


# ---------------------------------------------------------------- proof files


def _proof_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .") or "file"
    if n.split(".")[0].lower() in _WIN_RESERVED:
        n = "_" + n
    return n[:120]


def _size_text(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{max(round(n / 1024), 1)} KB"


def _too_big(name: str) -> str:
    return f"{name} is too big. A proof file can be at most 25 MB. Use --url or --note."


def attach_file(root: Path, tid: str, path: str, title: str | None, role: str | None) -> dict:
    """Copy a workspace file into .orch/tickets/<tid>/evidence/ and return the evidence entry for it.
    Only regular files inside the workspace, no link followed anywhere on the way, at most 25 MB."""
    load(root, tid)
    if role is not None and role not in ROLES:
        raise Refused(f"A proof role is one of: {', '.join(ROLES)}.")
    if title is not None and not 1 <= len(title.strip()) <= 120:
        raise Refused("A proof title needs 1 to 120 characters.")
    base = Path(os.path.realpath(root))
    given = Path(os.path.abspath(os.path.expanduser(path)))
    rel = None
    for b in (Path(os.path.abspath(root)), base):
        try:
            rel = given.relative_to(b)
            break
        except ValueError:
            continue
    inside = Refused("proof files must be inside this workspace.")
    if rel is None or ".." in rel.parts:
        raise inside
    cur = base
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise Refused("proof files cannot be links. Give the real file.")
    low = tuple(x.lower() for x in rel.parts)
    if low[:2] == (".orch", "secrets") or ".git" in low:
        raise inside
    if not cur.exists():
        raise Refused(f"{path} doesn't exist.")
    if not cur.is_file():
        raise Refused(f"{path} is not a file.")
    cur_src = cur
    size = cur_src.stat().st_size
    if size > MAX_PROOF_BYTES:
        raise Refused(
            f"{cur_src.name} is {_size_text(size)}. A proof file can be at most 25 MB. Use --url or --note."
        )
    dest_dir = base / ".orch" / "tickets" / tid / "evidence"
    cur = base
    for part in (".orch", "tickets", tid, "evidence"):
        cur = cur / part
        if cur.is_symlink():
            raise Refused("The proof folder of this ticket is a link. orch will not copy into it.")
        if cur.exists() and not cur.is_dir():
            raise Refused("The proof folder of this ticket is blocked by a file. Move that file away.")
        if not cur.exists():
            cur.mkdir()
    real_dir = Path(os.path.realpath(dest_dir))
    if real_dir != dest_dir or not str(real_dir).startswith(str(base / ".orch" / "tickets") + os.sep):
        raise Refused("The proof folder of this ticket is not inside this workspace.")
    name = _proof_name(cur_src.name)
    dest, n = dest_dir / name, 1
    while True:
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
            break
        except FileExistsError:
            n += 1
            stem, dot, ext = name.rpartition(".")
            dest = dest_dir / (f"{stem}-{n}.{ext}" if dot and stem else f"{name}-{n}")
    try:
        src_fd = os.open(cur_src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        os.close(fd)
        os.unlink(dest)
        raise Refused("proof files cannot be links. Give the real file.") from None
    try:
        with os.fdopen(src_fd, "rb") as src, os.fdopen(fd, "wb") as out:
            if os.fstat(src.fileno()).st_size > MAX_PROOF_BYTES:
                raise Refused(_too_big(cur_src.name))
            data = src.read(MAX_PROOF_BYTES + 1)  # bounded: a file that grows while we copy is refused too
            if len(data) > MAX_PROOF_BYTES:
                raise Refused(_too_big(cur_src.name))
            out.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(dest)
        raise
    ev = {"type": "file", "ref": dest.relative_to(base).as_posix(), "text": _size_text(size)}
    if title:
        ev["title"] = title.strip()
    if role:
        ev["role"] = role
    return ev


def proof_present(root: Path, ev: dict) -> bool:
    """False for a copied proof file that is not on this computer (evidence/ is not in git)."""
    ref = str(ev.get("ref", ""))
    if ev.get("type") != "file" or not ref.startswith(".orch/tickets/") or "/evidence/" not in ref:
        return True
    return (root / ref).is_file()


# ---------------------------------------------------------------- sub-tickets


CLOSED = ("done", "dropped")


def children_of(all_: list[dict], tid: str) -> list[dict]:
    return [t for t in all_ if t.get("parent") == tid]


def children_counts(all_: list[dict], tid: str) -> dict:
    kids = children_of(all_, tid)
    closed = sum(1 for k in kids if k.get("status") in CLOSED)
    return {"total": len(kids), "closed": closed, "open": len(kids) - closed}


def open_children(root: Path, tid: str) -> list[dict]:
    return [k for k in children_of(list_all(root), tid) if k.get("status") not in CLOSED]
