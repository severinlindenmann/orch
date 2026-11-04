"""orch command line: argument parsing and plain-words output only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import __version__, addons, cli_clients, net, relay, tickets
from orch import init as init_mod
from orch.errors import Refused


def _find_root() -> Path:
    """The workspace root: nearest folder upwards with .orch/ or .agents/, else the current folder."""
    cwd = Path.cwd()
    for p in (cwd, *cwd.parents):
        if (p / ".orch").is_dir() or (p / ".agents").is_dir():
            return p
    return cwd


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _tid(t: dict) -> str:
    return t["id"]


def _progress(t: dict) -> str:
    d, n = tickets.checks_done(t)
    return f"{d} of {n} done" if n else ""


def _line(t: dict) -> str:
    bits = [t["status"]] + ([_progress(t)] if _progress(t) else [])
    return f"{t['title']}  ({', '.join(bits)})  [{t['id']}]"


def _show(t: dict) -> str:
    open_q = [q for q in t["questions"] if q["answer"] is None]
    head = f"{t['title']}  [{t['id']}]"
    out = [head, f"Status: {t['status']}" + (f" - {_progress(t)}" if _progress(t) else "")]
    if t.get("wake_at"):
        out.append(f"Wakes up: {net.when(t['wake_at'])}")
    if t.get("waiting_on"):
        w = t["waiting_on"]
        out.append("Waiting for: " + ("an answer" if w["kind"] == "question" else f"{w['kind']} {w['ref']}"))
    if open_q:
        out.append("\nNeeds an answer:")
        for q in open_q:
            opts = f" ({' / '.join(q['options'])})" if q["options"] else ""
            rec = f" - suggested: {q['recommended']}" if q["recommended"] else ""
            out.append(f"  {q['text']}{opts}{rec}  [{q['id']}]")
    if t["checklist"]:
        out.append("\nChecklist:")
        for c in t["checklist"]:
            if c["done"]:
                ev = c["evidence"][0]
                out.append(f"  [x] {c['text']}  [{c['id']}]  - proof: {ev['ref']}")
            else:
                out.append(f"  [ ] {c['text']}  [{c['id']}]")
    answered = [q for q in t["questions"] if q["answer"] is not None]
    if answered:
        out.append("\nAnswered:")
        for q in answered:
            out.append(f"  {q['text']} - {q['answer']} ({q['answered_by']})")
    if t["links"]:
        out.append("\nLinks:")
        out += [f"  {ln.get('title') or ln['type']}: {ln['url']}" for ln in t["links"]]
    if t["history"]:
        out.append("\nRecent:")
        out += [f"  {net.when(h['at'])}  {h['by']}: {h['text']}" for h in t["history"][-3:]]
    return "\n".join(out)


ADVANCED_TOP = {"update", "wait", "log", "answer", "link", "ext"}
ADVANCED_SUB = {
    "relay": {"done", "delegate", "start", "allow", "download", "webhook"},
    "publish": {"restart", "stop", "delete"},
}


def _hide_advanced(parser: argparse.ArgumentParser) -> None:
    """Help lists the everyday commands; `orch --help-all` (or `orch <cmd> --help-all`) lists the rest."""

    def hide(sp, names):
        sp._choices_actions[:] = [a for a in sp._choices_actions if a.dest not in names]

    top = parser._subparsers._group_actions[0]
    hide(top, ADVANCED_TOP)
    for name, names in ADVANCED_SUB.items():
        for a in top.choices[name]._subparsers._group_actions:
            a.metavar = "<command>"
            hide(a, names)


def build_parser(show_all: bool = False) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--by", help="actor, agent:<tool> or human:<name> (default: detected)")

    p = argparse.ArgumentParser(prog="orch", description="orch: tickets with evidence for any agent tool")
    p.add_argument("--version", action="version", version=f"orch {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("init", parents=[common], help="set up this folder (safe to repeat)")
    u = sub.add_parser("update", parents=[common], help="install the latest orch and add-ons")
    u.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)

    a = sub.add_parser("addon", help="add-ons: dashboard, scheduler").add_subparsers(
        dest="sub", required=True
    )
    for n in ("add", "remove"):
        x = a.add_parser(n, parents=[common])
        x.add_argument("name")
        if n == "add":
            x.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)
    a.add_parser("list", parents=[common])

    t = sub.add_parser("ticket", help="tickets").add_subparsers(dest="sub", required=True)
    x = t.add_parser("new", parents=[common])
    x.add_argument("title")
    x.add_argument("--recurring", metavar="CRON", help="5-field cron, UTC")
    x = t.add_parser("list", parents=[common])
    x.add_argument("--status", choices=tickets.STATUSES)
    x.add_argument("--all", action="store_true", help="include done and dropped tickets")
    x = t.add_parser("show", parents=[common])
    x.add_argument("id")
    x = t.add_parser("status", parents=[common])
    x.add_argument("id")
    x.add_argument("status", choices=tickets.STATUSES)
    x = t.add_parser("edit", parents=[common])
    x.add_argument("id")
    x.add_argument("--title")
    x = t.add_parser("wait", parents=[common])
    x.add_argument("id")
    x.add_argument("--until")
    x.add_argument("--on", metavar="KIND:REF")
    x.add_argument("--clear", action="store_true", help="clear wake_at and waiting_on")

    x = sub.add_parser("wait", parents=[common], help="same as: ticket wait")
    x.add_argument("id")
    x.add_argument("--until")
    x.add_argument("--on", metavar="KIND:REF")
    x.add_argument("--clear", action="store_true", help="clear wake_at and waiting_on")

    c = sub.add_parser("check", help="checklist").add_subparsers(dest="sub", required=True)
    x = c.add_parser("add", parents=[common])
    x.add_argument("id")
    x.add_argument("text")
    x = c.add_parser("done", parents=[common])
    x.add_argument("id")
    x.add_argument("check")
    x.add_argument("--evidence", action="append", default=[], metavar="JSON", help=argparse.SUPPRESS)
    for k in ("command", "note", "pr", "commit", "file", "url"):
        x.add_argument(f"--{k}", metavar="TEXT", help=f"proof: a {k}")

    x = sub.add_parser("log", parents=[common], help="add a history entry")
    x.add_argument("id")
    x.add_argument("text")

    x = sub.add_parser("ask", parents=[common], help="ask a question and wait for the answer")
    x.add_argument("id")
    x.add_argument("text")
    x.add_argument("--option", action="append", default=[])
    x.add_argument("--recommend", "--recommended", dest="recommend")
    x.add_argument("--phone", action="store_true", help="also send the question to the phones via relay")
    x = sub.add_parser("answer", parents=[common], help="answer a question")
    x.add_argument("id")
    x.add_argument("question")
    x.add_argument("answer")
    x.add_argument("--via", choices=("cli", "phone", "relay"), default="cli")

    lk = sub.add_parser("link", help="links").add_subparsers(dest="sub", required=True)
    x = lk.add_parser("add", parents=[common])
    x.add_argument("id")
    x.add_argument("--type", required=True)
    x.add_argument("--url", required=True)
    x.add_argument("--title")

    e = sub.add_parser("ext", help="add-on data on a ticket").add_subparsers(dest="sub", required=True)
    x = e.add_parser("set", parents=[common])
    x.add_argument("id")
    x.add_argument("addon")
    x.add_argument("data", help="JSON object")
    cli_clients.add_parsers(sub, common)
    if not show_all:
        _hide_advanced(p)
        p.epilog = "More commands: orch --help-all"
    return p


def run(args: argparse.Namespace) -> None:
    root = _find_root()
    by = lambda: tickets.current_actor(getattr(args, "by", None))  # noqa: E731
    cmd, sub = args.cmd, getattr(args, "sub", None)

    if cmd == "init":
        root = Path.cwd()
        lines = init_mod.init(root)
        _out(args, {"ok": True, "root": str(root), "details": lines}, "orch is ready in this folder.")
    elif cmd == "update":
        done = addons.update(root, args.project_only)
        if args.project_only:
            _out(args, {"ok": True, "refreshed": done}, "Refreshed: " + ", ".join(done or ["nothing"]))
        elif not args.json:
            print("orch is up to date.")
    elif cmd == "addon":
        if sub == "list":
            inst = addons.project_addons(root)
            data = {n: ("installed" if n in inst else "not installed") for n in addons.KNOWN}
            _out(
                args,
                data,
                "\n".join(
                    f"{n:<10} " + ("on" if s == "installed" else f"off (turn on: orch addon add {n})")
                    for n, s in data.items()
                ),
            )
        elif sub == "add":
            addons.add(root, args.name, args.project_only)
            if args.project_only:
                _out(args, {"ok": True}, f"{args.name} is added to this project.")
        else:
            addons.remove(root, args.name)
            _out(args, {"ok": True}, f"{args.name} is removed from this project.")
    elif cmd == "ticket" and sub == "new":
        t = tickets.create(root, args.title, by(), args.recurring)
        _out(args, t, f'Created "{t["title"]}" [{t["id"]}]')
    elif cmd == "ticket" and sub == "list":
        ts = [
            t
            for t in tickets.list_all(root)
            if (
                t["status"] == args.status
                if args.status
                else args.all or t["status"] not in ("done", "dropped")
            )
        ]
        hidden = (
            0
            if args.status or args.all
            else sum(1 for t in tickets.list_all(root) if t["status"] in ("done", "dropped"))
        )
        txt = "\n".join(_line(t) for t in ts) or 'No open tickets. Create one with: orch ticket new "<title>"'
        if hidden and not args.json:
            txt += f"\n({hidden} finished - show them with: orch ticket list --all)"
        _out(args, ts, txt)
    elif cmd == "ticket" and sub == "show":
        t = tickets.load(root, args.id)
        _out(args, t, _show(t))
    elif cmd == "ticket" and sub == "status":
        t = tickets.set_status(root, args.id, args.status, by())
        _out(args, t, f"{t['title']} - {t['status']}")
    elif cmd == "ticket" and sub == "edit":
        t = tickets.edit(root, args.id, args.title, by())
        _out(args, t, f"Renamed to: {t['title']}")
    elif (cmd == "ticket" and sub == "wait") or cmd == "wait":
        t = tickets.wait(root, args.id, args.until, args.on, by(), args.clear)
        _out(
            args,
            t,
            f"{t['id']} wait cleared"
            if args.clear
            else f"{t['id']} is waiting" + (f" until {t['wake_at']}" if args.until else f" on {args.on}"),
        )
    elif cmd == "check" and sub == "add":
        t, c = tickets.check_add(root, args.id, args.text, by())
        _out(args, c, f"Added to the checklist: {c['text']}  [{c['id']}]")
    elif cmd == "check":
        shorthand = [
            json.dumps({"type": k, "ref": getattr(args, k)})
            for k in ("command", "note", "pr", "commit", "file", "url")
            if getattr(args, k)
        ]
        t, c = tickets.check_done(root, args.id, args.check, args.evidence + shorthand, by())
        ev = c["evidence"][-1]
        _out(args, c, f"Done: {c['text']} (proof: {ev['ref']})")
    elif cmd == "log":
        t = tickets.log(root, args.id, args.text, by())
        h = t["history"][-1]
        _out(args, h, f"{h['at']} {h['by']}: {h['text']}")
    elif cmd == "ask":
        t, q = tickets.ask(root, args.id, args.text, args.option, args.recommend, by())
        if args.phone:
            cli_clients.send_phone_question(root, t["id"], q)
        _out(args, q, f"Question asked. {t['title']} is now waiting for an answer.")
    elif cmd == "answer":
        who = by()
        if who.startswith("agent:") and relay.asked_to_phones(root, args.id, args.question):
            raise Refused("This question was sent to the phones. Only a human answers it.")
        t, q = tickets.answer(root, args.id, args.question, args.answer, who, args.via)
        _out(args, q, f"Answered: {q['answer']}")
    elif cmd == "link":
        t = tickets.link_add(root, args.id, args.type, args.url, args.title, by())
        _out(args, t["links"][-1], f"Linked {args.title or args.type}: {args.url}")
    elif cmd == "publish":
        cli_clients.run_publish(args, root, _out)
    elif cmd == "relay":
        cli_clients.run_relay(args, root, _out)
    elif cmd == "ext":
        t = tickets.ext_set(root, args.id, args.addon, args.data, by())
        _out(args, t["ext"][args.addon], f"ext.{args.addon} set on {t['id']}")


def _addon_command(name: str):
    """An installed add-on registers `<name> = module:function` in the entry-point group orch.addons."""
    from importlib.metadata import entry_points

    return next(iter(entry_points(group="orch.addons", name=name)), None)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else list(argv)
    show_all = "--help-all" in argv
    argv = ["--help" if a == "--help-all" else a for a in argv]
    parser = build_parser(show_all)
    if argv and not argv[0].startswith("-") and argv[0] not in parser._subparsers._group_actions[0].choices:
        ep = _addon_command(argv[0])
        if ep is not None:
            return int(ep.load()(argv[1:]) or 0)
    args = parser.parse_args(argv)
    try:
        run(args)
    except Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    return 0
