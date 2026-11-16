"""Scripts: a repeat that runs a command on this computer instead of starting an agent.

The command lives only in this computer's `.orch/config.toml` (not committed, never synced), as
`[automation.scripts.<name>] command = ["prog", "arg", ...]`. A ticket names the script (`ext.automation.script`), never
the command, so a ticket that arrives by git or sync can never make this computer run something. The command runs
without a shell, in the workspace folder, in the background; its output goes to `.orch/run/logs/<ticket>-script-*.log`
and its exit code to runs.jsonl (the dashboard's run history). One run per ticket at a time.

The trust rule of agent commands (contracts/local-files.md) holds here too: a script runs only if a person approved
exactly that entry on this computer. The allowed entries are hashes (workspace path, name, command) in the orch home
(`automation-script-allowed.json`), never in the workspace. `script add` by a person approves what they typed; an
agent's entry waits until a person runs `script allow <name> --key <key>`. Any change asks again; any error = not approved.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_ARGS = 64
MAX_ARG = 4096
TABLE = re.compile(r"^\s*\[\s*automation\s*\.\s*scripts\s*\.\s*(\"?)([a-z][a-z0-9-]{0,31})\1\s*\]\s*(#.*)?$")
HEADER = re.compile(r"^\s*\[")


class ScriptError(Exception):
    """Plain words for the person."""


def _config(root: Path) -> Path:
    return root / ".orch" / "config.toml"


def _valid_command(cmd: object) -> list[str] | None:
    if (
        isinstance(cmd, list)
        and 0 < len(cmd) <= MAX_ARGS
        and all(isinstance(a, str) and a and len(a) <= MAX_ARG and "\x00" not in a for a in cmd)
    ):
        return list(cmd)
    return None


def load(root: Path) -> dict[str, list[str]]:
    """name -> argv of every well-formed [automation.scripts.<name>] entry. A broken file or entry gives nothing."""
    p = _config(root)
    if p.is_symlink() or not p.is_file():
        return {}
    try:
        t = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return {}
    table = (t.get("automation") or {}).get("scripts") if isinstance(t.get("automation"), dict) else None
    out = {}
    for name, entry in (table or {}).items() if isinstance(table, dict) else ():
        cmd = _valid_command(entry.get("command")) if isinstance(entry, dict) else None
        if NAME_RE.match(str(name)) and cmd:
            out[name] = cmd
    return out


def command(root: Path, name: object) -> list[str] | None:
    """The argv of an APPROVED script, else None (unknown, broken or not allowed on this computer)."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    argv = load(root).get(name)
    return argv if argv and approved(root, name, argv) else None


def defined(root: Path, name: object) -> bool:
    return isinstance(name, str) and name in load(root)


# ---- allowed scripts (orch home, per computer)


def _allowed_path() -> Path:
    from orch import addons

    return addons.home() / "automation-script-allowed.json"


def key(root: Path, name: str, argv: list[str]) -> str:
    return hashlib.sha256(json.dumps([str(root.resolve()), name, argv]).encode("utf-8")).hexdigest()


def approved(root: Path, name: str, argv: list[str]) -> bool:
    try:
        data = json.loads(_allowed_path().read_text(encoding="utf-8"))
        return isinstance(data, list) and key(root, name, argv) in data
    except Exception:  # noqa: BLE001 - fail closed on anything
        return False


def _approve(root: Path, name: str, argv: list[str]) -> None:
    p = _allowed_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except (OSError, ValueError):
        data = []
    data = data if isinstance(data, list) else []
    k = key(root, name, argv)
    if k in data:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(json.dumps(data[-500:] + [k]), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def an_agent() -> str | None:
    """The agent tool this process runs under (core's rule), else None. Without core: count as an agent."""
    try:
        from orch import tickets
    except ImportError:
        return "unknown"
    return tickets.agent_tool()


def shown(argv: list[str]) -> str:
    """The command as a person reads it: each argument quoted where needed, so the text maps back to exactly one argv
    (["rm -rf ~"] and ["rm", "-rf", "~"] never look the same)."""
    import shlex

    return shlex.join(argv)


def showable(argv: list[str]) -> bool:
    """Plain printable text only (what is shown is exactly what is hashed); core's rule for agent commands."""
    import unicodedata

    text = " ".join(argv)
    return len(text) <= 500 and all(
        c == " " or unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs")
        for c in text
    )


def allow(root: Path, name: str, given_key: str) -> None:
    """A person's yes for exactly ONE entry, and only if it is still what was shown (the key matches now)."""
    if an_agent():
        raise ScriptError("Only a person can allow a script, not an agent.")
    argv = load(root).get(name) if isinstance(name, str) else None
    if argv is None:
        raise ScriptError(f"There is no script named {name} on this computer.")
    if not isinstance(given_key, str) or key(root, name, argv) != given_key:
        raise ScriptError("That script changed since you looked. Look again: orch automation script list")
    if not showable(argv):
        raise ScriptError(
            "That command cannot be shown safely (too long or odd characters), so it cannot be allowed."
        )
    _approve(root, name, argv)


def _toml_str(s: str) -> str:
    # json's escapes (\" \\ \n \uXXXX ...) are all valid in a TOML basic string; no "\/" is ever written
    return json.dumps(s, ensure_ascii=True)


def add(root: Path, name: str, cmd: list[str]) -> None:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ScriptError("A script name may only have a-z, 0-9 and - (up to 32, starting with a letter).")
    argv = _valid_command(cmd)
    if not argv:
        raise ScriptError(
            "Say the command after --, for example: orch automation script add backup -- ./backup.sh"
        )
    p = _config(root)
    if p.is_symlink():
        raise ScriptError(f"{p} is a symbolic link; orch does not write to it.")
    if p.exists():
        try:
            tomllib.loads(p.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            raise ScriptError(f"The settings file cannot be read ({e}). Fix it first.") from None
    if name in load(root) or any(TABLE.match(x) and TABLE.match(x)[2] == name for x in _lines(p)):
        raise ScriptError(
            f"A script named {name} exists already. Remove it first: orch automation script remove {name}"
        )
    block = f"\n[automation.scripts.{name}]\ncommand = [{', '.join(_toml_str(a) for a in argv)}]\n"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    new = old + ("" if not old or old.endswith("\n") else "\n") + block
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:  # e.g. an [automation.scripts] written as an inline table by hand
        raise ScriptError(f"The script could not be added to the settings file ({e}).") from None
    _write(p, new)
    if not an_agent() and load(root).get(name) == argv and showable(argv):
        _approve(root, name, argv)  # a person typed it here: approve ONLY what they typed


def remove(root: Path, name: str) -> bool:
    p = _config(root)
    if p.is_symlink() or not p.is_file():
        return False
    lines = _lines(p)
    keep, skipping, found = [], False, False
    for line in lines:
        m = TABLE.match(line)
        if m:
            skipping = m[2] == name
            found = found or skipping
        elif skipping and HEADER.match(line):
            skipping = False
        if not skipping:
            keep.append(line)
    if not found:
        return False
    new = "".join(keep)
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        raise ScriptError(
            f"The script could not be removed from the settings file ({e}). Edit it by hand."
        ) from None
    _write(p, new)
    return True


def _lines(p: Path) -> list[str]:
    try:
        return p.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return []


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".config-{os.getpid()}-{time.time_ns()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | runfiles.NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def _pidfile(root: Path, tid: str) -> Path:
    from .runner import sdir

    return sdir(root) / f"script-{tid}.json"


def busy(root: Path, tid: str) -> bool:
    """A script run for this ticket is going on (its pid file names a live process with the recorded start time)."""
    try:
        rec = runfiles.read_json(_pidfile(root, tid))
    except RuntimeError:
        return True  # a link or an unreadable file: start nothing
    if not rec:
        return False
    pid = rec.get("pid")
    return runfiles.alive(pid) and runfiles.proc_start(pid) == rec.get("started")


def _claim(root: Path, tid: str) -> bool:
    """Write this process's pid file; False when another live run holds it."""
    p = _pidfile(root, tid)
    if busy(root, tid):
        return False
    runfiles.remove(p)  # a stale file of a run that ended without cleaning up
    me = os.getpid()
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | runfiles.NOFOLLOW, 0o600)
    except FileExistsError:
        return False  # another run claimed it this very moment
    with os.fdopen(fd, "w") as f:
        json.dump({"pid": me, "started": runfiles.proc_start(me) or ""}, f)
    return True


def runner_argv(root: Path, tid: str) -> list[str]:
    """-P: the workspace folder is never on the import path (a planted orch_automation.py there is not run)."""
    import sys

    return [sys.executable, "-P", "-m", "orch_automation", "--dir", str(root), "script", "run", tid]


def _start_runner(root: Path, tid: str) -> None:
    """`orch automation script run <tid>` in the background; it waits for the script and records the result."""
    from orch.procs import background_popen_kwargs

    from .runner import sdir

    with runfiles.open_append(sdir(root) / "scripts.log") as out:
        subprocess.Popen(
            runner_argv(root, tid),
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "ORCH_ROOT": str(root.resolve())},
            **background_popen_kwargs(),
        )


def launch(root: Path, tid: str, name: str) -> tuple[str, str | None]:
    """Start `orch automation script run <tid>` in the background. ("started"|"pending"|"failed", reason)."""
    if command(root, name) is None:
        return "failed", missing(root, name)
    if busy(root, tid):
        return "pending", None
    try:
        _start_runner(root, tid)
    except OSError as e:
        return "failed", f"the script could not be started ({e.__class__.__name__})"
    return "started", None


def missing(root: Path, name: str) -> str:
    if defined(root, name):
        return (
            f"the script {name} is not allowed on this computer yet. "
            f"A person allows it once: orch automation script list, then orch automation script allow {name} --key <key>"
        )
    return (
        f"there is no script named {name} on this computer. "
        f"Add it: orch automation script add {name} -- <command>"
    )


def run(root: Path, tid: str, name: str, at: str, on_fail) -> int:
    """Run the script in the foreground and wait: log file, runs.jsonl line, one question when it failed.
    Returns its exit code (75 = another run of it is going on, nothing was started)."""
    from .runner import history

    argv = command(root, name)
    if argv is None:
        on_fail(missing(root, name))
        return 2
    if not _claim(root, tid):
        return 75
    try:
        logs = root / ".orch" / "run" / "logs"
        for part in (root / ".orch" / "run", logs):
            if part.is_symlink():
                on_fail(f"{part} is a symbolic link; the script was not started")
                return 2
        logs.mkdir(parents=True, exist_ok=True)
        rel = f".orch/run/logs/{tid}-script-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
        t0 = time.time()
        with runfiles.open_append(root / rel) as out:
            try:
                code = subprocess.run(
                    argv,
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "ORCH_ROOT": str(root.resolve()), "ORCH_TICKET": tid},
                    check=False,
                ).returncode
            except OSError as e:
                out.write(f"orch: the script could not be started: {e}\n")
                code = 127
        history(root, tid, at, max(0, round(time.time() - t0)), code)
        if code != 0:
            on_fail(f"the script {name} stopped with exit code {code}. Its output is in {rel}")
        return code
    finally:
        runfiles.remove(_pidfile(root, tid))
