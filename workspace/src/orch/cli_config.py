"""`orch config` (agent settings) and `orch agents`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import adapters, config
from orch.errors import Refused

KEYS = ("workspace.agent",)


def add_parsers(sub, common) -> None:
    sub.add_parser("agents", parents=[common], help=argparse.SUPPRESS)
    c = sub.add_parser("config", help=argparse.SUPPRESS).add_subparsers(dest="sub", required=True)
    g = c.add_parser("get", parents=[common])
    g.add_argument("key", nargs="?", choices=KEYS)
    s = c.add_parser("set", parents=[common])
    s.add_argument("key", choices=KEYS)
    s.add_argument("value")
    a = c.add_parser("agent", parents=[common])
    a.add_argument("name_or_add", metavar="add|NAME")
    a.add_argument("name", nargs="?")
    a.add_argument("--command", help="the command that does the work; {prompt} is where the task goes")
    a.add_argument("--interactive", help="optional: the command that starts it for a live session")


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _choose(root: Path, name: str) -> str:
    adapters.load(name, root)  # refuses a name nobody knows
    config.set_key(root, "workspace", "agent", name)
    return name


def agents_rows(root: Path) -> list[dict]:
    found = {r["name"]: r for r in adapters.detect()}
    entries = config.agent_entries(root)
    chosen = config.agent_name(root)
    rows = []
    for name in list(found) + [n for n in entries if n not in found]:
        a = adapters.load(name, root)
        f = found.get(name)
        if name in entries:
            status = (
                "your command"
                if entries[name].get("command")
                else (
                    f"found {f['version']}"
                    if f and f["found"] and f["version"]
                    else "found"
                    if f and f["found"]
                    else "not found"
                )
            )
        else:
            status = (
                (f"found {f['version']}" if f["version"] else "found") if f and f["found"] else "not found"
            )
        rows.append(
            {
                "name": name,
                "label": a["label"],
                "adapter": a["adapter"],
                "found": bool(f and f["found"]) or bool(entries.get(name, {}).get("command")),
                "version": f["version"] if f else None,
                "can": adapters.describe(name, root) if status != "not found" else "",
                "status": status,
                "chosen": name == chosen,
            }
        )
    return rows


def _agents(args, root: Path) -> None:
    rows = agents_rows(root)
    width = max(len(r["name"]) for r in rows) + 2
    sw = max(len(r["status"]) for r in rows) + 3
    lines = [f"{r['name']:<{width}}{r['status']:<{sw}}{r['can']}".rstrip() for r in rows]
    chosen = next((r for r in rows if r["chosen"]), None)
    if chosen:
        lines.append(f"* {chosen['name']} does the work here")
    else:
        lines.append("No agent chosen here. Pick one: orch config set workspace.agent <name>")
    _out(args, rows, "\n".join(lines))


def _config(args, root: Path) -> None:
    if args.sub == "get":
        cur = {"workspace.agent": config.agent_name(root)}
        if args.key:
            _out(args, {args.key: cur[args.key]}, cur[args.key] or "(not set)")
        else:
            _out(args, cur, "\n".join(f"{k} = {v}" for k, v in cur.items() if v) or "Nothing is set.")
    elif args.sub == "set":
        name = _choose(root, args.value)
        _out(
            args,
            {"workspace.agent": name},
            f"Saved: workspace.agent = {name}. {adapters.describe(name, root)}.",
        )
    else:
        if args.name_or_add == "add":
            if not args.name or not args.command:
                raise Refused(
                    'Say the name and the command: orch config agent add <name> --command "... {prompt}"'
                )
            config.add_agent(root, args.name, args.command, args.interactive)
            tail = (
                "starts fresh each run; no live steps"
                if not args.interactive
                else "starts fresh each run; live session possible"
            )
            _out(args, {"agent": args.name}, f"Added {args.name} ({tail}).")
        else:
            name = _choose(root, args.name_or_add)
            _out(args, {"workspace.agent": name}, f"Saved: workspace.agent = {name}.")


def dispatch(args, root: Path) -> bool:
    if args.cmd == "agents":
        _agents(args, root)
    elif args.cmd == "config":
        _config(args, root)
    else:
        return False
    return True
