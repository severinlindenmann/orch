"""`orch start`, `orch stop`, `orch status`: add-on background processes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import cardtext, history, look, pagelaunch, services, term
from orch.errors import Refused


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    x = sub.add_parser("start", parents=[common], help="start the add-ons that run in the background here")
    x.add_argument("--no-open", action="store_true", help="do not open the dashboard in the browser")
    x.add_argument(
        "--print-launch-url",
        action="store_true",
        help=argparse.SUPPRESS,  # test installs only: print a one-time page link (for browser tests)
    )
    x = sub.add_parser(
        "stop", parents=[common], help="stop them (asks which workspace when you are outside one)"
    )
    x.add_argument("workspace", nargs="?", metavar="PATH|NAME", help="the workspace to stop")
    x.add_argument("--all", action="store_true", help="stop every running workspace")
    x.add_argument("--pick", action="store_true", help="choose from the running workspaces")
    sub.add_parser("status", parents=[common], help="what runs in the background, and where")
    sub.add_parser("pause", parents=[common], help="stop all automation in this workspace")
    sub.add_parser("resume", parents=[common], help="turn automation back on after orch pause")
    c = sub.add_parser("copy", help=argparse.SUPPRESS).add_subparsers(dest="sub", required=True)
    for name in ("update", "ask-update", "review", "approve"):
        item = c.add_parser(name, parents=[common])
        item.add_argument("ticket")
        if name == "approve":  # what the person was shown; compared with the copy as it is now
            item.add_argument("--approve-tip", help=argparse.SUPPRESS)
            item.add_argument("--control-paths", type=int, help=argparse.SUPPRESS)
            item.add_argument("--paths-hash", help=argparse.SUPPRESS)
    cc = c.add_parser("clean", parents=[common], help="take back the separate copies nobody needs")
    cc.add_argument("--trash", action="store_true", help=argparse.SUPPRESS)  # empty the trash (detached run)
    cc.add_argument("--background", action="store_true", help=argparse.SUPPRESS)  # sweep + trash, silent
    rt = c.add_parser("retry", parents=[common], help="try again where git was interrupted (a person's call)")
    rt.add_argument("ticket")
    rt.add_argument("--approve-tip", help=argparse.SUPPRESS)
    rt.add_argument("--control-paths", type=int, help=argparse.SUPPRESS)
    rt.add_argument("--paths-hash", help=argparse.SUPPRESS)
    ro = c.add_parser(
        "remove-orphaned",
        parents=[common],
        help="remove the copies of a project that is gone (a person's call)",
    )
    ro.add_argument("ws8", help="the copies folder (8 characters), as `orch copy clean` lists it")
    ro.add_argument("--discard", action="store_true", help="also remove copies whose changes cannot be saved")


def _home_path(p: str) -> str:
    try:
        return "~/" + Path(p).relative_to(Path.home()).as_posix()
    except ValueError:
        return p


def _service_line(r: dict) -> str:
    if r.get("error"):
        return f"  {r['addon']:<12}did not start: {r['error']}"
    if r.get("running") is False and r.get("idle"):
        return f"  {r['addon']:<12}off here (turned off in its settings)"
    if r.get("running") is False and "last_seen" not in r and "url" not in r:
        return f"  {r['addon']:<12}not running - start it: orch start"
    if r.get("running") is False and "last_seen" in r:
        seen = services.ago(r["last_seen"])
        return f"  {r['addon']:<12}not running (last seen {seen}) - start it: orch start"
    url = services.local_url(r.get("url"))
    return f"  {r['addon']:<12}" + (url or f"running (pid {r.get('pid')})")


def _pick(running: list[dict]) -> list[Path]:
    if not running:
        return []
    if not term.is_terminal(sys.stdin):
        raise Refused(
            "Say which workspace to stop: orch stop <folder|name>, or orch stop --all. "
            "See what runs: orch status"
        )
    print("Running workspaces:")
    for i, w in enumerate(running, 1):
        names = ", ".join(a["addon"] for a in w["addons"])
        print(f"  {i}  {w['name']:<20}{_home_path(w['workspace'])}  ({names})")
    ans = input('Which one to stop? Number, "all", or Enter for none: ').strip().lower()
    if not ans:
        return []
    if ans == "all":
        return [Path(w["workspace"]) for w in running]
    if ans.isdigit() and 1 <= int(ans) <= len(running):
        return [Path(running[int(ans) - 1]["workspace"])]
    raise Refused(f"'{ans}' is not on the list. Nothing was stopped.")


def _launch_urls(root: Path, rows: list[dict]) -> list[tuple[str, str]]:

    out = []
    for r in rows:
        base = services.local_url(r.get("url"))
        if base and r.get("addon") in pagelaunch.LAUNCH_SERVERS:
            out.append((r["addon"], pagelaunch.printable_launch_url(root, r["addon"], base)))
    return out


def _services_cmd(args, root: Path) -> None:
    if args.cmd == "start":
        if args.print_launch_url:  # refuse before anything starts
            if not pagelaunch.is_test_workspace(root):
                raise Refused("--print-launch-url works only on a test install, in a test folder.")
        from orch import worktrees

        worktrees.schedule_sweep(root)  # B12: copies nobody needs, in a detached run (never raises)
        rows = services.start(root)
        launch = _launch_urls(root, rows) if args.print_launch_url else []
        if args.json:
            data = {"workspace": str(root.resolve()), "addons": rows}
            if args.print_launch_url:
                data["launch"] = [{"addon": a, "url": u} for a, u in launch]
            print(json.dumps(data, indent=2))
        elif not rows:
            print("No add-on that is on here runs in the background. Nothing to start.")
        else:
            print(f"Started in {root.name}:")
            print("\n".join(_service_line(r) for r in rows))
            print("Stop: orch stop")
        if launch and not args.json:
            print("\n".join(f"launch {a}: {u}" for a, u in launch))
        row = next((r for r in rows if services.local_url(r.get("url"))), None)
        url = services.local_url(row.get("url")) if row else None
        opens = not args.no_open and not args.print_launch_url and not args.json
        if url and opens and term.is_terminal(sys.stdout):
            # a person opens the page: the launch token (URL fragment) lets it start a proof session (H1)
            pagelaunch.open_browser(pagelaunch.launch_url(root, row.get("addon"), url))
        bad = [r for r in rows if r.get("error")]
        if bad:
            raise Refused(", ".join(r["addon"] for r in bad) + " did not start (see above).")
    elif args.cmd == "status":
        ws = services.status()
        if (root / ".orch").is_dir():  # this workspace: one row per background add-on, stopped ones too
            here = services.workspace_rows(root)
            if here:
                key = str(root.resolve())
                w = next((x for x in ws if x["workspace"] == key), None)
                if w is None:
                    w = {"workspace": key, "name": root.resolve().name, "addons": []}
                    ws = sorted([*ws, w], key=lambda x: (x["name"].lower(), x["workspace"]))
                w["addons"] = here
        ws = _with_known(ws)
        for w in ws:  # the workspace switcher draws each one with its badge
            w.update({k: look.read(Path(w["workspace"]))[k] for k in ("icon", "color")})
        lines = []
        for w in ws:
            lines.append(f"{w['name']}  ({_home_path(w['workspace'])})")
            lines += [_service_line(a) for a in w["addons"]] or ["  nothing running"]
        if (root / ".orch").is_dir() and not args.json:  # git notes for this workspace (a plain line each)
            from orch import cli_config

            lines += cli_config.private_lines(root)
        from orch import updateinfo

        if (root / ".orch").is_dir() and not args.json:
            from orch import brake

            if brake.paused(root) is not None:
                lines.append("Automation is paused. Turn it back on with: orch resume")
        _out(
            args,
            ws,
            ("\n".join(lines) or "Nothing runs in the background. Start it in a workspace: orch start")
            + f"\n{updateinfo.current_label()}",  # which release this is (e.g. "orch 16")
        )
    else:
        if args.all:
            targets = [Path(w["workspace"]) for w in services.status()]
        elif args.workspace:
            targets = [services.find(args.workspace)]
        elif (root / ".orch").is_dir() and not args.pick:
            targets = [root.resolve()]
        else:
            targets = _pick(services.status())
        from orch import runs_live

        done = [
            {"workspace": str(t), "addons": services.stop(t), "sessions": runs_live.stop_hidden(t)}
            for t in targets
        ]
        lines = []
        for d in done:
            names = [r["addon"] for r in d["addons"] if r["stopped"]]
            lines.append(
                f"Stopped in {Path(d['workspace']).name}: " + (", ".join(names) or "nothing was running")
            )
        _out(args, done, "\n".join(lines) or "Nothing was stopped.")


def _with_known(ws: list) -> list:
    """Add the person's other known workspaces (consent records) that run nothing, so the switcher can list
    them as "Not running". Only folders that still exist and hold .orch; de-duplicated by resolved path."""
    from orch import addons

    try:
        known = addons._registered_workspaces(None)
    except Exception:
        return ws
    seen = {str(Path(w["workspace"]).resolve()) for w in ws}
    extra = []
    for p in known:
        if str(p) in seen or not (p / ".orch").is_dir():
            continue
        seen.add(str(p))
        extra.append({"workspace": str(p), "name": p.name, "addons": []})
    return sorted([*ws, *extra], key=lambda x: (x["name"].lower(), x["workspace"])) if extra else ws


def _copy_clean(args, root: Path) -> None:
    from orch import worktrees

    if args.sub in ("update", "ask-update"):
        from orch import tickets

        tid = tickets.load(root, args.ticket)["id"]
        message = (worktrees.update_copy if args.sub == "update" else worktrees.ask_update)(root, tid)
        _out(args, {"message": message}, message)
        return
    if args.sub == "review":
        target, tip, paths = worktrees.approval_view(root, args.ticket)
        # Path names are the agent's: each one is shown as one plain line (no newlines, no fake quotes).
        shown = [cardtext.part(p) for p in paths]
        summary = worktrees.control_summary(shown)
        size = worktrees.change_counts(root, tip)
        result = {
            "target": target,
            "tip": tip,
            **({"commits": size[0], "files": size[1]} if size else {}),
            "control_paths": len(paths),
            "paths_hash": target.rsplit(":", 1)[1],
            "paths": shown[:5],
            "paths_summary": summary,
        }
        brings = f"{size[0]} commits, {size[1]} files, " if size else ""
        text = f"Tip {tip}: {brings}{len(paths)} orch or git control paths." + (
            f" {summary}" if summary else ""
        )
        _out(args, result, text)
        return
    if args.sub == "approve" or (args.sub == "retry" and getattr(args, "approve_tip", None)):
        target, tip, paths = worktrees.approval_view(root, args.ticket)
        count, digest = len(paths), target.rsplit(":", 1)[1]
        size = worktrees.change_counts(root, tip)
        shown = getattr(args, "approve_tip", None)
        if (shown is not None or args.sub == "retry") and (
            shown != tip or args.control_paths != count or args.paths_hash != digest
        ):
            raise Refused("The copy changed after it was shown. Review it again.")
        result = worktrees.approve_copy(root, args.ticket, target)
        _out(args, result, result.get("reason") or "Brought back.")
        return
    if args.sub == "remove-orphaned":
        if not isinstance(args.ws8, str) or not worktrees._WS8.fullmatch(args.ws8):
            raise Refused("That is not a copies folder.")
        notes = worktrees.remove_orphaned(root, args.ws8, args.discard)
        _out(args, {"notes": notes}, "\n".join(notes) or "Removed.")
        return
    if args.sub == "retry":
        if not isinstance(args.ticket, str) or not worktrees._TID.fullmatch(args.ticket):
            raise Refused("That is not a ticket id.")
        notes = worktrees.retry(root, args.ticket)
        _out(args, {"notes": notes}, "\n".join(notes) or "Done.")
        return
    if args.trash:
        worktrees.empty_trash(root)
        return
    if args.background:
        worktrees.sweep(root)
        worktrees.empty_trash(root)
        return
    notes = worktrees.sweep(root)
    u = worktrees.usage(root)
    lines = [
        *notes,
        f"{u['copies']} separate copies are in use." if u["copies"] else "No separate copies left.",
    ]
    for o in u["orphaned"]:
        lines.append(
            f"{o['copies']} copies of a project that is gone or moved: orch copy remove-orphaned {o['ws8']}"
        )
    _out(
        args,
        {k: u[k] for k in ("copies", "bytes", "partial", "orphaned", "changed", "stuck")} | {"notes": notes},
        "\n".join(lines),
    )


def _brake_cmd(args, root: Path) -> None:
    from orch import brake, tickets

    if not (root / ".orch").is_dir():
        raise Refused("This folder is not an orch workspace. Go into one, or run: orch init")
    if args.cmd == "pause":
        rec = brake.pause(root, tickets.current_actor(args.by))
        _out(
            args,
            {"paused": True, **rec},
            "Automation paused in this workspace. Nothing starts on its own until you run: orch resume",
        )
    else:
        was = brake.resume(root)
        _out(
            args,
            {"paused": False, "was_paused": was},
            "Automation is on again in this workspace."
            if was
            else "Automation was not paused. Nothing to do.",
        )


def dispatch(args, root: Path) -> bool:
    if args.cmd == "copy":
        _copy_clean(args, root)
        return True
    if args.cmd in ("pause", "resume"):
        _brake_cmd(args, root)
        return True
    if args.cmd not in ("start", "stop", "status"):
        return False
    _services_cmd(args, root)
    return True
