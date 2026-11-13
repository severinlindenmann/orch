"""Public core CLI only; never open or write core ticket files."""

import json
import os
import subprocess

from .store import Refused


def call(root, *args, write=False):
    cmd = [os.environ.get("ORCH_BIN") or "orch", *args, "--json"]
    if write:
        cmd += ["--by", "agent:factory"]
    env = dict(os.environ, ORCH_ROOT=str(root))
    try:
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            check=False,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("Orch could not be reached. Try again.", "not_available") from None
    try:
        value = json.loads(result.stdout)
    except ValueError:
        raise Refused("Orch did not return a readable answer.", "not_available") from None
    if result.returncode:
        raise Refused(value.get("error", "Orch refused the request."), value.get("code", "refused"))
    return value


def ticket(root, order):
    return call(root, "ticket", "show", order)


def tickets(root):
    return call(root, "ticket", "list", "--all")


def set_ext(root, ticket, **changes):
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
    )
