"""orch command line: argument parsing and plain-words output only."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

from orch import (
    __version__,
    addons,
    cli_addons,
    cli_chat,
    cli_clients,
    cli_config,
    cli_look,
    cli_needs,
    cli_run,
    cli_status,
    fields,
    mobile_mode,
    net,
    refs,
    relay,
    runs_live,
    services,
    term,
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
    bits = [tickets.STATUS_WORDS[t["status"]]] + ([_progress(t)] if _progress(t) else [])
    return (f"{t['key']}  " if t.get("key") else "") + f"{t['title']}  ({', '.join(bits)})  [{t['id']}]"


def _ago(iso: str) -> str:
    import datetime as dt

    try:
        secs = (
            dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ).total_seconds()
    except (ValueError, AttributeError):
        return "a while ago"
    return f"{int(secs // 3600)} h ago" if secs >= 3600 else f"{max(int(secs // 60), 1)} min ago"


def _short(ev: dict) -> str:
    t, ref = ev.get("type"), str(ev.get("ref", ""))
    if t == "commit":
        return ref[:7]
    if t == "command":
        return f"{ref} · {ev['text']}" if ev.get("text") else ref
    if t == "file" or ev.get("title"):
        return tickets.proof_label(ev)
    return ref if len(ref) <= 80 else ref[:77] + "..."


def _chip(root: Path | None, ev: dict) -> str:
    text = _short(ev)
    if ev.get("type") == "file" and root is not None and not tickets.proof_present(root, ev):
        text = (ev.get("title") or tickets.proof_label({**ev, "text": ""})) + " (file on another computer)"
    elif ev.get("type") == "file" and ev.get("text") and ev.get("title"):
        text = f"{ev['title']} (file, {ev['text']})"
    return text


def _who_added(t: dict, c: dict, ev: dict) -> str:
    by = ev.get("by")
    if not by:
        line = next((h for h in reversed(t["history"]) if h["text"] == f"Check {c['id']} done"), None)
        by = line["by"] if line else ""
    return "● You" if by.startswith("human:") else "○ Agent says"


def _check_lines(root: Path | None, t: dict, c: dict, open_q: list[dict]) -> list[str]:
    q = next((q for q in open_q if q.get("check") == c["id"]), None)
    mark = "✓" if c["done"] else ("◐" if c.get("state") == "doing" else "○")
    line = f"  {mark} {c['id']} {c['text']}"
    if q and not c["done"]:
        line += f"   waiting for your answer ({q['id']})"
    if c.get("state") == "doing" and not c["done"] and root is not None:
        who = c.get("by", "someone")
        if tickets.doing_stale(root, t, c):
            line += f"   {who} was on it ({_ago(c.get('at', ''))}, not running)"
        else:
            line += f"   {who} is on it"
    out = [line]
    for ev in c.get("evidence", []):
        role = f"{ev['role']:<7} " if ev.get("role") else ""
        out.append(f"       {role}{_chip(root, ev)}   {_who_added(t, c, ev)}")
    return out


def _lookup(root: Path | None, tid: str) -> dict | None:
    if root is None:
        return None
    try:
        return tickets.load(root, tid)
    except (Refused, ValueError, OSError):
        return None


def _show(t: dict, root: Path | None = None) -> str:
    open_q = [q for q in t["questions"] if q["answer"] is None]
    head = (f"{t['key']}  " if t.get("key") else "") + f"{t['title']}  [{t['id']}]"
    out = [head]
    if t.get("summary"):
        out.append(t["summary"])
    d, n = tickets.checks_done(t)
    out.append(
        f"Status: {tickets.STATUS_WORDS[t['status']]}" + (f" - {_progress(t)}" if _progress(t) else "")
    )
    if n and d == n:
        out.append(f"✓ All done · {n} of {n}")
    extra = [f"{k.capitalize()}: {t[k]}" for k in ("owner", "due") if t.get(k)]
    if extra:
        out.append("  ".join(extra))
    if t.get("note"):
        out.append(f"Note: {t['note']}")
    if t.get("done_when"):
        out.append(f"Done when: {t['done_when']}")
    if t.get("parent"):
        p = _lookup(root, t["parent"])
        out.append(f"Step of: {p['title']} ({p['id']})" if p else f"Step of: {t['parent']} (parent missing)")
    if root is not None:
        cc = tickets.children_counts(tickets.list_all(root), t["id"])
        if cc["total"]:
            out.append(f"Sub-tickets: {cc['closed']} of {cc['total']} closed")
    if t.get("waiting_on"):
        w = t["waiting_on"]
        if w["kind"] == "time":
            out.append(f"Waiting until: {net.when(w['until'])}")
        elif w["kind"] == "ticket":
            b = _lookup(root, w["ref"])
            out.append(
                f"Blocked by: {b['title']} ({b['id']}, {tickets.STATUS_WORDS[b['status']]})"
                if b
                else f"Blocked by: {w['ref']}"
            )
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
            out += _check_lines(root, t, c, open_q)
    answered = [q for q in t["questions"] if q["answer"] is not None]
    if answered:
        out.append("\nAnswered:")
        for q in answered:
            out.append(f"  {q['text']} - {q['answer']} ({q['answered_by']})")
    rows = refs.all_refs(root, t)
    if rows:
        kinds = refs.active_kinds(root)
        out.append("\nReferences:")
        for n, ln in rows:
            d = refs.describe(ln, kinds, root)
            st = f" ({d['status']})" if d["status"] else ""
            out.append(f"  {n}  {d['type']}: {d['title']}{st}  {refs.one_line(refs.target(ln), 300)}")
    if t["history"]:
        out.append("\nRecent:")
        out += [
            f"  {net.when(h['at'])}  {h['by']}: {tickets.history_line(h['text'], t['checklist'])}"
            for h in t["history"][-3:]
        ]
    return "\n".join(out)


def _tree(all_: list[dict], t: dict, prefix: str = "", seen: frozenset = frozenset()) -> list[str]:
    kids = tickets.children_of(all_, t["id"])
    out = []
    for i, k in enumerate(kids):
        last = i == len(kids) - 1
        closed = k["status"] in tickets.CLOSED
        mark = "✓" if closed else ("○" if k["status"] in ("open", "ready") else "◐")
        state = ""
        if not closed:
            asks = any(q["answer"] is None for q in k["questions"])
            state = "   " + (
                "waiting for your answer"
                if k["status"] == "waiting" and asks
                else tickets.STATUS_WORDS[k["status"]]
            )
        out.append(f"{prefix}{'└─' if last else '├─'} {mark} {k['title']}{state}")
        if k["id"] not in seen:
            out += _tree(all_, k, prefix + ("   " if last else "│  "), seen | {t["id"]})
    return out


CORE_EXT = {"relay"}  # ext keys the core itself writes (relay-created tickets)


def _visible(root: Path, t: dict) -> dict:
    """Ticket data as the CLI shows it: ext keys of add-ons that are not on stay in the file, hidden."""
    ext = t.get("ext")
    if not ext:
        return t
    on = set(addons.active(root)) | CORE_EXT
    return {**t, "ext": {k: v for k, v in ext.items() if k in on}}


_PLACEHOLDERS = {"run", "agents", "config", "share", "chat", "private"}  # hidden until built
ADVANCED_TOP = {"update", "wait", "log", "answer", "ref", "ext"}
ADVANCED_SUB = {"relay": {"allow"}}


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
    x.add_argument("--recommended", action="store_true", help="also turn on the recommended add-ons")
    x.add_argument("--code", help="code for ticket keys, e.g. MEC gives MEC-1 (default: from the folder)")
    u = sub.add_parser("update", parents=[common], help="install the latest orch and the add-ons you use")
    u.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)
    u.add_argument("--update-nonce", help=argparse.SUPPRESS)
    u.add_argument("--after-install", action="store_true", help=argparse.SUPPRESS)

    cli_status.add_parsers(sub, common)
    cli_addons.add_parsers(sub, common)

    t = sub.add_parser("ticket", help="tickets").add_subparsers(dest="sub", required=True)
    x = t.add_parser("new", parents=[common])
    x.add_argument("title")
    x.add_argument("--parent", metavar="ID", help="make it a sub-ticket of this ticket")
    x.add_argument("--owner", help="who owns it (a name)")
    x.add_argument("--due", metavar="YYYY-MM-DD", help="due day")
    x.add_argument("--note", help="a free note")
    x.add_argument("--done-when", help="what should be true when it is done")
    x.add_argument(
        "--title-auto", action="store_true", help="the title is a placeholder; the agent writes it"
    )
    x.add_argument(
        "--ext",
        action="append",
        default=[],
        metavar="ADDON=JSON",
        help="add-on data, written with the ticket",
    )
    x = t.add_parser("tree", parents=[common], help="a ticket and its sub-tickets")
    x.add_argument("id")
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
    x.add_argument("--done-when", help="what should be true when it is done (empty clears)")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    x = t.add_parser("set", parents=[common], help="set an add-on field, e.g. marketing.budget 2400")
    x.add_argument("id")
    x.add_argument("field", metavar="ADDON.FIELD")
    x.add_argument("value", help="the new value (empty clears it)")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    x = t.add_parser("summary", parents=[common], help="where things stand, one or two sentences")
    x.add_argument("id")
    x.add_argument("text")
    x = t.add_parser("artifacts", parents=[common], help="the files this ticket produced")
    x.add_argument("id")
    x = t.add_parser(
        "title", parents=[common], help="write the real title (and description) of a placeholder ticket"
    )
    x.add_argument("id")
    x.add_argument("title")
    x.add_argument(
        "--description", help="what it is about, 1 to 3 sentences (shown as the agent's description)"
    )
    x = t.add_parser(
        "attach", parents=[common], help="keep a text file or picture (read from stdin) with the ticket"
    )
    x.add_argument("id")
    x.add_argument("--name", required=True, help="a name hint; orch picks the final name")
    x = t.add_parser("artifacts-dir", parents=[common], help="the folder for this ticket's output files")
    x.add_argument("id")
    x = t.add_parser("wait", parents=[common])
    x.add_argument("id")
    x.add_argument("--until")
    x.add_argument("--on", metavar="KIND:REF")
    x.add_argument("--clear", action="store_true", help="clear waiting_on")
    x = t.add_parser("changes", parents=[common], help="send a ticket in Review back with a note (a person)")
    x.add_argument("id")
    x.add_argument("text")
    x = t.add_parser("patch", parents=[common])
    x.add_argument("id")
    x.add_argument(
        "data",
        help='JSON object: status, waiting_on, owner, due, note, done_when, e.g. \'{"title": "New"}\'',
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
    x.add_argument("--title", help="short name of the proof")
    x.add_argument("--role", help="result, check or support")
    x.add_argument("--summary", help="one line: what came out of this step (shown on the task)")

    x = sub.add_parser("log", parents=[common], help="add a history entry")
    x.add_argument("id")
    x.add_argument("text")

    x = sub.add_parser("ask", parents=[common], help="ask a question and wait for the answer")
    x.add_argument("id")
    x.add_argument("text")
    x.add_argument("--option", action="append", default=[])
    x.add_argument("--recommend", "--recommended", dest="recommend")
    x.add_argument("--phone", action="store_true", help="also send the question to the phones via relay")
    x.add_argument(
        "--preview",
        action="append",
        default=[],
        metavar="OPTION=ID",
        help="with --phone: show an attachment next to an option",
    )
    x.add_argument("--scope", help='with --phone, options Once/Always/No: what "Always" covers')
    x.add_argument("--kind", metavar="KIND", help="plain (default) or <add-on>:<name>")
    x.add_argument("--action", metavar="JSON", help="data for the add-on that acts on the answer")
    x.add_argument("--check", metavar="CID", help="the task this question belongs to")
    x = sub.add_parser("answer", parents=[common], help="answer a question")
    x.add_argument("id")
    x.add_argument("question")
    x.add_argument("answer")
    x.add_argument("--via", default="cli", metavar="WORD", help="where the answer comes from (default cli)")

    lk = sub.add_parser("ref", help="references to useful work").add_subparsers(dest="sub", required=True)
    x = lk.add_parser("add", parents=[common], help="add a reference to a ticket")
    x.add_argument("id")
    x.add_argument("target")
    x.add_argument("--kind")
    x.add_argument("--title")
    x = lk.add_parser("list", parents=[common], help="the ticket's references, numbered")
    x.add_argument("id")
    x = lk.add_parser("rm", parents=[common], help="remove a reference")
    x.add_argument("id")
    x.add_argument("target")

    e = sub.add_parser("ext", help="add-on data on a ticket").add_subparsers(dest="sub", required=True)
    x = e.add_parser("set", parents=[common])
    x.add_argument("id")
    x.add_argument("addon")
    x.add_argument("data", help="JSON object")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    x = e.add_parser("unset", parents=[common], help="remove an add-on's data, or one key of it")
    x.add_argument("id")
    x.add_argument("target", help="<add-on> or <add-on>.<key>")
    x.add_argument("--if-revision", type=int, metavar="N", help="refused when the ticket changed meanwhile")
    cli_clients.add_parsers(sub, common)
    cli_run.add_parsers(sub, common)
    cli_needs.add_parsers(sub, common)
    cli_config.add_parsers(sub, common)
    cli_look.add_parsers(sub, common)
    cli_chat.add_parsers(sub, common)
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


def _child_warning(root: Path, t: dict) -> list[str]:
    """Closing a parent with open sub-tickets is saved anyway: a warning on stderr and in --json."""
    if t["status"] != "done":
        return []
    kids = tickets.open_children(root, t["id"])
    if not kids:
        return []
    names = ", ".join(k["title"] for k in kids)
    print(f"Warning: {len(kids)} sub-tickets are still open ({names}). Closed anyway.", file=sys.stderr)
    return [f"{len(kids)} sub-tickets are still open: " + ", ".join(k["id"] for k in kids)]


def run(args: argparse.Namespace) -> None:
    root = _find_root()
    by = lambda: tickets.current_actor(getattr(args, "by", None))  # noqa: E731
    cmd, sub = args.cmd, getattr(args, "sub", None)
    from orch import chat

    chat.guard(root, args)  # the Chat helper's role is enforced here (every command, init too)

    if cmd == "init":
        root = Path.cwd()
        asking = term.is_terminal(sys.stdin) and not args.json
        agent = init_mod.choose_agent(root, args.yes, asking)
        lines = init_mod.init(root, args.code)
        on = init_mod.recommended(root, args.yes, asking) if args.recommended else []
        _out(
            args,
            {"ok": True, "root": str(root), "details": lines, "agent": agent, "recommended": on},
            "orch is ready in this folder. "
            + agent
            + "\n"
            + "\n".join(lines)
            + (f"\nTurned on: {', '.join(on)}" if on else "")
            + (
                "\nNext: orch init --recommended"
                if not args.recommended and init_mod.has_recommended(root)
                else ""
            ),
        )
    elif cmd == "update":
        report = []
        done = addons.update(
            root,
            args.project_only,
            args.after_install,
            json_output=args.json,
            report=report,
            nonce=args.update_nonce,
        )
        if args.after_install:
            pass
        elif args.project_only and (args.json or not report):
            _out(args, {"ok": True, "refreshed": done}, "Refreshed: " + ", ".join(done or ["nothing"]))
    elif cli_status.dispatch(args, root) or cli_addons.dispatch(args, root):
        pass
    elif cli_run.dispatch(args, root) or cli_needs.dispatch(args, root) or cli_config.dispatch(args, root):
        pass
    elif cli_chat.dispatch(args, root) or cli_look.dispatch(args, root):
        pass
    elif cmd == "ticket" and sub == "new":
        t = tickets.create(
            root,
            args.title,
            by(),
            args.parent,
            tickets.parse_ext_args(args.ext, lambda a: addons.active_ext_schema(root, a)),
            {k: getattr(args, k) for k in ("owner", "due", "note", "done_when") if getattr(args, k)},
            title_auto=args.title_auto,
        )
        part = f" (step of: {_lookup(root, args.parent)['title']})" if args.parent else ""
        _out(
            args,
            t,
            f'Created {t["key"]} "{t["title"]}" [{t["id"]}]{part}\n'
            f'Next: add one checklist item per step: orch check add {t["key"]} "<step>"',
        )
    elif cmd == "ticket" and sub == "tree":
        top = _visible(root, tickets.load(root, args.id))
        everything = tickets.list_all(root)
        _out(args, top, "\n".join([top["title"], *_tree(everything, top)]))
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
        ts.sort(key=lambda t: tuple(tickets.STATUS_WORDS).index(t["status"]))
        everything = tickets.list_all(root)
        ids = {x["id"] for x in everything}
        for t in ts:
            t["children"] = tickets.children_counts(everything, t["id"])
        txt = (
            "\n".join(
                _line(t) + (" - parent missing" if t.get("parent") and t["parent"] not in ids else "")
                for t in ts
            )
            or 'No open tickets. Create one with: orch ticket new "<title>"'
        )
        if hidden and not args.json:
            txt += f"\n({hidden} finished - show them with: orch ticket list --all)"
        _out(args, ts, txt)
    elif cmd == "ticket" and sub == "show":
        t = _visible(root, tickets.load(root, args.id))
        _out(args, t, _show(t, root))
    elif cmd == "ticket" and sub == "status":
        t = tickets.set_status(root, args.id, args.status, by())
        warn = _child_warning(root, t)
        _out(
            args,
            {**t, "warnings": warn} if warn else t,
            tickets.REVIEW_MESSAGE
            if args.status == "done" and t["status"] == "review"
            else f"{t['title']} - {tickets.STATUS_WORDS[t['status']]}",
        )
    elif cmd == "ticket" and sub == "edit":
        keys = ("owner", "due", "note", "done_when")
        fields = {k: getattr(args, k) for k in keys if getattr(args, k) is not None}
        if args.title is None and not fields:
            raise Refused("Say what to change: --title, --owner, --due, --note or --done-when.")
        t = tickets.edit(root, args.id, args.title, by(), fields, args.if_revision)
        _out(args, t, f"Saved (revision {t['revision']}).")
    elif cmd == "ticket" and sub == "set":
        _ticket_set(args, root, by)
    elif cmd == "ticket" and sub == "summary":
        t = tickets.set_summary(root, args.id, args.text, by())
        _out(args, t, "Summary saved.")
    elif cmd == "ticket" and sub == "artifacts":
        rows = tickets.artifacts_list(root, args.id)
        _out(
            args,
            rows,
            "\n".join(
                f"{r['name']}  {tickets._size_text(r['size'])}  {r['mtime']}  {r['path']}" for r in rows
            )
            or "No files yet. Put them in: orch ticket artifacts-dir " + args.id,
        )
    elif cmd == "ticket" and sub == "title":
        t = tickets.set_auto_title(root, args.id, args.title, by(), args.description)
        _out(args, t, f'Title written: "{t["title"]}"')
    elif cmd == "ticket" and sub == "attach":
        data = sys.stdin.buffer.read(tickets.ATTACH_MAX + 1)
        r = tickets.attach(root, args.id, args.name, data, by())
        _out(args, r, f"Attached {r['name']} ({tickets._size_text(r['size'])}): {r['path']}")
    elif cmd == "ticket" and sub == "artifacts-dir":
        d = tickets.artifacts_dir(root, args.id)
        rel = d.relative_to(root).as_posix()
        _out(args, {"path": rel}, rel)
    elif cmd == "ticket" and sub == "changes":
        t = tickets.ask_for_changes(root, args.id, args.text, by())
        _out(args, t, f"{t['title']} - sent back with your note. An agent picks it up.")
    elif cmd == "ticket" and sub == "patch":
        t = tickets.patch(root, args.id, args.if_revision, args.data, by())
        warn = _child_warning(root, t)
        _out(
            args,
            {**t, "warnings": warn} if warn else t,
            tickets.REVIEW_MESSAGE
            if json.loads(args.data).get("status") == "done" and t["status"] == "review"
            else f"{t['id']} changed (revision {t['revision']})",
        )
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
        extra = {k: getattr(args, k) for k in ("title", "role") if getattr(args, k)}
        # the summary says what came out of the step: it goes on ONE proof (the file, else the first one)
        kinds = [k for k in ("command", "note", "pr", "commit", "url") if getattr(args, k)]
        shorthand = [json.dumps({"type": k, "ref": getattr(args, k), **extra}) for k in kinds]
        if args.summary and shorthand and not args.file:
            shorthand[0] = json.dumps({**json.loads(shorthand[0]), "summary": args.summary})
        if args.file:
            tickets.check_exists(root, args.id, args.check)  # no orphan copy for a wrong id
            attached = tickets.attach_file(root, args.id, args.file, args.title, args.role, args.summary)
            shorthand.append(json.dumps(attached))
        t, c = tickets.check_done(root, args.id, args.check, args.evidence + shorthand, by())
        ev = c["evidence"][-1]
        copied = args.file and tickets.proof_present(root, ev)
        _out(
            args,
            c,
            f"Done: {c['text']} (proof: {ev['ref']})"
            + (f"\nProof copied: {ev['ref']} ({ev['text']})" if copied else ""),
        )
    elif cmd == "log":
        t = tickets.log(root, args.id, args.text, by())
        h = t["history"][-1]
        _out(args, h, f"{h['at']} {h['by']}: {tickets.history_line(h['text'], t['checklist'])}")
    elif cmd == "ask":
        if args.phone and "relay" not in addons.active(root):
            raise Refused(addons.not_on_message(root, "relay"))
        if (args.preview or args.scope) and not args.phone:
            raise Refused("--preview and --scope go with --phone.")
        t, q = tickets.ask(
            root, args.id, args.text, args.option, args.recommend, by(), args.kind, args.action, args.check
        )
        if args.phone:
            cli_clients.send_phone_question(root, t["id"], q, args.preview, args.scope)
        elif mobile_mode.question_to_phone(root, t["id"], os.environ.get("ORCH_TICKET")):
            # Mobile mode, or a ticket from the phone (or one its agent made): also to the phone
            with contextlib.suppress(Refused):  # the question is saved either way
                cli_clients.send_phone_question(root, t["id"], q)
        _out(
            args,
            q,
            f"Asked {q['id']}" + (f" on {q['check']}" if q.get("check") else "") + f", waiting. {t['title']} "
            "is now waiting for an answer.",
        )
    elif cmd == "answer":
        who = by()
        if tickets.agent_tool():  # an agent counts as an agent whatever --by says (as for finishing)
            who = "agent:" + str(tickets.agent_tool())
        if who.startswith("agent:") and relay.asked_to_phones(root, args.id, args.question):
            raise Refused("This question was sent to the phones. Only a human answers it.")
        t, q = tickets.answer(root, args.id, args.question, args.answer, who, args.via)
        with contextlib.suppress(
            Refused
        ):  # the answer is saved; a busy run only delays it reaching the agent
            runs_live.pass_answer(root, t["id"], q, who)
        note = _addon_note(root, q)
        _out(args, q, f"Answered: {q['answer']}" + (f"\n{note}" if note else ""))
    elif cmd == "ref":
        _ref(args, root, by)
    elif cmd == "publish":
        cli_clients.run_publish(args, root, _out)
    elif cmd == "relay":
        cli_clients.run_relay(args, root, _out)
    elif cmd == "ext" and args.sub == "unset":
        addon = args.target.partition(".")[0]
        t = tickets.ext_unset(
            root, args.id, args.target, by(), args.if_revision, addons.active_ext_schema(root, addon)
        )
        _out(args, (t.get("ext") or {}).get(addon, {}), f"ext.{args.target} removed from {t['id']}")
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


def _ref(args, root: Path, by) -> None:
    kinds = refs.active_kinds(root)
    if args.sub == "add":
        t, ref, added = tickets.ref_add(root, args.id, args.target, by(), args.kind, args.title, kinds)
        key = t.get("key") or t["id"]
        message = (
            f"Added reference to {key}: {refs.target(ref)}"
            if added
            else f"{key} already has this reference: {refs.target(ref)}"
        )
        _out(args, ref, message)
    elif args.sub == "list":
        t = tickets.load(root, args.id)
        rows = refs.all_refs(root, t)
        if args.json:
            _out(args, [{"n": n, **ref, "view": refs.describe(ref, kinds, root)} for n, ref in rows], "")
        elif not rows:
            key = t.get("key") or t["id"]
            print(f"{key} has no references yet. Add one: orch ref add {key} <url>")
        else:
            for n, ref in rows:
                d = refs.describe(ref, kinds, root)
                value = refs.one_line(d["title"], 300)
                suffix = " (On this computer only)" if ref.get("local") else ""
                print(f"  {n}  {d['type']}  {value}{suffix}" + (f"  {d['status']}" if d["status"] else ""))
    else:
        t, ref = tickets.ref_remove(root, args.id, args.target, by())
        _out(args, ref, f"Removed reference {args.target} from {t.get('key') or t['id']}")


def _ticket_set(args, root: Path, by) -> None:
    """`orch ticket set <id> <add-on>.<field> <value>`: one add-on field, typed and checked in plain words."""
    addon, _, key = args.field.partition(".")
    m = addons.active_manifests(root).get(addon)
    sec = fields.section(m) if m else None
    if sec is None:
        if addon in addons.discover():
            raise Refused(addons.not_on_message(root, addon))
        raise Refused(
            f"There is no add-on field {args.field}. "
            "Fields look like <add-on>.<field>, e.g. marketing.budget."
        )
    f = next((x for x in sec["fields"] if x["key"] == key), None)
    if f is None:
        names = ", ".join(
            f"{addon}.{x['key']}" for x in sec["fields"] if not x["read_only"] and not x["hidden"]
        )
        raise Refused(f"{sec['section']} has no field {key}. Fields: {names}.")
    who = (m.get("dashboard") or {}).get("label") or addon.capitalize()
    if f["read_only"]:
        shown = tickets.load(root, args.id).get("key") or args.id
        hint = f" Run: orch {addon} act refresh -- {shown}" if "refresh" in m["acts"] else ""
        raise Refused(f"{f['title']} is filled in by the {who} add-on.{hint}")
    schema = addons.active_ext_schema(root, addon) or {}
    value = fields.parse_value(f, args.value, (schema.get("properties") or {}).get(key) or {})
    if value is None:
        t = tickets.ext_unset(root, args.id, f"{addon}.{key}", by(), args.if_revision, schema)
    else:
        t = tickets.ext_set(root, args.id, addon, json.dumps({key: value}), by(), args.if_revision, schema)
    cur = ((t.get("ext") or {}).get(addon) or {}).get(key)
    _out(
        args,
        (t.get("ext") or {}).get(addon, {}),
        f"{t.get('key') or t['id']} {sec['section']} · {f['title']}: {fields.shown(f, cur)}",
    )


# The arguments that really name a ticket: (command, argument). Only these take a key; an `id` of another
# command (a publish file or app, a relay message, a webhook) is passed through untouched.
_TICKET_ARGS = {
    *{(c, "id") for c in ("ticket", "check", "log", "ask", "answer", "ref", "ext", "wait")},
    ("ticket", "parent"),
    ("run", "ticket"),
    ("relay", "ticket"),
}


def _resolve_keys(args: argparse.Namespace, root: Path | None) -> None:
    """A ticket key (DM1-12, any case) works wherever a ticket id does: turned into the id here, once."""
    cmd = getattr(args, "cmd", None)
    if root is None:
        return
    for c, name in _TICKET_ARGS:
        if c == cmd and isinstance(getattr(args, name, None), str):
            setattr(args, name, tickets.resolve(root, getattr(args, name)))
    on = getattr(args, "on", None)
    if cmd in ("ticket", "wait") and isinstance(on, str) and on.startswith("ticket:"):
        args.on = "ticket:" + tickets.resolve(root, on[len("ticket:") :])


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
        # a confirmation that could not be asked (no terminal) is a question: no "Refused:" in front
        print(f"{e}" if getattr(e, "confirm", False) else f"Refused: {e}", file=sys.stderr)
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
        _resolve_keys(args, root)
        run(args)
        cli_run.after_command(args, root, want_json)
    except Refused as e:
        return refuse(e)
    return 0
