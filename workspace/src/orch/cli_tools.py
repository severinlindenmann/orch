"""`orch tools`: the tools this workspace uses, their updates and update notes (toolupdates.py, ORCH-589).

list [--refresh] | notes <name> | update <name>
"""

from __future__ import annotations

from orch import cli_health, toolupdates
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    p = sub.add_parser("tools", parents=[common], help="the tools this workspace uses and their updates")
    acts = p.add_subparsers(dest="tools_action")
    ls = acts.add_parser("list", parents=[common], help="each tool: installed and newest version")
    ls.add_argument("--refresh", action="store_true", help="ask the update sources now (else kept 6 hours)")
    n = acts.add_parser("notes", parents=[common], help="what is new in the newer versions of one tool")
    n.add_argument("name")
    n.add_argument("--refresh", action="store_true", help="ask the update sources now")
    u = acts.add_parser("update", parents=[common], help="update one tool now (a person only)")
    u.add_argument("name")


def _line(t: dict) -> str:
    have = t.get("installed") or "version unknown"
    head = f"{t['label']} ({t['name']}) {have}"
    if t.get("update"):
        head += f", newer: {t['newest']}"
        if t.get("can_update"):
            head += f". Update with {t['how']}: orch tools update {t['name']}"
        else:
            head += ". " + (t.get("manual") or "")
    elif t.get("compare") == "current":
        head += ", up to date"
    else:
        head += ", newest version unknown"
    if t.get("error"):
        head += f" ({t['error']}" + (f" Last checked {t['last_good_at']})" if t.get("last_good_at") else ")")
    return head


def _notes_text(t: dict) -> str:
    out = []
    for s in t.get("notes") or []:
        out.append(f"What's new in {s['version']}:")
        out.extend(f"  - {x}" for x in s["lines"])
    if not out and t.get("notes_error"):
        out.append(t["notes_error"])
    if t.get("more"):
        out.append(f"  and {t['more']} more")
    if t.get("notes_url"):
        out.append(f"All notes: {t['notes_url']}")
    return "\n".join(out)


def dispatch(args, root) -> bool:
    if args.cmd != "tools":
        return False
    action = getattr(args, "tools_action", None) or "list"
    out = cli_health._out
    if action == "list":
        doc = toolupdates.status(root, refresh=getattr(args, "refresh", False))
        if toolupdates.in_helper():
            doc = toolupdates.for_helper(doc)
        text = "\n".join(_line(t) for t in doc["tools"]) or "No tools orch knows how to check are used here."
        job = doc.get("job")
        if job and job.get("status") == "running":
            text += f"\n{job['label']} is being updated now."
        out(args, doc, text)
        return True
    if action == "notes":
        doc = toolupdates.status(root, refresh=args.refresh, only=args.name)
        if not doc["tools"]:
            raise Refused(f"There is no tool called {args.name} here. See them with: orch tools")
        if toolupdates.in_helper():
            doc = toolupdates.for_helper(doc)
        t = doc["tools"][0]
        body = _notes_text(t) if t.get("update") else ""
        if t.get("notes_hidden"):
            body = (
                "The notes are shown to the person: Settings > About & updates, or orch tools notes "
                + t["name"]
            )
        out(args, t, _line(t) + ("\n" + body if body else ""))
        return True
    if action == "update":
        job = toolupdates.update(root, args.name)
        text = job["say"] or ""
        if job.get("tail"):
            text += "\nLast lines of its output:\n" + "\n".join("  " + x for x in job["tail"])
        out(args, job, text)
        if job["status"] != "done":
            raise SystemExit(1)
        return True
    raise Refused("Use one of: orch tools list | notes <name> | update <name>")
