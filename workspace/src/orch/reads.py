"""The JSON answers of a few read-only commands, made inside the caller's own process (ORCH-102).

The dashboard builds its state from `orch ticket list --all --json`, `orch run status <ids> --json` and
`orch review list [--answered] --json`, and answers a click with `orch ticket show <id> --json`. Each was a
new Python process; with helpers running and the machine busy one build took seconds and a click waited for
it. The dashboard server runs in the core's own interpreter, so it asks here instead. The answer is the same
JSON the command prints (the CLI calls the same functions); argv this module does not know raises NotHere and
the caller starts the command as before."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from orch import history, review, ticketindex, tickets
from orch.errors import Refused

_EXT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")  # an add-on name as `ticket list --ext` is asked here


class NotHere(LookupError):
    """This argv is not answered in-process: run the command."""


def ticket_rows(
    root: Path, status: str | None = None, all_: bool = False, ext: str | None = None
) -> list[dict]:
    """`orch ticket list` rows, before the JSON shaping: the visible tickets, sorted by status, with children
    counts and the quiet mark. `ext`: only tickets with that add-on's data, without children counts (those
    need every ticket; ORCH-603)."""
    from orch.cli import visible

    if ext is not None:  # an add-on's own tickets, read once, without children counts (ORCH-603)
        ts = [
            visible(root, t)
            for t in tickets.list_all(root, ext=ext)
            if (t["status"] == status if status else all_ or t["status"] not in ("done", "dropped"))
        ]
        for t in ts:
            if quiet := tickets.quiet_since(t):
                t["quiet_since"] = quiet
        ts.sort(key=lambda t: tuple(tickets.STATUS_WORDS).index(t["status"]))
        return ts
    everything = ticketindex.rows(root)  # which tickets and their children: the index, not every file
    kids = ticketindex.children_counts(everything)
    ts = []
    for r in _picked(everything, status, all_):
        try:
            t = tickets.load(root, r["id"])  # only the listed tickets are read in full
        except (Refused, OSError):
            continue  # changed into something unlistable meanwhile: a listing never stalls on a bad file
        if tickets.is_hidden(t) or not _picked([t], status, all_):
            continue  # hidden, or its status changed since the index row: filter on the file itself
        t = visible(root, t)
        t["children"] = dict(kids.get(t["id"]) or ticketindex.no_children())
        if quiet := tickets.quiet_since(t):
            t["quiet_since"] = quiet
        ts.append(t)
    ts.sort(key=lambda t: tuple(tickets.STATUS_WORDS).index(t["status"]))
    return ts


def _picked(everything: list[dict], status: str | None, all_: bool) -> list[dict]:
    return [
        r
        for r in everything
        if r.get("status") in tickets.STATUS_WORDS
        and (r["status"] == status if status else all_ or r["status"] not in ("done", "dropped"))
    ]


def index_list(root: Path, status: str | None = None, all_: bool = False) -> tuple[list[dict], list[dict]]:
    """(the listed rows, every row) for the text `orch ticket list`: index rows only, no ticket file read.
    Each listed row gets children and quiet_since like ticket_rows."""
    everything = ticketindex.rows(root)
    kids = ticketindex.children_counts(everything)
    ts = _picked(everything, status, all_)
    ts.sort(key=lambda r: tuple(tickets.STATUS_WORDS).index(r["status"]))
    for r in ts:
        r["children"] = dict(kids.get(r["id"]) or ticketindex.no_children())
        stamps = {"status": r["status"], "updated_at": r.get("updated_at"), "created_at": r.get("created_at")}
        if r.get("last_at"):
            stamps["history"] = [{"at": r["last_at"]}]
        if quiet := tickets.quiet_since(stamps):
            r["quiet_since"] = quiet
    return ts, everything


def run_status(root: Path, ids: list[str]) -> dict:
    """`orch run status <id> <id> ... --json` for several tickets: {"runs": {id: answer}}; a ticket that
    cannot be read gets {"ticket", "error"} and does not spoil the others."""
    from orch.cli_run import status_of

    out: dict[str, dict] = {}
    for tid in dict.fromkeys(ids):
        try:
            out[tid] = status_of(root, tid)[0]
        except Refused as e:
            out[tid] = {"ticket": tid, "error": str(e)}
    return {"runs": out}


def review_cards(root: Path) -> dict:
    return {"workspace": root.name, "cards": review.stack(root)}


def review_answered(root: Path) -> list[dict]:
    from orch.cli_review import _answered

    return _answered(root)


def _record_args(argv: list[str]):
    """argv (`record query ...`, without --json) parsed by the command's own parser, or NotHere."""
    from orch import cli_record

    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--by")
    cli_record.add_parsers(parser.add_subparsers(dest="cmd"), common)
    try:
        args, rest = parser.parse_known_args(argv)
    except (argparse.ArgumentError, SystemExit, ValueError):
        raise NotHere(" ".join(argv)) from None
    if rest or args.cmd != "record" or args.sub != "query" or args.detail is not None:
        raise NotHere(" ".join(argv))
    return args


def record_query(root: Path, argv: list[str]) -> dict:
    """`orch record query --ticket <id> ... --json` with the long-running reader's memory of run files
    (record.read_run_for): only run files that changed are parsed again. Without --ticket it is not answered
    here (a whole-record query is rare and would keep every line in memory)."""
    from orch import cli_record

    args = _record_args(argv)
    if not args.ticket:
        raise NotHere(" ".join(argv))
    return cli_record.query(root, args, cached=True)


def _plain(root: Path, data):
    """As the command prints it with --json: tickets shown as provable here, then through JSON (a copy that
    shares nothing with the core's own objects)."""
    return json.loads(json.dumps(history.shown_json(root, data), ensure_ascii=False))


_LISTS = (["ticket", "list"], ["review", "list"], ["chat", "list"], ["needs"])


def answer(root: Path, argv: list[str]):
    """The parsed JSON `orch <argv>` would print. Refused when the command would refuse (exit 2), NotHere when
    this argv is not one of the reads above. A list is one read-only pass, so it looks at the ticket files
    once (ORCH-2289: the rows and their shown fields each stat'ed every ticket file)."""
    if list(argv[:2]) in _LISTS or list(argv[:1]) in _LISTS:
        with ticketindex.reuse():
            return _answer(root, argv)
    return _answer(root, argv)


def _answer(root: Path, argv: list[str]):
    a = list(argv)
    if not a or a[-1] != "--json":
        raise NotHere(" ".join(a))
    a = a[:-1]
    if a == ["ticket", "list", "--all"]:
        return _plain(root, ticket_rows(root, all_=True))
    if a == ["ticket", "list"]:
        return _plain(root, ticket_rows(root))
    if (
        a[:2] == ["ticket", "list"]
        and a[-2:-1] == ["--ext"]
        and a[2:-2] in ([], ["--all"])
        and _EXT_NAME.fullmatch(a[-1])
    ):  # an add-on's own tickets (Factory's page and watcher): at 10,000 tickets about 800, several MB
        # through the read worker's pipe and parsed twice took about a second (ORCH-2288)
        return _plain(root, ticket_rows(root, all_=a[2:-2] == ["--all"], ext=a[-1]))
    if a[:2] == ["ticket", "show"] and len(a) == 3 and tickets._ID_RE.fullmatch(a[2]):
        from orch.cli import visible

        return _plain(root, visible(root, tickets.load(root, a[2])))
    if a[:2] == ["run", "status"] and len(a) > 2 and all(tickets._ID_RE.fullmatch(x) for x in a[2:]):
        ids = a[2:]
        if len(ids) == 1:  # the one-ticket answer is the ticket's own row
            from orch.cli_run import status_of

            return _plain(root, status_of(root, ids[0])[0])
        return _plain(root, run_status(root, ids))
    if (
        a[:2] == ["run", "screen"]
        and len(a) > 5
        and a[-2] == "--lines"
        and a[-1].isdigit()
        and all(tickets._ID_RE.fullmatch(x) for x in a[2:-2])
    ):  # several sessions' last lines (one tmux call); one ticket keeps the command's own answer
        from orch import runwatch

        return {"screens": runwatch.tails(root, a[2:-2], int(a[-1]))}
    if a[:2] == ["record", "query"]:
        return record_query(root, a)
    if a == ["needs"]:
        from orch import needs

        return json.loads(json.dumps(needs.needs(root), ensure_ascii=False))
    if a[:2] == ["chat", "list"] and (len(a) == 2 or (len(a) == 4 and a[2] == "--reader")):
        from orch import ticketchats

        return _plain(root, ticketchats.chats(root, a[3] if len(a) == 4 else None))
    if a in (["addon", "list"], ["addon", "list", "--catalog"]):
        from orch import addons

        return _plain(root, addons.listing(root, catalog="--catalog" in a))
    if a == ["chat", "id"]:  # asked every Automation round (ORCH-1295)
        from orch import chat

        return _plain(root, chat.chat_id(root))
    if a == ["review", "list"]:
        return _plain(root, review_cards(root))
    if a == ["review", "list", "--answered"]:
        return _plain(root, review_answered(root))
    raise NotHere(" ".join(argv))


def same_orch(orch_bin: str | None) -> bool:
    """True when `orch_bin` is this very orch: `orch:self` (pagesession.SELF), or the `orch` console script of
    the Python this process runs (its first line names this interpreter). Anything else (a test's fake orch,
    another install) keeps its own process for every read."""
    if orch_bin == "orch:self":
        return True
    if not orch_bin or os.name == "nt":
        return False
    try:
        with open(orch_bin, "rb") as f:
            head = f.read(512)
    except OSError:
        return False
    first = head.split(b"\n", 1)[0]
    if not first.startswith(b"#!") or b"orch_entry" not in head:
        return False
    interp = first[2:].strip().decode("utf-8", "replace")
    return os.path.abspath(interp) == os.path.abspath(sys.executable)


READS = {"here": 0, "worker": 0}  # per process: reads answered in this process, and by the read worker


def call(root: Path, argv: list[str], *, timeout: float = 10.0, environ=None) -> tuple[int, object] | None:
    """`orch <argv>` (a read, ending in --json) for a caller in this orch's own interpreter, without a new
    process per read: (exit code, the parsed JSON it prints), answered here (answer) or by the caller's read
    worker (orch.readworker). None: neither could answer, the caller starts the command as before. Exit 2
    comes with the command's own `{"error", ...}` object."""
    try:
        value = answer(root, argv)
        READS["here"] += 1
        return 0, value
    except NotHere:
        pass
    except Refused as e:
        READS["here"] += 1
        return 2, {"error": str(e), **getattr(e, "extra", {})}
    except Exception:  # noqa: BLE001 - anything unexpected: the worker (the command itself) gets its chance
        pass
    from orch import readworker

    got = readworker.run(root, argv, timeout=timeout, environ=environ)
    if got is None:
        return None
    code, out = got
    try:
        value = json.loads(out)
    except ValueError:
        value = None
    READS["worker"] += 1
    return code, value
