"""orch command line: argument parsing and plain-words output only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import (
    __version__,
    addons,
    cli_addons,
    cli_clients,
    cli_config,
    cli_needs,
    cli_run,
    cli_status,
    net,
    relay,
    services,
    tickets,
)
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


def _ago(iso: str) -> str:
    import datetime as dt

    try:
        secs = (
            dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ).total_seconds()
    except (ValueError, AttributeError):
        return "a while ago"
    return f"{int(secs // 3600)} h ago" if secs >= 3600 else f"{max(int(secs // 60), 1)} min ago"


def _check_line(root: Path | None, t: dict, c: dict, open_q: list[dict]) -> str:
    mark = "[x]" if c["done"] else "[ ]"
    line = f"  {mark} {c['text']}  [{c['id']}]"
    if c["done"] and c["evidence"]:
        line += f"  - proof: {c['evidence'][0]['ref']}"
    q = next((q for q in open_q if q.get("check") == c["id"]), None)
    if q:
        line += f"  - waiting for your answer ({q['id']})"
    if c.get("state") == "doing" and not c["done"] and root is not None:
        who = c.get("by", "someone")
        if tickets.doing_stale(root, t, c):
            line += f"  - {who} was on it ({_ago(c.get('at', ''))}, not running)"
        else:
            line += f"  - {who} is on it"
    return line


def _show(t: dict, root: Path | None = None) -> str:
    open_q = [q for q in t["questions"] if q["answer"] is None]
    head = f"{t['title']}  [{t['id']}]"
    out = [head]
    if t.get("summary"):
        out.append(t["summary"])
    out.append(f"Status: {t['status']}" + (f" - {_progress(t)}" if _progress(t) else ""))
    extra = [f"{k.capitalize()}: {t[k]}" for k in ("owner", "due") if t.get(k)]
    if extra:
        out.append("  ".join(extra))
    if t.get("note"):
        out.append(f"Note: {t['note']}")
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
        out += [_check_line(root, t, c, open_q) for c in t["checklist"]]
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


_PLACEHOLDERS = {"run", "needs", "agents", "config"}  # hidden until built
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

    x = sub.add_parser("init", parents=[common], help="set up this folder (safe to repeat)")
    x.add_argument("--yes", action="store_true", help="do not ask; take the first agent found")
    u = sub.add_parser("update", parents=[common], help="install the latest orch and the add-ons you use")
    u.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)

    cli_status.add_parsers(sub, common)
    cli_addons.add_parsers(sub, common)

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
    x.add_argument("--owner", help="who owns it (a name; empty clears)")
    x.add_argument("--due", metavar="YYYY-MM-DD", help="due day (empty clears)")
    x.add_argument("--note", help="a free note (empty clears)")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    x = t.add_parser("summary", parents=[common], help="where things stand, one or two sentences")
    x.add_argument("id")
    x.add_argument("text")
    x = t.add_parser("wait", parents=[common])
    x.add_argument("id")
    x.add_argument("--until")
    x.add_argument("--on", metavar="KIND:REF")
    x.add_argument("--clear", action="store_true", help="clear waiting_on")
    x = t.add_parser("patch", parents=[common])
    x.add_argument("id")
    x.add_argument(
        "data",
        help='JSON object: title, status, waiting_on, owner, due, note, summary, e.g. \'{"title": "New"}\'',
    )
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
    x = c.add_parser("edit", parents=[common], help="rename a task")
    x.add_argument("id")
    x.add_argument("check")
    x.add_argument("text")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    x.add_argument("--was", metavar="TEXT", help="refused when the task text is no longer this")
    x = c.add_parser("move", parents=[common], help="put a task after another")
    x.add_argument("id")
    x.add_argument("check")
    x.add_argument("--after", required=True, metavar="CID")
    for name, hlp in (
        ("remove", "remove a task (kept in the history)"),
        ("reopen", "open a done task again"),
        ("start", "mark a task as being worked on"),
        ("stop", "clear the working mark"),
    ):
        x = c.add_parser(name, parents=[common], help=hlp)
        x.add_argument("id")
        x.add_argument("check")
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
    x.add_argument("--kind", metavar="KIND", help="plain (default) or <add-on>:<name>")
    x.add_argument("--action", metavar="JSON", help="data for the add-on that acts on the answer")
    x.add_argument("--check", metavar="CID", help="the task this question belongs to")
    x = sub.add_parser("answer", parents=[common], help="answer a question")
    x.add_argument("id")
    x.add_argument("question")
    x.add_argument("answer")
    x.add_argument("--via", default="cli", metavar="WORD", help="where the answer comes from (default cli)")

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
    cli_run.add_parsers(sub, common)
    cli_needs.add_parsers(sub, common)
    cli_config.add_parsers(sub, common)
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
    top._choices_actions[:] = [
        a for a in top._choices_actions if a.dest not in addons.CORE_ADDONS and a.dest not in _PLACEHOLDERS
    ]
    return p


def _addon_note(root: Path, q: dict) -> str | None:
    """An answer to an add-on question is only recorded when that add-on is off or not running."""
    owner = str(q.get("kind", "plain")).partition(":")[0]
    if owner == "plain" or ":" not in str(q.get("kind", "")):
        return None
    if owner in addons.active(root) and any(
        e.get("addon") == owner and Path(e.get("workspace", "")) == root for e in services.running()
    ):
        return None
    return f"Recorded. The {owner} acts on it when it runs."


def run(args: argparse.Namespace) -> None:
    root = _find_root()
    by = lambda: tickets.current_actor(getattr(args, "by", None))  # noqa: E731
    cmd, sub = args.cmd, getattr(args, "sub", None)

    if cmd == "init":
        root = Path.cwd()
        lines = init_mod.init(root)
        asking = sys.stdin.isatty() and not args.json
        agent = init_mod.choose_agent(root, args.yes, asking)
        _out(
            args,
            {"ok": True, "root": str(root), "details": lines, "agent": agent},
            f"orch is ready in this folder. {agent}",
        )
    elif cmd == "update":
        done = addons.update(root, args.project_only)
        if args.project_only:
            _out(args, {"ok": True, "refreshed": done}, "Refreshed: " + ", ".join(done or ["nothing"]))
        elif not args.json:
            print("orch is up to date.")
    elif cli_status.dispatch(args, root) or cli_addons.dispatch(args, root):
        pass
    elif cli_run.dispatch(args, root) or cli_needs.dispatch(args, root) or cli_config.dispatch(args, root):
        pass
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
        _out(args, t, _show(t, root))
    elif cmd == "ticket" and sub == "status":
        t = tickets.set_status(root, args.id, args.status, by())
        _out(args, t, f"{t['title']} - {t['status']}")
    elif cmd == "ticket" and sub == "edit":
        fields = {k: getattr(args, k) for k in ("owner", "due", "note") if getattr(args, k) is not None}
        if args.title is None and not fields:
            raise Refused("Say what to change: --title, --owner, --due or --note.")
        t = tickets.edit(root, args.id, args.title, by(), fields, args.if_revision)
        _out(args, t, f"Saved (revision {t['revision']}).")
    elif cmd == "ticket" and sub == "summary":
        t = tickets.set_summary(root, args.id, args.text, by())
        _out(args, t, "Summary saved.")
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
    elif cmd == "check" and sub in ("edit", "move", "remove", "reopen", "start", "stop"):
        who = by()
        if sub == "edit":
            t, c = tickets.check_edit(root, args.id, args.check, args.text, who, args.if_revision, args.was)
            msg = f"{c['id']} renamed."
        elif sub == "move":
            t, c = tickets.check_move(root, args.id, args.check, args.after, who)
            msg = f"{c['id']} now follows {args.after}."
        elif sub == "remove":
            t, c = tickets.check_remove(root, args.id, args.check, who)
            msg = f"{c['id']} removed. It and its proof are kept in the history."
        elif sub == "reopen":
            t, c = tickets.check_reopen(root, args.id, args.check, who)
            msg = f"{c['id']} is open again. Its proof stays in the history."
        elif sub == "start":
            t, c = tickets.check_start(root, args.id, args.check, who)
            msg = f"{c['id']}: {who} is on it."
        else:
            t, c = tickets.check_stop(root, args.id, args.check, who)
            msg = f"{c['id']}: no longer marked as being worked on."
        _out(args, c, msg)
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
        t, q = tickets.ask(
            root, args.id, args.text, args.option, args.recommend, by(), args.kind, args.action, args.check
        )
        if args.phone:
            cli_clients.send_phone_question(root, t["id"], q)
        _out(
            args,
            q,
            f"Asked {q['id']}" + (f" on {q['check']}" if q.get("check") else "") + f", waiting. {t['title']} "
            "is now waiting for an answer.",
        )
    elif cmd == "answer":
        who = by()
        if who.startswith("agent:") and relay.asked_to_phones(root, args.id, args.question):
            raise Refused("This question was sent to the phones. Only a human answers it.")
        t, q = tickets.answer(root, args.id, args.question, args.answer, who, args.via)
        note = _addon_note(root, q)
        _out(args, q, f"Answered: {q['answer']}" + (f"\n{note}" if note else ""))
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
            print(json.dumps({"error": str(e), **getattr(e, "extra", {})}, ensure_ascii=False))
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
        cli_run.after_command(args, root, want_json)
    except Refused as e:
        return refuse(e)
    return 0
