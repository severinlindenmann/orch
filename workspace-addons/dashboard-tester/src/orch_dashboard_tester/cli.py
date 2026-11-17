"""orch dashboard-tester setup|run|status: the daily look at every dashboard page (daily.py)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import daily
from .daily import Refused

SCRIPT = "dashboard-tester"
NOTE = (
    "The dashboard tester opens every dashboard page once a day, reads it and reports what is broken. "
    "It never clicks anything."
)


def _root(start: str) -> Path:
    p = Path(start).absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=1) if args.json else text)


def cmd_run(args, root: Path) -> int:
    ticket = args.ticket or os.environ.get("ORCH_TICKET") or None
    sp = daily.space(root)
    state_path = sp / "state.json"
    state = daily.load(state_path)
    if args.dry_run:
        sp.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="dry-", dir=str(sp)))
    else:
        out = sp / "next"
        shutil.rmtree(out, ignore_errors=True)  # a pass that broke half way left it
        out.mkdir(parents=True)
    world = daily.World(root, out, dry=args.dry_run)
    s = daily.run_pass(world, state, ticket, helper_each_release=args.helper_each_release)
    text = daily.note_text(s)
    if args.dry_run:
        shutil.rmtree(out, ignore_errors=True)
        _out(
            args, {"summary": s, "would_send": world.sent}, text + "\n(dry run: nothing was reported or kept)"
        )
        return 0
    last = sp / "last"
    if any(out.iterdir()):  # keep only the newest pictures and page texts
        shutil.rmtree(last, ignore_errors=True)
        out.rename(last)
    else:
        shutil.rmtree(out, ignore_errors=True)
    daily.save(state_path, state)
    daily.save(sp / "last.json", {"summary": s, "findings": state.get("findings", {})})
    world.note(ticket, text)
    _out(args, {"summary": s}, text)
    return 0


def _repeat_text(at: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise Refused(f"'{at}' is not a time like 06:30.")
    return f"daily {at}"


def cmd_setup(args, root: Path) -> int:
    from . import browser

    when = _repeat_text(args.at)
    steps: list[str] = []
    if not args.no_browser and not browser.browser_ready():
        print("Downloading the browser for the daily look (about 100 MB, once)...", file=sys.stderr)
        r = subprocess.run(
            [sys.executable, "-P", "-m", "playwright", "install", "--only-shell", "chromium"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0 or not browser.browser_ready():
            raise Refused("The browser download did not work: " + (r.stdout + r.stderr).strip()[-300:])
        steps.append("Browser downloaded.")
    ticket = args.ticket
    if not ticket:
        data = daily.as_json(
            daily.orch(
                root,
                [
                    "ticket",
                    "new",
                    "Daily dashboard look",
                    "--note",
                    NOTE,
                    "--json",
                ],
            )
        )
        ticket = data.get("id") if isinstance(data, dict) else None
        if not ticket:
            raise Refused("Could not make the ticket for the daily look.")
        steps.append(f"Ticket {data.get('key') or ticket} made for the daily look.")
    command = [daily.orch_bin(), "dashboard-tester", "run"]
    if args.helper_each_release:
        command.append("--helper-each-release")
    added = daily.as_json(daily.orch(root, ["automation", "script", "add", SCRIPT, "--json", "--", *command]))
    if not isinstance(added, dict):
        raise Refused("Could not add the daily look to automation. Is the automation add-on on?")
    rep = daily.orch(root, ["automation", "repeat", ticket, when, "--script", SCRIPT, "--json"])
    if rep.returncode != 0:
        raise Refused("Could not set the repeat: " + (rep.stdout + rep.stderr).strip()[-200:])
    steps.append(f"It runs {when.replace('daily', 'every day at')}.")
    if not added.get("allowed"):
        steps.append(
            "It runs only after a person presses Allow this script on the repeat (Automation in the dashboard)."
        )
    _out(args, {"ticket": ticket, "repeat": when, "allowed": bool(added.get("allowed")), "steps": steps},
         "\n".join(steps))  # fmt: skip
    return 0


def cmd_status(args, root: Path) -> int:
    sp = daily.space(root)
    last = daily.load(sp / "last.json")
    s = last.get("summary") or {}
    found = last.get("findings") or {}
    counts: dict[str, int] = {}
    for f in found.values():
        counts[f.get("status", "?")] = counts.get(f.get("status", "?"), 0) + 1
    if not s:
        _out(
            args,
            {"last_pass": None, "findings": counts},
            "No daily look yet. Set it up: orch dashboard-tester setup",
        )
        return 0
    text = daily.note_text(s)
    if counts:
        text += "\nKnown findings: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    _out(args, {"last_pass": s.get("at"), "summary": s, "findings": counts}, text)
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--by", help="actor (accepted for orch's sake)")
    ap = argparse.ArgumentParser(
        prog="orch dashboard-tester", description="A daily look at every dashboard page."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", parents=[common], help="download the browser and set up the daily repeat")
    s.add_argument("--at", default="06:30", help="time of day, HH:MM (this computer's time zone)")
    s.add_argument("--ticket", help="the ticket that holds the repeat (default: a new one)")
    s.add_argument("--helper-each-release", action="store_true", help="one helper look per new orch release")
    s.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    r = sub.add_parser("run", parents=[common], help="one look now (the repeat runs this)")
    r.add_argument("--ticket", help="where the result line goes (default: the repeat's ticket)")
    r.add_argument("--dry-run", action="store_true", help="look, but report and keep nothing")
    r.add_argument("--helper-each-release", action="store_true", help="one helper look per new orch release")
    sub.add_parser("status", parents=[common], help="what the last look found")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = _root(os.environ.get("ORCH_ROOT") or os.getcwd())
        return {"setup": cmd_setup, "run": cmd_run, "status": cmd_status}[args.cmd](args, root)
    except Refused as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Refused: {e}", file=sys.stderr)
        return 2
