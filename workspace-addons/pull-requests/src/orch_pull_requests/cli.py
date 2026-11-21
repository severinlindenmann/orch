"""orch pull-requests queue add|list|remove|run, tend, failed-checks, helper-stopped, start|stop|status (contract: contracts/addons/pull-requests/README.md)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import store
from .store import FINISHED, MERGED, Refused

POLL_SECS = 15


def _root(start: str | None) -> Path:
    p = Path(start or ".").absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _actor() -> str:
    agent = os.environ.get("ORCH_AGENT")
    if agent or os.environ.get("ORCH_RUN"):
        return "agent:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", agent or "helper")[:64] or "helper")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "human:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", user)[:64] or "user")


def _ticket(root: Path, ref: str | None, url: str) -> str | None:
    """The ticket id; refused when a person merges this pull request with a Merge card on it."""
    if not ref:
        return None
    from orch import review, tickets

    from .runner import pr_key

    tid = tickets.resolve(root, ref.strip())
    t = tickets.load(root, tid)
    for q in t.get("questions") or []:
        if q.get("answer") is None and pr_key(review.merge_url(q) or "") == pr_key(url):
            raise Refused(f"A person merges {url} with the Merge card on {t.get('key') or tid}; not queued.")
    return t["id"]


# -- the runner process ------------------------------------------------------------------------------------
def _runner_lock(root: Path) -> Path:
    return store.folder(root) / "runner.lock"


def runner_alive(root: Path) -> bool:
    from orch import procs

    lock = _runner_lock(root)
    try:
        holder = (lock / "owner").read_text(encoding="utf-8")
    except OSError:
        try:  # just made, owner not written yet; an old one without owner is a runner that died at its start
            return time.time() - lock.stat().st_mtime < store.STALE_SECS
        except OSError:
            return False
    return not procs.owner_dead(holder)


def _hold_runner(root: Path) -> bool:
    lock = _runner_lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    return store.take_lock(lock, store.STALE_SECS)


def start_runner(root: Path) -> None:
    """Start `queue run` in the background unless one runs. Its output goes to runner.log."""
    if runner_alive(root):
        return
    from orch import procs

    d = store.folder(root)
    d.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-I", "-P", "-m", "orch_pull_requests", "queue", "run", "--root", str(root)]
    with open(d / "runner.log", "a", encoding="utf-8") as log:
        # background_popen_kwargs sets stdin and the own session (or the hidden Windows console): never pass them here too
        subprocess.Popen(argv, cwd=root, stdout=log, stderr=log, **procs.background_popen_kwargs())


def _github():
    from .github import GitHub

    return GitHub()


def _run(root: Path) -> int:
    from .group import Git
    from .runner import Runner

    folder = store.folder(root)
    ran = False
    while _hold_runner(root):
        ran = True
        try:
            r = Runner(root, _github(), lambda repo: Git(folder, repo), log=lambda s: print(s, flush=True))
            r.run()
            more = r.has_work()  # an add that came while the lock was still ours started no runner
        finally:
            store._drop_lock(_runner_lock(root))
        if not more:
            other = len(store.waiting(root))
            print(
                f"Nothing waits for this runner; {other} wait for a runner on the GitHub login that added them."
                if other
                else "Nothing waits in the merge queue.",
                flush=True,
            )
            return 0
    if not ran:
        print("The merge queue runs already.")
    return 0


# -- commands ----------------------------------------------------------------------------------------------
def _show(row: dict) -> str:
    t = f"  [{row['ticket']}]" if row.get("ticket") else ""
    return f"{row['state']:8} {row['url']}{t}  {row.get('why') or ''}"


def _wait(root: Path, url: str, max_wait: float, json_out: bool) -> int:
    end = time.monotonic() + max_wait
    while True:
        row = store.find(store.read(root), url)
        if row is None:
            print(f"{url} is not in the merge queue.")
            return 1
        if row.get("state") in FINISHED:
            if json_out:
                print(json.dumps(row))
            else:
                print(row.get("why") or row["state"])
            return 0 if row["state"] == MERGED else 1
        if not runner_alive(root):
            start_runner(root)
        if time.monotonic() > end:
            print(f"{url} still waits in the merge queue ({row.get('why')}); stopped waiting.")
            return 1
        time.sleep(POLL_SECS)


def _tend(root: Path) -> dict:
    from . import switch
    from .github import GitHub

    return switch.tend(root, GitHub(), log=lambda s: print(s, flush=True), start=start_runner)


def _round(root: Path) -> None:
    """One round of the background watcher: read the linked pull requests (the Pull requests page and the live
    state on tickets), then the Merge when green and failed-checks round. A failed read never stops that round."""
    from . import poll

    try:
        got = poll.once(root)
        if got["refreshed"] or got["errors"]:
            print(f"Pull requests: {json.dumps(got)}", flush=True)
    except Exception as e:  # noqa: BLE001 - one bad read never ends the round
        print(f"Pull requests: {e.__class__.__name__}: {str(e)[:200]}", flush=True)
    _watch_round(root)


def _page_cmd(args, root: Path) -> int:
    """poll, view, act refresh: the Pull requests page and the live pull request state on tickets."""
    from . import poll

    if args.cmd == "view":
        from .view import build

        print(json.dumps(build(root)))
        return 0
    if args.cmd == "poll":
        got = poll.once(root)
        text = f"Read {len(got['repos'])} repositories; {len(got['refreshed'])} tickets updated."
        for repo, why in got["errors"].items():
            text += f"\n{repo}: {why}"
        print(json.dumps(got) if args.json else text)
        return 0
    want = args.target.upper()
    t = next(
        (x for x in poll.tickets(root) if x["id"] == args.target or str(x.get("key") or "").upper() == want),
        None,
    )
    if t is None:
        raise Refused(f"There is no ticket {args.target}.")
    print(json.dumps(poll.refresh_one(root, t, os.environ.get(poll.CACHED_ENV) == "1")))
    return 0


def _checks_tend(root: Path) -> dict:
    from . import checks
    from .github import GitHub

    return checks.tend(root, GitHub(), log=lambda s: print(s, flush=True))


def _watch_round(root: Path) -> None:
    """One minute of the watcher: Merge when green, then (when turned on) the failed checks. A failure of one
    part never skips the other."""
    from . import checks

    err = None
    try:
        _tend(root)
    except Exception as e:  # noqa: BLE001 - raised again after the second part ran
        err = e
    if checks.is_on(root):
        _checks_tend(root)
    if err is not None:
        raise err


def _checks_cmd(args, root: Path) -> int:
    """failed-checks on|off|status|tend: rerun a cancelled or timed-out job once, wake the helper on a failure."""
    from . import checks

    def say(data: dict, text: str) -> None:
        print(json.dumps(data) if args.json else text, flush=True)

    if args.state in ("on", "off"):
        on = checks.set_on(root, args.state == "on")
        say(
            {"on": on},
            "Failed checks: on. A cancelled or timed-out job is run again once; a real failure wakes the "
            "ticket's helper. The Merge when green watcher does it every minute (orch pull-requests start)."
            if on
            else "Failed checks: off.",
        )
        return 0
    if args.state == "tend":
        got = _checks_tend(root)
        if not got["on"]:
            say(got, "Failed checks is off: nothing done. Turn it on: orch pull-requests failed-checks on")
            return 0
        say(got, f"Failed checks: {len(got['reran'])} job(s) run again, {len(got['woke'])} helper(s) woken.")
        return 0
    on = checks.is_on(root)
    say({"on": on}, "Failed checks: on." if on else "Failed checks: off.")
    return 0


def _stopped_cmd(args, root: Path) -> int:
    """helper-stopped on|off|status: a ready pull request a helper left open goes into the merge queue."""
    from . import switch

    if args.state in ("on", "off"):
        on = switch.set_stopped(root, args.state == "on")
    else:
        on = switch.stopped_is_on(root)
    text = (
        "Helper stopped: on. When no helper works on a ticket, its pull requests that are ready to merge go into "
        "the merge queue (the Merge when green watcher, every minute)."
        if on
        else "Helper stopped: off."
    )
    print(json.dumps({"on": on}) if args.json else text, flush=True)
    return 0


def _switch_cmd(args, root: Path) -> int:
    """tend, start, stop, status, watch: the Merge when green switch and its background watcher."""
    from . import service

    def say(data: dict, text: str) -> None:
        print(json.dumps(data) if getattr(args, "json", False) else text, flush=True)

    if args.cmd == "watch":
        return service.watch(root, lambda: _round(root), log=lambda s: print(s, flush=True))
    if args.cmd == "tend":
        got = _tend(root)
        n = len(got["added"])
        say(
            got,
            f"Merge when green: {n} pull request(s) put in the merge queue, {len(got['removed'])} taken out.",
        )
        return 0
    if args.cmd == "start":
        pid = service.start(root)
        say({"running": True, "pid": pid}, f"Merge when green watcher runs (pid {pid}).")
        return 0
    if args.cmd == "stop":
        stopped = service.stop(root)
        say({"stopped": stopped}, "Merge when green watcher stopped." if stopped else "It was not running.")
        return 0
    pid = service.running_pid(root)
    say(
        {"running": bool(pid), **({"pid": pid} if pid else {})},
        f"Running (pid {pid})." if pid else "Not running.",
    )
    return 0 if pid else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orch pull-requests")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue", help="the merge queue").add_subparsers(dest="sub", required=True)
    a = q.add_parser("add", help="put a pull request in the merge queue")
    a.add_argument("url")
    a.add_argument("--ticket")
    a.add_argument(
        "--first", action="store_true",
        help="it fixes the red base branch: ahead of the line, alone, also while the base branch is red",
    )  # fmt: skip
    a.add_argument("--wait", action="store_true", help="wait until it is merged or left the queue")
    a.add_argument("--max-wait", type=float, default=240, help="minutes (with --wait)")
    a.add_argument("--json", action="store_true")
    ls = q.add_parser("list", help="what waits and what happened lately")
    ls.add_argument("--json", action="store_true")
    au = q.add_parser(
        "audit",
        help="merges past the queue, times it stood still, check runs per merge, minutes to merged, the busiest hour and group start to merged, for the last hours",
    )
    au.add_argument("--hours", type=float, default=14, help="how far back (default 14: one night)")
    au.add_argument("--json", action="store_true")
    gt = q.add_parser(
        "local-checks",
        help="the local check: side by side with GitHub (same verdict?) and minutes from built to merged",
    )
    gt.add_argument("--last", type=int, default=20, help="local groups counted (default 20)")
    gt.add_argument("--json", action="store_true")
    rm = q.add_parser("remove", help="take a waiting pull request out of the queue")
    rm.add_argument("url")
    r = q.add_parser("run", help="the runner (add starts it by itself)")
    r.add_argument("--root", help=argparse.SUPPRESS)
    t = sub.add_parser("tend", help="Merge when green: one pass over the switched-on tickets")
    t.add_argument("--json", action="store_true")
    for name, text in (
        ("start", "start the Merge when green watcher"),
        ("stop", "stop it"),
        ("status", "is it running?"),
    ):
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    for name, text in (("poll", "read the linked pull requests now"), ("view", "the Pull requests page")):
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    ac = sub.add_parser("act", help="what the ticket page's Refresh does (run through orch, which writes)")
    ac.add_argument("verb", choices=["refresh"])
    ac.add_argument("--by", help="who asked (recorded on the ticket by orch)")
    ac.add_argument("--json", action="store_true")
    ac.add_argument("target", help="ticket id or key")
    fc = sub.add_parser(
        "failed-checks", help="rerun a cancelled or timed-out job once, wake the helper on a failure"
    )
    fc.add_argument("state", nargs="?", choices=("on", "off", "status", "tend"), default="status")
    fc.add_argument("--json", action="store_true")
    hs = sub.add_parser(
        "helper-stopped", help="a ready pull request a helper left open goes into the merge queue by itself"
    )
    hs.add_argument("state", nargs="?", choices=("on", "off", "status"), default="status")
    hs.add_argument("--json", action="store_true")
    w = sub.add_parser("watch")  # hidden: no help= keeps it out of the --help list
    w.add_argument("--root", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    try:
        root = _root(getattr(args, "root", None))
        if args.cmd in ("poll", "view", "act"):
            return _page_cmd(args, root)
        if args.cmd == "failed-checks":
            return _checks_cmd(args, root)
        if args.cmd == "helper-stopped":
            return _stopped_cmd(args, root)
        if args.cmd != "queue":
            return _switch_cmd(args, root)
        if args.sub == "run":
            return _run(root)
        if args.sub == "list":
            rows = store.read(root)
            if args.json:
                print(json.dumps({"entries": rows, "running": runner_alive(root)}, indent=1))
            elif not rows:
                print("The merge queue is empty.")
            else:  # what waits, and the last 50 that ended (the file keeps more for the audit)
                done = [x for x in rows if x.get("state") in FINISHED]
                shown = done[-50:] + [x for x in rows if x.get("state") not in FINISHED]
                print("\n".join(_show(x) for x in rows if x in shown))
            return 0
        if args.sub == "audit":
            from . import audit

            if args.hours <= 0:
                raise Refused("--hours is a number of hours above 0.")
            report = audit.run(root, _github(), args.hours)
            print(json.dumps(audit.as_json(report), indent=1) if args.json else audit.text(report))
            return 0
        if args.sub == "local-checks":
            from . import localcheck, settings

            got = localcheck.summary(root, max(1, args.last))
            got["group_check"] = settings.group_check(root)
            print(
                json.dumps(got, indent=1)
                if args.json
                else f"Groups are checked: {got['group_check']}.\n" + localcheck.text(got)
            )
            return 0
        if args.sub == "remove":
            if store.remove(root, args.url, _actor()):
                print(f"Taken out of the merge queue: {args.url}")
                return 0
            print(f"{args.url} does not wait in the merge queue.")
            return 1
        from .runner import _release_fix, admit

        url = store.canonical(args.url)
        ticket = _ticket(root, args.ticket, url)
        old = store.find(store.read(root), url)
        seen = {} if old and old.get("state") not in FINISHED else admit(root, _github(), url)
        # a release keeper's red-run fix goes first by itself (ORCH-1023)
        first = args.first or _release_fix(root, ticket)
        row, new = store.add(root, url, ticket, _actor(), first=first, **seen)
        start_runner(root)
        if not args.wait:
            ahead = [x for x in store.read(root) if x.get("state") not in FINISHED and x["url"] != url]
            if args.json:
                print(json.dumps({**row, "new": new, "ahead": len(ahead)}))
            else:
                where = "Added to" if new else "Already in"
                print(f"{where} the merge queue: {url} ({len(ahead)} ahead of it).")
            return 0
        return _wait(root, url, args.max_wait * 60, args.json)
    except Refused as e:
        print(str(e), file=sys.stderr)
        if getattr(args, "json", False):  # the add-on CLI contract: with --json the refusal is on stdout too
            print(json.dumps({"error": str(e)}))
        return 2
    except Exception as e:  # the core's Refused (ticket not found ...) is plain words too
        if e.__class__.__name__ == "Refused":
            print(str(e), file=sys.stderr)
            return 2
        raise
