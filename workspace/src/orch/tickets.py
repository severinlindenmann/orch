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
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from orch import config, procs, term
from orch.errors import Refused

STATUSES = ("open", "active", "waiting", "ready", "review", "done", "dropped")
STATUS_WORDS = {
    "open": "Backlog",
    "ready": "Ready",
    "active": "Working",
    "waiting": "Waiting",
    "review": "Review",
    "done": "Done",
    "dropped": "Dropped",
}
OPEN_STATUSES = tuple(s for s in STATUS_WORDS if s not in ("done", "dropped"))
REVIEW_MESSAGE = "Moved to Review, not Done. A person marks a ticket Done."
EVIDENCE_TYPES = ("pr", "commit", "file", "url", "command", "note")
WAIT_KINDS = ("time", "ticket", "question", "external")
PATCH_FIELDS = ("title", "status", "waiting_on", "owner", "due", "note", "done_when", "summary")
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
    if term.is_terminal(sys.stdin):
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
    if not _ID_RE.fullmatch(tid):
        raise Refused(f"Ticket {tid} doesn't exist. Run `orch ticket list` to see your tickets.")
    return tickets_dir(root) / f"{tid}.json"


def new_id(root: Path) -> str:
    for _ in range(100):
        tid = "t_" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not ticket_path(root, tid).exists():
            return tid
    raise Refused("Could not find a free ticket id.")


_KEY_RE = re.compile(r"^([A-Za-z0-9]{2,4})-([1-9][0-9]{0,8})$")


def resolve(root: Path, ref):
    """The one place a ticket key (DM1-12, any case) becomes the ticket id. Anything else is returned as it
    is (an id, or a word the command refuses later)."""
    if not isinstance(ref, str) or not _KEY_RE.match(ref.strip()):
        return ref
    want = ref.strip().upper()
    for t in list_all(root):
        if str(t.get("key", "")).upper() == want:
            return t["id"]
    raise Refused(f"Ticket {ref} doesn't exist. Run `orch ticket list` to see your tickets.")


def _counter_path(root: Path) -> Path:
    return root / ".orch" / "ticket-counter.json"


def next_key(root: Path) -> str:
    """<code>-<n> for a new ticket. n is 1 + the highest number handed out (counter file or any ticket's key),
    written to the counter under one workspace lock, so no two tickets share a number and none is reused."""
    from orch import config

    code = config.workspace_code(root) or config.set_code(root, config.suggest_code(root.resolve().name))
    with _locked(root, "key"):
        p = _counter_path(root)
        try:
            last = int(json.loads(p.read_text(encoding="utf-8")).get("last", 0))
        except (OSError, ValueError, AttributeError, TypeError):
            last = 0
        for t in list_all(root):
            m = _KEY_RE.match(str(t.get("key", "")))
            if m:
                last = max(last, int(m.group(2)))
        n = last + 1
        tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps({"last": n}) + "\n", encoding="utf-8")
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)
    return f"{code}-{n}"


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


NO_WRITE = object()  # an op returns this when it changed nothing


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
        if result is NO_WRITE:  # the op found nothing to change: no new revision, no history
            return ticket, None
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


def list_all(root: Path, include_general: bool = False) -> list[dict]:
    """Every ticket by creation time. The hidden General ticket of the phone conversation (flag
    `general: true`) is left out unless include_general: it is not a ticket anyone lists, counts or closes."""
    d = tickets_dir(root)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("t_*.json")):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if include_general or not (isinstance(t, dict) and t.get("general") is True):
                out.append(t)
    out.sort(key=lambda t: t.get("created_at", ""))
    return out


def is_general(root: Path, tid: str) -> bool:
    """True for the hidden General ticket (reads one file; a missing or unreadable ticket is not General)."""
    try:
        return json.loads(ticket_path(root, tid).read_text(encoding="utf-8")).get("general") is True
    except (OSError, ValueError, Refused, AttributeError):
        return False


def general_id(root: Path) -> str | None:
    """The id of this workspace's hidden General ticket, or None before the first General text."""
    for t in list_all(root, include_general=True):
        if isinstance(t, dict) and t.get("general") is True:
            return t["id"]
    return None


def ensure_general(root: Path, by: str) -> str:
    """The General ticket (flag general: true, no display key so no number is used up), made once."""
    if tid := general_id(root):
        return tid
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "title": "General",
        "general": True,
        "status": "open",
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [{"at": t, "by": by, "via": "cli", "text": "Created", "chat_message": False}],
    }
    save(root, ticket)
    return ticket["id"]


_FIELD_WORDS = {
    "title": "title",
    "owner": "owner",
    "due": "due date",
    "note": "note",
    "done_when": "done criteria",
    "summary": "summary",
    "status": "status",
    "waiting_on": "wait",
}


def _fields_text(raw: str) -> str | None:
    keys = [k.strip() for k in raw.split(",")]
    if any(k not in _FIELD_WORDS for k in keys):
        return None  # free text someone logged by hand: shown as written
    words = [_FIELD_WORDS[k] for k in keys]
    return "the " + (", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0])


def history_line(text: str, checklist: list[dict] | None = None) -> str:
    """Plain words for the history lines orch itself writes (what a person reads in the CLI). The stored text
    stays as it is; anything else, such as a line someone logged by hand, is shown as written.
    checklist: the ticket's tasks, so a task line can say what the task was."""
    t = text.strip()

    def task(cid: str) -> str:
        item = next((c for c in checklist or [] if c.get("id") == cid), None)
        return f": {item['text']}" if item and item.get("text") else ""

    def addon(key: str) -> str:
        return key.replace("-", " ").capitalize()

    if re.fullmatch(r"Asked q\d+, waiting", t):
        return "Asked a question"
    if m := re.fullmatch(r"Answered q\d+: (.*)", t, re.DOTALL):
        return f"Answered a question: {m.group(1)}"
    if m := re.fullmatch(r"Status (\w+) -> (\w+)", t):
        return f"Moved to {STATUS_WORDS.get(m.group(2), m.group(2))}"
    if m := re.fullmatch(r"Edited ([a-z_, ]+)", t):
        if (f := _fields_text(m.group(1))) is not None:
            return "Changed " + f
    if m := re.fullmatch(r"Patched ([a-z_, ]+?)(?: \(status \w+ -> (\w+)\))?", t):
        if (f := _fields_text(m.group(1))) is not None:
            return (
                "Changed " + f + (f" (now {STATUS_WORDS.get(m.group(2), m.group(2))})" if m.group(2) else "")
            )
    if m := re.fullmatch(r"Added check (c\d+)", t):
        return "Added a task" + task(m.group(1))
    if m := re.fullmatch(r"Check (c\d+) done", t):
        return "Finished a task" + task(m.group(1))
    if m := re.fullmatch(r"Set ext\.([a-z][a-z0-9-]*)", t):
        return f"Updated {addon(m.group(1))} settings"
    if m := re.fullmatch(r"Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?", t):
        return f"Removed {addon(m.group(1))} settings"
    return t


def _env_via() -> str:
    """Where a change comes from: ORCH_VIA (a page that runs orch sets it, e.g. dashboard), else cli."""
    v = os.environ.get("ORCH_VIA", "")
    return v if re.fullmatch(r"[a-z][a-z0-9-]{1,23}", v) else "cli"


def add_history(ticket: dict, by: str, text: str, via: str | None = None, chat: bool = False) -> None:
    """chat=True marks a real Chat or group message (`chat_message: true`): the only lines the Chat shows."""
    entry = {"at": now(), "by": by, "via": via or _env_via(), "text": text, "chat_message": chat}
    ticket["history"].append(entry)


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
    root: Path,
    title: str,
    by: str,
    parent: str | None = None,
    ext: dict[str, dict] | None = None,
    fields: dict | None = None,
) -> dict:
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    if parent is not None:
        load(root, parent)  # the parent must exist (cycles are impossible: it is set only here)
    fields = fields or {}
    for k, v in fields.items():
        clean_field(k, v)
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "key": next_key(root),
        "title": title,
        "status": "open",
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [
            {
                "at": t,
                "by": by,
                "via": _env_via(),
                "text": "Created" + (f" under {parent}" if parent else ""),
                "chat_message": False,
            }
        ],
    }
    if parent is not None:
        ticket["parent"] = parent
    for k, v in fields.items():  # owner, due, note, done_when: part of the one "Created" line
        _set_field(ticket, k, v)
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


def _open_questions(ticket: dict) -> list[str]:
    """Plain questions nobody answered yet (an add-on's own questions are its business)."""
    return [
        q["id"]
        for q in ticket.get("questions") or []
        if q.get("answer") is None and q.get("kind") in (None, "plain")
    ]


def _check_not_too_early(root: Path, ticket: dict) -> None:
    """An agent never finishes a ticket while its own question is open or a person's new input has not
    reached it yet: that work is not done (round 8 Nov: "never close a ticket too early")."""
    open_ = _open_questions(ticket)
    if open_:
        raise Refused(f"Not done: {', '.join(open_)} is not answered yet. Wait for the answer.")
    from orch import runs  # runs imports tickets

    if any(i.get("via") not in ("start", "slots") for i in runs.undelivered(root, ticket["id"])):
        raise Refused("Not done: new input for this ticket has not reached you yet. Read it first.")


GENERAL_REFUSAL = "The Chat is not a ticket: it is never finished, dropped or reopened."
GENERAL_REFUSED = (
    "open",
    "review",
    "done",
    "dropped",
    "active",
)  # finish, reopen, Working; waiting and ready stay


def _finish_status(root: Path, ticket: dict, status: str, by: str) -> tuple[str, str]:
    if (
        ticket.get("general") is True and status in GENERAL_REFUSED
    ):  # the ONE status guard (agent, person, wrapper)
        raise Refused(GENERAL_REFUSAL)
    if agent_tool():  # an agent in the environment counts as an agent whatever --by says
        by = "agent:" + str(agent_tool())
    if status in ("done", "review") and by.startswith("agent:") and ticket["status"] != status:
        _check_not_too_early(root, ticket)
    if status == "done" and by.startswith("agent:"):
        _check_can_finish(ticket)
        if not config.agents_may_finish(root):
            add_history(ticket, by, f"{by} finished the work and moved it to Review")
            return "review", by
    return status, by


def ask_for_changes(root: Path, tid: str, text: str, by: str) -> dict:
    """A person sends a Review ticket back with a note, in ONE step: the note becomes a task, the ticket is
    Ready (Working only when a run claims it) and the note is queued as the person's own input, so the
    automation host starts exactly one run for it (a person's pending input is what starts runs; #287)."""
    if not by.startswith("human:") or agent_tool():
        raise Refused("Only a person can ask for changes.")
    note = (text or "").strip()
    if not note:
        raise Refused("Say what should change.")
    if len(note) > 2000:
        raise Refused("A note for changes is at most 2000 characters.")

    def op(ticket):
        if ticket["status"] != "review":
            raise Refused("This ticket is not waiting for your review.")
        ticket["checklist"].append(
            {
                "id": _next_id(ticket["checklist"], "c"),
                "text": "Change: " + note,
                "done": False,
                "evidence": [],
            }
        )
        ticket["status"] = "ready"  # any wait the ticket has is not this review's: left as it is
        add_history(ticket, by, "Asked for changes: " + note[:200])

    from orch import runs  # runs imports tickets

    if load(root, tid)["status"] != "review":
        raise Refused("This ticket is not waiting for your review.")
    # Queue the note first, then commit the ticket: a failure of either leaves nothing half done.
    item = runs.pending_add(root, tid, by, "message", note, _env_via())
    try:
        return apply_op(root, tid, op)[0]
    except BaseException:
        runs.pending_discard(root, tid, item["id"])
        raise


def mark_working(root: Path, tid: str, by: str, agent_label: str) -> None:
    def op(ticket):
        if ticket.get("general") is True:
            return NO_WRITE
        was_started = ticket.get("started") is True
        ticket["started"] = True
        w = ticket.get("waiting_on") or {}
        if ticket["status"] not in ("open", "ready", "review") and not (
            ticket["status"] == "waiting" and w.get("start") is True
        ):  # a start that was waiting for a sign-in (wait_for_start) is Working again
            return NO_WRITE if was_started else None
        ticket["status"] = "active"
        ticket["waiting_on"] = None
        add_history(ticket, by, f"{agent_label} started")

    try:
        apply_op(root, tid, op)
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise


STOPPED_TEXT = "The agent stopped before the work was finished. Continue goes on where it left off."


def agent_stopped(root: Path, tid: str, by: str, still_running=None, say: bool = True) -> bool:
    """No agent works on the ticket any more: a Working ticket is Ready again (Working is shown only while
    an agent runs). still_running() is asked under the ticket lock, so a run that started meanwhile wins.
    Returns True when the ticket was moved."""

    def op(ticket):
        if ticket.get("general") is True:
            return NO_WRITE
        if ticket["status"] != "active" or (still_running is not None and still_running()):
            return NO_WRITE
        ticket["status"] = "ready"
        ticket["waiting_on"] = None
        if say:
            add_history(ticket, by, STOPPED_TEXT)
        return True

    try:
        return apply_op(root, tid, op)[1] is True
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise
        return False


def wait_for_start(root: Path, tid: str, reason: str, by: str) -> None:
    """The agent is not up (it needs a sign-in, or failed to start): the ticket is Waiting with that reason,
    never Working. Only a Working ticket is moved."""

    def op(ticket):
        if ticket["status"] != "active":
            return NO_WRITE
        ticket["status"] = "waiting"
        ref = (reason.strip() or "The agent did not start")[:200]
        ticket["waiting_on"] = {"kind": "external", "ref": ref, "start": True}
        add_history(ticket, by, "Waiting: the agent is not up")

    try:
        apply_op(root, tid, op)
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise


def resume_after_start_wait(root: Path, tid: str, by: str) -> None:
    """The agent is up now: a ticket that wait_for_start put in Waiting is Working again."""

    def op(ticket):
        if ticket["status"] != "waiting" or (ticket.get("waiting_on") or {}).get("start") is not True:
            return NO_WRITE
        ticket["status"] = "active"
        ticket["waiting_on"] = None
        add_history(ticket, by, "The agent is up")

    try:
        apply_op(root, tid, op)
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise


def set_status(root: Path, tid: str, status: str, by: str) -> dict:
    if status not in STATUSES:
        raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")

    def op(ticket):
        target, actor = _finish_status(root, ticket, status, by)
        if target in ("open", "ready") and not actor.startswith("agent:"):
            ticket.pop("started", None)
        if target != "waiting":
            ticket["waiting_on"] = None
        elif isinstance(ticket.get("waiting_on"), dict):
            ticket["waiting_on"].pop("start", None)  # a person's choice: no hook turns it back
        old = ticket["status"]
        ticket["status"] = target
        if old != target and target == status:
            add_history(ticket, actor, f"Status {old} -> {target}")

    return apply_op(root, tid, op)[0]


# ------------------------------------------------------- plain fields (owner, due, note, done_when, summary)


def clean_field(key: str, value):
    """Validate a plain field (None or empty clears it); returns the value to store."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise Refused(f"{key} must be text.")
    v = value if key in ("note", "done_when") else value.strip()
    if key == "owner" and len(v) > 64:
        raise Refused("An owner is at most 64 characters.")
    if key == "note" and len(v) > 2000:
        raise Refused("A note is at most 2000 characters.")
    if key == "done_when" and len(v) > 2000:
        raise Refused("The done criteria are at most 2000 characters.")
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
    """Rename and/or set owner, due, note, done_when (`fields`)."""
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
    if "summary" in ev:
        if not isinstance(ev["summary"], str) or not 1 <= len(ev["summary"].strip()) <= 200:
            raise Refused("A proof summary is one line of 1 to 200 characters.")
        ev["summary"] = " ".join(ev["summary"].split())
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


def ref_add(
    root: Path, tid: str, target: str, by: str, kind: str | None = None, title: str | None = None, kinds=()
) -> tuple[dict, dict, bool]:
    from orch import refs

    t = load(root, tid)
    value = refs.detect(root, t["id"], target, kind, title, kinds)
    identity = {k: v for k, v in value.items() if k != "title" and (k != "kind" or "url" not in value)}
    added = True
    result = None

    def op(ticket):
        nonlocal added, result
        values = refs.local_refs(root, ticket["id"]) if value.get("local") else ticket["refs"]
        result = next((r for r in values if all(r.get(k) == v for k, v in identity.items())), None)
        if result is not None:
            added = False
            if value.get("kind") == "url" and kind is None:
                value["kind"] = result["kind"]
            if all(result.get(k) == v for k, v in value.items()):
                return NO_WRITE
            result.update(value)
            verb = "Changed reference"
        else:
            result = {**value, "at": now(), "by": by}
            values.append(result)
            verb = "Added reference"
        if value.get("local"):
            refs.write_local(root, ticket["id"], values)
            return NO_WRITE
        add_history(ticket, by, f"{verb} {refs.target(result)}")
        return result

    t, _ = apply_op(root, t["id"], op)
    return t, result, added


def ref_remove(root: Path, tid: str, target: str, by: str) -> tuple[dict, dict]:
    from orch import refs

    t = load(root, tid)
    wanted = None
    if not target.isdigit():
        try:
            wanted = refs.detect(root, t["id"], target, check_exists=False)
        except Refused:  # a file that became a link is refused by detect: match its stored text instead
            import posixpath

            text = target.replace("\\", "/")
            line = re.fullmatch(r"(.+):([0-9]+)", text)
            wanted = dict(path=posixpath.normpath(line[1] if line else text))
            if line:
                wanted["line"] = int(line[2])
    result = None

    def op(ticket):
        nonlocal result
        values = refs.numbered({"refs": ticket["refs"] + refs.local_refs(root, ticket["id"])})
        result = next(
            (
                r
                for n, r in values
                if isinstance(r, dict)
                and (
                    n == int(target)
                    if target.isdigit()
                    else all(r.get(k) == v for k, v in wanted.items() if k != "kind")
                )
            ),
            None,
        )
        if result is None:
            raise Refused(f"{ticket.get('key') or ticket['id']} has no reference {target}.")
        if result.get("local"):
            local = refs.local_refs(root, ticket["id"])
            local.remove(result)
            refs.write_local(root, ticket["id"], local)
            return NO_WRITE
        ticket["refs"].remove(result)
        add_history(ticket, by, f"Removed reference {refs.target(result)}")
        return result

    t, _ = apply_op(root, t["id"], op)
    return t, result


def merge_refresh(
    root: Path, tid: str, addon: str, out: dict, by: str, schema: dict | None
) -> tuple[dict, list]:
    """Merge what an add-on's refresh act printed: links matched by url change only title, status and thumb;
    ext only under the add-on's own name (checked with its schema). One history line per change.
    Returns (ticket, changes) with changes = [{what, url?, field, old, new}]."""
    from orch import refs

    if not isinstance(out, dict):
        raise Refused(f"The {addon} add-on did not say what to update.")
    upd = out.get("refs") or []
    ext = out.get("ext") or {}
    if not isinstance(upd, list) or not isinstance(ext, dict) or set(ext) - {addon}:
        raise Refused(f"The {addon} add-on may only update refs and ext.{addon}.")
    mine = ext.get(addon) or {}
    if not isinstance(mine, dict):
        raise Refused(f"The {addon} add-on sent ext.{addon} that is not an object.")

    def op(t):
        changes = []
        for u in upd:
            if not isinstance(u, dict) or not isinstance(u.get("url"), str):
                continue
            cur = next((ln for ln in t["refs"] if isinstance(ln, dict) and ln.get("url") == u["url"]), None)
            if cur is None:
                continue
            name = refs.one_line(cur.get("title") or refs.short_url(cur["url"]))
            for f in ("title", "status", "thumb"):
                v = u.get(f)
                if f not in u or v == cur.get(f):
                    continue
                if v is not None and not isinstance(v, str):
                    continue
                if f == "title" and v is not None:
                    v = refs.one_line(v) or None
                    if v == cur.get(f):
                        continue
                if f == "status" and v is not None and not refs.STATUS_RE.fullmatch(v):
                    continue
                if f == "thumb" and v is not None and not re.fullmatch(r"artifacts/[A-Za-z0-9_.-]{1,100}", v):
                    continue
                changes.append(
                    {"what": "link", "url": cur["url"], "name": name, "field": f, "old": cur.get(f), "new": v}
                )
                if v is None:
                    cur.pop(f, None)
                else:
                    cur[f] = v
        if mine:
            old = (t.get("ext") or {}).get(addon)
            old = old if isinstance(old, dict) else {}
            merged = {**old, **mine}
            if schema is not None:
                validate_ext(schema, merged, addon)
            for k, v in mine.items():
                if old.get(k) != v:
                    changes.append({"what": "ext", "name": k, "field": k, "old": old.get(k), "new": v})
            if merged != old:
                t.setdefault("ext", {})[addon] = merged
        if not changes:
            return NO_WRITE
        for c in changes:
            what = f"{c['name']} {c['field']}" if c["what"] == "link" else c["field"]
            old, new = (refs.one_line("-" if v in (None, "") else v, 120) for v in (c["old"], c["new"]))
            add_history(t, by, f"{addon} refresh: {what} {old} -> {new}")
        return changes

    t, changes = apply_op(root, tid, op)
    return t, changes or []


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


def ext_unset(
    root: Path,
    tid: str,
    target: str,
    by: str,
    if_revision: int | None = None,
    schema: dict | None = None,
) -> dict:
    """Drop ext.<addon> (target `addon`) or one key of it (`addon.key`). Nothing there: nothing written."""
    addon, _, key = target.partition(".")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", addon) or (
        key and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key)
    ):
        raise Refused(
            "Name the data as <add-on> or <add-on>.<key>; the add-on is lowercase letters, digits or -."
        )

    def op(ticket):
        cur = (ticket.get("ext") or {}).get(addon)
        if cur is None or (key and not (isinstance(cur, dict) and key in cur)):
            return NO_WRITE  # checked inside the lock, after the --if-revision check
        ext = ticket["ext"]
        if not key:
            del ext[addon]
            add_history(ticket, by, f"Removed ext.{addon}")
        else:
            rest = {k: v for k, v in cur.items() if k != key}
            # a schema's required fields may be gone with the key: that is only checked while data remains;
            # removing the last key just removes the add-on's data
            if rest and schema is not None:
                validate_ext(schema, rest, addon)
            if rest:
                ext[addon] = rest
            else:
                del ext[addon]
            add_history(ticket, by, f"Removed ext.{addon}.{key}")
        if not ext:
            del ticket["ext"]

    return apply_op(root, tid, op, if_revision=if_revision)[0]


_SECRET_FOLDER_RE = re.compile(r"\.orch[/\\]+secrets|\borch secrets\b|\bsecrets folder\b", re.I)
_SECRET_WORD = (
    r"(?:passwords?|passcodes?|passphrases?|passwort|passw\u00f6rter|kennwort|zugangsdaten|api[\s_-]?keys?"
    r"|(?:access|auth|bearer|login|api)[\s_-]?tokens?|tokens?|secrets?|private[\s_-]?keys?"
    r"|api[\s_-]?schl\u00fcssel|schl\u00fcssel|credentials?|login details)"
    r"(?![\s-]*(?:reset|protected|rotat|expir|set up))"
)
_GAP = r"(?:(?!rotat|expir|reset|protect|whether|set up)[^.?!\n]){0,40}?"
_HAND_OVER = (
    r"(?:give|send|paste|provide|enter|share|tell|upload|supply|attach|what's"
    r"|gib|schick\w*|sende\w*|teile\w*|nenne\w*|eingeben)"
)
_SECRET_ASK_RE = re.compile(r"\b" + _HAND_OVER + r"\b" + _GAP + r"\b" + _SECRET_WORD + r"\b", re.I)
_PAT_ASK_RE = re.compile(r"\b" + _HAND_OVER + r"\b" + _GAP + r"\bPAT\b", re.I)
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")
_MACHINE_VALUE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_MACHINE_KEYS = {"op", "run", "peer", "key", "id", "tid", "ticket"}
_REQUEST_RES = (
    re.compile(r"\bneed\s+(?:your|you to give|you to send)\b[^.?!\n]{0,20}?\b" + _SECRET_WORD + r"\b", re.I),
    re.compile(r"\byour\s+" + _SECRET_WORD + r"\s+please\b", re.I),
    re.compile(r"\breply\s+with\s+(?:your\s+|the\s+)?" + _SECRET_WORD + r"\b", re.I),
    re.compile(r"\bwhich\s+" + _SECRET_WORD + r"\s+(?:should|do)\s+i\s+use\b", re.I),
    re.compile(r"\bbrauche\s+(?:dein|deinen|ihr|ihren)\w*\s+" + _SECRET_WORD + r"\b", re.I),
)


def _labels(value, key: str = "") -> list[str]:
    """Every text of an add-on action (keys too), except the machine-only fields."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if str(k).lower() in _MACHINE_KEYS and isinstance(v, str) and _MACHINE_VALUE_RE.fullmatch(v):
                continue  # a machine-only token; natural language and nested data are still scanned
            out += [str(k), *_labels(v, str(k))]
        return out
    if isinstance(value, list):
        return [x for v in value for x in _labels(v, key)]
    return []


def _asks_for_secret(text: str) -> bool:
    """Light guard for `orch ask` (defence in depth; the skill text is the real control): the secrets
    folder, or asking a person to hand over a credential."""
    text = _INVISIBLE_RE.sub("", unicodedata.normalize("NFKC", text)).replace("\u2019", "'")
    return bool(
        _SECRET_FOLDER_RE.search(text)
        or _SECRET_ASK_RE.search(text)
        or _PAT_ASK_RE.search(text)
        or any(r.search(text) for r in _REQUEST_RES)
    )


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

    for part in (text, *options, *([recommended] if recommended else []), *_labels(act)):
        if _asks_for_secret(part):
            with contextlib.suppress(Exception):  # the attempt stays visible in the history
                apply_op(
                    root, tid, lambda t: add_history(t, by, "A question was refused: it asked for a secret.")
                )
            raise Refused(
                "A question must never ask for a password, token, API key or other credential, "
                "and never mention the secrets folder. Ask whether access is set up instead "
                "(for example: Is access to the service set up for this workspace?), "
                "and say in the ticket summary what is missing."
            )

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
    from orch import runs  # runs imports tickets

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
            still = _open_questions(ticket)
            if still:  # more questions wait: the ticket keeps waiting, on the oldest of them
                ticket["waiting_on"] = {"kind": "question", "ref": still[0]}
            else:
                ticket["waiting_on"] = None
                if ticket["status"] == "waiting":  # Working only while an agent runs; else Ready to go on
                    chat = ticket.get("general") is True  # the Chat ticket is never Working
                    ticket["status"] = "ready" if chat or not runs.running(root, tid) else "active"
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
    if "status" in obj:
        from orch import chat

        if chat.is_helper(root):
            raise Refused("The Chat helper does not change a ticket's status.")
    bad = sorted(set(obj) - set(PATCH_FIELDS))
    if bad:
        raise Refused(f"A patch can change only: {', '.join(PATCH_FIELDS)} (not {bad[0]}).")
    if "title" in obj:
        t = obj["title"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > 200:
            raise Refused("A title needs 1 to 200 characters.")
    for k in ("owner", "due", "note", "done_when", "summary"):
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
        actor = by
        if "status" in obj:
            status, actor = _finish_status(root, ticket, status, by)
            if status in ("open", "ready") and not actor.startswith("agent:"):
                ticket.pop("started", None)
        for k in ("owner", "due", "note", "done_when", "summary"):
            if k in obj:
                _set_field(ticket, k, obj[k])
        if "waiting_on" in obj:
            ticket["waiting_on"] = w
        if status != "waiting":
            ticket["waiting_on"] = None
        old, ticket["status"] = ticket["status"], status
        note = f" (status {old} -> {status})" if old != status else ""
        add_history(ticket, actor, "Patched " + ", ".join(sorted(obj)) + note)

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
    if n >= 1024:
        return f"{round(n / 1024)} KB"
    return f"{n} B"


def _too_big(name: str) -> str:
    return f"{name} is too big. A proof file can be at most 25 MB. Use --url or --note."


def attach_file(
    root: Path, tid: str, path: str, title: str | None, role: str | None, summary: str | None = None
) -> dict:
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
            raise Refused("proof files cannot be refs. Give the real file.")
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
        raise Refused("proof files cannot be refs. Give the real file.") from None
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
    if summary:
        ev["summary"] = summary
    return ev


def proof_present(root: Path, ev: dict) -> bool:
    """False for a copied proof file that is not on this computer (evidence/ is not in git)."""
    ref = str(ev.get("ref", ""))
    if ev.get("type") != "file" or not ref.startswith(".orch/tickets/") or "/evidence/" not in ref:
        return True
    return (root / ref).is_file()


# ---------------------------------------------------------------- artifacts


def artifacts_path(root: Path, tid: str) -> Path:
    """.orch/tickets/<id>/artifacts/ : where the files a ticket produces go (next to evidence/)."""
    load(root, tid)
    return tickets_dir(root) / tid / "artifacts"


def files_dir(root: Path, tid: str) -> Path:
    """.orch/tickets/<id>/files/ : files people send to the ticket (from the phone), created. A link anywhere
    on the way is refused."""
    load(root, tid)
    cur = root / ".orch"
    for part in ("tickets", tid, "files"):
        cur = cur / part
        if cur.is_symlink():
            raise Refused("The files folder of this ticket is a link. orch will not use it.")
        if cur.exists() and not cur.is_dir():
            raise Refused("The files folder of this ticket is blocked by a file. Move that file away.")
        if not cur.exists():
            cur.mkdir()
    return cur


def artifacts_dir(root: Path, tid: str) -> Path:
    """The ticket's artifacts folder, created. A link anywhere on the way is refused."""
    d = artifacts_path(root, tid)
    cur = root / ".orch"
    for part in ("tickets", tid, "artifacts"):
        cur = cur / part
        if cur.is_symlink():
            raise Refused("The artifacts folder of this ticket is a link. orch will not use it.")
        if cur.exists() and not cur.is_dir():
            raise Refused("The artifacts folder of this ticket is blocked by a file. Move that file away.")
        if not cur.exists():
            cur.mkdir()
    return d


def artifacts_list(root: Path, tid: str) -> list[dict]:
    """The files in the ticket's artifacts folder (sub-folders included): name, size, mtime, path."""
    d = artifacts_path(root, tid)
    out = []
    if d.is_dir() and not d.is_symlink():
        for f in sorted(d.rglob("*")):
            if f.is_symlink() or not f.is_file():
                continue
            st = f.stat()
            out.append(
                {
                    "name": f.relative_to(d).as_posix(),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "path": f.relative_to(root).as_posix(),
                }
            )
    return out


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
