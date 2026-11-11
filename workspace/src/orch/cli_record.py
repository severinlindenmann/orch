"""`orch record tail | query | counts` (contracts/activity.md, counts.md): read-only views of the record.

Every view reads the record through these commands (add-ons never read the files). Nothing here writes, so no
proof is needed. `delete-detail` and `propose` are not built yet.
"""

import argparse
import base64
import binascii
import heapq
import json
import re
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import record
from orch.collect_execjson import detail_name
from orch.errors import Refused

SUBCOMMANDS = ("tail", "query", "counts", "delete-detail")
_BUILT = ("tail", "query", "counts")
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


class RecordError(Refused):
    """A refusal with a contract error code (`{"error", "code"}`, exit 2)."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
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
    c = r.add_parser("counts", parents=[common], help=argparse.SUPPRESS)
    c.add_argument("--days")
    c.add_argument("--from", dest="from_")
    c.add_argument("--to")
    c.add_argument("--ticket")
    c.add_argument("--kind", action="append")
    for name in SUBCOMMANDS:
        if name not in _BUILT:
            r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "record":
        return False
    if not args.sub:
        raise Refused("`orch record` needs a subcommand. Subcommands: " + ", ".join(SUBCOMMANDS) + ".")
    if args.sub not in _BUILT:
        raise Refused(f"`orch record {args.sub}` is not built yet.")
    if not args.json:
        raise RecordError("Use --json.")
    try:
        if args.sub == "tail":
            _tail_cli(args, root)
        elif args.sub == "query":
            _emit(query(root, args))
        else:
            _emit(counts(root, args))
    except record.RecordRefused as e:
        raise RecordError(str(e), "refused") from None
    return True


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# --- cursors ---
def encode_cursor(positions: dict[str, int]) -> str:
    raw = json.dumps(positions, separators=(",", ":"), sort_keys=True).encode()
    cursor = _PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    if len(cursor) > _MAX_CURSOR:
        raise RecordError(
            "The record is too big to follow from one position. Start again without a cursor.", "too_large"
        )
    return cursor


def decode_cursor(text: str) -> dict[str, int]:
    bad = RecordError("That position in the record is not valid.")
    if not isinstance(text, str) or not text.startswith(_PREFIX) or len(text) > _MAX_CURSOR:
        raise bad
    body = text[len(_PREFIX) :]
    if not re.fullmatch(r"[A-Za-z0-9_-]*", body):
        raise bad
    try:
        value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (binascii.Error, ValueError, UnicodeError):
        raise bad from None
    if not isinstance(value, dict):
        raise bad
    for run, seq in value.items():  # every run id is checked before it can become a file path
        if not _RUN.fullmatch(run) or isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise bad
    return value


# --- selection ---
def _check_filters(ticket, run) -> None:
    if ticket is not None and not _TICKET.fullmatch(ticket):
        raise RecordError("That ticket is not valid.")
    if run is not None and not _RUN.fullmatch(run):
        raise RecordError("That run is not valid.")


def _runs(root: Path, run, *, must_exist: bool) -> list[str]:
    known = record.list_runs(root)
    if run is None:
        return known
    if run not in known:
        if must_exist:
            raise RecordError("That run does not exist.", "not_found")
        return []
    return [run]


def _events(root: Path, runs: list[str], ticket) -> dict[str, list[dict]]:
    out = {}
    for run in runs:
        events = record.read_events(root, run)
        out[run] = [e for e in events if ticket is None or e.get("ticket") == ticket]
    return out


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
    cursor = decode_cursor(since) if since is not None else {}
    runs = _runs(root, run, must_exist=True)
    known = set(record.list_runs(root))
    if any(r not in known for r in cursor):
        yield {"type": "reset", "cursor": encode_cursor({}), "reason": "pruned"}
        cursor = {}
    last_ping = clock()
    while True:
        sent = False
        by_run = _events(root, runs if run else record.list_runs(root), ticket)
        streams = [[e for e in events if e["seq"] > cursor.get(r, 0)] for r, events in sorted(by_run.items())]
        for event in heapq.merge(*streams, key=lambda e: (e["at"], e["run"])):
            cursor[event["run"]] = event["seq"]
            sent = True
            yield {"type": "event", "cursor": encode_cursor(cursor), "event": event}
        if not follow:
            return
        if sent:
            last_ping = clock()
        elif clock() - last_ping >= PING_SECONDS:
            last_ping = clock()
            yield {"type": "ping", "cursor": encode_cursor(cursor), "at": now()}
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
        code = e.extra["code"] if isinstance(e, RecordError) else "refused"
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
    by_run = _events(root, _runs(root, args.run, must_exist=True), args.ticket)
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
    return {"items": page, "next": encode_cursor({page[-1]["run"]: page[-1]["seq"]}) if more else None}


def _detail(root: Path, args) -> dict:
    if args.run is None:
        raise RecordError("--detail needs --run.")
    if not _EVENT_ID.fullmatch(args.detail):
        raise RecordError("That detail is not valid.")
    _runs(root, args.run, must_exist=True)
    value = record.read_detail(root, args.run, detail_name(args.detail))
    if value is None:
        raise RecordError("The details of this step are not available.", "not_found")
    return value


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


def _since(root: Path, models: list[dict]) -> str | None:
    try:
        meta = json.loads((record.record_dir(root) / "meta.json").read_text())
        value = meta.get("since")
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:]{8}(\.\d+)?Z", value):
            return value
    except (OSError, ValueError, AttributeError):
        pass
    firsts = [m["first"] for m in models if m.get("first")]
    return min(firsts) if firsts else None


def counts(root: Path, args) -> dict:
    _check_filters(args.ticket, None)
    kinds = _kinds(args.kind, _USED_KINDS)
    day_from, day_to = _window(args)
    models = []
    for run, events in _events(root, record.list_runs(root), args.ticket).items():
        if not events:
            continue
        model = run_model(run, events)
        model["first"] = events[0]["at"]
        models.append(model)
    since = _since(root, models)
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
        "sharing": {"counts": "not_connected", "names": False, "last_sent": None, "queued": 0},
    }
