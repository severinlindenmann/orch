"""Secret commands: changes and direct delivery to child commands."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from orch import humanproof as hp
from orch import keystore, secretrun, secretscan, term, tickets
from orch.errors import Refused

SUBCOMMANDS = ("env", "file", "exec", "list", "get", "add", "remove", "profile", "scan")


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
                    for option in ("env", "files", "set", "run", "skill", "extra"):
                        q.add_argument("--" + option, action="append", default=[])
                    q.add_argument(
                        "--real-home", action="store_true"
                    )  # person: the command may see your home
                    q.add_argument("--any-command", action="store_true")  # person: no fixed form needed


def _agent(root, args, profile, mode, words) -> bool:
    """True when the caller is an agent: an agent tool in the environment, or --by agent:..."""
    return bool(tickets.agent_tool() or str(getattr(args, "by", None) or "").startswith("agent:"))


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
    extra: dict = {}
    with hp._key_lock(hp.key_dir(root)):
        profiles = keystore.read_profiles(root)  # a damaged file refuses here
        if action == "set":
            profile = {section: _pairs(getattr(args, section)) for section in ("env", "files", "set")}
            profile.update(allow_get=False, agents_may_env=False)
            secretrun.check_arguments(root, profile["set"].values())
            if args.real_home:
                profile["real_home"] = True
            if args.run:  # found once, here: stored as the real full path, never searched later
                path, warnings = secretrun.approve_program(root, args.run[0])
                profile["run"] = [path, *args.run[1:]]
                profile["kind"] = secretrun.program_kind(path)  # from the real file, not the name typed
                if args.any_command:
                    profile["any_command"] = True
                template = secretrun.command_template(profile)
                secretrun.check_arguments(root, args.run[1:], template, profile["files"])
                extra = {"command": path, **({"warnings": warnings} if warnings else {})}
            if args.skill:
                profile["skills"] = args.skill
            if args.extra:
                profile["extra"] = list(args.extra)
            profiles[name] = profile
        else:
            if action == "remove":
                if name not in profiles:
                    raise Refused(f"Refused: there is no profile named {name}.")
                del profiles[name]
            elif name not in profiles:
                raise Refused(f"Refused: there is no profile named {name}.")
            else:
                flag = "allow_get" if action.startswith("get") else "agents_may_env"
                enabled = action.endswith("enable")
                profiles[name][flag] = enabled
        keystore.write_profiles(root, profiles)
    secretrun.record_change(root, "profile." + action.replace("-", "_"), name, who)
    return extra


def _scan(args, root: Path) -> None:
    """`orch secret scan`: text on stdin in, what looks like a secret out (kind and line, never the text)."""
    data = sys.stdin.buffer.read(secretscan.MAX_BYTES + 1)
    if secretscan.too_large(len(data)):
        err = Refused("The text is bigger than 1 MB. Scan it in smaller parts.")
        err.extra = {"code": "too_large"}
        raise err
    found = secretscan.find(data.decode("utf-8", "replace"), root)
    if not found:
        print(json.dumps({"found": []}) if getattr(args, "json", False) else "No secrets found.")
        return
    err = Refused(secretscan.refusal(found))
    err.extra = {"code": "refused", "found": found}
    raise err


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
            agent=_agent(root, args, args.profile, action, rest),
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
            agent=_agent(root, args, args.profile, "get", [args.key]),
        )
    elif action == "list":
        answer = secretrun.list_answer(root)
        if getattr(args, "json", False):
            print(json.dumps(answer))
        else:
            for item in answer["items"]:
                print(f"{item['name']}\t{item['type']}\t{item['source']}\t{item['state']}")
    elif action == "scan":
        _scan(args, root)
    elif action in ("add", "remove", "profile"):
        who = tickets.acting_by(args)
        extra: dict = {}
        if action == "add":
            if args.file is not None and args.type != "key-file":
                raise Refused("Refused: --file is only for a key-file.")
            if args.type == "key-file":
                if args.file is not None:
                    value = _file_bytes(args.file)
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
