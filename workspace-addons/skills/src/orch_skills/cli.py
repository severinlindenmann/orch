"""orch skills list|on|off|delete|restore|new|bin|history|act|run|start|stop|status (contract: contracts/addons/skills/README.md)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import bin as skill_bin
from . import model
from .switches import Refused

VERBS = ("on", "off", "delete", "restore", "new")
TARGET = re.compile(r"(skill|instructions|service|login):(orch|workspace|admin|mine):[A-Za-z0-9_.@-]{1,120}")
HISTORY = Path(".orch") / "addons" / "skills" / "history.jsonl"
HISTORY_WORD = {
    "on": "turned on",
    "off": "turned off",
    "delete": "moved to the bin",
    "restore": "restored",
    "new": "made as a draft",
}
KIND_WORD = {"skills": "Skills", "instructions": "Instructions", "services": "Connected services", "logins": "Logins"}


def _root(start: str) -> Path:
    p = Path(start).absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _actor(explicit: str | None) -> str:
    if explicit:
        who = re.sub(r"\s+", "_", explicit.strip())[:70]
        if not re.fullmatch(r"(agent|human):[A-Za-z0-9_.@-]{1,64}", who):
            raise Refused(f"'{explicit}' is not a valid name for the history.")
        return who
    if os.environ.get("ORCH_RUN") or os.environ.get("ORCH_AGENT"):
        return "agent:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", os.environ.get("ORCH_AGENT") or "helper")[:64] or "helper")
    try:
        import getpass

        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "human:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", user)[:64] or "user")


def _log(root: Path, who: str, what: str, item: dict) -> None:
    from .switches import safe_path

    path = safe_path(root, HISTORY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = safe_path(root, HISTORY)
    row = {"at": model.now(), "who": who, "what": what, "item": item["id"], "name": item["name"]}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _a_helper_runs_this() -> bool:
    """Like the core (addons.py, cli_config._actor): a helper tool in the environment counts as a helper,
    whatever --by says."""
    if os.environ.get("ORCH_RUN") or os.environ.get("ORCH_AGENT"):
        return True
    try:
        from orch import tickets

        return bool(tickets.agent_tool())
    except Exception:  # noqa: BLE001  no core to ask: only the environment above
        return False


def _history(root: Path) -> list[dict]:
    try:
        lines = (root / HISTORY).read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out[::-1]


def _emit(args, data, text: str) -> int:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)
    return 0


def _fail(args, msg: str) -> int:
    if args.json:
        print(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        print(f"Refused: {msg}", file=sys.stderr)
    return 2


def _list_text(data: dict) -> str:
    lines = []
    for kind, word in KIND_WORD.items():
        lines.append(f"{word}:")
        for it in data[kind]:
            state = "on" if it["on"] else "off"
            extra = f" ({it['note']})" if it.get("note") else ""
            look = f"  needs a look: {'; '.join(it['problems'])}" if it["problems"] else ""
            lines.append(f"  {it['id']}  {state}{extra}{look}")
        if not data[kind]:
            lines.append("  (none)")
    lines.append("Next: orch skills off <id>  (or on <id>)")
    return "\n".join(lines)


def _turn(args, root: Path, on: bool) -> int:
    who = _actor(args.by)
    if _a_helper_runs_this() or not who.startswith("human:"):
        raise Refused("Only a person turns things on or off here. Ask the person to use the switch on the Skills page.")
    target = args.target.strip()
    if not TARGET.fullmatch(target):
        raise Refused("Name the item by its id from orch skills list, e.g. skill:orch:orch-hello.")
    res = model.turn(root, target, on)
    it = res["item"]
    if res["changed"]:
        _log(root, who, "on" if on else "off", it)
        text = f"{it['name']} is {'on' if on else 'off'} in this workspace." + (
            f" {it['note']}." if it.get("note") else ""
        )
        text += " Helpers notice from their next start."
    else:
        text = f"{it['name']} was already {'on' if on else 'off'}. Nothing changed."
    return _emit(args, {"item": it, "changed": res["changed"], "next": text}, text)


def _person(args) -> str:
    who = _actor(args.by)
    if _a_helper_runs_this() or not who.startswith("human:"):
        raise Refused("Only a person deletes, restores or makes skills here. Ask the person to use the Skills page.")
    return who


def _delete(args, root: Path) -> int:
    who = _person(args)
    target = args.target.strip()
    if not TARGET.fullmatch(target):
        raise Refused("Name the skill by its id from orch skills list, e.g. skill:workspace:weekly-report.")
    res = model.delete(root, target, who)
    it, row = res["item"], res["bin"]
    _log(root, who, "delete", it)
    place = "every workspace on this computer" if it["where"] == "mine" else "this workspace"
    text = f"{it['name']} is in the bin; helpers in {place} no longer see it. Undo: orch skills restore {row['id']}"
    if row.get("note"):
        text += f" ({row['note']})"
    return _emit(args, {"item": it, "bin": row, "changed": True, "next": text}, text)


def _restore(args, root: Path) -> int:
    who = _person(args)
    target = args.target.strip()
    if not skill_bin.BIN_TARGET.fullmatch(target):
        raise Refused(
            "Name the bin entry by its id from orch skills bin, e.g. bin:workspace:20261120T120000Z-x-a1b2c3."
        )
    res = model.restore(root, target, who)
    _log(root, who, "restore", res["item"])
    text = f"{res['item']['name']} is back where it was. Helpers see it from their next start."
    return _emit(args, {**res, "changed": True, "next": text}, text)


def _new(args, root: Path) -> int:
    who = _person(args)
    name = args.target.strip()
    if name.startswith("skill:workspace:"):  # the page names it like an item
        name = name.split(":", 2)[2]
    res = model.new_skill(root, name, who.split(":", 1)[1])
    _log(root, who, "new", res["item"])
    text = f"Made the draft skill {name} in .agents/skills/{name}/SKILL.md. Fill in its description and steps."
    return _emit(args, {**res, "changed": True, "next": text}, text)


def _bin_text(rows: list[dict]) -> str:
    if not rows:
        return "The bin is empty."
    lines = []
    for r in rows:
        state = "" if r["can_restore"] else f"  ({r.get('why', 'cannot be restored now')})"
        lines.append(f"  {r['id']}  {r['name']} from {r['from']}, deleted {r['at']} by {r['by']}{state}")
    return "In the bin (nothing is removed by itself):\n" + "\n".join(lines) + "\nNext: orch skills restore <id>"


def _loop(args, root: Path) -> int:
    from . import server, service

    cmd = args.cmd
    if cmd == "run":
        import signal

        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"orch skills for {root.name} started {model.now()}", flush=True)
        page = server.serve_in_background(root, args.port or service.preferred_port())
        port = page.server_address[1] if page else None
        if page is None:
            print("The Skills page could not start: no free port.", flush=True)
        nonce = service.announce(root, port)
        try:
            while True:  # the page is the only job; it reads on demand
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            if page:
                page.shutdown()
            service.forget(root, nonce)
        return 0
    if cmd == "start":
        try:
            pid = service.start(root)
        except RuntimeError as e:
            raise Refused(str(e)) from None
        url = service.page_url(root)
        data = {"running": True, "pid": pid, **({"url": url} if url else {})}
        return _emit(args, data, f"Skills is running: {url}" if url else f"Skills is running (pid {pid}).")
    if cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = str(e)
        if res in ("stopped", "not running"):
            return _emit(
                args,
                {"stopped": res == "stopped"},
                "Skills stopped." if res == "stopped" else "Skills was not running.",
            )
        note = (
            "A file in .orch/run/skills/ names a process that is not the Skills page; nothing was stopped."
            if res == "not verified"
            else res
        )
        return _emit(args, {"stopped": False, "note": note}, note)
    pid = service.running_pid(root)
    data = {"running": bool(pid), "pid": pid}
    url = service.page_url(root) if pid else None
    if url:
        data["url"] = url
    print(
        json.dumps(data)
        if args.json
        else (f"Skills is running (pid {pid})." if pid else "Skills is not running. Start it: orch start.")
    )
    return 0 if pid else 1


def run(args) -> int:
    root = _root(args.dir)
    if args.cmd == "list":
        data = model.build(root)
        return _emit(args, data, _list_text(data))
    if args.cmd == "history":
        rows = _history(root)
        text = "\n".join(
            f"{r.get('at')}  {r.get('name')}: {HISTORY_WORD.get(r.get('what'), r.get('what'))} "
            f"(by {str(r.get('who', '')).split(':', 1)[-1]})"
            for r in rows
        )
        return _emit(args, {"history": rows}, text or "No changes yet.")
    if args.cmd in ("on", "off"):
        return _turn(args, root, args.cmd == "on")
    if args.cmd == "bin":
        with skill_bin.locked(root):
            skill_bin.recover(root)
        rows = skill_bin.rows(root)
        return _emit(args, {"bin": rows}, _bin_text(rows))
    if args.cmd == "delete":
        return _delete(args, root)
    if args.cmd == "restore":
        return _restore(args, root)
    if args.cmd == "new":
        return _new(args, root)
    return _loop(args, root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orch skills")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true")
        return s

    p("list", help="everything helpers get here, with ids")
    p("history", help="who turned on, off, deleted, restored or made what")
    p("bin", help="deleted skills that can be restored")
    helps = {
        "on": "turn one item on in this workspace",
        "off": "turn one item off in this workspace",
        "delete": "move one workspace or computer skill to the bin",
        "restore": "put one bin entry back",
        "new": "make a draft skill in .agents/skills",
    }
    for name in VERBS:
        s = p(name, help=helps[name])
        s.add_argument("target", metavar="name" if name == "new" else "id")
        s.add_argument("--by")
    s = p("act", help=argparse.SUPPRESS)
    s.add_argument("verb")
    s.add_argument("target")
    s.add_argument("--by")
    s = p("run", help=argparse.SUPPRESS)
    s.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    for name in ("start", "stop", "status"):
        p(name)
    args = ap.parse_args(argv)
    args.json = bool(getattr(args, "json", False)) or "--json" in (argv if argv is not None else sys.argv)
    try:
        if args.cmd == "act":  # the page's clicks, run by the dashboard as the person
            if args.verb not in VERBS:
                raise Refused(f"Skills has no '{args.verb}' action.")
            ok = {"restore": skill_bin.BIN_TARGET, "new": re.compile(r"skill:workspace:[a-z0-9-]{1,64}")}
            if not ok.get(args.verb, TARGET).fullmatch(args.target or ""):
                raise Refused("That is not something Skills can change. Reload the page and try again.")
            args.cmd = args.verb
        return run(args)
    except Refused as e:
        return _fail(args, str(e))
