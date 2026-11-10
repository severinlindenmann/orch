"""`orch config` (agent settings) and `orch agents`."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from orch import adapters, config, humanproof, tickets
from orch.errors import Refused

KEYS = (
    "workspace.agent",
    "workspace.code",
    "workspace.permissions",
    "workspace.live_idle_minutes",
    "workflow.agents_may_finish",
    "workflow.copies",
    "workflow.copies_max",
    "workflow.copy_setup",
)
TEST_PROMPT = "Reply with the word ok"
TEST_TIMEOUT = 60  # seconds


def add_parsers(sub, common) -> None:
    ag = sub.add_parser("agents", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    t = ag.add_parser("test", parents=[common], help="run an agent once with a trivial prompt")
    t.add_argument("name")
    sh = sub.add_parser("share", parents=[common], help=argparse.SUPPRESS)
    sh.add_argument("state", nargs="?", choices=("on", "off", "status"), default="status")
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


def _person(args, root: Path, op: str, target: str, **kw) -> str:
    """A person's own decision (H1): the proof from the page, or a hand-off. An agent is refused in words."""
    who = humanproof.person_by(root, args, op, target, **kw)
    if not who.startswith("human:"):
        raise Refused(humanproof.AGENT_REFUSED)
    return who


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
            "workflow.copies": config.copies_mode(root),
            "workflow.copies_max": config.copies_max(root),
            "workflow.copy_setup": config.copy_setup(root),
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
        who = None
        if args.value == "on":
            if _actor(args).startswith("agent:"):
                raise Refused(
                    "Only a person can allow agents to mark tickets Done. Ask them to run: "
                    "orch config set workflow.agents_may_finish on"
                )
            who = _person(
                args, root, "config.agents_may_finish", "on", parts={"setting": "agents_may_finish"}
            )
        value = config.set_agents_may_finish(root, args.value == "on", who)
        _out(args, {"workflow.agents_may_finish": value}, f"Agents may mark tickets Done: {args.value}.")
    elif args.sub == "set" and args.key in ("workflow.copies", "workflow.copies_max", "workflow.copy_setup"):
        if _actor(args).startswith("agent:"):  # copy_setup is a command orch runs: only a person chooses it
            raise Refused(f"Only a person can change this. Ask them to run: orch config set {args.key} ...")
        if args.key == "workflow.copies":
            v = config.set_copies_mode(root, args.value)
            text = f"Saved: separate copies = {v}."
        elif args.key == "workflow.copies_max":
            v = config.set_copies_max(root, args.value)
            text = f"Saved: at most {v} separate copies at once."
        else:
            setup = args.value.strip()
            if setup not in (
                "",
                "none",
            ):  # a command orch runs in every new copy: a person's proof, bound to it
                _person(
                    args, root, "config.copy_setup", hashlib.sha256(setup.encode()).hexdigest(),
                    value=args.value, exact=setup,
                )  # fmt: skip
            v = config.set_copy_setup(root, args.value)
            text = f"Saved: a new copy is prepared with: {v}." if v else "Saved: nothing runs in a new copy."
        _out(args, {args.key: v}, text)
    elif args.sub == "set" and args.key == "workspace.code":
        code = config.set_code(root, args.value)
        _out(
            args,
            {"workspace.code": code},
            f"Saved: workspace.code = {code}. New tickets get {code}-<n>; existing keys stay as they are.",
        )
    elif args.sub == "set" and args.key == "workspace.permissions":
        who = _actor(args)
        modes = config.PERMISSION_MODES
        if (
            args.value in modes
            and not who.startswith("agent:")
            and modes.index(args.value) > modes.index(config.permissions(root))
        ):  # giving agents MORE room is a person's decision (lowering is free for anyone)
            who = _person(args, root, "config.permissions", args.value, parts={"mode": args.value})
        mode = config.set_permissions(root, args.value, who)
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
            # a command orch will run for every task: only a person approves it, shown in full (both the
            # command and the live-session one). An agent is refused until private allow (#374) gates what
            # a config.toml command may run (F5): editing config.toml by hand is the same class, Level 2.
            exact = args.command
            if args.interactive:
                exact = f"Command: {args.command}\nLive session command: {args.interactive}"
            _person(
                args,
                root,
                "config.agent_add",
                args.name,
                parts={"name": humanproof.part(args.name)},
                exact=exact,
            )
            config.add_agent(root, args.name, args.command, args.interactive, prompt=args.prompt_via)
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
        if args.state == "on":  # off needs no proof
            _person(args, root, "config.share", "on", parts={})
        (harness.share_on if args.state == "on" else harness.share_off)(root)
    on = harness.share_state(root)
    _out(
        args,
        {"shared": on},
        "Shared with your team: AGENTS.md has the orch entry."
        if on
        else "Not shared: the orch files stay on this computer.",
    )


def dispatch(args, root: Path) -> bool:
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
