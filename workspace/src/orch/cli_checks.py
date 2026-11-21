"""`orch checks`: the tools, logins, connections and keys this workspace depends on (checkfiles.py, ORCH-529).

list | init | templates | add <template> [--profile X] | approve <name> --hash <h> | remove <name>
| run [<name>]
Only states, times and names are printed; never anything a check's command said (R5.2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orch import checkfiles, cli_health, health, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    p = sub.add_parser("checks", parents=[common], help="the logins and tools this workspace depends on")
    acts = p.add_subparsers(dest="checks_action")
    acts.add_parser("list", parents=[common], help="every check: state, last and next run, approved or not")
    acts.add_parser("init", parents=[common], help="make .orch/checks with a documented template")
    acts.add_parser("templates", parents=[common], help="the built-in checks a workspace can add")
    a = acts.add_parser("add", parents=[common], help="add a check from a template")
    a.add_argument("template")
    a.add_argument("--profile", help="the tool's profile to check (Databricks, AWS): one check per profile")
    a.add_argument("--name", help="the check's name (default: template-profile)")
    ap = acts.add_parser(
        "approve", parents=[common], help="let a new or changed check file run (a person only)"
    )
    ap.add_argument("name")
    ap.add_argument("--hash", help="the short content hash shown next to the check (refused when it changed)")
    r = acts.add_parser("remove", parents=[common], help="delete a check file and forget it was approved")
    r.add_argument("name")
    run = acts.add_parser("run", parents=[common], help="run the checks now (or one)")
    run.add_argument("name", nargs="?")


def _when(at: str | None) -> str:
    return at.replace("T", " ").removesuffix("Z") + " UTC" if at else "never"


def _rows(root) -> list[dict]:
    last = {x.get("name"): x for x in (health.last(root) or {}).get("items") or [] if isinstance(x, dict)}
    out = []
    for e in checkfiles.entries(root):
        r, row = e["recipe"], last.get(e["name"]) or {}
        ran = row.get("checked_at") if not row.get("approve") else None
        nxt = None
        if r and e["status"] == "approved":
            if ran and row.get("v") == r.get("v"):
                at = datetime.strptime(ran, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                nxt = (at + timedelta(seconds=r["interval"])).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                nxt = "next background check"
        out.append(
            {
                "name": e["name"],
                "label": r["label"] if r else e["name"],
                "kind": r["kind"] if r else None,
                "status": e["status"] if r else "broken",
                "state": row.get("state") if ran and row.get("v") == (r or {}).get("v") else None,
                "last_run": ran if ran and row.get("v") == (r or {}).get("v") else None,
                "next_run": nxt,
                "interval": r["interval"] if r else None,
                "runs": checkfiles.runs(r) if r else None,
                "digest": checkfiles.short(e["digest"]) or None,
            }
        )
    return out


def _list_line(x: dict) -> str:
    if x["status"] == "broken":
        return f"{x['name']}: the file cannot be read; fix it with {checkfiles.TEMPLATE_FILE}"
    if x["status"] != "approved":
        head = f"{x['name']} ({x['label']}): {x['status']}"
        return (
            f"{head}, runs {x['runs']} (content {checkfiles.short(x['digest'])}), "
            f"waits until you approve it: {checkfiles.approve_command(x['name'], x['digest'])}"
        )
    nxt = x["next_run"] if x["next_run"] and "T" not in x["next_run"] else _when(x["next_run"])
    head = f"{x['name']} ({x['label']}): {x['state'] or 'not run yet'}"
    return f"{head}, last run {_when(x['last_run'])}, next {nxt}"


def _run_line(doc: dict, name: str) -> str:
    row = next((x for x in doc["items"] if x.get("name") == name), None)
    return cli_health.line(row) if row else f"{name} did not run."


def dispatch(args, root) -> bool:
    if args.cmd != "checks":
        return False
    action = getattr(args, "checks_action", None) or "list"
    out = cli_health._out
    if action == "list":
        rows = _rows(root)
        if not checkfiles.present(root):
            text = "This workspace has no checks of its own yet. Start with: orch checks init"
            note = checkfiles.notice(root)
            text += f"\n{note}" if note else ""
        else:
            text = "\n".join(_list_line(x) for x in rows) or "No checks yet. Add one: orch checks templates"
        out(
            args,
            {"present": checkfiles.present(root), "checks": rows, "notice": checkfiles.notice(root)},
            text,
        )
        return True
    if action == "init":
        res = checkfiles.init(root)
        text = (
            f"Checks for this workspace live in {res['folder']}; {checkfiles.TEMPLATE_FILE} says every field."
        )
        text += " Built-in checks no longer run here by themselves."
        if res["set_up_here"]:
            text += " Set up on this computer: " + ", ".join(res["set_up_here"])
            text += ". Add the ones this workspace needs: orch checks add <name> [--profile X]"
        out(args, res, text)
        return True
    if action == "templates":
        items = checkfiles.templates()
        text = "\n".join(
            f"{t['name']}: {t['label']}"
            + (" (one check per profile: --profile <name>)" if t["profile"] else "")
            for t in items
        )
        out(args, {"templates": items}, text)
        return True
    if action == "add":
        r = checkfiles.add_from_template(root, args.template, args.profile, args.name)
        doc = health.check(root, only=r["name"])
        text = f"Added {r['name']}: orch checks {r['label']} every {r['interval'] // 60} minutes. "
        text += _run_line(doc, r["name"])
        out(args, {"added": r["name"], "label": r["label"], "items": doc["items"]}, text)
        return True
    if action == "approve":
        r = checkfiles.approve(root, args.name, tickets.acting_by(args), args.hash)
        doc = health.check(root, only=r["name"])
        out(
            args,
            {"approved": r["name"], "items": doc["items"]},
            f"Approved {r['name']}. {_run_line(doc, r['name'])}",
        )
        return True
    if action == "remove":
        gone = checkfiles.remove(root, args.name)
        if not gone:
            raise Refused(f"There is no check called {args.name}. See them with: orch checks list")
        health.check(root, only="-")  # drops its row; no other check runs
        out(args, {"removed": args.name}, f"orch no longer checks {args.name}.")
        return True
    if action == "run":
        names = {e["name"] for e in checkfiles.entries(root)} | {r["name"] for r in health.recipes(root)}
        if args.name and args.name not in names:
            raise Refused(f"There is no check called {args.name}. See them with: orch checks list")
        doc = health.check(root, only=args.name) if args.name else health.check(root)
        rows = [x for x in doc["items"] if not args.name or x.get("name") == args.name]
        out(args, doc, "\n".join(cli_health.line(x) for x in rows) or cli_health.NONE_SET)
        return True
    raise Refused("Use one of: orch checks list | init | templates | add | approve | remove | run")
