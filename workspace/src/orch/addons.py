"""Add-ons (contracts/addon-manifest.md): discovery, install, activation, dispatch, orch update.

The core knows no add-on by name. An add-on is a Python package with an `orch-addon.toml` and an entry point
`<name> = "<module>"` in the group `orch.addons`. Discovery reads the manifest file next to the package
(`importlib.util.find_spec`, top-level only) and never imports or runs add-on code.

Two steps: install (per machine, `~/.orch-tool/addons.json`, uv tool env) and activation (per workspace,
`.orch/addons.json`, written only by `orch addon add|remove`). Only an active add-on gets its command, skill,
AGENTS block, tab and background process. Leftover files or ext data never activate anything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from orch import skills
from orch.errors import Refused

DEFAULT_REPO = "https://github.com/severinlindenmann/orch"
MANIFEST = "orch-addon.toml"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
MODULE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PATH_RE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]{1,200}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
# Names an add-on may never take: core commands (same list as contracts/addon-manifest.schema.json).
RESERVED = frozenset(
    "orch core ticket check log ask answer link ext wait addon addons update init publish relay config help "
    "version view".split()
)
ICONS = frozenset(
    "clock calendar inbox list chart bell book globe link check star box chat folder user bolt".split()
)
FORMATS = frozenset({"text", "time", "cron-human", "chips", "yes-no"})
TOP_KEYS = frozenset(
    "schema orch_api name version description run skill agents_block ticket_ext background dashboard "
    "ticket_view".split()
)
EXT_SCHEMA_MAX = 32 * 1024


# ---------------------------------------------------------------- sources


def repo() -> str:
    return os.environ.get("ORCH_REPO", DEFAULT_REPO)


def ref() -> str:
    return os.environ.get("ORCH_REF", "main")


def _is_local(r: str) -> bool:
    return Path(r).exists()


def spec(subdir: str) -> str:
    r = repo()
    if _is_local(r):
        return str((Path(r) / subdir).resolve())
    r = r.removesuffix(".git")
    return f"git+{r}@{ref()}#subdirectory={subdir}"


def home() -> Path:
    return Path(os.environ.get("ORCH_HOME") or Path.home() / ".orch-tool")


def registry_path() -> Path:
    return home() / "addons.json"


def registry() -> list[dict]:
    """Installed add-ons on this machine: [{name, source, version}]. source = "built-in" or a folder path."""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        e
        for e in data
        if isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("source"), str)
    ]


def _save_registry(entries: list[dict]) -> None:
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(entries, key=lambda e: e["name"])
    registry_path().write_text(json.dumps(entries, indent=2), encoding="utf-8")


def installed_names() -> list[str]:
    return [e["name"] for e in registry()]


def _entry_spec(e: dict) -> str:
    if e["source"] == "built-in":
        return spec(f"workspace-addons/{e['name']}")
    return e["source"]


def _which_uv() -> str | None:
    """uv from PATH, but never one inside the current folder (a planted uv in the project)."""
    found = shutil.which("uv")
    if not found:
        return None
    try:
        Path(found).resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return found
    return None


def run_uv(args: list[str]) -> None:
    """Tests replace this. Real: run uv and show its output."""
    uv = _which_uv()
    if not uv:
        raise Refused("uv is not installed. Run the orch install script first.")
    r = subprocess.run([uv, *args], text=True, capture_output=True)
    if r.returncode != 0:
        raise Refused(f"uv failed: {(r.stderr or r.stdout).strip()[-600:]}")


def _install_tool(entries: list[dict]) -> None:
    args = ["tool", "install", "--reinstall", spec("workspace")]
    for e in entries:
        args += ["--with", _entry_spec(e)]
    run_uv(args)


# ---------------------------------------------------------------- manifest


def _bad(why: str) -> Refused:
    return Refused(f"This add-on's {MANIFEST} is not valid: {why}.")


def _inside(base: Path, rel: str, what: str, must_be: str) -> Path:
    if not isinstance(rel, str) or not PATH_RE.match(rel):
        raise _bad(f"{what} must be a relative path inside the add-on folder")
    p = base / rel
    try:
        rp = p.resolve()
        rp.relative_to(base.resolve())
    except (ValueError, OSError):
        raise _bad(f"{what} leaves the add-on folder") from None
    if must_be == "dir" and not rp.is_dir():
        raise _bad(f"{what} is not a folder")
    if must_be == "file" and not rp.is_file():
        raise _bad(f"{what} is not a file")
    return rp


def _no_escaping_links(base: Path, folder: Path) -> None:
    """No link inside `folder` may point outside the add-on folder (the skill is copied into the project)."""
    b = base.resolve()
    for p in [folder, *folder.rglob("*")]:
        try:
            p.resolve().relative_to(b)
        except (ValueError, OSError):
            raise _bad(f"{p.name} is a link that leaves the add-on folder") from None


def _text_ok(v, limit: int) -> bool:
    return isinstance(v, str) and 0 < len(v) <= limit and "<" not in v and ">" not in v


def _remote_ref(node) -> bool:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("$ref", "$dynamicRef") and isinstance(v, str) and not v.startswith("#"):
                return True
            if _remote_ref(v):
                return True
    elif isinstance(node, list):
        return any(_remote_ref(v) for v in node)
    return False


def parse_manifest(file: Path) -> dict:
    """Validate orch-addon.toml (addon-manifest.schema.json) and the paths it names. Never runs add-on code.
    Returns the manifest plus `dir` (its folder). Refused when anything is off."""
    try:
        m = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise _bad(f"it cannot be read ({type(e).__name__})") from None
    base = file.parent
    extra = set(m) - TOP_KEYS
    if extra:
        raise _bad(f"unknown key {sorted(extra)[0]}")
    if m.get("schema") != "orch.addon/1" or m.get("orch_api") != 1 or isinstance(m.get("orch_api"), bool):
        raise _bad('it needs schema = "orch.addon/1" and orch_api = 1')
    name = m.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _bad("name is 2 to 32 lowercase letters, digits or dashes")
    if name in RESERVED:
        raise _bad(f"'{name}' is a core command and cannot be an add-on name")
    if not isinstance(m.get("version"), str) or not VERSION_RE.match(m["version"]):
        raise _bad("version is x.y.z")
    if not _text_ok(m.get("description"), 120):
        raise _bad("description is one plain sentence (at most 120 characters, no < or >)")
    if not isinstance(m.get("run"), str) or not MODULE_RE.match(m["run"]):
        raise _bad("run is a top-level module name")
    skill = _inside(base, m.get("skill"), "skill", "dir")
    if not (skill / "SKILL.md").is_file():
        raise _bad("the skill folder has no SKILL.md")
    _no_escaping_links(base, skill)
    block = m.get("agents_block", f"{m['skill']}/AGENTS-block.md")
    m["agents_block"] = block
    _inside(base, block, "agents_block", "file")
    if "ticket_ext" in m:
        f = _inside(base, m["ticket_ext"], "ticket_ext", "file")
        if f.stat().st_size > EXT_SCHEMA_MAX:
            raise _bad("ticket_ext is larger than 32 KB")
        try:
            schema = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise _bad("ticket_ext is not JSON") from None
        if not isinstance(schema, dict) or _remote_ref(schema):
            raise _bad("ticket_ext must be a JSON Schema object without remote $ref")
    bg = m.get("background", False)
    if not isinstance(bg, bool):
        raise _bad("background is true or false")
    m["background"] = bg
    d = m.get("dashboard")
    if d is not None:
        if not isinstance(d, dict) or set(d) - {"label", "icon", "order"}:
            raise _bad("[dashboard] has label, icon and order")
        if not _text_ok(d.get("label"), 16):
            raise _bad("dashboard label is at most 16 characters")
        if d.get("icon") not in ICONS:
            raise _bad("dashboard icon is not in the fixed icon set")
        order = d.get("order", 50)
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 99:
            raise _bad("dashboard order is 0 to 99")
        d["order"] = order
    tv = m.get("ticket_view", [])
    if not isinstance(tv, list) or len(tv) > 8:
        raise _bad("ticket_view has at most 8 rows")
    for row in tv:
        if (
            not isinstance(row, dict)
            or set(row) != {"field", "label", "format"}
            or not isinstance(row["field"], str)
            or not re.fullmatch(r"[a-z_][a-z0-9_]{0,31}", row["field"])
            or not _text_ok(row["label"], 24)
            or row["format"] not in FORMATS
        ):
            raise _bad("a [[ticket_view]] row needs field, label and format")
    m["ticket_view"] = tv
    m["dir"] = base
    return m


def _entry_points() -> dict[str, str]:
    """name -> module from the entry-point group orch.addons (tests replace this)."""
    from importlib.metadata import entry_points

    out = {}
    for ep in entry_points(group="orch.addons"):
        out[ep.name] = ep.value
    return out


def _manifest_file(module: str) -> Path | None:
    if not MODULE_RE.match(module):
        return None
    try:
        s = importlib.util.find_spec(module)  # top-level only: nothing is imported
    except (ImportError, ValueError):
        return None
    if not s or not s.submodule_search_locations:
        return None
    for loc in s.submodule_search_locations:
        f = Path(loc) / MANIFEST
        if f.is_file():
            return f
    return None


def discover() -> dict[str, dict]:
    """Every installed add-on with a valid manifest, by name. Invalid ones are skipped."""
    importlib.invalidate_caches()
    out = {}
    for name, module in _entry_points().items():
        f = _manifest_file(module)
        if f is None:
            continue
        try:
            m = parse_manifest(f)
        except Refused:
            continue
        if m["name"] != name or m["run"] != module:  # the entry point must say what the manifest says
            continue
        out[name] = m
    return out


def folder_manifest(folder: Path) -> dict:
    """The manifest of a source folder that is not installed yet (preview before consent)."""
    found = [p for pat in (f"src/*/{MANIFEST}", f"*/{MANIFEST}") for p in sorted(folder.glob(pat))]
    if not found:
        raise Refused(f"{folder} has no {MANIFEST} inside its Python package.")
    return parse_manifest(found[0])


# ---------------------------------------------------------------- activation (.orch/addons.json)


def activation_path(root: Path) -> Path:
    return root / ".orch" / "addons.json"


def active(root: Path) -> dict[str, dict]:
    """The one switch. Only this file says what is on here; anything else is ignored."""
    try:
        data = json.loads(activation_path(root).read_text(encoding="utf-8"))
        a = data["active"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(a, dict):
        return {}
    return {k: v for k, v in a.items() if isinstance(k, str) and NAME_RE.match(k) and isinstance(v, dict)}


def _save_active(root: Path, a: dict[str, dict]) -> None:
    p = activation_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"active": a}, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def active_manifests(root: Path) -> dict[str, dict]:
    """Active add-ons that are also installed here (a switch without a package does nothing)."""
    found = discover()
    return {n: found[n] for n in active(root) if n in found}


def not_on_message(name: str) -> str:
    return f"The {name} add-on is not turned on in this workspace. Turn it on: orch addon add {name}"


def active_ext_schema(root: Path, name: str) -> dict | None:
    """The ticket_ext schema of an ACTIVE add-on, else None."""
    m = active_manifests(root).get(name)
    if not m or "ticket_ext" not in m:
        return None
    return json.loads((m["dir"] / m["ticket_ext"]).read_text(encoding="utf-8"))


def listing(root: Path) -> list[dict]:
    """`orch addon list --json`: the one source the dashboard uses."""
    act = active(root)
    reg = {e["name"]: e for e in registry()}
    out = []
    for name, m in sorted(discover().items()):
        src = reg.get(name, {}).get("source", "built-in")
        out.append(
            {
                "name": name,
                "version": m["version"],
                "description": m["description"],
                "source": "built-in" if src == "built-in" else "local",
                "active": name in act,
                "dashboard": m.get("dashboard"),
                "ticket_view": m["ticket_view"],
                "background": m["background"],
            }
        )
    return out


# ---------------------------------------------------------------- dispatch


def orch_bin() -> str:
    me = Path(sys.argv[0])
    if me.name.startswith("orch") and me.is_file():
        return str(me.resolve())
    return shutil.which("orch") or "orch"


def dispatch(root: Path, name: str, argv: list[str]) -> int:
    """`orch <name> <args>`: refused unless active here, then `python -m <run> <args>` in a subprocess."""
    if name not in active(root):
        raise Refused(not_on_message(name))
    m = discover().get(name)
    if m is None:
        raise Refused(f"The {name} add-on is turned on here but is not installed. Run: orch addon add {name}")
    env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin()}
    # -P: the folder we run in is never put on the import path (a planted module there cannot take over)
    return subprocess.run([sys.executable, "-P", "-m", m["run"], *argv], cwd=root, env=env).returncode


def help_lines(root: Path) -> list[str]:
    return [f"  {n:<12}{m['description']}" for n, m in sorted(active_manifests(root).items())]


# ---------------------------------------------------------------- add / remove / uninstall


def _is_path(source: str) -> bool:
    return source.startswith((".", "/", "~")) or "/" in source or "\\" in source


def consent_text(m: dict, local: bool) -> str:
    lines = [f"{m['name']} {m['version']}: {m['description']}"]
    if local:
        lines.append("Source: local folder (not checked by orch). It runs code on this computer.")
    lines.append(f"Adds the command: orch {m['name']}")
    lines.append(f"Adds a skill and an entry in AGENTS.md: orch-{m['name']}")
    if "ticket_ext" in m:
        lines.append(f"Stores data on tickets under: ext.{m['name']}")
    if m.get("dashboard"):
        lines.append(f"Adds a dashboard tab: {m['dashboard']['label']}")
    if m["background"]:
        lines.append("Runs a background process.")
    return "\n".join(lines)


def _confirm(m: dict, local: bool, yes: bool) -> None:
    text = consent_text(m, local)
    if yes:
        print(text)
        return
    if not sys.stdin.isatty():
        raise Refused(f"{text}\nTo continue run it again with --yes.")
    sys.stderr.write(text + "\nTurn it on? [y/N] ")
    sys.stderr.flush()
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        raise Refused("Not confirmed. Nothing was changed.")


def reexec(args: list[str]) -> None:
    """Run the freshly installed orch for the project step (this process still runs the old code).
    Tests replace this with an in-process call."""
    r = subprocess.run([sys.executable, "-P", "-m", "orch", *args], text=True)
    if r.returncode != 0:
        raise Refused("The project step failed (see above).")


def add(root: Path, source: str, yes: bool = False, project_only: bool = False) -> None:
    """Install (if needed) and turn on in this workspace. `source` = built-in name or ./folder."""
    if project_only:
        _activate(root, source)
        return
    reg = registry()
    if _is_path(source):
        folder = Path(source).expanduser().resolve()
        if not (folder / "pyproject.toml").is_file():
            raise Refused(f"{folder} is not an add-on folder (no pyproject.toml).")
        m = folder_manifest(folder)
        _confirm(m, True, yes)
        entry = {"name": m["name"], "source": str(folder), "version": m["version"]}
    else:
        name = source
        if not NAME_RE.match(name) or name in RESERVED:
            raise Refused(f"'{name}' is not an add-on name.")
        known = next((e for e in reg if e["name"] == name), None)
        if known:
            entry = known
            m = discover().get(name)
            if m:
                _confirm(m, known["source"] != "built-in", yes)
        else:
            base = Path(repo()) / "workspace-addons" / name if _is_local(repo()) else None
            if base is not None:
                if not base.is_dir():
                    raise Refused(f"There is no built-in add-on '{name}'.")
                m = folder_manifest(base)
                _confirm(m, False, yes)
            elif not yes:
                raise Refused(f"Installing the built-in add-on {name}: run it again with --yes.")
            entry = {"name": name, "source": "built-in", "version": m["version"] if base else "0.0.0"}
    if entry not in reg:
        _install_tool([e for e in reg if e["name"] != entry["name"]] + [entry])
        _save_registry([e for e in reg if e["name"] != entry["name"]] + [entry])
    reexec(["addon", "add", entry["name"], "--project-only"])


def _activate(root: Path, name: str) -> None:
    m = discover().get(name)
    if m is None:
        raise Refused(f"The add-on '{name}' is not installed or its {MANIFEST} is not valid.")
    _apply_project(root, m)
    a = active(root)
    prev = a.get(name, {})
    a[name] = {"version": m["version"], "activated_at": prev.get("activated_at") or _now()}
    _save_active(root, a)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_project(root: Path, m: dict) -> None:
    name, base = m["name"], m["dir"]
    skill = base / m["skill"]
    skills.install_skill(root, f"orch-{name}", skill)
    body = skills.read_block(skill, f"orch-{name}", base / m["agents_block"])
    skills.set_block(root, name, body, addon=True)
    skills.link_claude_skills(root)


def _remove_skill_folders(root: Path, name: str) -> None:
    sdir = root / ".agents" / "skills"
    if not sdir.is_dir():
        return
    for p in sorted(sdir.iterdir()):
        if p.name == f"orch-{name}" or p.name.startswith(f"orch-{name}-"):
            skills.unlink_skill(root, p.name)
            skills.remove_skill(root, p.name)


def remove(root: Path, name: str, purge: bool = False) -> None:
    if not NAME_RE.match(name):
        raise Refused(f"'{name}' is not an add-on name.")
    a = active(root)
    if name not in a:
        raise Refused(f"The {name} add-on is not turned on in this workspace.")
    m = discover().get(name)
    if m is not None and m["background"]:
        env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin()}
        r = subprocess.run([sys.executable, "-P", "-m", m["run"], "stop"], cwd=root, env=env)
        if r.returncode != 0:
            print(f"Note: '{name} stop' did not finish cleanly; the process ends by itself.", file=sys.stderr)
    _remove_skill_folders(root, name)
    skills.remove_block(root, name, addon=True)
    del a[name]
    _save_active(root, a)
    if purge:
        _purge(root, name)


def _purge(root: Path, name: str) -> None:
    d = root / ".orch" / "addons" / name
    if d.is_symlink():
        d.unlink()
    elif d.is_dir():
        try:
            d.resolve().relative_to((root / ".orch" / "addons").resolve())
        except ValueError:
            raise Refused(f"{d} points outside this project; orch will not delete it.") from None
        shutil.rmtree(d)
    drop_config_table(root, name)


_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]\[]+?)\s*\]\]?\s*(#.*)?$")


def drop_config_table(root: Path, name: str) -> None:
    """Remove the [<name>] table (and [<name>.*]) from .orch/config.toml; everything else stays."""
    p = root / ".orch" / "config.toml"
    if not p.is_file():
        return
    out, skipping = [], False
    for line in p.read_text(encoding="utf-8").splitlines(keepends=True):
        h = _HEADER_RE.match(line)
        if h:
            key = h.group(1).strip()
            skipping = key == name or key.startswith(name + ".")
        if not skipping:
            out.append(line)
    p.write_text("".join(out), encoding="utf-8", newline="\n")


def uninstall(root: Path, name: str) -> None:
    """Remove the package from this machine. Refused while it is on in this workspace."""
    if name in active(root):
        raise Refused(f"The {name} add-on is turned on here. Turn it off first: orch addon remove {name}")
    reg = registry()
    if name not in [e["name"] for e in reg]:
        raise Refused(f"The add-on '{name}' is not installed.")
    rest = [e for e in reg if e["name"] != name]
    _install_tool(rest)
    _save_registry(rest)


# ---------------------------------------------------------------- update


def update(root: Path, project_only: bool = False) -> list[str]:
    """Reinstall orch + every installed add-on together, then refresh this project's skills and blocks."""
    if not project_only:
        _install_tool(registry())
        reexec(["update", "--project-only"])
        return []
    done = []
    if (root / ".agents" / "skills" / "orch").is_dir():
        from orch.init import init

        init(root)
        done.append("orch")
    found = discover()
    a = active(root)
    for n in sorted(a):
        m = found.get(n)
        if m is None:
            continue
        _apply_project(root, m)
        a[n]["version"] = m["version"]
        done.append(f"orch-{n}")
    if a:
        _save_active(root, a)
    return done
