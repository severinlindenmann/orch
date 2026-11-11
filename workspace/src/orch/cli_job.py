"""`orch job …` (contracts/job-events.md): a long job reports what it does; `list` and `show` read it back.

Writing needs a live run (ORCH_RUN + ORCH_TICKET, proven like the record hook) and goes through jobs.ingest;
reading needs nothing and never hides a problem (unavailable / tampered are explicit). `orch job run` (the
generic wrapper) is not built yet.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

from orch import jobs, record
from orch.errors import Refused

WRITE = ("start", "step", "progress", "artifact", "metric", "table", "link", "log", "end")
ALIASES = {"done": "end", "fail": "end", "result": "table"}  # done / fail = end ok / failed; result = a table
READ = ("list", "show")
SUBCOMMANDS = (*WRITE, *ALIASES, *READ, "run")


def _number(text):
    try:
        value = float(text)
    except ValueError:
        raise Refused(f"`{text}` is not a number.") from None
    if not math.isfinite(value):
        raise Refused(f"`{text}` is not a number.")
    return int(value) if value.is_integer() and abs(value) < 2**53 else value


def add_parsers(sub, common) -> None:
    r = sub.add_parser("job", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")

    def add(name):
        p = r.add_parser(name, parents=[common], help=argparse.SUPPRESS)
        p.add_argument("--job")
        return p

    p = add("start")
    p.add_argument("--title")
    p.add_argument("--ticket")
    p.add_argument("--quiet-minutes", type=int)
    p = add("step")
    p.add_argument("name")
    p.add_argument("--label")
    p.add_argument("--state", default="running")
    p = add("progress")
    p.add_argument("--done", required=True)
    p.add_argument("--total")
    p.add_argument("--unit")
    p.add_argument("--text")
    p = add("artifact")
    p.add_argument("path")
    p.add_argument("--label")
    p = add("metric")
    p.add_argument("name")
    p.add_argument("value")
    p.add_argument("--unit")
    for name in ("table", "result"):
        add(name).add_argument("--table", help="a blocks table as JSON, or - to read it from stdin")
    p = add("link")
    p.add_argument("url")
    p.add_argument("--label")
    p = add("log")
    p.add_argument("text")
    p.add_argument("--err", action="store_true")
    p = add("end")
    p.add_argument("--status")
    p.add_argument("--summary")
    p.add_argument("--exit", dest="exit_code")
    for name in ("done", "fail"):
        p = add(name)
        p.add_argument("--summary")
        p.add_argument("--exit", dest="exit_code")
    r.add_parser("run", parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")
    p = r.add_parser("list", parents=[common], help=argparse.SUPPRESS)
    p.add_argument("--run")
    p.add_argument("--ticket")
    p = r.add_parser("show", parents=[common], help=argparse.SUPPRESS)
    p.add_argument("job_id", nargs="?")
    p.add_argument("--job")


def _table(args) -> dict:
    text = args.table
    if text == "-":
        text = sys.stdin.read(jobs.INPUT_BYTES + 1)
    if not text:
        raise Refused("Give the table with --table '<json>' (or - for stdin).")
    try:
        table = json.loads(text)
    except (ValueError, RecursionError):
        raise Refused("The table is not valid JSON.") from None
    return {"type": "table", "table": table}


def _input(args) -> dict:
    sub = args.sub
    if sub == "start":
        if not args.title:
            raise Refused('Give the job a title: --title "<title>".')
        env_ticket = os.environ.get("ORCH_TICKET")
        if args.ticket and env_ticket and args.ticket != env_ticket:
            raise jobs.JobError("other_run")
        out = {"type": "start", "title": args.title}
        if args.quiet_minutes is not None:
            out["quiet_minutes"] = args.quiet_minutes
        return out
    if sub == "step":
        return {"type": "step", "step": args.name, "label": args.label or args.name, "state": args.state}
    if sub == "progress":
        out = {"type": "progress", "done": _number(args.done)}
        if args.total is not None:
            out["total"] = _number(args.total)
        out.update({k: v for k, v in (("unit", args.unit), ("text", args.text)) if v is not None})
        return out
    if sub == "artifact":
        return {"type": "artifact", "path": args.path, **({"label": args.label} if args.label else {})}
    if sub == "metric":
        return {
            "type": "metric",
            "name": args.name,
            "value": _number(args.value),
            **({"unit": args.unit} if args.unit else {}),
        }
    if sub in ("table", "result"):
        return _table(args)
    if sub == "link":
        return {"type": "link", "url": args.url, "label": args.label or args.url}
    if sub == "log":
        return {"type": "log", "text": args.text, "stream": "err" if args.err else "out"}
    status = {"done": "ok", "fail": "failed"}.get(sub) or args.status
    if status is None:
        raise Refused("Say how it ended: --status ok|failed|cancelled.")
    out = {"type": "end", "status": status}
    if args.summary:
        out["summary"] = args.summary
    if args.exit_code is not None:
        out["exit"] = _number(args.exit_code)
    return out


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def dispatch(args, root: Path) -> bool:
    if args.cmd != "job":
        return False
    sub = args.sub
    if not sub:
        raise Refused("`orch job` needs a subcommand. Subcommands: " + ", ".join(SUBCOMMANDS) + ".")
    if sub == "run":
        raise Refused("`orch job run` is not built yet.")
    try:
        if sub in READ:
            if not args.json:
                raise jobs.JobError("invalid", "use --json.")
            if sub == "list":
                _emit(jobs.list_jobs(root, run=args.run, ticket=args.ticket))
            else:
                job_id = args.job_id or args.job or os.environ.get("ORCH_JOB")
                if not job_id:
                    raise jobs.JobError("no_job")
                _emit(jobs.show_job(root, job_id))
            return True
        stored = jobs.ingest(root, _input(args), job=args.job)
    except record.RecordRefused as e:
        raise jobs.JobError(e.code, str(e)) from None
    if args.json:
        _emit({"job": stored["job"]} if sub == "start" else stored)
    elif sub == "start":
        print(stored["job"])
    return True
