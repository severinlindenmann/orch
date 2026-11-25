"""Sign-in state of connected services, as the helper tool itself reports it (ORCH-842).

A tool keeps a service's web sign-in in its own store; orch cannot read it from a file. The core already asks the
tool through its own list command (tool data `connection_check`, health.py) and reads only each service's state
word. That command starts every service's program, so it runs only when a person presses "Check sign-in", never
on a page load. The answer is kept in `.orch/addons/skills/signin.json` with its time (names and states only). The
sign-in itself happens in the tool; orch cannot do it.

The same check keeps the names the tool lists that no file has (services of the person's account, ORCH-1819) in
"account", with the tool's label in "by": the page shows them read only from the cache. A failed check keeps the
last answer.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import switches
from .switches import Refused

CACHE = Path(".orch") / "addons" / "skills" / "signin.json"
SCHEMA = "orch.skills-signin/1"
WORDS = {"needs authentication": "needs-sign-in", "failed": "failed", "connected": "connected"}
TEXT = {
    "connected": "Signed in and working (checked {at})",
    "needs-sign-in": "Needs a sign-in. {how} (checked {at})",
    "failed": "Could not reach it (checked {at})",
}
ACCOUNT_NAME = re.compile(r"^[^\x00-\x1f\x7f<>]{1,80}$")
MAX_ACCOUNT = 100


def checker(tools_here: dict[str, dict]) -> tuple[str, dict] | None:
    """The first tool used here that can report the sign-in state: (name, tool)."""
    for name, tool in tools_here.items():
        if isinstance(tool.get("connection_check"), dict) and tool.get("binary"):
            return name, tool
    return None


def read(root: Path) -> dict:
    """{"checked_at", "servers": {name: state}, "account": [names], "by": label | None} (never raises)."""
    try:
        doc, _ = switches._read(root, CACHE)
    except Refused:
        doc = {}
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("servers"), dict):
        return {"checked_at": None, "servers": {}, "account": [], "by": None}
    servers = {k: v for k, v in doc["servers"].items() if isinstance(k, str) and v in TEXT}
    account = doc.get("account") if isinstance(doc.get("account"), list) else []
    by = doc.get("by") if isinstance(doc.get("by"), str) and ACCOUNT_NAME.match(doc["by"]) else None
    return {
        "checked_at": doc.get("checked_at") if isinstance(doc.get("checked_at"), str) else None,
        "servers": servers,
        "account": [n for n in account if isinstance(n, str) and ACCOUNT_NAME.match(n) and n in servers][:MAX_ACCOUNT],
        "by": by,
    }


def check(root: Path, now: str, tool: dict, names: list[str]) -> dict:
    """Ask the tool once (through the core) and keep the answer. Refused when it is not installed or says nothing;
    then the last answer stays."""
    from orch import health

    label = tool["label"]
    spec = tool["connection_check"]
    exe = shutil.which(tool["binary"])
    if not exe:
        raise Refused(f"{label} is not installed on this computer, so orch cannot ask it about the sign-in state.")
    listed = health.conn_list(Path(root), exe, spec["list"])
    says = health.match_names(listed, names, spec.get("plugin_prefix"))
    account = account_names(listed, names, spec)
    if not says and not account:
        raise Refused(
            f"{label} reported no service as connected, needing a sign-in or failed. It may still wait for you "
            f"to allow them: start {label} in this folder once, then check again."
        )
    servers = {n: WORDS[w] for n, w in says.items() if w in WORDS}
    servers.update({n: WORDS[listed[n]] for n in account if listed[n] in WORDS})
    doc = {"schema": SCHEMA, "checked_at": now, "servers": servers, "account": account, "by": label}
    with switches._locked(root):
        switches._write(root, CACHE, doc)
    return doc


def account_names(listed: dict[str, str], names: list[str], spec: dict) -> list[str]:
    """Names the tool lists that no file has: neither a known server nor a plugin's server; with an account
    prefix in the tool data, only names that start with it."""
    known, plugin, account = set(names), spec.get("plugin_prefix"), spec.get("account_prefix")
    out = [
        n
        for n in listed
        if n not in known
        and not (plugin and n.startswith(plugin))
        and (not account or n.startswith(account))
        and ACCOUNT_NAME.match(n)
    ]
    return sorted(out)[:MAX_ACCOUNT]


def shown_name(name: str, tool: dict | None) -> str:
    """An account service's name without the tool's prefix (connection_check account_prefix)."""
    prefix = ((tool or {}).get("connection_check") or {}).get("account_prefix")
    return name[len(prefix) :] if prefix and name.startswith(prefix) and len(name) > len(prefix) else name


def how(tool: dict | None, name: str) -> str:
    sign_in = ((tool or {}).get("connection_check") or {}).get("sign_in")
    return sign_in.format(name=name) if sign_in else "Sign in again in your helper tool."


def text(state: str, at: str | None, tool: dict | None, name: str) -> str:
    return TEXT[state].format(at=(at or "")[:16].replace("T", " "), how=how(tool, name).rstrip("."))
