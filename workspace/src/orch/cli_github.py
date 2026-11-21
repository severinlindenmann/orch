"""`orch github`: the GitHub add-on's hourly write limit for helpers and scripts (no AI call).

    orch github wait <merge|pr|comment|other> [--for "<repo#n>"] [--max-wait <minutes>]
        waits until one write of that kind fits this computer's limit and counts it (a merge with --for only
        waits for room: `orch ref wait --merge` counts it when it really merges); exit 0 = write now,
        exit 2 = no room in time (do not write)
    orch github writes      the writes of the last hour per kind, the limit and when the next one fits
    orch github retries [--days N]
        checks orch ran once more after a timeout or network error (orch ref wait), most retried first
    orch github expert [--dry-run] [--known <problem>=<ticket>]
        the Development expert's read-only pass over CI, pull requests and tickets (devexpert.py); off until
        `orch config set github.dev_expert <role ticket>` and `github.dev_expert_repo <owner/name>`
    orch github ci-waiting [--repo <owner/name>] [--wait <minutes>]
        jobs waiting for a machine on GitHub now and the day's peak (cibusy.py, ORCH-454); --wait waits until
        fewer than 20 wait (exit 2 = still busy: start no runs now). The repository defaults to
        github.dev_expert_repo
    orch github develop-green
        the last develop commit whose own checks all finished green, and how far develop is ahead (ORCH-314)
    orch github release [--dry-run] [--known-red "<job>=<ticket>"]
        one pass of the release keeper (releasekeeper.py): green develop -> release pull request -> Merge card
        -> merged by the switch or the owner's click -> orch update here -> deploy prepared, production
        only on the owner's go; off until github.release_keeper, github.release_repo and
        github.release_clone are set
    orch github release-hold "<why>" | off
        stop cutting new releases (a running one goes on) / lift it
    orch github release-deployed <server>[,<server>]=<commit>
        write down what production runs after a deploy
    orch github release-exception ["<check>" --ticket <key> --until <YYYY-MM-DD> [--why ...] | --ticket off]
        a named exception (a person's): this check may be red in a release until the date or until the
        ticket is done; shown on the Merge card and in the note. Without a check: the list
    orch github release-walk <N> <walk> pass|fail "<one line>" --commit <sha>
        a walk helper's result for release N (github.release_walks); the Merge card waits for every pass

The limits are settings: `orch config set github.merge_per_hour 12` (also pr_, comment_, other_per_hour).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import ghlimit, nextstep, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    g = sub.add_parser("github", parents=[common], help=argparse.SUPPRESS).add_subparsers(
        dest="sub", required=True
    )
    w = g.add_parser("wait", parents=[common], help="wait for room for one GitHub write, then count it")
    w.add_argument("kind", choices=ghlimit.KINDS)
    w.add_argument("--for", dest="what", default="", help="what is written (a repo#number), for the log")
    w.add_argument(
        "--max-wait",
        dest="max_wait",
        type=int,
        default=ghlimit.WAIT_SECS // 60,
        help="minutes to wait for room (default 60)",
    )
    g.add_parser("writes", parents=[common], help="GitHub writes of the last hour and the limits")
    rt = g.add_parser(
        "retries", parents=[common], help="checks orch ran once more after a timeout or network error"
    )
    rt.add_argument("--days", type=int, default=30, help="how many days back (default 30)")
    e = g.add_parser(
        "expert", parents=[common], help="the Development expert's pass over CI and pull requests"
    )
    e.add_argument("--dry-run", action="store_true", help="only say what it would do")
    e.add_argument(
        "--known",
        action="append",
        metavar="PROBLEM=TICKET",
        help="a red problem that already has its ticket, e.g. nightly-ci=ORCH-32 (no second ticket)",
    )
    r = g.add_parser("release", parents=[common], help="one pass of the release keeper")
    r.add_argument("--dry-run", action="store_true", help="only say what it would do")
    r.add_argument(
        "--known-red",
        dest="known_red",
        action="append",
        metavar="JOB=TICKET",
        help="a job that is red for a known reason while that ticket is open: named, never a blocker",
    )
    hd = g.add_parser("release-hold", parents=[common], help="stop cutting releases (off lifts it)")
    hd.add_argument("why", help='why, in a few words, or "off"')
    cw = g.add_parser(
        "ci-waiting", parents=[common], help="jobs waiting for a machine on GitHub now and the day's peak"
    )
    cw.add_argument("--repo", default="", help="owner/name (default: github.dev_expert_repo)")
    cw.add_argument("--wait", type=int, default=0, metavar="MINUTES", help="wait until fewer than 20 wait")
    g.add_parser("develop-green", parents=[common], help="the last develop commit whose checks all passed")
    dp = g.add_parser("release-deployed", parents=[common], help="write down what production runs")
    dp.add_argument("spec", metavar="SERVER=COMMIT", help="e.g. relay=58e00713 or relay,publish=<commit>")
    ex = g.add_parser(
        "release-exception", parents=[common], help="let one check be red in releases, named and dated"
    )
    ex.add_argument("check", nargs="?", help="the check as the pull request shows it; none lists them")
    ex.add_argument("--ticket", help="the ticket that fixes it (off removes the exception)")
    ex.add_argument("--until", help="the end date, YYYY-MM-DD")
    ex.add_argument("--why", help="why it may be red, in a few words")
    wk = g.add_parser("release-walk", parents=[common], help="record a release walk's result")
    wk.add_argument("n", type=int, metavar="N", help="the release number")
    wk.add_argument("walk", help="the walk's name (github.release_walks)")
    wk.add_argument("verdict", choices=("pass", "fail"))
    wk.add_argument("line", help="what was walked (pass) or the worst problem (fail), one line")
    wk.add_argument("--commit", required=True, help="the commit you walked (the walk ticket names it)")


def _release(args, root: Path | None) -> None:
    from orch import releasekeeper as rk

    if root is None:
        raise Refused("Run this inside an orch workspace.")
    if args.sub == "develop-green":
        res = rk.green_status(root)
        print(json.dumps(res) if args.json else rk.green_text(res))
    elif args.sub == "release":
        res = rk.run(root, dry_run=args.dry_run, known=rk.parse_known(args.known_red))
        nextstep.remember(args, res)
        print(json.dumps(res, indent=2, default=str) if args.json else rk.text(res, args.dry_run))
    elif args.sub == "release-exception":
        _exception(args, root, rk)
    elif args.sub == "release-walk":
        by = tickets.current_actor(getattr(args, "by", None))
        e = rk.record_walk(root, args.n, args.walk, args.verdict, args.line, by, args.commit)
        msg = (
            f"Recorded: release {args.n} {args.walk} walk {'passed' if args.verdict == 'pass' else 'FAILED'}."
        )
        print(json.dumps(e) if args.json else msg)
    elif args.sub == "release-hold":
        v = rk.set_hold(root, args.why)
        data = {"hold": v}
        msg = (
            f"No new release is cut until the hold is lifted: {v}"
            if v
            else "Hold lifted: releases are cut again."
        )
        print(json.dumps(data) if args.json else msg)
    else:
        by = getattr(args, "by", None) or "by hand"
        got = rk.record_deployed(root, args.spec, by)
        msg = f"Written down: {' and '.join(got['parts'])} runs {got['sha'][:8]} in production."
        print(json.dumps(got) if args.json else msg)


def _ci_waiting(args, root: Path | None) -> None:
    from orch import cibusy, devexpert

    name = (args.repo or "").strip() or devexpert.repo(root) or ""
    if not cibusy.REPO_RE.match(name):
        raise Refused("Name the repository: --repo owner/name (or set github.dev_expert_repo).")
    if not 0 <= args.wait <= 120:
        raise Refused("--wait is a number of minutes from 0 to 120.")
    if args.wait:
        ok, n = cibusy.wait_room(name, max_wait=args.wait * 60)
    else:
        ok, n = cibusy.room(name, fresh=True)
    peaks = cibusy.peaks(name)
    today = peaks.get(max(peaks)) if peaks else None
    data = {"repo": name, "waiting": n, "limit": cibusy.LIMIT, "room": ok, "peak_today": today}
    if n is None:
        text = f"GitHub did not say how many jobs of {name} wait for a machine (counted as room)."
    else:
        text = f"{n} jobs of {name} wait for a machine (limit {cibusy.LIMIT})" + (
            f"; the day's peak was {today['n']} at {today['at']}." if today else "."
        )
    print(json.dumps(data, indent=2) if args.json else text)
    if not ok:
        raise Refused(cibusy.busy_line(n) + ": start no runs now; try again in a few minutes.")


def _exception(args, root: Path, rk) -> None:
    if not args.check:
        rows = rk.list_exceptions(root)
        text = "\n".join(
            f"{c}: {e.get('ticket')}, until {e.get('until')}" + (f" ({e['why']})" if e.get("why") else "")
            for c, e in rows.items()
        )
        print(
            json.dumps(rows) if args.json else (text or "No exception recorded: every check must be green.")
        )
        return
    who = tickets.current_actor(getattr(args, "by", None))
    if tickets.agent_tool() or not who.startswith("human:"):
        raise Refused(
            "Only a person records a release exception. Ask the owner to run: "
            f'orch github release-exception "{args.check}" --ticket <key> --until <YYYY-MM-DD>'
        )
    e = rk.set_exception(root, args.check, args.ticket, args.until, args.why, who)
    msg = (
        f"Recorded: {args.check} may be red in releases until {e['until']} or until {e['ticket']} is done."
        if e
        else f"Removed: {args.check} must be green again in releases."
    )
    print(json.dumps({"check": args.check, "exception": e}) if args.json else msg)


def _when(secs) -> str:
    if secs is None:
        return "none this hour"
    return f"{secs // 60} min ago" if secs >= 60 else f"{secs} s ago"


def dispatch(args, root: Path | None) -> bool:
    if getattr(args, "cmd", None) != "github":
        return False
    if args.sub in (
        "release",
        "release-hold",
        "release-deployed",
        "develop-green",
        "release-exception",
        "release-walk",
    ):
        _release(args, root)
        return True
    if args.sub == "expert":
        from orch import devexpert

        res = devexpert.run(root, dry_run=args.dry_run, known=devexpert.parse_known(args.known))
        nextstep.remember(args, res)
        print(json.dumps(res, indent=2, default=str) if args.json else devexpert.text(res, args.dry_run))
        return True
    if args.sub == "ci-waiting":
        _ci_waiting(args, root)
        return True
    if args.sub == "retries":
        from orch import checkretry

        if not 1 <= args.days <= 365:
            raise Refused("--days is a number from 1 to 365.")
        data = checkretry.summary(args.days)
        text = (
            f"{data['total']} check retries in the last {args.days} days."
            + "".join(f"\n{r['check']}: {r['count']}x ({r['repo']})" for r in data["checks"][:10])
            if data["total"]
            else f"No check was run again in the last {args.days} days."
        )
        print(json.dumps(data) if args.json else text)
        return True
    if args.sub == "wait":
        if args.max_wait < 0:
            raise Refused("--max-wait is a number of minutes, 0 or more.")
        # a merge of a named pull request is counted by `orch ref wait --merge` when it merges: here only wait
        # for room, so waiting helpers and repeated runs never use up the hour
        peek = args.kind == "merge" and bool(args.what)
        secs = args.max_wait * 60
        got = (
            ghlimit.wait_room(args.kind, wait=secs) if peek else ghlimit.take(args.kind, args.what, wait=secs)
        )
        if not got:
            raise Refused(
                f"No room for one of the {ghlimit.WHAT[args.kind]} within {args.max_wait} minutes "
                "(see orch github writes). Do not write to GitHub now; try again later."
            )
        data = {"kind": args.kind, "taken": not peek}
        text = f"Room for one of the {ghlimit.WHAT[args.kind]}: " + (
            "merge it now (orch ref wait --merge counts it when it merges)." if peek else "write it now."
        )
    else:
        rows = ghlimit.status()
        data = {"writes": rows}
        text = "\n".join(
            f"{r['kind']}: {r['used']} of {r['per_hour']} this hour, last {_when(r['last_secs_ago'])}"
            + (f", next fits in {r['next_in_secs']} s" if r["next_in_secs"] > 0 else ", room now")
            for r in rows
        )
    print(json.dumps(data, indent=2) if args.json else text)
    return True
