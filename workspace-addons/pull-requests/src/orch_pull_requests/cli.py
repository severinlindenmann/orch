"""orch pull-requests queue add|list|remove|run, tend, start|stop|status (contract: contracts/addons/pull-requests/README.md)."""

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

    tid = tickets.resolve(root, ref.strip())
    t = tickets.load(root, tid)
    for q in t.get("questions") or []:
        if q.get("answer") is None and review.merge_url(q) == url:
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
        subprocess.Popen(
            argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=os.name != "nt", **procs.background_popen_kwargs(),
        )  # fmt: skip


def _run(root: Path) -> int:
    from .github import GitHub
    from .group import Git
    from .runner import Runner

    folder = store.folder(root)
    ran = False
    while _hold_runner(root):
        ran = True
        try:
            r = Runner(root, GitHub(), lambda repo: Git(folder, repo), log=lambda s: print(s, flush=True))
            r.run()
        finally:
            store._drop_lock(_runner_lock(root))
        if not store.waiting(root):  # an add that came while the lock was still ours started no runner
            print("The merge queue is empty.", flush=True)
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


def _switch_cmd(args, root: Path) -> int:
    """tend, start, stop, status, watch: the Merge when green switch and its background watcher."""
    from . import service

    def say(data: dict, text: str) -> None:
        print(json.dumps(data) if getattr(args, "json", False) else text, flush=True)

    if args.cmd == "watch":
        return service.watch(root, lambda: _tend(root), log=lambda s: print(s, flush=True))
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
    a.add_argument("--wait", action="store_true", help="wait until it is merged or left the queue")
    a.add_argument("--max-wait", type=float, default=240, help="minutes (with --wait)")
    a.add_argument("--json", action="store_true")
    ls = q.add_parser("list", help="what waits and what happened lately")
    ls.add_argument("--json", action="store_true")
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
    w = sub.add_parser("watch", help=argparse.SUPPRESS)
    w.add_argument("--root", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    try:
        root = _root(getattr(args, "root", None))
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
            else:
                print("\n".join(_show(x) for x in rows))
            return 0
        if args.sub == "remove":
            if store.remove(root, args.url, _actor()):
                print(f"Taken out of the merge queue: {args.url}")
                return 0
            print(f"{args.url} does not wait in the merge queue.")
            return 1
        repo, number = store.parse_url(args.url)
        url = f"https://github.com/{repo}/pull/{number}"
        row, new = store.add(root, url, _ticket(root, args.ticket, url), _actor())
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
        return 2
    except Exception as e:  # the core's Refused (ticket not found ...) is plain words too
        if e.__class__.__name__ == "Refused":
            print(str(e), file=sys.stderr)
            return 2
        raise
