"""Tickets: one JSON file per ticket in .orch/tickets/<id>.json.

Unknown fields are kept: a ticket is loaded as a plain dict, changed, saved whole.
"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import config, diag, history, net, ownerpick, people, procs, saferead, syncgate, term
from orch.errors import Refused
from orch.session_ids import SESSION_ID_RE as SESSION_ID_RE
from orch.session_ids import valid_session_id
from orch.text import clean_untrusted

STATUSES = ("open", "active", "waiting", "ready", "review", "done", "dropped")
STATUS_WORDS = {
    "open": "Backlog",
    "ready": "Ready",
    "active": "Working",
    "waiting": "Waiting",
    "review": "Review",
    "done": "Done",
    "dropped": "Won't do",
}


def changes_asked(t: dict) -> bool:
    """True while a person's Send back is still open: the ticket is back on the list (Ready) and a task
    made from their words (origin change_request) is neither done nor set aside. Derived, never stored:
    Undo and finishing the task clear it by themselves."""
    return t.get("status") == "ready" and any(
        c.get("origin") == "change_request" and not c.get("done") and not c.get("wont_do")
        for c in t.get("checklist") or []
    )


def status_word(t: dict) -> str:
    """The word for a ticket's status; a dropped ticket another ticket replaces says Superseded; a ticket
    a person sent back and that is not yet worked says Changes asked."""
    if t.get("status") == "dropped" and t.get("superseded_by"):
        return "Superseded"
    if changes_asked(t):
        return "Changes asked"
    return STATUS_WORDS.get(t.get("status"), str(t.get("status")))


OPEN_STATUSES = tuple(s for s in STATUS_WORDS if s not in ("done", "dropped"))
REVIEW_MESSAGE = "Moved to Review, not Done. A person marks a ticket Done."
CLOSED_ITSELF_MESSAGE = (  # ORCH-1741: merged with nothing open, or a security review with an ok
    "Done: accepted for the person at once, nothing is left for them to check. They can send it back."
)
TAIL_MAX = 2048
# C0 except tab/newline, DEL, C1 and bidi overrides: never in a recorded command or output
UNSAFE_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
RAN_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
RUNS_PER_REF = 5
RUNS_PER_CHECK = 45  # notes are not capped: only people write them, orch writes the runs
SIG = re.compile(r"[0-9a-f]{16,128}")
EVIDENCE_TYPES = ("pr", "commit", "file", "url", "command", "note")
WAIT_KINDS = ("time", "ticket", "pr", "question", "external")
# ORCH-815: `orch wait <id> --on pr:<url>`: the helper watcher wakes it once the PR is merged or closed
PR_WAIT_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+")
PR_FINAL = ("merged", "closed")
PATCH_FIELDS = (
    "title",
    "status",
    "waiting_on",
    "superseded_by",
    "owner",
    "due",
    "note",
    "done_when",
    "summary",
)
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
# the ticket id of the unattributed record run (secretrun); never a real ticket
RESERVED_OUTSIDE_ID = "t_outside"
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> str:
    """Any ISO 8601 time -> UTC RFC 3339 ending in Z. Without offset = local time (ORCH-619)."""
    t = text.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise Refused(f"'{text}' is not a time. Use e.g. 2026-11-05T08:00:00+01:00") from None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # a naive time is read as local by astimezone


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
    if history.is_reserved_label(who):
        raise Refused(f"'{who}' is reserved for orch's sync. Use agent:<tool> or human:<name>.")
    return who


def acting_by(args) -> str:
    """Who runs this command: the agent tool seen in the environment, else --by, else human:<os user>.
    Plain: no op is human-only, an agent's command just runs and is recorded as agent:<tool>."""
    tool = agent_tool()
    if tool:
        return "agent:" + str(tool)
    return current_actor(getattr(args, "by", None))


def tickets_dir(root: Path) -> Path:
    return root / ".orch" / "tickets"


def ticket_path(root: Path, tid: str) -> Path:
    if not isinstance(tid, str) or not _ID_RE.fullmatch(tid) or tid == RESERVED_OUTSIDE_ID:
        raise Refused(f"Ticket {tid} doesn't exist. Run `orch ticket list` to see your tickets.")
    return tickets_dir(root) / f"{tid}.json"


def new_id(root: Path) -> str:
    for _ in range(100):
        tid = "t_" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not ticket_path(root, tid).exists():
            return tid
    raise Refused("Could not find a free ticket id.")


_KEY_RE = re.compile(r"^([A-Za-z0-9]{2,4})-([1-9][0-9]{0,8})$")
BROKEN_FIX = "fix the JSON by hand or restore it from git"


def broken_file(name: str) -> str:
    """The one sentence for a ticket file that holds no valid JSON (ORCH-2019): list, show and doctor."""
    return f"The ticket file .orch/tickets/{name} is broken (not valid JSON): {BROKEN_FIX}."


def _broken_with_key(root: Path, want: str) -> Refused | None:
    """Why a key was not found when some ticket files are broken: the file that still names the key, else
    the broken files it may be in. Only the broken files are read, and only on this miss."""
    from orch import ticketindex

    bad = ticketindex.broken(root)
    if not bad:
        return None
    rx = re.compile(r'"key"\s*:\s*"' + re.escape(want) + '"', re.I)
    for name in bad:
        try:
            text = (tickets_dir(root) / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if rx.search(text):
            return Refused(f"Ticket {want} can't be read. " + broken_file(name))
    files = ", ".join(bad[:3]) + (f" and {len(bad) - 3} more" if len(bad) > 3 else "")
    return Refused(
        f"Ticket {want} doesn't exist here, or it is in a broken ticket file ({files}): {BROKEN_FIX}."
    )


def resolve(root: Path, ref, *, follow_moved: bool = False, notice=None):
    """The one place a ticket key (DM1-12, any case) becomes the ticket id. Anything else is returned as it
    is (an id, or a word the command refuses later). Old keys require explicit opt-in."""
    if not isinstance(ref, str) or not _KEY_RE.match(ref.strip()):
        return ref
    want = ref.strip().upper()
    from orch import ticketindex

    for r in ticketindex.rows(root):  # the index, not every ticket file (ORCH-521)
        if str(r.get("key") or "").upper() == want:
            return r["id"]
    if follow_moved:
        t = _moved_ticket(root, want, list_all(root))
        if t is not None:
            if notice is not None:
                notice(f"{want} moved to {t.get('key') or t['id']}")
            return t["id"]
    broken = _broken_with_key(root, want)
    if broken is not None:
        raise broken
    raise Refused(f"Ticket {ref} doesn't exist. Run `orch ticket list` to see your tickets.")


def _moved_ticket(root: Path, want: str, local: list[dict]):
    """Find a unique, locally issued old key; never follow chains or cross workspaces."""
    key = _KEY_RE.fullmatch(want)
    code = config.workspace_code(root)
    alias_allowed = (
        key is not None
        and code is not None
        and key.group(1) == code.upper()
        and int(key.group(2)) <= _counter_last(root)
    )
    matches = []
    for t in local if alias_allowed else []:
        old_keys = _get(t, "ext.sync.old_keys")
        if isinstance(old_keys, list) and any(isinstance(k, str) and k.upper() == want for k in old_keys):
            matches.append(t)
    if len(matches) > 1:
        keys = ", ".join(sorted(str(t.get("key") or t["id"]) for t in matches))
        raise Refused(f"{want} is an old key claimed by several tickets: {keys}. Use a current key.")
    return matches[0] if matches else None


def resolve_cli(root: Path, ref, *, json_output: bool = False):
    """Text CLI follows moved keys visibly; JSON callers must use the current key."""
    if not json_output:
        return resolve(root, ref, follow_moved=True, notice=lambda message: print(message, file=sys.stderr))
    try:
        return resolve(root, ref)
    except Refused:
        if isinstance(ref, str) and _KEY_RE.fullmatch(ref.strip()):
            want = ref.strip().upper()
            t = _moved_ticket(root, want, list_all(root))
            if t is not None:
                current = t.get("key") or t["id"]
                raise Refused(f"{want} moved to {current}; use {current}") from None
        raise


def _counter_path(root: Path) -> Path:
    return root / ".orch" / "ticket-counter.json"


def _counter_last(root: Path) -> int:
    try:
        return int(json.loads(_counter_path(root).read_text(encoding="utf-8")).get("last", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def next_key(root: Path) -> str:
    """<code>-<n> for a new ticket. n is 1 + the highest number handed out (counter file or any ticket's key),
    written to the counter under one workspace lock, so no two tickets share a number and none is reused."""
    code = config.workspace_code(root) or config.set_code(root, config.suggest_code(root.resolve().name))
    with _locked(root, "key"):
        p = _counter_path(root)
        last = _counter_last(root)
        from orch import ticketindex

        for t in ticketindex.rows(root):  # the keys from the index, not every ticket file (ORCH-521)
            m = _KEY_RE.match(str(t.get("key") or ""))
            if m:
                last = max(last, int(m.group(2)))
        n = last + 1
        tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps({"last": n}) + "\n", encoding="utf-8")
            syncgate.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)
    return f"{code}-{n}"


def _load_raw(root: Path, tid: str) -> dict:
    """The ticket file as it is: for the writers, which must see and keep what a peer or an agent wrote."""
    p = ticket_path(root, tid)
    if not p.exists():
        raise Refused(f"Ticket {tid} doesn't exist. Run `orch ticket list` to see your tickets.")
    return _read_ticket(p, tid)


def load(root: Path, tid: str) -> dict:
    """The ticket as it is on disk. Old fields this version no longer uses (verdicts, wont_mac, ...) stay in
    the file and are kept on every save, never dropped."""
    return _load_raw(root, tid)


_SCHEMA_RE = re.compile(r"orch\.ticket/(\d+)$")


def _newer_format(data: dict) -> str | None:
    m = _SCHEMA_RE.match(str(data.get("schema", "")))
    return m.group(0) if m and int(m.group(1)) > 1 else None


def _check_format(data: dict, tid: str) -> None:
    """A ticket file written by a newer orch (schema orch.ticket/<N>, N above ours) is refused with one
    plain sentence, so an older orch never edits and saves it (there is no migration code, R8.2)."""
    fmt = _newer_format(data)
    if fmt:
        raise Refused(
            f"Ticket {tid} was written by a newer orch (format {fmt}). Update orch with `orch update`;"
            " the file is left as it is."
        )


def _read_ticket(p: Path, tid: str) -> dict:
    """Read one ticket file. Invalid JSON is retried (3x, 100 ms) only while a sync gate is live (a sync step
    may be swapping the file in), then reported as "being updated"; with no sync running it is reported as a
    broken file the person fixes (ORCH-2019). Read-only: a reader never rewrites, quarantines or deletes a
    file."""
    for attempt in range(4):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("id") != tid:
                raise Refused(f"Ticket {tid} is invalid: its id does not match its filename.")
            _check_format(data, tid)
            return data
        except (ValueError, PermissionError) as e:  # Windows: a sharing violation while a file is swapped in
            if syncgate.live_holder(_root_of(p)) is None:
                if isinstance(e, PermissionError):
                    raise
                raise Refused(f"Ticket {tid} can't be read. " + broken_file(p.name)) from None
            if attempt == 3:
                if isinstance(e, PermissionError):
                    raise
                raise Refused(f"Ticket {tid} is being updated. Try again in a moment.") from None
        time.sleep(0.1)
    raise AssertionError("unreachable")


def _root_of(p: Path) -> Path:
    return p.parent.parent.parent  # <root>/.orch/tickets/<file>


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
def sync_apply(root: Path, tid: str):
    """Lock a ticket (or ``key`` for the counter) for an in-process sync write.

    Call on the thread holding syncgate.hold; other writers retain the normal
    gate-before-ticket ordering. The caller checks and replaces the file while
    this context is held, without importing core lock internals. Before each
    write batch the holder checks that the gate still carries its identity;
    a thread holding no gate for `root` is refused (fail closed).
    """
    if tid != "key":
        ticket_path(root, tid)
    with _locked(root, tid):
        syncgate.ensure_held(root)
        yield


@contextlib.contextmanager
def _locked(root: Path, tid: str, wait: float = 5.0):
    """One writer at a time per ticket: an exclusive lock file next to it (stale after 30 s).
    Lock order is gate -> ticket lock: a synced ticket (or the counter) waits for the sync gate BEFORE taking
    the lock and checks again after taking it, so the sync step (which holds the gate and takes this same lock
    for every file it writes) never has a writer inside a file it replaces. Never waits for the gate while
    holding the lock."""
    gated = bool(_ID_RE.fullmatch(tid)) or tid == "key"  # chat / relay state is never synced
    what = f"ticket {tid}" if tid != "key" else "the ticket counter"
    lock = tickets_dir(root) / f".lock-{tid}"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if gated:
        syncgate.wait_clear(root, what)
    end = time.monotonic() + wait
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
                raise Refused(f"Ticket {tid} is busy (retried for {wait:g} s). Try again.") from None
            try:
                stale = time.time() - lock.stat().st_mtime > 30
            except OSError:
                time.sleep(0.02)
                continue
            if stale and _break_stale(lock):
                continue
            if time.monotonic() > end:
                raise Refused(f"Ticket {tid} is busy (retried for {wait:g} s). Try again.") from None
            time.sleep(0.02)
    try:
        if gated and syncgate.live_holder(root) is not None:  # a gate appeared while we took the lock
            raise syncgate.busy(what)
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


def _conflict(root: Path, ticket: dict, what: str, current) -> Conflict:
    h = (history.lines(root, ticket) or [{}])[-1]  # the shown line: an unproven synced author is not named
    by = h.get("by", "unknown")
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
    people.stamp_lines(root, history.created_lines(ticket))  # new lines name the person and device (list on)
    history.register_written(root, ticket)  # the lines/evidence/refs core made for it (only once sync is on)
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


def _wont_view(ticket: dict) -> dict:
    """The Won't do state (id, flag, reason, who, when, text): what only a person may change."""
    return {
        c.get("id"): (
            c.get("wont_do"),
            c.get("reason"),
            c.get("by") if c.get("wont_do") else None,
            c.get("at") if c.get("wont_do") else None,
            c.get("text") if c.get("wont_do") else None,
        )
        for c in ticket.get("checklist") or []
        if isinstance(c, dict) and (c.get("wont_do") or c.get("reason"))
    }


def _is_person(by: str) -> bool:
    """The ONE person check for Won't do: a human actor and no agent tool in the environment."""
    return by.startswith("human:") and not agent_tool()


# `by` of a write that is not an agent-callable op: sync apply, relay/chat system lines, run bookkeeping.
# It is never an agent actor and is never guarded; it behaves exactly like an op without an actor.
SYSTEM = "system"


CLOSED_AGENT = "This ticket is closed, so the agent can't change it."


class ClosedRefused(Refused):
    """The closed-ticket agent guard said no (not a busy lock or a sync wait): dropped, never retried."""


def _agent_actor(by: str) -> bool:
    """An agent wrote it: `by` is agent:*, or a human:* claimed from inside an agent's environment (a run sets
    ORCH_AGENT, so an agent run cannot pass for a person; the same rule as _is_person). System actors (orch)
    are neither."""
    return by.startswith("agent:") or (by.startswith("human:") and bool(agent_tool()))


def _addon_keeps_its_ticket(root: Path, ticket: dict, by: str) -> bool:
    """An add-on's work can go on after its ticket is Done (a repeat survives Done, #194): an ACTIVE add-on,
    writing as agent:<its name>, still keeps up a done ticket that carries its own ext block (its record, a
    history line, opening it again for the next run). Never from inside an agent run (a run sets ORCH_AGENT),
    never on a dropped ticket, never on a ticket the add-on has no data on."""
    name = by.removeprefix("agent:")
    if by == name or ticket.get("status") != "done" or agent_tool():
        return False
    if not isinstance((ticket.get("ext") or {}).get(name), dict):
        return False
    from orch import addons  # addons is a leaf here; imported late like the other helpers

    return name in addons.active(root)


def _refuse_closed_agent(root: Path, tid: str, by: str) -> None:
    """The closed-ticket guard for a write that happens outside apply_op (a file copy): same rule, checked
    under the caller's ticket lock BEFORE anything is written."""
    if not _agent_actor(by):
        return
    ticket = _load_raw(root, tid)
    if ticket.get("status") in CLOSED:
        raise ClosedRefused(CLOSED_AGENT)


def apply_op(
    root: Path,
    tid: str,
    fn,
    *,
    expect: tuple[str, object] | None = None,
    if_revision: int | None = None,
    by: str,
    person_click: bool = False,
    keep_revision: bool = False,
    closed_ok=None,
):
    """person_click: a person's click on the dashboard or a phone, whatever tool started that server.
    keep_revision: a background note nobody edits on a page (where Prepare stands) keeps the revision, so
    a person's edit of what they saw is not refused as changed meanwhile (ORCH-741).
    closed_ok(ticket) -> bool: a write the closed-ticket guard lets through on a done/dropped ticket (only
    switching an add-on's repeat off, #2051); checked under the lock on the stored ticket.
    Every attempt leaves one decision event in the debug log (diag.md): ticket.op_applied or
    ticket.op_refused (actor, op, status and revision before/after, the refusing guard; no ticket text)."""
    info: dict = {"person_click": person_click, "keep_revision": keep_revision, "closed_ok": closed_ok}
    try:
        out = _apply_op(root, tid, fn, expect, if_revision, by, info)
    except BaseException as e:
        guard = (
            "closed_ticket"
            if isinstance(e, ClosedRefused)
            else "conflict"
            if isinstance(e, Conflict)
            else type(e).__name__
        )
        diag.log(
            "ticket.op_refused", "info", root=root, ticket=tid, actor=by, op=_op_name(fn), guard=guard,
            status=info.get("status"), expected_revision=if_revision, actual_revision=info.get("revision"),
        )  # fmt: skip
        raise
    diag.log(
        "ticket.op_applied", "info", root=root, ticket=tid, actor=by, op=_op_name(fn),
        status_from=info.get("status"), status_to=info.get("status_to"),
        revision_from=info.get("revision"), revision_to=info.get("revision_to"),
        written=info.get("written", False),
    )  # fmt: skip
    return out


def _op_name(fn) -> str:
    name = getattr(fn, "__name__", "") or "op"
    return "op" if name == "<lambda>" else name.strip("_")[:60] or "op"


def _apply_op(root: Path, tid: str, fn, expect, if_revision, by: str, info: dict):
    """The one write path: load, change and write under ONE lock, so concurrent plain ops all land on the
    latest revision. `fn(ticket)` changes the dict (no subprocess, nothing slow) and returns a result.
    Only an edit of something a person saw passes `expect=(path, old value)` or `if_revision`;
    it is refused (Conflict, exit 2) when that changed. `by` is required: the validated actor of an op an
    agent can call, or SYSTEM for any other write. It is THE guard of a closed ticket: an agent changes
    nothing in a done/dropped ticket, re-opening included, refused before `fn` runs, so nothing (ticket,
    history, ledger) is touched (#542).
    Returns (ticket, result)."""
    ticket_path(root, tid)  # id shape check, same friendly refusal
    with _locked(root, tid):
        ticket = _load_raw(root, tid)
        eff_status = ticket.get("status")
        info.update(status=eff_status, revision=revision(ticket))
        if (
            eff_status in CLOSED
            and _agent_actor(by)
            and not _addon_keeps_its_ticket(root, ticket, by)
            and not (info.get("closed_ok") and info["closed_ok"](ticket))
        ):
            raise ClosedRefused(CLOSED_AGENT)
        if if_revision is not None and revision(ticket) != if_revision:
            raise _conflict(root, ticket, f"Ticket {tid}", {k: ticket.get(k) for k in PATCH_FIELDS})
        if expect is not None and _get(ticket, expect[0]) != expect[1]:
            parent, _, leaf = expect[0].rpartition(".")
            raise _conflict(root, ticket, parent.split(".")[-1] or leaf, _get(ticket, parent or leaf))
        was_review = ticket.get("status") == "review"
        wont_before = _wont_view(ticket)
        result = fn(ticket)
        if agent_tool() and not info.get("person_click"):
            ids = [c.get("id") for c in ticket.get("checklist") or [] if isinstance(c, dict)]
            if len(ids) != len(set(ids)):
                raise Refused("Duplicate checklist step ids are not allowed.")
            if _wont_view(ticket) != wont_before:
                # no write path run by an agent changes a person's Won't do decision
                raise Refused("Only a person marks a step as won't do, or opens it again.")
        if result is NO_WRITE:  # the op found nothing to change: no new revision, no history
            return ticket, None
        if was_review and ticket.get("status") != "review":
            # leaving Review closes the phones' review round in the same lock (fb8): an old "accept"
            # can never apply to work that came back to Review later
            from orch import phone_view  # phone_view imports tickets

            phone_view.close_rounds(root, tid)
        if not info.get("keep_revision"):
            ticket["revision"] = revision(ticket) + 1
        ticket["updated_at"] = now()
        _write(root, ticket)
        info.update(status_to=ticket.get("status"), revision_to=revision(ticket), written=True)
        after = ticket.get("status")
        closed_now = after in CLOSED and eff_status not in CLOSED
        # entering Review, leaving Review for more work, or leaving Done: a review round starts or ends
        new_round = (
            not closed_now and after != eff_status and (after == "review" or eff_status in ("review", "done"))
        )
    if closed_now:
        # THE one place a ticket becomes done/dropped, whatever op did it (accept, status, patch from the
        # dashboard, ...): its live agent run stops when a person closed it (#542) and its separate copy
        # goes, after the ticket lock is released. Each in its own try: one failing never skips the other.
        try:
            from orch import runs_live  # runs_live imports tickets

            runs_live.stop_closed(root, tid, by)
        except Exception:  # noqa: BLE001
            pass
        try:
            from orch import worktrees  # worktrees imports tickets

            worktrees.on_closed(root, tid)
        except Exception:  # noqa: BLE001
            pass
    elif new_round:
        from orch import worktrees

        worktrees.on_status(root, tid, eff_status, after)  # the reviewed tip of a copy (never raises)
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


def list_all(root: Path, include_general: bool = False, ext: str | None = None) -> list[dict]:
    """Every ticket by creation time. The hidden General ticket of the phone conversation (flag
    `general: true`) and the hidden Manager ticket (flag `manager: true`) are left out unless include_general:
    they are not tickets anyone lists, counts or closes. `ext`: only tickets with add-on data under that name;
    a file whose text does not name it is not parsed (ORCH-603: an add-on reads its own tickets fast); with
    the ticket index only the files of tickets that carry it are read (ORCH-1621)."""
    if ext is not None:
        mine = _with_ext(root, ext, include_general)
        if mine is not None:
            return mine
    d = tickets_dir(root)
    out = []
    mark = json.dumps(ext) if ext is not None else None
    if d.is_dir():
        for p in sorted(d.glob("t_*.json")):
            try:
                text = p.read_text(encoding="utf-8")
                if mark is not None and mark not in text:
                    continue
                t = json.loads(text)  # no retry: a listing never stalls on a bad file
            except (OSError, ValueError):
                continue
            if not isinstance(t, dict) or t.get("id") != p.stem:
                continue
            if ext is not None and not (isinstance(t.get("ext"), dict) and ext in t["ext"]):
                continue
            if _newer_format(t):
                continue  # a newer orch's file: not shown here, never rewritten
            if include_general or not is_hidden(t):
                out.append(t)
    out.sort(key=lambda t: t.get("created_at", ""))
    return out


def _with_ext(root: Path, ext: str, include_general: bool) -> list[dict] | None:
    """list_all(ext=...) through the ticket index, or None without a usable one (then every file is
    looked at)."""
    from orch import ticketindex

    try:
        found = ticketindex.rows(root, include_hidden=include_general)
    except Exception:  # noqa: BLE001 - no index (or a broken one): the caller reads every file
        return None
    out = []
    for r in found:
        if ext not in (r.get("ext") or ()):
            continue
        try:
            t = load(root, r["id"])
        except Exception:  # noqa: BLE001, S112 - a ticket that cannot be read is left out
            continue
        if isinstance(t.get("ext"), dict) and ext in t["ext"]:
            out.append(t)
    return out


def is_general(root: Path, tid: str) -> bool:
    """True for the hidden General ticket (reads one file; a missing or unreadable ticket is not General)."""
    try:
        return json.loads(ticket_path(root, tid).read_text(encoding="utf-8")).get("general") is True
    except (OSError, ValueError, Refused, AttributeError):
        return False


def general_id(root: Path) -> str | None:
    """The id of this workspace's hidden General ticket, or None before the first General text. Only the
    hidden tickets are read (the ticket index names them; ORCH-1621: every ticket was read, 1 s at 10,000)."""
    for t in _hidden_tickets(root):
        if isinstance(t, dict) and t.get("general") is True:
            return t["id"]
    return None


def _hidden_tickets(root: Path) -> list[dict]:
    """The hidden tickets (Chat, Manager, sessions) by creation time, as list_all(include_general=True) has
    them."""
    from orch import ticketindex

    return ticketindex.load_where(root, lambda r: bool(r.get("hidden")), include_hidden=True)


def is_manager(root: Path, tid: str) -> bool:
    """True for the hidden Manager ticket: the workspace's always-on helper session (ORCH-147)."""
    try:
        return json.loads(ticket_path(root, tid).read_text(encoding="utf-8")).get("manager") is True
    except (OSError, ValueError, Refused, AttributeError):
        return False


def is_session(root: Path, tid: str) -> bool:
    """True for the hidden ticket of a session without a ticket (empty helper, plain terminal; ORCH-364)."""
    try:
        return json.loads(ticket_path(root, tid).read_text(encoding="utf-8")).get("session") in SESSION_KINDS
    except (OSError, ValueError, Refused, AttributeError):
        return False


def manager_id(root: Path) -> str | None:
    """The id of this workspace's hidden Manager ticket, or None before the Manager was first started."""
    for t in _hidden_tickets(root):
        if isinstance(t, dict) and t.get("manager") is True and t.get("general") is not True:
            return t["id"]
    return None


MANAGER_NOTE = (
    "The Manager: an always-on helper the person talks to in Focus or joins in a terminal. It looks after "
    "the workspace's tickets and helpers with the full rights of a normal helper. Nothing ends its session "
    "by itself."
)


def ensure_manager(root: Path, by: str) -> str:
    """The Manager ticket (flag manager: true, no display key so no number is used up), made once. Kept out of
    git like the Chat ticket: it is this computer's own session."""
    from orch import harness

    if tid := manager_id(root):
        return tid
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "title": "Manager",
        "manager": True,
        "status": "open",
        "note": MANAGER_NOTE,
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [],
    }
    add_history(ticket, by, "Created", "cli", at=t)
    save(root, ticket)
    harness.protect_local(root)
    return ticket["id"]


# Sessions without a ticket (ORCH-364, draft D): the empty helper and the plain terminal, one of each per
# workspace, each a hidden ticket like the Manager's (flag session: <kind>, no display key, kept out of git).
SESSION_KINDS = ("empty", "terminal")
SESSION_TITLES = {"empty": "Empty helper", "terminal": "Plain terminal"}
SESSION_NOTES = {
    "empty": "A helper with no ticket and no task yet: it waits for the person's first message.",
    "terminal": "A plain terminal in this workspace, no helper.",
}


def session_id(root: Path, kind: str) -> str | None:
    """The id of this workspace's hidden ticket of a session without a ticket of this kind, or None."""
    for t in list_all(root, include_general=True):
        if isinstance(t, dict) and t.get("session") == kind and hidden_kind(t) == kind:
            return t["id"]
    return None


def ensure_session(root: Path, kind: str, by: str) -> str:
    """The hidden ticket of a session without a ticket (empty helper or plain terminal), made once."""
    from orch import harness

    if kind not in SESSION_KINDS:
        raise Refused(f"No such session without a ticket: {kind}.")
    if tid := session_id(root, kind):
        return tid
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": new_id(root),
        "title": SESSION_TITLES[kind],
        "session": kind,
        "status": "open",
        "note": SESSION_NOTES[kind],
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [],
    }
    add_history(ticket, by, "Created", "cli", at=t)
    save(root, ticket)
    harness.protect_local(root)
    return ticket["id"]


def ensure_general(root: Path, by: str) -> str:
    """The General ticket (flag general: true, no display key so no number is used up), made once."""
    from orch import harness

    if tid := general_id(root):
        harness.protect_local(root)  # older workspaces: the Chat ticket file stays out of git from now on
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
        "history": [],
    }
    add_history(ticket, by, "Created", "cli", at=t)
    save(root, ticket)
    harness.protect_local(root)
    return ticket["id"]


_FIELD_WORDS = {
    "title": "title",
    "owner": "owner",
    "due": "due date",
    "note": "note",
    "done_when": "Done when line",
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


def _parent_words(parent: dict) -> str:
    """The parent in a "Created under ..." line: its key and title (never its internal id)."""
    title = " ".join(str(parent.get("title") or "").split())
    title = title[:77] + "..." if len(title) > 80 else title
    return f"{parent.get('key') or parent['id']}" + (f" {title}" if title else "")


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

    if re.fullmatch(r"Created under t_\w+", t):
        return "Created as a sub-ticket"  # an older line: it holds only the internal id
    if m := re.fullmatch(r"Recorded a check run for (c\d+)(?: \(exit (\d+)\))?", t):
        result = "" if m.group(2) is None else " (passed)" if m.group(2) == "0" else " (failed)"
        return "Ran a check" + task(m.group(1)) + result
    if m := re.fullmatch(r"Moved (c\d+) after c\d+", t):
        return "Moved a task" + task(m.group(1))
    if re.fullmatch(r"Asked q\d+, waiting", t):
        return "Asked a question"
    if m := re.fullmatch(r"Answered q\d+: (.*)", t, re.DOTALL):
        return f"Answered a question: {m.group(1)}"
    if m := re.fullmatch(r"Status (\w+) -> (\w+)", t):
        return f"Moved to {STATUS_WORDS.get(m.group(2), m.group(2))}"
    if m := re.fullmatch(r"Edited ([a-z_, ]+)(?: \(was: .* \| now: .*\))?", t, re.DOTALL):
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
    if m := re.fullmatch(r"Marked (c\d+) as won't do", t):
        return "Marked as won't do" + task(m.group(1))
    # ORCH-240: never a raw task id ("Reopened c1") in the Activity
    if m := re.fullmatch(r"Reopened (c\d+)(?: \(old evidence: .*\))?", t, re.DOTALL):
        return "Opened a task again" + task(m.group(1))
    if m := re.fullmatch(r"Renamed (c\d+)(?: \(was: .* \| now: .*\))?", t, re.DOTALL):
        return "Renamed a task" + task(m.group(1))
    if m := re.fullmatch(r"Linked (c\d+) to Done when", t):
        return "Linked a task to Done when" + task(m.group(1))
    removed = r"Removed step c\d+ '(.*)' \((?:was done|was open)(?:; evidence: .*)?\)"
    if m := re.fullmatch(removed, t, re.DOTALL):
        return f"Removed a task: {m.group(1)}"
    if re.fullmatch(r"Title changed(?: \(was: .* \| now: .*\))?", t, re.DOTALL):
        return "Changed the title"
    if m := re.fullmatch(r"Set ext\.([a-z][a-z0-9-]*)", t):
        return f"Updated {addon(m.group(1))} settings"
    if m := re.fullmatch(r"Removed ext\.([a-z][a-z0-9-]*)(\.[\w-]+)?", t):
        return f"Removed {addon(m.group(1))} settings"
    return t


# The `via` / origin word for "the person, through a UI" (contracts/chat-groups.md). The wire and the stored
# files keep this value, so old tickets, messages and peers stay readable; the only place core spells it.
PERSON_VIA = "dashboard"


def _env_via() -> str:
    """Where a change comes from: ORCH_VIA (a page that runs orch sets it, e.g. dashboard), else cli."""
    v = os.environ.get("ORCH_VIA", "")
    return v if re.fullmatch(r"[a-z][a-z0-9-]{1,23}", v) else "cli"


_ADDON_NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")


def _env_addon(by: str) -> str | None:
    """The add-on whose command writes a line (history.md 'Add-on lines'): ORCH_ADDON of an add-on
    subprocess, only for a line that is not a person's, not from a page (ORCH_VIA) and not inside a helper
    run (ORCH_RUN)."""
    v = os.environ.get("ORCH_ADDON", "")
    if not _ADDON_NAME_RE.fullmatch(v) or os.environ.get("ORCH_VIA") or os.environ.get("ORCH_RUN"):
        return None
    return None if str(by).startswith("human:") else v


CHAT_LINE_ID_RE = re.compile(r"m_[a-z0-9]{16}")
BY_NAME_MAX = 60


def chat_line_id() -> str:
    """A new stable id for a chat line (contracts/history.md "Chat lines"), in the form of a message id."""
    return "m_" + "".join(secrets.choice(_ALPHABET) for _ in range(16))


def clean_by_name(name: str | None) -> str | None:
    """The name a person typed for a chat line: one line, 1 to 60 characters, or None. Never an identity."""
    if name is None:
        return None
    name = " ".join(clean_untrusted(str(name)).split())
    if not name:
        return None
    if len(name) > BY_NAME_MAX:
        raise Refused(f"A name has 1 to {BY_NAME_MAX} characters.")
    return name


def add_history(
    ticket: dict,
    by: str,
    text: str,
    via: str | None = None,
    chat: bool = False,
    *,
    at: str | None = None,
    mid: str | None = None,
    by_name: str | None = None,
) -> None:
    """THE one point where core appends a history line (contracts/history.md). chat=True marks a real Chat or
    group message (`chat_message: true`): the only lines the Chat shows. A chat line also gets a stable `id`
    (`mid` when the message already has one, else a new one) and, when given, the name the person typed
    (`by_name`, shown as typed and never trusted; `by` stays the actor). The exact line object made here is
    marked as core's own (history.created); _write records it when the ticket is written."""
    entry = {"at": at or now(), "by": by, "via": via or _env_via(), "text": text, "chat_message": chat}
    if chat:
        if mid is not None and not CHAT_LINE_ID_RE.fullmatch(mid):
            raise Refused("A chat line id is m_ and 16 lowercase letters or digits.")
        entry["id"] = mid or chat_line_id()
        name = clean_by_name(by_name)
        if name:
            entry["by_name"] = name
    elif mid is not None or by_name is not None:
        raise Refused("Only a chat line carries an id and a typed name.")
    addon = _env_addon(by)
    if addon:
        entry["addon"] = addon
    ticket["history"].append(entry)
    history.created("lines", entry)


def add_evidence(item: dict, evs: list[dict], *, trim: bool = False) -> None:
    """THE one point where core appends evidence to a step: each object made here is marked as core's own
    (history.created), recorded when the ticket is written. trim: recorded runs are capped (trim_runs)."""
    for ev in evs:
        history.created("evidence", ev)
    if trim:
        item["evidence"] = trim_runs([*item["evidence"], *evs])
    else:
        item["evidence"].extend(evs)


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
    *,
    tid: str | None = None,
    title_auto: bool = False,
    plan_first: bool = False,
    epic: bool = False,
    release: bool = False,
    human_review: bool | None = None,
) -> dict:
    """`human_review`: the Human review needed switch (ORCH-424); None = the workspace default (on, or off
    while the Auto Reviewer is on: config.auto_reviewer_on).
    `title_auto`: the title is only a placeholder (first words of what a person wrote); the agent
    writes the real one (`orch ticket title`). The flag clears when anyone sets the title.
    tid lets callers persist a reserved id before this write."""
    if tid is not None:
        ticket_path(root, tid)  # validate before using the id in a lock path
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    parent_ticket = None
    if parent is not None:
        # the parent must exist (a new ticket has no children, so no loop; set_parent checks loops later)
        parent_ticket = load(root, parent)
    fields = fields or {}
    for k, v in fields.items():
        clean_field(k, v)
    t = now()
    ticket = {
        "schema": "orch.ticket/1",
        "id": tid if tid is not None else new_id(root),
        "key": next_key(root),
        "title": title,
        "status": "open",
        "created_at": t,
        "updated_at": t,
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [],
    }
    under = f" under {_parent_words(parent_ticket)}" if parent_ticket else ""
    add_history(ticket, by, "Created" + under, at=t)
    if parent is not None:
        ticket["parent"] = parent
    if title_auto:
        ticket["title_auto"] = True
    if plan_first:  # "Show plan first": the agent plans, asks "Plan ready", waits (set at creation only)
        ticket["plan_first"] = True
    if epic:  # several tickets made at once: its sub-tickets are the work, one run goes through them in order
        ticket["epic"] = True
    if (
        release
    ):  # ORCH-37: a release holds the epics and tickets that ship together (set_release changes it later)
        ticket["release"] = True
    if human_review is None:
        human_review = not config.auto_reviewer_on(root)
    if not human_review:  # ORCH-424: stored only when off; no field = on (also every older ticket)
        ticket["human_review"] = False
        add_history(ticket, by, HUMAN_REVIEW_OFF, at=t)
    for k, v in fields.items():  # owner, due, note, done_when: part of the one "Created" line
        _set_field(ticket, k, v)
    if ticket.get("note"):  # #1812: the first note stays as it was asked; the note itself is editable
        ticket["request"] = {"note": ticket["note"]}
    if ext:  # add-on data in the same write as the ticket (no half-made ticket)
        ticket["ext"] = ext
    if tid is not None and ticket_path(root, tid).exists():
        raise Refused("That ticket already exists.")
    save(
        root, ticket
    )  # under the ticket lock; it also refuses an id that appeared meanwhile (revision differs)
    return ticket


def checks_done(ticket: dict) -> tuple[int, int]:
    c = ticket.get("checklist", [])
    return sum(1 for x in c if x.get("done") or x.get("wont_do")), len(c)


def checks_split(ticket: dict) -> tuple[int, int, int]:
    """(done with proof, won't do, total): a ticket's steps, declined ones counted apart."""
    c = ticket.get("checklist", [])
    return (
        sum(1 for x in c if x.get("done")),
        sum(1 for x in c if x.get("wont_do") and not x.get("done")),
        len(c),
    )


def progress_text(ticket: dict) -> str:
    """'2 of 4 done', or '3 done, 1 won't do' when steps were declined: never '4 of 4' for work not done."""
    done, wont, total = checks_split(ticket)
    if not total:
        return ""
    return f"{done} done, {wont} won't do" if wont else f"{done} of {total} done"


def _latest(evs: list[dict], key: str) -> dict | None:
    """The newest command evidence that carries `key` (a recorded run; later ones replace earlier ones)."""
    return next((e for e in reversed(evs) if e.get("type") == "command" and e.get(key) is not None), None)


def _ev_failed(evs: list[dict]) -> bool:
    """A recorded failure: the newest recorded run says exit != 0. No exit recorded = unknown, never
    failed."""
    ev = _latest(evs, "exit")
    return ev is not None and type(ev["exit"]) is int and ev["exit"] != 0


def _norm_words(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text.lower()).split())


def _covered(part: str, cover: str) -> bool:
    """One contains the other at word boundaries (the shorter one at least 3 characters)."""
    a, b = _norm_words(part), cover
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and f" {short} " in f" {long_} "


def _loosely_named(part: str, texts: list[str]) -> bool:
    """A task text names a Done when part by meaning, not link: at least 70% of the part's words (3+ letters,
    at least 3 of them) are in that one task's text. Lets a reworded Done when keep its finished tasks."""
    words = {w for w in _norm_words(part).split() if len(w) >= 3}
    if len(words) < 3:
        return False
    return any(len(words & set(_norm_words(t).split())) * 10 >= len(words) * 7 for t in texts)


def done_when_parts(done_when: str) -> list[str]:
    """done_when split into its parts: one per line, ';' or sentence end. Plain and cheap on purpose."""
    parts = []
    for line in done_when.splitlines():
        for chunk in line.split(";"):
            parts += re.split(r"(?<=[.!?])\s+", chunk.strip())
    return [p.strip() for p in parts if _norm_words(p)]


def proof_state(ticket: dict, root: Path | None = None, cache: bool = False) -> dict:
    """Honest proof summary of a ticket. Reads files only (files_sig), runs nothing from the ticket.
    per_item: id -> passed | failed | changed | note | missing.
    failed = the newest recorded run (`orch check record`) has exit != 0 (also on a task not done);
    done + any proof that is not a note = passed; done + note proof only = note; not done = missing.
    changed (done, needs `root`): the newest recorded run has a files_sig and files_sig(root) is different now
    (a stored flag is never trusted). The current signature is computed at most once per call, only when a
    recorded signature exists; `cache` reuses it for a few seconds (polled pages).
    uncovered: the parts of done_when that no task `covers` (a part is covered when a task's covers text
    and the part contain one another, ignoring case and punctuation, or when one task's own text holds
    70% of the part's words); one hint when done_when cannot be
    split and nothing is linked. level: ok | note | warn | fail, so views never parse `line`."""
    from orch import filesig

    items = [c for c in ticket.get("checklist") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)]
    per: dict[str, str] = {}
    current: list = []

    def moved(ev: dict) -> bool:
        if root is None:
            return False
        if not current:
            current.append(filesig.cached_sig(root) if cache else filesig.files_sig(root))
        return current[0] is not None and current[0] != ev["files_sig"]

    for c in items:
        evs = [e for e in c.get("evidence") or [] if isinstance(e, dict)]
        sig_ev = _latest(evs, "files_sig")
        if _ev_failed(evs):
            per[c["id"]] = "failed"
        elif not c.get("done"):
            per[c["id"]] = "missing"
        elif sig_ev is not None and isinstance(sig_ev["files_sig"], str) and moved(sig_ev):
            per[c["id"]] = "changed"
        elif any(e.get("type") != "note" for e in evs):
            per[c["id"]] = "passed"
        else:
            per[c["id"]] = "note" if evs else "missing"
    done_when = ticket.get("done_when")
    covers = [_norm_words(c["covers"]) for c in items if isinstance(c.get("covers"), str)]
    # a finished task with evidence that the helper linked to a part proves it, in any words
    for c in items:
        if c.get("done") and c.get("evidence") and isinstance(c.get("proves"), list):
            covers += [_norm_words(q) for q in c["proves"] if isinstance(q, str)]
    covers = [c for c in covers if c]
    uncovered: list[str] = []
    if isinstance(done_when, str) and done_when.strip():
        parts = done_when_parts(done_when)
        texts = [c["text"] for c in items if isinstance(c.get("text"), str) and not c.get("wont_do")]
        uncovered = [
            p for p in parts if not any(_covered(p, c) for c in covers) and not _loosely_named(p, texts)
        ]
        if not parts and not covers:
            uncovered = ["Done when isn't linked to tasks"]
    n = {k: list(per.values()).count(k) for k in ("passed", "failed", "changed", "note")}

    def plural(count: int, word: str) -> str:
        return f"{count} {word}" + ("" if count == 1 else "s")

    if n["failed"]:
        line, level = f"{plural(n['failed'], 'check')} failed", "fail"
    elif n["changed"]:
        line, level = "Changes haven't been checked yet", "warn"
    elif uncovered:
        count = len(uncovered)
        one = count == 1 or uncovered == ["Done when isn't linked to tasks"]
        noun = "1 part" if one else f"{count} parts"
        line = f'{noun} of "Done when" {"has" if one else "have"} no task'
        level = "warn"
    elif n["passed"] or n["note"]:
        bits = ([f"{plural(n['passed'], 'check')} passed"] if n["passed"] else []) + (
            [plural(n["note"], "note")] if n["note"] else []
        )
        line, level = " · ".join(bits), "ok" if n["passed"] else "note"
    else:
        line, level = "No checks recorded", "note"
    return {"per_item": per, "uncovered": uncovered, "line": line, "level": level}


def _check_can_finish(ticket: dict) -> None:
    open_ = [c["id"] for c in ticket["checklist"] if not c.get("done") and not c.get("wont_do")]
    if open_:
        raise Refused(f"Not done: {', '.join(open_)} is not checked yet.")
    bad = [c["id"] for c in ticket["checklist"] if not c.get("evidence") and not c.get("wont_do")]
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

    tid = ticket["id"]
    if runs.unread_for_finish(root, tid):
        ref, rec = ticket.get("key") or tid, runs.read(root, tid)
        if rec and os.environ.get("ORCH_RUN") == rec.get("run"):
            raise Refused(
                f"Not done: new input for {ref} has not reached you yet; read it with: orch run input {ref}"
            )
        raise Refused(
            f"Not done: new input for {ref} has not been read yet; you can read it with: "
            f"orch run input {ref} and then go on."
        )


GENERAL_REFUSAL = "The Chat is not a ticket: it is never finished, dropped or reopened."
MANAGER_REFUSAL = "The Manager is not a ticket: it is never finished, dropped or reopened."
SESSION_REFUSAL = "A session without a ticket is not a ticket: it is never finished, dropped or reopened."


def hidden_kind(ticket: dict) -> str | None:
    """'general' (Chat), 'manager', or a session without a ticket ('empty' helper, 'terminal'; ORCH-364) for
    the hidden tickets that hold a conversation, never a piece of work: no status moves, never Working. None
    for every other ticket."""
    if ticket.get("general") is True:
        return "general"
    if ticket.get("manager") is True:
        return "manager"
    if ticket.get("session") in SESSION_KINDS:
        return str(ticket["session"])
    return None


def is_hidden(ticket) -> bool:
    """A hidden ticket (Chat, Manager, a session without a ticket): never in the ticket list."""
    return isinstance(ticket, dict) and hidden_kind(ticket) is not None


def _hidden_refusal(ticket: dict) -> str:
    kind = hidden_kind(ticket)
    return (
        MANAGER_REFUSAL
        if kind == "manager"
        else SESSION_REFUSAL
        if kind in SESSION_KINDS
        else GENERAL_REFUSAL
    )


GENERAL_REFUSED = (
    "open",
    "review",
    "done",
    "dropped",
    "active",
)  # finish, reopen, Working; waiting and ready stay


DRAFT_TO_CHECK = "a ticket with a draft, mockup or design waits for the owner's Check"


PREPARE_NO_STATUS = (
    "This ticket is being prepared: Prepare never changes its status. It stays in Backlog until a person "
    "starts it."
)


def _preparing_agent(root: Path, tid: str, by: str, person: bool = False) -> bool:
    """A helper (not a person) acts on a ticket a prepare-only run works on now (ORCH-741)."""
    if person or not (agent_tool() or by.startswith("agent:")):
        return False
    from orch import prepare

    return prepare.running_prepare(root, tid)


def _finish_status(root: Path, ticket: dict, status: str, by: str, person: bool = False) -> tuple[str, str]:
    """person: a signed-in person (the dashboard's one-time grant); only then does a ticket that carries a
    draft become Done (ORCH-582). An agent's Done goes to Review instead, also with agents may finish on."""
    if status != ticket.get("status") and _preparing_agent(root, ticket["id"], by, person):
        raise Refused(PREPARE_NO_STATUS)  # every status write of set_status and patch passes here
    if hidden_kind(ticket) and status in GENERAL_REFUSED:  # the ONE status guard (agent, person, wrapper)
        raise Refused(_hidden_refusal(ticket))
    if agent_tool():  # an agent in the environment counts as an agent whatever --by says
        by = "agent:" + str(agent_tool())
    if status == "done" and ticket["status"] != "done" and ownerpick.carries_draft(ticket):
        if by.startswith("agent:"):
            _check_not_too_early(root, ticket)
            _check_can_finish(ticket)
            add_history(ticket, by, f"{by} finished the work and sent it to Check: {DRAFT_TO_CHECK}")
            return "review", by
        ownerpick.refuse_ticket(ticket, person)
    if status in ("done", "review") and by.startswith("agent:") and ticket["status"] != status:
        _check_not_too_early(root, ticket)
    if status == "waiting" and by.startswith("agent:") and not hidden_kind(ticket):
        _check_waits_on_something(ticket)
    if status == "done" and by.startswith("agent:"):
        _check_can_finish(ticket)
        if not config.agents_may_finish(root):
            add_history(ticket, by, f"{by} finished the work and sent it to Check")
            return "review", by
    return status, by


WAITING_NO_REASON = (
    "Waiting needs something to wait on, or the person sees Waiting with no reason. "
    "Blocked or need an answer: "
    'orch ask {key} "<what blocks you and what you need>" --option <A> --option <B> --recommend <A>. '
    "Waiting for a time: orch wait {key} --until <time>."
)


def _check_waits_on_something(ticket: dict) -> None:
    """ORCH-602: an agent moves its ticket to Waiting only with a question, a time or a thing to wait on.
    A helper blocked by its tool's sandbox set Waiting with only a summary line (ORCH-548, ORCH-549, 18 Nov):
    the ticket sat in Waiting with no card and no reason shown. A person may still set Waiting by hand."""
    if ticket.get("waiting_on") or _open_questions(ticket):
        return
    raise Refused(WAITING_NO_REASON.format(key=ticket.get("key") or ticket.get("id") or "<id>"))


AGENT_FINISH_TEXT = "finished by the agent (agents may finish is on)"


def _note_agent_finish(ticket: dict, actor: str) -> None:
    """The ticket is becoming Done: when an agent does it (only with `agents_may_finish`, decided in
    _finish_status), the history says why it could."""
    if actor.startswith("agent:"):
        add_history(ticket, actor, AGENT_FINISH_TEXT)


def note_history(root: Path, tid: str, by: str, text: str, via: str | None = None) -> None:
    """One history line, nothing else changes (e.g. a phone answer that was too late)."""
    apply_op(root, tid, lambda ticket: add_history(ticket, by, text, via), by=by)


def accept_review(root: Path, tid: str, by: str, via: str = "phone", *, person: bool = False) -> dict:
    """A person accepts a ticket in Review: Review -> Done, like the dashboard's Accept. Refused for an agent
    (an agent in the environment, or any `by` that is not human:) and when the ticket is not in Review, so a
    second accept is refused. The relay's phone path calls it for an answer to the current review question
    (relay._apply_review_answer). person: a signed-in person or a paired phone; a ticket that carries a draft
    is accepted only then, checked under the ticket's lock (ORCH-582)."""
    if not by.startswith("human:") or agent_tool():
        raise Refused("Only a person can accept.")

    def op(ticket):
        if hidden_kind(ticket):
            raise Refused(_hidden_refusal(ticket))
        if ticket["status"] != "review":
            raise Refused("This ticket is not waiting for your review.")
        ownerpick.refuse_ticket(ticket, person)
        ticket["status"] = "done"
        ticket["waiting_on"] = None
        add_history(ticket, by, "Status review -> done", via)

    return apply_op(root, tid, op, by=by)[0]  # apply_op takes the copy away (worktrees.on_closed)


REVIEWER = "agent:reviewer"  # the Reviewer role (reviewer.py): acts for the owner, never as a person
REVIEWER_VIA = "reviewer"
ACCEPTED_LINE = "Accepted for you by the Reviewer: "
SENT_BACK_LINE = "Sent back by the Reviewer: "


def accepted_by_reviewer(root: Path, ticket: dict) -> bool:
    """Done, and the line that made it Done is the Reviewer's (the owner may still send it back)."""
    if ticket.get("status") != "done":
        return False
    for h in reversed(history.lines(root, ticket)):
        if isinstance(h, dict) and re.fullmatch(r"Status \w+ -> done", str(h.get("text", ""))):
            return h.get("by") == REVIEWER
    return False


def accept_for_owner(
    root: Path, tid: str, reasons: str, auto: str | None = None, if_revision: int | None = None
) -> dict:
    """The Reviewer accepts a ticket in Review for the owner (Review -> Done), only while the owner turned it
    on (`workflow.reviewer`), every task is done with evidence and no question waits. The history says who did
    it and why: a role acting for the owner, not a second approver (R4.1). The owner can send it back.
    auto: the Auto Reviewer's point-by-point line (ORCH-425): then its switch or Away mode must be on, the
    ticket
    must still be the revision it looked at, and ownerpick.refuse_auto runs inside the write."""
    from orch import autoreview

    if auto is not None and not autoreview.active(root):
        raise Refused("The Auto Reviewer is off here. Turn it on on the Review page.")
    if auto is None and not config.reviewer_on(root):
        raise Refused("The Reviewer is off here. Turn it on: orch config set workflow.reviewer on")
    why = _one_line(reasons)

    def op(ticket):
        if hidden_kind(ticket):
            raise Refused(_hidden_refusal(ticket))
        if ticket["status"] != "review":
            raise Refused("This ticket is not in Review.")
        ownerpick.refuse_ticket(
            ticket, person=False
        )  # ORCH-582: a draft is the owner's, never the Reviewer's
        if auto is not None:
            ownerpick.refuse_auto(ticket)  # Human review needed on: never the Auto Reviewer's
        _check_can_finish(ticket)
        if _open_questions(ticket):
            raise Refused("A question on this ticket still waits for an answer.")
        ticket["status"] = "done"
        ticket["waiting_on"] = None
        if auto is not None:
            add_history(ticket, REVIEWER, auto, REVIEWER_VIA)
        add_history(ticket, REVIEWER, "Status review -> done", REVIEWER_VIA)
        line = autoreview.AUTO_ACCEPTED_LINE if auto is not None else ACCEPTED_LINE
        add_history(ticket, REVIEWER, line + why, REVIEWER_VIA)

    return apply_op(root, tid, op, by=REVIEWER, if_revision=if_revision)[0]


ANSWERED_LINE = "Answered for you by the Reviewer: "


def answer_for_owner(root: Path, tid: str, qid: str, digest: str, why: str, away: bool = False) -> dict:
    """The Reviewer answers a small, routine question for the owner with the helper's recommended option,
    only while the owner turned it on (`workflow.reviewer_answers`) and only for a plain question (no card, no
    merge, not an add-on's) that is still exactly the one the Reviewer looked at (`digest`). The history says
    who did it and why: a role acting for the owner (R4.1); the owner corrects it with a message on the
    ticket.
    away: Away mode (ORCH-425) answers a plain question or a choice or plan card at once; its own rules
    (autoreview.away_answerable, with ownerpick.refuse_auto) run again inside the write."""
    from orch import autoreview

    if away and not config.away_on(root):
        raise Refused("Away mode is off here. Turn it on on the Review page.")
    if not away and not config.reviewer_answers_on(root):
        raise Refused("The Reviewer does not answer questions here. Turn it on: orch config set "
                      "workflow.reviewer_answers on")  # fmt: skip
    line = _one_line(why)

    def op(ticket):
        if ticket.get("general") is True:
            raise Refused(GENERAL_REFUSAL)
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}.")
        refuse_if_taken_back(q)
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered.")
        if question_digest(q) != digest:
            raise Refused(f"{qid} changed after the Reviewer looked at it.")
        ownerpick.refuse_card(q, person=False)  # ORCH-582: said first, in its own words
        if away:
            autoreview._away_recheck(ticket, q)  # noqa: SLF001 - the same rules on the fresh ticket
        elif q.get("card") is not None or q.get("action") is not None or q.get("kind") not in (None, "plain"):
            raise Refused(f"{qid} waits for the owner.")
        if q.get(autoreview.OWNER_ONLY):
            raise Refused(f"{qid} waits for the owner: they took it back from the Reviewer.")
        rec = q.get("recommended")
        if not rec or rec not in q["options"]:
            raise Refused(f"{qid} has no recommended answer.")
        answer = rec
        # Away mode, a choice card: the same decision a person's pick records
        if isinstance(q.get("card"), dict):
            from orch import review

            d = review._decision(q, review._card_of(q), "ok", rec, None)  # noqa: SLF001
            q["decision"], answer = d, review._plain_answer(q, d)  # noqa: SLF001
        q["answer"], q["answered_by"], q["via"] = answer, REVIEWER, REVIEWER_VIA
        q["answered_at"] = now()
        _release_wait(root, tid, ticket, qid)
        add_history(ticket, REVIEWER, f"Answered {qid}: {answer}", REVIEWER_VIA)
        said = autoreview.AUTO_ANSWERED_LINE if away else ANSWERED_LINE
        add_history(ticket, REVIEWER, said + f"{qid} = {answer} ({line})", REVIEWER_VIA)
        history.created("answers", q)
        return q

    return apply_op(root, tid, op, by=REVIEWER)[0]


def _undo_person(by: str) -> None:
    if not by.startswith("human:") or agent_tool():
        raise Refused("Only a person can undo what the Reviewer did.")


def undo_reviewer_accept(root: Path, tid: str, by: str) -> dict:
    """ORCH-425: a person undoes the Reviewer's accept: Done -> Review, with Human review needed on, so
    neither
    the Auto Reviewer nor Away mode accepts it again (the plain Reviewer looks at it again only when it
    changes).
    Refused when the ticket is no longer Done by the Reviewer's line (a person decided since)."""
    from orch import autoreview

    _undo_person(by)

    def op(ticket):
        if not accepted_by_reviewer(root, ticket):
            raise Refused("This ticket is not Done by the Reviewer any more, so there is nothing to undo.")
        ticket["status"] = "review"
        ticket.pop("human_review", None)
        add_history(ticket, by, "Status done -> review")
        add_history(ticket, by, autoreview.UNDONE_LINE + "the Reviewer's accept; back in Review for you, "
                    "with Human review needed on.")  # fmt: skip

    return apply_op(root, tid, op, by=by)[0]


def undo_reviewer_send_back(root: Path, tid: str, cid: str, by: str) -> dict:
    """ORCH-425: a person undoes the Reviewer's send-back before a helper took it: the Reviewer's task goes
    (the
    history keeps it), the ticket is in Review again with Human review needed on. The caller took the queued
    note away (autoreview._undo_send_back)."""
    from orch import autoreview

    _undo_person(by)

    def op(ticket):
        item = next((c for c in ticket["checklist"] if c.get("id") == cid), None)
        was = ticket["status"]
        if item is None or item.get("done") or was not in ("ready", "open"):
            raise Refused("A helper already took what the Reviewer asked, so it cannot be undone.")
        ticket["checklist"] = [c for c in ticket["checklist"] if c.get("id") != cid]
        ticket["status"] = "review"
        ticket.pop("human_review", None)
        add_history(ticket, by, f"Status {was} -> review")
        what = _one_line(item.get("text"), 120)
        add_history(ticket, by, autoreview.UNDONE_LINE + f"the Reviewer's send-back ({what}); "
                    "back in Review for you, with Human review needed on.")  # fmt: skip

    return apply_op(root, tid, op, by=by)[0]


def _reviewer_answer_stored(q: dict) -> bool:
    """Writer guard (ORCH-425): the stored question still holds an answer the Reviewer gave (raw bytes
    compared inside the locked write; nothing is shown)."""
    return q.get("answered_by") == REVIEWER and q.get("answer") is not None and q.get("taken_back") is None


def undo_reviewer_answer(root: Path, tid: str, qid: str, by: str) -> dict:
    """ORCH-425: a person undoes an answer the Reviewer or Away mode gave: the question is open again and
    marked
    as the owner's (never answered for them again). What the helper already did with the old answer stays: the
    caller tells the helper."""
    from orch import autoreview

    _undo_person(by)

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}.")
        if not _reviewer_answer_stored(q):
            raise Refused(f"{qid} was not answered by the Reviewer, so there is nothing to undo.")
        old = q["answer"]
        for k in ("answered_at", "decision"):
            q.pop(k, None)
        q["answer"] = q["answered_by"] = q["via"] = None
        q[autoreview.OWNER_ONLY] = True
        what = _one_line(old, 80)
        add_history(ticket, by, autoreview.UNDONE_LINE + f"the Reviewer's answer on {qid} ({what}); "
                    "it waits for you again.")  # fmt: skip
        return q

    return apply_op(root, tid, op, by=by)[0]


RELEASE_KEEPER = "agent:release-keeper"  # merges a green release for the owner (review.tend_releases)
RELEASE_VIA = "release-keeper"
RELEASE_MERGED_LINE = "Merged for you (Settings: merge releases without my click): "


def merged_for_owner(root: Path, tid: str, qid: str, url: str, head: str, line: str, decision: dict) -> dict:
    """A release Merge card that review.tend_releases merged on GitHub for the owner: record it as answered
    (Merge) by the release keeper, only while the owner turned it on (`workflow.release_merge`) and only for a
    card made with `orch ask ... --merge --release` on exactly this pull request and commit. The history says
    who did it and why; the owner's own Merge click stays the default (R4.1: a role acting for the owner)."""
    if not config.release_merge_on(root):
        raise Refused("Releases merge only on your click here. Turn it on in Settings.")

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}.")
        refuse_if_taken_back(q)
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered.")
        act = q.get("action")
        if not (isinstance(act, dict) and act.get("release") is True and act.get("merge") == url
                and act.get("head") == head):  # fmt: skip
            raise Refused(f"{qid} is not this release's Merge card.")
        q["answer"], q["answered_by"], q["via"] = "Merge", RELEASE_KEEPER, RELEASE_VIA
        q["answered_at"] = q["at"] = now()
        q["decision"] = dict(decision)
        _release_wait(root, tid, ticket, qid)
        add_history(ticket, RELEASE_KEEPER, RELEASE_MERGED_LINE + _one_line(line), RELEASE_VIA)
        history.created("answers", q)
        return q

    return apply_op(root, tid, op, by=RELEASE_KEEPER)[0]


def _one_line(text: str, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def ask_for_changes(
    root: Path,
    tid: str,
    text: str,
    by: str,
    *,
    via: str | None = None,
    phone: str | None = None,
    pid: str | None = None,
    guard=None,
    if_revision: int | None = None,
    line: str | None = None,
    extra: str | None = None,
) -> dict:
    """A person sends a Review ticket back with a note, in ONE step: the note becomes a task, the ticket is
    Ready (Working only when a run claims it) and the note is queued as the person's own input, so the
    automation host starts exactly one run for it (a person's pending input is what starts runs; #287).
    A ticket the Reviewer accepted for the person (Done) can be sent back the same way.
    The Reviewer itself (by REVIEWER) sends a Review ticket back once when work is missing (reviewer.py).
    The Auto Reviewer (ORCH-425) passes `guard` (ownerpick.refuse_auto, run inside the write), the revision it
    looked at, its own history `line` and its point-by-point line (`extra`)."""
    role = by == REVIEWER
    if (guard or if_revision is not None or line or extra) and not role:
        raise Refused("Only the Reviewer sends back this way.")
    if not role and (not by.startswith("human:") or agent_tool()):
        raise Refused("Only a person can ask for changes.")
    note = (text or "").strip()
    if not note:
        raise Refused("Say what should change.")
    if len(note) > 2000:
        raise Refused("A note for changes is at most 2000 characters.")

    def may_send_back(ticket) -> bool:
        return ticket["status"] == "review" or (not role and accepted_by_reviewer(root, ticket))

    def op(ticket):
        if not may_send_back(ticket):
            raise Refused("This ticket is not waiting for your review.")
        if guard is not None:
            guard(ticket)
        item = {"id": _next_id(ticket["checklist"], "c"), "text": note, "done": False, "evidence": []}
        if not role:
            item["origin"] = "change_request"  # structured: the dashboard shows "You asked: <note>"
        ticket["checklist"].append(item)
        ticket["status"] = "ready"  # any wait the ticket has is not this review's: left as it is
        if extra:
            add_history(ticket, by, extra, REVIEWER_VIA)
        said = line or (SENT_BACK_LINE if role else "Asked for changes: ")
        add_history(ticket, by, said + note[:200], REVIEWER_VIA if role else via)

    from orch import runs  # runs imports tickets

    if not may_send_back(load(root, tid)):
        raise Refused("This ticket is not waiting for your review.")
    # Queue the note first, then commit the ticket: a failure of either leaves nothing half done.
    item = runs.pending_add(
        root,
        tid,
        by,
        "event" if role else "message",
        note,
        REVIEWER_VIA if role else via or _env_via(),
        pid,
        phone=phone,
    )
    try:
        return apply_op(root, tid, op, by=SYSTEM, if_revision=if_revision)[0]
    except BaseException:
        runs.pending_discard(root, tid, item["id"])
        raise


def mark_working(root: Path, tid: str, by: str, agent_label: str) -> None:
    def op(ticket):
        if hidden_kind(ticket):
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
        apply_op(root, tid, op, by=SYSTEM)
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise


STOPPED_TEXT = "The helper stopped before the work was finished. Continue goes on where it left off."
# ORCH-235: a ticket moved to Working by hand that no helper ever started is To do again,
# without claiming one ran
NOT_STARTED_TEXT = "No helper started on it, so it is back in To do. Press Start to begin."


def agent_stopped(
    root: Path, tid: str, by: str, still_running=None, say: bool = True, text: str | None = None
) -> bool:
    """No agent works on the ticket any more: a Working ticket is Ready again (Working is shown only while
    an agent runs). still_running() is asked under the ticket lock, so a run that started meanwhile wins.
    Returns True when the ticket was moved."""

    def op(ticket):
        if hidden_kind(ticket):
            return NO_WRITE
        if ticket["status"] != "active" or (still_running is not None and still_running()):
            return NO_WRITE
        ticket["status"] = "ready"
        ticket["waiting_on"] = None
        if say:
            add_history(ticket, by, text or STOPPED_TEXT)
        return True

    try:
        return apply_op(root, tid, op, by=SYSTEM)[1] is True
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
        apply_op(root, tid, op, by=SYSTEM)
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
        apply_op(root, tid, op, by=SYSTEM)
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise


RECHECK_TEXT = "Please run the checks again and record them with orch check record."  # as the dashboard's
RECHECK_HINT = "Run the checks again and record them with orch check record."  # next step, never a refusal


def recheck_hint(root: Path, tid: str, status: str, by: str) -> str | None:
    """An agent sends a ticket to Review while a step's proof is changed or failed: the move goes through, and
    the command prints this as its next step. Never a block, never a loop."""
    if status != "review" or not (agent_tool() or by.startswith("agent:")):
        return None
    t = load(root, tid)
    if t.get("status") == "review" or hidden_kind(t):
        return None
    if not {"changed", "failed"} & set(proof_state(t, root)["per_item"].values()):
        return None
    return RECHECK_HINT


def superseded_value(root: Path, tid: str, other) -> str | None:
    """The ticket that replaces `tid` (Superseded: Won't do because another ticket does the work). Its id,
    from an id or a key; None clears. Refused for the ticket itself or a ticket that does not exist."""
    if other is None or other == "":
        return None
    if not isinstance(other, str):
        raise Refused("superseded_by is a ticket id or key, or null.")
    oid = resolve(root, other.strip())
    if not isinstance(oid, str) or not _ID_RE.fullmatch(oid) or not ticket_path(root, oid).is_file():
        raise Refused(f"Ticket {other} doesn't exist. Run `orch ticket list` to see your tickets.")
    if oid == tid:
        raise Refused("A ticket cannot replace itself.")
    return oid


def _keep_superseded(ticket: dict, status: str, other: str | None, given: bool) -> None:
    """superseded_by lives only on a dropped ticket: any other status clears it."""
    if status != "dropped":
        ticket.pop("superseded_by", None)
    elif given:
        if other:
            ticket["superseded_by"] = other
        else:
            ticket.pop("superseded_by", None)


def set_status(
    root: Path, tid: str, status: str, by: str, superseded_by: str | None = None, *, person: bool = False
) -> dict:
    if status not in STATUSES:
        raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
    if superseded_by is not None and status != "dropped":
        raise Refused("--superseded-by goes with the status dropped (Won't do).")
    other = superseded_value(root, tid, superseded_by) if superseded_by is not None else None

    def op(ticket):
        target, actor = _finish_status(root, ticket, status, by, person)
        _keep_superseded(ticket, target, other, superseded_by is not None)
        if other and target == "dropped":
            add_history(ticket, actor, f"Superseded by {other}")
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
        if target == "done" and old != "done":
            _note_agent_finish(ticket, actor)
        note_results(root, ticket, _result_by(by))

    return apply_op(root, tid, op, by=by)[0]  # apply_op takes the copy away of a done/closed ticket


# ------------------------------------------------------- plain fields (owner, due, note, done_when, summary)


# orch writes these itself
PROTECTED_FIELDS = (
    "title_auto",
    "plan_first",
    "epic",
    "release",
    "human_review",
    "description",
    "description_by",
    "model",
    "kind",
)


DUE_MSG = "due must be a date like 2026-11-10 or a time like 18:30."
_DUE_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?|(\d{1,2}:\d{2})")


def clean_due(text: str, today: str | None = None) -> str:
    """One spelling in the `due` field: `YYYY-MM-DD` (a day) or `YYYY-MM-DDTHH:MM` (local wall time, no
    zone). Input also takes `YYYY-MM-DD HH:MM` and `HH:MM` (= today, local). Anything else is refused."""
    m = _DUE_TIME.fullmatch(text.strip())
    if not m:
        raise Refused(DUE_MSG)
    day, hm, only = m.groups()
    if only:
        day, hm = today or datetime.now().strftime("%Y-%m-%d"), only
    try:
        datetime.strptime(day, "%Y-%m-%d")
        if hm:
            datetime.strptime(hm, "%H:%M")
    except ValueError:
        raise Refused(DUE_MSG) from None
    return f"{day}T{int(hm[:-3]):02d}:{hm[-2:]}" if hm else day


def _when_words(at: datetime, now: datetime) -> str:
    """A local time in plain words: "18:30" (today), "Mon 18:30" (within a week), "1 Dec 2026, 18:30".
    Same wording as the dashboard helper `whenWords` (web/helpers.js)."""
    gap = (at.date() - now.date()).days
    hm = at.strftime("%H:%M")
    if gap == 0:
        return hm
    if abs(gap) < 7:
        return f"{at.strftime('%a')} {hm}"
    return f"{at.day} {at.strftime('%b %Y')}, {hm}"


def due_label(due: str | None, status: str = "open", now: datetime | None = None) -> str | None:
    """The plain words for a due WITH a time: "Due 18:30" (today), "Due Mon 16 Nov, 18:30" (another day),
    "Late since 18:30" (past, ticket still active). None for no due or a date-only due (callers keep their day
    wording). Same wording as the dashboard helper `dueWords` (web/helpers.js)."""
    if not due or "T" not in str(due):
        return None
    try:
        at = datetime.strptime(str(due), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    now = now or datetime.now()
    late = at < now and status not in ("done", "dropped")
    words = _when_words(at, now)
    if 0 < abs((at.date() - now.date()).days) < 7:  # ORCH-240: which Monday? the day of the month too
        words = f"{at.strftime('%a')} {at.day} {at.strftime('%b')}, {at.strftime('%H:%M')}"
    return f"{'Late since' if late else 'Due'} {words}"


QUIET_HOURS = 6  # a working ticket with no history line for this long is "quiet" (fixed, no setting: R4.4)


def quiet_since(ticket: dict, now: datetime | None = None) -> str | None:
    """G2: the UTC time (`YYYY-MM-DDTHH:MM:SSZ`) of the newest history line (else updated/created time) when
    the ticket is Working (status active) and that is more than QUIET_HOURS ago; otherwise None. Read-only,
    computed from the history: nothing is stored. The one place the dashboard and the CLI both ask."""
    if ticket.get("status") != "active":
        return None
    stamps = [
        h.get("at")
        for h in ticket.get("history") or []
        if isinstance(h, dict) and isinstance(h.get("at"), str)
    ] or [v for v in (ticket.get("updated_at"), ticket.get("created_at")) if isinstance(v, str)]
    newest = None
    for text in stamps:
        try:
            at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if newest is None or at > newest[0]:
            newest = (at, text)
    if newest is None:
        return None
    if (now or datetime.now(UTC)) - newest[0] <= timedelta(hours=QUIET_HOURS):
        return None
    return newest[0].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


STUCK_HOURS = (
    24  # a question unanswered or a Working ticket without news this long counts as stuck (fixed: R4.4)
)


def overdue(ticket: dict, now: datetime | None = None) -> bool:
    """Past its due date (local time like the due itself): a date-only due from the next day on, a due with a
    time from that minute on; never for a finished or dropped ticket."""
    due = ticket.get("due")
    if not isinstance(due, str) or not due or ticket.get("status") in ("done", "dropped"):
        return False
    now = now or datetime.now()
    try:
        if "T" in due:
            return datetime.strptime(due, "%Y-%m-%dT%H:%M") < now.replace(tzinfo=None)
        return datetime.strptime(due, "%Y-%m-%d").date() < now.date()
    except ValueError:
        return False


def _utc(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def stuck_why(ticket: dict, now: datetime | None = None) -> str | None:
    """ORCH-189, the one Stuck rule beside a stuck helper (which only the run knows): "question" when a
    question has waited more than STUCK_HOURS, "quiet" when a Working ticket had no news that long, "overdue"
    past its due date; None otherwise and for finished, dropped or in-Review tickets. Read-only, nothing is
    stored."""
    status = ticket.get("status")
    if status in ("done", "dropped", "review"):
        return None
    if now is None:
        utc_now, local = datetime.now(UTC), None
    elif now.tzinfo is None:  # a plain time is taken as UTC here and as local time for the due date
        utc_now, local = now.replace(tzinfo=UTC), now
    else:
        utc_now, local = now.astimezone(UTC), now.astimezone().replace(tzinfo=None)
    limit = timedelta(hours=STUCK_HOURS)
    for q in ticket.get("questions") or []:
        if not isinstance(q, dict) or q.get("answer") is not None or q.get("taken_back"):
            continue
        sent = _utc(q.get("asked_at") or q.get("sent_at") or q.get("at"))
        if sent is not None and utc_now - sent > limit:
            return "question"
    since = quiet_since(ticket, utc_now)
    if since and utc_now - (_utc(since) or utc_now) > limit:
        return "quiet"
    if overdue(ticket, local):
        return "overdue"
    return None


def quiet_label(since: str | None, now: datetime | None = None) -> str | None:
    """The words "Quiet since 09:20" (local time; "Mon 09:20" on another day). None when not quiet.
    Same words as the dashboard helper `quietWords`."""
    if not since:
        return None
    try:
        at = datetime.fromisoformat(since.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None
    return f"Quiet since {_when_words(at, now or datetime.now())}"


def clean_field(key: str, value):
    """Validate a plain field (None or empty clears it); returns the value to store."""
    if key in PROTECTED_FIELDS:
        raise Refused(f"{key} is written by orch itself (orch ticket title), not set like a field.")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise Refused(f"{key} must be text.")
    v = value if key in ("note", "done_when") else value.strip()
    if key == "owner" and len(v) > 64:
        raise Refused("An owner is at most 64 characters.")
    if key == "note" and len(v) > 2000:
        raise Refused(
            f"A note is at most 2000 characters; this one has {len(v)}. Nothing was changed. "
            "Shorten it, or keep the full text as a file on the ticket: "
            "orch ticket attach <ticket> --name note.md < note.md"
        )
    if key == "done_when" and len(v) > 2000:
        raise Refused(
            f"The done criteria are at most 2000 characters; these have {len(v)}. Nothing was changed. "
            "Shorten them to one plain line and keep the details in the note."
        )
    if key == "summary" and len(v) > 200:
        raise Refused("A summary is at most 200 characters.")
    if key == "due":
        v = clean_due(v)
    return v


def _set_field(ticket: dict, key: str, value) -> None:
    v = clean_field(key, value)
    if v is None:
        ticket.pop(key, None)
    else:
        ticket[key] = v


def _edit_snip(value, limit: int = 200) -> str:
    """The old or new text of an edited field in one short line for the Activity (ORCH-185)."""
    text = " ".join(str(value or "").split())
    if not text:
        return "(empty)"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


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
            before = ticket.get("title")
            if title != before:
                ticket.pop("title_auto", None)  # a person's (or anyone's) own title is final
            ticket["title"] = title
            # ORCH-240: the Activity shows what the title was and is now
            line = "Title changed"
            if title != before:
                line += f" (was: {_edit_snip(before)} | now: {_edit_snip(title)})"
            add_history(ticket, by, line)
        was = {k: ticket.get(k) for k in fields}
        for k, v in fields.items():
            _set_field(ticket, k, v)
        if fields:
            text = "Edited " + ", ".join(sorted(fields))
            # ORCH-240: owner and due keep their old and new value too
            if len(fields) == 1 and next(iter(fields)) in ("note", "done_when", "owner", "due"):
                k = next(iter(fields))
                text += f" (was: {_edit_snip(was[k])} | now: {_edit_snip(ticket.get(k))})"  # ORCH-185
            add_history(ticket, by, text)

    return apply_op(root, tid, op, if_revision=if_revision, by=by)[0]


def set_release(root: Path, tid: str, on: bool, by: str, if_revision: int | None = None) -> dict:
    """ORCH-37: mark a ticket as a release (the epics and tickets that ship together sit under it, put there
    with set_parent) or take the mark off. Its sub-tickets stay where they are either way."""
    me = load(root, tid)
    if bool(me.get("release")) == on:
        return me  # nothing changes: no write, no history line

    def op(ticket):
        if on:
            ticket["release"] = True
        else:
            ticket.pop("release", None)
        add_history(ticket, by, "Marked as a release" if on else "No longer a release")

    return apply_op(root, tid, op, if_revision=if_revision, by=by)[0]


def human_review(ticket: dict) -> bool:
    """ORCH-424: the Human review needed switch. On unless a person turned it off (the field is False only
    then), so a ticket made before the switch existed counts as on. While it is on, the Auto Reviewer and Away
    mode leave the ticket alone (ownerpick.refuse_auto; owner 18 Nov). The plain Reviewer ignores it."""
    return ticket.get("human_review") is not False


HUMAN_REVIEW_ON = "Human review needed: on"
HUMAN_REVIEW_OFF = "Human review needed: off"


def set_human_review(root: Path, tid: str, on: bool, by: str, if_revision: int | None = None) -> dict:
    """ORCH-424: turn the Human review needed switch on or off. Who may turn it off is checked by the caller
    (only a person: `orch ticket edit --human-review no`, the dashboard, a paired phone)."""
    me = load(root, tid)
    if human_review(me) == on:
        return me  # nothing changes: no write, no history line

    def op(ticket):
        if on:
            ticket.pop("human_review", None)
        else:
            ticket["human_review"] = False
        add_history(ticket, by, HUMAN_REVIEW_ON if on else HUMAN_REVIEW_OFF)

    return apply_op(root, tid, op, if_revision=if_revision, by=by)[0]


PRIORITIES = ("high", "normal", "low")  # ORCH-813: the order waiting tickets start in (then the oldest first)


def priority(ticket: dict) -> str:
    """ORCH-813: the ticket's priority, high, normal or low. No field means normal (older tickets too)."""
    p = ticket.get("priority")
    return p if p in PRIORITIES else "normal"


def set_priority(root: Path, tid: str, value: str, by: str, if_revision: int | None = None) -> dict:
    """ORCH-813: set the ticket's priority. Higher priority tickets start first when helpers wait for a free
    slot (runs_live.waiting_line). Normal is stored as no field."""
    if value not in PRIORITIES:
        raise Refused("The priority is high, normal or low.")
    me = load(root, tid)
    if priority(me) == value and (if_revision is None or me.get("revision") == if_revision):
        return me  # nothing changes: no write, no history line (a stale revision is still refused below)

    def op(ticket):
        if priority(ticket) == value:
            return
        if value == "normal":
            ticket.pop("priority", None)
        else:
            ticket["priority"] = value
        add_history(ticket, by, f"Priority: {value}")

    return apply_op(root, tid, op, if_revision=if_revision, by=by)[0]


PARENT_DEPTH = 50  # a parent chain longer than this is broken data: never followed further


def set_parent(root: Path, tid: str, parent: str | None, by: str, if_revision: int | None = None) -> dict:
    """ORCH-156: put a ticket that already exists under another one (an epic, a release) or take it out
    (`parent` None or empty). Refused: itself, a ticket that does not exist, or one of its own sub-tickets
    (a loop). One history line on the ticket and one on each parent it joins or leaves."""
    me = load(root, tid)
    new = None
    if isinstance(parent, str) and parent.strip():
        if parent.strip() in (me["id"], me.get("key")):
            raise Refused("A ticket cannot be part of itself.")
        new = load(root, parent.strip())
        by_id = {t["id"]: t for t in list_all(root)}
        seen, cur = set(), new
        while cur is not None and cur["id"] not in seen and len(seen) < PARENT_DEPTH:
            if cur["id"] == me["id"]:
                raise Refused(
                    f"{_parent_words(new)} is inside this ticket already, so it cannot hold this ticket."
                )
            seen.add(cur["id"])
            cur = by_id.get(str(cur.get("parent") or ""))
    old_id = me.get("parent")
    if (new["id"] if new else None) == (old_id or None):
        return me  # nothing changes: no write, no history line
    try:
        old = load(root, old_id) if old_id else None
    except (Refused, OSError, ValueError):
        old = None  # a parent that is gone: taking the ticket out still works

    def op(ticket):
        if new is None:
            ticket.pop("parent", None)
            add_history(ticket, by, "Taken out of " + (_parent_words(old) if old else str(old_id)))
        else:
            ticket["parent"] = new["id"]
            add_history(ticket, by, "Put under " + _parent_words(new))

    t = apply_op(root, tid, op, if_revision=if_revision, by=by)[0]
    me_words = _parent_words(t)
    for other, words in ((old, f"{me_words} moved out"), (new, f"{me_words} added")):
        if other is None:
            continue
        try:  # the parent's line is a courtesy: the ticket itself is already saved
            apply_op(root, other["id"], lambda p, w=words: add_history(p, by, w), by=by)
        except (Refused, OSError, ValueError):
            pass
    return t


LANE_RE = re.compile(r"^[a-z][a-z_]{0,23}$")
MAX_ORDER = 500


def set_lane_order(root: Path, lane: str, ids: list[str], by: str) -> list[dict]:
    """ORCH-156: the order of the tickets inside one board lane (To do, Backlog ...), first to last. Each
    listed ticket keeps {lane, n}; the board uses it only while the ticket is still in that lane, so a ticket
    that moves on needs no clean-up. Only tickets whose place changed are written (no history line: the order
    is how the board shows them, not news about the work). Returns the tickets that changed."""
    if not isinstance(lane, str) or not LANE_RE.match(lane):
        raise Refused("A lane is a short name such as todo or backlog.")
    if not ids:
        raise Refused("Name the tickets of the lane, first to last.")
    if len(ids) > MAX_ORDER:
        raise Refused(f"At most {MAX_ORDER} tickets can be put in order at once.")
    if len(set(ids)) != len(ids):
        raise Refused("A ticket is named twice; name each ticket once.")
    now_at = [load(root, tid).get("lane_order") for tid in ids]  # every ticket exists before any write
    changed = []
    for n, (tid, was) in enumerate(zip(ids, now_at, strict=True), start=1):
        want = {"lane": lane, "n": n}
        if was != want:
            changed.append(apply_op(root, tid, lambda t, w=want: t.__setitem__("lane_order", w), by=by)[0])
    return changed


LONG_NOTE = (
    "The full text is attached as note.md. Read it, then give this ticket a short title and description."
)
PLACEHOLDER_TITLE = 80  # characters of a person's text kept as the title until the agent writes one


_TITLE_ABBR = re.compile(
    r"(?:^|\s)(?:e\.\s?g\.|i\.\s?e\.|etc\.|z\.\s?B\.|d\.\s?h\.|u\.\s?a\.|bzw\.|vs\.|ca\.|approx\.)$", re.I
)


_TITLE_TAIL = re.compile(  # a cut never ends on a small word
    r"\s(?:and|or|but|then|for|to|of|the|a|an|with|in|on|at|by|like|und|oder|dann|für|mit|der|die|das|zu)$",
    re.I,
)


def cut_title(line: str, limit: int = PLACEHOLDER_TITLE) -> str:
    """ORCH-62: a line longer than `limit` is cut at a whole word, never right after an abbreviation such as
    "e.g." (it read like the end of a sentence), and ends with "…" so it reads as cut. The dashboard's New
    ticket dialog cuts the same way (ticketTextTitle)."""
    if len(line) <= limit:
        return line
    cut = line[: limit - 1]
    space = cut.rfind(" ")
    if line[limit - 1] != " " and space > limit / 2:
        cut = cut[:space]
    prev = None
    while prev != cut:
        prev = cut
        cut = re.sub(r"[\s,;:.\-–—(]+$", "", _TITLE_ABBR.sub("", cut))
        if len(cut) > limit / 2:
            cut = _TITLE_TAIL.sub("", cut)
    return (cut or line[: limit - 1].strip()) + "…"


def placeholder_title(text: str) -> str:
    """The first words of what a person wrote, on one line: the title until the agent writes the real one."""
    first = next((x for x in clean_untrusted(str(text), 4000).splitlines() if x.strip()), "")
    return cut_title(" ".join(first.split())).strip() or "New ticket"


def needs_agent_title(text: str) -> bool:
    """Short one-line text is its own title. A long or multi-line text gets a title from the agent."""
    lines = [x for x in clean_untrusted(str(text), 100000).splitlines() if x.strip()]
    return (
        len(lines) > 1
        or len(" ".join(lines[0].split()) if lines else "") > PLACEHOLDER_TITLE
        or len(text) > LONG_TEXT
    )


def create_from_input(
    root: Path,
    text: str,
    by: str,
    parent: str | None = None,
    fields: dict | None = None,
    ext: dict[str, dict] | None = None,
    human_review: bool | None = None,
) -> dict:
    """THE way a ticket is made from what a person wrote or said (dashboard paste box, phone text, Open
    agent): the title is the first words (a placeholder, flag `title_auto`, when the text is long or has
    several lines)
    and the agent writes the real title and the description first (runs.fresh_prompt, `orch ticket title`)."""
    return create(
        root,
        placeholder_title(text),
        by,
        parent,
        ext,
        fields,
        title_auto=needs_agent_title(text),
        human_review=human_review,
    )


def set_auto_title(root: Path, tid: str, title: str, by: str, description: str | None = None) -> dict:
    """The agent's real title (and its description, in its own field) for a placeholder ticket.
    Refused when a person set the title (or it was never a placeholder): a person's title is never
    overwritten."""
    title = title.strip()
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    if description is not None:
        clean_field("note", description)  # the same plain-text rules and 2000 characters

    def op(ticket):
        if not ticket.get("title_auto"):
            raise Refused("This title was set by a person (or already written). It is left as it is.")
        ticket["title"] = title
        ticket.pop("title_auto", None)
        add_history(ticket, by, "Title written")
        if description:
            # The description is the agent's own field: it is never merged into the person's note (the
            # note is shown and sent to the agent as "the person's words"). Only the placeholder note goes.
            ticket["description"] = description
            ticket["description_by"] = by[:100]
            if ticket.get("note") == LONG_NOTE:
                ticket.pop("note", None)
            add_history(ticket, by, f"Description written by {by[:100]}")

    return apply_op(root, tid, op, by=by)[0]


TIDY_LINE = "Title tidied from: "


def tidied(root: Path, ticket: dict) -> bool:
    lines = history.lines(root, ticket)
    # An unverified (synced) line shows with a display prefix; the stored text is what marks "tidied".
    texts = (str(h.get("text", "")).removeprefix(history.SYNCED_UNVERIFIED) for h in lines)
    return any(t.startswith((TIDY_LINE, "Ticket tidied")) for t in texts)


# Prepare on Save without starting (ORCH-738, draft ORCH-730 section 3): a prepare-only helper run fills the
# ticket and stops; the ticket stays in Backlog. `prepare` on the ticket says where that stands.
PREPARE_STATES = ("waiting", "preparing", "prepared", "not_prepared")
PREPARED_LINE = "Prepared: title, description, done-when, estimate and suggested steps"
NOT_PREPARED = "Not prepared yet"


def set_prepare(
    root: Path,
    tid: str,
    state: str,
    by: str,
    why: str | None = None,
    run: str | None = None,
    line: str | None = None,
) -> bool:
    """Write where the prepare run stands. Prepared and Not prepared yet get one history line. Only a ticket
    still in Backlog changes: one a person or a helper moved on meanwhile keeps its newer state, and an older
    run's result never overwrites a newer run's. Returns True when written."""
    if state not in PREPARE_STATES:
        raise ValueError(state)

    def op(ticket):
        if hidden_kind(ticket) or ticket.get("status") != "open":
            return NO_WRITE
        cur = ticket.get("prepare") if isinstance(ticket.get("prepare"), dict) else {}
        if run and cur.get("run") and cur["run"] != run and state in ("prepared", "not_prepared"):
            return NO_WRITE
        rec: dict = {"state": state, "at": now()}
        if run:
            rec["run"] = run
        if why:
            rec["why"] = " ".join(str(why).split())[:200]
        if state == "prepared":  # what Prepare left, so Start can tell what changed since (ORCH-739)
            rec["seen"] = _prepare_seen(root, ticket)
        ticket["prepare"] = rec
        if state == "prepared":
            add_history(ticket, by, PREPARED_LINE)
        elif state == "not_prepared":
            add_history(ticket, by, f"{NOT_PREPARED}: {rec['why']}" if why else NOT_PREPARED)
        elif line:  # waiting or preparing: a line for the Activity, written with the note
            add_history(ticket, by, line)
        return True

    # waiting and preparing are a background note (with at most the line saying so): the revision stays, so a
    # person who opens the ticket right after Save can still change it (their later edit wins)
    quiet = state in ("waiting", "preparing")
    try:
        return apply_op(root, tid, op, by=SYSTEM, keep_revision=quiet)[1] is True
    except (Refused, FileNotFoundError):
        if ticket_path(root, tid).exists():
            raise
        return False


_PREPARE_FIELDS = (
    ("title", "Title"),
    ("note", "The person's note"),
    ("description", "Description"),
    ("done_when", "Done when"),
    ("due", "Due date"),
    ("owner", "Owner"),
)
_SEEN_FILES_MAX = 200
# lines that only say the work started (the Start itself), not something the helper must react to
_START_NOISE = re.compile(r"^(Status \S+ -> \S+|\S+( \S+)? started|" + re.escape(PREPARED_LINE) + r")$")


def _artifact_names(root: Path, tid: str) -> list[str]:
    """The files in the ticket's artifacts folder (relative names, sorted, capped); [] when there is none.
    Read only: never creates the folder, never follows a link."""
    d = artifacts_path(root, tid)
    try:
        if d.is_symlink() or not d.is_dir():
            return []
        names = sorted(
            p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and not p.is_symlink()
        )
    except OSError:
        return []
    return names[:_SEEN_FILES_MAX]


def _prepare_seen(root: Path, ticket: dict) -> dict:
    """The ticket as Prepare left it: its fields, its steps and its files (ORCH-739)."""
    seen: dict = {k: ticket.get(k) for k, _ in _PREPARE_FIELDS if ticket.get(k) not in (None, "")}
    seen["checks"] = {
        str(c.get("id")): str(c.get("text") or "")
        for c in ticket.get("checklist") or []
        if isinstance(c, dict) and c.get("id")
    }
    seen["files"] = _artifact_names(root, ticket["id"])
    seen["lines"] = history.length(ticket)  # lines from here on came after Prepare
    return seen


def _short(v: object, n: int = 300) -> str:
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def changed_since_prepare(root: Path, ticket: dict, agent: str | None = None) -> list[str] | None:
    """What changed on a prepared ticket since Prepare ended, one plain line each: a field a person edited,
    steps added, removed or reworded, new files, and what others wrote on the ticket since (answers,
    messages). [] = nothing changed; None = the ticket was never marked Prepared (no record to compare).
    agent: the helper's own label (agent:<name>), whose own lines are left out."""
    p = ticket.get("prepare") if isinstance(ticket.get("prepare"), dict) else {}
    seen = p.get("seen") if p.get("state") == "prepared" else None
    if not isinstance(seen, dict):
        return None
    out: list[str] = []
    for key, label in _PREPARE_FIELDS:
        old, new = seen.get(key), ticket.get(key)
        if old in (None, "") and new in (None, ""):
            continue
        if old == new:
            continue
        if old in (None, ""):
            out.append(f"{label} added: {_short(new)}")
        elif new in (None, ""):
            out.append(f"{label} removed (was: {_short(old)})")
        else:
            out.append(f"{label} changed from: {_short(old)} | to: {_short(new)}")
    old_checks = seen.get("checks") if isinstance(seen.get("checks"), dict) else {}
    now_checks = {
        str(c.get("id")): c for c in ticket.get("checklist") or [] if isinstance(c, dict) and c.get("id")
    }
    for cid, c in now_checks.items():
        text = str(c.get("text") or "")
        if cid not in old_checks:
            out.append(f"Step added: {cid} {_short(text, 200)}")
        elif old_checks[cid] != text:
            out.append(f"Step {cid} reworded from: {_short(old_checks[cid], 200)} | to: {_short(text, 200)}")
    for cid, text in old_checks.items():
        if cid not in now_checks:
            out.append(f"Step removed: {cid} {_short(text, 200)}")
    old_files = set(seen.get("files") or [])
    new_files = [f for f in _artifact_names(root, ticket["id"]) if f not in old_files]
    if new_files:
        shown = ", ".join(_short(f, 200) for f in new_files[:20])  # a name is one plain line, never more
        out.append("New files: " + shown + (" …" if len(new_files) > 20 else ""))
    lines = history.lines(root, ticket)
    start = seen.get("lines")
    if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= len(lines):
        since = str(p.get("at") or "")  # no position kept (or the history was cut): by time, strictly after
        lines = [h for h in lines if isinstance(h, dict) and str(h.get("at") or "") > since]
    else:
        lines = lines[start:]
    said = []
    for h in lines:
        if not isinstance(h, dict):
            continue
        by, text = str(h.get("by") or "?"), str(h.get("text") or "")
        if (agent and by == agent) or by in (SYSTEM, "orch") or _START_NOISE.match(text):
            continue
        said.append(f"{by}: {_short(text)}")
    if said:
        out.append("Written on the ticket since:\n" + "\n".join(f"  - {s}" for s in said[-10:]))
    return out


def worked_since_prepare(root: Path, ticket: dict, agent: str | None) -> bool:
    """True once the helper (agent:<name>) wrote on the ticket after Prepare ended: the first Start after
    Prepare is over, so later runs are not told again that preparing ended or what changed (ORCH-739)."""
    p = ticket.get("prepare") if isinstance(ticket.get("prepare"), dict) else {}
    if not agent or not p.get("state"):
        return False
    lines = history.lines(root, ticket)
    seen = p.get("seen") if isinstance(p.get("seen"), dict) else {}
    start = seen.get("lines")
    if isinstance(start, int) and not isinstance(start, bool) and 0 <= start <= len(lines):
        after = lines[start:]
    else:  # Not prepared yet (no position kept): by time, strictly after
        since = str(p.get("at") or "")
        after = [h for h in lines if isinstance(h, dict) and str(h.get("at") or "") > since]
    since = str(p.get("at") or "")
    checklist = history.shown_ticket(root, ticket).get("checklist") or []  # who marked a step, as proven
    if any(  # a helper started or finished a step since Prepare ended (starting one writes no history line;
        # Prepare itself starts and finishes none, so the same second counts); a person's tick is a change
        isinstance(c, dict)
        and (c.get("state") == "doing" or c.get("done"))
        and not str(c.get("by") or "").startswith("human:")
        and str(c.get("at") or "") >= since
        for c in checklist
    ):
        return True
    return any(
        isinstance(h, dict)
        and h.get("by") == agent
        and not _START_NOISE.match(str(h.get("text") or ""))
        and not str(h.get("text") or "").startswith(NOT_PREPARED)
        for h in after
    )


def prepare_state(root: Path, ticket: dict) -> dict | None:
    """Where Prepare stands for a reader ({"state", "words", "why"?}), or None when it never ran. A ticket in
    Backlog still marked preparing or waiting whose run is gone and that waits in no line was left by a run
    that died: it reads Not prepared yet (Prepare fails quietly; Start still works)."""
    p = ticket.get("prepare")
    if not isinstance(p, dict) or p.get("state") not in PREPARE_STATES:
        return None
    state, why = p["state"], p.get("why")
    if state in ("waiting", "preparing", "not_prepared") and ticket.get("status") != "open":
        return None  # a person started the work meanwhile: Prepare is over, nothing to show
    if state in ("waiting", "preparing"):
        from orch import runs, runs_live

        try:
            gone = not runs.running(root, ticket["id"]) and ticket["id"] not in {
                t for t, _ in runs_live.waiting_line(root)
            }
        except Exception:  # noqa: BLE001 - a reader never fails on this
            gone = False
        if gone:
            state, why = "not_prepared", "the helper stopped"
    words = {
        "waiting": "Waits in line to be prepared",
        "preparing": "Preparing",
        "prepared": "Prepared",
        "not_prepared": NOT_PREPARED,
    }[state]
    return {"state": state, "words": words, **({"why": why} if why else {})}


def _minutes_words(m: int) -> str:
    return (f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")) if m >= 60 else f"{m} min"


def _ok_minutes(m: object) -> bool:
    return isinstance(m, int) and not isinstance(m, bool) and m > 0


def _ok_cost(c: object) -> bool:
    return isinstance(c, int | float) and not isinstance(c, bool) and c >= 0


def estimate_words(est: object) -> str:
    """ "about 45 min · $2.00" for a stored estimate, "about 30-60 min · $2.00-$5.00" for a range (ORCH-740);
    "" for none."""
    if not isinstance(est, dict):
        return ""
    m, cost = est.get("minutes"), est.get("cost")
    lo_m, lo_c = est.get("minutes_low"), est.get("cost_low")
    parts = []
    if _ok_minutes(m):
        if _ok_minutes(lo_m) and lo_m < m:
            parts.append(f"{lo_m}-{m} min" if m < 120 else f"{_minutes_words(lo_m)} - {_minutes_words(m)}")
        else:
            parts.append(_minutes_words(m))
    if _ok_cost(cost):
        parts.append(f"${lo_c:,.2f}-${cost:,.2f}" if _ok_cost(lo_c) and lo_c < cost else f"${cost:,.2f}")
    return "about " + " · ".join(parts) if parts else ""


def parse_range(text: object, kind: str):
    """ "45" -> 45, "30-60" -> (30, 60) for --estimate-minutes / --estimate-cost (ORCH-740: an estimate is a
    range). Minutes are whole numbers, dollars may have cents. None stays None."""
    if text is None or isinstance(text, int | float | tuple):
        return text
    s = str(text).strip().replace("$", "").replace(" ", "").replace("–", "-")
    num = r"\d+" if kind == "minutes" else r"\d*\.?\d+"
    m = re.fullmatch(rf"({num})(?:-({num}))?", s)
    if not m:
        what = "whole minutes" if kind == "minutes" else "dollars"
        raise Refused(f"Give the estimate in {what}, one number (45) or a range (30-60).")
    conv = int if kind == "minutes" else float
    lo = conv(m.group(1))
    if m.group(2) is None:
        return lo
    hi = conv(m.group(2))
    if hi < lo:
        raise Refused("A range starts with the smaller number: 30-60, not 60-30.")
    return lo if hi == lo else (lo, hi)


def _estimate(minutes: object, cost: object) -> dict | None:
    """ORCH-189: the helper's own estimate from its first run (helper minutes, dollars at list price).
    Either may be a (low, high) range (ORCH-740): stored as minutes/cost = the high end, so every older
    reader keeps a number, and minutes_low/cost_low = the low end."""
    if minutes is None and cost is None:
        return None
    out: dict = {}
    for name, value in (("minutes", minutes), ("cost", cost)):
        if value is None:
            continue
        lo, hi = value if isinstance(value, tuple) else (None, value)
        for v in (lo, hi):
            if v is None:
                continue
            if name == "minutes" and (not isinstance(v, int) or isinstance(v, bool) or not 0 < v <= 100_000):
                raise Refused("An estimate needs whole minutes between 1 and 100000.")
            if name == "cost" and (
                not isinstance(v, int | float) or isinstance(v, bool) or not 0 <= v <= 100_000
            ):
                raise Refused("An estimated cost needs dollars between 0 and 100000.")
        if lo is not None and lo > hi:
            raise Refused("A range starts with the smaller number: 30-60, not 60-30.")
        out[name] = hi if name == "minutes" else round(float(hi), 2)
        if lo is not None and lo != hi:
            out[f"{name}_low"] = lo if name == "minutes" else round(float(lo), 2)
    return out


# ORCH-645 (owner 18 Nov): what kind of work a ticket is. The tidy helper sets it; the Reviewer accepts work
# by itself only for the kinds the workspace lists (workflow.reviewer_kinds), never a draft.
KINDS = {
    "bug": "Bug",
    "small_bug": "Small bug",
    "feature": "New feature",
    "small_feature": "Small feature",
    "draft": "Draft or design",
    "other": "Other",
}


def clean_kind(name) -> str:
    name = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if name not in KINDS:
        raise Refused("Pick a kind: " + ", ".join(KINDS) + ".")
    return name


def kind(ticket: dict) -> str | None:
    """The ticket's kind, or None (not set yet, or a value orch does not know)."""
    k = ticket.get("kind") if isinstance(ticket, dict) else None
    name = k.get("name") if isinstance(k, dict) else None
    return name if name in KINDS else None


def kind_by_person(ticket: dict) -> bool:
    k = ticket.get("kind")
    return kind(ticket) is not None and str(k.get("by") or "").startswith("human:")


def _put_kind(ticket: dict, name: str, by: str) -> bool:
    """Set the kind (a history line); False when it already is that. A person's kind stays: only a person
    changes it."""
    if kind(ticket) == name:
        return False
    old = kind(ticket)
    person = _is_person(by)
    ask = (
        f'Ask instead: orch ask {ticket.get("id", "<id>")} "Change the kind to {KINDS[name]}?" '
        "--option yes --option no"
    )
    if not person:
        if kind_by_person(ticket):
            raise Refused(f"A person set this ticket's kind ({KINDS[old]}); only a person changes it. {ask}")
        if old == "draft":  # a helper never turns a draft into work the Reviewer may accept
            raise Refused(f"Only a person moves a ticket out of Draft or design. {ask}")
        if ticket.get("status") in ("review", "done", "dropped"):
            raise Refused(f"The work is finished: only a person changes its kind now. {ask}")
        if by.startswith(
            "human:"
        ):  # --by human:... from inside a helper: stored as the helper (never a lock)
            by = "agent:" + str(agent_tool() or "helper")
    ticket["kind"] = {"name": name, "by": by[:100]}
    add_history(ticket, by, f"Kind: {KINDS[name]}" + (f" (was: {KINDS[old]})" if old else ""))
    return True


def set_kind(root: Path, tid: str, name: str, by: str) -> dict:
    """`orch ticket kind`: change what kind of work the ticket is."""
    name = clean_kind(name)

    def op(ticket):
        if not _put_kind(ticket, name, by):
            raise Refused(f"This ticket already is: {KINDS[name]}.")

    return apply_op(root, tid, op, by=by)[0]


def tidy(
    root: Path,
    tid: str,
    title: str,
    by: str,
    fields: dict | None = None,
    description: str | None = None,
    estimate: dict | None = None,
    extra: dict | None = None,
    kind_name: str | None = None,
) -> dict:
    """Tidy a new ticket when work starts, without asking: a short clear title (the person's own words stay in
    the history: "Title tidied from: ...") and owner / due / done_when,
    filled only where still empty, and the agent's description (what and why, its own field, never the
    person's note) when there is none yet, and the helper's time and cost estimate (ORCH-189: made in the same
    first run, shown on the ticket) when there is none yet. Once.
    extra (Prepare, ORCH-740), each filled only while empty: asked_by (who asked for the work, e.g. the sender
    of the email), maybe_same (a ticket that looks like the same work: shown, never merged) and needs_ok (what
    the plan will need the person's OK for)."""
    title = title.strip()
    est = _estimate((estimate or {}).get("minutes"), (estimate or {}).get("cost"))
    if not title or len(title) > 200:
        raise Refused("A title needs 1 to 200 characters.")
    description = (description or "").strip() or None
    if description is not None:
        clean_field("note", description)  # the same plain-text rules and 2000 characters
    fields = {k: v for k, v in (fields or {}).items() if k in ("owner", "due", "done_when") and v}
    for k, v in fields.items():
        clean_field(k, v)
    more = _prepare_fields(root, tid, extra or {})
    kind_name = clean_kind(kind_name) if kind_name else None

    def op(ticket):
        if tidied(root, ticket):
            raise Refused("This ticket was already tidied.")
        old = str(ticket.get("title") or "")
        was_auto = bool(ticket.get("title_auto"))
        edited = any(  # someone renamed it after it was created: that title is theirs, tidy leaves it
            re.fullmatch(
                r"Title changed(?: \(was: .* \| now: .*\))?",
                str(h.get("text", "")).removeprefix(history.SYNCED_UNVERIFIED),
                re.DOTALL,
            )
            for h in history.lines(root, ticket)
        )
        if title != old and not edited:
            ticket["title"] = title
            ticket.pop("title_auto", None)
            add_history(ticket, by, TIDY_LINE + old[:200])
        elif was_auto and not edited:  # the helper kept the placeholder's words: now they are its title
            ticket.pop("title_auto", None)
        filled = [k for k in sorted(fields) if not ticket.get(k)]
        for k in filled:
            _set_field(ticket, k, fields[k])
        if filled:
            add_history(ticket, by, "Details filled in: " + ", ".join(filled))
        wrote = bool(description and not ticket.get("description"))
        if wrote:
            ticket["description"] = description
            ticket["description_by"] = by[:100]
            if was_auto and ticket.get("note") == LONG_NOTE:  # only the placeholder note goes (as `title`)
                ticket.pop("note", None)
            add_history(ticket, by, f"Description written by {by[:100]}")
        estimated = bool(est and not ticket.get("estimate"))
        if estimated:
            ticket["estimate"] = {**est, "by": by[:100], "at": now()}
            add_history(ticket, by, "Estimate: " + estimate_words(est))
        added = [k for k in PREPARE_FIELDS if k in more and not ticket.get(k)]
        for k in added:
            ticket[k] = more[k]
            add_history(ticket, by, PREPARE_FIELDS[k] + ": " + _field_words(root, k, more[k]))
        kinded = bool(kind_name and not kind(ticket) and _put_kind(ticket, kind_name, by))
        if (
            (title == old or edited)
            and not filled
            and not wrote
            and not estimated
            and not added
            and not kinded
        ):
            add_history(ticket, by, "Ticket tidied: nothing to change")

    return apply_op(root, tid, op, by=by)[0]


# Prepare (ORCH-740, accepted draft ORCH-730 2a/2b): what the helper fills besides tidy's fields.
PREPARE_FIELDS = {"asked_by": "Asked by", "maybe_same": "Maybe the same as", "needs_ok": "Needs your OK for"}
PREPARED_PREFIX = "Prepared:"
FOUND_MAX_SOURCES = 20
FOUND_MAX_FACTS = 10


def _plain(value: object, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"{what} must be text.")
    v = " ".join(value.split())
    if len(v) > limit:
        raise Refused(f"{what} is at most {limit} characters; this one has {len(v)}. Shorten it.")
    return v


def _prepare_fields(root: Path, tid: str, extra: dict) -> dict:
    """Check tidy's Prepare fields before anything is written: plain text with limits, maybe_same a real
    ticket other than this one (open or closed), no secret in any of them (R5.2)."""
    out: dict = {}
    if extra.get("asked_by"):
        out["asked_by"] = _plain(extra["asked_by"], "Asked by", 100)
    if extra.get("needs_ok"):
        out["needs_ok"] = _plain(extra["needs_ok"], "Needs your OK for", 300)
    if extra.get("maybe_same"):
        ref = str(extra["maybe_same"]).strip()
        try:
            other = load(root, resolve(root, ref))["id"]
        except (Refused, OSError, ValueError, KeyError):
            raise Refused(
                f"No ticket {ref} here: name an existing ticket for --maybe-same (orch ticket list)."
            ) from None
        if other == resolve(root, tid):
            raise Refused("A ticket cannot be the same as itself: leave --maybe-same out.")
        out["maybe_same"] = other
    if out:
        from orch import secretscan

        secretscan.refuse_if_secret_in(root, {k: v for k, v in out.items()}, "ticket", verb="saved")
    return out


def _field_words(root: Path, key: str, value: str) -> str:
    if key == "maybe_same":
        with contextlib.suppress(Exception):
            o = load(root, value)
            return f"{o.get('key') or value} {o.get('title', '')}".strip()
    return value


def _found_text(value: object, what: str, limit: int, *, optional: bool = False) -> str | None:
    if optional and (value is None or (isinstance(value, str) and not value.strip())):
        return None
    return _plain(value, what, limit)


def clean_found(data: object) -> dict:
    """The "What I found" part (ORCH-740) as a helper gives it, checked whole before anything is written:
    {"sources": [{"name", "link"?, "lines"} or {"name", "link"?, "could_not_open": "<why>"}], "facts": [...]}.
    Returns the stored shape (sources with opened true/false)."""
    if not isinstance(data, dict):
        raise Refused('What I found must be a JSON object: {"sources": [...], "facts": [...]}.')
    unknown = sorted(set(data) - {"sources", "facts"})
    if unknown:
        raise Refused(f"What I found takes only sources and facts, not {', '.join(unknown)}.")
    sources, facts = data.get("sources") or [], data.get("facts") or []
    if not isinstance(sources, list) or not isinstance(facts, list):
        raise Refused("sources and facts must be lists.")
    if not sources:
        raise Refused(
            "What I found needs at least one source: every link, file or message the ticket points to, "
            "read or not."
        )
    if len(sources) > FOUND_MAX_SOURCES:
        raise Refused(f"What I found keeps at most {FOUND_MAX_SOURCES} sources; this has {len(sources)}.")
    if len(facts) > FOUND_MAX_FACTS:
        raise Refused(f"What I found keeps at most {FOUND_MAX_FACTS} key facts; this has {len(facts)}.")
    out_sources = []
    for i, src in enumerate(sources, 1):
        if not isinstance(src, dict):
            raise Refused(f"Source {i} must be an object with name and lines (or could_not_open).")
        bad = sorted(set(src) - {"name", "link", "lines", "could_not_open"})
        if bad:
            raise Refused(f"Source {i} takes name, link, lines or could_not_open, not {', '.join(bad)}.")
        rec: dict = {"name": _plain(src.get("name"), f"Source {i} name", 120)}
        link = _found_text(src.get("link"), f"Source {i} link", 500, optional=True)
        if link:
            rec["link"] = link
        why = _found_text(src.get("could_not_open"), f"Source {i} could_not_open", 200, optional=True)
        lines = _found_text(src.get("lines"), f"Source {i} lines", 300, optional=True)
        if why and lines:
            raise Refused(f"Source {i}: give lines (it was read) or could_not_open (it was not), not both.")
        if why:
            rec.update(opened=False, why=why)
        elif lines:
            rec.update(opened=True, lines=lines)
        else:
            raise Refused(
                f"Source {i} needs lines (one or two lines of what it says) or could_not_open (why not)."
            )
        out_sources.append(rec)
    out_facts = [_plain(f, f"Fact {i}", 300) for i, f in enumerate(facts, 1)]
    return {"sources": out_sources, "facts": out_facts}


def found_counts(found: object) -> tuple[int, int]:
    """(read, could not open) of a stored What I found part."""
    src = found.get("sources") if isinstance(found, dict) else None
    src = [s for s in src or [] if isinstance(s, dict)]
    read = sum(1 for s in src if s.get("opened") is True)
    return read, len(src) - read


def sources_words(found: object) -> str:
    """ "2 sources read, 1 could not be opened" (ORCH-740)."""
    read, missed = found_counts(found)
    words = f"{read} source{'s' if read != 1 else ''} read"
    return words + (f", {missed} could not be opened" if missed else "")


def prepare_lines(ticket: dict, root: Path | None = None) -> list[str]:
    """What Prepare added, as plain lines for `orch ticket show` and a later helper's start text (ORCH-740):
    Asked by, Maybe the same as, Needs your OK for, and the What I found part with Could not open."""
    out = []
    for k, label in PREPARE_FIELDS.items():
        v = ticket.get(k)
        if isinstance(v, str) and v:
            out.append(f"{label}: " + (_field_words(root, k, v) if root is not None else v))
    found = ticket.get("found")
    if isinstance(found, dict):
        src = [x for x in found.get("sources") or [] if isinstance(x, dict)]
        read = [x for x in src if x.get("opened") is True]
        missed = [x for x in src if x.get("opened") is not True]
        lines = ["What I found:"]
        lines += [
            f"  - {x.get('name', '?')}"
            + (f" ({x['link']})" if x.get("link") else "")
            + f": {x.get('lines', '')}"
            for x in read
        ]
        lines += [f"  * {f}" for f in found.get("facts") or [] if isinstance(f, str)]
        if missed:
            lines.append("Could not open:")
            lines += [
                f"  - {x.get('name', '?')}"
                + (f" ({x['link']})" if x.get("link") else "")
                + f": {x.get('why', '')}"
                for x in missed
            ]
        out.append("\n".join(lines))
    return out


def set_found(root: Path, tid: str, data: object, by: str) -> dict:
    """Write the ticket's What I found part (ORCH-740): what Prepare read from the sources the ticket points
    to,
    one or two lines each with its link, the key facts, and the sources it could not open with the reason.
    A later call replaces it whole (the helper gathered again). Information, never instructions: later helpers
    get it labelled as such. Nothing with a secret in it is written (R5.2)."""
    found = clean_found(data)
    from orch import secretscan

    secretscan.refuse_if_secret_in(root, found, "What I found part", verb="saved")

    def op(ticket):
        again = isinstance(ticket.get("found"), dict)
        ticket["found"] = {**found, "by": by[:100], "at": now()}
        add_history(
            ticket,
            by,
            ("What I found, gathered again: " if again else "What I found: ") + sources_words(found),
        )

    return apply_op(root, tid, op, by=by)[0]


def is_prepared(root: Path, ticket: dict) -> bool:
    """The ticket has its Prepared line (ORCH-740)."""
    texts = (
        str(h.get("text", "")).removeprefix(history.SYNCED_UNVERIFIED) for h in history.lines(root, ticket)
    )
    return any(t.startswith(PREPARED_PREFIX) for t in texts)


def prepared(root: Path, tid: str, by: str) -> dict:
    """End of Prepare (ORCH-740): one history line that says what it read and filled, e.g. "Prepared: 2
    sources
    read, 1 could not be opened; title, description, done-when, estimate, asked by, suggested plan (4 steps)".
    Once per ticket. It names only what is there; refused while the ticket has no suggested plan (no task)."""

    def op(ticket):
        if is_prepared(root, ticket):
            raise Refused("This ticket is already prepared; go on with the work.")
        steps = [c for c in ticket.get("checklist") or [] if not c.get("wont_do")]
        if not steps:
            raise Refused(f'Add the suggested plan first, one task per step: orch check add {tid} "<step>"')
        filled = [] if ticket.get("title_auto") else ["title"]
        for k, w in (
            ("description", "description"),
            ("done_when", "done-when"),
            ("estimate", "estimate"),
            ("owner", "owner"),
            ("asked_by", "asked by"),
            ("due", "due date"),
        ):
            if ticket.get(k):
                filled.append(w)
        refs = [r for r in ticket.get("refs") or [] if isinstance(r, dict)]
        if refs:
            filled.append(f"links ({len(refs)})")
        for k, w in (("maybe_same", "maybe the same as"), ("needs_ok", "needs your OK for")):
            if ticket.get(k):
                filled.append(w)
        filled.append(f"suggested plan ({len(steps)} step{'s' if len(steps) != 1 else ''})")
        head = sources_words(ticket["found"]) + "; " if isinstance(ticket.get("found"), dict) else ""
        add_history(ticket, by, f"{PREPARED_PREFIX} {head}{', '.join(filled)}")

    return apply_op(root, tid, op, by=by)[0]


def set_model(root: Path, tid: str, name: str, by: str) -> dict:
    """A person's model for this ticket's helper (haiku, sonnet, opus or fable), or auto: orch picks again
    next start. Haiku and Fable come only from here: orch never picks them (owner 17 Nov, ORCH-257)."""
    from orch import modelpick

    name = (name or "").strip().lower()
    if name not in (*modelpick.MODELS, "auto"):
        raise Refused("Pick haiku, sonnet, opus, fable or auto.")
    if not _is_person(by):
        raise Refused(
            f'Only a person picks the model. Ask instead: orch ask {tid} "Run this ticket on Opus?" '
            "--option yes --option no"
        )

    def op(ticket):
        if name == "auto":
            ticket.pop("model", None)
            add_history(ticket, by, "Model: orch picks it again on the next start")
        else:
            ticket["model"] = {"name": name, "by": by[:100]}
            add_history(ticket, by, f"Model set to {modelpick.LABELS[name]}")

    return apply_op(root, tid, op, by=by)[0]


def _kept_model(ticket: dict) -> str | None:
    """The model that stays as it is: a person's choice, or Opus once a helper ran on it (never down by
    itself: a ticket picked or moved up to Opus does not drop to Sonnet in the middle of its work)."""
    from orch import modelpick

    cur = modelpick.chosen(ticket)
    if not cur:
        return None
    if modelpick.by_person(ticket) or cur["name"] == modelpick.pick(ticket)[0]:
        return cur["name"]
    if cur["name"] == "opus" and (cur.get("up") or ticket.get("sessions")):
        return "opus"
    return None


def next_model(ticket: dict) -> str:
    """The model the next start runs on, read only (pick_model without writing): what a page shows before
    the person starts a helper (the Empty helper's New menu, ORCH-710)."""
    from orch import modelpick

    return _kept_model(ticket) or modelpick.pick(ticket)[0]


def pick_model(root: Path, tid: str, by: str) -> str:
    """Before a start: keep a person's choice, else let orch pick from the ticket as it is now (a history line
    only when the pick changes). Returns the model name."""
    from orch import modelpick

    out: dict = {}

    def op(ticket):
        kept = _kept_model(ticket)
        if kept:
            out["name"] = kept
            return
        name, why = modelpick.pick(ticket)
        out["name"] = name
        ticket["model"] = {"name": name, "by": modelpick.BY_ORCH, "why": why[:200]}
        add_history(ticket, by, f"Model picked: {modelpick.LABELS[name]} ({why[:200]})")

    kept = _kept_model(load(root, tid))
    if kept:
        return kept  # nothing to write
    apply_op(root, tid, op, by=by)
    return out["name"]


def move_up(root: Path, tid: str, why: str, by: str) -> tuple[dict, bool]:
    """Move a ticket orch put on Sonnet up to Opus (the helper when its plan shows design, security or
    several parts; orch after two failed checks on one step). One history line says why. A person's choice
    is never changed. Returns (ticket, moved): moved False when it already runs on Opus or Fable."""
    from orch import modelpick

    why = " ".join(clean_untrusted(why or "", 200).split())
    if len(why) < 3:
        raise Refused('Say why in a few words, e.g. --why "the plan needs a new design".')
    out = {"moved": False}

    def op(ticket):
        cur = modelpick.chosen(ticket)
        if cur and modelpick.by_person(ticket):
            if cur["name"] in modelpick.STRONG:
                return
            raise Refused(
                f"A person chose {modelpick.LABELS[cur['name']]} for this ticket. Ask instead: "
                f'orch ask {tid} "Move this ticket up to Opus? {why[:80]}" --option yes --option no'
            )
        if cur and cur["name"] in modelpick.STRONG:
            return
        ticket["model"] = {
            "name": "opus",
            "by": modelpick.BY_ORCH,
            "why": why,
            "up": {"from": (cur or {}).get("name") or "sonnet", "at": now(), "by": by[:100]},
        }
        add_history(ticket, by, f"{modelpick.UP_PREFIX}: {why}")
        out["moved"] = True

    t = load(root, tid)
    if (modelpick.chosen(t) or {}).get("name") in modelpick.STRONG:
        return t, False  # already on Opus or Fable: nothing to write
    t = apply_op(root, tid, op, by=by)[0]
    return t, out["moved"]


def set_plan(root: Path, tid: str, goal: str, not_included: str | None, by: str) -> dict:
    """The agent's goal and 'Not included' of a plan, in its own field (never the person's note)."""
    goal = goal.strip()
    ni = (not_included or "").strip()
    if not goal or len(goal) > 500 or len(ni) > 500:
        raise Refused("The goal needs 1 to 500 characters, 'Not included' at most 500.")

    def op(ticket):
        ticket["plan"] = {"goal": goal, **({"not_included": ni} if ni else {}), "by": by[:100]}
        add_history(ticket, by, "Plan written")

    return apply_op(root, tid, op, by=by)[0]


def set_summary(root: Path, tid: str, text: str, by: str) -> dict:
    """No history line: it would double the history on every run."""
    clean_field("summary", text)

    def op(t):
        _set_field(t, "summary", text)
        note_results(root, t, _result_by(by))

    return apply_op(root, tid, op, by=by)[0]


# Short plain-text fields on a ticket (outcome parts); the schema maxLength matches.
TEXT_FIELD_MAX = 300
OUTCOME_KEYS = ("changed", "why", "not_included")


def set_outcome(root: Path, tid: str, by: str, **parts) -> dict:
    """What changed and why (outcome). Given parts replace theirs, empty clears one. No history line."""
    clean = {}
    for k, v in parts.items():
        if k not in OUTCOME_KEYS:
            raise Refused(f"An outcome has only: {', '.join(OUTCOME_KEYS)}.")
        if v is None:
            continue
        if not isinstance(v, str):
            raise Refused(f"{k} must be text.")
        v = v.strip()
        if len(v) > TEXT_FIELD_MAX:
            raise Refused(f"'{k}' is at most {TEXT_FIELD_MAX} characters.")
        clean[k] = v
    if not clean:
        raise Refused("Say what to record: --changed, --why or --not-included.")

    def op(ticket):
        out = dict(ticket.get("outcome") or {})
        for k, v in clean.items():
            if v:
                out[k] = v
            else:
                out.pop(k, None)
        if out:
            ticket["outcome"] = out
        else:
            ticket.pop("outcome", None)

    return apply_op(root, tid, op, by=by)[0]


def _next_id(items: list[dict], prefix: str) -> str:
    nums = [int(i["id"][1:]) for i in items if re.fullmatch(prefix + r"[0-9]+", str(i.get("id", "")))]
    return f"{prefix}{max(nums, default=0) + 1}"


# ---------------------------------------------------------------- checklist


def _item(ticket: dict, cid: str) -> dict:
    """The task named `cid`. A plain number N is the task c<N> (checks are named c1, c2, ...)."""
    cid = str(cid)
    ids = [c["id"] for c in ticket["checklist"]]
    if cid not in ids and cid.isdigit() and f"c{int(cid)}" in ids:
        cid = f"c{int(cid)}"
    item = next((c for c in ticket["checklist"] if c["id"] == cid), None)
    if item is None:
        have = f" This ticket has {ids[0]}..{ids[-1]}." if ids else " This ticket has no checks yet."
        raise Refused(
            f"Ticket {ticket['id']} has no check {cid}. Checks are named c1, c2, ...{have} "
            f"Run `orch ticket show {ticket['id']}` to see them."
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


def _clean_covers(covers: str | None) -> str | None:
    """`covers`: the quoted part of done_when a task covers, 1 to 300 characters; None = not given."""
    if covers is None:
        return None
    line = " ".join(covers.split())
    if not 1 <= len(line) <= TEXT_FIELD_MAX:
        raise Refused(f"--covers is a short quote of 'Done when' (1 to {TEXT_FIELD_MAX} characters).")
    return line


def check_add(root: Path, tid: str, text: str, by: str, covers: str | None = None) -> tuple[dict, dict]:
    if not text.strip():
        raise Refused("A checklist item needs text.")
    covers = _clean_covers(covers)

    def op(ticket):
        item = {"id": _next_id(ticket["checklist"], "c"), "text": text.strip(), "done": False, "evidence": []}
        if covers:
            item["covers"] = covers
        ticket["checklist"].append(item)
        add_history(ticket, by, f"Added check {item['id']}")
        return item

    return apply_op(root, tid, op, by=by)


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
        raise Refused(f"An evidence role is one of: {', '.join(ROLES)}.")
    if "text" in ev and not isinstance(ev["text"], str):
        raise Refused("Evidence text must be a string.")
    if "summary" in ev:
        raw = ev["summary"]
        line = " ".join(raw.split()) if isinstance(raw, str) else ""
        if not 1 <= len(line) <= 200 or not line.isprintable():
            raise Refused("An evidence summary is one line of 1 to 200 printable characters.")
        ev["summary"] = line
    _check_record_fields(ev)
    return ev


def _ran_at_ok(v) -> bool:
    if not isinstance(v, str) or not RAN_AT.fullmatch(v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _check_record_fields(ev: dict) -> None:
    """Optional fields of a recorded check (`orch check record`): exit, ran_at, files_sig, output_tail.
    Data only."""
    if "exit" in ev and (type(ev["exit"]) is not int or not -255 <= ev["exit"] <= 255):
        raise Refused("A recorded exit code is a whole number from -255 to 255.")
    if "ran_at" in ev and not _ran_at_ok(ev["ran_at"]):
        raise Refused("ran_at is a UTC time like 2026-11-09T14:30:00Z.")
    if "files_sig" in ev and not (isinstance(ev["files_sig"], str) and SIG.fullmatch(ev["files_sig"])):
        raise Refused("files_sig is a hex string of 16 to 128 characters.")
    if "output_tail" in ev and not (
        isinstance(ev["output_tail"], str) and len(ev["output_tail"]) <= TAIL_MAX
    ):
        raise Refused(f"output_tail is text of at most {TAIL_MAX} characters.")
    for k in ("ref", "output_tail"):
        if isinstance(ev.get(k), str) and UNSAFE_TEXT.search(ev[k]):
            raise Refused(f"{k} must not contain control or direction-changing characters.")


def _canon(entry) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _is_run(e) -> bool:
    return isinstance(e, dict) and e.get("type") == "command" and _ran_at_ok(e.get("ran_at"))


def trim_runs(evidence: list) -> list:
    """Recorded runs (command evidence with a well-formed ran_at, see _ran_at_ok): keep the newest
    RUNS_PER_REF per command text and at most RUNS_PER_CHECK runs per check, oldest runs dropped first, so a
    loop of `orch check record` cannot grow a ticket without bound. Order of runs: (ran_at, canonical JSON).
    Notes and every other kind of proof are never dropped because of runs. The sync add-on's merge has the
    same rule (orch_sync.merge.trim_runs, parity-tested) so every replica ends with the same entries."""
    key = lambda i: (evidence[i]["ran_at"], _canon(evidence[i]))  # noqa: E731
    by_ref: dict[str, list[int]] = {}
    for i, e in enumerate(evidence):
        if _is_run(e):
            by_ref.setdefault(str(e.get("ref")), []).append(i)
    drop: set[int] = set()
    for idx in by_ref.values():
        idx.sort(key=key)
        drop.update(idx[:-RUNS_PER_REF])
    live = sorted((i for idx in by_ref.values() for i in idx if i not in drop), key=key)
    drop.update(live[:-RUNS_PER_CHECK])  # over the cap only the oldest runs go; other proof is never touched
    return [e for i, e in enumerate(evidence) if i not in drop]


def _clear_doing(item: dict) -> None:
    for k in ("state", "by", "at"):
        item.pop(k, None)


# how an evidence field reads in a refusal; `ref` reads by the evidence type
_EVIDENCE_REF_WORDS = {
    "note": "note",
    "command": "command",
    "url": "link",
    "pr": "pull request",
    "commit": "commit",
    "file": "file name",
}
_EVIDENCE_FIELD_WORDS = {"output_tail": "output", "summary": "summary", "title": "title", "text": "text"}
# fields parse_evidence checks against a fixed shape (a list, an int, a time, hex), so they hold no free text.
# `by` and `at` are NOT here: a caller can set them (--evidence JSON) and nothing checks their shape.
_EVIDENCE_NOT_SCANNED = {"type", "role", "exit", "ran_at", "files_sig"}


def refuse_secret_in_evidence(root: Path, evidence: list) -> None:
    """R5.2 (#942): evidence can leave this computer later (sync, the relay, a phone, a share), so every
    evidence write runs the one scanner first. `evidence`: evidence objects or their JSON text (anything else
    is left to parse_evidence). A hit refuses with the kind and the field, never the value; nothing is
    written."""
    from orch import secretscan

    for raw in evidence:
        ev = raw
        if isinstance(raw, str):
            try:
                ev = json.loads(raw)
            except ValueError:
                ev = raw  # not JSON: still scanned as text, parse_evidence refuses it afterwards
        if not isinstance(ev, dict):
            secretscan.refuse_if_secret_in(root, {"evidence": str(ev)}, "evidence", verb="saved")
            continue
        body = {}
        for k, v in ev.items():
            if k in _EVIDENCE_NOT_SCANNED and not isinstance(v, (dict, list)):
                continue
            word = (
                _EVIDENCE_REF_WORDS.get(str(ev.get("type")), "text")
                if k == "ref"
                else _EVIDENCE_FIELD_WORDS.get(k, k)
            )
            key = word
            while key in body:  # never overwrite a field already in the body: every value is scanned
                key += " "
            body[key] = v
        secretscan.refuse_if_secret_in(root, body, "evidence", verb="saved")


def check_done(
    root: Path, tid: str, cid: str, evidence: list[str], by: str, proves: list[str] | None = None
) -> tuple[dict, dict]:
    """`proves`: quoted parts of Done when this finished task shows; the evidence decides, not the wording."""
    proved = [q for q in (_clean_covers(p) for p in proves or []) if q]
    ticket = load(root, tid)  # a missing ticket is reported before anything else
    if not evidence:
        raise Refused(
            "A check is done only with evidence. Say what shows it, for example "
            f'`orch check done {tid} {cid} --command "pytest -q"` or `--note "what you saw"` '
            "(also --pr, --commit, --file, --url)."
        )
    refuse_secret_in_evidence(root, evidence)
    evs = [parse_evidence(e) for e in evidence]
    _item(ticket, cid)

    def op(t):
        item = _item(t, cid)
        _refuse_if_wont_do(item, tid, cid)
        for ev in evs:
            ev.setdefault("by", by)
            ev.setdefault("at", now())
        add_evidence(item, evs)
        item["done"] = True
        if proved:
            item["proves"] = list(dict.fromkeys([*item.get("proves", []), *proved]))
        _clear_doing(item)
        note_results(root, t, _result_by(by))
        add_history(t, by, f"Check {item['id']} done")
        _note_run_task(t, item["id"])
        return item

    return apply_op(root, tid, op, by=by)


WONT_DO_AGENT = (
    "Only a person marks a step as won't do. Ask them, and say where the step would run if they say no: "
    'orch ask {tid} "Mark step {cid} as won\'t do?" --option yes '
    '--option "No, run it in CI" --check {cid}'
)

_WONT_DO_Q_RE = re.compile(r"\bwon'?t do\b|\bskip\b", re.IGNORECASE)
_TEST_WORD_RE = re.compile(
    r"\b(test|tests|tested|testing|pytest|try[- ]?out|trial|experiment)\b", re.IGNORECASE
)


def _guard_question(
    root: Path, text: str, options: list[str], recommended: str | None, check: str | None
) -> None:
    """Two plain refusals (ORCH-332). A question never offers a protected (production) machine for a test.
    A question that asks whether to skip a step must name where it would run if the answer is no (a bare
    yes/no was once read as "run it now, on production")."""
    parts = [text, *options, *([recommended] if recommended else [])]
    machines = config.protected_machines(root)
    if machines:
        from orch import protected

        names = protected.expand(machines)

        def find(blob: str) -> str | None:
            blob = blob.lower()
            return next(
                (
                    n
                    for n in sorted(names)
                    if re.search(rf"(?<![a-z0-9.-]){re.escape(n)}(?![a-z0-9.-])", blob)
                ),
                None,
            )

        offered = find(" ".join(parts[1:]))  # an option or the recommended answer
        mentioned = find(text) if _TEST_WORD_RE.search(text) else None
        deploy = re.search(r"\b(release|deploy|deployment|ship)\b", text, re.IGNORECASE)
        hit = mentioned or (offered if not deploy else None)
        if hit:
            raise Refused(
                f"{hit} is a protected machine (production): a question never offers it for a test or as a "
                "place to run something. Offer the CI job or a throwaway server, or skip the step."
            )
    if (
        check is not None
        and _WONT_DO_Q_RE.search(text)
        and options
        and all(o.strip().lower() in {"yes", "no", "y", "n"} for o in options)
    ):
        raise Refused(
            "A question about skipping a step must say where it would run if the answer is no. "
            'Use options such as yes and "No, run it in CI", not a bare yes and no.'
        )


def _refuse_if_wont_do(item: dict, tid: str, cid: str) -> None:
    if item.get("wont_do"):
        raise Refused(f"{cid} was marked won't do by a person. Only a person opens it again.")


def _person_only(by: str, item: dict, tid: str, cid: str) -> None:
    """A step marked Won't do is a person's decision: only a person edits, removes or reopens it."""
    if item.get("wont_do") and not _is_person(by):
        _refuse_if_wont_do(item, tid, cid)


def check_wont_do(root: Path, tid: str, cid: str, by: str, reason: str | None = None) -> tuple[dict, dict]:
    """A person decides a step will not be done. Person only, enforced here like accept_review: `by` must be
    human: and no agent tool may be in the environment; an agent can only ask (orch ask ...). The step stays
    done=false (it is not done) and counts as resolved. It is stored plain: wont_do, wont_by, wont_at. Calling
    again changes the reason."""
    if not _is_person(by):
        raise Refused(WONT_DO_AGENT.format(tid=tid, cid=cid))
    why = " ".join((reason or "").split())
    if len(why) > 200 or (why and not why.isprintable()):
        raise Refused("The reason is one line of at most 200 characters.")

    def op(t):
        return _mark_wont_do(t, cid, by, why)

    return apply_op(root, tid, op, by=by)


def _mark_wont_do(t: dict, cid: str, by: str, why: str = "") -> dict:
    """Inside an apply_op: mark step `cid` won't do for the person `by` (check_wont_do, or their yes to a
    "won't do?" question tied to the step)."""
    item = _item(t, cid)
    if item.get("done"):
        raise Refused(f"{cid} is already done. Open it again first.")
    item["evidence"] = []
    _clear_doing(item)
    item["wont_do"] = True
    if why:
        item["reason"] = why
    else:
        item.pop("reason", None)
    item.update({"by": by, "at": now(), "wont_by": by, "wont_at": now()})
    history.created("steps", item)  # the step mark is core's own (like check_start)
    add_history(t, by, f"Marked {cid} as won't do")
    return item


_YES = re.compile(r"yes(?:\s*:.*)?", re.IGNORECASE | re.DOTALL)  # "yes", or "Yes: <why>" (#2309)


def _wont_do_yes(q: dict, ans: str) -> bool:
    """A person's yes to exactly the question WONT_DO_AGENT tells helpers to ask ("Mark step c2 as won't do?",
    tied to that step, with a yes option). ORCH-267: the yes marks the step; no second click. Only that exact
    wording counts, so a helper cannot word another question so that its yes also drops a step. A yes option
    is "yes" or "Yes: <why>"; the answer is that option (or a plain yes)."""
    cid, text = q.get("check"), q.get("text")
    if not isinstance(cid, str) or not isinstance(text, str):
        return False
    canon = re.compile(rf"Mark step {re.escape(cid)} as won['\u2019]t do\??", re.IGNORECASE)
    yeses = [
        o.strip().casefold()
        for o in q.get("options") or []
        if isinstance(o, str) and _YES.fullmatch(o.strip())
    ]
    said = ans.strip().casefold()
    return bool(canon.fullmatch(text.strip())) and bool(yeses) and (said in yeses or said == "yes")


def _output_tail(root: Path, source: str | None) -> str | None:
    """The last TAIL_MAX characters of a plain log file inside the workspace, control characters removed. Only
    read as text, never run. All file rules live in saferead.safe_read_tail (no stdin, no dotfiles, no
    links)."""
    if source is None:
        return None
    data = saferead.safe_read_tail(root, source, 8192)
    return clean_untrusted(data.decode("utf-8", "replace"), 100_000)[-TAIL_MAX:]


def check_record(
    root: Path,
    tid: str,
    cid: str,
    cmd: str,
    exit_code: int | None,
    output: str | None,
    by: str,
) -> tuple[dict, dict]:
    """Record that a command ran for a task: ONE `command` evidence with exit, ran_at, files_sig (when
    the folder
    is under git) and the output tail. It only stores what the agent says; `cmd` and the output are data,
    never
    run. The task is not marked done (that stays `orch check done`)."""
    from orch import filesig

    line = " ".join(clean_untrusted(cmd or "", 500).split())
    if not line:
        raise Refused('Say what ran, e.g. --cmd "uv run pytest -q".')
    _item(load(root, tid), cid)  # a wrong ticket or task is refused before anything is read
    ev: dict = {"type": "command", "ref": line}
    if exit_code is not None:
        ev["exit"] = exit_code
    ev["ran_at"] = now()
    sig = filesig.files_sig(root)
    if sig:
        ev["files_sig"] = sig
    tail = _output_tail(root, output)
    if tail:
        ev["output_tail"] = tail
    refuse_secret_in_evidence(root, [{"type": "command", "ref": cmd}, ev])  # as given and as it would be kept
    parse_evidence(json.dumps(ev))  # same checks as every proof
    ev["by"], ev["at"] = by, now()

    def op(t):
        item = _item(t, cid)
        add_evidence(item, [ev], trim=True)
        add_history(
            t,
            by,
            f"Recorded a check run for {cid}" + (f" (exit {exit_code})" if exit_code is not None else ""),
        )
        return item

    t, item = apply_op(root, tid, op, by=by)
    if exit_code and _failed_twice(item):
        _up_after_failures(root, tid, item)
    return t, item


def _failed_twice(item: dict) -> bool:
    """The step's last two recorded check runs both failed (a non-zero exit)."""
    runs_ = [e for e in item.get("evidence") or [] if e.get("type") == "command" and "exit" in e]
    return len(runs_) >= 2 and all(e.get("exit") not in (0, None) for e in runs_[-2:])


def _up_after_failures(root: Path, tid: str, item: dict) -> None:
    """Two failed checks on one step: a ticket orch put on Sonnet moves up to Opus by itself. Never fails
    the record (a person's choice stays; a live session switches at its next turn end)."""
    from orch import modelpick, runs_live

    t = load(root, tid)
    cur = modelpick.chosen(t)
    if not cur or cur["name"] not in modelpick.SMALL or modelpick.by_person(t):
        return
    step = " ".join(str(item.get("text") or "").split())[:80]
    why = f'two checks failed on the step "{step}"' if step else "two checks failed on one step"
    with contextlib.suppress(Refused):
        t, moved = move_up(root, tid, why, "orch")
        if moved:
            with contextlib.suppress(Exception):
                runs_live.switch_model(root, tid, "opus", "orch")


def check_exists(root: Path, tid: str, cid: str) -> None:
    _item(load(root, tid), cid)


def check_edit(
    root: Path,
    tid: str,
    cid: str,
    text: str | None,
    by: str,
    if_revision: int | None = None,
    was: str | None = None,
    covers: str | None = None,
) -> tuple[dict, dict]:
    if text is None and covers is None:
        raise Refused("Say the new text or --covers.")
    if text is not None and not text.strip():
        raise Refused("A checklist item needs text.")
    covers = _clean_covers(covers)

    def op(t):
        item = _item(t, cid)
        _person_only(by, item, tid, cid)
        if text is not None:
            before = item.get("text")
            item["text"] = text.strip()
            # ORCH-240: the Activity shows the old and the new task text
            add_history(t, by, f"Renamed {cid} (was: {_edit_snip(before)} | now: {_edit_snip(item['text'])})")
        if covers is not None:
            item["covers"] = covers
            if text is None:
                add_history(t, by, f"Linked {cid} to Done when")
        return item

    expect = (f"checklist.{cid}.text", was) if was is not None else None
    return apply_op(root, tid, op, expect=expect, if_revision=if_revision, by=by)


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

    return apply_op(root, tid, op, by=by)


def check_remove(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Allowed, except a Won't do step: that is a person's decision (decided under the lock). The history line
    keeps the step text and its proof."""

    def op(t):
        item = _item(t, cid)
        _person_only(by, item, tid, cid)  # an agent cannot delete a person's decision
        t["checklist"].remove(item)
        proof = ", ".join(proof_label(e) for e in item.get("evidence", []))
        state = "was done" if item.get("done") else "was open"
        add_history(
            t,
            by,
            f"Removed step {cid} '{item['text']}' ({state}" + (f"; evidence: {proof})" if proof else ")"),
        )
        return item

    return apply_op(root, tid, op, by=by)


def check_reopen(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Open again; the old proof stays in the history line. A Won't do step is a person's decision: only a
    person undoes it. Decided HERE, under the ticket lock, on the ticket as it is now (no check-then-act
    gap, and a ticket that cannot be read refuses)."""

    def op(t):
        item = _item(t, cid)
        if item.get("wont_do"):
            _person_only(by, item, tid, cid)
            for k in ("wont_do", "reason", "wont_by", "wont_at"):
                item.pop(k, None)
            _clear_doing(item)
            add_history(t, by, f"Reopened {cid}")
            return item
        proof = ", ".join(proof_label(e) for e in item.get("evidence", []))
        item["done"] = False
        item["evidence"] = []
        _clear_doing(item)
        add_history(t, by, f"Reopened {cid}" + (f" (old evidence: {proof})" if proof else ""))
        return item

    return apply_op(root, tid, op, by=by)


def check_start(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    """Mark a step as being worked on; the mark on any other step goes."""

    def op(t):
        item = _item(t, cid)
        if item.get("done"):
            raise Refused(f"{cid} is already done. Reopen it first: orch check reopen {tid} {cid}")
        _refuse_if_wont_do(item, tid, cid)
        for c in t["checklist"]:
            _clear_doing(c)
        item.update({"state": "doing", "by": by, "at": now()})
        history.created("steps", item)  # the step-start point: this mark is core's own (like evidence)
        return item

    return apply_op(root, tid, op, by=by)


def check_stop(root: Path, tid: str, cid: str, by: str) -> tuple[dict, dict]:
    def op(t):
        item = _item(t, cid)
        _clear_doing(item)
        return item

    return apply_op(root, tid, op, by=by)


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
    return apply_op(root, tid, lambda t: add_history(t, by, text.strip()), by=by)[0]


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
            history.created("refs", result)  # the ref-add point: this exact object is core's
            verb = "Added reference"
        if value.get("local"):
            refs.write_local(root, ticket["id"], values)
            return NO_WRITE
        add_history(ticket, by, f"{verb} {refs.target(result)}")
        return result

    t, _ = apply_op(root, t["id"], op, by=by)
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

    t, _ = apply_op(root, t["id"], op, by=by)
    return t, result


def ref_set(root: Path, tid: str, target: str, status: str, by: str) -> tuple[dict, dict, bool]:
    """Record the state of a web reference as the helper last saw it: `status` and `seen_at`; `at` and `by`
    keep who added it. `status` is a lower-case word (refs.STATUS_RE) or "" to clear it. Returns
    (ticket, reference, changed); nothing is written when the state is already that."""
    from orch import refs

    status = status.strip()
    if status and not refs.STATUS_RE.fullmatch(status):
        raise Refused("A state is a short lower-case word such as open, closed, merged or in review.")
    t = load(root, tid)
    key = t.get("key") or t["id"]
    wanted = None
    if not target.isdigit():
        try:
            wanted = refs.detect(root, t["id"], target, check_exists=False)
        except Refused:
            wanted = None
    result, changed = None, False

    def op(ticket):
        nonlocal result, changed
        values = refs.numbered({"refs": ticket["refs"] + refs.local_refs(root, ticket["id"])})
        result = next(
            (
                r
                for n, r in values
                if isinstance(r, dict)
                and (
                    n == int(target)
                    if target.isdigit()
                    else wanted is not None and all(r.get(k) == v for k, v in wanted.items() if k != "kind")
                )
            ),
            None,
        )
        if result is None:
            raise Refused(f"{key} has no reference {target}. See them: orch ref list {key}")
        if "url" not in result or result.get("local"):
            raise Refused("That reference is not a web address. Only web references have a state.")
        old = result.get("status") or ""
        if old == status:
            return NO_WRITE
        changed = True
        if status:
            result["status"] = status
        else:
            result.pop("status", None)
        result["seen_at"] = now()
        name = refs.ref_name(result, root)
        add_history(ticket, by, f"Reference {name}: status {old or 'none'} -> {status or 'none'}")
        return result

    t, _ = apply_op(root, t["id"], op, by=by)
    return t, result, changed


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

    t, changes = apply_op(root, tid, op, by=by)  # an agent can run an add-on refresh: its real actor
    return t, changes or []


def validate_ext(schema: dict, obj: dict, addon: str) -> None:
    import jsonschema

    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        where = ".".join(str(x) for x in e.path)
        raise Refused(f"ext.{addon}{'.' + where if where else ''}: {e.message}")


# an add-on marks a boolean field of its ticket_ext schema with the value that switches it off
OFF_MARK = "x-orch-off"


def _off_values(schema: dict | None) -> dict:
    """The fields an add-on's ticket_ext schema marks with x-orch-off, and the value that switches its repeat
    off: {field: True|False}. Declared by the add-on, never inferred from stored data; core names no field."""
    props = (schema or {}).get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return {}
    return {
        k: v[OFF_MARK]
        for k, v in props.items()
        if isinstance(v, dict) and v.get("type") == "boolean" and isinstance(v.get(OFF_MARK), bool)
    }


def _repeat_block(ticket: dict, addon: str, schema: dict | None) -> tuple[dict, dict] | None:
    """(ext block, off values) of an ACTIVE add-on whose own ticket_ext schema marks fields that switch a
    repeat off, else None (R1.2: core names no add-on)."""
    off = _off_values(schema)
    if not off:
        return None
    cur = (ticket.get("ext") or {}).get(addon)
    return (cur, off) if isinstance(cur, dict) else None


def repeat_off_only(cur: dict, new: dict, off: dict) -> bool:
    """#2051: the change from cur to new only sets fields to their switch-off values (`off`), nothing else.
    An agent may do that on a done or dropped ticket (a helper turns off a repeat on a ticket in Review); it
    never switches one on there or changes anything else."""
    changed = {k for k in set(cur) | set(new) if cur.get(k) != new.get(k)}
    return all(k in off and new.get(k) is off[k] for k in changed)


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

    def only_off(ticket) -> bool:
        block = _repeat_block(ticket, addon, schema)
        return block is not None and repeat_off_only(block[0], {**block[0], **obj}, block[1])

    return apply_op(root, tid, op, if_revision=if_revision, by=by, closed_ok=only_off)[0]


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

    def only_off(ticket) -> bool:
        """Removing a repeat (or its next planned start) only switches work off, so it is allowed on a closed
        ticket too; but not the whole block of a paused one: that would also undo its switch-off."""
        block = _repeat_block(ticket, addon, schema)
        if block is None:
            return False
        cur, off = block
        # a field whose switch-off value is true (absent = on) must not be removed while it is set
        return key in ("next_run", "each_run") or (
            not key and not any(v is True and cur.get(k) is True for k, v in off.items())
        )

    return apply_op(root, tid, op, if_revision=if_revision, by=by, closed_ok=only_off)[0]


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
    card: dict | None = None,
    shown: dict | None = None,
    group: str | None = None,
    links: list[dict] | None = None,
    add_workspace: str | None = None,
    because: str | None = None,
) -> tuple[dict, dict]:
    """because: the helper's one-line reason for the recommended answer (ORCH-1643, draft D: "The helper
    suggests ...: <because>"); only with recommended. The dashboard highlights a suggested answer only
    when it has one.
    card/shown: a Review stack card (orch/review.py validates and copies it before it gets here).
    group: a short name for cards that belong together (one set on Review); only with a card.
    add_workspace: only from chat_groups.ask_to_add (the Add / Not now card it words itself); a caller's own
    --action can never carry it, so a person's Add never adds a workspace under other words."""
    if not text.strip():
        raise Refused("A question needs text.")
    if group is not None:
        group = " ".join(group.split())
        if card is None or not group or len(group) > GROUP_MAX or any(ord(ch) < 32 for ch in group):
            raise Refused(f"A group is a short name (at most {GROUP_MAX} characters) on a card.")
    if links is not None and card is None:
        raise Refused("Links go with a card.")
    if recommended is not None and options and recommended not in options:
        raise Refused("The recommended answer must be one of the options.")
    if because is not None:
        because = " ".join(because.split())
        if not because or recommended is None:
            raise Refused(
                "--because goes with --recommend: the reason for the answer you suggest, in one line."
            )
        if len(because) > BECAUSE_MAX:
            raise Refused(f"--because is one line of at most {BECAUSE_MAX} characters.")
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
        if "add_workspace" in act:
            raise Refused("Asking to add a workspace: orch relay group ask-add <ticket> <workspace>.")
        if "merge" in act and card is None:  # a merge is only ever the --merge link card's
            raise Refused(
                "A merge goes with a link card: orch ask --link TITLE --open <pull request> --merge."
            )

    if add_workspace is not None:
        act = {**(act or {}), "add_workspace": add_workspace}
    _guard_question(root, text, options, recommended, check)
    for part in (
        text,
        *options,
        *([recommended] if recommended else []),
        *([because] if because else []),
        *_labels(act),
    ):
        if _asks_for_secret(part):
            with contextlib.suppress(Exception):  # the attempt stays visible in the history
                apply_op(
                    root,
                    tid,
                    lambda t: add_history(t, by, "A question was refused: it asked for a secret."),
                    by=by,
                )
            raise Refused(
                "A question must never ask for a password, token, API key or other credential, "
                "and never mention the secrets folder. Ask whether access is set up instead "
                "(for example: Is access to the service set up for this workspace?), "
                "and say in the ticket summary what is missing."
            )

    preparing = _preparing_agent(root, tid, by)  # ORCH-741: asked during Prepare

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
            "asked_at": now(),  # the Reviewer's routine answers wait from here (reviewer.routine)
        }
        if kind is not None:
            q["kind"] = kind
        if act is not None:
            q["action"] = act
        if check is not None:
            q["check"] = check
        if because:  # RULE A: only when given (old digests stay the same); part of what the person is shown
            q["because"] = because
        if card is not None:  # RULE A: only a card question carries these (old digests stay the same)
            q["card"] = card
            q["shown"] = shown
            if group:
                q["group"] = group
            if links:  # part of what the person is shown: in the digest (question_digest)
                q["links"] = [dict(x) for x in links]
        ticket["questions"].append(q)
        if preparing and ticket["status"] == "open":  # Prepare's one question: the ticket stays in Backlog
            add_history(ticket, by, f"Asked {q['id']}")
            return q
        ticket["status"] = "waiting"
        ticket["waiting_on"] = {"kind": "question", "ref": q["id"]}
        add_history(ticket, by, f"Asked {q['id']}, waiting")
        return q

    return apply_op(root, tid, op, by=by)


GROUP_MAX = 80
BECAUSE_MAX = 200
QUESTION_UNENCODABLE = "unencodable"  # never equal to a sha256 hex: an answer expecting it is always refused


def question_digest(q) -> str:
    """sha256 of what a person is shown of a question (id, text, options, kind, action, recommended).
    A question that cannot be encoded gives QUESTION_UNENCODABLE, which no answer is accepted against."""
    if not isinstance(q, dict):
        return QUESTION_UNENCODABLE
    shown = {k: q.get(k) for k in ("id", "text", "options", "kind", "action", "recommended")}
    for k in (
        "card",
        "shown",
        "links",
        "because",
    ):  # RULE A: only when present, so a question without them keeps its digest
        if q.get(k) is not None:
            shown[k] = q[k]
    try:
        canon = json.dumps(shown, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeError):
        return QUESTION_UNENCODABLE


def _release_wait(root: Path, tid: str, ticket: dict, qid: str) -> None:
    """A question is settled (answered or taken back): a ticket that waited on it stops waiting."""
    from orch import runs  # runs imports tickets

    w = ticket.get("waiting_on")
    if w and w.get("kind") == "question" and w.get("ref") == qid:
        still = _open_questions(ticket)
        if still:  # more questions wait: the ticket keeps waiting, on the oldest of them
            ticket["waiting_on"] = {"kind": "question", "ref": still[0]}
        else:
            ticket["waiting_on"] = None
            if ticket["status"] == "waiting":  # Working only while an agent runs; else Ready to go on
                chat = hidden_kind(ticket) is not None  # the Chat and Manager tickets are never Working
                ticket["status"] = "ready" if chat or not runs.running(root, tid) else "active"


TAKEN_BACK = "Taken back: "
MAX_TAKE_BACK_REASON = 300


def taken_back_text(q: dict) -> str | None:
    """ "Taken back: <reason>" for a taken-back question, else None. The one place that word is built."""
    tb = q.get("taken_back") if isinstance(q, dict) else None
    if not isinstance(tb, dict):
        return None
    return TAKEN_BACK + " ".join(str(tb.get("reason") or "").split())


def refuse_if_taken_back(q: dict) -> None:
    """The one check every answer path makes (CLI, dashboard, phone, card): taken back stays closed."""
    if (text := taken_back_text(q)) is not None:
        raise Refused(f"This question was taken back: {text[len(TAKEN_BACK) :]}")


def take_back(root: Path, tid: str, qid: str, reason: str, by: str) -> tuple[dict, dict, bool]:
    """A helper takes back its own question that no longer matters. The question stays in the ticket, settled
    (`taken_back` {at, by, reason}; `answer` is "Taken back: <reason>", so every reader that lists open
    questions drops it), one history line, and a `waiting_on` that pointed at it clears.
    Returns (ticket, question, changed). changed is False when the same reason was given before (a no-op).
    The phone message that removes the card hooks in here (G3b): it needs only tid and q["id"]."""
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Refused('A reason is needed: orch ask <ticket> --take-back q3 "why it no longer matters".')
    if len(reason) > MAX_TAKE_BACK_REASON:
        raise Refused(f"Keep the reason to one short line (at most {MAX_TAKE_BACK_REASON} characters).")

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}. See the open ones: orch needs.")
        if (old := q.get("taken_back")) is not None:
            if isinstance(old, dict) and old.get("reason") == reason:
                return NO_WRITE
            refuse_if_taken_back(q)
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered, so it cannot be taken back.")
        at = now()
        q["taken_back"] = {"at": at, "by": by, "reason": reason}
        q["answer"], q["answered_by"], q["via"] = TAKEN_BACK + reason, by, _env_via()
        _release_wait(root, tid, ticket, qid)
        add_history(ticket, by, TAKEN_BACK + reason)
        return q

    t, q = apply_op(root, tid, op, by=by)
    if q is None:  # NO_WRITE: the same reason again
        q = next(x for x in t["questions"] if x["id"] == qid)
        return t, q, False
    return t, q, True


IN_CONVERSATION = "Answered in the conversation: "
IN_CONVERSATION_VIA = "conversation"


def answered_in_conversation(root: Path, tid: str, qid: str, words: str, by: str) -> dict:
    """The person answered the helper in its own window instead of on the open card (owner, ORCH-267): the
    helper writes their words on the card and it closes. It is shown as theirs only through the helper: the
    answer reads "Answered in the conversation: <words>", answered_by stays the helper, via is "conversation".
    A card that does something on its answer (merge, start a run, release) is refused: the person answers that
    one on the card. Returns the question."""
    words = " ".join(str(words or "").split())
    if not words:
        raise Refused(
            'Write down what the person said: orch ask <ticket> --in-conversation q3 "<their words>".'
        )
    if len(words) > MAX_TAKE_BACK_REASON:
        raise Refused(f"Keep it to one short line (at most {MAX_TAKE_BACK_REASON} characters).")

    if str(by).startswith("human:"):
        raise Refused(
            "Only the helper writes down an answer from the conversation; a person answers on the card."
        )

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}. See the open ones: orch needs.")
        refuse_if_taken_back(q)
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered.")
        if q.get("action") or q.get("kind") not in (None, "plain"):
            raise Refused(f"{qid} does something when it is answered: the person answers it on the card.")
        at = now()
        q["in_conversation"] = {"at": at, "by": by}
        q["answer"], q["answered_by"], q["via"], q["answered_at"] = (
            IN_CONVERSATION + words,
            by,
            IN_CONVERSATION_VIA,
            at,
        )
        _release_wait(root, tid, ticket, qid)
        add_history(ticket, by, f"{qid} answered in the conversation: {words}")
        return q

    return apply_op(root, tid, op, by=by)[1]


def answer(
    root: Path,
    tid: str,
    qid: str,
    text: str,
    by: str,
    via: str,
    *,
    expected_question_digest: str | None = None,
    decision: dict | None = None,
    person: bool = False,
    ran: bool = False,
) -> tuple[dict, dict]:
    """ran: only orch.runcard.run sets it, after it ran a run card's command for the person (ORCH-848); a
    run card's "I ran it" (or any yes) is refused without it, from every other caller.
    decision: the Review stack's structured answer (orch/review.py); `answer` is then its plain summary.
    person: a signed-in person on the dashboard (a one-time person grant) or a paired phone; only then is a
    draft card answered (ORCH-582, orch/ownerpick.py), whatever `by` and `via` say.
    expected_question_digest: question_digest of the question as the person was shown it; the answer is
    refused when the question is no longer that one, or could not be encoded. None: not checked (a caller that
    kept no digest, e.g. a relay record from before digests)."""
    if not VIA_RE.fullmatch(via):
        raise Refused("via must be a short word (a-z, 0-9, -), e.g. cli or dashboard.")
    if not text.strip():
        raise Refused("An answer needs text.")
    text = text.strip()

    person_click = by.startswith("human:") and (via != "cli" or not agent_tool())

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None:
            raise Refused(f"Ticket {tid} has no question {qid}.")
        refuse_if_taken_back(q)
        if q["answer"] is not None:
            raise Refused(f"{qid} is already answered.")
        if isinstance(q.get("card"), dict) and not str(by).startswith("human:"):
            raise Refused(
                "This card waits for the owner. Ask with orch review add and wait with orch review wait."
            )
        ownerpick.refuse_card(q, person and str(by).startswith("human:"))
        if not ran and _claims_ran(q, text, decision):
            from orch import runcard

            raise Refused(runcard.OK_REFUSAL)
        if decision is None and isinstance(q.get("action"), dict) and "merge" in q["action"]:
            raise Refused(f"{qid} merges a pull request: answer it on the card (Merge or Not now).")
        if isinstance(q.get("action"), dict) and "add_workspace" in q["action"] and not person_click:
            raise Refused(f"{qid} adds a workspace to the chat: only the person answers it (Add or Not now).")
        if expected_question_digest is not None and (
            expected_question_digest == QUESTION_UNENCODABLE or question_digest(q) != expected_question_digest
        ):
            raise Refused(f"{qid} changed after it was shown. Look at the question again, then answer.")
        ans = text
        for opt in q["options"]:  # an option matches case-insensitively: store its spelling; else free text
            if opt.casefold() == ans.casefold():
                ans = opt
                break
        q["answer"], q["answered_by"], q["via"] = ans, by, via
        q["answered_at"] = now()  # when, whatever `via` says (a page shows "Answered on your phone 12:34")
        if decision is not None:
            q["decision"], q["at"] = dict(decision), now()
        _release_wait(root, tid, ticket, qid)
        add_history(ticket, by, f"Answered {qid}: {ans}", via)
        history.created("answers", q)  # the answer point: this question, as answered, is core's own
        # A click on the dashboard or a phone is a person even when that server was started from a helper's
        # session (its environment then shows an agent tool, which only says who runs the CLI). #1354.
        if person_click and _wont_do_yes(q, ans):
            item = _item(ticket, q["check"])
            if not item.get("done") and not item.get("wont_do"):
                _mark_wont_do(ticket, q["check"], by, f"Answered yes to {qid}")
        return q

    adding = person_click and _asks_to_add(root, tid, qid)
    if adding:
        from orch import (
            chat_groups,
        )  # saved before the answer: a crash after it still adds (on the next sync)

        chat_groups.note_add(root, tid, qid, by)
    try:
        res = apply_op(root, tid, op, by=by, person_click=person_click)
    except BaseException:
        if adding:
            chat_groups.add_done(root, tid, qid)
        raise
    q = res[1] if isinstance(res, tuple) else res
    if isinstance(q, dict) and isinstance(q.get("action"), dict) and "add_workspace" in q["action"]:
        from orch import chat_groups  # the person's Add on an ask-to-add card adds the workspace

        chat_groups.add_from_answer(root, tid, q, by)
        chat_groups.add_done(root, tid, qid)
    return res


def _asks_to_add(root: Path, tid: str, qid: str) -> bool:
    try:
        t = load(root, tid)
    except (Refused, OSError, ValueError):
        return False
    q = next((x for x in t.get("questions", []) if x.get("id") == qid), None)
    return isinstance(q, dict) and isinstance(q.get("action"), dict) and "add_workspace" in q["action"]


def _claims_ran(q: dict, text: str, decision: dict | None) -> bool:
    """A run card (ORCH-848) answered yes in any form other than the run itself: "I ran it", an approve or
    use decision, or anything that is not one of its other answers (no_label, its options)."""
    card = q.get("card")
    if not (isinstance(card, dict) and card.get("kind") == "run"):
        return False
    if isinstance(decision, dict):
        said = " ".join(str(decision.get("summary") or text).split()).casefold()
        return decision.get("action") in ("approve", "use", "use_with_changes") or "ran it" in said

    def norm(v: str) -> str:
        return " ".join(v.split()).casefold()

    from orch import runcard

    said = norm(text)
    no = card.get("no_label")
    # the one other answer: orch's own words (runcard.NO_LABELS), never the question's options or free text
    return not (isinstance(no, str) and no in runcard.NO_LABELS and said == norm(no))


def mark_question_sent(root: Path, tid: str, qid: str, by: str = "orch") -> None:
    """Record when a question went to the person's phones (questions[].sent_at, once): one quiet write under
    the ticket lock; a question that is gone or already marked changes nothing."""

    def op(ticket):
        q = next((x for x in ticket["questions"] if x["id"] == qid), None)
        if q is None or q.get("sent_at"):
            return NO_WRITE
        q["sent_at"] = now()
        return q

    apply_op(root, tid, op, by=by)


def record_answered(
    root: Path, tid: str, entry: dict, by: str, via: str, *, replaces: str | None = None, person: bool = False
) -> dict:
    """Append one already-answered questions[] entry (a Review stack decision that was not an open question:
    a Check result, or a changed answer). Nothing is overwritten: with `replaces` the old entry only gets
    decision.replaced_by. One apply_op, one history line "Answered <qid>: <summary>"."""
    if not VIA_RE.fullmatch(via):
        raise Refused("via must be a short word (a-z, 0-9, -), e.g. cli or dashboard.")
    if not isinstance(entry.get("answer"), str) or not entry["answer"].strip():
        raise Refused("An answer needs text.")
    if isinstance(entry.get("card"), dict) and not str(by).startswith("human:"):
        raise Refused(
            "This card waits for the owner. Ask with orch review add and wait with orch review wait."
        )
    ownerpick.refuse_card(entry, person and str(by).startswith("human:"))

    def op(ticket):
        old = None
        if replaces is not None:
            old = next((x for x in ticket["questions"] if x["id"] == replaces), None)
            if old is None or old.get("answer") is None:
                raise Refused(f"Ticket {tid} has no answered question {replaces}.")
            if (old.get("decision") or {}).get("replaced_by"):
                raise Refused(f"{replaces} was already replaced by a newer answer.")
        q = {
            "answer": None,
            "answered_by": None,
            "via": None,  # fixed key order, like ask()
            **{k: v for k, v in entry.items() if k not in ("id", "answered_by", "via", "at")},
        }
        q = {"id": _next_id(ticket["questions"], "q"), **q}
        q["answer"], q["answered_by"], q["via"], q["at"] = entry["answer"], by, via, now()
        q["answered_at"] = q["at"]
        if replaces is not None:
            q["decision"] = {**(q.get("decision") or {}), "replaces": replaces, "replaced_by": None}
            old["decision"] = {**(old.get("decision") or {}), "replaced_by": q["id"]}
        ticket["questions"].append(q)
        add_history(ticket, by, f"Answered {q['id']}: {q['answer']}", via)
        history.created("answers", q)
        return q

    return apply_op(root, tid, op, by=by)[1]


def waiting_value(kind: str, ref: str | None = None, until: str | None = None) -> dict:
    if kind not in WAIT_KINDS:
        raise Refused(f"A wait kind is one of: {', '.join(WAIT_KINDS)}.")
    if kind == "time":
        if not until:
            raise Refused("Waiting for a time needs until.")
        w = {"kind": "time", "until": parse_time(until)}
        if ref is not None:  # ORCH-235: what it waits for, as a person wrote it (optional)
            if not isinstance(ref, str) or len(ref.strip()) > 200:
                raise Refused("The reason of a wait has at most 200 characters.")
            if ref.strip():
                w["ref"] = ref.strip()
        return w
    if not isinstance(ref, str) or not ref.strip() or len(ref.strip()) > 200:
        raise Refused(f"Waiting on {kind} needs a ref (1 to 200 characters).")
    if kind == "pr":
        m = PR_WAIT_URL.match(ref.strip())
        if not m or ref.strip()[m.end() : m.end() + 1] not in ("", "/", "?", "#"):  # never .../pull/9oops
            raise Refused(
                "Waiting on a pull request needs its address: pr:https://github.com/<owner>/<repo>/pull/<n>"
            )
        return {"kind": "pr", "ref": m.group(0)}
    return {"kind": kind, "ref": ref.strip()}


def pr_ref(ticket: dict, url: str) -> dict | None:
    """The ticket's web reference to this pull request."""
    for r in ticket.get("refs") or []:
        u = r.get("url") if isinstance(r, dict) else None
        if isinstance(u, str) and (m := PR_WAIT_URL.match(u.strip())) and m.group(0).lower() == url.lower():
            return r
    return None


def _check_pr_wait(root: Path, ticket: dict, url: str) -> None:
    """Refuse a wait that no active reference provider can wake, or that is finished already."""
    from orch import addons, refs

    key = ticket.get("key") or ticket["id"]
    readers = {n: m for n, m in addons.active_manifests(root).items() if m.get("background")}
    if not any(
        refs.kind_for(url, [k]) == k["kind"] and set(PR_FINAL).issubset(k["statuses"])
        for k in refs.kinds_of(readers)
    ):
        raise Refused(
            "Nothing here tracks whether this pull request is merged or closed. Wait for a time instead "
            "(--until)."
        )
    r = pr_ref(ticket, url)
    if r is None:
        raise Refused(f"{key} does not link {url}. Link it first: orch ref add {key} {url}")
    if (r.get("status") or "") in PR_FINAL:
        raise Refused(f"{url} is {r['status']} already: nothing to wait for, go on with {key}.")


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

        return apply_op(root, tid, op, by=by)[0]
    if bool(until) == bool(on):
        raise Refused("Use exactly one of --until <time> or --on <kind>:<ref>.")
    if until:
        w = waiting_value("time", until=until)
        from .net import when as _local_when

        note = f"Waiting until {_local_when(w['until'])}"
    else:
        kind, sep, ref = on.partition(":")
        if not sep or kind not in WAIT_KINDS or kind == "time":
            raise Refused(
                "--on needs <kind>:<ref>, kind ticket, pr, question or external. For a time: --until."
            )
        w = waiting_value(kind, ref)
        if kind == "pr":
            _check_pr_wait(root, load(root, tid), w["ref"])
        note = f"Waiting on {kind} {w['ref']}"

    if _preparing_agent(root, tid, by):
        raise Refused(PREPARE_NO_STATUS)

    def op2(ticket):
        ticket["waiting_on"] = w
        ticket["status"] = "waiting"
        add_history(ticket, by, note)

    load(root, tid)
    return apply_op(root, tid, op2, by=by)[0]


def patch(root: Path, tid: str, if_revision: int, data: str, by: str, *, person: bool = False) -> dict:
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
    if obj.get("superseded_by") and obj.get("status", "dropped") != "dropped":
        raise Refused("superseded_by goes with the status dropped (Won't do).")
    other = superseded_value(root, tid, obj.get("superseded_by")) if "superseded_by" in obj else None

    def op(ticket):
        if other and "status" not in obj and ticket["status"] != "dropped":
            raise Refused("superseded_by goes with the status dropped (Won't do).")
        if "title" in obj:
            if obj["title"].strip() != ticket.get("title"):
                ticket.pop("title_auto", None)
            ticket["title"] = obj["title"].strip()
        status = obj.get("status", ticket["status"])
        if status not in STATUSES:
            raise Refused(f"Status must be one of: {', '.join(STATUSES)}.")
        actor = by
        if "status" in obj:
            status, actor = _finish_status(root, ticket, status, by, person)
            if status in ("open", "ready") and not actor.startswith("agent:"):
                ticket.pop("started", None)
        for k in ("owner", "due", "note", "done_when", "summary"):
            if k in obj:
                _set_field(ticket, k, obj[k])
        if "waiting_on" in obj:
            ticket["waiting_on"] = w
        if status != "waiting":
            ticket["waiting_on"] = None
        _keep_superseded(ticket, status, other, "superseded_by" in obj)
        old, ticket["status"] = ticket["status"], status
        note = f" (status {old} -> {status})" if old != status else ""
        add_history(ticket, actor, "Patched " + ", ".join(sorted(obj)) + note)
        if status == "done" and old != "done":
            _note_agent_finish(ticket, actor)

    return apply_op(root, tid, op, if_revision=if_revision, by=by)[0]


# ---------------------------------------------------------------- agent sessions (used by the run lane)


OWN_SESSIONS_MAX = 500


def adopt_own_sessions(root: Path) -> None:
    """Run the one-time adoption of this machine's existing sessions now (if it hasn't run yet). The sync
    add-on calls this before its first fetch, so synced tickets can never take part in the adoption."""
    if not tickets_dir(root).is_dir():  # nothing to adopt; don't create the folder (the lock lives there)
        marker = root / ".orch" / "run" / "own-sessions.adopted"
        if not marker.exists():
            net.write_json(marker, {"adopted": True})
        return
    _own_sessions(root)


def _own_sessions(root: Path) -> list[dict]:
    """Read local ownership, adopting pre-record sessions once under the writer's lock."""
    with _locked(root, "own-sessions"):
        return _own_sessions_locked(root)


def _own_sessions_locked(root: Path) -> list[dict]:
    """Caller holds own-sessions. After adoption, absent or corrupt records grant nothing."""
    path = root / ".orch" / "run" / "own-sessions.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    entries = [
        s
        for s in (entries if isinstance(entries, list) else [])
        if isinstance(s, dict)
        and valid_session_id(s.get("id"))
        and all(
            isinstance(s.get(k), str) and s[k] for k in ("id", "agent", "host", "ticket_id", "first_seen")
        )
    ]
    marker = path.with_name("own-sessions.adopted")
    if not marker.exists():
        from orch import harness, runs

        host, first_seen = runs.host(), now()
        owned = {(s["id"], s["agent"], s["host"], s["ticket_id"]) for s in entries}
        adopted = []
        # Shared tickets cannot establish local ownership, even when the hostname matches.
        # General/Chat tickets also use sessions_for and therefore have session semantics.
        candidates = []
        for p in sorted(tickets_dir(root).glob("t_*.json")):
            try:
                ticket = load(root, p.stem)  # refuses embedded id / trusted filename mismatches
            except (OSError, ValueError, Refused):
                continue
            sessions = ticket.get("sessions")
            if not isinstance(sessions, list) or not sessions:
                continue
            candidates.append((p, sessions))
        tracked = harness.tracked_ticket_paths(root) if candidates else set()
        for p, sessions in candidates:
            if tracked is None or p.relative_to(root).as_posix().casefold() in tracked:
                continue  # git failures grant no ownership
            for s in sessions:
                if (
                    not isinstance(s, dict)
                    or s.get("host") != host
                    or not valid_session_id(s.get("id"))
                    or not isinstance(s.get("agent"), str)
                    or not config.NAME_RE.fullmatch(s["agent"])
                ):
                    continue
                key = (s["id"], s["agent"], host, p.stem)
                if key not in owned:
                    adopted.append(
                        {
                            "id": s["id"],
                            "agent": s["agent"],
                            "host": host,
                            "ticket_id": p.stem,
                            "first_seen": first_seen,
                        }
                    )
                    owned.add(key)
        # Keep valid old ownership preferentially when migration reaches the cap.
        merged = {(s["id"], s["agent"], s["host"], s["ticket_id"]): s for s in adopted + entries}
        entries = list(merged.values())[-OWN_SESSIONS_MAX:]
        net.write_json(path, entries)
        net.write_json(marker, {"adopted": True})
    return entries


def _record_own_session(root: Path, tid: str, agent: str, sid: str, host: str) -> None:
    with _locked(root, "own-sessions"):
        entries = _own_sessions_locked(root)
        entry = next(
            (
                s
                for s in entries
                if (s["id"], s["agent"], s["host"], s["ticket_id"]) == (sid, agent, host, tid)
            ),
            {"id": sid, "agent": agent, "host": host, "ticket_id": tid, "first_seen": now()},
        )
        entries = [s for s in entries if s != entry]
        entries.append(entry)
        # atomic temp + replace in net (never through a link); only tickets._write replaces files in here
        net.write_json(root / ".orch" / "run" / "own-sessions.json", entries[-OWN_SESSIONS_MAX:])


SESSIONS_KEPT = 10  # sessions remembered per ticket, the ones in use included (owner's choice, ORCH-363)


def _keep_last_sessions(sessions: list) -> None:
    """Forget the oldest replaced sessions so a ticket remembers at most SESSIONS_KEPT (the ones in use always
    stay; only the ids are forgotten here: the tool's own conversation file is never touched)."""
    earlier = [
        (e.get("last_used") or "", -j, i)  # same time: the earlier place in a list is the newer one
        for i, s in enumerate(sessions)
        if isinstance(s, dict)
        for j, e in enumerate(s.get("earlier") or [])
        if isinstance(e, dict)
    ]
    room = max(0, SESSIONS_KEPT - len(sessions))
    if len(earlier) <= room:
        return
    drop = {(i, -nj) for _, nj, i in sorted(earlier, reverse=True)[room:]}
    for i, s in enumerate(sessions):
        if isinstance(s, dict) and s.get("earlier"):
            s["earlier"] = [e for j, e in enumerate(s["earlier"]) if (i, j) not in drop]
            if not s["earlier"]:
                del s["earlier"]


def record_session(root: Path, tid: str, agent: str, sid: str, host: str) -> dict:
    """Remember the agent session for this agent and machine (updates last_used when it is known)."""
    if not valid_session_id(sid):
        raise Refused(
            "Invalid session id: use 1-128 letters, digits, underscores or hyphens, "
            "starting with a letter or digit."
        )

    def op(t):
        sessions = t.setdefault("sessions", [])
        for s in sessions:
            if s.get("agent") == agent and s.get("host") == host:
                if s.get("id") != sid and valid_session_id(s.get("id")):
                    # keep the replaced conversation so a person can read or continue it later
                    old = [e for e in s.get("earlier") or [] if isinstance(e, dict) and e.get("id") != sid]
                    old.insert(0, {"id": s["id"], "last_used": s.get("last_used")})
                    s["earlier"] = old
                elif s.get("earlier"):
                    s["earlier"] = [e for e in s["earlier"] if e.get("id") != sid]
                s["id"], s["last_used"] = sid, now()
                break
        else:
            sessions.append({"agent": agent, "id": sid, "host": host, "last_used": now()})
            if len(sessions) > 32:
                sessions.sort(key=lambda s: s.get("last_used", ""))
                del sessions[0 : len(sessions) - 32]
        _keep_last_sessions(sessions)

    ticket = apply_op(root, tid, op, by=SYSTEM)[0]
    _record_own_session(root, tid, agent, sid, host)
    return ticket


RUNS_KEPT = 50
RUN_ID_RE = re.compile(r"r_[a-z0-9_]{6,32}")


def _run_entry(ticket: dict, run: str) -> dict | None:
    rs = ticket.get("runs")
    if not isinstance(rs, list):
        return None
    return next((r for r in rs if isinstance(r, dict) and r.get("id") == run), None)


def run_started(root: Path, tid: str, run: str, agent: str) -> None:
    """A helper run began on the ticket: one record in `runs` (history.md 'Runs'), once per run id."""
    if not RUN_ID_RE.fullmatch(run or ""):
        return

    def op(t):
        if _run_entry(t, run) is not None:
            return NO_WRITE
        rs = t["runs"] if isinstance(t.get("runs"), list) else []
        rs.append({"id": run, "agent": agent, "started": now()})
        t["runs"] = rs[-RUNS_KEPT:]

    apply_op(root, tid, op, by=SYSTEM, keep_revision=True)


def run_ended(root: Path, tid: str, run: str) -> None:
    """The run ended: its record gets the end time and its whole minutes. A run with no record (it never got
    going) or one that ended already is left alone."""

    def op(t):
        r = _run_entry(t, run)
        if r is None or r.get("ended"):
            return NO_WRITE
        r["ended"] = now()
        with contextlib.suppress(TypeError, ValueError):
            start = datetime.fromisoformat(str(r["started"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(r["ended"].replace("Z", "+00:00"))
            r["minutes"] = max(0, round((end - start).total_seconds() / 60))

    apply_op(root, tid, op, by=SYSTEM, keep_revision=True)


def _note_run_task(t: dict, cid: str) -> None:
    """`orch check done` inside a helper run (ORCH_RUN): the step goes on that run's record of this ticket."""
    r = _run_entry(t, os.environ.get("ORCH_RUN", ""))
    if r is None or r.get("ended"):
        return
    tasks = r["tasks"] if isinstance(r.get("tasks"), list) else []
    if cid not in tasks and len(tasks) < 200:
        r["tasks"] = [*tasks, cid]


def sessions_for(root: Path, tid: str, ticket: dict, agent: str, host: str) -> str | None:
    """Resume local sessions for the trusted file/resolve id, never the peer-controlled ticket id."""
    owned = {(s["id"], s["agent"], s["host"], s["ticket_id"]) for s in _own_sessions(root)}
    for s in ticket.get("sessions") or []:
        if (
            isinstance(s, dict)
            and valid_session_id(s.get("id"))
            and s.get("agent") == agent
            and s.get("host") == host
            and (s["id"], agent, host, tid) in owned
        ):
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
    return f"{name} is too big. An evidence file can be at most 25 MB. Use --url or --note."


def attach_file(
    root: Path,
    tid: str,
    path: str,
    title: str | None,
    role: str | None,
    summary: str | None = None,
    *,
    by: str,
) -> dict:
    """Copy a workspace file into the ticket's evidence/ folder (gate -> ticket lock held for the copy).
    An agent actor is refused on a closed ticket before anything is written (#542)."""
    ticket_path(root, tid)
    with _locked(root, tid):
        _refuse_closed_agent(root, tid, by)
        return _attach_file(root, tid, path, title, role, summary)


def _own_copy(root: Path, tid: str) -> Path | None:
    """The resolved folder of THIS ticket's own working copy (worktrees.path_for), or None when there is none
    (no copy, not made by orch, a link). Never another ticket's or workspace's copy."""
    from orch import addons, worktrees

    try:
        want = worktrees.path_for(addons.workspace_id(root) or "", tid, addons.home(root))
        if want.is_symlink() or not want.is_dir() or not worktrees.is_orch_copy(want):
            return None
        return Path(os.path.realpath(want))
    except (Refused, OSError, RuntimeError, ValueError):
        return None


def _attach_file(
    root: Path, tid: str, path: str, title: str | None, role: str | None, summary: str | None = None
) -> dict:
    """Copy a workspace file into .orch/tickets/<tid>/evidence/ and return the evidence entry for it.
    Only regular files inside the workspace, no link followed anywhere on the way, at most 25 MB."""
    load(root, tid)
    if role is not None and role not in ROLES:
        raise Refused(f"An evidence role is one of: {', '.join(ROLES)}.")
    if title is not None and not 1 <= len(title.strip()) <= 120:
        raise Refused("An evidence title needs 1 to 120 characters.")
    refuse_secret_in_evidence(
        root,
        [{"type": "file", "ref": os.path.basename(path), "title": title or "", "summary": summary or ""}],
    )
    if summary:  # checked before anything is copied
        summary = parse_evidence(json.dumps({"type": "file", "ref": "x", "summary": summary}))["summary"]
    base = Path(os.path.realpath(root))
    given = Path(os.path.abspath(os.path.expanduser(path)))
    rel = None
    src_base = base
    for b in (Path(os.path.abspath(root)), base):
        try:
            rel = given.relative_to(b)
            break
        except ValueError:
            continue
    if rel is None:  # a helper works in this ticket's own copy: files from THAT copy (only) count too
        own = _own_copy(root, tid)
        if own is not None:
            for b in (Path(os.path.abspath(own)), own):
                try:
                    rel, src_base = given.relative_to(b), own
                    break
                except ValueError:
                    continue
    inside = Refused("evidence files must be inside this workspace or this ticket's own working copy.")
    if rel is None or ".." in rel.parts:
        raise inside
    cur = src_base
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise Refused("evidence files cannot be refs. Give the real file.")
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
            f"{cur_src.name} is {_size_text(size)}. "
            "An evidence file can be at most 25 MB. Use --url or --note."
        )
    dest_dir = base / ".orch" / "tickets" / tid / "evidence"
    cur = base
    for part in (".orch", "tickets", tid, "evidence"):
        cur = cur / part
        if cur.is_symlink():
            raise Refused("The evidence folder of this ticket is a link. orch will not copy into it.")
        if cur.exists() and not cur.is_dir():
            raise Refused("The evidence folder of this ticket is blocked by a file. Move that file away.")
        if not cur.exists():
            cur.mkdir()
    real_dir = Path(os.path.realpath(dest_dir))
    if real_dir != dest_dir or not str(real_dir).startswith(str(base / ".orch" / "tickets") + os.sep):
        raise Refused("The evidence folder of this ticket is not inside this workspace.")
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
        raise Refused("evidence files cannot be refs. Give the real file.") from None
    try:
        with os.fdopen(src_fd, "rb") as src, os.fdopen(fd, "wb") as out:
            if os.fstat(src.fileno()).st_size > MAX_PROOF_BYTES:
                raise Refused(_too_big(cur_src.name))
            data = src.read(MAX_PROOF_BYTES + 1)  # bounded: a file that grows while we copy is refused too
            if len(data) > MAX_PROOF_BYTES:
                raise Refused(_too_big(cur_src.name))
            from orch import secretscan

            secretscan.refuse_if_secret(data, "evidence file", root, verb="saved")  # R5.2 (#942)
            out.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(dest)
        raise
    ev = {
        "type": "file",
        "ref": dest.relative_to(base).as_posix(),
        "text": _size_text(size),
        "source": rel.as_posix(),
    }
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


def proof_source(root: Path, tid: str, ev: dict) -> bytes | None:
    """The file a copied proof was made from (`source`), as it is on disk now: read from this ticket's own
    working copy when it has the file, else from the workspace. None when there is no such file or source."""
    from orch import safefile

    src = ev.get("source") if ev.get("type") == "file" else None
    if not isinstance(src, str) or not src or "\x00" in src:
        return None
    own = _own_copy(root, tid)
    for base in (own, root) if own is not None else (root,):
        try:
            data = safefile.open_file_ref(base, src, MAX_PROOF_BYTES)
        except (OSError, ValueError, safefile.TooLarge):
            continue
        if data is not None:
            return data
    return None


_CHANGED_CACHE: dict = {}  # (copy path, source text, tid) -> (stat key, changed)


def _stat_key(p: Path):
    try:
        st = os.stat(p, follow_symlinks=False)
    except (OSError, ValueError):
        return None
    # identity and ctime too: a file swapped in with the same size and copied mtime is still a different file
    return st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino, st.st_ctime_ns


def proof_changed(root: Path, tid: str, ev: dict) -> bool:
    """True when the file a copied proof was made from is still there but differs from the copy (ORCH-1874):
    the copy is what the step proved, the file on disk is what the person gets now. Files are read again only
    when one of them changed on disk (a page is polled)."""
    from orch import safefile

    ref, src = str(ev.get("ref", "")), ev.get("source")
    head = f".orch/tickets/{tid}/evidence/"
    if ev.get("type") != "file" or not ref.startswith(head) or not isinstance(src, str) or not src:
        return False
    own = _own_copy(root, tid)
    stats = (_stat_key(root / ref), own, *(_stat_key(b / src) for b in ((own, root) if own else (root,))))
    key = (str(root), ref, src)
    hit = _CHANGED_CACHE.get(key)
    if hit is not None and hit[0] == stats:
        return hit[1]
    changed = False
    try:
        copy = safefile._read_parts(
            root, [".orch", "tickets", tid, "evidence"], ref[len(head) :].split("/"), MAX_PROOF_BYTES
        )
    except (OSError, ValueError, safefile.TooLarge):
        copy = None
    if copy is not None:
        now = proof_source(root, tid, ev)
        changed = now is not None and now != copy
    if len(_CHANGED_CACHE) > 512:
        _CHANGED_CACHE.clear()
    _CHANGED_CACHE[key] = (stats, changed)
    return changed


# ---------------------------------------------------------------- artifacts


def artifacts_path(root: Path, tid: str) -> Path:
    """.orch/tickets/<id>/artifacts/ : where the files a ticket produces go (next to evidence/)."""
    load(root, tid)
    return tickets_dir(root) / tid / "artifacts"


def files_dir(root: Path, tid: str) -> Path:
    """.orch/tickets/<id>/files/ : files people send to the ticket (from the phone), created. A link anywhere
    on the way is refused. Only the creation is guarded; to WRITE a file there use files_dir_locked."""
    ticket_path(root, tid)
    with _locked(root, tid):
        return _files_dir_raw(root, tid)


@contextlib.contextmanager
def files_dir_locked(root: Path, tid: str):
    """The files folder for one write: the gate check and the ticket lock are held for the whole `with`."""
    ticket_path(root, tid)
    with _locked(root, tid):
        yield _files_dir_raw(root, tid)


def _files_dir_raw(root: Path, tid: str) -> Path:
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
    """The ticket's artifacts folder, created (guarded by the sync gate). A link anywhere on the way is
    refused. Agents write files there with plain file I/O: not gated (a merge skips a changed path)."""
    ticket_path(root, tid)
    with _locked(root, tid):
        return _artifacts_dir_raw(root, tid)


def _artifacts_dir_raw(root: Path, tid: str, sub: tuple = ()) -> Path:
    d = artifacts_path(root, tid).joinpath(*sub)
    cur = root / ".orch"
    for part in ("tickets", tid, "artifacts", *sub):
        cur = cur / part
        if cur.is_symlink():
            raise Refused("The artifacts folder of this ticket is a link. orch will not use it.")
        if cur.exists() and not cur.is_dir():
            raise Refused("The artifacts folder of this ticket is blocked by a file. Move that file away.")
        if not cur.exists():
            cur.mkdir()
    return d


# What a person may attach to a ticket from the dashboard or the phone: text, pictures and voice recordings.
# Never a page or a program that runs: html, xml, svg and scripts are not accepted.
# (The dashboard's actions.py mirrors these limits to refuse early; orch here is the one that decides.)
ATTACH_TEXT = frozenset({"txt", "md", "csv", "tsv", "json", "log", "yml", "yaml", "toml", "ini"})
ATTACH_IMAGES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}
# A voice note recorded in the browser (ORCH-422): Chrome and Edge record webm, Firefox ogg,
# Safari mp4 (kept as m4a).
# Each is checked by its first bytes like a picture; nothing in it runs.
ATTACH_AUDIO = {
    "webm": (b"\x1a\x45\xdf\xa3",),
    "ogg": (b"OggS",),
    "m4a": (),  # an mp4 box: "ftyp" at byte 4 (checked below)
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "wav": (b"RIFF",),
}
ATTACH_MAX = 25 * 1024 * 1024  # one attached file: the one limit (dashboard and Focus use it too)
LONG_TEXT = 1500  # a text longer than this is kept as a file (note.md); the Note stays short
PASTED_NAME = "note.md"


def attach_name(hint) -> str:
    """The file name the SERVER keeps: the base name of the hint only, safe characters, an allowed type.
    A name from a browser or a phone is a hint, never a path."""
    base = re.split(r"[\\/]", clean_untrusted(str(hint), 1000))[-1].strip().strip(". ")
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    base = re.sub(r"\.{2,}", ".", base)
    stem, dot, ext = base.rpartition(".")
    ext = ext.lower()
    stem = stem.strip()[:80].strip(". ")
    allowed = ext in ATTACH_TEXT or ext in ATTACH_IMAGES or ext in ATTACH_AUDIO
    if not dot or not stem.strip("._ -") or not allowed:
        raise Refused("That kind of file cannot be attached. Text files, pictures and voice recordings can.")
    if stem.split(".")[0].lower() in _WIN_RESERVED:
        stem = "_" + stem
    return stem + "." + ext


def _check_attach(name: str, data) -> str:
    ext = name.rsplit(".", 1)[-1]
    if not isinstance(data, bytes) or not data:
        raise Refused("That file is empty.")
    if len(data) > ATTACH_MAX:
        raise Refused(f"A file is at most {ATTACH_MAX // (1024 * 1024)} MB.")
    if ext in ATTACH_IMAGES:
        if not data.startswith(ATTACH_IMAGES[ext]) or (ext == "webp" and data[8:12] != b"WEBP"):
            raise Refused("That picture is not what its name says.")
    elif ext in ATTACH_AUDIO:
        ok = (
            data[4:8] == b"ftyp"
            if ext == "m4a"
            else data.startswith(ATTACH_AUDIO[ext]) and (ext != "wav" or data[8:12] == b"WAVE")
        )
        if not ok:
            raise Refused("That recording is not what its name says.")
    else:
        if b"\x00" in data:
            raise Refused("That file is not plain text.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise Refused("That file is not plain text (UTF-8).") from None
    return ext


def _open_artifacts_fd(root: Path, tid: str, sub: tuple = ()) -> int:
    """A handle on .orch/tickets/<id>/artifacts (created), every folder opened from the workspace root with
    O_NOFOLLOW|O_DIRECTORY: a folder swapped for a link meanwhile is refused, never followed."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in (".orch", "tickets", tid, "artifacts", *sub):
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part, dir_fd=fd)
                nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except OSError:
        os.close(fd)
        raise Refused(
            "The artifacts folder of this ticket is a link or blocked by a file. orch will not use it."
        ) from None


# A person's feedback files (screenshots, files, voice notes sent with an answer on Review) go in this
# sub-folder of the artifacts: the Files tab lists them, but a Check card shows only the helper's own result
# files, so adding feedback never makes the card being answered look changed (ORCH-420 follow-up).
FEEDBACK_DIR = "feedback"


REQUEST_FILES_MAX = 100


def _add_request_file(ticket: dict, name: str) -> None:
    """#1812: the file came with the request (the files sent with a new ticket), kept by name."""
    req = ticket.get("request") if isinstance(ticket.get("request"), dict) else {}
    old = req.get("files") if isinstance(req.get("files"), list) else []
    files = [f for f in old if isinstance(f, str)]
    if name not in files and len(files) < REQUEST_FILES_MAX:
        files.append(name)
    ticket["request"] = {**req, "files": files}


def attach(
    root: Path,
    tid: str,
    hint,
    data: bytes,
    by: str,
    *,
    exact: str | None = None,
    folder: str | None = None,
    request: bool = False,
) -> dict:
    """The file is written under gate -> ticket lock; the history line (its own lock) comes after.
    Keep `data` as a file in .orch/tickets/<id>/artifacts/ (name picked by attach_name; a clash gets
    ' (2)', ' (3)' ...; created with O_EXCL, no link followed on the file or any folder). Text must be UTF-8
    without NUL bytes, a picture must start with its type's signature. One history line says what was
    attached. `exact` (an allowed file name made by orch itself): that name or nothing, an existing file
    means it was done before (returned with existed=True, nothing written). `request`: the file came with the
    request (a new ticket's files): its name is kept in the ticket's `request.files`."""
    if folder not in (None, FEEDBACK_DIR):
        raise Refused("That folder is not allowed.")
    ticket_path(root, tid)
    with _locked(root, tid):
        _refuse_closed_agent(root, tid, by)  # before the file is written
        res = _attach_write(root, tid, hint, data, exact, (folder,) if folder else ())
    text = f"Attached {res['name']}"
    # done before: only the history line may be missing (an earlier call was refused as busy after the file
    # was written); add it if it is not there
    there = lambda t: res.get("existed") and any(h.get("text") == text for h in t.get("history", []))  # noqa: E731

    def op(t):
        line = not there(t)
        kept = request and res["name"] in ((t.get("request") or {}).get("files") or [])
        if not line and (not request or kept):
            return NO_WRITE
        if line:
            add_history(t, by, text)
        if request:
            _add_request_file(t, res["name"])

    apply_op(root, tid, op, by=by)
    return res


def _result_by(by: str) -> str:
    """Who added a file nobody attached: the agent whose write found it, else orch itself (never a person)."""
    return by if str(by).startswith("agent:") else SYSTEM


RESULT_LINE = "Added file "
RESULT_LINES_MAX = 50  # one sweep writes at most this many lines; the rest come on the next one


def note_results(root: Path, ticket: dict, by: str) -> None:
    """#1812: one history line per file that landed in the ticket's results folder (artifacts/) by plain file
    I/O since the last look, with the file's time at that look: a later rewrite never moves it. Files a person
    attached (an "Attached <name>" line) and feedback files are theirs already. Called inside a write
    (status, check done, summary), so a helper's files are on the history when its work is shown."""
    d = tickets_dir(root) / ticket["id"] / "artifacts"
    try:
        if d.is_symlink() or not d.is_dir():
            return
        found = []
        for f in d.rglob("*"):
            rel = f.relative_to(d)
            if f.is_symlink() or not f.is_file() or any(p.startswith(".") for p in rel.parts):
                continue
            if rel.parts[0] == FEEDBACK_DIR and len(rel.parts) > 1:
                continue
            found.append((f.stat().st_mtime, rel.as_posix()))
    except OSError:
        return
    seen = set()
    for h in ticket.get("history", []):
        text = str(h.get("text", ""))
        for head in ("Attached ", RESULT_LINE):
            if text.startswith(head):
                seen.add(text[len(head) :])
    t_now = now()
    for mtime, name in sorted(x for x in found if x[1] not in seen)[:RESULT_LINES_MAX]:
        at = datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        at = max(min(at, t_now), str(ticket.get("created_at") or at))
        add_history(ticket, by, RESULT_LINE + name, at=at)


def _attach_write(root: Path, tid: str, hint, data: bytes, exact: str | None, sub: tuple = ()) -> dict:
    load(root, tid)  # the id has the shape of a ticket id and the ticket exists
    name = attach_name(exact or hint)
    if exact and name != exact:
        raise Refused("That file name is not allowed.")
    ext = _check_attach(name, data)
    stem = name[: -len(ext) - 1]
    wflags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    if hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd:
        dfd = _open_artifacts_fd(root, tid, sub)
        opener = lambda n: os.open(n, wflags, 0o644, dir_fd=dfd)  # noqa: E731
        remove = lambda n: os.unlink(n, dir_fd=dfd)  # noqa: E731
        linker = lambda a, b: os.link(a, b, src_dir_fd=dfd, dst_dir_fd=dfd, **_nofollow_link())  # noqa: E731
        lstat = lambda n: os.stat(n, dir_fd=dfd, follow_symlinks=False)  # noqa: E731
        names = lambda: os.listdir(dfd)  # noqa: E731
        close = lambda: os.close(dfd)  # noqa: E731
    else:  # Windows: no handles on folders; the folders are checked one by one
        d0 = _artifacts_dir_raw(root, tid, sub)
        opener = lambda n: os.open(d0 / n, wflags, 0o644)  # noqa: E731
        remove = lambda n: (d0 / n).unlink()  # noqa: E731
        linker = lambda a, b: os.link(d0 / a, d0 / b, **_nofollow_link())  # noqa: E731
        lstat = lambda n: os.lstat(d0 / n)  # noqa: E731
        names = lambda: os.listdir(d0)  # noqa: E731
        close = lambda: None  # noqa: E731
    tmp = f".{secrets.token_hex(6)}.part"  # written whole under a hidden name, then linked to its final name
    try:
        _sweep_parts(names, lstat, remove)
        fd = opener(tmp)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                written = os.fstat(f.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                remove(tmp)
            raise
        try:
            for n in range(1, 100):
                final = name if n == 1 else f"{stem} ({n}).{ext}"
                if exact and n > 1:
                    break
                try:
                    _publish(linker, opener, remove, lstat, tmp, final, data, written)
                except FileExistsError:
                    if exact:
                        return {
                            "name": "/".join((*sub, final)),
                            "size": len(data),
                            "path": _art_rel(tid, "/".join((*sub, final))),
                            "existed": True,
                        }
                    continue
                break
            else:
                raise Refused("Too many files with that name on this ticket.")
        finally:
            with contextlib.suppress(OSError):
                remove(tmp)
    finally:
        close()
    shown = "/".join((*sub, final))
    return {"name": shown, "size": len(data), "path": _art_rel(tid, shown)}


def _nofollow_link() -> dict:
    # Windows CPython has no linkat: follow_symlinks=False raises NotImplementedError there. The identity
    # check after linking (device + inode) covers a swapped file either way.
    return {"follow_symlinks": False} if os.link in os.supports_follow_symlinks else {}


def _publish(linker, opener, remove, lstat, tmp: str, final: str, data: bytes, written) -> None:
    """Give the finished temp file its final name without replacing anything: a hard link (then the file is
    checked to be the very one we wrote). A file system that cannot link (FAT, some network drives) gets an
    O_EXCL create of the final name and a copy instead. FileExistsError means the name is taken."""
    try:
        linker(tmp, final)
    except FileExistsError:
        raise
    except (OSError, NotImplementedError):
        fd = opener(final)  # O_EXCL | O_NOFOLLOW; FileExistsError is the same "taken"
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            with contextlib.suppress(OSError):
                remove(final)
            raise
        return
    st = lstat(final)
    if (st.st_dev, st.st_ino) != (written.st_dev, written.st_ino) or not stat.S_ISREG(st.st_mode):
        with contextlib.suppress(OSError):
            remove(final)
        raise Refused("The file was replaced while it was saved. Not kept.")


def _sweep_parts(names, lstat, remove) -> None:
    """Leftovers of a killed attach (hidden .part files older than an hour) are removed."""
    with contextlib.suppress(OSError):
        for n in names():
            if n.startswith(".") and n.endswith(".part") and time.time() - lstat(n).st_mtime > 3600:
                with contextlib.suppress(OSError):
                    remove(n)


def _art_rel(tid: str, name: str) -> str:
    return f".orch/tickets/{tid}/artifacts/{name}"


def artifacts_list(root: Path, tid: str) -> list[dict]:
    """The files in the ticket's artifacts folder (sub-folders included): name, size, mtime, path."""
    d = artifacts_path(root, tid)
    out = []
    if d.is_dir() and not d.is_symlink():
        for f in sorted(d.rglob("*")):
            if f.is_symlink() or not f.is_file() or any(p.startswith(".") for p in f.relative_to(d).parts):
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
