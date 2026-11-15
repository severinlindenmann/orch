"""orch lessons add|list|edit|rm|act|view (contract: contracts/addons/lessons/README.md)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import store
from .store import Refused

SAVED = "Saved. Helpers read it from their next start."


def _root(start: str) -> Path:
    p = Path(start).absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _actor(explicit: str | None) -> str:
    if explicit:
        if not store.valid_actor(explicit):
            raise Refused(f"'{explicit}' is not a valid name. Use agent:<tool> or human:<name>.")
        return explicit
    inside_run = os.environ.get("ORCH_RUN") or os.environ.get("ORCH_AGENT")
    tool = None
    try:
        from orch import tickets

        tool = tickets.agent_tool()
    except Exception:  # noqa: BLE001 - no core to ask: fall back to the environment
        tool = None
    if inside_run or tool:
        name = re.sub(r"[^A-Za-z0-9_.@-]", "_", os.environ.get("ORCH_AGENT") or tool or "helper")[:64]
        return f"agent:{name or 'helper'}"
    try:
        import getpass

        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "human:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", user)[:64] or "user")


def _ticket(root: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    tid = ref.strip()
    try:
        from orch import tickets

        tid = tickets.resolve(root, tid)
    except Exception as e:  # noqa: BLE001 - Refused from the core already says what to do
        if e.__class__.__name__ == "Refused":
            raise Refused(str(e)) from None
    if (
        not isinstance(tid, str)
        or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid)
        or not (root / ".orch" / "tickets" / f"{tid}.json").is_file()
    ):
        raise Refused(f"Ticket {ref} doesn't exist. Run `orch ticket list` to see your tickets.")
    return tid


def _secrets(root: Path, text: str) -> None:
    try:
        from orch import secretscan
    except ImportError:  # the core is always there (python -m under orch); never a silent pass
        raise Refused("Could not check the text for secrets. Update orch and try again.") from None
    found = secretscan.find(text, root)
    if found:
        raise Refused(secretscan.refusal(found))


def _next(root: Path, base: str) -> str:
    d = store.load(root)
    return f"{base} {store.OVER_CAP}" if d["bytes"] > store.CAP else base


def _emit(args, data: dict, text: str) -> int:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)
    return 0


def _fail(args, msg: str) -> int:
    if args.json:
        print(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        print(f"Refused: {msg}", file=sys.stderr)
    return 2


def run(args) -> int:
    root = _root(args.dir)
    cmd = args.cmd
    if cmd == "act":
        cmd = args.verb
        args.id, args.text = args.target, args.value
    if cmd == "add":
        _secrets(root, store.clean_text(args.text))
        row, added = store.add(root, args.text, _actor(args.by), _ticket(root, args.ticket))
        if added:
            nxt = _next(root, SAVED)
            return _emit(args, {"lesson": row, "added": True, "next": nxt}, nxt)
        nxt = "Already saved. Nothing changed."
        return _emit(args, {"lesson": row, "added": False, "next": nxt}, nxt)
    if cmd == "edit":
        text = store.clean_text(args.text or "")
        _secrets(root, text)
        row = store.edit(root, args.id, text, _actor(args.by))
        nxt = _next(root, SAVED)
        return _emit(args, {"lesson": row, "next": nxt}, nxt)
    if cmd == "rm":
        store.remove(root, args.id)
        nxt = "Removed. Helpers no longer see it from their next start."
        return _emit(args, {"removed": args.id, "next": nxt}, nxt)
    if cmd == "list":
        d = store.load(root)
        if args.json:
            print(json.dumps(d, ensure_ascii=False))
            return 0
        lines = [f"{r['id']}  {r['text']}" for r in d["lessons"]] or ["No lessons yet."]
        if d["unreadable"]:
            lines.append(
                f"{d['unreadable']} file(s) in .orch/addons/lessons could not be read and are skipped."
            )
        lines.append('Next: orch lessons add "<one line>"  (or edit / rm <id>)')
        print("\n".join(lines))
        return 0
    if cmd == "view":
        from .view import build

        print(json.dumps(build(root), ensure_ascii=False))
        return 0
    raise Refused(f"Unknown command {cmd}.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orch lessons")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true")
        return s

    s = p("add")
    s.add_argument("text")
    s.add_argument("--ticket")
    s.add_argument("--by")
    p("list")
    s = p("edit")
    s.add_argument("id")
    s.add_argument("text")
    s.add_argument("--by")
    s = p("rm")
    s.add_argument("id")
    p("view")
    s = p("act")
    s.add_argument("verb", choices=("edit", "rm"))
    s.add_argument("target")
    s.add_argument("--value")
    s.add_argument("--by")
    args = ap.parse_args(argv)
    args.json = bool(getattr(args, "json", False)) or "--json" in (argv if argv is not None else sys.argv)
    try:
        return run(args)
    except Refused as e:
        return _fail(args, str(e))
