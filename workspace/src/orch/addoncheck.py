"""`orch addon check <name|./folder>`: an add-on against contracts/addon-manifest.md, in plain words.

Checks the four parts an add-on plugs in with: the entry point (`orch.addons` in pyproject.toml, or the
installed package's metadata), the manifest (`addons.parse_manifest`, the same check `orch addon add` runs),
the skill (SKILL.md named `orch-<name>`) with its AGENTS block, and the `ext.<name>` schema. Never imports or
runs add-on code. Each problem is one sentence that says what to fix.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from orch import addons, harness
from orch.errors import Refused

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def _frontmatter(text: str) -> dict[str, str]:
    m = _FRONT.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and k and not k.startswith((" ", "\t")):
            out[k.strip()] = v.strip().strip("\"'")
    return out


def _source_entry_point(folder: Path, problems: list[str]) -> tuple[str, str] | None:
    """(name, module) from the folder's pyproject.toml, or None (problems say why)."""
    py = folder / "pyproject.toml"
    if not py.is_file():
        problems.append(
            f"{folder.name} has no pyproject.toml: "
            'add one with an [project.entry-points."orch.addons"] table.'
        )
        return None
    try:
        data = tomllib.loads(py.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        problems.append("pyproject.toml cannot be read: fix its TOML.")
        return None
    eps = ((data.get("project") or {}).get("entry-points") or {}).get("orch.addons")
    if not isinstance(eps, dict) or not eps:
        problems.append(
            "pyproject.toml has no entry point: "
            'add [project.entry-points."orch.addons"] with <name> = "<module>".'
        )
        return None
    if len(eps) != 1:
        problems.append('pyproject.toml names more than one add-on under "orch.addons": keep exactly one.')
        return None
    name, module = next(iter(eps.items()))
    return name, module


def _installed_entry_point(name: str, problems: list[str]) -> tuple[str, str] | None:
    eps = addons._entry_points()
    eps = list(eps.items()) if isinstance(eps, dict) else list(eps)
    mods = [m for n, m in eps if n == name]
    if not mods:
        problems.append(
            f'No installed package has the entry point {name} in "orch.addons": '
            "reinstall it with orch addon add."
        )
        return None
    if len(mods) > 1:
        problems.append(f'Two installed packages register {name} in "orch.addons": uninstall one of them.')
        return None
    return name, mods[0]


def _manifest_in(folder: Path, module: str) -> Path | None:
    for f in (folder / "src" / module / addons.MANIFEST, folder / module / addons.MANIFEST):
        if f.is_file():
            return f
    return None


def _check_entry(name: str, module: str, problems: list[str]) -> bool:
    if not addons.NAME_RE.match(name):
        problems.append(f"The entry point name '{name}' is not 2 to 32 lowercase letters, digits or dashes.")
        return False
    if not isinstance(module, str) or not addons.MODULE_RE.match(module):
        problems.append(
            f'The entry point {name} = "{module}" must name a top-level module only (no ":object", no dots).'
        )
        return False
    return True


def _check_skill(m: dict, problems: list[str]) -> None:
    name, base = m["name"], m["dir"]
    skill = base / m["skill"]
    try:
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        problems.append("The skill's SKILL.md cannot be read as UTF-8 text: save it as UTF-8.")
        return
    front = _frontmatter(text)
    if not front:
        problems.append(
            "The skill's SKILL.md has no front matter: start it with --- name: ... description: ... ---."
        )
    else:
        if front.get("name") != f"orch-{name}":
            problems.append(
                f"The skill's SKILL.md says name: {front.get('name') or '(none)'}; it must be orch-{name}."
            )
        if not front.get("description"):
            problems.append("The skill's SKILL.md has no description: say in one sentence when to use it.")
    try:
        block = (base / m["agents_block"]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        problems.append("The AGENTS block cannot be read as UTF-8 text: save it as UTF-8.")
        return
    if not harness.strip_comments(block).strip():
        problems.append(
            f"The AGENTS block ({m['agents_block']}) is empty: add a few lines that point to the skill."
        )


def _check_ext(m: dict, problems: list[str]) -> None:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    rel = m.get("ticket_ext") or (m.get("ticket_fields") or {}).get("schema")
    rows = [r["field"] for r in m.get("ticket_view", [])]
    card = list((m.get("ticket_fields") or {}).get("show_on_card", []))
    if not rel:
        if rows or card:
            problems.append(
                f"Ticket rows read ext.{m['name']} but there is no ticket_ext: "
                f"add a JSON Schema for ext.{m['name']}."
            )
        return
    schema = json.loads((m["dir"] / rel).read_text(encoding="utf-8"))  # parse_manifest read it already
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        problems.append(f"{rel} is not a valid JSON Schema ({e.message}): fix it.")
        return
    if schema.get("type") != "object":
        problems.append(
            f'{rel} must describe an object (type = "object"): ext.{m["name"]} is one JSON object.'
        )
    props = schema.get("properties")
    if isinstance(props, dict):
        for f in dict.fromkeys(rows + card):
            if f not in props:
                problems.append(
                    f"{f} is shown on tickets but {rel} has no property {f}: add it to the schema."
                )


def resolve(target: str) -> tuple[Path, str | None]:
    """(folder, installed name or None). A path is a source folder; a name is a built-in core add-on, a
    shipped add-on in the local source folder, or an installed add-on."""
    if addons._is_path(target):
        folder = Path(target).expanduser().resolve()
        if not folder.is_dir():
            raise Refused(
                f"{target} is not a folder. Check an add-on folder with: orch addon check ./my-addon"
            )
        return folder, None
    if target in addons.CORE_ADDONS:
        return Path(addons.__file__).resolve().parent / "builtin" / target, target
    r = addons.repo()
    if addons._is_local(r) and (Path(r) / "workspace-addons" / target / "pyproject.toml").is_file():
        return Path(r) / "workspace-addons" / target, None
    eps = addons._entry_points()
    names = [n for n, _ in (eps.items() if isinstance(eps, dict) else eps)]
    if target in names:
        return Path(), target
    raise Refused(
        f"No add-on named {target} is installed here. "
        f"Check an add-on folder with: orch addon check ./{target}"
    )


def check(target: str) -> dict:
    """{"name", "folder", "ok", "problems": [plain sentences]}."""
    folder, installed = resolve(target)
    problems: list[str] = []
    name = module = None
    manifest: Path | None = None
    if installed in addons.CORE_ADDONS:
        name, module, manifest = installed, "orch", folder / addons.MANIFEST
    else:
        ep = (
            _installed_entry_point(installed, problems)
            if installed
            else _source_entry_point(folder, problems)
        )
        if ep and _check_entry(*ep, problems):
            name, module = ep
            if installed:
                manifest = addons._manifest_file(module)
                folder = manifest.parent if manifest else folder
            else:
                manifest = _manifest_in(folder, module)
            if manifest is None:
                problems.append(
                    f"There is no {addons.MANIFEST} next to the package {module}: "
                    f"put it beside {module}/__init__.py."
                )
            elif not (manifest.parent / "__init__.py").is_file():
                problems.append(
                    f"{module} has no __init__.py beside {addons.MANIFEST}: it must be a Python package."
                )
    m = None
    if manifest is not None:
        try:
            m = addons.parse_manifest(manifest, core=installed in addons.CORE_ADDONS)
        except Refused as e:
            problems.append(str(e))
    if m is not None:
        if m["name"] != name:
            problems.append(
                f'The entry point is {name} but {addons.MANIFEST} says name = "{m["name"]}": '
                "make them the same."
            )
        if m["run"] != module:
            problems.append(
                f"The entry point names the module {module} but "
                f'{addons.MANIFEST} says run = "{m["run"]}": make them the same.'
            )
        _check_skill(m, problems)
        _check_ext(m, problems)
    return {
        "name": (m or {}).get("name") or name or target,
        "folder": str(folder),
        "ok": not problems,
        "problems": problems,
    }


def text(res: dict) -> str:
    if res["ok"]:
        return (
            f"{res['name']}: ok "
            "(entry point, manifest, skill, AGENTS block and ext key follow the add-on contract)."
        )
    n = len(res["problems"])
    head = (
        f"{res['name']}: {n} problem{'s' if n != 1 else ''} "
        "with the add-on contract (contracts/addon-manifest.md):"
    )
    return "\n".join([head, *(f"  - {p}" for p in res["problems"])])
