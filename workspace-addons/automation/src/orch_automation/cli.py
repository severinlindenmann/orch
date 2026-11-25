"""`orch automation`: run, start, stop, status, list, repeat, view. Exit 0 ok, 2 refused (plain words), like the core."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import actions, orchcli, plain, scripts, service
from .cron import fmt, next_after, valid
from .listen import NOT_LISTENING
from .loop import Scheduler, group_of, scheduled
from .runner import load_state
from .view import cron_human


class Refused(Exception):
    pass


SCRIPT_OR_AGENT = "A repeat runs either a script or an agent, and a script never gets its own sub-tickets."


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def local_text(at: str | None) -> str | None:
    """A UTC time as the computer's local time with its zone: "Fri 07 Nov 09:00 CET"."""
    try:
        return datetime.fromisoformat(at).astimezone().strftime("%a %d %b %H:%M %Z") if at else None
    except (ValueError, AttributeError):
        return None


def list_line(x: dict) -> str:
    name = x["key"] or x["ticket"]
    if x["kind"] == "wake":
        return f"{name}  Wakes {x.get('local') or x['at']}  {x['title']}"
    nxt = "switched off" if x.get("off") else f"next {x.get('local') or x['at'] or 'unknown'}"
    if x["kind"] == "script":
        return f"{name}  script {x['script']}: {x['when']}, {nxt}  {x['title']}"
    return f"{name}  {x['when']}, {nxt}  {x['title']}"


def describe(root: Path) -> list[dict]:
    """Next wake-ups and repeats, soonest first: the tickets the scheduler plans (a repeat survives Done)."""
    state = load_state(root)
    rows = []
    for t in orchcli.tickets(root):
        if not scheduled(t):
            continue
        w = t.get("waiting_on") or {}
        if w.get("kind") == "time" and w.get("until"):
            rows.append(
                {
                    "ticket": t["id"],
                    "key": t.get("key"),
                    "title": t["title"],
                    "kind": "wake",
                    "at": w["until"],
                    "local": local_text(w["until"]),
                }
            )
        s = (t.get("ext") or {}).get("automation") or {}
        if s.get("recurring") is True and s.get("cron"):
            if s.get("paused") is True:  # switched off: listed, no next time
                rows.append(
                    {
                        "ticket": t["id"],
                        "key": t.get("key"),
                        "title": t["title"],
                        "kind": "repeat",
                        "cron": s["cron"],
                        "at": None,
                        "off": True,
                        "when": cron_human(s["cron"], plain.zone(s.get("tz"))),
                    }
                )
                continue
            for n, c in sorted(group_of(t).items()):  # each script of a group on its own plan
                nx = next_after(c, datetime.now(UTC), plain.zone(s.get("tz")))
                gat = fmt(nx) if nx else None
                rows.append(
                    {
                        "ticket": t["id"],
                        "key": t.get("key"),
                        "title": t["title"],
                        "kind": "script",
                        "script": n,
                        "cron": c,
                        "at": gat,
                        "when": cron_human(c, plain.zone(s.get("tz"))),
                        "local": local_text(gat),
                    }
                )
            nxt = next_after(s["cron"], datetime.now(UTC), plain.zone(s.get("tz")))
            at = fmt(nxt) if nxt else state.get(t["id"], {}).get("next_run")
            rows.append(
                {
                    "ticket": t["id"],
                    "key": t.get("key"),
                    "title": t["title"],
                    "kind": "repeat",
                    "cron": s["cron"],
                    "at": at,
                    "when": cron_human(s["cron"], plain.zone(s.get("tz"))),
                    "local": local_text(at),
                }
            )
    return sorted(rows, key=lambda r: r["at"] or "")


def repeat(
    root: Path,
    tid: str,
    phrase: str | None,
    off: bool,
    agent: str | None = None,
    tz: str | None = None,
    each_run: bool = False,
    by: str | None = None,
    script: str | list[str] | None = None,
    when_changed: str | None = None,
) -> dict:
    want = tid.strip().upper()  # the ticket id, or its key (DM1-12, any case)
    t = next(
        (x for x in orchcli.tickets(root) if x["id"] == tid or str(x.get("key") or "").upper() == want), None
    )
    if t is None:
        raise Refused(f"There is no ticket {tid}.")
    tid = t["id"]
    if off:
        if not orchcli.set_ext(root, t, remove=("each_run", "next_run"), by=by, recurring=False):
            raise Refused(orchcli.refusal("The ticket changed or the change was not accepted. Try again."))
        return {"ticket": tid, "recurring": False}
    if not phrase:
        raise Refused(f"Say when. For example: {plain.EXAMPLES}.")
    daily = re.fullmatch(r"every day at ([0-9]{1,2})(?::([0-9]{2}))?", phrase.strip().lower())
    if daily:
        phrase = f"daily {int(daily[1]):02d}:{daily[2] or '00'}"
    zone_name = tz or plain.new_repeat_zone(root)
    try:
        plan = plain.Plan(cron=phrase) if valid(phrase) else plain.parse(phrase, zone_name)
    except plain.Plain as e:
        raise Refused(str(e)) from None
    if plan.until:  # a one-off is a core wait
        if each_run:
            raise Refused("Each run as its own ticket is only for repeats.")
        if orchcli.call(root, "wait", tid, "--until", plan.until, by=by or True) is None:
            raise Refused("The wait was not accepted. Try again.")
        return {"ticket": tid, "recurring": False, "until": plan.until}
    if plain.zone(zone_name) is None:
        raise Refused(f"'{zone_name}' is not a time zone. Use a name like Europe/Zurich.")
    changes = {"recurring": True, "cron": plan.cron, "tz": zone_name}
    nxt = next_after(plan.cron, datetime.now(UTC), plain.zone(zone_name))
    if nxt:  # read by core's scheduled health checks: a repeat whose planned time passed long ago stopped
        changes["next_run"] = fmt(nxt)
    if each_run and not plain.daily_or_slower(plan.cron):
        raise Refused('Each run as its own ticket needs a repeat daily or slower, like "daily 07:30".')
    remove = [] if each_run else ["each_run"]
    group = _group(root, script, zone_name, agent, each_run, plan.cron) if isinstance(script, list) else None
    if group is not None:
        if len(group) == 1 and next(iter(group.values())) == plan.cron:
            script = next(iter(group))  # one script on the repeat's own plan: a plain script repeat
        else:
            changes["group"] = group
            remove.append("script")
            script = None
    if group is None or "group" not in changes:
        remove.append("group")
    if when_changed is not None:
        from .loop import CHANGE_RE, change_mark

        if when_changed.strip().lower() in ("", "off", "none"):
            remove.append("when_changed")
        elif not CHANGE_RE.match(when_changed) or ".." in when_changed.split("@")[0].split("/"):
            raise Refused(
                "Say the folder in this workspace and the branch, for example: --when-changed orch@origin/develop"
            )
        elif change_mark(root, when_changed) is None:
            raise Refused(
                f"{when_changed} cannot be read: is the folder a git project here and the branch right?"
            )
        else:
            changes["when_changed"] = when_changed
    if script is not None:
        if agent or each_run:
            raise Refused(SCRIPT_OR_AGENT)
        if not scripts.NAME_RE.match(script):
            raise Refused(
                "A script name may only have a-z, 0-9 and -. It names a script (orch automation script list)."
            )
        if not scripts.defined(root, script):
            why = scripts.missing(root, script)
            raise Refused(why[0].upper() + why[1:] + ".")
        changes["script"] = script
    if agent:
        remove.append("script")  # an agent again instead of a script
        if not orchcli.AGENT_RE.match(agent):
            raise Refused("The agent name may only have a-z, 0-9 and -. It names an agent (orch agents).")
        changes["agent"] = agent
    if each_run:
        changes["each_run"] = "sub-ticket"
    if not orchcli.set_ext(root, t, remove=tuple(remove), by=by, **changes):
        raise Refused(orchcli.refusal("The ticket changed or the change was not accepted. Try again."))
    return {"ticket": tid, **changes}


def allow(root: Path, tid: str, key: str) -> dict:
    """`orch automation allow <ticket> --key <key>`: a person (never an agent) allows the ticket's repeat on this computer."""
    from . import syncapproval

    if scripts.an_agent():
        raise Refused("Only a person can allow a repeat on this computer, not a helper.")
    want = tid.strip().upper()
    t = next(
        (x for x in orchcli.tickets(root) if x["id"] == tid or str(x.get("key") or "").upper() == want), None
    )
    if t is None:
        raise Refused(f"There is no ticket {tid}.")
    try:
        syncapproval.allow_here(root, t, key)
    except ValueError as e:
        raise Refused(str(e)) from None
    return {"ticket": t["id"], "key": t.get("key"), "allowed": True}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="orch automation",
        description="Starts helper runs: at a time, on a repeat, from the relay inbox.",
    )
    ap.add_argument(
        "--dir",
        default=os.environ.get("ORCH_ROOT", "."),
        help="workspace folder (default: ORCH_ROOT or current)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    r = sub.add_parser("run", parents=[common], help="run in the foreground")
    r.add_argument("--once", action="store_true", help="one pass, wait for the agents, then stop")
    sub.add_parser("start", parents=[common], help="run in the background")
    sub.add_parser("stop", parents=[common], help="stop the background run")
    sub.add_parser("status", parents=[common], help="is it running? (exit 0 when running, 1 when stopped)")
    sub.add_parser("list", parents=[common], help="next wake-ups and repeats")
    sub.add_parser("needs", parents=[common], help="rows for `orch needs`")
    sub.add_parser("view", parents=[common], help="dashboard tab data")
    rp = sub.add_parser(
        "repeat", parents=[common], help="repeat a ticket, or wake it once; say when in plain words"
    )
    rp.add_argument("ticket")
    rp.add_argument("when", nargs="?", help=f"for example: {plain.EXAMPLES}")
    rp.add_argument("--agent", help="name of the agent for this repeat")
    rp.add_argument("--tz", help="time zone of the times (default: this computer's, e.g. Europe/Zurich)")
    rp.add_argument(
        "--each-run", choices=("sub-ticket",), help="give every run its own sub-ticket (daily or slower)"
    )
    rp.add_argument(
        "--script",
        action="append",
        help="run this script (orch automation script list) instead of an agent; give it more than once for a group, "
        'each as name or "name=every 15 minutes" (its own plan)',
    )
    rp.add_argument(
        "--when-changed",
        metavar="FOLDER@BRANCH",
        help="start only when this git branch moved since the last run, e.g. orch@origin/develop (off: any time)",
    )
    rp.add_argument("--off", action="store_true")
    al = sub.add_parser(
        "allow", parents=[common], help="a person allows a repeat that came by sync on this computer"
    )
    al.add_argument("ticket")
    al.add_argument("--key", required=True, help="the key the refusal on the ticket shows")
    sc = sub.add_parser(
        "script", parents=[common], help="commands a repeat can run instead of an agent (this computer only)"
    )
    scs = sc.add_subparsers(dest="script_cmd", required=True)
    sa = scs.add_parser(
        "add", parents=[common], help="add a script: orch automation script add <name> -- <command>"
    )
    sa.add_argument("name")
    sa.add_argument("command", nargs=argparse.REMAINDER)
    scs.add_parser("list", parents=[common], help="the scripts on this computer")
    sw = scs.add_parser("allow", parents=[common], help="a person allows a script on this computer")
    sw.add_argument("name")
    sw.add_argument("--key", required=True, help="the key orch automation script list shows")
    sr = scs.add_parser("remove", parents=[common], help="remove a script")
    sr.add_argument("name")
    sx = scs.add_parser(
        "run", parents=[common], help="run a ticket's script now and wait (what a repeat does)"
    )
    sx.add_argument("ticket")
    sx.add_argument("--name", help="one script of the ticket's group")
    rs = sub.add_parser("result", parents=[common], help="a role's helper writes the result of its run")
    rs.add_argument("ticket")
    rs.add_argument("text", help="what the run found, one line")
    rs.add_argument("--outcome", required=True, choices=("ok", "problems", "not-finished", "failed"))
    rs.add_argument("--checked", action="append", help="one thing it checked and how that went (repeat it)")
    rs.add_argument("--file", action="append", help="a file of the ticket this run made (repeat it)")
    rs.add_argument("--cost", type=float, help="what the run cost in dollars, when known")
    rs.add_argument("--run", type=int, help="the run number (default: the run going on now)")
    fd = sub.add_parser(
        "finding", parents=[common], help="a role's run found a problem: make or reuse its ticket"
    )
    fd.add_argument("ticket", help="the role ticket")
    fd.add_argument("title", help="the problem in a few words")
    fd.add_argument(
        "--ticket", dest="into", help="put it on this ticket (for example the day's review ticket)"
    )
    fd.add_argument("--same-as", help="a short name that marks the same problem again (default: the title)")
    fd.add_argument("--file", action="append", help="a file of the role ticket that shows it (repeat it)")
    fd.add_argument("--run", type=int, help="the run number (default: the run going on now)")
    ro = sub.add_parser("role", parents=[common], help="a repeating ticket's runs and what came of them")
    ro.add_argument("ticket")
    ac = sub.add_parser(
        "act",
        parents=[common],
        help="what the dashboard buttons do: on, off, toggle, run, delete, repeat, copy",
    )
    ac.add_argument("--value", help="when to repeat, in plain words")
    ac.add_argument("verb", choices=actions.VERBS)
    ac.add_argument("target", help="ticket id")
    ac.add_argument("--by", help="who pressed the button (recorded on the ticket); the add-on act contract")
    ac.add_argument(
        "--proof-target", action="store_true", help="say what the person confirms (the dashboard asks first)"
    )
    args = ap.parse_args(argv)
    try:
        root = find_workspace(Path(args.dir))
        if root is None:
            raise Refused("No orch workspace here (no .orch/ folder). Run `orch init` first.")
        return _run(args, root)
    except Refused as e:
        print(
            json.dumps({"error": str(e)}) if args.json else f"Refused: {e}",
            file=None if args.json else sys.stderr,
        )
        return 2


def _group(root: Path, given: list[str], zone_name: str, agent, each_run, own: str) -> dict[str, str]:
    """--script given once or more: "name" (on the repeat's own plan) or "name=<plan in plain words>".
    Returns name -> cron rule; every script must be set up on this computer."""
    if agent or each_run:
        raise Refused(SCRIPT_OR_AGENT)
    out: dict[str, str] = {}
    for item in given:
        name, _, words = item.partition("=")
        name = name.strip()
        if not scripts.NAME_RE.match(name):
            raise Refused(
                "A script name may only have a-z, 0-9 and -. It names a script (orch automation script list)."
            )
        if not scripts.defined(root, name):
            why = scripts.missing(root, name)
            raise Refused(why[0].upper() + why[1:] + ".")
        words = words.strip()
        try:
            rule = own if not words else words if valid(words) else plain.parse(words, zone_name).cron
        except plain.Plain as e:
            raise Refused(f"{name}: {e}") from None
        if not rule:
            raise Refused(f'{name}: a script of a group repeats, for example "{name}=every 15 minutes".')
        out[name] = rule
    return out


def _run(args, root: Path) -> int:
    def out(data, text: str) -> None:
        print(json.dumps(data) if args.json else text)

    if args.cmd == "run":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"orch automation for {root.name} started {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}", flush=True)
        nonce = service.announce(root)  # background run: record pid + start time in .orch/run/automation/
        try:
            Scheduler(root).run_forever(once=args.once)
        except KeyboardInterrupt:
            pass
        finally:
            service.forget(root, nonce)
    elif args.cmd == "start":
        try:
            pid = service.start(root)
        except RuntimeError as e:
            raise Refused(str(e)) from None
        out({"running": True, "pid": pid}, f"Scheduler running (pid {pid}).")
    elif args.cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = str(e)
        if res in ("stopped", "not running"):
            out(
                {"stopped": res == "stopped"},
                "Scheduler stopped." if res == "stopped" else "Scheduler was not running.",
            )
        else:
            note = (
                "A file in .orch/run/automation/ names a process that is not this scheduler; nothing was stopped."
                if res == "not verified"
                else res
            )
            out({"stopped": False, "note": note}, note)
    elif args.cmd == "status":
        from . import listen

        pid = service.running_pid(root)
        ls = listen.read(root) if pid else {}
        listening = bool(pid and ls.get("listening"))
        heard = (
            "Listening for the phone and other workspaces."
            if listening
            else (ls.get("note") or NOT_LISTENING)
        )
        line = f"Automation is running (pid {pid}). {heard}" if pid else "Automation is not running."
        out({"running": bool(pid), "pid": pid, "listening": listening}, line)
        return 0 if pid else 1
    elif args.cmd == "needs":
        from . import needs

        rs = needs.rows(root)
        out(rs, "\n".join(f"{r['title']}: {r['text']}" for r in rs) or "Nothing needs you here.")
    elif args.cmd == "list":
        rows = describe(root)
        out(rows, "\n".join(list_line(x) for x in rows) or "Nothing scheduled.")
    elif args.cmd == "view":
        from .view import build

        print(json.dumps(build(root)))
    elif args.cmd == "act" and args.proof_target:
        try:
            print(json.dumps(actions.review(root, args.verb, args.target)))
        except actions.Bad as e:
            raise Refused(str(e)) from None
    elif args.cmd == "act":
        try:
            res = actions.act(root, args.verb, args.target, args.by, args.value)
        except actions.Bad as e:
            raise Refused(str(e)) from None
        out(res, res["text"])
    elif args.cmd == "allow":
        res = allow(root, args.ticket, args.key)
        out(res, f"Allowed on this computer. The repeat of {res['key'] or res['ticket']} runs again.")
    elif args.cmd == "script":
        return _script(args, root, out)
    elif args.cmd in ("result", "finding", "role"):
        return _role_cmd(args, root, out)
    elif args.cmd == "repeat":
        res = repeat(
            root,
            args.ticket,
            args.when,
            args.off,
            args.agent,
            args.tz,
            bool(args.each_run),
            script=args.script,
            when_changed=args.when_changed,
        )
        if res.get("until"):
            text = f"{args.ticket} wakes once at {local_text(res['until']) or res['until']}."
        elif res["recurring"]:
            text = f"{args.ticket} repeats: {cron_human(res['cron'], plain.zone(res['tz']), local=plain.zone(res['tz']))} ({res['tz']})."
            if res.get("script"):
                text += f" Each time it runs the script {res['script']}, no agent."
            for name, rule in sorted((res.get("group") or {}).items()):
                text += f"\n  {name}: {cron_human(rule, plain.zone(res['tz']), local=plain.zone(res['tz']))}"
            if res.get("when_changed"):
                text += f"\nIt starts only when {res['when_changed']} changed since its last run."
        else:
            text = f"{args.ticket} no longer repeats."
        running = bool(service.running_pid(root))
        res["running"] = running
        if not running and not args.off:
            text += "\nRepeating work isn't running here. Start it: orch start"
        out(res, text)
    return 0


def _script(args, root: Path, out) -> int:
    from .loop import ask_failure, script_of

    if args.script_cmd == "add":
        cmd = list(args.command)
        if "--" in cmd:  # options before -- (only --json) belong to orch; everything after it is the command
            cut = cmd.index("--")
            args.json = args.json or "--json" in cmd[:cut]
            cmd = cmd[cut + 1 :]
        try:
            scripts.add(root, args.name, cmd)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        ok = scripts.command(root, args.name) is not None
        text = f"Script {args.name} added on this computer. Use it: orch automation repeat <ticket> " + (
            f'"every 15 minutes" --script {args.name}'
        )
        if not ok:
            text += (
                f"\nIt runs only after a person allows it: orch automation script allow {args.name} "
                f"--key {scripts.key(root, args.name, cmd)}"
            )
        out({"script": args.name, "command": cmd, "allowed": ok}, text)
    elif args.script_cmd == "list":
        rows = []
        for n, c in sorted(scripts.load(root).items()):
            ok = scripts.approved(root, n, c)
            rows.append(
                {"script": n, "command": c, "allowed": ok, **({} if ok else {"key": scripts.key(root, n, c)})}
            )
        out(
            rows,
            "\n".join(
                f"{r['script']}  {scripts.shown(r['command'])}"
                + (
                    ""
                    if r["allowed"]
                    else f"\n  not allowed yet: orch automation script allow {r['script']} --key {r['key']}"
                )
                for r in rows
            )
            or "No scripts on this computer.",
        )
    elif args.script_cmd == "allow":
        try:
            scripts.allow(root, args.name, args.key)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        out({"script": args.name, "allowed": True}, f"Script {args.name} allowed on this computer.")
    elif args.script_cmd == "remove":
        try:
            gone = scripts.remove(root, args.name)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        if not gone:
            raise Refused(f"There is no script named {args.name} on this computer.")
        out(
            {"script": args.name, "removed": True},
            f"Script {args.name} removed. Repeats that name it stop with a question.",
        )
    elif args.script_cmd == "run":
        want = args.ticket.strip().upper()
        t = next(
            (
                x
                for x in orchcli.tickets(root)
                if x["id"] == args.ticket or str(x.get("key") or "").upper() == want
            ),
            None,
        )
        if t is None:
            raise Refused(f"There is no ticket {args.ticket}.")
        group = group_of(t)
        if args.name and args.name not in group:
            raise Refused(f"{args.name} is not one of the scripts of {args.ticket}.")
        if args.name:
            todo = [(args.name, True)]
        elif script_of(t):
            todo = [(script_of(t), False)]
        elif group:
            todo = [(n, True) for n in sorted(group)]  # what Start now does: the whole group
        else:
            raise Refused(
                f"{args.ticket} runs no script. Set one: orch automation repeat {args.ticket} <when> --script <name>"
            )
        refused = orchcli.sync_refusal(root, t["id"])
        if refused:
            raise Refused(refused)
        results, worst = [], 0
        for name, member in todo:
            code = scripts.run(
                root,
                t["id"],
                name,
                fmt(datetime.now(UTC)),
                lambda why: ask_failure(root, t["id"], f"The script did not work: {why}"),
                member=member,
            )
            results.append((name, code))
            if code not in (0, 75) and worst == 0:
                worst = code
        if len(results) == 1:
            name, code = results[0]
            if code == 75:
                out({"ticket": t["id"], "running": True}, "It is still running from before.")
                return 0
            out({"ticket": t["id"], "exit": code}, f"Script {name} ended with exit code {code}.")
            return 0 if code == 0 else 1
        lines = [
            f"Script {n} is still running from before."
            if c == 75
            else f"Script {n} ended with exit code {c}."
            for n, c in results
        ]
        out({"ticket": t["id"], "exit": worst, "scripts": dict(results)}, "\n".join(lines))
        return 0 if worst == 0 else 1
    return 0


def _role_ticket(root: Path, ref: str) -> dict:
    want = str(ref).strip().lower()
    t = next(
        (x for x in orchcli.tickets(root) if x["id"] == want or str(x.get("key") or "").lower() == want), None
    )
    if not t:
        raise Refused(f"There is no ticket {ref}.")
    return t


def _role_cmd(args, root: Path, out) -> int:
    """result / finding / role (ORCH-827): the runs of a repeating ticket and what came of them."""
    from . import roles

    t = _role_ticket(root, args.ticket)
    tid, key = t["id"], t.get("key") or t["id"]
    if args.cmd == "result":
        try:
            line = roles.result(
                root, tid, args.text, args.outcome, args.checked, args.file, args.cost, args.run
            )
        except ValueError as e:
            raise Refused(str(e)) from None
        out(line, f"Result of run {line['run']} saved: {roles.OUTCOME_WORDS[line['outcome']]}.")
        return 0
    if args.cmd == "role":
        all_t = {x["id"]: x for x in orchcli.tickets(root)}
        running = bool(orchcli.run_running(root, tid))
        rl = roles.runs(root, t, running)
        tot = roles.totals(root, t, all_t, rl)
        lines = [
            f"{key}: {tot['runs']} runs, {tot['findings']} findings, {tot['fixed']} fixed, {tot['open']} open, {tot['dropped']} dropped."
        ]
        lines += [
            f"  Run {r['run']} · {r['words']}" + (f": {r['text']}" if r["text"] else "") for r in rl[:10]
        ]
        out({"ticket": tid, "runs": rl, "totals": tot, "schedule": _role_schedule(root, t)}, "\n".join(lines))
        return 0
    run = args.run if args.run is not None else roles.current(root, tid)
    if not isinstance(run, int) or run < 1:
        raise Refused("This ticket has no run yet. Say which one with --run.")
    title = " ".join(str(args.title).split())[:200]
    if not title:
        raise Refused("Say the problem in a few words.")
    match = roles.match_name(args.same_as or title)
    if not match:
        raise Refused("Say the problem in a few words (letters or digits).")
    all_t = {x["id"]: x for x in orchcli.tickets(root)}
    earlier = None
    if args.into:
        into = _role_ticket(root, args.into)
        target, made = into["id"], False
    else:
        reuse, earlier = roles.finding_ticket(roles.findings_of(root, tid), all_t, tid, match)
        if reuse:
            target, made = reuse, False
        else:
            res = orchcli.call(root, "ticket", "new", title)
            if not isinstance(res, dict) or not res.get("id"):
                raise Refused("The ticket for the finding could not be made. Nothing was saved.")
            target, made = res["id"], True
    roles.finding_line(root, tid, run, title, target, match, args.file)
    words = f"Found by {key} ({t.get('title', '')[:80]}), run {run}: {title}"
    if earlier:
        words += f". Seen again after {(all_t.get(earlier) or {}).get('key') or earlier} was closed"
    orchcli.log(root, target, words + ".")
    tkey = (all_t.get(target) or {}).get("key") or (res.get("key") if made else None) or target
    orchcli.log(root, tid, f"Run {run} found: {title} ({'new ticket' if made else 'on'} {tkey}).")
    out(
        {"role": tid, "run": run, "ticket": target, "made": made, "match": match},
        f"{'Made' if made else 'Added to'} {tkey} for run {run}.",
    )
    return 0


def _role_schedule(root: Path, t: dict) -> dict:
    """The Schedule tab in words: how it repeats, the next three times (none while paused), quick check, time limit."""
    from .loop import script_of, time_limit

    sched = (t.get("ext") or {}).get("automation") or {}
    cron = (
        sched.get("cron") if sched.get("recurring") is True and isinstance(sched.get("cron"), str) else None
    )
    tz = plain.zone(sched.get("tz")) or plain.zone(plain.workspace_tz(root))
    paused = sched.get("paused") is True
    nxt: list[str] = []
    if cron and not paused:
        at = datetime.now(UTC)
        for _ in range(3):
            at = next_after(cron, at, tz)
            if not at:
                break
            nxt.append(fmt(at))
    return {
        "repeats": cron_human(cron, tz, local=tz) if cron else None,
        "cron": cron,
        "paused": paused,
        "next": nxt,
        "quick": "on" if sched.get("when_changed") else "off" if sched.get("when_changed_off") else "none",
        "time_limit": time_limit(t),
        "script": bool(script_of(t)) or "group" in sched,
        "running": bool(service.running_pid(root)),
    }


if __name__ == "__main__":
    sys.exit(main())
