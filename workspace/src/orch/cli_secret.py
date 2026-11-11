"""Secret commands: proof-gated changes and direct delivery to child commands."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from orch import humanproof as hp
from orch import keystore, secretrun, term, tickets
from orch.errors import Refused

SUBCOMMANDS = ("env", "file", "exec", "list", "get", "add", "remove", "profile")


def add_parsers(sub, common) -> None:
    def parser(parent, name):
        return parent.add_parser(name, parents=[common], help=argparse.SUPPRESS)

    commands = parser(sub, "secret").add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        p = parser(commands, name)
        if name in ("env", "file", "exec"):
            p.add_argument("profile")
            p.add_argument("rest", nargs=argparse.REMAINDER)
        elif name == "get":
            p.add_argument("profile")
            p.add_argument("key")
        elif name in ("add", "remove"):
            p.add_argument("name")
            if name == "add":
                p.add_argument("--type", required=True, choices=keystore.TYPES)
                p.add_argument("--file", type=Path)
        elif name == "profile":
            actions = p.add_subparsers(dest="profile_action", required=True)
            for action in ("set", "get-enable", "get-disable", "agents-enable", "agents-disable", "remove"):
                q = parser(actions, action)
                q.add_argument("name")
                if action == "set":
                    for option in ("env", "files", "set", "run", "skill"):
                        q.add_argument("--" + option, action="append", default=[])


def _agent(args) -> bool:
    """An agent tool in the environment, or --by agent:... (an agent that hides its identity looks like a
    script: Level 1)."""
    return bool(tickets.agent_tool()) or str(getattr(args, "by", None) or "").startswith("agent:")


def _person(root, args, op, target):
    who = hp.person_by(root, args, op, target, no_handoff="Do this in the dashboard on this computer.")
    if not who.startswith("human:"):
        raise Refused(hp.AGENT_REFUSED)
    return who


def _pairs(items):
    result = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep or name in result:
            raise Refused("Refused: give each variable once as NAME=VALUE.")
        result[name] = value
    return result


def _file_bytes(path):
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise Refused("Refused: the key file must be a regular file, not a link.")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > keystore.FILE_MAX:
                raise Refused("Refused: the key file must be a regular file of at most 1 MB.")
            value = stream.read(keystore.FILE_MAX + 1)
        if len(value) > keystore.FILE_MAX:
            raise Refused("Refused: a key file can be at most 1 MB.")
        return value
    except OSError:
        raise Refused("Refused: could not read the key file.") from None


def _change_profile(root, args, who):
    """Returns the extra fields for the answer (the resolved command, warnings)."""
    name, action = args.name, args.profile_action
    setting = f"secret.allow_get.{name}"
    agents = f"secret.agents_may_env.{name}"
    extra: dict = {}
    # One lock across record and file: a reader (secretrun._switch_on) never sees one without the other.
    with hp._key_lock(hp.key_dir(root)):
        profiles = keystore.read_profiles(root)
        if action == "set":
            profile = {section: _pairs(getattr(args, section)) for section in ("env", "files", "set")}
            profile.update(allow_get=False, agents_may_env=False)
            if args.run:  # found once, here: stored as the real full path, never searched later
                path, warnings = secretrun.approve_program(root, args.run[0])
                profile["run"] = [path, *args.run[1:]]
                extra = {"command": path, **({"warnings": warnings} if warnings else {})}
            if args.skill:
                profile["skills"] = args.skill
            hp.record_set(root, setting, False, who)
            hp.record_set(root, agents, False, who)
            profiles[name] = profile
        else:
            if name not in profiles:
                raise Refused(f"Refused: there is no profile named {name}.")
            if action == "remove":
                hp.record_set(root, setting, False, who)
                hp.record_set(root, agents, False, who)
                del profiles[name]
            else:
                flag, rec = ("allow_get", setting) if action.startswith("get") else ("agents_may_env", agents)
                enabled = action.endswith("enable")
                hp.record_set(root, rec, enabled, who)  # the record first, then the file
                profiles[name][flag] = enabled
        keystore.write_profiles(root, profiles, sign=frozenset({name}) if action == "set" else frozenset())
    secretrun.record_change(root, "profile." + action.replace("-", "_"), name, who)
    return extra


def dispatch(args, root: Path) -> bool:
    if args.cmd != "secret":
        return False
    action = args.sub
    if action in ("env", "file", "exec"):
        rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
        code = secretrun.run(
            root,
            action,
            args.profile,
            rest,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
            agent=_agent(args),
        )
        sys.stdout.flush()
        sys.stderr.flush()
        if code:
            raise SystemExit(code)
    elif action == "get":
        secretrun.get(
            root,
            args.profile,
            args.key,
            stdout_is_tty=term.is_terminal(sys.stdout),
            out=sys.stdout.buffer,
            agent=_agent(args),
        )
    elif action == "list":
        answer = secretrun.list_answer(root)
        if getattr(args, "json", False):
            print(json.dumps(answer))
        else:
            for item in answer["items"]:
                print(f"{item['name']}\t{item['type']}\t{item['source']}\t{item['state']}")
    elif action in ("add", "remove", "profile"):
        target = args.name
        if action == "profile" and args.profile_action in ("get-enable", "get-disable"):
            target += ":allow_get"
        elif action == "profile" and args.profile_action in ("agents-enable", "agents-disable"):
            target += ":agents_may_env"
        elif action == "profile" and args.profile_action == "remove":
            target += ":remove"
        lowering = action == "profile" and args.profile_action in ("get-disable", "agents-disable")
        if (
            action == "add"
            and args.type == "key-file"
            and args.file is None
            and getattr(args, "proof_stdin", False)
            and hasattr(sys.stdin, "reconfigure")
        ):
            # Preserve arbitrary file bytes and CRLF after the proof's text line.
            sys.stdin.reconfigure(encoding="utf-8", errors="surrogateescape", newline="")
        # Turning a switch OFF needs no proof (the record says "reset"); everything else does.
        if lowering and not getattr(args, "proof_stdin", False):
            who = "reset"
        else:  # a proof handed over with a lowering is checked and spent like any other
            who = _person(root, args, "secret." + action, target)
        extra: dict = {}
        if action == "add":
            if args.file is not None and args.type != "key-file":
                raise Refused("Refused: --file is only for a key-file.")
            if args.type == "key-file":
                # Proof consumption uses TextIOWrapper.readline; its buffered tail must not be bypassed.
                if args.file is not None:
                    value = _file_bytes(args.file)
                elif getattr(args, "proof_stdin", False):
                    value = sys.stdin.read().encode(sys.stdin.encoding or "utf-8", errors="surrogateescape")
                else:
                    value = sys.stdin.buffer.read(keystore.FILE_MAX + 1)
            else:
                value = sys.stdin.read().removesuffix("\n").removesuffix("\r")
            keystore.add(root, args.name, args.type, value)
        elif action == "remove":
            keystore.remove(root, args.name)
        else:
            extra = _change_profile(root, args, who)
        if getattr(args, "json", False):
            print(json.dumps({"ok": True, **extra}))
        else:
            print("Done." + (f" Command: {extra['command']}" if extra.get("command") else ""))
            for w in extra.get("warnings", []):
                print("Note: " + w, file=sys.stderr)
    else:
        raise Refused("Choose an orch secret subcommand: " + ", ".join(SUBCOMMANDS) + ".")
    return True
