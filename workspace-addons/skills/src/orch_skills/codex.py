"""Codex's own per-folder switch for connected services (checked with Codex 0.170, ORCH-842).

Codex reads `[mcp_servers.<name>] enabled = false` from the folder's `.codex/config.toml`, also for a service
defined in the person's own Codex settings, but only in a folder Codex trusts (`[projects."<folder>"]
trust_level = "trusted"` in the person's settings); in any other folder it ignores the folder's file completely.
Codex has no per-folder switch for skills (`[[skills.config]]` counts only in the person's own settings, for every
folder), so this page never writes one.

orch writes one marked block per service it turned off and removes only that block; the rest of the file stays
byte for byte. The person's own settings are only read.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from . import switches
from .switches import Refused

PROJECT = Path(".codex") / "config.toml"
MARK = "# orch: turned off here on the Skills page"


def _key(name: str) -> str:
    return json.dumps(name, ensure_ascii=False)  # a TOML basic string has the same escapes as JSON for names


def block(name: str, nl: str = "\n") -> str:
    return nl.join((MARK, f"[mcp_servers.{_key(name)}]", "enabled = false", ""))


def _strict(text: str) -> dict | None:
    """The parsed file, or None when it is not valid TOML (never mistaken for an empty file)."""
    try:
        doc = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _load(text: str) -> dict:
    try:
        doc = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _servers(doc: dict) -> dict:
    s = doc.get("mcp_servers")
    return {k: v for k, v in s.items() if isinstance(v, dict)} if isinstance(s, dict) else {}


def user_file(account_home: Path) -> Path:
    env = os.environ.get("CODEX_HOME")
    return (Path(env) if env else Path(account_home) / ".codex") / "config.toml"


def _read_text(path: Path) -> str:
    try:
        if switches._is_link(path) or not path.is_file() or path.stat().st_size > switches.MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def state(root: Path, account_home: Path) -> dict:
    """{"trusted": bool, "servers": {name: "on" | "orch" | "hand"}} of what Codex sees here (read only).
    "orch" = off through orch's block in this folder, "hand" = off by a line orch did not write."""
    user = _load(_read_text(user_file(account_home)))
    root = Path(root)
    projects = user.get("projects") if isinstance(user.get("projects"), dict) else {}
    trusted = any(
        isinstance(projects.get(k), dict) and projects[k].get("trust_level") == "trusted"
        for k in {str(root), str(root.resolve())}
    )
    text = _read_text(root / PROJECT) if trusted else ""
    here = _servers(_load(text))
    owned = set(switches._owned(root)["codexMcp"])
    mine = _servers(user)
    out = {}
    for name in {**mine, **here}:
        enabled = here.get(name, {}).get("enabled", mine.get(name, {}).get("enabled", True))
        if enabled is not False:
            out[name] = "on"
        elif name in owned and (block(name) in text or block(name, "\r\n") in text):
            out[name] = "orch"
        else:
            out[name] = "hand"
    return {"trusted": trusted, "servers": out}


def set_mcp(root: Path, name: str, on: bool) -> bool:
    """Off: add orch's block for `name` to this folder's .codex/config.toml. On: remove only that block.
    True when the file changed."""
    if not name or len(name) > 200 or any(c in name for c in "\r\n\x00"):
        raise Refused("That is not a service orch can turn off for Codex.")
    with switches._locked(root):
        path = switches.safe_path(root, PROJECT)
        raw = path.read_bytes() if path.exists() else None
        if raw is not None and len(raw) > switches.MAX_BYTES:
            raise Refused(f"{PROJECT} is too big to change safely. Nothing was changed.")
        try:
            text = raw.decode("utf-8") if raw is not None else ""
        except UnicodeDecodeError:
            raise Refused(f"{PROJECT} is not readable. Fix it first; nothing was changed.") from None
        if _strict(text) is None:
            raise Refused(f"{PROJECT} is not readable TOML. Fix it first; nothing was changed.")
        owned = switches._owned(root)
        nl = "\r\n" if "\r\n" in text else "\n"
        mine = block(name, nl)
        if on:
            if mine not in text:
                if name in owned["codexMcp"]:
                    owned["codexMcp"].remove(name)
                    switches.save_owned(root, owned)
                return False
            if _servers(_strict(text) or {}).get(name) != {"enabled": False}:
                raise Refused(
                    f"Someone added settings for {name} under orch's lines in {PROJECT}; orch leaves them alone. "
                    f"Change enabled there to turn it on for Codex."
                )
            new = text.replace(nl + mine, "", 1) if (nl + mine) in text else text.replace(mine, "", 1)
            after = _strict(new)
            if after is None or name in _servers(after):
                raise Refused(f"orch could not take its switch out of {PROJECT} cleanly. Nothing was changed.")
            switches._write(root, PROJECT, new, expect=raw)
            if name in owned["codexMcp"]:
                owned["codexMcp"].remove(name)
                switches.save_owned(root, owned)
            return True
        if name in _servers(_load(text)):
            if mine in text:
                return False
            raise Refused(
                f"This folder's Codex settings already list {name}; orch leaves that alone. Set enabled = false "
                f"there to turn it off for Codex."
            )
        new = text + ("" if not text or text.endswith("\n") else nl) + (nl if text else "") + mine
        if _servers(_strict(new) or {}).get(name) != {"enabled": False}:
            raise Refused(f"orch could not add a clean switch to {PROJECT}. Nothing was changed.")
        before = list(owned["codexMcp"])
        owned["codexMcp"] = sorted(set(before) | {name})
        switches.save_owned(root, owned)
        try:
            switches._write(root, PROJECT, new, expect=raw)
        except Refused:
            owned["codexMcp"] = before
            switches.save_owned(root, owned)
            raise
    return True
