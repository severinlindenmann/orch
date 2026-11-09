"""`orch config` (agent settings) and `orch agents`."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from orch import adapters, config, tickets
from orch.errors import Refused

KEYS = (
    "workspace.agent",
    "workspace.code",
    "workspace.permissions",
    "workspace.live_idle_minutes",
    "workflow.agents_may_finish",
)
TEST_PROMPT = "Reply with the word ok"
TEST_TIMEOUT = 60  # seconds


def add_parsers(sub, common) -> None:
    ag = sub.add_parser("agents", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    t = ag.add_parser("test", parents=[common], help="run an agent once with a trivial prompt")
    t.add_argument("name")
    sh = sub.add_parser("share", parents=[common], help=argparse.SUPPRESS)
    sh.add_argument("state", nargs="?", choices=("on", "off", "status"), default="status")
    pv = sub.add_parser("private", parents=[common], help=argparse.SUPPRESS)
    pv.add_argument("state", nargs="?", choices=("status", "move", "allow"), default="status")
    pv.add_argument("name", nargs="?", help="allow: the agent name shown by orch private")
    pv.add_argument("--key", help="allow: the key shown by orch private (binds the yes to what you saw)")
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
    a.add_argument("--prompt-via", choices=("arg", "stdin"), help="how the task reaches the command")
    a.add_argument("--interactive", help="optional: the command that starts it for a live session")


def _actor(args) -> str:
    """Who runs this: --by, else the agent tool seen in the environment, else the person. An agent in the
    environment counts as an agent whatever --by says."""
    who = tickets.current_actor(getattr(args, "by", None))
    return "agent:" + str(tickets.agent_tool()) if tickets.agent_tool() else who


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


def test_agent(root: Path, name: str) -> dict:
    """Run the agent once with a trivial prompt: {ok, name, reason}. Writes no ticket or run state."""
    a = adapters.load(name, root)
    label = a["label"]

    def result(ok: bool, reason: str) -> dict:
        return {"name": name, "ok": ok, "reason": reason}

    argv = adapters.render(
        name, "fresh", "oneshot", {"prompt": TEST_PROMPT, "new_session": str(uuid.uuid4())}, root
    )
    if argv is None:
        return result(False, f"{label} cannot be started this way.")
    if not shutil.which(argv[0]):
        return result(False, f"{label} is not installed.")
    stdin = TEST_PROMPT if adapters.prompt_via_stdin(name, root) else None
    t0 = time.monotonic()
    scratch = tempfile.mkdtemp(prefix="orch-agent-test-")  # empty: agent can't touch the workspace
    try:
        return _run_test(argv, stdin, scratch, label, t0, result)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run_test(argv, stdin, scratch, label, t0, result) -> dict:
    try:
        proc = subprocess.Popen(
            argv,
            cwd=scratch,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=os.name != "nt",
        )
    except OSError as e:
        return result(False, f"The command failed: {str(e).splitlines()[0] if str(e) else 'could not start'}")
    try:
        out, err = proc.communicate(stdin, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(Exception):
            from orch import runs

            runs.kill_tree(proc.pid)
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.communicate(timeout=5)
        return result(False, f"No answer within {TEST_TIMEOUT} s.")
    took = max(1, round(time.monotonic() - t0))
    if proc.returncode != 0:
        first = next((ln.strip() for ln in (err or out or "").splitlines() if ln.strip()), "")
        return result(False, f"The command failed: {first or f'it stopped with code {proc.returncode}'}")
    if not (out or "").strip():
        return result(False, f"{label} gave no answer.")
    return result(True, f"{label} answered in {took} s.")


def _test(args, root: Path) -> int:
    r = test_agent(root, args.name)
    _out(args, r, r["reason"])
    return 0 if r["ok"] else 1


def _config(args, root: Path) -> None:
    if args.sub == "get":
        cur = {
            "workspace.agent": config.agent_name(root),
            "workspace.code": config.workspace_code(root),
            "workspace.permissions": config.permissions(root),
            "workspace.live_idle_minutes": config.live_idle_minutes(root),
            "workflow.agents_may_finish": config.agents_may_finish(root),
        }
        if args.key:
            _out(
                args,
                {args.key: cur[args.key]},
                str(cur[args.key]) if cur[args.key] is not None else "(not set)",
            )
        else:
            _out(
                args,
                cur,
                "\n".join(f"{k} = {v}" for k, v in cur.items() if v is not None) or "Nothing is set.",
            )
    elif args.sub == "set" and args.key == "workflow.agents_may_finish":
        if args.value not in ("on", "off"):
            raise Refused("Choose on or off.")
        if args.value == "on" and _actor(args).startswith("agent:"):
            raise Refused(
                "Only a person can allow agents to mark tickets Done. Ask them to run: "
                "orch config set workflow.agents_may_finish on"
            )
        value = config.set_agents_may_finish(root, args.value == "on")
        _out(args, {"workflow.agents_may_finish": value}, f"Agents may mark tickets Done: {args.value}.")
    elif args.sub == "set" and args.key == "workspace.code":
        code = config.set_code(root, args.value)
        _out(
            args,
            {"workspace.code": code},
            f"Saved: workspace.code = {code}. New tickets get {code}-<n>; existing keys stay as they are.",
        )
    elif args.sub == "set" and args.key == "workspace.permissions":
        mode = config.set_permissions(root, args.value, _actor(args))
        _out(
            args,
            {"workspace.permissions": mode},
            f"Saved: workspace.permissions = {mode}. It applies to the next agent start.",
        )
    elif args.sub == "set" and args.key == "workspace.live_idle_minutes":
        mins = config.set_live_idle_minutes(root, args.value)
        _out(
            args,
            {"workspace.live_idle_minutes": mins},
            f"Saved: workspace.live_idle_minutes = {mins}. Live sessions close after that long idle; "
            "Continue picks the conversation up again.",
        )
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
            if args.name in adapters.builtin_names():
                raise Refused(f"'{args.name}' is a built-in agent; pick another name.")
            config.add_agent(
                root,
                args.name,
                args.command,
                args.interactive,
                prompt=args.prompt_via,
                approve=not tickets.agent_tool(),
            )
            tail = (
                "starts fresh each run; no live steps"
                if not args.interactive
                else "starts fresh each run; live session possible"
            )
            _out(args, {"agent": args.name}, f"Added {args.name} ({tail}).")
        else:
            name = _choose(root, args.name_or_add)
            _out(args, {"workspace.agent": name}, f"Saved: workspace.agent = {name}.")


def _share(args, root: Path) -> None:
    """Share with team: one stable block in the team's AGENTS.md and merge=union in .gitattributes.
    Human only (it changes files the team owns). Off removes both."""
    from orch import harness

    if args.state != "status":
        if tickets.agent_tool():
            raise Refused("Only a person can share the orch entry with the team.")
        (harness.share_on if args.state == "on" else harness.share_off)(root)
    on = harness.share_state(root)
    _out(
        args,
        {"shared": on},
        "Shared with your team: AGENTS.md has the orch entry."
        if on
        else "Not shared: the orch files stay on this computer.",
    )


def private_lines(root: Path) -> list[str]:
    """The git notes for `orch status` / `orch private`: what the team repo holds, the next step, a committed
    agent command that is ignored. [] when there is nothing to say."""
    from orch import harness

    s = harness.private_summary(root)
    out = []
    if s["files"]:
        out += [
            harness.private_words(s),
            "Move to private: removes them from the team repo, keeps your files (orch private move).",
        ]
    for p in config.pending_agents(root):
        shown = "; ".join(f"{k}: {p[k]}" for k in ("adapter", "command", "interactive", "prompt") if p[k])
        if p["showable"]:
            out.append(
                f"This workspace asks to run an agent '{p['name']}' ({shown}). "
                f"Allow on this machine: orch private allow {p['name']} --key {p['key']}"
            )
        else:
            out.append(
                "This workspace asks to run a command orch can't show safely. Not allowed; it is not run."
            )
    return out


def _private(args, root: Path) -> None:
    """`orch private [status|move]`: personal files that the team repo already tracks. `move` is a person's
    action (git rm --cached; nothing is committed, the files stay)."""
    from orch import harness

    if args.state == "allow":
        if tickets.agent_tool():
            raise Refused("Only a person can allow a command to run on this computer.")
        if not args.name or not args.key:
            raise Refused("Say which one: orch private allow <name> --key <key> (orch private shows both).")
        done = config.allow_agent(root, args.name, args.key)
        _out(args, {"allowed": [done]}, f"Allowed on this computer: {done}.")
        return
    if args.state == "move":
        if tickets.agent_tool():
            raise Refused("Only a person can move these files out of the team repo.")
        moved = harness.move_to_private(root)
        if args.json:
            print(json.dumps({"moved": len(moved)}))
        else:
            print(
                f"Moved {len(moved)} file{'s' if len(moved) != 1 else ''} out of the team repo. "
                "Your files stay here. "
                "Commit the removal when you are ready; older commits keep their copies."
                if moved
                else "Nothing to move."
            )
        return
    s = harness.private_summary(root)
    data = {
        "committed": s["counts"],
        "count": len(s["files"]),
        "config_tracked": s["config_tracked"],
        "pending_agents": config.pending_agents(root),
        "agent_command_ignored": bool(config.pending_agents(root)),
        "lines": private_lines(root),
    }
    _out(args, data, "\n".join(data["lines"]) or "Nothing personal is committed in the team repo.")


def dispatch(args, root: Path) -> bool:
    if args.cmd == "private":
        _private(args, root)
        return True
    if args.cmd == "agents":
        if getattr(args, "sub", None) == "test":
            raise SystemExit(_test(args, root))
        _agents(args, root)
    elif args.cmd == "config":
        _config(args, root)
    elif args.cmd == "share":
        _share(args, root)
    else:
        return False
    return True
