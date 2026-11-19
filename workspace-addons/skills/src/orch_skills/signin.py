"""Sign-in state of connected services, as Claude reports it (ORCH-842).

Claude keeps a service's web sign-in in its own store; orch cannot read it from a file. `claude mcp list` says per
service whether it is connected, needs a sign-in, failed or waits to be allowed. It starts every service's program
to find out, so it runs only when a person presses "Check sign-in", never on a page load. The answer is kept in
`.orch/addons/skills/signin.json` with its time (names and states only). The sign-in itself happens in Claude
(`/mcp`); orch cannot do it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import switches
from .switches import Refused

CACHE = Path(".orch") / "addons" / "skills" / "signin.json"
SCHEMA = "orch.skills-signin/1"
TIMEOUT = 90
WORDS = (
    ("needs authentication", "needs-sign-in"),
    ("failed to connect", "failed"),
    ("pending", "pending"),  # Claude waits for the person to allow the service
    ("disabled", "off"),
    ("connected", "connected"),
)
TEXT = {
    "connected": "Signed in and working (checked {at})",
    "needs-sign-in": "Needs a sign-in: type /mcp in Claude and sign in there (checked {at})",
    "failed": "Could not reach it (checked {at})",
    "pending": "Claude waits for you to allow it: start Claude in this folder once (checked {at})",
    "off": "Claude has it turned off (checked {at})",
}


def parse(out: str) -> dict[str, str]:
    """`claude mcp list` lines `<name>: <where> - <mark> <state>` -> {name: state}. Unknown words are skipped."""
    found: dict[str, str] = {}
    for line in out.splitlines():
        name, sep, rest = line.partition(": ")
        if not sep or " - " not in rest or not name.strip() or len(name) > 200:
            continue
        status = rest.rsplit(" - ", 1)[1].lower()
        for word, state in WORDS:
            if word in status:
                found[name.strip()] = state
                break
    return found


def read(root: Path) -> dict:
    """{"checked_at": str | None, "servers": {name: state}} (never raises)."""
    try:
        doc, _ = switches._read(root, CACHE)
    except Refused:
        doc = {}
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("servers"), dict):
        return {"checked_at": None, "servers": {}}
    servers = {k: v for k, v in doc["servers"].items() if isinstance(k, str) and v in TEXT}
    return {"checked_at": doc.get("checked_at") if isinstance(doc.get("checked_at"), str) else None, "servers": servers}


def check(root: Path, now: str) -> dict:
    """Ask Claude once and keep the answer. Refused when Claude is not installed or does not answer in time."""
    claude = shutil.which("claude")
    if not claude:
        raise Refused("Claude is not installed on this computer, so orch cannot ask it about the sign-in state.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_SECRET")}
    try:
        res = subprocess.run(
            [claude, "mcp", "list"],
            check=False,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise Refused("Claude took too long to check the services. Try again later.") from None
    except OSError:
        raise Refused("Claude could not be started to check the services.") from None
    servers = parse(res.stdout or "")
    if res.returncode != 0 and not servers:
        raise Refused("Claude could not check the services just now. Try again later.")
    doc = {"schema": SCHEMA, "checked_at": now, "servers": servers}
    with switches._locked(root):
        switches._write(root, CACHE, doc)
    return doc


def text(state: str, at: str | None) -> str:
    return TEXT[state].format(at=(at or "")[:16].replace("T", " "))
