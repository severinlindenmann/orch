"""What a skill's header says about offering it here (skill format, ORCH-531 step 2).

The header is the flat skill format; a private reader until the shared one (ORCH-532) lands.
orch acts on three metadata keys at install:
- status: retired     -> not linked where agents look, and its block leaves AGENTS.orch.md; the files stay.
- status: deprecated  -> the description agents see starts with "Old skill, use <replaced-by> instead."
- platforms           -> not linked on a system that is not in the list (missing or empty = every system).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLATFORM_WORDS = {
    "macos": "macos",
    "mac": "macos",
    "darwin": "macos",
    "windows": "windows",
    "win": "windows",
    "linux": "linux",
}


_KEY = re.compile(r"^([A-Za-z0-9_.-]+):(.*)$")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _front(text: str) -> tuple[list[str], int, int] | None:
    """The header lines and the [start, end) line numbers of the header body, or None without a header."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines, 1, i
    return None


def _parse_header(text: str) -> dict:
    """{key: text} for the top level and {"metadata": {key: text}}; anything fancier is skipped."""
    out: dict = {"metadata": {}}
    f = _front(text)
    if f is None:
        return out
    lines, a, b = f
    in_meta = False
    for ln in lines[a:b]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if ln[0] in " \t":
            if in_meta:
                m = _KEY.match(ln.strip())
                if m:
                    out["metadata"][m.group(1)] = _unquote(m.group(2).split(" #")[0])
            continue
        m = _KEY.match(ln.rstrip("\r"))
        if not m:
            in_meta = False
            continue
        key, val = m.group(1), m.group(2)
        in_meta = key == "metadata" and not val.strip()
        if not in_meta:
            out[key] = _unquote(val)
    return out


def _read_header(skill_dir: Path) -> dict:
    f = skill_dir / "SKILL.md"
    try:
        return _parse_header(f.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n"))
    except OSError:
        return {"metadata": {}}


def _split_list(value: object) -> list[str]:
    """A comma list ("gh, git") as its non-empty parts."""
    return [w.strip() for w in str(value or "").split(",") if w.strip()]


def this_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def platforms(meta: dict) -> set[str]:
    """The known systems the header names; an empty set means every system."""
    words = [w.lower() for w in _split_list(meta.get("platforms"))]
    return {PLATFORM_WORDS[w] for w in words if w in PLATFORM_WORDS}


def hidden_reason(skill_dir: Path, platform: str | None = None) -> str | None:
    """Why orch does not offer this skill here ("retired", "not for linux"), or None when it is offered."""
    meta = _read_header(skill_dir)["metadata"]
    if str(meta.get("status") or "").strip().lower() == "retired":
        return "retired"
    want = platforms(meta)
    here = platform or this_platform()
    if want and here not in want:
        return f"not for {here}"
    return None


def mark_deprecated(text: str) -> str:
    """The skill text with "Old skill, use <replaced-by> instead." in front of its description when the
    header says deprecated. Idempotent; every other byte stays as it is."""
    head = _parse_header(text)
    meta = head["metadata"]
    if str(meta.get("status") or "").strip().lower() != "deprecated":
        return text
    repl = re.sub(r"[^A-Za-z0-9 _.,/-]", "", str(meta.get("replaced-by") or "")).strip()
    # no ": " in the note: an unquoted description must stay valid YAML
    note = f"Old skill, use {repl} instead." if repl else "Old skill, no longer kept up."
    f = _front(text)
    if f is None:
        return text
    lines, a, b = f
    for i in range(a, b):
        m = re.match(r"^description:(\s*)(.*)$", lines[i])
        if not m:
            continue
        val = m.group(2)
        quote = val[:1] if val[:1] in "\"'" and len(val) >= 2 and val[-1] == val[0] else ""
        inner = val[1:-1] if quote else val
        if inner.startswith(note):
            return text
        if not quote and val.lstrip()[:1] in "|>":
            return text  # a block value: not changed (the flat format writes the description on one line)
        lines[i] = f"description: {quote}{note} {inner}{quote}"
        return "\n".join(lines)
    return text
