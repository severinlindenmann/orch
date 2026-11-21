"""A helper tool's per-folder switch in a TOML settings file (format "toml" in agents/switches.json).

The switch is a table per item under a path (`table_set`, e.g. {"enabled": false}), merged over the same table in
the person's own settings file (`user_file`, only read). When the data names a `trust` rule, the tool reads the
folder's file only in folders the person trusts; elsewhere orch offers no switch and says why.

orch writes one marked block per item it turned off and removes only that block; the rest of the file stays byte
for byte (line endings kept).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from . import switches, tools
from .switches import Refused

MARK = "# orch: turned off here on the Skills page"


def _key(name: str) -> str:
    return json.dumps(name, ensure_ascii=False)  # a TOML basic string has the same escapes as JSON for names


def _value(v) -> str:
    return "true" if v is True else "false" if v is False else json.dumps(v, ensure_ascii=False)


def block(spec: dict, name: str, nl: str = "\n") -> str:
    head = ".".join(_key(p) if not p.isidentifier() else p for p in spec["path"])
    return nl.join((MARK, f"[{head}.{_key(name)}]", *(f"{k} = {_value(v)}" for k, v in spec["table_set"].items()), ""))


def _strict(text: str) -> dict | None:
    """The parsed file, or None when it is not valid TOML (never mistaken for an empty file)."""
    try:
        doc = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _tables(doc: dict | None, spec: dict) -> dict:
    t = doc or {}
    for k in spec["path"]:
        t = t.get(k) if isinstance(t, dict) else None
    return {k: v for k, v in t.items() if isinstance(v, dict)} if isinstance(t, dict) else {}


def _read_text(path: Path) -> str:
    try:
        if switches._is_link(path) or not path.is_file() or path.stat().st_size > switches.MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def trusted(root: Path, tool: dict, home: Path) -> bool:
    fs = tool["switches"]
    rule = fs.get("trust")
    if not isinstance(rule, dict):
        return True
    user = _strict(_read_text(Path(tools.fill(fs.get("user_file", ""), home, root, tool)))) or {}
    for folder in {str(Path(root)), str(Path(root).resolve())}:
        t = user
        for k in rule["path"]:
            t = t.get(k.replace("{folder}", folder)) if isinstance(t, dict) else None
        if t == rule["value"]:
            return True
    return False


def state(root: Path, name: str, tool: dict, home: Path) -> dict:
    """{"trusted": bool, "service": {item: "on" | "orch" | "hand"}} of what this tool sees here (read only)."""
    fs = tool["switches"]
    spec = fs.get("service")
    if not isinstance(spec, dict):
        return {"trusted": True, "service": {}}
    ok = trusted(root, tool, home)
    user = _tables(_strict(_read_text(Path(tools.fill(fs.get("user_file", ""), home, root, tool)))), spec)
    text = _read_text(Path(root) / fs["file"]) if ok else ""
    here = _tables(_strict(text), spec)
    mine = set(switches.owned(root, name, "service"))
    out = {}
    for item in {**user, **here}:
        merged = {**user.get(item, {}), **here.get(item, {})}
        if any(merged.get(k) != v for k, v in spec["table_set"].items()):
            out[item] = "on"
        elif item in mine and (block(spec, item) in text or block(spec, item, "\r\n") in text):
            out[item] = "orch"
        else:
            out[item] = "hand"
    return {"trusted": ok, "service": out}


def set_table(root: Path, name: str, tool: dict, item: str, on: bool) -> bool:
    """Off: add orch's block for `item` to the folder's file. On: remove only that block. True when it changed."""
    fs = tool["switches"]
    spec = fs.get("service")
    rel = Path(fs["file"])
    if not isinstance(spec, dict) or not item or len(item) > 200 or any(c in item for c in "\r\n\x00"):
        raise Refused(f"That is not a service orch can turn off for {tool['label']}.")
    with switches._locked(root):
        path = switches.safe_path(root, rel)
        raw = path.read_bytes() if path.exists() else None
        if raw is not None and len(raw) > switches.MAX_BYTES:
            raise Refused(f"{rel} is too big to change safely. Nothing was changed.")
        try:
            text = raw.decode("utf-8") if raw is not None else ""
        except UnicodeDecodeError:
            raise Refused(f"{rel} is not readable. Fix it first; nothing was changed.") from None
        if _strict(text) is None:
            raise Refused(f"{rel} is not readable TOML. Fix it first; nothing was changed.")
        recorded = switches.owned(root, name, "service")
        nl = "\r\n" if "\r\n" in text else "\n"
        mine = block(spec, item, nl)
        if on:
            if mine not in text:
                if item in recorded:
                    switches.set_owned(root, name, "service", [e for e in recorded if e != item])
                return False
            if _tables(_strict(text), spec).get(item) != spec["table_set"]:
                raise Refused(
                    f"Someone added settings for {item} under orch's lines in {rel}; orch leaves them alone. "
                    f"Change them there to turn it on for {tool['label']}."
                )
            new = text.replace(nl + mine, "", 1) if (nl + mine) in text else text.replace(mine, "", 1)
            after = _strict(new)
            if after is None or item in _tables(after, spec):
                raise Refused(f"orch could not take its switch out of {rel} cleanly. Nothing was changed.")
            switches._write(root, rel, new, expect=raw)
            switches.set_owned(root, name, "service", [e for e in recorded if e != item])
            return True
        if item in _tables(_strict(text), spec):
            if mine in text:
                return False
            raise Refused(
                f"This folder's {tool['label']} settings already list {item}; orch leaves that alone. "
                f"Change it there to turn it off for {tool['label']}."
            )
        new = text + ("" if not text or text.endswith("\n") else nl) + (nl if text else "") + mine
        if _tables(_strict(new), spec).get(item) != spec["table_set"]:
            raise Refused(f"orch could not add a clean switch to {rel}. Nothing was changed.")
        switches.set_owned(root, name, "service", [*recorded, item])
        try:
            switches._write(root, rel, new, expect=raw)
        except Refused:
            switches.set_owned(root, name, "service", recorded)
            raise
    return True
