"""What helpers get in this workspace, for the Skills page and `orch skills list --json` (read only).

Four kinds (skill, instructions, service, login) from four places: orch (orch's own and its add-ons' skills),
workspace (this folder), admin (shared over the relay) and mine (this computer's own, outside the folder).
Every item says whether it is on, whether and why it can be turned off here, what each helper tool does with it
and what needs a look. Names and short texts only: never a key, an environment value or a server address path.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from . import jsonswitch, shared, signin, switches, tomlswitch
from . import tools as toolsdata
from .switches import Refused

SCHEMA = "orch.skills-page/1"
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


def _tools(root: Path) -> dict[str, dict]:
    return toolsdata.here(root)


def _fmt(t: dict) -> str:
    return t["switches"].get("format", "")


def _json_states(root: Path, tl: dict) -> dict[str, dict]:
    return {n: jsonswitch.state(root, n, t) for n, t in tl.items() if _fmt(t) == "json"}


def _by_hand(t: dict) -> str:
    return f"Turned off by hand in {t['switches']['file']}"


def _instruction_files(tl: dict) -> list[str]:
    try:
        from orch import adapters

        guide = list(adapters.GUIDE_FILES)
    except Exception:  # noqa: BLE001
        guide = ["AGENTS.md"]
    names = [
        *guide,
        *(f for t in toolsdata.all_tools().values() for f in t.get("instruction_files", [])),
        "AGENTS.local.md",
    ]
    return list(dict.fromkeys(names))


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
    for base in [root / p for p in switches.skill_places()]:
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
            out.append(f"Not ready here: a program it needs is not installed ({prog})")
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


def _kept_copy(root: Path, name: str) -> bool:
    """A copy of an orch skill (no links on this computer) that holds an add-on's own file: orch keeps it."""
    try:
        from orch import harness
    except ImportError:
        return False
    for where in switches.skill_places():
        p = root / where / name
        if not _is_link(p) and p.is_dir() and harness._keep_files(p):
            return True
    return False


def skills(root: Path, account_home: Path | None = None, keys: set[str] | None = None) -> list[dict]:
    from orch import skills as core

    off = core.off_names(root)
    tl = _tools(root)
    js = _json_states(root, tl)
    skill_off = {n: js[n].get("skill", {}) for n in js if isinstance(tl[n]["switches"].get("skill"), dict)}
    home = _home(account_home)
    offered, gone = shared.offered(root), shared.removed(root)
    waiting = shared.newer_waiting(root)
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
        hand = [n for n, st in skill_off.items() if st.get(name) == "hand"]
        if where in ("workspace", "mine") and _is_link(folder):
            item["link"] = True  # a link to somewhere else: orch does not delete through it
        if where in ("orch", "admin"):
            item["on"] = name not in off and not any(name in st for st in skill_off.values())
            item["switch"] = "linked"
            if name in core.ALWAYS_ON:
                item.update(on=True, locked="orch needs it to work tickets; always on")
            elif item["on"] and _kept_copy(root, name):
                item["locked"] = (
                    "On this computer it is a copy that holds its add-on's file; turn the add-on off instead"
                )
            elif hand:
                item["locked"] = _by_hand(tl[hand[0]])
            # orch's links reach every tool; a shared folder itself stays in .agents/skills, which a tool without
            # its own skills folder link reads directly
            item["tools"] = {
                t["label"]: "off" if not item["on"] and not (where == "admin" and not t.get("skills_link")) else "on"
                for t in tl.values()
            }
        else:
            seeing = tl
            if where == "mine":
                seeing = {
                    n: t
                    for n, t in tl.items()
                    if any(Path(toolsdata.fill(d, home)) == folder.parent for d in t.get("skill_dirs", []))
                } or tl
            item["on"] = not any(name in skill_off.get(n, {}) for n in seeing)
            item["switch"] = "tool" if any(n in skill_off for n in seeing) else None
            hand = [n for n in hand if n in seeing]  # a tool that does not read this folder locks nothing here
            if hand:
                item["locked"] = _by_hand(tl[hand[0]])
            item["tools"] = {t["label"]: ("off" if name in skill_off.get(n, {}) else "on") for n, t in seeing.items()}
            limits = [t for n, t in seeing.items() if n not in skill_off and t["switches"].get("skill_limit")]
            if limits and where == "workspace":
                t = limits[0]
                item["tool_limit"] = f"{t['label']} {t['switches']['skill_limit']}, so {t['label']} still sees it"
        item["problems"] = _skill_problems(root, head, meta, keys or set()) if item["on"] else []
        if where == "admin":
            item["actions"] = ["remove"]
            if waiting:
                item["newer"] = "Your admin has newer shared settings; they arrive with the next relay update"
        items.append(item)
    for name, had in sorted(gone.items()):
        now_v = offered.get(name)
        item = {
            "id": item_id("skill", "admin", name),
            "kind": "skill",
            "name": name,
            "where": "admin",
            "on": False,
            "removed": True,
            "locked": "Removed from this workspace; relay updates do not bring it back",
            "description": "Removed here. Your admin still has it.",
            "fields": {},
            "tools": {},
            "problems": [],
            "actions": ["restore"],
        }
        if now_v is not None and now_v > had:
            item["newer"] = "Your admin has a newer version than the one you removed"
        elif now_v is None and offered:
            item["description"] = "Removed here. Your admin no longer shares it with this workspace."
        items.append(item)
    return items


# ---- instructions -------------------------------------------------------------------------------------------


def instructions(root: Path, account_home: Path | None = None) -> list[dict]:
    tl = _tools(root)
    js = _json_states(root, tl)
    home = _home(account_home)
    labels = [t["label"] for t in tl.values()]
    items = []
    for n, t in tl.items():
        spec = t["switches"].get("rules")
        if not isinstance(spec, dict) or n not in js:
            continue
        mine = Path(toolsdata.fill(spec["file"], home))
        if not mine.is_file():
            continue
        excl = js[n].get("rules", {})
        on = str(mine) not in excl
        it = {
            "id": item_id("instructions", "mine", mine.name),
            "kind": "instructions",
            "name": "Your rules for every project",
            "file": spec.get("shown", mine.name),
            "where": "mine",
            "tool": n,
            "on": on,
            "switch": "tool",
            "words": len(_text(mine).split()),
            "description": spec.get("words", "").replace("{label}", t["label"]),
            "tools": {t["label"]: "on" if on else "off"},
            "problems": [],
        }
        if excl.get(str(mine)) == "hand":
            it["locked"] = _by_hand(t)
        items.append(it)
    for fn in _instruction_files(tl):
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
                "tools": {lb: "on" for lb in labels},
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
                "tools": {lb: "on" for lb in labels},
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
        managed = inventory.harness_manage_in(root, account_home)
    except Exception:  # noqa: BLE001  no inventory: nothing listed (the page says so)
        conns, managed = [], {}
    tl = _tools(root)
    js = _json_states(root, tl)
    home = _home(account_home)
    tom = {n: tomlswitch.state(root, n, t, home) for n, t in tl.items() if _fmt(t) == "toml"}
    seen = signin.read(root)
    check = signin.checker(tl)
    asker = check[1] if check else None
    items = []
    for c in conns:
        if c.get("shadowed"):
            continue
        states, hand, limits = {}, [], []
        manage_in = managed.get(c["name"]) if c.get("source") == "harness" else None
        for n, t in tl.items():
            spec = t["switches"].get("service")
            if not isinstance(spec, dict) or manage_in:
                continue
            if n in js:
                st = js[n].get("service", {}).get(jsonswitch.render(spec, c["name"]))
                states[t["label"]] = "off" if st else "on"
                if st == "hand":
                    hand.append(t)
            elif n in tom and c["name"] in tom[n]["service"]:
                st = tom[n]["service"][c["name"]]
                states[t["label"]] = "on" if st == "on" else "off"
                if st == "hand":
                    hand.append(t)
                if not tom[n]["trusted"]:
                    limits.append(t)
        on = all(v == "on" for v in states.values())
        it = {
            "id": item_id("service", WHERE_OF_SOURCE.get(c["source"], "workspace"), c["name"]),
            "kind": "service",
            "name": c.get("label") or c["name"],
            "server": c["name"],
            "where": WHERE_OF_SOURCE.get(c["source"], "workspace"),
            "on": on,
            "switch": "tool" if states else None,
            "description": "Program on this computer: " + c["command"]
            if c.get("command")
            else ("Web service at " + c["host"] if c.get("host") else "Connected service"),
            "tools": states,
            "problems": ["Its login is not stored here"] if c.get("state") == "missing-key" and on else [],
        }
        if c.get("profile"):
            it["signin"] = (
                "Its login is not stored here" if c.get("state") == "missing-key" else "Its login is stored here"
            )
            it["signin_state"] = "needs-sign-in" if c.get("state") == "missing-key" else "connected"
        elif c["name"] in seen["servers"]:
            st = seen["servers"][c["name"]]
            it["signin"], it["signin_state"] = signin.text(st, seen["checked_at"], asker, c["name"]), st
            if st == "needs-sign-in" and on:
                it["problems"].append("Needs a sign-in. " + signin.how(asker, c["name"]))
        else:
            it["signin"] = "Not checked yet. The sign-in itself happens in your helper tool, not in orch"
        it["actions"] = ["check"] if check else []
        if manage_in:
            it["manage_in"] = manage_in
        if check:
            it["check_hint"] = check_hint(asker)
        if limits:
            t = limits[0]
            it["tool_limit"] = (
                f"{t['label']} ignores this folder's own settings until you trust this folder in {t['label']}"
            )
            if all(lb == t["label"] for lb in states):
                it["locked"] = it["tool_limit"]
        if hand:
            it["locked"] = _by_hand(hand[0])
        items.append(it)
    return items + _account_services(seen, asker, {i["server"] for i in items})


def check_hint(tool: dict) -> str:
    return f"Also finds the services in your {tool['label']} account. This may take a moment"


def _account_services(seen: dict, asker: dict | None, taken: set[str]) -> list[dict]:
    """Services of the person's account that no file has, as the last Check sign-in found them (ORCH-1819):
    read only from the cache, so a page load starts nothing."""
    label = (asker or {}).get("label") or seen.get("by")
    if not label:
        return []
    items = []
    for name in seen["account"]:
        if name in taken:
            continue
        st = seen["servers"][name]
        it = {
            "id": item_id("service", "account", name),
            "kind": "service",
            "name": signin.shown_name(name, asker),
            "server": name,
            "where": "account",
            "from": f"In your {label} account",
            "on": True,
            "switch": None,
            "manage_in": label,
            "description": f"In your {label} account",
            "tools": {},
            "problems": ["Needs a sign-in. " + signin.how(asker, name)] if st == "needs-sign-in" else [],
            "signin": signin.text(st, seen["checked_at"], asker, name),
            "signin_state": st,
            "actions": ["check"] if asker else [],
        }
        if asker:
            it["check_hint"] = check_hint(asker)
        items.append(it)
    return items


PER_WORKSPACE = "This switch counts for this workspace only; your other workspaces keep their own"


def _profiles(root: Path) -> dict:
    try:
        from orch import keystore

        got = keystore.read_profiles(root)
    except Exception:  # noqa: BLE001  no key store or a damaged profiles file: none (orch secret list says why)
        return {}
    return {n: p for n, p in got.items() if isinstance(n, str) and isinstance(p, dict)}


def logins(root: Path) -> list[dict]:
    """One row per key profile (what helpers get: on = helpers may use it with any command, the switch of
    `orch secret profile agents-enable|agents-disable`, kept per workspace), then keys no profile uses."""
    try:
        from orch import inventory

        keys = inventory.keys(root)
    except Exception:  # noqa: BLE001
        keys = []
    kind = {"token": "Key", "password": "Password", "key-file": "Key file", "json": "Key file"}
    used: set[str] = set()
    items = []
    for name, prof in sorted(_profiles(root).items()):
        names = sorted(
            {v for sect in ("env", "files") if isinstance(prof.get(sect), dict) for v in prof[sect].values()}
        )
        used |= set(names)
        run = prof.get("run") if isinstance(prof.get("run"), list) else []
        prog = Path(str(run[0])).name if run else ""
        on = prof.get("agents_may_env") is True
        items.append(
            {
                "id": item_id("login", "workspace", name),
                "kind": "login",
                "name": name,
                "where": "workspace",
                "on": on,
                "switch": "profile",
                "description": "Uses " + (", ".join(names) or "no key") + ". Helpers never see the secret.",
                "off_means": (
                    f"Off: helpers can use it only through its own command ({prog})"
                    if prog
                    else "Off: helpers cannot use it; you still can"
                ),
                "on_means": "On: helpers may use it with any command",
                "scope": PER_WORKSPACE,
                "tools": {},
                "problems": [],
            }
        )
    for k in keys:
        if k["name"] in used:
            continue
        items.append(
            {
                "id": item_id("login", "admin" if k["source"] == "admin" else "workspace", "key-" + k["name"]),
                "kind": "login",
                "name": k["name"],
                "where": "admin" if k["source"] == "admin" else "workspace",
                "on": False,
                "locked": "No key profile uses this key, so helpers cannot use it. A profile makes it usable",
                "description": kind.get(k["type"], "Key") + ". Not given to helpers.",
                "tools": {},
                "problems": [],
            }
        )
    return items


def build(root: Path, account_home: Path | None = None) -> dict:
    from . import bin as skill_bin

    root = Path(root)
    with contextlib.suppress(Exception), skill_bin.locked(root, wait=1.0):  # a cut-off move is finished or undone
        skill_bin.recover(root, account_home)  # first; while another change runs, the next look does it
    lg = logins(root)
    data = {
        "schema": SCHEMA,
        "generated_at": now(),
        "tools": [t["label"] for t in _tools(root).values()],
        "skills": skills(root, account_home, {x["name"] for x in lg}),
        "instructions": instructions(root, account_home),
        "services": services(root, account_home),
        "services_checked_at": signin.read(root)["checked_at"],
        "logins": lg,
        "bin": skill_bin.rows(root, account_home),
    }
    _edit_offers(root, data)
    for kind in ("skills", "instructions", "services", "logins"):
        for it in data[kind]:
            it["can_off"] = it.get("switch") is not None and "locked" not in it
            seen = [t for t, s in it.get("tools", {}).items() if s == "on"]
            it["can_delete"] = it["kind"] == "skill" and it["where"] in ("workspace", "mine") and not it.get("link")
            if not it["on"] and seen:
                it["note"] = " and ".join(seen) + (" still sees it" if len(seen) == 1 else " still see it")
            it.setdefault("actions", [])
    return data


NOT_EDITABLE = {
    "orch": "Comes with orch; orch keeps it up to date",
    "admin": "Shared by your admin; ask them to change it",
    "mine": "Editing your computer's own files comes in a later version",
}


def orch_names(data: dict) -> set[str]:
    return {it["name"] for it in data["skills"] if it["where"] in ("orch", "admin")}


def _edit_offers(root: Path, data: dict) -> None:
    """Each skill and instruction file says whether Edit works ({"id", "mode"}) or why not ("edit_why")."""
    from . import edit

    offers = edit.offer(root, orch_names(data))
    for kind, key in (("skills", "skill"), ("instructions", "instructions")):
        for it in data[kind]:
            hit = (
                offers.get((key, it["name"] if key == "skill" else it.get("file", "")))
                if it["where"] == "workspace"
                else None
            )
            if hit and "id" in hit:
                it["edit"] = hit
            else:
                it["edit_why"] = (hit or {}).get("why") or NOT_EDITABLE.get(it["where"], "This cannot be edited here")


def find(root: Path, target: str, account_home: Path | None = None) -> dict:
    data = build(root, account_home)
    for kind in ("skills", "instructions", "services", "logins"):
        for it in data[kind]:
            if it["id"] == target:
                return it
    raise Refused("That item is not here any more. Reload the page and try again.")


def turn(root: Path, target: str, on: bool, account_home: Path | None = None, who: str = "") -> dict:
    """Turn one item off or on here. Returns {"item", "changed"}; refuses what cannot be switched."""
    it = find(root, target, account_home)
    if it.get("locked"):
        raise Refused(f"{it['name']}: {it['locked']}.")
    if it.get("switch") is None:
        raise Refused(f"{it['name']} cannot be turned off here.")
    tl = _tools(root)
    if it["kind"] == "skill" and it["switch"] == "linked":
        changed = switches.set_linked(root, it["name"], on)
    elif it["kind"] == "skill":
        changed = False
        for n, t in tl.items():
            if _fmt(t) == "json" and t["label"] in it["tools"] and isinstance(t["switches"].get("skill"), dict):
                changed = jsonswitch.set_entry(root, n, t, "skill", it["name"], on) or changed
    elif it["kind"] == "service":
        changed = _turn_service(root, tl, it, on)
    elif it["kind"] == "login":
        from orch import cli_secret

        changed = cli_secret.set_agents(root, it["name"], on, who)
    elif it["kind"] == "instructions" and it["where"] == "mine" and it.get("tool") in tl:
        t = tl[it["tool"]]
        path = toolsdata.fill(t["switches"]["rules"]["file"], _home(account_home))
        changed = jsonswitch.set_entry(root, it["tool"], t, "rules", path, on)
    else:
        raise Refused(f"{it['name']} cannot be turned off here.")
    return {"item": find(root, target, account_home), "changed": changed}


def _turn_service(root: Path, tl: dict, it: dict, on: bool) -> bool:
    """Every tool's switch for one service: the TOML ones first (the files most likely to refuse), then the JSON
    ones; a refusal puts back what was already changed, so a refused click changes nothing."""
    done: list[tuple[str, dict]] = []
    changed = False
    order = sorted(tl.items(), key=lambda nt: _fmt(nt[1]) != "toml")
    try:
        for n, t in order:
            spec = t["switches"].get("service")
            if not isinstance(spec, dict) or t["label"] not in it["tools"]:
                continue
            if _fmt(t) == "toml":
                if "tool_limit" in it and it["tool_limit"].startswith(t["label"] + " "):
                    continue
                c = tomlswitch.set_table(root, n, t, it["server"], on)
            else:
                c = jsonswitch.set_entry(root, n, t, "service", jsonswitch.render(spec, it["server"]), on)
            if c:
                done.append((n, t))
            changed = c or changed
    except Refused:
        for n, t in done:
            with contextlib.suppress(Refused, OSError):
                if _fmt(t) == "toml":
                    tomlswitch.set_table(root, n, t, it["server"], not on)
                else:
                    spec = t["switches"]["service"]
                    jsonswitch.set_entry(root, n, t, "service", jsonswitch.render(spec, it["server"]), not on)
        raise
    return changed


def act(root: Path, verb: str, target: str, account_home: Path | None = None) -> dict:
    """The page's other clicks: remove / restore a shared skill, check the services' sign-in."""
    it = find(root, target, account_home)
    if verb not in it.get("actions", []):
        raise Refused(f"{it['name']}: that is not possible here.")
    if verb == "remove":
        changed = shared.remove(root, it["name"])
        text = f"{it['name']} is removed from this workspace. Relay updates no longer bring it back."
    elif verb == "restore":
        text, changed = shared.restore(root, it["name"]), True
    else:
        check = signin.checker(_tools(root))
        if not check:
            raise Refused("No helper tool here can report the sign-in state.")
        names = [i["server"] for i in services(root, account_home) if i["where"] != "account"]
        doc = signin.check(root, now(), check[1], names)
        changed = True
        text = f"Checked {len(doc['servers'])} services with {check[1]['label']}."
        if doc["account"]:
            text += f" {len(doc['account'])} of them are in your {check[1]['label']} account."
    try:
        after = find(root, target, account_home)
    except Refused:
        after = {**it, "gone": True}
    return {"item": after, "changed": changed, "next": text}


def delete(root: Path, target: str, who: str, account_home: Path | None = None) -> dict:
    """Move one workspace or computer skill into its bin. Returns {"item", "bin"}."""
    from . import bin as skill_bin

    it = find(root, target, account_home)
    if not it.get("can_delete"):
        why = (
            "it is a link to somewhere else"
            if it.get("link")
            else "only this workspace's and your computer's skills can"
        )
        raise Refused(f"{it['name']} cannot be deleted here: {why}.")
    with skill_bin.locked(root):
        skill_bin.recover(root, account_home)
        row = skill_bin.delete(root, it["where"], it["name"], who, account_home)
    return {"item": it, "bin": row}


def restore(root: Path, target: str, who: str, account_home: Path | None = None) -> dict:
    """Put one bin entry back where it was (a removed shared skill comes back through act "restore")."""
    from . import bin as skill_bin

    with skill_bin.locked(root):
        skill_bin.recover(root, account_home)
        back = skill_bin.restore(root, target, who, account_home)
    return {"item": {"id": target, "name": back["name"]}, "restored": back}


def new_skill(root: Path, name: str, owner: str, account_home: Path | None = None) -> dict:
    from . import bin as skill_bin

    taken = {it["name"] for it in skills(root, account_home)}
    with skill_bin.locked(root):
        skill_bin.new_skill(root, name, owner, taken)
    return {"item": find(root, item_id("skill", "workspace", name), account_home)}
