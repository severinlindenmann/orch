"""Public core CLI only; never open or write core ticket files."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .store import Refused


def _orch_cmd() -> list[str]:
    """How orch is started: this Python's own orch where the launcher must not be (orch.exe on Windows, or no orch
    on the PATH; orch.procs.orch_cmd, ORCH-2138), else `$ORCH_BIN` / `orch` as before."""
    try:
        from orch import procs
    except ImportError:  # no orch in this Python (the add-on's own test env)
        return [os.environ.get("ORCH_BIN") or "orch"]
    return procs.orch_cmd()


READS = {"here": 0, "process": 0}  # reads answered without a new process (ORCH-634), and commands started


def _here(root, args):
    """A read answered by the core in this process or by its one read worker (orch.reads.call), when ORCH_BIN is
    this very orch: (code, value), or None to start the command as before (a test's fake orch, an older core)."""
    try:
        from orch import procs, reads
    except ImportError:
        return None
    if not hasattr(reads, "call"):
        return None
    cmd = _orch_cmd()
    orch_bin = shutil.which(cmd[0]) if cmd == ["orch"] else cmd[0]
    if cmd != procs.orch_python_argv() and not reads.same_orch(orch_bin):
        return None
    try:
        return reads.call(Path(root), [*args, "--json"])
    except Exception:  # noqa: BLE001 - the command gets its chance
        return None


def _value(code, value):
    if code:
        if not isinstance(value, dict):
            raise Refused("Orch refused the request.", "refused")
        code = value.get("code")
        if code is None and "changed_by" in value and "revision" in value:
            code = "conflict"  # core's stale-edit refusal (--if-revision) carries no code; callers retry on "conflict"
        error = Refused(value.get("error", "Orch refused the request."), code or "refused")
        error.found = value.get("found")  # `orch secret scan`: what it found (kind and line, never the text)
        raise error
    if value is None:
        raise Refused("Orch did not return a readable answer.", "not_available")
    return value


def call(root, *args, write=False, by=None, data=None):
    """`by`: who a write is recorded as (a person's dashboard click passes `human:<name>`); default the add-on.
    A read (no write, no input) is answered without a new process when it can be (`_here`)."""
    if not write and data is None:
        got = _here(root, args)
        if got is not None and (got[0] or got[1] is not None):  # an unreadable answer: the command itself
            READS["here"] += 1
            return _value(*got)
    READS["process"] += 1
    cmd = [*_orch_cmd(), *args, "--json"]
    if write:
        cmd += ["--by", by or "agent:factory"]
    env = dict(os.environ, ORCH_ROOT=str(root))
    try:
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            check=False,
            text=data is None,
            input=data,
            stdin=subprocess.DEVNULL if data is None else None,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("Orch could not be reached. Try again.", "not_available") from None
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise Refused("Orch did not return a readable answer.", "not_available") from None
    return _value(result.returncode, value)


def ticket(root, order):
    return call(root, "ticket", "show", order)


def tickets(root):
    return call(root, "ticket", "list", "--all")


def own_tickets(root):
    """Only the tickets with Factory's data (orders and their crew), without reading every ticket (ORCH-603).
    An orch without `--ext` refuses it: then the full list."""
    try:
        return call(root, "ticket", "list", "--all", "--ext", "factory")
    except Refused:
        return tickets(root)


def set_ext(root, ticket, by=None, **changes):
    ext = dict(ticket.get("ext", {}).get("factory", {}))
    ext.update(changes)
    return call(
        root,
        "ext",
        "set",
        ticket["id"],
        "factory",
        json.dumps(ext),
        "--if-revision",
        str(ticket["revision"]),
        write=True,
        by=by,
    )
