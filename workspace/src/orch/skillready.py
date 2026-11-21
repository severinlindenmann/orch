"""Is a skill ready on this computer? (skill format, ORCH-534)

A skill's header may list what it needs under `metadata` (comma lists, plain strings):
`requires` (programs on PATH), `requires-logins` (names of stored logins, never values) and
`requires-addons` (orch add-ons that must be on). A skill that misses something is never hidden
(owner, ORCH-531 q4): helpers read one line "not ready here: gh missing" in a core block of
AGENTS.orch.md, and the inventory (Insights) carries what is missing.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

BLOCK = "skills-ready"  # .orch/harness/blocks/skills-ready.md
WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")  # a requirement that may be shown and written
MAX_SKILLS = 30  # lines in the helper block
MAX_ITEMS = 8  # requirements shown per skill
MAX_MISSING = 64  # the inventory schema's cap on `missing`
HEADER_CAP = 64 * 1024  # bytes of SKILL.md read for the header


def _fallback_header(text: str) -> dict:
    """Only until the shared reader (orch.skillmeta) is in: flat `key: value` lines, one `metadata:` level."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict = {}
    meta: dict[str, str] = {}
    in_meta = False
    for line in lines[1:]:
        if line.strip() == "---":
            if meta:
                out["metadata"] = meta
            return out
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        value = value.strip()
        if value[:1] not in ('"', "'"):
            value = value.split(" #", 1)[0].rstrip()  # an inline YAML comment
        elif (end := value.find(value[0], 1)) > 0:  # a quoted value, maybe with a comment after it
            value = value[1:end]
        if indented and in_meta:
            meta[key.strip()] = value
        elif not indented:
            in_meta = key.strip() == "metadata" and not value
            if not in_meta:
                out[key.strip()] = value
    return {}  # no closing line: not a header


def metadata(skill_dir: Path) -> dict[str, str]:
    """The skill's metadata strings; {} when it has no readable header."""
    try:
        from orch import skillmeta  # the shared reader (ORCH-532), when it is in
    except ImportError:
        skillmeta = None
    header: dict = {}
    if skillmeta is not None:
        try:
            reader = getattr(skillmeta, "try_header", None) or skillmeta.read_header
            header = reader(Path(skill_dir)) or {}
        except Exception:  # a bad header reads as none here; orch skill check says why
            header = {}
    else:
        try:
            with open(Path(skill_dir) / "SKILL.md", "rb") as f:
                raw = f.read(HEADER_CAP)
            header = _fallback_header(raw.decode("utf-8", "replace"))
        except OSError:
            header = {}
    meta = header.get("metadata") if isinstance(header, dict) else None
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items() if isinstance(k, str) and isinstance(v, str)}


def split_list(value: str) -> list[str]:
    try:
        from orch.skillmeta import split_list as shared
    except ImportError:
        return [p.strip() for p in str(value).split(",") if p.strip()]
    return shared(value)


def _login_names(root: Path) -> set[str]:
    from orch import keystore
    from orch.errors import Refused

    try:
        return {
            k.get("name")
            for k in keystore.list_keys(Path(root))
            if isinstance(k.get("name"), str)
            and k.get("state") != keystore.NEEDS_REENTRY  # unusable = missing
        }
    except (Refused, OSError, ValueError):  # a damaged key store: every login reads as missing
        return set()


def _active_addons(root: Path) -> set[str]:
    from orch import addons

    try:
        return set(addons.active(Path(root)))
    except Exception:  # a broken add-on state reads as nothing on
        return set()


def missing(root: Path, meta: dict[str, str], *, _cache: dict | None = None) -> list[str]:
    """What this computer lacks for a skill with this metadata, in plain words: "gh", "login github-login",
    "add-on relay". Empty = ready. Requirements that are not plain names are left out (never shown, never
    run)."""
    cache = _cache if _cache is not None else {}
    out: list[str] = []
    for prog in split_list(meta.get("requires", "")):
        if WORD_RE.match(prog) and shutil.which(prog) is None:
            out.append(prog)
    logins = [n for n in split_list(meta.get("requires-logins", "")) if WORD_RE.match(n)]
    if logins:
        if "logins" not in cache:
            cache["logins"] = _login_names(root)
        out += [f"login {n}" for n in logins if n not in cache["logins"]]
    wanted = [n for n in split_list(meta.get("requires-addons", "")) if WORD_RE.match(n)]
    if wanted:
        if "addons" not in cache:
            cache["addons"] = _active_addons(root)
        out += [f"add-on {n}" for n in wanted if n not in cache["addons"]]
    return out[:MAX_MISSING]


def note(lacks: list[str]) -> str:
    """The one line a helper reads: "not ready here: gh missing"."""
    shown = lacks[:MAX_ITEMS]
    more = f" and {len(lacks) - MAX_ITEMS} more" if len(lacks) > MAX_ITEMS else ""
    return f"not ready here: {', '.join(shown)}{more} missing"


def _helper_skills(root: Path, account_home: Path | None = None) -> list[tuple[str, Path]]:
    """The skills helpers see, one per name (the workspace one wins over the agent tool's own)."""
    from orch import inventory

    seen: dict[str, Path] = {}
    own = Path(root) / ".agents" / "skills"
    for name, folder in inventory._skill_folders(own, inside=Path(root)).items():
        seen.setdefault(name, folder)
    for base in inventory.harness_skill_dirs(account_home):
        for name, folder in inventory._skill_folders(base).items():
            seen.setdefault(name, folder)
    return sorted(seen.items())


def not_ready(root: Path, account_home: Path | None = None) -> list[dict]:
    """[{"name", "missing": [...], "note"}] for every skill helpers see that misses something here."""
    cache: dict = {}
    out = []
    for name, folder in _helper_skills(root, account_home):
        lacks = missing(root, metadata(folder), _cache=cache)
        if lacks:
            out.append({"name": name, "missing": lacks, "note": note(lacks)})
    return out


def block_text(items: list[dict]) -> str:
    if not items:
        return ""
    lines = [
        "## Skills not ready here",
        "These skills stay available but need something this computer does not have. Set it up or tell the "
        "person before you rely on one:",
    ]
    lines += [f"- {i['name']}: {i['note']}" for i in items[:MAX_SKILLS]]
    if len(items) > MAX_SKILLS:
        lines.append(f"- and {len(items) - MAX_SKILLS} more")
    return "\n".join(lines)


def refresh(root: Path, account_home: Path | None = None) -> bool:
    """Write the helper block when it changed (none when every skill is ready). True if AGENTS.orch.md
    changed. Never raises: a run must not fail because a skill header could not be read."""
    from orch import harness

    try:
        text = block_text(not_ready(root, account_home))
        current = harness.current_block(root, BLOCK, addon=False)
        if not text:
            if current is None:
                return False
            harness.remove_block(root, BLOCK, addon=False)
            return True
        if (current or "").strip() == text.strip():
            return False
        harness.set_block(root, BLOCK, text, addon=False)
        return True
    except Exception:
        return False
