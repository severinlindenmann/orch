"""Protected machines: a helper's command that connects to a production machine is refused.

The workspace lists its production machines (`orch config set workspace.protected_machines "<name>,..."`,
set by a person; a name is an ssh name or an address). A tool's before-tool hook
(`orch protected-check --hook <tool>`) reads the command about to run. When it is ssh, scp, sftp, rsync or
mosh to a listed machine, the hook answers with a refusal and a plain reason. Only a step that is a release
or deploy step (its text starts with "Release" or "Deploy") may connect.

Light security: a guard against a helper's mistake, not against a person or a malicious helper. The command
is read as text; a name inside a script file is not seen. Aliases of ~/.ssh/config are followed both ways
(an alias and its HostName count as the same machine).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REMOTE_TOOLS = frozenset({"ssh", "scp", "sftp", "rsync", "mosh", "autossh", "ssh-copy-id"})
_SEGMENT = re.compile(r"[;|&\n]+")
_WORD = re.compile(r"[^\s'\"`()<>{}]+")
_DEPLOY = re.compile(r"^\s*(release|deploy)\b", re.IGNORECASE)


def _ssh_aliases(home: Path | None = None) -> dict[str, str]:
    """{alias: HostName} from ~/.ssh/config (simple `Host` / `HostName` lines; no Include, no wildcards)."""
    cfg = (home or Path.home()) / ".ssh" / "config"
    try:
        lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    out: dict[str, str] = {}
    names: list[str] = []
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        key, val = parts[0].lower(), parts[1].strip()
        if key == "host":
            names = [n.lower() for n in val.split() if not any(c in n for c in "*?!")]
        elif key == "hostname":
            for n in names:
                out.setdefault(n, val.lower())
    return out


def expand(machines: list[str], home: Path | None = None) -> set[str]:
    """The listed names plus every other name for the same machine in ~/.ssh/config."""
    names = {m.lower() for m in machines}
    aliases = _ssh_aliases(home)
    for _ in range(2):
        for alias, host in aliases.items():
            if alias in names or host in names:
                names |= {alias, host}
    return names


def _host_of(word: str) -> str:
    w = word.lower()
    if w.startswith("ssh://"):
        w = w[6:]
    w = w.rsplit("@", 1)[-1]  # user@host
    if w.startswith("["):  # [v6]:path
        return w[1:].split("]", 1)[0]
    return w.split(":", 1)[0].split("/", 1)[0]


def find_target(command: str, machines: list[str], home: Path | None = None) -> str | None:
    """The listed machine this command connects to, or None."""
    names = expand(machines, home)
    if not names:
        return None
    for seg in _SEGMENT.split(command or ""):
        words = _WORD.findall(seg)
        for i, w in enumerate(words):
            if os.path.basename(w) in REMOTE_TOOLS:
                for arg in words[i + 1 :]:
                    host = _host_of(arg)
                    if host in names:
                        return host
                    # -oHostName=x / -o HostName=x is rare; a plain scp "host:path" is covered above
    return None


def is_deploy_step(root: Path, ticket: str | None) -> bool:
    """True when the step the run is working on is a release or deploy step."""
    if not ticket:
        return False
    try:
        from orch import tickets

        t = tickets.load(root, ticket)
    except Exception:  # noqa: BLE001 - a hook never fails the tool; unknown = not a deploy step
        return False
    for c in t.get("checklist") or []:
        if c.get("state") == "doing" and _DEPLOY.match(str(c.get("text") or c.get("title") or "")):
            return True
    return False


def reason(host: str) -> str:
    return (
        f"{host} is a protected machine (production). A helper does not connect to it outside a release or "
        "deploy step. Run the test in CI or on a throwaway server instead, or ask the owner."
    )


def verdict(root: Path, command: str, ticket: str | None, home: Path | None = None) -> str | None:
    """The refusal sentence for this command, or None when it may run."""
    from orch import config

    host = find_target(command, config.protected_machines(root), home)
    if host is None or is_deploy_step(root, ticket):
        return None
    return reason(host)


def hook_main(argv: list[str] | None = None, watchdog=None) -> int:
    """`orch protected-check --hook <tool>`: exit 0 always. When the command is refused, stdout carries the
    tool's one JSON refusal (the before-tool refusal: `permissionDecision: deny`)."""
    if watchdog is not None:
        watchdog.cancel()
    try:
        data = json.loads(sys.stdin.read(1024 * 1024) or "{}")
        if data.get("tool_name") != "Bash":
            return 0
        command = (data.get("tool_input") or {}).get("command")
        if not isinstance(command, str):
            return 0
        from orch import workcheck

        env = os.environ.get("ORCH_ROOT")  # a run in its own copy sits outside the workspace folder
        root = Path(env) if env else workcheck.find_root(Path(data.get("cwd") or os.getcwd()))
        why = verdict(root, command, os.environ.get("ORCH_TICKET"))
        if why:
            sys.stdout.write(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": why,
                        }
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
    except BaseException:  # noqa: BLE001
        pass
    return 0
