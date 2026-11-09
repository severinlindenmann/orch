"""`orch start`, `orch stop`, `orch status`: add-on background processes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from orch import look, services, term
from orch.errors import Refused


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    x = sub.add_parser("start", parents=[common], help="start the add-ons that run in the background here")
    x.add_argument("--no-open", action="store_true", help="do not open the dashboard in the browser")
    x = sub.add_parser(
        "stop", parents=[common], help="stop them (asks which workspace when you are outside one)"
    )
    x.add_argument("workspace", nargs="?", metavar="PATH|NAME", help="the workspace to stop")
    x.add_argument("--all", action="store_true", help="stop every running workspace")
    x.add_argument("--pick", action="store_true", help="choose from the running workspaces")
    sub.add_parser("status", parents=[common], help="what runs in the background, and where")


def _home_path(p: str) -> str:
    try:
        return "~/" + Path(p).relative_to(Path.home()).as_posix()
    except ValueError:
        return p


def _service_line(r: dict) -> str:
    if r.get("error"):
        return f"  {r['addon']:<12}did not start: {r['error']}"
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


def _services_cmd(args, root: Path) -> None:
    if args.cmd == "start":
        rows = services.start(root)
        if args.json:
            print(json.dumps({"workspace": str(root.resolve()), "addons": rows}, indent=2))
        elif not rows:
            print("No add-on that is on here runs in the background. Nothing to start.")
        else:
            print(f"Started in {root.name}:")
            print("\n".join(_service_line(r) for r in rows))
            print("Stop: orch stop")
        url = next((services.local_url(r.get("url")) for r in rows if services.local_url(r.get("url"))), None)
        if url and not args.no_open and not args.json and term.is_terminal(sys.stdout):
            import webbrowser

            webbrowser.open(url)
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
        for w in ws:  # the workspace switcher draws each one with its badge
            w.update({k: look.read(Path(w["workspace"]))[k] for k in ("icon", "color")})
        lines = []
        for w in ws:
            lines.append(f"{w['name']}  ({_home_path(w['workspace'])})")
            lines += [_service_line(a) for a in w["addons"]]
        if (root / ".orch").is_dir() and not args.json:  # git notes for this workspace (a plain line each)
            from orch import cli_config

            lines += cli_config.private_lines(root)
        _out(
            args,
            ws,
            "\n".join(lines) or "Nothing runs in the background. Start it in a workspace: orch start",
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
        done = [{"workspace": str(t), "addons": services.stop(t)} for t in targets]
        lines = []
        for d in done:
            names = [r["addon"] for r in d["addons"] if r["stopped"]]
            lines.append(
                f"Stopped in {Path(d['workspace']).name}: " + (", ".join(names) or "nothing was running")
            )
        _out(args, done, "\n".join(lines) or "Nothing was stopped.")


def dispatch(args, root: Path) -> bool:
    if args.cmd not in ("start", "stop", "status"):
        return False
    _services_cmd(args, root)
    return True
