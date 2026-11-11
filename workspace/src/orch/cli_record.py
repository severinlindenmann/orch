"""`orch record tail | query | counts | settings | delete-detail` (contracts/activity.md, counts.md).

Every view reads the record through these commands (add-ons never read the files). The views write nothing
(but `settings` may record a lowered retention value, humanproof.retention) and need no proof. `delete-detail`
is a person's own decision (op `record.delete_detail`, invariant H1).
"""

import argparse
import base64
import binascii
import heapq
import json
import re
import sys
import time
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import record
from orch.errors import Refused

SUBCOMMANDS = ("tail", "query", "counts", "settings", "delete-detail", "hook")
_BUILT = ("tail", "query", "counts", "settings", "delete-detail", "hook")
_RUN = re.compile(r"^r_[a-z0-9_]{6,32}$")
_TICKET = re.compile(r"^t_[a-z0-9]{6,16}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KINDS = (
    "step",
    "task.start",
    "task.done",
    "ask",
    "denial",
    "helper.start",
    "helper.end",
    "run.state",
    "usage",
    "key.use",
    "job",
    "session.input",
)
_USED_KINDS = ("skill", "tool", "mcp", "key", "helper")
_PREFIX = "rc1."
_MAX_CURSOR = 4096
POLL_SECONDS = 1.0
PING_SECONDS = 15.0


def _ticket_title(root, tid: str) -> str:
    """The ticket's title for the proof card (plain text, capped; the card shows it as text only)."""
    from orch import tickets

    try:
        t = tickets.load(root, tid).get("title")
    except Refused:
        return tid
    return t[:200] if isinstance(t, str) and t.strip() else tid


class RecordError(Refused):
    """A refusal with a contract error code (`{"error", "code"}`, exit 2)."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code
        self.extra = {"code": code}


def add_parsers(sub, common) -> None:
    r = sub.add_parser("record", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    t = r.add_parser("tail", parents=[common], help=argparse.SUPPRESS)
    t.add_argument("--ticket")
    t.add_argument("--run")
    t.add_argument("--since")
    t.add_argument("--after")
    t.add_argument("--follow", action="store_true")
    q = r.add_parser("query", parents=[common], help=argparse.SUPPRESS)
    q.add_argument("--ticket")
    q.add_argument("--run")
    q.add_argument("--kind", action="append")
    q.add_argument("--from", dest="from_")
    q.add_argument("--to")
    q.add_argument("--limit")
    q.add_argument("--after")
    q.add_argument("--detail")
    h = r.add_parser("hook", parents=[common], help=argparse.SUPPRESS)
    h.add_argument("--strict", action="store_true")
    c = r.add_parser("counts", parents=[common], help=argparse.SUPPRESS)
    c.add_argument("--days")
    c.add_argument("--from", dest="from_")
    c.add_argument("--to")
    c.add_argument("--ticket")
    c.add_argument("--kind", action="append")
    r.add_parser("settings", parents=[common], help=argparse.SUPPRESS)
    d = r.add_parser("delete-detail", parents=[common], help=argparse.SUPPRESS)
    d.add_argument("ticket")
    for name in SUBCOMMANDS:
        if name not in _BUILT:
            r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def _run_hook(find_root, strict: bool, before_write=lambda: None) -> int:
    """The hook's exit-0 wrapper: ANY failure (a SystemExit from argparse or sys.exit included) ends with one
    stderr line and exit 0; only --strict gives 2. Never re-raises."""
    try:
        from orch import record_hook

        record_hook.cli(find_root(), strict=strict, before_write=before_write)
        return 0
    except BaseException as e:  # noqa: BLE001 - a tool's hook: exit 2 would block the tool call
        note = str(e) if isinstance(e, Refused) and str(e) else "nothing was recorded."
    if strict:
        print(f"Refused: {note}", file=sys.stderr)
        return 2
    sys.stderr.write(f"orch: {note}\n")
    return 0


def hook_main(argv: list[str], watchdog=None) -> int:
    """`orch record hook [--strict]`, called from cli.main before the parser, the chat guard and the notices:
    a tool's hook runs before every tool call and exit 2 would block it. The wiring must call exactly
    `orch record hook`; global flags before it (--json, --root) are not understood here and are ignored."""
    from orch import workcheck

    timer = workcheck.start_watchdog()  # a hung hook ends quietly (exit 0) after the hard timeout
    if watchdog is not None:
        watchdog.cancel()
    try:
        from orch import cli

        # the timer is cancelled before the first write: os._exit never lands in the middle of one
        return _run_hook(cli._find_root, "--strict" in argv, before_write=timer.cancel)
    finally:
        timer.cancel()


def dispatch(args, root: Path) -> bool:
    if args.cmd != "record":
        return False
    if not args.sub:
        raise Refused("`orch record` needs a subcommand. Subcommands: " + ", ".join(SUBCOMMANDS) + ".")
    if args.sub == "hook":  # one event line on stdin from a live session's tool hook; never blocks the agent
        # reached only by a form hook_main does not take (a global flag before `record`): same exit-0 rule
        from orch import workcheck

        timer = workcheck.start_watchdog()
        try:
            if _run_hook(lambda: root, args.strict, before_write=timer.cancel):
                raise Refused("Nothing was recorded.")
        finally:
            timer.cancel()
        return True
    if args.sub not in _BUILT:
        raise Refused(f"`orch record {args.sub}` is not built yet.")
    if not args.json:
        raise RecordError("Use --json.")
    try:
        if args.sub == "tail":
            _tail_cli(args, root)
        elif args.sub == "query":
            _emit(query(root, args))
        elif args.sub == "settings":
            _emit(settings(root))
        elif args.sub == "delete-detail":
            _emit(delete_detail(root, args))
        else:
            _emit(counts(root, args))
    except record.RecordRefused as e:
        _show_alert(e.alert)
        raise RecordError(str(e), e.code) from None
    return True


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# --- cursors ---
def _pack(value, *, compress: bool = False) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    if compress:
        raw = zlib.compress(raw, 9)
    cursor = _PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    if len(cursor) > _MAX_CURSOR:
        raise RecordError(
            "The record is too big to follow from one position. Start again without a cursor.", "too_large"
        )
    return cursor


def _unpack(text, *, compress: bool = False) -> dict:
    bad = RecordError("That position in the record is not valid.")
    if not isinstance(text, str) or not text.startswith(_PREFIX) or len(text) > _MAX_CURSOR:
        raise bad
    body = text[len(_PREFIX) :]
    if not re.fullmatch(r"[A-Za-z0-9_-]*", body):
        raise bad
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        if compress:  # a bounded inflate: a small cursor never becomes a large buffer
            inflater = zlib.decompressobj()
            raw = inflater.decompress(raw, 1 << 20)
            if inflater.unconsumed_tail or not inflater.eof:
                raise bad
        value = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeError, zlib.error, RecursionError):
        raise bad from None
    if not isinstance(value, dict):
        raise bad
    return value


def _positions(value, bad) -> dict[str, int]:
    if not isinstance(value, dict):
        raise bad
    for run, seq in value.items():  # every run id is checked before it can become a file path
        if not _RUN.fullmatch(run) or isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise bad
    return value


def encode_cursor(positions: dict[str, int]) -> str:
    """A page cursor of query: one `{run: seq}` entry (the last item returned)."""
    return _pack(positions)


def decode_cursor(text: str) -> dict[str, int]:
    return _positions(_unpack(text), RecordError("That position in the record is not valid."))


_TERMINAL = ("done", "failed", "stopped")


def _run_info(events: list[dict]) -> tuple[int, str]:
    """(last seq, last time) of one run."""
    return events[-1]["seq"], events[-1]["at"]


class TailCursor:
    """Where a tail stands: the last seq sent of every run (`{run: seq}`, compressed). Nothing else, so a
    run can never be skipped quietly. When that gets too big for a cursor, the runs whose events were all
    sent (oldest last event first) are left out with a loud marker (`trimmed`); they are not repeated
    while this stream lives, and a reconnect may send them again (duplicates are chosen over losses)."""

    def __init__(self, seqs=None):
        self.seqs = dict(seqs or {})
        self.trimmed: dict[str, int] = {}

    @classmethod
    def decode(cls, text: str) -> "TailCursor":
        value = _unpack(text, compress=True)
        if set(value) != {"r"}:
            raise RecordError("That position in the record is not valid.")
        return cls(_positions(value["r"], RecordError("That position in the record is not valid.")))

    def encode(self) -> str:
        return _pack({"r": self.seqs}, compress=True)

    def is_new(self, event: dict) -> bool:
        floor = self.trimmed.get(event["run"], self.seqs.get(event["run"], 0))
        return event["seq"] > floor

    def advance(self, event: dict, info: dict) -> list[str]:
        """Record a sent event; returns the runs trimmed to make the cursor fit (none: too_large)."""
        self.seqs[event["run"]] = event["seq"]
        self.trimmed.pop(event["run"], None)
        out = []
        while True:
            try:
                self.encode()
                return out
            except RecordError:
                old = sorted(
                    (info[r][1], r)
                    for r in self.seqs
                    if r != event["run"] and r in info and info[r][0] == self.seqs[r]
                )
                if not old:
                    raise
                name = old[0][1]
                self.trimmed[name] = self.seqs.pop(name)
                out.append(name)


# --- selection ---
def _check_filters(ticket, run) -> None:
    if ticket is not None and not _TICKET.fullmatch(ticket):
        raise RecordError("That ticket is not valid.")
    if run is not None and not _RUN.fullmatch(run):
        raise RecordError("That run is not valid.")


_SKIPPED = "Some lines of this run could not be read and are not shown."
_RECOVERED = "The records of this run can be read again."
_MISSING = "There are no records for this run."
_REWOUND = "The records of this run were rewritten. Its steps are sent again from the start."
_TRIMMED = "Too many runs to follow from one position. This run may be sent again after a reconnect."


def _show_alert(alert) -> None:
    """An integrity alert reaches the person even when it could not be stored (activity.md, Integrity)."""
    if alert:
        print(json.dumps(alert, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)


class _Problem(dict):
    """One thing a person must be told about a read; `alert` is shown with it, never on its own."""

    alert = None


def _known(root: Path) -> list[str]:
    result = record.list_runs(root)
    _show_alert(result.alert)
    if result.status == "unavailable" and result.reason == "missing":
        return []  # nothing has been recorded yet
    try:
        return result.unwrap()
    except record.RecordRefused as e:
        e.alert = None  # shown above
        raise


def _fail(result) -> RecordError:
    if result.status == "unavailable" and result.reason == "missing":
        return RecordError(result.message, "not_found")
    try:
        result.unwrap()
    except record.RecordRefused as e:
        return RecordError(str(e), e.code)
    raise AssertionError("an ok result has no error")


def _problems(run: str, result) -> list[dict]:
    """What a person must be told about one read: it failed, lines were skipped, writes are pending."""
    if result.status != "ok":
        found = [_Problem(run=run, status=result.status, reason=result.reason, message=result.message)]
        found[0].alert = result.alert
        return found
    out = []
    if result.skipped:
        out.append(_Problem(run=run, status="ok", reason="skipped", message=_SKIPPED))
    if result.pending:
        out.append(_Problem(run=run, status="ok", reason="pending", message=result.message))
    return out


def _events(root: Path, runs: list[str], ticket, *, explicit: bool = False, tell: bool = True):
    """(events per run, problems). An explicit run that cannot be read is an error, never empty.
    `tell=False` leaves the alerts to the caller (a followed stream tells each one once)."""
    out, problems = {}, []
    for run in runs:
        result = record.read_run(root, run)
        if result.status != "ok":
            if explicit:
                _show_alert(result.alert)
                raise _fail(result)
            out[run] = []
        else:
            out[run] = [e for e in result.value if ticket is None or e.get("ticket") == ticket]
        found = _problems(run, result)
        if tell:
            for problem in found:
                _show_alert(problem.alert)
        problems += found
    return out, problems


def _time(text: str, what: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise RecordError(f"--{what} must be a time like 2026-11-16T09:00:00Z.") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _when(event: dict) -> datetime:
    return _time(event["at"], "at")


# --- tail ---
def tail_lines(
    root: Path,
    *,
    ticket=None,
    run=None,
    since: str | None = None,
    follow: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] | None = None,
) -> Iterator[dict]:
    _check_filters(ticket, run)
    now = now or (lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    cursor = TailCursor.decode(since) if since is not None else TailCursor()
    known = set(_known(root))
    if run is not None and run not in known:
        raise RecordError("That run does not exist.", "not_found")
    last_ping = clock()
    told: dict[str, tuple] = {}  # per run: the marks sent last (A -> B -> A is sent again)
    missing = (("unavailable", "missing"),)

    def marker(name, status, reason, message):
        return {
            "type": "unavailable",
            "cursor": cursor.encode(),
            "run": name,
            "status": status,
            "reason": reason,
            "message": message,
        }

    # Every poll re-reads the runs it follows (simple and safe; fine up to a few hundred runs).
    while True:
        sent = False
        runs = [run] if run else _known(root)
        listed = set(runs)
        for name in sorted(
            (set(told) | set(cursor.seqs)) - listed
        ):  # vanished (pruned): told once, as missing
            cursor.seqs.pop(name, None)
            cursor.trimmed.pop(name, None)
            if told.get(name) != missing:
                told[name] = missing
                yield marker(name, "unavailable", "missing", _MISSING)
                sent = True
        by_run, problems = _events(root, runs, ticket, explicit=run is not None, tell=False)
        bad = {p["run"] for p in problems if p["status"] != "ok"}
        for name, events in sorted(by_run.items()):  # a run file shorter than the cursor: resend it, loudly
            floor = cursor.trimmed.get(name, cursor.seqs.get(name, 0))
            if name not in bad and floor > (events[-1]["seq"] if events else 0):
                cursor.seqs[name] = 0
                cursor.trimmed.pop(name, None)
                yield marker(name, "ok", "rewound", _REWOUND)
                sent = True
        info = {r: _run_info(ev) for r, ev in by_run.items() if ev}
        now_marks: dict[str, list] = {r: [] for r in told if r in listed}
        for problem in problems:
            now_marks.setdefault(problem["run"], []).append(problem)
        for name, found in now_marks.items():
            marks = tuple(sorted((p["status"], p["reason"]) for p in found))
            if marks == told.get(name, ()):
                continue
            told[name] = marks
            for problem in found:
                _show_alert(problem.alert)
                yield {"type": "unavailable", "cursor": cursor.encode(), **problem}
            if not found:  # it was read again just now
                yield marker(name, "ok", "recovered", _RECOVERED)
            sent = True
        streams = [[e for e in events if cursor.is_new(e)] for _, events in sorted(by_run.items())]
        for event in heapq.merge(*streams, key=lambda e: (e["at"], e["run"])):
            for name in cursor.advance(event, info):
                yield marker(name, "ok", "trimmed", _TRIMMED)
            sent = True
            yield {"type": "event", "cursor": cursor.encode(), "event": event}
        if not follow:
            return
        if sent:
            last_ping = clock()
        elif clock() - last_ping >= PING_SECONDS:
            last_ping = clock()
            yield {"type": "ping", "cursor": cursor.encode(), "at": now()}
        sleep(POLL_SECONDS)


def _tail_cli(args, root: Path) -> None:
    if args.since is not None and args.after is not None:
        raise RecordError("Use --since or --after, not both.")
    stream = tail_lines(
        root,
        ticket=args.ticket,
        run=args.run,
        since=args.since if args.since is not None else args.after,
        follow=args.follow,
    )
    started = False
    try:
        for line in (
            stream
        ):  # a bad argument fails before the first line (plain error); later errors are stream lines
            started = True
            _emit(line)
    except (RecordError, record.RecordRefused) as e:
        _show_alert(e.alert if isinstance(e, record.RecordRefused) else None)
        code = e.code
        if not started:
            raise RecordError(str(e), code) from None
        _emit({"type": "error", "error": str(e), "code": code})
        raise SystemExit(2) from None
    except (KeyboardInterrupt, BrokenPipeError):
        return


# --- query ---
def _limit(text) -> int:
    if text is None:
        return 100
    try:
        n = int(text)
    except ValueError:
        raise RecordError("--limit must be a whole number.") from None
    if not 1 <= n <= 500:
        raise RecordError("--limit must be between 1 and 500.")
    return n


def _kinds(values, allowed: tuple[str, ...]) -> set[str] | None:
    if not values:
        return None
    bad = [k for k in values if k not in allowed]
    if bad:
        raise RecordError("That kind is not known: " + ", ".join(bad) + ".")
    return set(values)


def query(root: Path, args) -> dict:
    _check_filters(args.ticket, args.run)
    if args.detail is not None:
        return _detail(root, args)
    limit = _limit(args.limit)
    kinds = _kinds(args.kind, _KINDS)
    lo = _time(args.from_, "from") if args.from_ else None
    hi = _time(args.to, "to") if args.to else None
    after = None
    if args.after is not None:
        pos = decode_cursor(args.after)
        if len(pos) != 1:
            raise RecordError("That page position is not valid.")
        after = next(iter(pos.items()))
    by_run, problems = _events(
        root, [args.run] if args.run else _known(root), args.ticket, explicit=args.run is not None
    )
    rows = [e for events in by_run.values() for e in events]
    rows = [
        e
        for e in rows
        if (kinds is None or e["kind"] in kinds)
        and (lo is None or _when(e) >= lo)
        and (hi is None or _when(e) <= hi)
    ]
    rows.sort(key=lambda e: (_when(e), e["run"], e["seq"]), reverse=True)  # newest first
    start = 0
    if after is not None:
        index = next((i for i, e in enumerate(rows) if (e["run"], e["seq"]) == after), None)
        if index is None:
            raise RecordError("That page position is gone. Start again.", "gone")
        start = index + 1
    page = rows[start : start + limit]
    more = start + limit < len(rows)
    return {
        "items": page,
        "next": encode_cursor({page[-1]["run"]: page[-1]["seq"]}) if more else None,
        "unavailable": problems,
    }


def _detail(root: Path, args) -> dict:
    if args.run is None:
        raise RecordError("--detail needs --run.")
    if not _EVENT_ID.fullmatch(args.detail):
        raise RecordError("That detail is not valid.")
    result = record.read_run(root, args.run)
    _show_alert(result.alert)
    if result.status != "ok":
        raise _fail(result)
    pointers = [
        e for e in result.value if e["id"] == args.detail and e.get("detail")
    ]  # the line knows its detail file; the name is never rebuilt here
    unavailable = RecordError("The details of this step are not available.", "not_found")
    if not pointers:
        raise unavailable
    line = pointers[-1]
    file_id = line["detail"].rsplit("/", 1)[-1].removesuffix(".json")
    # the file must belong to the line's own ticket (I4): a line of ticket B naming A's file is refused
    detail = record.read_detail(root, args.run, file_id, ticket=line.get("ticket"))
    _show_alert(detail.alert)
    if detail.status != "ok":
        raise _fail(detail)
    # ALWAYS compared (a line with no ticket is None, never equal to a stored t_...): the file must be the one
    # this event points to, of the line's own ticket and id
    stored = (detail.value.get("ticket"), detail.value.get("id"))
    if stored != (line.get("ticket"), line["id"]) or line["id"] != args.detail:
        raise RecordError(str(record.RecordTampered("swapped")), "tampered")
    return detail.value


# --- settings (read only) ---
_MB = 1024**2


def settings(root: Path) -> dict:
    """The Insights settings in effect (config.py: share_* with the person's record, retention the lower of
    the file and the record) and how big the record is, read through the hardened helpers. A record that
    cannot be read gives the sizes as null plus the `status`/`reason`/`message` marker of the other reads."""
    from orch import config

    out = {
        "keep_days": config.record_keep_days(root),
        "max_mb": config.record_max_mb(root),
        "share_counts": config.insights_share_counts(root),
        "share_names": config.insights_share_names(root),
        "record_mb": None,
        "detail_mb": None,
        "runs": None,
    }
    for read in (sizes := record.record_sizes(root), runs := record.list_runs(root)):
        _show_alert(read.alert)
        if read.status != "ok" and not (read.status == "unavailable" and read.reason == "missing"):
            return {**out, "status": read.status, "reason": read.reason, "message": read.message}
    return {
        **out,
        "record_mb": -(-sizes.value["record"] // _MB),  # rounded up: a record that holds anything is >= 1 MB
        "detail_mb": -(-sizes.value["detail"] // _MB),
        "runs": len(runs.value or []),
    }


# --- delete-detail (a person only) ---
def delete_detail(root: Path, args) -> dict:
    """Delete the detail of one ticket: the detail files its own lines point at whose name is this ticket's
    own (I4), and its own files no line points at (orphans, found by their stored ticket/kind/id); a person's
    own decision, op `record.delete_detail`, target the ticket id, invariant H1. `deleted` = the runs that
    lost detail, `kept` = files its lines point at that are not its own name (left, reported), `unreadable` =
    runs that could not be read (skipped, never a veto; their detail stays, said plainly on stderr). Lines,
    counts and the detail of other tickets stay. Order: an agent is refused before anything else
    (needs_person); a ticket that does not exist is not_found (a deleted ticket's detail goes with retention:
    accepted); then the proof (needs_person); the detail folder itself not being safe refuses with nothing
    deleted (a run's folder or file that is not safe only makes that run unreadable);
    the audit line is written BEFORE anything is deleted (it cannot be written: not_available, nothing
    deleted)."""
    from orch import humanproof, tickets

    agent = tickets.agent_tool() or (getattr(args, "by", None) or "").startswith("agent:")
    if agent:
        raise RecordError("Only a person can delete the details of a ticket.", "needs_person")
    try:
        tid = tickets.resolve(root, args.ticket)
    except Refused:
        tid = None
    if not isinstance(tid, str) or not _TICKET.fullmatch(tid) or not tickets.ticket_path(root, tid).is_file():
        raise RecordError("That ticket does not exist.", "not_found")
    try:
        who = humanproof.person_by(
            root,
            args,
            "record.delete_detail",
            tid,
            no_handoff=humanproof.HANDOFF,
            parts={"title": _ticket_title(root, tid)},
        )
    except Refused as e:
        raise RecordError(str(e), "needs_person") from None
    if not who.startswith("human:"):
        raise RecordError("Only a person can delete the details of a ticket.", "needs_person")
    mine: dict[tuple[str, str], None] = {}
    pointed: dict[tuple[str, str], None] = {}
    unreadable: dict[str, None] = {}
    for run in _known(root):
        result = record.read_run(root, run, seen_by="cli")
        _show_alert(result.alert)
        if result.status == "unavailable" and result.reason == "missing":
            continue  # pruned since it was listed: nothing of it to delete
        if result.status != "ok":
            unreadable.setdefault(run)  # skipped and reported (no veto): its detail is not deleted
            continue
        for e in result.value:
            ref = _detail_ref(run, e.get("detail"))
            if ref is None or e.get("ticket") != tid:
                continue  # lines of other tickets never veto: by I4 their files have other names
            pointed.setdefault(ref)
            if ref[1] == record.detail_name(run, e["kind"], e["id"], tid):
                mine.setdefault(ref)
    # Exactly the files this ticket's own lines point at AND whose name is this ticket's own (I4). A line of
    # this ticket naming any other file (planted or changed) is not followed: it stays, counted in `kept`.
    kept = sum(1 for ref in pointed if ref not in mine)
    found = record.detail_files(root, list(mine))
    _show_alert(found.alert)
    if found.status != "ok":
        raise _fail(found)  # only the detail folder itself not being safe refuses
    pointed_files, unsafe_runs = found.value
    for run in unsafe_runs:
        unreadable.setdefault(run)  # a planted link or special file in one run: skipped, never a veto
    # This ticket's own files no line points at (orphans: the detail is written before its line): found by
    # their stored ticket, id and kind, which must give the file's own name (I4).
    orphans = record.ticket_detail_files(root, tid, skip=tuple(unreadable))
    _show_alert(orphans.alert)
    if orphans.status != "ok":
        raise _fail(orphans)
    own_files, unreadable_folders = orphans.value
    for run in unreadable_folders:
        unreadable.setdefault(run)
    items = list(dict.fromkeys(ref for ref in [*pointed_files, *own_files] if ref[0] not in unreadable))
    deleted = len({run for run, _ in items})
    try:
        record.note_change(root, change="record.delete_detail", by=who, ticket=tid, deleted=deleted)
    except (OSError, record.RecordInvalid):
        raise RecordError(DELETE_NOT_SAVED, "not_available") from None
    try:
        record.delete_detail_files(root, items)
    except (OSError, record.RecordInvalid, record.RecordBusy):
        # The audit line above names what was going to go; what is left can be deleted with a new proof.
        raise RecordError(DELETE_PARTLY, "not_available") from None
    if unreadable:
        print(delete_unreadable_text(len(unreadable)), file=sys.stderr)
    return {"deleted": deleted, "ticket": tid, "kept": kept, "unreadable": len(unreadable)}


def prune(root: Path, fold, now: str | None = None) -> dict:
    """Apply retention (record.apply_retention) with the EFFECTIVE values: config.record_keep_days /
    record_max_mb, the lower of the file and the person's record, never a file value alone. A lowered value
    deletes nothing when it is set; it takes effect here, at the next pruning."""
    from orch import config

    when = now or _today().strftime("%Y-%m-%dT%H:%M:%SZ")
    return record.apply_retention(root, when, config.record_keep_days(root), config.record_max_mb(root), fold)


DELETE_NOT_SAVED = "The deletion could not be noted in the record, so nothing was deleted. Try again later."
DELETE_PARTLY = "Some details could not be deleted. Try again later."


def delete_unreadable_text(n: int) -> str:
    """The plain words for `unreadable` (a page shows the same sentence)."""
    if n == 1:
        return "1 run could not be read; its detail was not deleted."
    return f"{n} runs could not be read; their detail was not deleted."


_DETAIL_REF = re.compile(r"^detail/(r_[a-z0-9_]{6,32})/([0-9a-f]{32})\.json$")


def _detail_ref(run: str, value) -> tuple[str, str] | None:
    """(run, detail id) of an event's `detail` path when it is one orch writes for this run, else None."""
    m = _DETAIL_REF.fullmatch(value) if isinstance(value, str) else None
    return (run, m[2]) if m and m[1] == run else None


# --- counts ---
def _today() -> datetime:
    return datetime.now(UTC)


def _window(args) -> tuple[str, str]:
    if args.days is not None and (args.from_ or args.to):
        raise RecordError("Use --days, or --from with --to.")
    if bool(args.from_) != bool(args.to):
        raise RecordError("Use --days, or --from with --to.")
    if args.from_:
        for text, name in ((args.from_, "from"), (args.to, "to")):
            if not _DAY.fullmatch(text):
                raise RecordError(f"--{name} must be a day like 2026-11-16.")
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                raise RecordError(f"--{name} must be a day like 2026-11-16.") from None
        if args.from_ > args.to:
            raise RecordError("--from must not be after --to.")
        return args.from_, args.to
    try:
        days = int(args.days) if args.days is not None else 30
    except ValueError:
        raise RecordError("--days must be a whole number.") from None
    if not 1 <= days <= 3650:
        raise RecordError("--days must be between 1 and 3650.")
    end = _today()
    return (end - timedelta(days=days - 1)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def run_model(run: str, events: list[dict]) -> dict:
    """One run as counts.md sees it: ticket, day started, what its agent tool can report, uses."""
    uses: dict[tuple, dict] = {}
    sees = None
    partial = False
    for e in events:
        if e["kind"] == "run.state" and (e.get("data") or {}).get("state") == "starting":
            value = (e.get("data") or {}).get("sees")
            if isinstance(value, list):
                sees = [k for k in value if k in _USED_KINDS]
        partial = partial or e.get("coverage") == "partial"
        used = e.get("used")
        if not used or e["kind"] not in ("step", "denial", "key.use", "helper.start"):
            continue
        key = (e["kind"], e["id"])
        finished = e.get("outcome") is not None
        if key in uses and uses[key]["finished"] and not finished:
            continue
        uses[key] = {"event": e, "finished": finished}
    items = []
    for u in uses.values():
        e = u["event"]
        outcome = e.get("outcome") or {}
        if e["kind"] == "denial" or (e["kind"] == "key.use" and (e.get("data") or {}).get("refused")):
            result = "refused"
        elif outcome.get("ok") is True:
            result = "ok"
        elif outcome.get("ok") is False:
            result = "failed"
        else:
            result = "unknown"
        items.append({**e["used"], "result": result, "at": e["at"]})
    if sees is None:  # no capability list was written: only what the run actually used is known to be seen
        sees = sorted({i["kind"] for i in items})
    first = events[0]["at"] if events else None
    return {
        "run": run,
        "ticket": events[0].get("ticket") if events else None,
        "day": first[:10] if first else None,
        "sees": sees,
        "partial": partial,
        "uses": items,
    }


def count_items(runs: list[dict], inventory: list[dict] = ()) -> list[dict]:
    """The reference counting of counts.md (validate.py cnt_items) plus first/last seen and versions."""

    def zero() -> dict:
        return {
            "uses": 0,
            "ok": 0,
            "failed": 0,
            "refused": 0,
            "unknown": 0,
            "runs": set(),
            "ver": {},
            "at": [],
        }

    items: dict[tuple, dict] = {}
    for inv in inventory:
        items.setdefault((inv["kind"], inv["name"], inv["source"], inv.get("action")), zero())
    for r in runs:
        for u in r["uses"]:
            it = items.setdefault((u["kind"], u["name"], u["source"], u.get("action")), zero())
            it["uses"] += 1
            it["runs"].add(r["run"])
            it[u["result"]] += 1
            it["at"].append(u["at"])
            if u.get("version"):
                v = it["ver"].setdefault(
                    u["version"], {"uses": 0, "ok": 0, "failed": 0, "first_seen": u["at"]}
                )
                v["uses"] += 1
                v["ok"] += u["result"] == "ok"
                v["failed"] += u["result"] == "failed"
                v["first_seen"] = min(v["first_seen"], u["at"])
    out = []
    for (kind, name, source, action), it in sorted(
        items.items(), key=lambda kv: tuple(x or "" for x in kv[0])
    ):
        of = sum(1 for r in runs if kind in r["sees"])
        used = len(it["runs"])
        seen = "yes" if it["uses"] else ("not_seen" if of else "unknown")
        out.append(
            {
                "kind": kind,
                "name": name,
                "source": source,
                "action": action,
                "runs": {"used": used, "of": max(of, used), "unseen": len(runs) - max(of, used)},
                "uses": it["uses"],
                "ok": it["ok"],
                "failed": it["failed"],
                "refused": it["refused"],
                "unknown": it["unknown"],
                "seen": seen,
                "first_seen": min(it["at"]) if it["at"] else None,
                "last_seen": max(it["at"]) if it["at"] else None,
                "versions": [
                    {"version": ver, **v}
                    for ver, v in sorted(it["ver"].items(), key=lambda kv: kv[1]["first_seen"])
                ][:20],
            }
        )
    return out


def _since(root: Path, models: list[dict]) -> tuple[str | None, list[dict]]:
    meta = record.read_meta(root)
    _show_alert(meta.alert)
    if meta.status == "ok":
        value = (meta.value or {}).get("since")
        if isinstance(value, str):
            return value, []
    firsts = [m["first"] for m in models if m.get("first")]
    problem = [] if meta.status == "ok" or meta.reason == "missing" else _problems(None, meta)
    return (min(firsts) if firsts else None), problem


def counts(root: Path, args) -> dict:
    from orch import config

    _check_filters(args.ticket, None)
    kinds = _kinds(args.kind, _USED_KINDS)
    day_from, day_to = _window(args)
    models = []
    by_run, unavailable = _events(root, _known(root), args.ticket)
    for run, events in by_run.items():
        if not events:
            continue
        model = run_model(run, events)
        model["first"] = events[0]["at"]
        models.append(model)
    since, meta_problem = _since(root, models)
    unavailable += meta_problem
    runs = [m for m in models if day_from <= m["day"] <= day_to]
    if kinds is not None:
        for m in runs:
            m["sees"] = [k for k in m["sees"] if k in kinds]
            m["uses"] = [u for u in m["uses"] if u["kind"] in kinds]
    stamp = _today().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": "orch.counts/1",
        "generated_at": stamp,
        "since": since,
        "from": day_from,
        "to": day_to,
        "runs": len(runs),
        "tickets": len({m["ticket"] for m in runs}),
        "coverage": {"full": sum(not m["partial"] for m in runs), "partial": sum(m["partial"] for m in runs)},
        "items": count_items(runs),
        "inventory": {
            "schema": "orch.inventory/1",
            "generated_at": stamp,
            "skills": [],
            "connections": [],
            "keys": [],
        },
        "sharing": {
            "counts": config.share_counts_state(root),
            "names": config.insights_share_names(root),  # the EFFECTIVE share_names (file AND the record)
            "last_sent": None,
            "queued": 0,
        },
        "unavailable": unavailable,
        "complete": not unavailable,
    }
