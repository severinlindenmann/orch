"""What helpers get in this workspace, for the Skills page and `orch skills list --json` (read only).

Four kinds (skill, instructions, service, login) from four places: orch (orch's own and its add-ons' skills),
workspace (this folder), admin (shared over the relay) and mine (this computer's own, outside the folder).
Every item says whether it is on, whether and why it can be turned off here, what each helper tool does with it
and what needs a look. Names and short texts only: never a key, an environment value or a server address path.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from . import switches
from .switches import Refused

SCHEMA = "orch.skills-page/1"
TOOLS = {"claude": "Claude", "codex": "Codex"}
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.local.md")
DESC_MIN = 20
_DESC = re.compile(r"^description:[ \t]*(.*)$", re.MULTILINE)
_ID_PART = re.compile(r"[^A-Za-z0-9_.@-]")


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def item_id(kind: str, where: str, name: str) -> str:
    """kind:where:name, one plain line (the page's click target, at most 200 characters)."""
    return f"{kind}:{where}:{_ID_PART.sub('_', name)[:120]}"


def _is_link(p: Path) -> bool:
    return switches._is_link(p)


def _text(path: Path, limit: int = 256 * 1024) -> str:
    try:
        if _is_link(path) or not path.is_file() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _header(folder: Path) -> dict:
    """The skill header through the one reader (ORCH-532's orch.skillmeta); without it only the description."""
    try:
        from orch import skillmeta
    except ImportError:
        m = _DESC.search(_text(folder / "SKILL.md").split("\n---", 2)[0])
        return {"description": m.group(1).strip().strip("\"'")} if m else {}
    try:
        return skillmeta.try_header(folder)
    except Exception:  # noqa: BLE001  an unreadable header shows as "has no real description"
        return {}


def _home(account_home: Path | None) -> Path:
    """The person's own home (the core's real_home: right under a test or a guarded orch home too)."""
    if account_home:
        return Path(account_home)
    try:
        from orch import addons

        return Path(addons.real_home())
    except Exception:  # noqa: BLE001
        return Path(os.path.expanduser("~"))


def _tools(root: Path) -> list[str]:
    try:
        from orch import skills

        found = [n for n in skills.detected_agents(root) if n in TOOLS]
    except Exception:  # noqa: BLE001  no core: Claude is the one tool this page can switch
        found = []
    return found or ["claude"]


# ---- skills -------------------------------------------------------------------------------------------------


def _skill_folders(base: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    try:
        kids = sorted(base.iterdir()) if base.is_dir() and not _is_link(base) else []
    except OSError:
        kids = []
    for p in kids:
        if (p / "SKILL.md").is_file() and not p.name.startswith("."):
            out[p.name] = p
    return out


def _skill_sources(root: Path, account_home: Path | None) -> list[tuple[str, str, Path]]:
    """(where, name, folder): orch's harness skills, the workspace's own and shared ones, then this computer's."""
    found: list[tuple[str, str, Path]] = []
    harness = root / ".orch" / "harness" / "skills"
    orch_names = set(_skill_folders(harness))
    for name, folder in _skill_folders(harness).items():
        found.append(("orch", name, folder))
    seen = set(orch_names)
    for base in (root / ".agents" / "skills", root / ".claude" / "skills"):
        for name, folder in _skill_folders(base).items():
            if name in seen:
                continue
            seen.add(name)
            found.append(("admin" if (folder / ".orch-shared").exists() else "workspace", name, folder))
    try:
        from orch import inventory

        dirs = inventory.harness_skill_dirs(account_home)
    except Exception:  # noqa: BLE001
        dirs = []
    for base in dirs:
        for name, folder in _skill_folders(base).items():
            if (name, "mine") not in {(n, w) for w, n, _ in found}:
                found.append(("mine", name, folder))
    return found


def _skill_problems(root: Path, head: dict, meta: dict, keys: set[str]) -> list[str]:
    out = []
    if meta.get("status") == "retired":
        out.append("Retired, but helpers still see it")
    if len((head.get("description") or "").strip()) < DESC_MIN:
        out.append("Has no real description")
    for prog in [p.strip() for p in (meta.get("requires") or "").split(",") if p.strip()]:
        if shutil.which(prog) is None:
            out.append(f"Not ready here: {prog} is missing")
    for login in [p.strip() for p in (meta.get("requires-logins") or "").split(",") if p.strip()]:
        if login not in keys:
            out.append(f"Needs the login {login}, which is not stored here")
    rb = meta.get("review-by") or ""
    try:
        if rb and date.fromisoformat(rb) < date.today():
            out.append(f"Review date passed ({rb})")
    except ValueError:
        pass
    return out


def skills(root: Path, account_home: Path | None = None, keys: set[str] | None = None) -> list[dict]:
    from orch import skills as core

    off = core.off_names(root)
    claude = switches.claude_state(root)["skillOverrides"]
    tools = _tools(root)
    items = []
    for where, name, folder in _skill_sources(root, account_home):
        head = _header(folder)
        meta = head.get("metadata") if isinstance(head.get("metadata"), dict) else {}
        item = {
            "id": item_id("skill", where, name),
            "kind": "skill",
            "name": name,
            "where": where,
            "description": (head.get("description") or "").strip(),
            "fields": {k: v for k, v in meta.items() if isinstance(v, str)},
            "words": len((head.get("description") or "").split()),
        }
        if where in ("orch", "admin"):
            linked_off = name in off
            item["on"] = not linked_off and name not in claude
            item["switch"] = "linked"
            if name in core.ALWAYS_ON:
                item.update(on=True, locked="orch needs it to work tickets; always on")
            elif name in claude and claude[name] == "hand":
                item["locked"] = "Turned off by hand in .claude/settings.local.json"
            # orch's links reach every tool; a shared folder itself stays in .agents/skills, which Codex reads
            item["tools"] = {
                TOOLS[t]: "off" if not item["on"] and not (where == "admin" and t == "codex") else "on" for t in tools
            }
        else:
            item["on"] = name not in claude
            item["switch"] = "claude"
            if claude.get(name) == "hand":
                item["locked"] = "Turned off by hand in .claude/settings.local.json"
            item["tools"] = {TOOLS[t]: ("off" if (t == "claude" and not item["on"]) else "on") for t in tools}
        item["problems"] = _skill_problems(root, head, meta, keys or set()) if item["on"] else []
        items.append(item)
    return items


# ---- instructions -------------------------------------------------------------------------------------------


def instructions(root: Path, account_home: Path | None = None) -> list[dict]:
    excl = switches.claude_state(root)["claudeMdExcludes"]
    tools = _tools(root)
    items = []
    mine = _home(account_home) / ".claude" / "CLAUDE.md"
    if mine.is_file():
        on = str(mine) not in excl
        it = {
            "id": item_id("instructions", "mine", "CLAUDE.md"),
            "kind": "instructions",
            "name": "Your rules for every project",
            "file": "~/.claude/CLAUDE.md",
            "where": "mine",
            "on": on,
            "switch": "claude",
            "words": len(_text(mine).split()),
            "description": "Your own rules for Claude, read in every folder on this computer.",
            "tools": {"Claude": "on" if on else "off"},
            "problems": [],
        }
        if excl.get(str(mine)) == "hand":
            it["locked"] = "Turned off by hand in .claude/settings.local.json"
        items.append(it)
    for fn in INSTRUCTION_FILES:
        p = root / fn
        if not p.is_file():
            continue
        text = _text(p)
        items.append(
            {
                "id": item_id("instructions", "workspace", fn),
                "kind": "instructions",
                "name": fn,
                "file": fn,
                "where": "workspace",
                "on": True,
                "locked": "Helpers in this workspace always read it",
                "words": len(text.split()),
                "description": _first_line(text),
                "tools": {TOOLS[t]: "on" for t in tools},
                "problems": [],
            }
        )
    block = root / ".orch" / "harness" / "AGENTS.orch.md"
    if block.is_file():
        text = _text(block)
        items.append(
            {
                "id": item_id("instructions", "orch", "AGENTS.orch.md"),
                "kind": "instructions",
                "name": "orch blocks",
                "file": "AGENTS.orch.md",
                "where": "orch",
                "on": True,
                "locked": "Written by orch: one block for each add-on that is on. Turn the add-on off to remove its block",
                "words": len(text.split()),
                "description": f"{text.count(chr(10) + '## ') + text.startswith('## ')} blocks, one per add-on.",
                "tools": {TOOLS[t]: "on" for t in tools},
                "problems": [],
            }
        )
    return items


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("@", "<!--")):
            return line[:160]
    return next((x.strip() for x in text.splitlines() if x.strip()), "")[:160]


# ---- connected services and logins --------------------------------------------------------------------------

WHERE_OF_SOURCE = {"workspace": "workspace", "admin": "admin", "harness": "mine"}


def services(root: Path, account_home: Path | None = None) -> list[dict]:
    try:
        from orch import inventory

        conns, _ = inventory.connections(root, account_home=account_home)
    except Exception:  # noqa: BLE001  no inventory: nothing listed (the page says so)
        conns = []
    deny = switches.claude_state(root)["deny"]
    tools = _tools(root)
    items = []
    for c in conns:
        if c.get("shadowed"):
            continue
        rule = switches.mcp_rule(c["name"])
        on = rule not in deny
        it = {
            "id": item_id("service", WHERE_OF_SOURCE.get(c["source"], "workspace"), c["name"]),
            "kind": "service",
            "name": c.get("label") or c["name"],
            "server": c["name"],
            "where": WHERE_OF_SOURCE.get(c["source"], "workspace"),
            "on": on,
            "switch": "claude",
            "description": "Program on this computer: " + c["command"]
            if c.get("command")
            else ("Web service at " + c["host"] if c.get("host") else "Connected service"),
            "tools": {TOOLS[t]: ("off" if t == "claude" and not on else "on") for t in tools},
            "problems": ["Its login is not stored here"] if c.get("state") == "missing-key" and on else [],
        }
        if deny.get(rule) == "hand":
            it["locked"] = "Turned off by hand in .claude/settings.local.json"
        items.append(it)
    return items


def logins(root: Path) -> list[dict]:
    try:
        from orch import inventory

        keys = inventory.keys(root)
    except Exception:  # noqa: BLE001
        keys = []
    kind = {"token": "Key", "password": "Password", "key-file": "Key file", "json": "Key file"}
    return [
        {
            "id": item_id("login", "admin" if k["source"] == "admin" else "workspace", k["name"]),
            "kind": "login",
            "name": k["name"],
            "where": "admin" if k["source"] == "admin" else "workspace",
            "on": True,
            "locked": "Turning a login off for helpers comes in a later version",
            "description": kind.get(k["type"], "Key") + ". Helpers see only its name, never the secret.",
            "tools": {},
            "problems": [],
        }
        for k in keys
    ]


def build(root: Path, account_home: Path | None = None) -> dict:
    root = Path(root)
    lg = logins(root)
    data = {
        "schema": SCHEMA,
        "generated_at": now(),
        "tools": [TOOLS[t] for t in _tools(root)],
        "skills": skills(root, account_home, {x["name"] for x in lg}),
        "instructions": instructions(root, account_home),
        "services": services(root, account_home),
        "logins": lg,
    }
    for kind in ("skills", "instructions", "services", "logins"):
        for it in data[kind]:
            it["can_off"] = it.get("switch") is not None and "locked" not in it
            seen = [t for t, s in it.get("tools", {}).items() if s == "on"]
            if not it["on"] and seen:
                it["note"] = " and ".join(seen) + (" still sees it" if len(seen) == 1 else " still see it")
    return data


def find(root: Path, target: str, account_home: Path | None = None) -> dict:
    data = build(root, account_home)
    for kind in ("skills", "instructions", "services", "logins"):
        for it in data[kind]:
            if it["id"] == target:
                return it
    raise Refused("That item is not here any more. Reload the page and try again.")


def turn(root: Path, target: str, on: bool, account_home: Path | None = None) -> dict:
    """Turn one item off or on here. Returns {"item", "changed"}; refuses what cannot be switched."""
    it = find(root, target, account_home)
    if it.get("locked"):
        raise Refused(f"{it['name']}: {it['locked']}.")
    if it.get("switch") is None:
        raise Refused(f"{it['name']} cannot be turned off here.")
    if it["kind"] == "skill" and it["switch"] == "linked":
        changed = switches.set_linked(root, it["name"], on)
    elif it["kind"] == "skill":
        changed = switches.set_claude(root, "skillOverrides", it["name"], on)
    elif it["kind"] == "service":
        changed = switches.set_claude(root, "deny", switches.mcp_rule(it["server"]), on)
    elif it["kind"] == "instructions" and it["where"] == "mine":
        changed = switches.set_claude(root, "claudeMdExcludes", str(_home(account_home) / ".claude" / "CLAUDE.md"), on)
    else:
        raise Refused(f"{it['name']} cannot be turned off here.")
    return {"item": find(root, target, account_home), "changed": changed}
