"""Skills that say what is on (SK-02/SK-03).

A skill source may hold `{{#fact}}...{{/fact}}` (shown when the fact is true) and
`{{^fact}}...{{/fact}}` (shown when it is false) sections, and `{{description}}`. Facts are booleans
only: never a name, never text another workspace wrote. `refresh_skills(root)` renders every
turned-on add-on that has such a skill and writes only what changed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from orch import skills
from orch.errors import Refused

_SEC = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.S)
_TAG = re.compile(r"\{\{[#^/]\w+\}\}")
_STANDALONE = re.compile(r"^(\{\{[#^/]\w+\}\})\n", re.M)
DESCRIPTION_FILE = "description.toml"
MESSAGE = "Skills updated; they apply from the next agent session."

# Facts each skill may use, and which combinations cannot happen (used by the lint test to render every one).
FACTS: dict[str, list[str]] = {
    "orch-relay": ["connected", "workspaces", "files", "delegate", "start", "phones", "webhooks"],
    "orch-publish": ["connected", "files", "apps", "permanent", "public"],
    "orch-automation": ["relay", "webhooks"],
    "orch-dashboard": ["publish"],
}


def possible(skill: str, f: dict[str, bool]) -> bool:
    if skill in ("orch-relay", "orch-publish") and not f["connected"]:
        return not any(v for k, v in f.items() if k != "connected")
    if skill == "orch-relay" and not f["workspaces"] and (f["files"] or f["delegate"] or f["start"]):
        return False
    if skill == "orch-automation" and f["webhooks"] and not f["relay"]:
        return False
    return True


def render(text: str, facts: dict[str, bool]) -> str:
    """Sections by boolean facts. An unknown fact is an error, so a typo cannot silently hide text."""
    for name in {m.group(0)[3:-2] for m in _TAG.finditer(text)}:
        if name not in facts:
            raise ValueError(f"unknown fact in skill text: {name}")
    text = _STANDALONE.sub(r"\1", text)  # a tag alone on its line leaves no blank line
    while True:
        new = _SEC.sub(lambda m: m.group(3) if bool(facts[m.group(2)]) == (m.group(1) == "#") else "", text)
        if new == text:
            break
        text = new
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)


def description(spec: dict, facts: dict[str, bool]) -> str:
    """The frontmatter description from description.toml: what the agent can do with what is on."""
    if "offline" in spec and not facts.get("connected", True):
        return spec["offline"]["text"]
    o = spec["online"]
    parts = [p["text"] for p in o["part"] if all(facts.get(w) for w in p["when"])]
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", or " + parts[-1]
    return f"{o['lead']} Use when you need to: {joined}. {o['not_for']}"


def render_skill(source: Path, facts: dict[str, bool]) -> tuple[str, str]:
    """(SKILL.md text, AGENTS block text) for a skill folder and facts."""
    body = render((source / "SKILL.md").read_text(encoding="utf-8"), facts)
    spec_file = source / DESCRIPTION_FILE
    if spec_file.is_file():
        desc = description(tomllib.loads(spec_file.read_text(encoding="utf-8")), facts)
        body = body.replace("{{description}}", desc.replace('"', "'"))
    block = ""
    for fn in skills.BLOCK_FILES:
        if (source / fn).is_file():
            block = render((source / fn).read_text(encoding="utf-8"), facts)
            break
    return body, block


# ---------------------------------------------------------------- facts from what the workspace has


def _json(path: Path) -> dict:
    from orch import net

    d = net.read_json(path, {})
    return d if isinstance(d, dict) else {}


def _connected(root: Path, service: str) -> dict | None:
    cfg = _json(root / ".orch" / "secrets" / f"{service}.json")
    return cfg if {"url", "workspace", "token"} <= cfg.keys() else None


def facts_for(root: Path, skill: str) -> dict[str, bool]:
    if skill == "orch-relay":
        ws = _json(root / ".agents" / "skills" / "orch-relay" / "workspaces.json")
        can = [w.get("can_send") or {} for w in ws.get("workspaces", []) if isinstance(w, dict)]
        connected = _connected(root, "relay") is not None
        return {
            "connected": connected,
            "workspaces": any(any(c.values()) for c in can),
            "files": any(c.get("files") for c in can),
            "delegate": any(c.get("delegate") for c in can),
            "start": any(c.get("start") for c in can),
            "phones": bool(ws.get("phones")),
            "webhooks": connected,
        }
    if skill == "orch-publish":
        cfg = _connected(root, "publish")
        rights = (cfg or {}).get("rights") or {}
        return {
            "connected": cfg is not None,
            **{k: bool(rights.get(k)) for k in ("files", "apps", "permanent", "public")},
        }
    relay = _connected(root, "relay") is not None
    if skill == "orch-automation":
        return {"relay": relay, "webhooks": relay}
    if skill == "orch-dashboard":
        return {"publish": _connected(root, "publish") is not None}
    return {}


def remember_rights(root: Path, who: dict) -> None:
    """Keep what the publish server allows this workspace (files, apps, permanent, public) for the skill."""
    from orch import net

    p = root / ".orch" / "secrets" / "publish.json"
    cfg = _json(p)
    rights = who.get("rights") if isinstance(who, dict) else None
    if cfg and isinstance(rights, dict) and cfg.get("rights") != rights:
        net.write_json(p, {**cfg, "rights": {k: bool(v) for k, v in rights.items()}}, True)


# ---------------------------------------------------------------- writing


def _safe_write(root: Path, dest: Path, text: str) -> None:
    """Into .orch/harness/skills only, never through a link: the file is replaced (a new file next to it,
    then rename), so a planted SKILL.md link is replaced, not followed."""
    from orch import harness

    skills.check_inside(root, dest)
    harness.write_text(dest, text)


def render_installed(root: Path, addon: str, source: Path) -> bool:
    """Render one turned-on add-on's skill and block into .orch/harness. True if it changed."""
    skill = f"orch-{addon}"
    if "{{" not in (source / "SKILL.md").read_text(encoding="utf-8"):
        return False  # a plain skill: install_skill already copied it
    dest = skills.harness_skill(root, skill) / "SKILL.md"
    body, block = render_skill(source, facts_for(root, skill))
    changed = False
    if not dest.is_file() or dest.read_text(encoding="utf-8") != body:
        _safe_write(root, dest, body)
        changed = True
    if block:
        from orch import harness

        if (harness.current_block(root, addon) or "").strip() != re.sub(r"<!--.*?-->", "", block, flags=re.S).strip():
            skills.set_block(root, addon, block, addon=True)
            changed = True
    return changed


def refresh_skills(root: Path, say: bool = True) -> list[str]:
    """Render the skills of every turned-on add-on that says what is on. Writes only on change."""
    from orch import addons

    changed = []
    found = addons.discover()
    for name in sorted(addons.active(root)):
        m = found.get(name)
        if not m or "skill" not in m:
            continue
        source = m["dir"] / m["skill"]
        if not (source / "SKILL.md").is_file():
            continue
        if render_installed(root, name, source):
            changed.append(name)
    if changed and say:
        print(MESSAGE)
    return changed
