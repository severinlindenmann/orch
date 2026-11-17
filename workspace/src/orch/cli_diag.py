"""`orch diag inspect | query | report | tickets`: what happened inside orch, read-only (contracts/diag.md).
`tickets` (report_tickets.py) is the one that writes tickets: new problem reports become tickets.

`inspect` and `query` never write anything and never repair anything: they do not call `orch run status`'s
orphan repair, they read files. `report` writes one folder under `.orch/diag/reports/` and nothing else.
Nothing here
uploads anything.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from orch import diag, diag_checks, diag_collect, diag_query, diag_report
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    d = sub.add_parser("diag", help="what happened inside orch (read-only)").add_subparsers(
        dest="sub", required=True
    )
    i = d.add_parser("inspect", parents=[common], help="the state and the health checks, now")
    i.add_argument("--ticket")
    i.add_argument("--run")
    q = d.add_parser("query", parents=[common], help="search the debug log and the activity record")
    q.add_argument("--ticket")
    q.add_argument("--run")
    q.add_argument("--ev", help="event name pattern, like 'ticket.*'")
    q.add_argument("--lvl", help="debug, info, warn or error (and above)")
    q.add_argument("--around", help="a time, HH:MM (UTC) or a full time")
    q.add_argument("--window", help="with --around: how far each side, like 2m")
    q.add_argument("--since", help="how far back, like 2h")
    q.add_argument("--limit")
    q.add_argument("--page", help="the `next` token of the last answer")
    r = d.add_parser("report", parents=[common], help="write a report folder for an agent or a person")
    r.add_argument("--ticket")
    r.add_argument("--run")
    r.add_argument("--addon")
    r.add_argument("--since")
    r.add_argument("--note")
    r.add_argument("--expected")
    r.add_argument("--more", help="further details, up to 4000 characters")
    r.add_argument(
        "--about",
        choices=["problem", "feature"],
        default="problem",
        help="a problem (default) or a feature wish",
    )
    r.add_argument("--file", action="append", default=[], help="add a picture or file (up to 10 times)")
    r.add_argument(
        "--content",
        dest="content",
        action="store_true",
        default=True,
        help="include ticket text and helper excerpts (default)",
    )
    r.add_argument("--no-content", dest="content", action="store_false")
    t = d.add_parser("tickets", parents=[common], help="turn new problem reports into tickets, once (no AI)")
    t.add_argument("--dry-run", action="store_true", help="say what would happen, change nothing")
    x = d.add_parser("delete", parents=[common], help="delete saved reports or the saved debug notes")
    x.add_argument("what", choices=["reports", "notes"])


def read_files(paths) -> list[tuple[str, bytes]]:
    """The pictures and files a person or helper names (`--file`), each checked before it is read."""
    files = []
    for raw in list(paths or [])[: diag_report.ATTACH_MAX + 1]:
        f = Path(raw).expanduser()
        if not f.is_file():
            raise Refused(f"{raw} is not a file. Check the path and try again.")
        if f.stat().st_size > diag_report.ATTACH_FILE_BYTES:  # before reading it
            raise Refused(
                f"{f.name} is bigger than {diag_report.ATTACH_FILE_BYTES // 1024 // 1024} MB. "
                "Leave it out or make it smaller."
            )
        files.append((f.name, f.read_bytes()))
    return files


def _check_id(value, what: str, rx) -> None:
    if value is not None and not rx.fullmatch(value):
        raise Refused(f"That {what} is not valid.")


def inspect(root: Path, ticket=None, run=None, now=None) -> dict:
    now = time.time() if now is None else now
    scope = {"ticket": ticket, "run": run}
    collected = diag_collect.collect_all(root, scope, now)
    events = list(diag_collect.recent_events(root, now - 86400))
    checks = diag_checks.run_all({"now": now, "collected": collected, "events": events})
    return {"at": diag_collect._iso(now), "scope": scope, "checks": checks, "state": collected}


def _text_inspect(res: dict) -> str:
    out = [f"orch diag inspect, {res['at']}"]
    for c in res["checks"]:
        out.append(f"[{c['verdict']}] {c['name']}: {c['fact']}")
        out += [f"    {e}" for e in c["evidence"]]
    gaps = [f"{n}: {g}" for n, c in res["state"].items() for g in c["gaps"]]
    out += ["", "Not collected:", *[f"  {g}" for g in gaps]] if gaps else []
    return "\n".join(out)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "diag":
        return False
    from orch import tickets

    _check_id(getattr(args, "ticket", None), "ticket", tickets._ID_RE)
    _check_id(getattr(args, "run", None), "run", __import__("re").compile(r"r_[A-Za-z0-9]{1,32}"))
    if args.sub == "inspect":
        res = inspect(root, args.ticket, args.run)
        print(json.dumps(res, indent=2, ensure_ascii=False) if args.json else _text_inspect(res))
    elif args.sub == "query":
        res = diag_query.query(
            root,
            ticket=args.ticket,
            run=args.run,
            ev=args.ev,
            lvl=args.lvl,
            around=args.around,
            span=args.window,
            since=args.since,
            limit=args.limit,
            page=args.page,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"{res['total']} event(s), {res['window']['from']} to {res['window']['to']}")
            for it in res["items"]:
                print(diag_report._one_line(it))
            if res["next"]:
                print(f"more: --page {res['next']}")
            for g in res["unavailable"]:
                print(f"not available: {g}")
    elif args.sub == "tickets":
        from orch import report_tickets

        res = report_tickets.run_pass(root, dry_run=args.dry_run)
        print(report_tickets.dumps(res) if args.json else report_tickets.text(res))
    elif args.sub == "delete":
        gone = diag_report.delete_all(root) if args.what == "reports" else diag.delete_notes(root)
        label = "report" if args.what == "reports" else "file of notes"
        text = f"Deleted {gone} {label}{'' if gone == 1 else 's'}."
        print(json.dumps({"deleted": gone, "what": args.what}) if args.json else text)
    else:
        files = read_files(args.file)
        made = diag_report.make(
            root,
            ticket=args.ticket,
            run=args.run,
            addon=args.addon,
            since=args.since,
            note=args.note,
            expected=args.expected,
            content=args.content,
            more=args.more,
            files=files,
            about=args.about,
        )
        if args.json:
            print(
                json.dumps(
                    {"ref": made["ref"], "path": made["path"], "problems": made["problems"]},
                    ensure_ascii=False,
                )
            )
        else:
            print(f"Report {made['ref']}\n{made['path']}")
            if made["problems"]:
                print("Problems found: " + ", ".join(made["problems"]))
    return True
