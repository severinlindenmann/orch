"""Add-ons (contracts/addon-manifest.md): discovery, install, activation, dispatch, orch update.

The core knows no add-on by name. An add-on is a Python package with an `orch-addon.toml` and an entry point
`<name> = "<module>"` in the group `orch.addons`. Discovery reads the manifest file next to the package
(`importlib.util.find_spec`, top-level only) and never imports or runs add-on code.

Two steps: install (per machine, `~/.orch-tool/addons.json`, uv tool env) and activation (per workspace,
`.orch/addons.json`, written only by `orch addon add|remove`). Only an active add-on gets its command, skill,
AGENTS block, tab and background process. Leftover files or ext data never activate anything.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from orch import fields, skillrender, skills
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
    "version view start stop status run needs agents".split()
)
ICONS = frozenset(
    "clock calendar inbox list chart bell book globe link check star box chat folder user bolt".split()
)
FORMATS = frozenset({"text", "time", "cron-human", "chips", "yes-no", "open-page"})
GITIGNORE_RE = re.compile(r"(?!/)(?![A-Za-z]:)(?!.*\.\.)(?!.*\\)[A-Za-z0-9_./* -]{1,200}")
PAGE_PATH_RE = re.compile(r"/[A-Za-z0-9_./-]{0,200}")
TOP_KEYS = frozenset(
    "schema orch_api name version description run skill agents_block ticket_ext background dashboard "
    "ticket_view recommended gitignore runs_agents requires needs page "
    "ticket_links ticket_fields acts".split()
)
EXT_SCHEMA_MAX = 32 * 1024
# Built-in add-ons that ship inside the orch package (orch/builtin/<name>/orch-addon.toml): always installed,
# off until `orch addon add <name>`; their commands are parsed by the core CLI. No other add-on may take
# these names (they stay in RESERVED).
CORE_ADDONS = ("publish", "relay")
# Separate packages that ship in this repo's workspace-addons/ and are installed on `orch addon add <name>`.
SHIPPED_ADDONS = ("automation", "dashboard", "focus")


# ---------------------------------------------------------------- sources


def _install_origin() -> dict:
    """Where this orch was installed from (PEP 610 direct_url.json written by uv): a git URL and ref, or a
    folder. Add-ons and `orch update` install from the SAME place, so an install from a branch stays on it.
    Editable dev installs and anything unreadable give {} (the defaults). Tests replace this."""
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        d = json.loads(distribution("orch-workspace").read_text("direct_url.json") or "{}")
    except (PackageNotFoundError, OSError, ValueError):
        return {}
    url, sub = d.get("url"), d.get("subdirectory") or ""
    if not isinstance(url, str):
        return {}
    vcs = d.get("vcs_info")
    if isinstance(vcs, dict) and vcs.get("vcs") == "git" and sub == "workspace":
        out = {"repo": url}
        if isinstance(vcs.get("requested_revision"), str):
            out["ref"] = vcs["requested_revision"]
        return out
    di = d.get("dir_info")
    if isinstance(di, dict) and not di.get("editable") and url.startswith("file://"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        folder = Path(url2pathname(urlparse(url).path))
        if folder.name == "workspace" and folder.is_absolute() and folder.parent.is_dir():
            return {"repo": str(folder.parent), "local": True}
    return {}


def repo() -> str:
    return os.environ.get("ORCH_REPO") or _install_origin().get("repo") or DEFAULT_REPO


def ref() -> str:
    return os.environ.get("ORCH_REF") or _install_origin().get("ref") or "main"


def _is_local(r: str) -> bool:
    """A source is a folder ONLY when ORCH_REPO is set explicitly to an absolute existing folder, or orch
    itself was installed from that folder. The default GitHub URL is never a path (a relative folder named
    like it must not count)."""
    if "ORCH_REPO" in os.environ:
        return r == os.environ["ORCH_REPO"] and Path(r).is_absolute() and Path(r).is_dir()
    o = _install_origin()
    return bool(o.get("local")) and r == o["repo"] and Path(r).is_dir()


def spec(subdir: str) -> str:
    r = repo()
    if _is_local(r):
        return str((Path(r) / subdir).resolve())
    r = r.removesuffix(".git")
    return f"git+{r}@{ref()}#subdirectory={subdir}"


def real_home() -> Path:
    """The user's home from the account database on POSIX (not $HOME, which a project .envrc can set)."""
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


def _trusted_home(h: Path, root: Path | None = None) -> bool:
    """ORCH_HOME counts only under the user's real home, outside the current folder and the workspace, and
    with no .orch, .agents or .git in any folder from it up to home (a repo .envrc could aim it higher)."""
    top = real_home().resolve()
    for base in (Path.cwd().resolve(), *([root.resolve()] if root else [])):
        try:
            h.relative_to(base)
        except ValueError:
            continue
        return False  # inside the current folder or the workspace
    try:
        h.relative_to(top)
    except ValueError:
        return False
    for p in (h, *h.parents):
        if p == top:
            break
        if any((p / m).exists() for m in (".orch", ".agents", ".git")):
            return False
    return True


def home(root: Path | None = None) -> Path:
    """The user's orch folder: ORCH_HOME when trusted (see _trusted_home), else ~/.orch-tool."""
    real = real_home() / ".orch-tool"
    env = os.environ.get("ORCH_HOME")
    if not env:
        return real
    h = Path(env).resolve()
    if _trusted_home(h, root):
        return h
    print(
        f"Note: ORCH_HOME ({env}) is ignored (not a plain folder under your home); using {real}.",
        file=sys.stderr,
    )
    return real


def registry_path() -> Path:
    return home() / "addons.json"


def registry() -> list[dict]:
    """Installed add-ons on this machine: [{name, source, version}]. source = "built-in" or a folder path."""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        e
        for e in data
        if isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("source"), str)
    ]


def _missing_source(e: dict) -> str | None:
    """Why this entry can not be installed any more (None = it can)."""
    if e["source"] == "built-in":
        local = _is_local(repo()) and not (Path(repo()) / "workspace-addons" / e["name"]).is_dir()
        return "it no longer ships with orch" if local else None
    return None if Path(e["source"]).is_dir() else f"its folder {e['source']} is gone"


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
    """Install orch with these add-ons in one uv tool env. An entry that can not be installed any more is
    left out with a note (it stays in the registry), so one stale entry never blocks the rest."""
    args = ["tool", "install", "--reinstall", spec("workspace")]
    for e in entries:
        why = _missing_source(e)
        if why:
            n = e["name"]
            print(
                f"Note: add-on {n} was left out: {why}. Remove it: orch addon uninstall {n}", file=sys.stderr
            )
            continue
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


def _ext_schema(base: Path, rel, key: str) -> dict:
    f = _inside(base, rel, key, "file")
    if f.stat().st_size > EXT_SCHEMA_MAX:
        raise _bad(f"{key} is larger than 32 KB")
    try:
        schema = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _bad(f"{key} is not JSON") from None
    if not isinstance(schema, dict) or _remote_ref(schema):
        raise _bad(f"{key} must be a JSON Schema object without remote $ref")
    return schema


LINK_KIND_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
LINK_ICON_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
LINK_STATUS_RE = re.compile(r"[a-z0-9][a-z0-9 -]{0,23}")
LINK_MATCH_RE = re.compile(r"https?://[^\s<>\"'`]{1,300}")
FIELD_KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _ticket_links_fields_acts(base: Path, m: dict) -> None:
    """[[ticket_links]] (link types), [ticket_fields] (fields under the ticket's Details) and [acts] (what
    `orch <name> act <verb>` offers; core knows only `refresh`)."""
    tl = m.setdefault("ticket_links", [])
    if not isinstance(tl, list) or len(tl) > 16:
        raise _bad("ticket_links has at most 16 link types")
    kinds = set()
    for k in tl:
        match = k.get("match") if isinstance(k, dict) else None
        if isinstance(match, str):
            match = [match]
        ok = (
            isinstance(k, dict)
            and not set(k) - {"kind", "label", "icon", "match", "statuses", "preview"}
            and isinstance(k.get("kind"), str)
            and LINK_KIND_RE.fullmatch(k["kind"])
            and k["kind"] != "link"
            and k["kind"] not in kinds
            and _text_ok(k.get("label"), 24)
            and isinstance(k.get("icon"), str)
            and LINK_ICON_RE.fullmatch(k["icon"])
            and isinstance(match, list)
            and 0 < len(match) <= 8
            and all(isinstance(x, str) and LINK_MATCH_RE.fullmatch(x) for x in match)
            and isinstance(k.setdefault("statuses", []), list)
            and len(k["statuses"]) <= 12
            and all(isinstance(x, str) and LINK_STATUS_RE.fullmatch(x) for x in k["statuses"])
            and k.get("preview") in (None, "thumb")
        )
        if not ok:
            raise _bad("a [[ticket_links]] entry needs kind, label, icon and match (https:// pattern)")
        kinds.add(k["kind"])
        k["match"] = match
    tf = m.get("ticket_fields")
    if tf is not None:
        ok = (
            isinstance(tf, dict)
            and not set(tf) - {"section", "schema", "show_on_card"}
            and _text_ok(tf.get("section"), 24)
            and isinstance(tf.setdefault("show_on_card", []), list)
            and len(tf["show_on_card"]) <= 3
            and all(isinstance(x, str) and FIELD_KEY_RE.fullmatch(x) for x in tf["show_on_card"])
        )
        if not ok:
            raise _bad("[ticket_fields] has section, schema and show_on_card (at most 3 fields)")
        tf.setdefault("schema", m.get("ticket_ext"))
        if not isinstance(tf["schema"], str):
            raise _bad("[ticket_fields] needs a schema (or ticket_ext)")
        if "ticket_ext" in m and tf["schema"] != m["ticket_ext"]:
            raise _bad("[ticket_fields] schema and ticket_ext must be the same file")
        _ext_schema(base, tf["schema"], "ticket_fields schema")
    acts = m.setdefault("acts", {})
    if not isinstance(acts, dict) or len(acts) > 16:
        raise _bad("[acts] has at most 16 entries")
    for verb, a in acts.items():
        ok = (
            re.fullmatch(r"[a-z][a-z-]{0,20}", verb)
            and isinstance(a, dict)
            and not set(a) - {"summary", "who", "writes"}
            and _text_ok(a.get("summary"), 80)
            and a.setdefault("who", "anyone") in ("anyone", "people")
            and isinstance(a.setdefault("writes", []), list)
            and all(x == "links" or x == f"ext.{m.get('name')}" for x in a["writes"])
        )
        if not ok:
            raise _bad(f"[acts.{verb}] has summary, who (anyone or people) and writes (links, ext.<name>)")


def parse_manifest(file: Path, core: bool = False) -> dict:
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
    if name in RESERVED and not (core and name in CORE_ADDONS):
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
        _ext_schema(base, m["ticket_ext"], "ticket_ext")
    _ticket_links_fields_acts(base, m)
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
    for key in ("recommended", "runs_agents", "needs"):
        if not isinstance(m.setdefault(key, False), bool):
            raise _bad(f"{key} is true or false")
    gi = m.setdefault("gitignore", [])
    ok_gi = (
        isinstance(gi, list)
        and len(gi) <= 16
        and all(isinstance(x, str) and GITIGNORE_RE.fullmatch(x) for x in gi)
    )
    if not ok_gi:
        raise _bad("gitignore lines are relative paths inside the workspace (at most 16)")
    rq = m.setdefault("requires", [])
    if (
        not isinstance(rq, list)
        or len(rq) > 8
        or len(set(map(str, rq))) != len(rq)
        or not all(isinstance(x, str) and NAME_RE.match(x) for x in rq)
    ):
        raise _bad("requires is a list of add-on names")
    pg = m.get("page")
    if pg is not None:
        if (
            not isinstance(pg, dict)
            or set(pg) - {"path", "label"}
            or not isinstance(pg.get("path"), str)
            or not PAGE_PATH_RE.fullmatch(pg["path"])
            or ".." in pg["path"]
            or pg["path"].startswith("//")
            or ("label" in pg and not _text_ok(pg["label"], 24))
        ):
            raise _bad("[page] has a path that starts with / (and an optional label)")
        if not bg:
            raise _bad("[page] needs background = true")
    if any(r["format"] == "open-page" for r in tv) and pg is None:
        raise _bad("an open-page row needs a [page]")
    m["dir"] = base
    return m


def _entry_points() -> list[tuple[str, str]] | dict[str, str]:
    """name -> module from the entry-point group orch.addons (tests replace this)."""
    from importlib.metadata import entry_points

    return [(ep.name, ep.value) for ep in entry_points(group="orch.addons")]


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


def core_manifests() -> dict[str, dict]:
    base = Path(__file__).resolve().parent / "builtin"
    return {n: parse_manifest(base / n / MANIFEST, core=True) for n in CORE_ADDONS}


def shipped_recommended(fetch: bool = True) -> dict[str, dict]:
    """Manifests of the shipped add-ons that are not installed yet and say recommended = true.
    From the local source folder when there is one; else (fetch=True) the manifest is previewed from the
    repo (one small download each), and with fetch=False the answer is empty."""
    have = set(discover())
    local = _is_local(repo())
    out = {}
    for name in SHIPPED_ADDONS:
        if name in have:
            continue
        try:
            if local:
                m = folder_manifest(Path(repo()) / "workspace-addons" / name)
            elif fetch:
                m = preview_builtin(name)
            else:
                continue
        except Refused:
            continue
        if m.get("recommended"):
            out[name] = m
    return out


def discover() -> dict[str, dict]:
    """Every installed add-on with a valid manifest, by name (the built-in core ones included)."""
    importlib.invalidate_caches()
    eps = _entry_points()
    eps = list(eps.items()) if isinstance(eps, dict) else list(eps)
    names = [n for n, _ in eps]
    installed = set(installed_names())
    out = {}
    for name, module in eps:
        # one name, one package: a second entry point with the same name disables both;
        # and only add-ons the user installed through orch (registry) count
        if names.count(name) > 1 or name not in installed:
            continue
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
    return {**out, **core_manifests()}


def folder_manifest(folder: Path) -> dict:
    """The manifest of a source folder that is not installed yet (preview before consent)."""
    found = [p for pat in (f"src/*/{MANIFEST}", f"*/{MANIFEST}") for p in sorted(folder.glob(pat))]
    if not found:
        raise Refused(f"{folder} has no {MANIFEST} inside its Python package.")
    return parse_manifest(found[0])


# ---------------------------------------------------------------- activation (.orch/addons.json)


def activation_path(root: Path) -> Path:
    return root / ".orch" / "addons.json"


def consent_path() -> Path:
    return home() / "consent.json"


def _consents() -> list[dict]:
    try:
        data = json.loads(consent_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _write_consents(items: list[dict]) -> None:
    consent_path().parent.mkdir(parents=True, exist_ok=True)
    consent_path().write_text(json.dumps(items, indent=2), encoding="utf-8")


ID_RE = re.compile(r"^[0-9a-f]{32}$")


def workspace_id(root: Path, create: bool = False) -> str | None:
    """Random id in gitignored .orch/.local-id. Consent is bound to it: a clone or copy has none."""
    f = root / ".orch" / ".local-id"
    try:
        v = f.read_text(encoding="utf-8").strip()
        if ID_RE.match(v):
            return v
    except OSError:
        pass
    if not create:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    v = secrets.token_hex(16)
    f.write_text(v + "\n", encoding="utf-8")
    return v


def folder_hash(folder: Path) -> str:
    """Content hash of a local add-on folder (paths + bytes; no .git, caches, virtual envs, build output)."""
    h = hashlib.sha256()
    skip = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "build", "dist"}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        top = rel.parts[0]  # build/cache names are skipped only at the top level, never nested
        if top in skip or top.endswith(".egg-info") or "__pycache__" in rel.parts or not p.is_file():
            continue
        h.update(rel.as_posix().encode() + b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"?")
    return h.hexdigest()


def _record_for(root: Path, name: str, wid: str) -> dict:
    src = next((e["source"] for e in registry() if e["name"] == name), "built-in")
    rec = {
        "workspace_id": wid,
        "workspace": str(root.resolve()),
        "name": name,
        "source": "built-in" if src == "built-in" else "local",
    }
    if src != "built-in":
        rec["path"] = str(Path(src).resolve())
        rec["hash"] = folder_hash(Path(src))
    return rec


def record_consent(root: Path, name: str) -> None:
    """The user turned `name` on in this workspace, on THIS machine (not from a file that arrived by git)."""
    wid = workspace_id(root, create=True)
    rec = _record_for(root, name, wid)
    # replace this workspace's record; prune records of workspaces that no longer exist
    keep = [
        e
        for e in _consents()
        if isinstance(e.get("workspace"), str)
        and Path(e["workspace"]).is_dir()
        and not (e.get("workspace_id") == wid and e.get("name") == name)
    ]
    _write_consents([*keep, rec])


def drop_consent(root: Path, name: str) -> None:
    wid = workspace_id(root)
    _write_consents([e for e in _consents() if not (e.get("workspace_id") == wid and e.get("name") == name)])


def _stale_consent(root: Path, name: str) -> bool:
    """A consent record exists for this workspace and add-on but no longer matches (local folder changed)."""
    wid = workspace_id(root)
    return wid is not None and any(
        e.get("workspace_id") == wid and e.get("name") == name for e in _consents()
    )


def consented(root: Path, name: str) -> bool:
    wid = workspace_id(root)
    if wid is None:
        return False
    for rec in _consents():
        if rec.get("workspace_id") != wid or rec.get("name") != name:
            continue
        try:
            if rec == _record_for(root, rec["name"], wid):
                return True
        except OSError:
            return False
    return False


def listed(root: Path) -> dict[str, dict]:
    """What .orch/addons.json says (it may have come with a git clone: a wish, not a switch)."""
    try:
        data = json.loads(activation_path(root).read_text(encoding="utf-8"))
        a = data["active"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(a, dict):
        return {}
    return {k: v for k, v in a.items() if isinstance(k, str) and NAME_RE.match(k) and isinstance(v, dict)}


def active(root: Path) -> dict[str, dict]:
    """The switch: listed in .orch/addons.json AND turned on by the user on this machine (consent record)."""
    return {k: v for k, v in listed(root).items() if consented(root, k)}


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


def not_on_message(root: Path, name: str) -> str:
    if name in listed(root):
        return (
            f"Add-on {name} is listed for this workspace but not turned on here. "
            f"Turn it on: orch addon add {name}"
        )
    return f"The {name} add-on is not turned on in this workspace. Turn it on: orch addon add {name}"


def active_ext_schema(root: Path, name: str) -> dict | None:
    """The ticket_ext schema of an ACTIVE add-on, else None."""
    m = active_manifests(root).get(name)
    rel = m and (m.get("ticket_ext") or (m.get("ticket_fields") or {}).get("schema"))
    if not rel:
        return None
    return json.loads((m["dir"] / rel).read_text(encoding="utf-8"))


def _running_here(root: Path) -> set[str]:
    from orch import services  # services imports addons

    here = root.resolve()
    out = set()
    for e in services.running():
        try:
            if Path(e["workspace"]).resolve() == here:
                out.add(e["addon"])
        except (OSError, KeyError, TypeError):
            continue
    return out


def listing(root: Path) -> list[dict]:
    """`orch addon list --json`: the one source the dashboard uses."""
    act = active(root)
    reg = {e["name"]: e for e in registry()}
    up = _running_here(root)
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
                "recommended": m["recommended"],
                "page": m.get("page"),
                "running": name in up,
                "ticket_links": [dict(x) for x in m["ticket_links"]],
                "ticket_fields": fields.section(m),
                "acts": sorted(m["acts"]),
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
        raise Refused(not_on_message(root, name))
    m = discover().get(name)
    if m is None:
        raise Refused(f"The {name} add-on is turned on here but is not installed. Run: orch addon add {name}")
    env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin()}
    # -P: the folder we run in is never put on the import path (a planted module there cannot take over)
    cmd = [sys.executable, "-P", "-m", m["run"], *argv]
    if argv[:2] == ["act", "refresh"] and "refresh" in m.get("acts", {}):
        return _refresh(root, name, cmd, env, argv)
    return subprocess.run(cmd, cwd=root, env=env).returncode


def _refresh(root: Path, name: str, cmd: list[str], env: dict, argv: list[str]) -> int:
    """`orch <name> act refresh [--by X] [--json] -- <ticket>`: the add-on looks its links up and prints
    ONE JSON object `{ticket, links: [{url, title?, status?, thumb?}], ext?: {<name>: {...}}, say?}`; core
    merges it into the ticket (tickets.merge_refresh) and says what changed.
    The add-on never writes the ticket itself."""
    from orch import links, tickets

    rest = argv[argv.index("--") + 1 :] if "--" in argv else []
    if len(rest) != 1:
        raise Refused(f"Say which ticket: orch {name} act refresh -- <ticket>")
    tid = tickets.resolve(root, rest[0])
    by = tickets.current_actor(argv[argv.index("--by") + 1] if "--by" in argv[:-1] else None)
    act = discover()[name]["acts"]["refresh"]
    # like cli_config._actor: an agent tool in the environment counts as an agent whatever --by says
    if act["who"] == "people" and (tickets.agent_tool() or not by.startswith("human:")):
        raise Refused(
            f"Only a person runs the {name} refresh. Ask the user to click Refresh on the ticket page."
        )
    # stderr stays out of the answer (a chatty add-on must not break --json)
    r = subprocess.run(
        cmd, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8"
    )
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        return r.returncode
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise Refused(f"The {name} add-on answered something orch cannot read.") from None
    if isinstance(out, dict) and out.get("ticket") and tickets.resolve(root, str(out["ticket"])) != tid:
        raise Refused(f"The {name} add-on answered for another ticket.")
    writes = act["writes"] or ["links", f"ext.{name}"]  # what the manifest says the refresh may change
    if isinstance(out, dict):
        out = {
            **out,
            "links": out.get("links") if "links" in writes else [],
            "ext": out.get("ext") if f"ext.{name}" in writes else {},
        }
    t, changes = tickets.merge_refresh(root, tid, name, out, by, active_ext_schema(root, name))
    say = out.get("say") if isinstance(out.get("say"), str) else ""
    say = links.one_line(say, 300)
    key = t.get("key") or t["id"]
    if "--json" in argv:
        print(json.dumps({"ticket": t["id"], "key": key, "changes": changes, "say": say}, ensure_ascii=False))
        return 0
    if not changes:
        print(f"{key}  {say or 'Nothing to update.'}")
        return 0
    for c in changes:
        old, new = (links.one_line("-" if x in (None, "") else x, 120) for x in (c["old"], c["new"]))
        what = f"{links.one_line(c['name'])}  {c['field']}" if c["what"] == "link" else c["field"]
        print(f"{key}  {what}: {old} → {new}")
    if say:
        print(say)
    return 0


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
    if "ticket_ext" in m or m.get("ticket_fields"):
        lines.append(f"Stores data on tickets under: ext.{m['name']}")
    if m.get("ticket_links"):
        lines.append("Knows these links: " + ", ".join(k["label"] for k in m["ticket_links"]))
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
    sys.stderr.write(text + "\nAdd it? [y/N] ")
    sys.stderr.flush()
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        raise Refused("Not confirmed. Nothing was changed.")


def preview_builtin(name: str) -> dict:
    """The manifest of a built-in add-on that is not installed yet, so the user sees what it adds before
    saying yes: its package alone (no dependencies) is fetched into a temp folder; nothing is installed."""
    uv = _which_uv()
    if not uv:
        raise Refused("uv is not installed. Run the orch install script first.")
    with tempfile.TemporaryDirectory(prefix="orch-preview-") as tmp:
        r = subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--quiet",
                "--no-deps",
                "--python",
                sys.executable,
                "--target",
                tmp,
                spec(f"workspace-addons/{name}"),
            ],
            text=True,
            capture_output=True,
        )
        if r.returncode != 0:
            raise Refused(f"There is no built-in add-on '{name}' (or it could not be fetched).")
        return folder_manifest(Path(tmp))


def reexec(args: list[str]) -> None:
    """Run the freshly installed orch for the project step (this process still runs the old code).
    Tests replace this with an in-process call."""
    r = subprocess.run([sys.executable, "-P", "-m", "orch", *args], text=True, stdout=subprocess.PIPE)
    sys.stdout.write(r.stdout)  # through our stdout, so a caller that redirects it (init --json) stays clean
    if r.returncode != 0:
        raise Refused("The project step failed (see above).")


def add(root: Path, source: str, yes: bool = False, project_only: bool = False) -> None:
    """Install (if needed) and turn on in this workspace. `source` = built-in name or ./folder."""
    if project_only:
        if not consented(root, source):
            raise Refused(not_on_message(root, source))
        _activate(root, source)
        return
    if source in CORE_ADDONS:  # part of orch: nothing to install
        _check_requires(root, core_manifests()[source])
        _confirm(core_manifests()[source], False, yes)
        record_consent(root, source)
        _activate(root, source)
        print(f"{source} is turned on in this workspace.")
        return
    reg = registry()
    if _is_path(source):
        folder = Path(source).expanduser().resolve()
        if not (folder / "pyproject.toml").is_file():
            raise Refused(f"{folder} is not an add-on folder (no pyproject.toml).")
        m = folder_manifest(folder)
        _check_requires(root, m)
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
                _check_requires(root, m)
                _confirm(m, known["source"] != "built-in", yes)
        else:
            base = Path(repo()) / "workspace-addons" / name if _is_local(repo()) else None
            if base is not None:
                if not base.is_dir():
                    raise Refused(f"There is no built-in add-on '{name}'.")
                m = folder_manifest(base)
                _check_requires(root, m)
                _confirm(m, False, yes)
            elif yes:
                m = None
            elif not sys.stdin.isatty():
                raise Refused(f"Installing the built-in add-on {name}: run it again with --yes.")
            else:
                m = preview_builtin(name)
                _confirm(m, False, False)
            entry = {"name": name, "source": "built-in", "version": m["version"] if m else "0.0.0"}
    if entry not in reg or entry["name"] not in discover():  # new, changed, or its package is gone
        _install_tool([e for e in reg if e["name"] != entry["name"]] + [entry])
        _save_registry([e for e in reg if e["name"] != entry["name"]] + [entry])
    record_consent(root, entry["name"])
    reexec(["addon", "add", entry["name"], "--project-only"])


def _check_requires(root: Path, m: dict) -> None:
    missing = [r for r in m.get("requires", []) if r not in active(root)]
    if missing:
        raise Refused(
            f"{m['name']} needs {', '.join(missing)} to be on first. Turn it on: orch addon add {missing[0]}"
        )


def _activate(root: Path, name: str) -> None:
    m = discover().get(name)
    if m is None:
        raise Refused(f"The add-on '{name}' is not installed or its {MANIFEST} is not valid.")
    _check_requires(root, m)
    _apply_project(root, m)
    _set_gitignore(root, name, m["gitignore"])
    a = listed(root)
    prev = a.get(name, {})
    a[name] = {"version": m["version"], "activated_at": prev.get("activated_at") or _now()}
    _save_active(root, a)
    skillrender.refresh_skills(root)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_project(root: Path, m: dict) -> None:
    name, base = m["name"], m["dir"]
    skill = base / m["skill"]
    skills.install_skill(root, f"orch-{name}", skill)
    body = skills.read_block(skill, f"orch-{name}", base / m["agents_block"])
    skills.set_block(root, name, body, addon=True)
    skillrender.render_installed(root, name, skill)
    skills.apply_agent_files(root)


def _gi_markers(name: str) -> tuple[str, str]:
    return f"# orch:addon:{name}", f"# /orch:addon:{name}"


def _set_gitignore(root: Path, name: str, lines: list[str]) -> None:
    """The add-on's lines live in their own block of the workspace .gitignore; no lines = block removed."""
    path = root / ".gitignore"
    f = skills._project_file(root, path)
    text = f.read_bytes().decode("utf-8") if f.exists() else ""
    eol = "\r\n" if "\r\n" in text else "\n"
    start, end = _gi_markers(name)
    rows = text.splitlines()
    if start in rows and end in rows[rows.index(start) :]:
        i = rows.index(start)
        j = rows.index(end, i)
        rows = rows[:i] + rows[j + 1 :]
    if lines:
        rows += [start, *lines, end]
    new = eol.join(rows) + eol if rows else ""
    if new != text:
        skills._write_project_file(root, path, new)


def _remove_skill_folders(root: Path, name: str) -> None:
    """Exactly orch-<name>: never a neighbour such as orch-<name>-x (another add-on or the user's skill)."""
    d = root / ".agents" / "skills" / f"orch-{name}"
    if d.exists() or d.is_symlink():
        skills.unlink_skill(root, d.name)
        skills.remove_skill(root, d.name)


def remove(root: Path, name: str, purge: bool = False) -> None:
    if not NAME_RE.match(name):
        raise Refused(f"'{name}' is not an add-on name.")
    a = listed(root)
    if name not in a:
        raise Refused(f"The {name} add-on is not turned on in this workspace.")
    if purge:
        _purge_check(root, name)  # refuse before anything is changed
    m = discover().get(name) if consented(root, name) else None  # never run a package nobody turned on here
    if m is not None and m["background"]:
        env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin()}
        r = subprocess.run([sys.executable, "-P", "-m", m["run"], "stop"], cwd=root, env=env)
        if r.returncode != 0:
            print(f"Note: '{name} stop' did not finish cleanly; the process ends by itself.", file=sys.stderr)
    _remove_skill_folders(root, name)
    _set_gitignore(root, name, [])
    skills.remove_block(root, name, addon=True)
    del a[name]
    _save_active(root, a)
    drop_consent(root, name)
    if purge:
        _purge(root, name)
    skillrender.refresh_skills(root)


def _safe_addons_dir(root: Path) -> Path:
    """.orch and .orch/addons must be real folders inside the workspace (never links out)."""
    base = root.resolve()
    orch, ad = root / ".orch", root / ".orch" / "addons"
    for p in (orch, ad):
        if p.is_symlink() or skills._is_link(p):
            raise Refused(f"{p} is a link; orch will not delete anything through it.")
        if p.exists():
            try:
                p.resolve().relative_to(base)
            except ValueError:
                raise Refused(f"{p} points outside this workspace; orch will not delete there.") from None
    return ad


def _purge_check(root: Path, name: str) -> Path:
    """Everything that could make a purge unsafe, checked before anything is changed. Returns the folder."""
    ad = _safe_addons_dir(root)
    d = ad / name
    if d.is_symlink() or skills._is_link(d):
        raise Refused(f"{d} is a link; orch will not delete it or what it points to.")
    if d.is_dir():
        try:
            d.resolve().relative_to(ad.resolve())
        except ValueError:
            raise Refused(f"{d} points outside .orch/addons; orch will not delete it.") from None
        for p in d.rglob("*"):
            if p.is_symlink() or skills._is_link(p):
                try:
                    p.resolve().relative_to(d.resolve())
                except (ValueError, OSError):
                    raise Refused(f"{p} is a link that leaves the folder; orch will not delete it.") from None
    return d


def _purge(root: Path, name: str) -> None:
    d = _purge_check(root, name)
    if d.is_dir():
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
    if name in CORE_ADDONS:
        raise Refused(f"{name} is part of orch. Turn it off here with: orch addon remove {name}")
    if name in active(root):
        raise Refused(f"The {name} add-on is turned on here. Turn it off first: orch addon remove {name}")
    reg = registry()
    if name not in [e["name"] for e in reg]:
        raise Refused(f"The add-on '{name}' is not installed.")
    rest = [e for e in reg if e["name"] != name]
    _install_tool(rest)
    _save_registry(rest)


# ---------------------------------------------------------------- update


def update(root: Path, project_only: bool = False, after_install: bool = False) -> list[str]:
    """Reinstall orch + every installed add-on together, then refresh this project's skills and blocks.
    after_install: the install script just put a bare orch in place; put the registered add-ons back."""
    if after_install:
        reg = registry()
        if reg:
            _install_tool(reg)
            _save_registry(reg)
            print("Add-ons installed again: " + ", ".join(e["name"] for e in reg))
        return []
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
    a = listed(root)
    on = sorted(active(root))
    for n in sorted(set(a) - set(on)):
        if _stale_consent(root, n):
            print(
                f"Add-on {n} changed on disk since you turned it on, so it was not refreshed. "
                f"Check it, then turn it on again: orch addon add <folder> --yes",
                file=sys.stderr,
            )
    for n in on:
        m = found.get(n)
        if m is None:
            continue
        _apply_project(root, m)
        a[n]["version"] = m["version"]
        done.append(f"orch-{n}")
    if a:
        _save_active(root, a)
    return done
