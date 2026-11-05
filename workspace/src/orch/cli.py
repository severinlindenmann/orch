"""orch command line: argument parsing and plain-words output only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import __version__, addons, cli_clients, net, relay, services, tickets
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
    if t.get("waiting_on"):
        w = t["waiting_on"]
        if w["kind"] == "time":
            out.append(f"Waiting until: {net.when(w['until'])}")
        else:
            out.append(
                "Waiting for: " + ("an answer" if w["kind"] == "question" else f"{w['kind']} {w['ref']}")
            )
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


CORE_EXT = {"relay"}  # ext keys the core itself writes (relay-created tickets)


def _visible(root: Path, t: dict) -> dict:
    """Ticket data as the CLI shows it: ext keys of add-ons that are not on stay in the file, hidden."""
    ext = t.get("ext")
    if not ext:
        return t
    on = set(addons.active(root)) | CORE_EXT
    return {**t, "ext": {k: v for k, v in ext.items() if k in on}}


ADVANCED_TOP = {"update", "wait", "log", "answer", "link", "ext"}
ADVANCED_SUB = {
    "relay": {"done", "delegate", "start", "allow", "download", "webhook"},
    "publish": {"restart", "stop", "delete"},
}


_EXAMPLES = {
    "orch ticket new": 'A ticket needs a title, for example: orch ticket new "Fix the login"',
    "orch check add": 'A checklist item needs a ticket and text, e.g.: orch check add t_abc "Write the test"',
    "orch check done": 'Say which ticket and item, for example: orch check done t_abc c1 --command "pytest"',
    "orch ticket show": "Say which ticket, for example: orch ticket show t_abc. List them: orch ticket list",
    "orch relay send": 'Say who and what, for example: orch relay send "Design" "The report is ready"',
}


class _Parser(argparse.ArgumentParser):
    """Plain-words usage errors instead of argparse's own text."""

    def error(self, message):
        import re

        m = re.search(r"invalid choice: '([^']*)'", message)
        if m:
            what = self.prog + " command" if self.prog != "orch" else "orch command"
            self.exit(2, f'"{m.group(1)}" is not an {what}. Run {self.prog} --help.\n')
        if self.prog in _EXAMPLES:
            self.exit(2, _EXAMPLES[self.prog] + "\n")
        m = re.search(r"required: (.*)", message)
        if m:
            usage = self.format_usage().replace("usage: ", "").strip()
            self.exit(2, f"Missing {m.group(1)}. Usage: {usage}\nMore help: {self.prog} --help\n")
        self.exit(2, f"{message}. Run {self.prog} --help.\n")


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


def build_parser(show_all: bool = False, addon_lines: list[str] | None = None) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--by", help="actor, agent:<tool> or human:<name> (default: detected)")

    p = _Parser(prog="orch", description="orch: tickets with evidence for any agent tool")
    p.add_argument("--version", action="version", version=f"orch {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("init", parents=[common], help="set up this folder (safe to repeat)")
    u = sub.add_parser("update", parents=[common], help="install the latest orch and the add-ons you use")
    u.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)

    x = sub.add_parser("start", parents=[common], help="start the add-ons that run in the background here")
    x.add_argument("--no-open", action="store_true", help="do not open the dashboard in the browser")
    x = sub.add_parser(
        "stop", parents=[common], help="stop them (asks which workspace when you are outside one)"
    )
    x.add_argument("workspace", nargs="?", metavar="PATH|NAME", help="the workspace to stop")
    x.add_argument("--all", action="store_true", help="stop every running workspace")
    x.add_argument("--pick", action="store_true", help="choose from the running workspaces")
    sub.add_parser("status", parents=[common], help="what runs in the background, and where")

    a = sub.add_parser("addon", help="add-ons: add, remove, list").add_subparsers(dest="sub", required=True)
    x = a.add_parser("add", parents=[common], help="install an add-on and turn it on here")
    x.add_argument("name", metavar="NAME|./FOLDER", help="a built-in add-on name or a local folder")
    x.add_argument("--yes", action="store_true", help="do not ask")
    x.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)
    x = a.add_parser("remove", parents=[common], help="turn an add-on off in this workspace")
    x.add_argument("name")
    x.add_argument("--purge", action="store_true", help="also delete its data folder and settings")
    x = a.add_parser("uninstall", parents=[common], help="remove an add-on from this computer")
    x.add_argument("name")
    a.add_parser("list", parents=[common])

    t = sub.add_parser("ticket", help="tickets").add_subparsers(dest="sub", required=True)
    x = t.add_parser("new", parents=[common])
    x.add_argument("title")
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
    x.add_argument("--clear", action="store_true", help="clear waiting_on")
    x = t.add_parser("patch", parents=[common])
    x.add_argument("id")
    x.add_argument("data", help='JSON object: title, status, waiting_on, e.g. \'{"title": "New"}\'')
    x.add_argument("--if-revision", type=int, required=True, metavar="N")

    x = sub.add_parser("wait", parents=[common], help="same as: ticket wait")
    x.add_argument("id")
    x.add_argument("--until")
    x.add_argument("--on", metavar="KIND:REF")
    x.add_argument("--clear", action="store_true", help="clear waiting_on")

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
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    cli_clients.add_parsers(sub, common)
    p.formatter_class = argparse.RawDescriptionHelpFormatter
    notes = []
    if addon_lines:
        notes.append("Add-ons:\n" + "\n".join(addon_lines))
    if not show_all:
        _hide_advanced(p)
        notes.append("More commands: orch --help-all")
    p.epilog = "\n\n".join(notes) or None
    # publish and relay are built-in add-ons: listed under "Add-ons" only when on (never as core commands)
    top = p._subparsers._group_actions[0]
    top._choices_actions[:] = [a for a in top._choices_actions if a.dest not in addons.CORE_ADDONS]
    return p


def _home_path(p: str) -> str:
    try:
        return "~/" + Path(p).relative_to(Path.home()).as_posix()
    except ValueError:
        return p


def _service_line(r: dict) -> str:
    if r.get("error"):
        return f"  {r['addon']:<12}did not start: {r['error']}"
    url = services.local_url(r.get("url"))
    return f"  {r['addon']:<12}" + (url or f"running (pid {r.get('pid')})")


def _pick(running: list[dict]) -> list[Path]:
    if not running:
        return []
    if not sys.stdin.isatty():
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
        if url and not args.no_open and not args.json and sys.stdout.isatty():
            import webbrowser

            webbrowser.open(url)
        bad = [r for r in rows if r.get("error")]
        if bad:
            raise Refused(", ".join(r["addon"] for r in bad) + " did not start (see above).")
    elif args.cmd == "status":
        ws = services.status()
        lines = []
        for w in ws:
            lines.append(f"{w['name']}  ({_home_path(w['workspace'])})")
            lines += [_service_line(a) for a in w["addons"]]
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
    elif cmd in ("start", "stop", "status"):
        _services_cmd(args, root)
    elif cmd == "addon":
        if sub == "list":
            rows = addons.listing(root)
            _out(
                args,
                rows,
                "\n".join(
                    f"{r['name']:<12}{'on ' if r['active'] else 'off'}  {r['description']}"
                    + ("" if r["active"] else f"  (turn on: orch addon add {r['name']})")
                    for r in rows
                )
                or "No add-ons are installed. Turn one on with: orch addon add <name>",
            )
        elif sub == "add":
            addons.add(root, args.name, args.yes, args.project_only)
            if args.project_only:
                _out(args, {"ok": True}, f"{args.name} is turned on in this workspace.")
        elif sub == "remove":
            addons.remove(root, args.name, args.purge)
            _out(args, {"ok": True}, f"{args.name} is turned off in this workspace.")
        else:
            addons.uninstall(root, args.name)
            _out(args, {"ok": True}, f"{args.name} is removed from this computer.")
    elif cmd == "ticket" and sub == "new":
        t = tickets.create(root, args.title, by())
        _out(
            args,
            t,
            f'Created "{t["title"]}" [{t["id"]}]\n'
            f'Next: add one checklist item per step: orch check add {t["id"]} "<step>"',
        )
    elif cmd == "ticket" and sub == "list":
        all_ = [_visible(root, t) for t in tickets.list_all(root)]
        ts = [
            t
            for t in all_
            if (
                t["status"] == args.status
                if args.status
                else args.all or t["status"] not in ("done", "dropped")
            )
        ]
        hidden = 0 if args.status or args.all else sum(1 for t in all_ if t["status"] in ("done", "dropped"))
        txt = "\n".join(_line(t) for t in ts) or 'No open tickets. Create one with: orch ticket new "<title>"'
        if hidden and not args.json:
            txt += f"\n({hidden} finished - show them with: orch ticket list --all)"
        _out(args, ts, txt)
    elif cmd == "ticket" and sub == "show":
        t = _visible(root, tickets.load(root, args.id))
        _out(args, t, _show(t))
    elif cmd == "ticket" and sub == "status":
        t = tickets.set_status(root, args.id, args.status, by())
        _out(args, t, f"{t['title']} - {t['status']}")
    elif cmd == "ticket" and sub == "edit":
        t = tickets.edit(root, args.id, args.title, by())
        _out(args, t, f"Renamed to: {t['title']}")
    elif cmd == "ticket" and sub == "patch":
        t = tickets.patch(root, args.id, args.if_revision, args.data, by())
        _out(args, t, f"{t['id']} changed (revision {t['revision']})")
    elif (cmd == "ticket" and sub == "wait") or cmd == "wait":
        t = tickets.wait(root, args.id, args.until, args.on, by(), args.clear)
        _out(
            args,
            t,
            f"{t['id']} wait cleared"
            if args.clear
            else f"{t['id']} is waiting"
            + (f" until {t['waiting_on']['until']}" if args.until else f" on {args.on}"),
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
        if args.phone and "relay" not in addons.active(root):
            raise Refused(addons.not_on_message(root, "relay"))
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
        t = tickets.ext_set(
            root,
            args.id,
            args.addon,
            args.data,
            by(),
            args.if_revision,
            addons.active_ext_schema(root, args.addon),
        )
        _out(args, t["ext"][args.addon], f"ext.{args.addon} set on {t['id']}")


def main(argv: list[str] | None = None) -> int:
    for s_ in (sys.stdout, sys.stderr):
        if hasattr(s_, "reconfigure"):
            s_.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else list(argv)
    show_all = "--help-all" in argv
    argv = ["--help" if a == "--help-all" else a for a in argv]
    root = _find_root()
    want_json = "--json" in argv

    def refuse(e: Refused) -> int:
        print(f"Refused: {e}", file=sys.stderr)
        if want_json:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2

    try:
        lines = addons.help_lines(root) if ("-h" in argv or "--help" in argv or not argv) else None
        parser = build_parser(show_all, lines)
        if argv and argv[0] in addons.CORE_ADDONS and argv[0] not in addons.active(root):
            raise Refused(addons.not_on_message(root, argv[0]))  # built-in add-on that is off: no command
        if (
            argv
            and not argv[0].startswith("-")
            and argv[0] not in parser._subparsers._group_actions[0].choices
        ):
            if argv[0] in addons.active(root) or argv[0] in addons.discover():
                return addons.dispatch(root, argv[0], argv[1:])
        args = parser.parse_args(argv)
        run(args)
    except Refused as e:
        return refuse(e)
    return 0
