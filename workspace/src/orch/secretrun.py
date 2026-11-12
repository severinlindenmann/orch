"""Deliver keys to commands and hide their output (Level 1).

Every use is written to the run's record (`.orch/record`, record.py) as a key.use event BEFORE the command
starts and before any key file is written, without any value; a writer that cannot write (no hider, damaged
record) stops the command. A call outside a run by a PROVEN person (hp1 proof, cli_secret) goes to the
workspace's unattributed run of the day (run r_outside_<yyyymmdd>, ticket t_outside); every other caller
(`agent=True`, the default of the CLI: nothing the caller controls can lower it) outside a run is refused.
set_recorder() replaces the writer (tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.parse

from orch import hider, keystore, launchenv, term
from orch import humanproof as hp
from orch.errors import Refused

_recorder = None
_NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run_ids():
    run, ticket = os.environ.get("ORCH_RUN"), os.environ.get("ORCH_TICKET")
    return (run, ticket) if run and ticket else None


OUTSIDE_DAY_CAP = 5000  # lines of the unattributed run of one day
NO_RUN = "Refused: an agent can use keys only inside an active orch run, where the use is recorded."
BAD_RUN = "Refused: this run is not active, so the use cannot be recorded."


def require_run(root, agent) -> None:
    """The run a use is recorded in. Every caller not proven as a person (`agent=True`) must have one
    (ORCH_RUN + ORCH_TICKET naming a live claim that belong together, like orch's own runs), or the call is
    refused before any key is read. A proven person without a run is not refused (its uses go to the
    unattributed run of the day); with a run named in its environment the same check applies (nothing is
    written into another run's record)."""
    ids = _run_ids()
    if ids is None:
        if agent:
            raise Refused(NO_RUN)
        return
    check_live_run(root, *ids)


def check_live_run(root, run, ticket) -> dict:
    """run and ticket name a live claim that belong together: the claim, or Refused (BAD_RUN)."""
    from orch import runs

    try:
        rec = runs.read(root, ticket)
        ok = bool(rec) and rec.get("run") == run and runs.state(rec) in ("alive", "maybe-stale")
    except Exception:
        ok = False
    if not ok:
        raise Refused(BAD_RUN)
    return rec


def _record_event(root, ev):
    """The record line for an event of this module, or None when there is no run to write it to."""
    ids = _run_ids() or (f"r_outside_{time.strftime('%Y%m%d', time.gmtime())}", "t_outside")
    from orch import tickets

    tool = tickets.agent_tool()
    harness = tool if isinstance(tool, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", tool) else "generic"
    line = {
        "run": ids[0],
        "session": None,
        "agent": "main",
        "parent": None,
        "at": _now(),
        "ticket": ids[1],
        "harness": harness,
        "coverage": "full",
        "via": "broker",
        "kind": ev["kind"],
        "detail": None,
        "outcome": {"ok": ev["outcome"]["ok"], "error": None, "ms": None},
    }
    if ev["kind"] == "key.use":
        refused = ev.get("refused")
        sources = {r["name"]: r["source"] for r in keystore.list_keys(root) if r["state"] != "shadowed"}
        cmd = ev.get("command")
        data = {
            "profile": ev["profile"],
            "command": cmd if cmd and _NAME.match(cmd) else None,
            "skill": ev.get("skill"),
        }
        if refused:
            data["refused"] = refused
            line["outcome"]["error"] = "Not allowed by this profile"
        line.update(
            text=f"Key {ev['key']} not given: {refused}"
            if refused
            else f"Key {ev['key']} handed to {data['command'] or 'a command'}",
            used={
                "kind": "key",
                "name": ev["key"],
                "action": ev["action"],
                "source": sources.get(ev["key"], "workspace"),
                "version": None,
            },
            data=data,
        )
    else:
        line.update(
            text=f"Profile {ev['profile']}: {ev['action']}",
            used=None,
            data={"action": ev["action"], "profile": ev["profile"], "by": ev["by"]},
        )
    return line


def _write_record(root, ev):
    """The default recorder: the run's record writer with a hider built from THIS workspace's key store."""
    from orch import record

    require_run(root, False)  # a named run must be live and match; no run: the unattributed run of the day
    line = _record_event(root, ev)
    if _run_ids() is None:  # a script cannot grow the unattributed run without bound
        read = record.read_run(root, line["run"], seen_by="writer")
        # verified lines only (a planted line can neither raise nor lower it); a legacy run is not counted
        own = [e for e in read.value or [] if record.is_sealed(e)]
        fresh = read.status == "unavailable" and read.reason == "missing"  # nothing recorded yet today
        # a file with planted junk and no verified line counts zero verified lines (a junk line must not stop
        # key uses for the day), but only while the key and the guarded home can be looked at
        junk = (
            read.status == "tampered"
            and read.reason in ("unverified", "content", "removed", "old_key")
            and hp.record_key(root) is not None
            and hp.record_head_state(root, line["run"]) != "unknown"
        )
        # anything else that is not a clean read counts as the cap reached (fail closed)
        # what orch's own chain head says was written counts too: cutting or deleting the file cannot reset it
        head, _ = hp.record_head_read(root, line["run"])
        seen = max(len(own), _head_lines(head))
        if (read.status != "ok" and not fresh and not junk) or seen >= OUTSIDE_DAY_CAP:
            raise Refused(_TOO_MANY)

        def admit(lines, head):  # checked again under the run lock, where the line is written: atomic
            own = [e for e in lines if record.is_sealed(e)]
            if max(len(own), _head_lines(head)) >= OUTSIDE_DAY_CAP:
                raise Refused(_TOO_MANY)
            return True

        try:
            record_writer(root).append(line, admit=admit, spool=False)
        except record.RecordBusy:
            raise Refused("Refused: too many key uses outside a run right now (busy).") from None
        return
    record_writer(root).append(line)


_TOO_MANY = "Refused: too many key uses outside a run today."


def _head_lines(head):
    """Lines orch's chain head says it sealed: its seq without the lines it found there before (legacy)."""
    if not head:
        return 0
    return max(0, int(head["seq"]) - int(head.get("legacy_lines") or 0))


def record_writer(root):
    """The record writer with a hider built from THIS workspace's key store (the one place that wires it)."""
    from orch import record

    return record.RecordWriter(root, hider=hider.Hider(keystore.all_needles(root)))


def set_recorder(fn):
    global _recorder
    _recorder = fn


class Recorder:
    def __init__(self, root, h, action, profile, command):
        self.root, self.h = root, h
        self.action, self.profile, self.command = action, profile, os.path.basename(command)

    def record(self, key, refused=None):
        skill = os.environ.get("ORCH_SKILL", "")
        event = {
            "kind": "key.use",
            "key": key,
            "action": self.action,
            "profile": self.profile,
            "command": self.command,
            "skill": skill if keystore.SKILL_RE.fullmatch(skill) else None,
            "outcome": {"ok": refused is None},
            "refused": refused,
        }

        def hide(value):
            if isinstance(value, str):
                return self.h.hide_text(value)
            if isinstance(value, dict):
                return {self.h.hide_text(k): hide(v) for k, v in value.items()}
            return value

        try:
            (_recorder or _write_record)(self.root, hide(event))
        except Exception:
            if refused is None:
                raise Refused("Refused: this use could not be recorded.") from None


def resolve_program(root, name):
    """The absolute path of a program, searched once and only in the safe folders (never cwd or the caller's
    unsafe PATH entries); an absolute name must be an executable file. Used when a person saves a profile."""
    if os.path.isabs(name):
        path = name
    else:
        path = next(
            (os.path.join(d, name) for d in safe_path_dirs(root) if os.path.isfile(os.path.join(d, name))),
            None,
        )
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise Refused(f"Refused: the program {name} was not found.")
    return path


def record_change(root, action, profile, by):
    """A person's or anyone's change of a profile switch, to the same recorder seam as key.use (best effort:
    a failing recorder never blocks turning a switch off)."""
    try:
        (_recorder or _write_record)(
            root,
            {
                "kind": "secret.change",
                "action": action,
                "profile": profile,
                "by": by,
                "outcome": {"ok": True},
            },
        )
    except Exception:
        pass


SHEBANG_REFUSED = (
    "Refused: this program is a script whose interpreter orch cannot approve (env, a relative path, or a "
    "program in a folder you own). Approve the interpreter itself as the command and give the script as an "
    "argument."
)
USER_OWNED_DEV = (
    "Refused: this program is a macOS developer-tools stub and the developer folder it runs from is missing."
)
USER_OWNED = (
    "Refused: the program or a folder above it belongs to your own user, so an agent running as you could "
    "replace it. Choose a program in a system folder, or approve this exact file as the person."
)

RISKY_PROGRAMS = re.compile(
    r"^(sh|bash|zsh|dash|ksh|fish|csh|tcsh|env|xargs|python[0-9.]*|node|npx|npm|pip[0-9.]*|perl|ruby|php|lua|"
    r"java|git|osascript|pwsh|powershell|cmd|ssh|scp|sftp|rsync|curl|wget|psql|mysql|sqlite3|redis-cli|mongosh)(\.exe)?$",
    re.IGNORECASE,
)


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


XCODE_SELECT_LINK = (
    "/var/db/xcode_select_link"  # macOS: where /usr/bin/git, make, python3 ... really run from
)
ROOT_REFUSED = "Refused: orch does not use keys as root. Run it as a normal user or a service user."
WINDOWS = "Refused: orch secret commands that start programs are not available on Windows yet."


def _refuse_root() -> None:
    if hasattr(os, "getuid") and os.getuid() == 0:
        raise Refused(ROOT_REFUSED)


def _windows() -> bool:
    return os.name == "nt"


def _user_can_write(p: str) -> bool:
    """The current user (not root) can change this file or folder: owner, group, ACL or admin group."""
    if os.getuid() == 0:
        return False
    st = os.stat(p)
    return (st.st_uid != 0 and st.st_uid == os.getuid()) or os.access(p, os.W_OK)


def _chain(real: str) -> list[str]:
    here, chain = real, []
    while True:
        chain.append(here)
        up = os.path.dirname(here)
        if up == here:
            return chain
        here = up


def _check_chain(real: str, ws: str) -> None:
    chain = _chain(real)
    for p in chain:
        if _under(p, ws):
            raise Refused("Refused: the program lies inside this workspace; an agent could change it.")
        st = os.stat(p)
        group_open = st.st_mode & 0o020 and st.st_gid != 0
        if st.st_mode & 0o002 or (group_open and (st.st_uid == os.getuid() or not _user_can_write(p))):
            raise Refused("Refused: the program or a folder above it can be changed by other users.")
    if any(_user_can_write(p) for p in chain):
        raise Refused(USER_OWNED)


def _developer_dir() -> str:
    """Where the macOS command line tools live: what xcode-select points to, else the standard folder."""
    link = os.path.realpath(XCODE_SELECT_LINK)
    return link if os.path.isdir(link) else "/Library/Developer/CommandLineTools"


XCRUN_STUB_DIR = "/usr/bin"  # where macOS keeps its xcrun stubs (git, python3, clang ...)


def _is_xcrun_stub(path: str) -> bool:
    """An xcrun stub names libxcselect inside; one that cannot be read counts as a stub (fail closed)."""
    try:
        with open(path, "rb") as f:
            return b"libxcselect" in f.read(4 * 1024 * 1024)
    except OSError:
        return True


def _in_stub_dir(path: str) -> bool:
    """Is the program in the xcrun stub folder? Compared by file identity (the file system ignores case);
    any error counts as yes."""
    try:
        return os.path.samefile(os.path.dirname(path), XCRUN_STUB_DIR)
    except OSError:
        return True


def _check_xcode(path: str, ws: str) -> None:
    """macOS: /usr/bin/git, make, python3, clang ... are stubs that run the real tool from the developer
    folder (chosen by xcode-select, never by the caller's environment). For such a stub that folder must be
    safe whether or not a tool of that name is found there, and so must the tool. Other /usr/bin programs
    do not depend on it."""
    if sys.platform != "darwin" or not _in_stub_dir(path) or not _is_xcrun_stub(path):
        return
    dev = _developer_dir()
    if not os.path.isdir(dev):  # no developer folder to run the real tool from: not a program to approve
        raise Refused(USER_OWNED_DEV)
    _check_chain(dev, ws)
    name = os.path.basename(path)
    candidates = [os.path.join(dev, "usr", "bin", name)]
    toolchains = os.path.join(dev, "Toolchains")
    for base, rest in (
        (toolchains, ("usr", "bin")),
        (os.path.join(dev, "Platforms"), ("Developer", "usr", "bin")),
    ):
        try:
            candidates += [os.path.join(base, t, *rest, name) for t in sorted(os.listdir(base))]
        except OSError:
            pass
    for c in candidates:
        if os.path.isfile(c):
            _check_chain(os.path.realpath(c), ws)


def approve_program(root, name, *, _depth=0):
    """What a person approves as a profile's `run` program: (real path, warnings). Refused: a relative path;
    the program or a folder above it inside the workspace, changeable by other users, or changeable by the
    current user (owner, group such as admin, or ACL: an agent running as that user can rewrite it). On macOS
    a /usr/bin stub whose real tool lives in a user-writable developer folder is refused too. A program that
    starts with #! needs a system interpreter (env is refused). Interpreters and tools that run arbitrary code
    (sh, python, node, env, git, npm, curl, and database clients that read commands from stdin or run shell
    escapes: psql, mysql, sqlite3, redis-cli, mongosh) are allowed but warned about: approving one is
    approving anything."""
    if _windows():
        raise Refused(WINDOWS)
    _refuse_root()  # no root exemption: nothing counts as user-writable under root
    if not os.path.isabs(name) and (os.sep in name or (os.altsep and os.altsep in name) or "/" in name):
        raise Refused("Refused: give the program as a full path or a plain name, not a relative path.")
    path = resolve_program(root, name)
    real = os.path.realpath(path)
    ws = os.path.realpath(root)
    _check_chain(real, ws)
    _check_xcode(path, ws)
    _check_shebang(root, real, _depth)
    warnings = []
    if RISKY_PROGRAMS.match(os.path.basename(real)) or RISKY_PROGRAMS.match(os.path.basename(name)):
        warnings.append(
            f"{os.path.basename(real)} can run any code: approving it as this profile's command is the same "
            "as approving any command."
        )
    return real, warnings


def _check_shebang(root, real: str, depth: int) -> None:
    """A program that starts with #! is run by its interpreter: that must be an approved system program too
    (env and relative interpreters are refused)."""
    try:
        with open(real, "rb") as f:
            head = f.read(256)
    except OSError:
        raise Refused(SHEBANG_REFUSED) from None
    if not head.startswith(b"#!"):
        return
    parts = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").split()
    if depth >= 2 or not parts or not os.path.isabs(parts[0]) or os.path.basename(parts[0]) == "env":
        raise Refused(SHEBANG_REFUSED)
    approve_program(root, parts[0], _depth=depth + 1)


_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")  # looks like scheme:... (jdbc:, sqlite3:, mailto:)
_WEB_SCHEMES = ("http", "https", "ssh", "git")  # the only schemes whose values are not looked at as paths


def _is_plain_address(value: str) -> bool:
    """A web or git address with no path hidden in it: scheme://..., exact lowercase scheme from the list, no
    whitespace, and no query value that looks like a path (also percent-encoded). Anything else is not an
    address: it goes through the path rules. A value that cannot be parsed is refused."""
    m = re.match(r"^([a-z]+)://", value)
    if not m or m[1] not in _WEB_SCHEMES or re.search(r"\s", value):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
        query = parts.query
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    except ValueError:
        raise Refused("Refused: an address in the command could not be read.") from None
    if "%2f" in query.lower() or "%5c" in query.lower():
        return False
    host_part = urllib.parse.unquote(
        parts.netloc
    )  # a user or host that starts with - is an option, not an address
    if host_part.startswith("-") or any(
        p.startswith("-") for p in host_part.replace("@", ":").split(":")[:2]
    ):
        return False
    if "@-" in host_part:
        return False
    return not any(
        "/" in v or "\\" in v or v[:1] in ("~", ".", "/") for v in (x for pair in pairs for x in pair)
    )


# The program kinds orch knows a safe form for, decided from the real file (program_kind). One table: words
# that must come first, the options (exact words, each at most once, before the operands; None = no value,
# else the slot type of the next word) and the operand slots. Nothing glued (-p22, -av, --opt=x), no
# abbreviation, nothing after the last operand. "copy" operands: exactly one is remote (host:path).
# No sftp: it reads commands from stdin (!cmd runs a local shell, put/lls/get reach any local file), so any
# sftp is "any command" and needs the person's --any-command.
TEMPLATES = {
    "ssh": ((), {"-p": "port", "-l": "user", "-i": "key"}, ("host",)),
    "scp": ((), {"-P": "port", "-i": "key"}, ("copy", "copy")),
    "rsync": ((), dict.fromkeys(["-a", "-r", "-t", "-v", "-z", "-n", "--delete"]), ("copy", "copy")),
    "git": (("ls-remote",), dict.fromkeys(["--heads", "--tags"]), ("url",)),
}
KINDS = (*TEMPLATES, "other")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_USERHOST = rf"(?:[A-Za-z0-9_][A-Za-z0-9._-]{{0,31}}@)?{_LABEL}(?:\.{_LABEL})*"
_REMOTE = rf"{_USERHOST}:(?:[A-Za-z0-9._~+/][A-Za-z0-9._~/+-]{{0,255}})?"  # no ::module, no //, no -path
_SLOTS = {
    "port": r"[1-9][0-9]{0,4}",
    "user": r"[A-Za-z0-9_][A-Za-z0-9._-]{0,31}",
    "host": _USERHOST,
}
SET_AGAIN = "Refused: this profile was saved by an older orch or its program changed. Set the profile again."
NOT_A_FORM = (
    "Refused: orch runs ssh, scp, rsync and git ls-remote only in a few fixed forms, and this command "
    "is not one of them. To allow any command, the person sets the profile with --any-command."
)
REAL_HOME_ANY = (
    "Refused: with your real home folder this program reads settings an agent could change. To allow it, "
    "the person sets the profile with --any-command."
)


def program_kind(real: str, names=TEMPLATES) -> str:
    """What a program really is, from the real file and never from the name it was given: one of `names`
    only when it is the same file (device and inode) as the system program of that name; else "other"."""
    for name in names:
        for d in safe_path_dirs(None):
            try:
                if os.path.samefile(os.path.join(d, name), real):
                    return name
            except OSError:
                pass
    return "other"


def command_template(profile) -> str | None:
    """The template a profile's command must match, None when it has no command or the person allowed any
    command. A command saved without a kind, a program orch has no form for, or a form with the real home
    folder needs the person's --any-command."""
    if not profile.get("run"):
        return None
    if profile.get("kind") not in KINDS:
        raise Refused(SET_AGAIN)
    if profile.get("any_command") is True:
        return None
    if profile["kind"] == "other":
        raise Refused(NOT_A_FORM)
    if profile.get("real_home") is True:
        raise Refused(REAL_HOME_ANY)
    return profile["kind"]


def _slot(slot: str, value: str, files) -> list[str] | None:
    """The paths in one slot value (checked by the path rules after), or None when it does not fit."""
    if slot in _SLOTS:
        return [] if re.fullmatch(_SLOTS[slot], value) else None
    if slot == "key":  # orch's own key file, or a full path
        m = re.fullmatch(r"\{file:([A-Za-z_][A-Za-z0-9_]*)\}", value)
        if m:
            return [] if m[1] in files else None
        return [value] if value.startswith("/") else None
    if slot == "local":
        return [value] if value.startswith("/") and ":" not in value else None
    if slot == "remote":
        return [] if re.fullmatch(_REMOTE, value) and "//" not in value else None
    if slot == "url":
        return [] if _is_plain_address(value) or re.fullmatch(_REMOTE, value) else None
    return None


def _match_template(kind: str, args: list[str], files) -> list[str]:
    """The arguments must fit the template of `kind` exactly (fail closed). Returns the path values."""
    if kind not in TEMPLATES:
        raise Refused(NOT_A_FORM)
    first, options, operands = TEMPLATES[kind]
    if args[: len(first)] != list(first):
        raise Refused(NOT_A_FORM)
    i, seen, paths = len(first), set(), []
    while i < len(args) and args[i] in options and args[i] not in seen:
        seen.add(args[i])
        if options[args[i]] is not None:
            got = _slot(options[args[i]], args[i + 1], files) if i + 1 < len(args) else None
            if got is None:
                raise Refused(NOT_A_FORM)
            paths += got
            i += 1
        i += 1
    rest = args[i:]
    if len(rest) != len(operands):
        raise Refused(NOT_A_FORM)
    remote = 0
    for slot, value in zip(operands, rest, strict=True):
        if slot == "copy":
            is_remote = _slot("remote", value, files) is not None
            remote += is_remote
            slot = "remote" if is_remote else "local"
        got = _slot(slot, value, files)
        if got is None:
            raise Refused(NOT_A_FORM)
        paths += got
    if "copy" in operands and remote != 1:
        raise Refused(NOT_A_FORM)
    return paths


def check_arguments(root, arguments, kind=None, files=()) -> None:
    """One fail-closed rule for the arguments of a profile's command and for its `set` values. With a `kind`
    the arguments must fit that program's template (_match_template) and only its path slots go on. A value
    with a path separator must be an absolute path as a whole (no -xVALUE, --opt=/path, @/path or relative
    path), must not go through a link, and neither it nor any parent may be inside the workspace or
    changeable by you (an agent running as you could change it). Only plain http, https, ssh and git
    addresses are not paths."""
    ws = os.path.realpath(root)
    for arg in arguments if kind is None else _match_template(kind, list(arguments), files):
        if re.match(r"^[^\s/]*@-", arg) or re.match(r"^[^\s/:]+:-", arg):
            raise Refused("Refused: an argument looks like an option hidden in an address.")
        if _is_plain_address(arg):
            continue
        if (
            "/" not in arg
            and "\\" not in arg
            and not (os.altsep and os.altsep in arg)
            and not _SCHEME.match(arg)
        ):
            continue
        if not os.path.isabs(arg) or "\0" in arg or "\\" in arg:
            raise Refused(
                "Refused: an argument with a path must be a full path on its own, "
                "not inside an option and not relative."
            )
        real = os.path.realpath(arg)
        if real != os.path.normpath(arg):
            raise Refused("Refused: a path in the command goes through a link; give the real path.")
        if not os.path.exists(real):
            raise Refused("Refused: a file named in the command does not exist.")
        _check_chain(real, ws)
        if not os.path.isfile(real):
            raise Refused("Refused: a path in the command must be a regular file.")


def use_target(profile: str, mode: str, argv) -> str:
    """The target of a person's proof for one call: the profile, the mode and the exact command words."""
    digest = hashlib.sha256("\0".join([mode, *argv]).encode("utf-8", "surrogateescape")).hexdigest()
    return f"{profile}:use:{digest}"


def safe_path_dirs(root):
    """The only folders a plain program name is searched in, and the child's PATH: fixed system folders that
    belong to root and nobody else can change. Never the caller's PATH (an agent can prepend to it)."""
    fixed = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    if os.name == "nt":
        return [
            p
            for p in [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
            if os.path.isdir(p)
        ]
    result = []
    for p in fixed:
        try:
            info = os.stat(p)
        except OSError:
            continue
        if info.st_uid == 0 and not info.st_mode & 0o022 and p not in result:
            result.append(p)
    return result


def _environment(dirs, private, real_home=False):
    names = "LANG LC_ALL LC_CTYPE TERM TZ USER LOGNAME".split()
    if os.name == "nt":
        names += "SYSTEMROOT COMSPEC PATHEXT USERPROFILE APPDATA LOCALAPPDATA TEMP TMP".split()
    env = {
        k: os.environ[k]
        for k in names
        if k in os.environ and len(os.environ[k]) <= 200 and "\0" not in os.environ[k]
    }
    env["PATH"] = os.pathsep.join(dirs)
    # H3: the child works in a private empty folder: no planted config, scripts or modules of the caller's
    # cwd or home are loaded. Programs that read their config from the real home are not contained unless a
    # person approved real_home (then HOME is the real one; the cwd stays private).
    home = launchenv.user_home() if real_home else None
    env["HOME"] = str(home if home is not None else private)
    if os.name == "nt":
        env["TEMP"] = env["TMP"] = str(private)
    env["TMPDIR"] = str(private)  # never the caller's (key-bearing temp files land only in our folder)
    return env


def neutral_ssh(command, env, dirs, h, private=None):
    """Every ssh orch starts reads no ssh or git config an agent could write (OpenSSH reads ~/.ssh/config
    from the account's home, not $HOME): ssh, scp and sftp get -F none, rsync gets its ssh from orch (-e),
    git gets GIT_SSH_COMMAND and no system, global or repository config. The kind comes from the real file."""
    kind = program_kind(os.path.realpath(command[0]), (*TEMPLATES, "sftp"))
    if kind in ("ssh", "scp", "sftp"):
        return [command[0], "-F", "none", *command[1:]]
    if kind not in ("rsync", "git"):
        return command
    ssh = _program("ssh", dirs, h) + " -F none"
    if kind == "rsync":
        return [command[0], "-e", ssh, *command[1:]]
    if private is None:
        raise Refused("Refused: could not run the command.")
    private = os.path.abspath(str(private))
    for k in [k for k in env if k.upper().startswith("GIT_") or "ASKPASS" in k.upper()]:
        del env[k]  # nothing inherited or from the profile steers git: only what is set below
    # No repository discovery: a .git an agent planted in a parent folder of the private cwd (with
    # core.sshCommand, credential.helper, url.*.insteadOf, hooks ...) is never read. GIT_DIR names a folder
    # that does not exist; the ceiling stops any upward search at the private folder's parent.
    config = {
        "credential.helper": "",
        "core.sshCommand": ssh,
        "core.fsmonitor": "false",
        "core.hooksPath": os.devnull,
        "core.askPass": "",
        "protocol.allow": "never",
        "protocol.https.allow": "always",
        "protocol.http.allow": "always",
        "protocol.ssh.allow": "always",
    }
    env.update(
        GIT_DIR=os.path.join(private, "no-git-dir"),
        GIT_CEILING_DIRECTORIES=os.path.dirname(private),
        GIT_SSH_COMMAND=ssh,
        GIT_SSH_VARIANT="ssh",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ALLOW_PROTOCOL="https:http:ssh",
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_COUNT=str(len(config)),
    )
    for i, (k, v) in enumerate(config.items()):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return command


def _program(name, dirs, h):
    paths = (
        [os.path.abspath(name)]
        if os.sep in name or (os.altsep and os.altsep in name)
        else [os.path.join(d, name) for d in dirs]
    )
    for path in paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise Refused(h.hide_text(f"Refused: the program {name} was not found."))


def _pid_alive(pid: int) -> bool:
    """Is a process with this pid still running? Unsure counts as alive (nothing is deleted)."""
    if os.name == "nt":
        try:
            import ctypes

            kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return kernel.GetLastError() != 87  # 87 = invalid parameter: no such process
            code = ctypes.c_ulong()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            return not ok or code.value == 259  # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True
    return True


def sweep_tmp(root):
    home = hp.guarded_home(root)
    tmp = home / "keys" / "tmp"
    if not tmp.exists() and not tmp.is_symlink():
        return
    hp._private_dir(tmp, home)
    for p in tmp.iterdir():
        if not re.fullmatch(r"\d+-[0-9a-f]{16}", p.name):
            continue
        info = p.lstat()
        if not stat.S_ISDIR(info.st_mode):
            continue
        if not _pid_alive(int(p.name.split("-", 1)[0])):
            shutil.rmtree(p, ignore_errors=True)  # one undeletable folder must not stop every use


AGENT_COMMAND = (
    "Refused: agents may only run this profile's own command. "
    "Ask the person to allow any command, or use orch secret exec {p}."
)


def _switch_on(root, name, flag) -> bool:
    """A profile switch (allow_get, agents_may_env): the file flag AND the person's record. The file is read
    again under the key lock, the same lock a person's enable holds across record and file, so a reader never
    writes an off record over an enable in progress."""
    with hp._key_lock(hp.key_dir(root)):
        profile = _verified(root, name)
        return hp.effective(root, f"secret.{flag}.{name}", bool(profile and profile.get(flag) is True))


def _agent_may_run(root, name, profile, command) -> bool:
    """The one gate for an agent's env, file AND exec call (`command` is the full argv, for exec the profile's
    `run` plus any extra arguments): any command only with agents_may_env (file flag AND a person's record);
    else exactly the profile's own `run` (same argv, absolute program, no extra arguments)."""
    if _switch_on(root, name, "agents_may_env"):
        return True
    run = profile.get("run")
    return bool(run) and os.path.isabs(run[0]) and list(command) == list(run)


def _verified(root, name):
    """The profile `name` with its body MAC-verified (None when there is no such profile). A body edited
    outside orch, or without a person's MAC, is refused; the variables are re-checked too (a forged file
    cannot inject loader/interpreter variables even if it carried a valid MAC for them)."""
    profile = keystore.read_profiles(root).get(name)
    if profile is None:
        return None
    if not hp.profile_verified(root, name, profile):
        raise Refused("Refused: " + hp.PROFILE_CHANGED + ".")
    keystore._profile_check({name: profile}, set())  # the variable rules again at run time (same code as set)
    for sect in ("env", "files", "set"):
        if any(
            keystore.env_denied(v, sect) or (sect == "set" and not keystore.set_name_ok(v))
            for v in profile.get(sect, {})
        ):
            raise Refused("Refused: this key profile sets a variable orch does not allow.")
    return profile


def _profile(root, name):
    profile = _verified(root, name)
    if profile is None:
        raise Refused(f"Refused: there is no profile named {name}.")
    return profile


def _value(root, name, recorder):
    try:
        return keystore.get_value(root, name)
    except Refused as exc:
        if str(exc) in ("There is no such key.", "The key file is missing."):
            recorder.record(name, "missing")
        raise


def _pump(pipe, out, h, errors):
    stream = hider.HidingStream(h, binary=True)
    try:
        with pipe:
            while chunk := pipe.read1(65536):
                out.write(stream.feed(chunk, now=True))
                out.flush()
            out.write(stream.close())
            out.flush()
    except BaseException:
        errors.append(True)


def _kill_group(pid: int, grace: float = 2.0) -> None:
    """End every process of the child's own session: TERM, then KILL after a short grace. Nothing left holds a
    key or a pipe."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                os.killpg(pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.02)


def _child(command, env, h, stdout, stderr, cwd=None):
    child = None
    threads, errors = [], []
    main = threading.current_thread() is threading.main_thread()
    sigs = [getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGQUIT") if hasattr(signal, n)]
    old = {s: signal.getsignal(s) for s in sigs} if main else {}
    state = {"spawning": False, "sig": None}
    interactive = term.is_terminal(sys.stdin)
    # Own session when no terminal input is needed, so a hangup of ours does not leave it running with a key
    # (a child can still open /dev/tty: known limit).
    own_session = not interactive and os.name == "posix"

    def ignore(signum, frame):
        pass

    def stop(signum, frame):
        # The first signal wins; the cleanup below is not interrupted by more. A Python no-op rather than
        # SIG_IGN: a signal already pending would otherwise be reported as "ignored due to race condition".
        for s in sigs:
            signal.signal(s, ignore)
        if state["spawning"]:  # between starting the child and knowing it: act on it right after
            state["sig"] = signum
            return
        raise SystemExit(128 + signum)

    try:
        if main:
            for s in sigs:
                signal.signal(s, stop)
        state["spawning"] = True
        try:
            child = subprocess.Popen(
                command,
                env=env,
                cwd=cwd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=own_session,
            )
        finally:
            state["spawning"] = False
        if state["sig"] is not None:
            raise SystemExit(128 + state["sig"])
        for pipe, out in ((child.stdout, stdout), (child.stderr, stderr)):
            thread = threading.Thread(target=_pump, args=(pipe, out, h, errors), daemon=True)
            thread.start()
            threads.append(thread)
        code = child.wait()
        for thread in threads:
            thread.join(2.0)
        if own_session and any(t.is_alive() for t in threads):
            _kill_group(child.pid)  # something kept the pipes open after the command ended
            for thread in threads:
                thread.join(2.0)
        if errors:
            raise Refused("Refused: could not run the command.")
        return 128 - code if code < 0 else code
    finally:
        if child is not None:
            if own_session:
                _kill_group(child.pid)  # also anything the command left running with the key
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for s, handler in old.items():
            signal.signal(s, handler)


def run(root, mode, profile_name, argv, *, stdout, stderr, agent) -> int:
    temp = None
    h = None
    try:
        if _windows():
            raise Refused(WINDOWS)
        _refuse_root()
        require_run(root, agent)  # before any key or file is touched
        profile = _profile(root, profile_name)
        if agent and profile.get("real_home") is True:  # the real HOME undoes the containment: person only
            raise Refused("Refused: this profile uses your real home folder, so only you can run it.")
        check_arguments(root, profile.get("set", {}).values())
        if mode not in ("env", "file", "exec"):
            raise Refused("Refused: unknown secret command.")
        sweep_tmp(root)
        command = list(argv)
        if mode == "exec":
            if not profile.get("run"):
                raise Refused("Refused: this profile has no command to run.")
            if not os.path.isabs(profile["run"][0]):
                raise Refused(
                    "Refused: this profile's command is not a full path. "
                    "Ask the person to set the profile again."
                )
            command = profile["run"] + command
        if not command:
            raise Refused("Refused: give a command to run.")
        run0 = (profile.get("run") or [None])[0]
        if run0 is not None and command[0] == run0:  # the profile's own program, in every mode
            if not os.path.isabs(run0):
                raise Refused(
                    "Refused: this profile's command is not a full path. Ask the person to set it again."
                )
            template = command_template(profile)
            real, _ = approve_program(root, run0)  # still a safe, existing program now
            if program_kind(real) != profile["kind"]:
                raise Refused(SET_AGAIN)
            if template:  # the whole command as it will run, extra words included
                check_arguments(root, command[1:], template, profile.get("files", {}))
            else:
                check_arguments(root, profile["run"][1:])
        elif run0 is not None:
            command_template(profile)  # an old profile, or one not in a fixed form, runs nothing
        if mode == "env" and not profile.get("env") and profile.get("files"):
            raise Refused("Refused: this profile needs files. Use orch secret file.")
        needles = keystore.all_needles(root)
        h = hider.Hider(needles)
        recorder = Recorder(root, h, mode, profile_name, command[0])
        if agent and not _agent_may_run(root, profile_name, profile, command):
            for name in dict.fromkeys([*profile.get("env", {}).values(), *profile.get("files", {}).values()]):
                recorder.record(name, "agent_command")
            raise Refused(AGENT_COMMAND.format(p=profile_name))
        files = profile.get("files", {}) if mode != "env" else {}
        names = list(dict.fromkeys([*profile.get("env", {}).values(), *files.values()]))
        values = {name: _value(root, name, recorder) for name in names}
        if not needles:
            raise Refused("Refused: no keys are available for hiding output.")
        dirs = safe_path_dirs(root)
        command[0] = _program(command[0], dirs, h)
        home = hp.guarded_home(root)
        parent = home / "keys" / "tmp"
        candidate = parent / f"{os.getpid()}-{secrets.token_hex(8)}"
        private = candidate / "~home"  # empty: the child's cwd and HOME (a key name can never be "~home")
        env = _environment(dirs, private, profile.get("real_home") is True)
        env.update(profile.get("set", {}))
        command = neutral_ssh(command, env, dirs, h, private)
        types = {row["name"]: row["type"] for row in keystore.list_keys(root) if row["state"] != "shadowed"}
        for var, name in profile.get("env", {}).items():
            value = values[name]
            if isinstance(value, bytes):
                raise Refused("Refused: a key file goes in the profile's files section.")
            env[var] = (
                json.dumps(json.loads(value), separators=(",", ":"), ensure_ascii=False)
                if types.get(name) == "json"
                else value
            )
        for name in names:  # recorded BEFORE any key file is written (a failing record leaves nothing behind)
            recorder.record(name)
        hp._private_dir(parent, home)
        candidate.mkdir(mode=0o700)
        temp = candidate
        hp.winacl.set_private(temp, True)
        hp._private_dir(temp, parent)
        private.mkdir(mode=0o700)
        if files:
            paths = {}
            for var, name in files.items():
                if name not in paths:
                    path = temp / name
                    value = values[name]
                    keystore._write_private_bytes(
                        path, value if isinstance(value, bytes) else value.encode("utf-8")
                    )
                    paths[name] = str(path)
                env[var] = paths[name]
            command = [
                re.sub(
                    r"\{file:([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: env[m[1]] if m[1] in files else m[0], arg
                )
                for arg in command
            ]
        return _child(command, env, h, stdout, stderr, cwd=str(private))
    except Refused as exc:
        raise Refused(h.hide_text(str(exc)) if h else str(exc)) from None
    except Exception:
        raise Refused("Refused: could not run the command.") from None
    finally:
        if temp is not None:
            try:
                shutil.rmtree(temp)
            except OSError:
                raise Refused("Refused: could not remove the temporary key files.") from None


def _get(root, profile_name, key, *, stdout_is_tty, out, agent) -> None:
    if _windows():
        raise Refused(WINDOWS)
    _refuse_root()
    require_run(root, agent)
    profile = _profile(root, profile_name)
    h = hider.Hider(keystore.all_needles(root))
    recorder = Recorder(root, h, "get", profile_name, "")

    def refuse(code, message):
        recorder.record(key, code)
        raise Refused(h.hide_text(message))

    if key not in {*profile.get("env", {}).values(), *profile.get("files", {}).values()}:
        refuse("not_in_profile", f'Refused: the profile "{profile_name}" does not hold the key "{key}".')
    if agent:  # printing a key is for a proven person's pipelines only, whatever allow_get says
        refuse("get_agent", "Refused: only the person can print a key. Use orch secret env instead.")
    if not _switch_on(root, profile_name, "allow_get"):
        refuse(
            "get_off",
            f'Refused: the profile "{profile_name}" does not allow printing keys. '
            f"Use orch secret env {profile_name} -- <command>.",
        )
    if stdout_is_tty:
        refuse("get_to_terminal", "Refused: this would show the key on a screen. Pipe the output.")
    value = _value(root, key, recorder)
    recorder.record(key)
    out.write(value if isinstance(value, bytes) else value.encode("utf-8"))
    out.flush()


def list_answer(root) -> dict:
    try:  # display only: a damaged file lists the keys with no profiles
        profiles = {  # a profile changed outside orch counts for nothing (it cannot run)
            n: v for n, v in keystore.read_profiles(root).items() if hp.profile_verified(root, n, v)
        }
    except Refused:
        profiles = {}
    items = []
    for row in keystore.list_keys(root):
        members = sorted(
            p
            for p, v in profiles.items()
            if row["name"] in {*v.get("env", {}).values(), *v.get("files", {}).values()}
        )
        state = "managed" if row["source"] == "admin" else "ok" if members else "unused"
        if row["state"] == "needs-reentry":
            state = "needs-reentry"
        items.append(
            {
                "name": row["name"],
                "type": row["type"],
                "source": row["source"],
                "profiles": members,
                "state": state,
                "last_used": None,
                "uses_7d": 0,
                "shadowed": row["state"] == "shadowed",
            }
        )
    return {"items": items, "next": None}


def get(root, profile_name, key, *, stdout_is_tty, out, agent) -> None:
    try:
        _get(root, profile_name, key, stdout_is_tty=stdout_is_tty, out=out, agent=agent)
    except Refused:
        raise
    except Exception:
        raise Refused("Refused: could not print the key.") from None
