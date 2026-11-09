"""Add-ons (contracts/addon-manifest.md): discovery, install, activation, dispatch, orch update.

The core knows no add-on by name. An add-on is a Python package with an `orch-addon.toml` and an entry point
`<name> = "<module>"` in the group `orch.addons`. Discovery reads the manifest file next to the package
(`importlib.util.find_spec`, top-level only) and never imports or runs add-on code.

Two steps: install (per machine, `~/.orch-tool/addons.json`, uv tool env) and activation (per workspace,
`.orch/addons.json`, written only by `orch addon add|remove`). Only an active add-on gets its command, skill,
AGENTS block, tab and background process. Leftover files or ext data never activate anything.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from orch import fields, skillrender, skills, term
from orch.errors import Refused

DEFAULT_REPO = "https://github.com/severinlindenmann/orch"
MANIFEST = "orch-addon.toml"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
MODULE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PATH_RE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]{1,200}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
# Names an add-on may never take: core commands (same list as contracts/addon-manifest.schema.json).
RESERVED = frozenset(
    "orch core ticket check log ask answer ref ext wait addon addons update init publish relay config help "
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
    if isinstance(d.get("archive_info"), dict) and sub == "workspace":
        m = _GITHUB_ZIP.match(url)
        return {"repo": m["repo"], "ref": m["ref"]} if m else {}
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


_REF_OK = re.compile(r"[A-Za-z0-9._/-]+")


def ref() -> str:
    """The branch, tag or commit to install. Checked like a git ref name: in a zip URL a '../' or '#' could
    point at another repository or folder (git+ took it as a revision only)."""
    r = os.environ.get("ORCH_REF") or _install_origin().get("ref") or "main"
    if not _REF_OK.fullmatch(r) or ".." in r or r.startswith(("-", "/")) or r.endswith((".lock", "/")):
        raise Refused(f"'{r}' is not a branch, tag or commit name orch can install from (check ORCH_REF).")
    return r


def _is_local(r: str) -> bool:
    """A source is a folder ONLY when ORCH_REPO is set explicitly to an absolute existing folder, or orch
    itself was installed from that folder. The default GitHub URL is never a path (a relative folder named
    like it must not count)."""
    if "ORCH_REPO" in os.environ:
        return r == os.environ["ORCH_REPO"] and Path(r).is_absolute() and Path(r).is_dir()
    o = _install_origin()
    return bool(o.get("local")) and r == o["repo"] and Path(r).is_dir()


# A GitHub source zip (what spec() installs), as uv records it: .../archive/[refs/heads/|refs/tags/]<ref>.zip
_GITHUB_ZIP = re.compile(
    r"^(?P<repo>https://github\.com/[^/]+/[^/]+)/archive/(?:refs/(?:heads|tags)/)?(?P<ref>.+)\.zip$"
)


def spec(subdir: str) -> str:
    """What uv installs. GitHub sources come as a zip download, so no git is needed: Windows PCs often have
    none, and their users may not be allowed to install it. Other hosts keep git."""
    r = repo()
    if _is_local(r):
        return str((Path(r) / subdir).resolve())
    r = r.removesuffix(".git")
    if any(c.isspace() or c in "\"'#?" for c in r):
        raise Refused(f"'{r}' is not a repository address orch can install from (check ORCH_REPO).")
    if r.startswith("https://github.com/"):
        return f"{r}/archive/{ref()}.zip#subdirectory={subdir}"
    return f"git+{r}@{ref()}#subdirectory={subdir}"


def real_home() -> Path:
    """The user's home from the account database on POSIX (not $HOME, which a project .envrc can set)."""
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


def _fold(p: Path) -> Path:
    return Path(str(p).casefold())  # macOS volumes ignore case: /Users/X and /users/x are one folder


def _is_under(h: Path, base: Path) -> bool:
    for a, b in ((h, base), (_fold(h), _fold(base))):
        try:
            a.relative_to(b)
            return True
        except ValueError:
            pass
    return False


def _same(a: Path, b: Path) -> bool:
    return a == b or _fold(a) == _fold(b)


def _untrusted_rule(h: Path, root: Path | None = None) -> str | None:
    """Why ORCH_HOME is not trusted (None = trusted): it counts only under the user's real home, outside the
    current folder and the workspace, and with no .orch, .agents or .git in any folder from it up to home (a
    repo .envrc could aim it higher)."""
    top = real_home().resolve()
    if _same(h, top):
        return "home-itself"  # the tool's files would lie loose in ~
    for name, base in (("cwd", Path.cwd().resolve()), *([("workspace", root.resolve())] if root else [])):
        if _is_under(h, base):
            return name  # inside the current folder or the workspace
    try:
        h.relative_to(top)
    except ValueError:
        return "outside-home"
    for p in (h, *h.parents):
        if p == top:
            break
        if any((p / m).exists() for m in (".orch", ".agents", ".git")):
            return "marker-folder"
    return None


def _trusted_home(h: Path, root: Path | None = None) -> bool:
    return _untrusted_rule(h, root) is None


_TRACE_MAX = 256 * 1024


def _trace_command() -> str:
    """The program name and up to two leading words that are real orch subcommands ("orch addon list"),
    checked against orch's own parser. Anything else (values, free text, another program's arguments when
    orch runs inside it) is never logged: it can hold secrets."""
    words = [os.path.basename(sys.argv[0] or "?")[:40]]
    try:
        import argparse

        from orch import cli

        p = cli.build_parser()
        for a in sys.argv[1:3]:
            sub = next((x for x in p._actions if isinstance(x, argparse._SubParsersAction)), None)
            if sub is None or a not in sub.choices:
                break
            words.append(a)
            p = sub.choices[a]
    except Exception:  # noqa: BLE001 - the program name alone is enough
        pass
    return " ".join(words)


def _trace_fallback(real: Path, reason: str) -> None:
    """One line in <real>/.fallback-trace.log each time home() falls back to the real ~/.orch-tool, to find
    who uses it. Best effort, never raises; refuses a symlinked folder or file (O_NOFOLLOW); mode 0600."""
    try:
        if real.is_symlink() or not (real / ".trace-fallbacks").is_file():
            return  # opt-in per machine (a dev Mac): a normal install never writes it
        line = json.dumps(
            {
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "cmd": _trace_command(),
                "cwd": os.getcwd(),
                "reason": reason,
            }
        )
        real.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = real / ".fallback-trace.log"
        try:
            if not log.is_symlink() and log.stat().st_size > _TRACE_MAX:
                # a unique name first, so two processes rotating at once can not drop a generation
                tmp = real / f".fallback-trace.log.tmp-{os.getpid()}-{secrets.token_hex(4)}"
                try:
                    os.replace(log, tmp)
                    os.replace(tmp, real / ".fallback-trace.log.1")
                except OSError:
                    for f in (tmp, log):  # rotation failed: never let the log grow without a bound
                        try:
                            if not f.is_symlink() and f.exists():
                                os.truncate(f, 0)
                        except OSError:
                            pass
        except OSError:
            pass
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(log, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return  # a FIFO or device there must not block or feed orch
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 - a trace must never break orch
        pass


def home_candidates() -> list[Path]:
    """Every place the user's orch folder can be, resolved, without the trust rules or any fallback trace:
    ORCH_HOME when set (as home() reads it), then ~/.orch-tool. For "is this path inside it" questions."""
    env = os.environ.get("ORCH_HOME")
    return [*([Path(env).resolve()] if env else []), (real_home() / ".orch-tool").resolve()]


def home(root: Path | None = None) -> Path:
    """The user's orch folder: ORCH_HOME when trusted (see _untrusted_rule), else ~/.orch-tool.
    ORCH_HOME_STRICT (anything but empty or 0, for tests and e2e) makes every fallback an error: ORCH_HOME
    unset or empty, untrusted, or aimed at the real folder. Every other fallback leaves one line in
    ~/.orch-tool/.fallback-trace.log."""
    real = real_home() / ".orch-tool"
    env = os.environ.get("ORCH_HOME")
    strict = os.environ.get("ORCH_HOME_STRICT", "") not in ("", "0")
    if not env:
        if strict:
            raise Refused(
                f"ORCH_HOME is not set, and ORCH_HOME_STRICT forbids using {real}. Nothing was written."
            )
        _trace_fallback(real, "unset")
        return real
    h = Path(env).resolve()
    if strict and _same(h, real.resolve()):
        raise Refused(
            f"ORCH_HOME ({env}) is the real {real}, and ORCH_HOME_STRICT forbids it. Nothing was written."
        )
    rule = _untrusted_rule(h, root)
    if rule is None:
        return h
    if strict:
        raise Refused(
            f"ORCH_HOME ({env}) is not a trusted folder (it must be under your home, outside the current "
            f"folder and any .git/.orch/.agents folder), and ORCH_HOME_STRICT forbids falling back to "
            f"{real}. Nothing was written."
        )
    print(
        f"Note: ORCH_HOME ({env}) is ignored (not a plain folder under your home); using {real}.",
        file=sys.stderr,
    )
    _trace_fallback(real, f"untrusted:{rule}")
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


def _no_longer_ships(e: dict) -> bool:
    """A built-in add-on this orch version does not ship (an older install registered it, e.g. 'scheduler').
    orch update drops it from the registry instead of failing on a folder the repository no longer has."""
    if e["source"] != "built-in":
        return False
    if _is_local(repo()):
        return not (Path(repo()) / "workspace-addons" / e["name"]).is_dir()
    return e["name"] not in SHIPPED_ADDONS


def _current_registry() -> list[dict]:
    """The registry without built-ins that no longer ship; saved back when one was dropped."""
    reg = registry()
    keep = [e for e in reg if not _no_longer_ships(e)]
    for e in reg:
        if e not in keep:
            print(f"Add-on {e['name']} removed: it no longer ships with orch.")
    if len(keep) < len(reg):
        _save_registry(keep)
    return keep


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


def _same_python() -> list[str]:
    """On Windows a reinstall keeps the Python orch runs on. On Windows on ARM the installer chose an x64
    Python (cryptography has no ARM64 Windows wheel); uv's own pick would try to compile it and fail."""
    base = getattr(sys, "_base_executable", None)
    return ["--python", base] if sys.platform == "win32" and base else []


def _tool_args(entries: list[dict]) -> list[str]:
    """uv arguments that install orch with these add-ons in one uv tool env. An entry that can not be
    installed any more is left out with a note (it stays in the registry), so one stale entry never blocks
    the rest."""
    # --refresh: a branch zip has the same URL after every push, so never take it from uv's cache
    args = ["tool", "install", "--reinstall", "--refresh", *_same_python(), spec("workspace")]
    for e in entries:
        why = _missing_source(e)
        if why:
            n = e["name"]
            print(
                f"Note: add-on {n} was left out: {why}. Remove it: orch addon uninstall {n}", file=sys.stderr
            )
            continue
        args += ["--with", _entry_spec(e)]
    return args


def _install_tool(entries: list[dict]) -> None:
    run_uv(_tool_args(entries))


def _reinstall(entries: list[dict], *, save: bool, then: list[list[str]], root: Path, done: str) -> bool:
    """Reinstall orch with these add-ons, then (if `save`) store them as the registry and run the orch
    commands in `then` with the new code. Returns False when that happens later: on Windows orch can not
    replace its own files while it runs, so a finisher does it once this command has exited (winfinish.py).
    """
    from orch import winfinish

    if not winfinish.needed():
        _install_tool(entries)
        if save:
            _save_registry(entries)
        for t in then:
            reexec(t)
        return True
    if winfinish.pending(home()):
        raise Refused(
            "An add-on install or update is still finishing in the background. "
            f"Try again in a minute. Log: {winfinish.log_path(home())}"
        )
    uv = _which_uv()
    if not uv:
        raise Refused("uv is not installed. Run the orch install script first.")
    reg = None
    if save:
        reg = (registry_path(), json.dumps(sorted(entries, key=lambda e: e["name"]), indent=2))
    try:
        log = winfinish.start(home(), [uv, *_tool_args(entries)], then, root, done, reg)
    except winfinish.Busy:
        raise Refused(
            "An add-on install or update is still finishing in the background. "
            f"Try again in a minute. Log: {winfinish.log_path(home())}"
        ) from None
    except RuntimeError as e:
        raise Refused(f"Could not finish the install: {e}. Reinstall orch with the install script.") from e
    print(
        f"Windows can not replace orch while it runs, so this finishes in the background once this command "
        f"has ended: {done}.\nWait about a minute before the next orch command (orch is being replaced "
        f"meanwhile). Then check with: orch addon list   Log: {log}"
    )
    return False


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


REF_KIND_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}(?::[a-z0-9][a-z0-9-]{0,31})?")
LINK_ICON_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
LINK_STATUS_RE = re.compile(r"[a-z0-9][a-z0-9 -]{0,23}")
LINK_MATCH_RE = re.compile(r"https?://[^\s<>\"'`]{1,300}")
FIELD_KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _ticket_links_fields_acts(base: Path, m: dict) -> None:
    """[[ticket_links]] (reference types), [ticket_fields] (ticket fields) and [acts] (what
    `orch <name> act <verb>` offers; core knows only `refresh`)."""
    tl = m.setdefault("ticket_links", [])
    if not isinstance(tl, list) or len(tl) > 16:
        raise _bad("ticket_links has at most 16 reference types")
    kinds = set()
    for k in tl:
        match = k.get("match") if isinstance(k, dict) else None
        if isinstance(match, str):
            match = [match]
        ok = (
            isinstance(k, dict)
            and not set(k) - {"kind", "label", "icon", "match", "statuses", "preview"}
            and isinstance(k.get("kind"), str)
            and REF_KIND_RE.fullmatch(k["kind"])
            and k["kind"] not in ("url", "ticket", "artifact", "file")
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
            and all(x == "refs" or x == f"ext.{m.get('name')}" for x in a["writes"])
        )
        if not ok:
            raise _bad(f"[acts.{verb}] has summary, who (anyone or people) and writes (refs, ext.<name>)")


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
        if not isinstance(d, dict) or set(d) - {"label", "icon", "order", "panel"}:
            raise _bad("[dashboard] has label, icon, order and panel")
        if not _text_ok(d.get("label"), 24):
            raise _bad("dashboard label is at most 24 characters")
        # `panel`: an extra native card the dashboard knows how to draw (a fixed set)
        if d.get("panel") not in (None, "repeats", "links", "phone"):
            raise _bad("dashboard panel is repeats, links or phone")
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


def _record_for(root: Path, name: str, wid: str, reg: list[dict] | None = None) -> dict:
    src = next((e["source"] for e in (registry() if reg is None else reg) if e["name"] == name), "built-in")
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


def record_consent(root: Path, name: str, reg: list[dict] | None = None) -> None:
    """The user turned `name` on in this workspace, on THIS machine (not from a file that arrived by git).
    reg: the add-on list as it will be once a pending install is done (default: as it is now)."""
    wid = workspace_id(root, create=True)
    rec = _record_for(root, name, wid, reg)
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
    """`orch <name> act refresh [--by X] [--json] -- <ticket>`: the add-on looks its references up and prints
    ONE JSON object `{ticket, refs: [{url, title?, status?, thumb?}], ext?: {<name>: {...}}, say?}`; core
    merges it into the ticket (tickets.merge_refresh) and says what changed.
    The add-on never writes the ticket itself."""
    from orch import refs, tickets

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
    writes = act["writes"] or ["refs", f"ext.{name}"]  # what the manifest says the refresh may change
    if isinstance(out, dict):
        out = {
            **out,
            "refs": out.get("refs") if "refs" in writes else [],
            "ext": out.get("ext") if f"ext.{name}" in writes else {},
        }
    t, changes = tickets.merge_refresh(root, tid, name, out, by, active_ext_schema(root, name))
    say = out.get("say") if isinstance(out.get("say"), str) else ""
    say = refs.one_line(say, 300)
    key = t.get("key") or t["id"]
    if "--json" in argv:
        print(json.dumps({"ticket": t["id"], "key": key, "changes": changes, "say": say}, ensure_ascii=False))
        return 0
    if not changes:
        print(f"{key}  {say or 'Nothing to update.'}")
        return 0
    for c in changes:
        old, new = (refs.one_line("-" if x in (None, "") else x, 120) for x in (c["old"], c["new"]))
        what = f"{refs.one_line(c['name'])}  {c['field']}" if c["what"] == "link" else c["field"]
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
    lines.append(f"Adds a skill and an entry in the local orch instructions: orch-{m['name']}")
    if "ticket_ext" in m or m.get("ticket_fields"):
        lines.append(f"Stores data on tickets under: ext.{m['name']}")
    if m.get("ticket_links"):
        lines.append("Knows these references: " + ", ".join(k["label"] for k in m["ticket_links"]))
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
    if not term.is_terminal(sys.stdin):
        err = Refused(f"{text}\n\nTo add it, run it again with --yes.")
        err.confirm = True
        raise err
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
            elif not term.is_terminal(sys.stdin):
                err = Refused(f"To install the built-in add-on {name}, run it again with --yes.")
                err.confirm = True
                raise err
            else:
                m = preview_builtin(name)
                _confirm(m, False, False)
            entry = {"name": name, "source": "built-in", "version": m["version"] if m else "0.0.0"}
    then = [["addon", "add", entry["name"], "--project-only"]]
    if entry not in reg or entry["name"] not in discover():  # new, changed, or its package is gone
        new = [e for e in reg if e["name"] != entry["name"]] + [entry]
        # before the install: its follow-up step (now, or in the Windows finisher) needs the consent. If the
        # install fails, the record does not match the unchanged registry, so it turns nothing on.
        record_consent(root, entry["name"], new)
        _reinstall(new, save=True, then=then, root=root, done=f"{entry['name']} installed and turned on")
        return
    record_consent(root, entry["name"])
    reexec(then[0])


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


_ORCH_STATE = {"tickets", "config.toml", "addons.json", "ticket-counter.json"}  # the team's workspace state


def _check_ignore_line(name: str, ln: str) -> None:
    """Allowlist: the first folder or file name of the line is literal (no glob characters), so a line can
    name a place but never sweep across the workspace; and nothing may hide .orch or the team's ticket files
    (compared without case, as on macOS and Windows, and without surrounding spaces)."""
    bad = Refused(
        f"The add-on '{name}' asks to hide '{ln}' from git. That is not allowed; nothing was changed."
    )
    parts = [p for p in ln.strip().strip("/").split("/") if p not in ("", ".")]
    if not parts or any(c in parts[0] for c in "*?[]\\{}") or parts[0].strip() != parts[0]:
        raise bad
    if parts[0].lower().strip() == ".orch":
        seg = parts[1].lower().strip() if len(parts) > 1 else ""
        if not seg or any(
            fnmatch.fnmatchcase(state, seg) for state in _ORCH_STATE
        ):  # a glob that can hit one
            raise bad


def _set_gitignore(root: Path, name: str, lines: list[str]) -> None:
    """The add-on's lines live in their own block of .git/info/exclude (local; the team's .gitignore stays
    untouched); no lines = block removed."""
    from orch import harness

    for ln in lines:
        _check_ignore_line(name, ln)
    lines = [ln.strip() for ln in lines]
    harness.exclude_set(root, f"addon-{name}", lines)


def _remove_skill_folders(root: Path, name: str) -> None:
    """Exactly orch-<name>: never a neighbour such as orch-<name>-x (another add-on or the user's skill)."""
    skills.remove_skill(root, f"orch-{name}")


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
    _reinstall(rest, save=True, then=[], root=root, done=f"{name} removed from this computer")


# ---------------------------------------------------------------- update


def _orch_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    from orch import __version__

    try:
        return version("orch-workspace")
    except PackageNotFoundError:
        return __version__


def _github_api() -> str | None:
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)", repo().removesuffix(".git"))
    return f"https://api.github.com/repos/{match[1]}/{match[2]}" if match else None


def _source_sha() -> str | None:
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    try:
        if _is_local(repo()):
            result = subprocess.run(
                ["git", "-C", repo(), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return _sha_or_none(result.stdout)
        api = _github_api()
        if api:
            request = Request(
                f"{api}/commits/{quote(ref(), safe='')}",
                headers={"Accept": "application/vnd.github.sha"},
            )
            with urlopen(request, timeout=5) as response:
                return _sha_or_none(response.read(200).decode("ascii", "replace"))
    except Exception:  # best effort: metadata must not prevent an update
        pass
    return None


def _release_title() -> str | None:
    from urllib.request import urlopen

    from orch.services import _printable

    try:
        api = _github_api()
        if api:
            with urlopen(f"{api}/releases/latest", timeout=5) as response:
                release = json.load(response)
            title = release.get("name") or release.get("body")
            if isinstance(title, str) and title.strip():
                return _printable(title.strip().splitlines()[0])[:100] or None
    except Exception:  # best effort, including malformed release data
        pass
    return None


SHA_RE = re.compile(r"[0-9a-f]{40}")
SNAPSHOT_MAX_AGE = 600  # seconds: an older update-before.json belongs to an update that never finished


def _sha_or_none(v: object) -> str | None:
    """Only a full lowercase hex commit id counts: anything else (a proxy page, escape codes) is no sha."""
    v = v.strip() if isinstance(v, str) else v
    return v if isinstance(v, str) and SHA_RE.fullmatch(v) else None


def _write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _stored_sha() -> str | None:
    try:
        d = json.loads((home() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _sha_or_none(d.get("sha")) if isinstance(d, dict) else None


def _save_installed(sha: str | None) -> None:
    _write_atomic(home() / "installed.json", json.dumps({"sha": _sha_or_none(sha)}))


def _load_snapshot(root: Path, nonce: str | None) -> dict | None:
    """The snapshot of THIS update (same nonce, same workspace, fresh), else None. A snapshot that is
    broken or too old is deleted; one that belongs to another update is left alone."""
    import time

    path = home() / "update-before.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # unreadable or not UTF-8: broken, delete it
        path.unlink(missing_ok=True)
        return None
    try:
        d = json.loads(raw)
        ok = (
            isinstance(d, dict)
            and isinstance(d.get("nonce"), str)
            and isinstance(d.get("root"), str)
            and isinstance(d.get("time"), (int, float))
            and math.isfinite(d["time"])
            and isinstance(d.get("orch"), str)
            and isinstance(d.get("addons"), dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in d["addons"].items())
        )
    except ValueError:
        ok = False
    if not ok or time.time() - d["time"] > SNAPSHOT_MAX_AGE or d["time"] > time.time() + 60:
        path.unlink(missing_ok=True)
        return None
    if not nonce or d["nonce"] != nonce or d["root"] != str(root.resolve()):
        return None
    path.unlink(missing_ok=True)
    d["sha"] = _sha_or_none(d.get("sha"))
    return d


def _update_lines(before: dict, found: dict, sha: str | None) -> tuple[list[str], bool]:
    """The lines to print and whether to restart. A restart needs a version change or a changed local
    source; a sha from the network only shows in the text."""
    from orch.services import _printable

    lines, restart = [], False
    old, new = _printable(before["orch"]), _printable(_orch_version())
    sha_changed = sha is not None and sha != before.get("sha")
    if old != new or sha_changed:
        line = f"Updating orch {old}" + (f" → {new}" if old != new else "")
        if sha:
            previous = f" {before['sha'][:8]}" if before.get("sha") else ""
            line += f" ({_printable(ref())}{previous} → {sha[:8]})"
        lines.append(line)
        restart = old != new or (_is_local(repo()) and sha_changed)
    for entry in registry():
        name = entry["name"]
        old = before["addons"].get(name)
        new = found.get(name, {}).get("version")
        if old is not None and isinstance(new, str) and old != new:
            lines.append(f"Updating {_printable(name)} {_printable(old)} → {_printable(new)}")
            restart = True
    if not lines:
        return ["orch is up to date."], False
    title = _release_title()
    if title:
        lines.append(title)
    return lines, restart


def _registered_workspaces(root: Path | None) -> set[Path]:
    """The workspaces the person set up on this machine: the one `orch update` runs in, and every workspace
    with a consent record (written when the person turned an add-on on there). Resolved paths."""
    out: set[Path] = set()
    if root is not None:
        out.add(root.resolve())
    for rec in _consents():
        w = rec.get("workspace")
        if isinstance(w, str):
            out.add(Path(w).resolve())
    return out


def _restart_updated(root: Path | None = None) -> list[str]:
    """Restart the services ORCH_HOME's running.json records, whoever runs the update and whatever its cwd or
    HOME: an update replaces the code of all of them. Only registered workspaces (see above): any other entry
    is listed, never touched. One lock around the whole thing."""
    from orch import services

    registered = _registered_workspaces(root)
    by_ws: dict[str, dict[str, int]] = {}
    skipped: list[str] = []
    for e in services.running():
        if not services.pid_alive(e.get("pid")):
            continue
        if Path(e["workspace"]).resolve() in registered:
            by_ws.setdefault(e["workspace"], {})[e["addon"]] = e["pid"]
        else:
            skipped.append(
                f"{e['addon']} ({Path(e['workspace']).name}) not restarted; "
                f"run orch start in {e['workspace']}"
            )
    if not by_ws:
        return skipped
    import signal
    import threading

    # The caller may be one of the services we stop (e.g. the dashboard started this update): the terminal or
    # pipe goes away with it. Survive SIGHUP in this process only for the restart (services.start resets it
    # for what it spawns) and never let a dead output abort the work between stop and start.
    old_hup = None
    if hasattr(signal, "SIGHUP") and threading.current_thread() is threading.main_thread():
        old_hup = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    _output_failure_proof()
    done, bad = [], []
    try:
        with services.locked():  # one lock around every stop + start + check
            for ws in sorted(by_ws):
                try:
                    ok, lines = _restart_locked(services, Path(ws), by_ws[ws])
                except Exception as e:  # one workspace must not stop the others
                    why = services._printable(e)
                    ok, lines = (
                        [],
                        [
                            f"Restart {n} ({Path(ws).name}) to use the new version ({why})"
                            for n in sorted(by_ws[ws])
                        ],
                    )
                done += ok
                bad += lines
    except Exception as e:  # e.g. the lock timed out
        why = services._printable(e)
        return [
            f"Restart {n} ({Path(w).name}) to use the new version ({why})"
            for w in sorted(by_ws)
            for n in sorted(by_ws[w])
        ]
    finally:
        if old_hup is not None:
            signal.signal(signal.SIGHUP, old_hup)
    return ([f"Restarted: {', '.join(done)}"] if done else []) + bad + skipped


def _output_failure_proof() -> None:
    """If stdout or stderr is already gone (broken pipe, closed terminal), point it at the null device so
    later prints cannot raise in the middle of a restart."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            try:
                with open(os.devnull, "w") as null:
                    os.dup2(null.fileno(), stream.fileno())
            except (OSError, ValueError, AttributeError):
                pass


def _say(text: str) -> None:
    try:
        print(text, flush=True)
    except (OSError, ValueError):  # the reader is gone: the update itself must not fail for it
        _output_failure_proof()


def _same_user(pid: int) -> bool:
    """The process belongs to this user (POSIX; Windows keeps the add-on's own checks)."""
    if os.name == "nt":
        return True
    try:
        r = subprocess.run(
            ["ps", "-o", "uid=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() == str(os.getuid())


def _unverified(services, root: Path, name: str, pid: int) -> str | None:
    """Why this recorded service can not be trusted, or None. The add-on's own `status` is the proof: it
    checks its record, the pid and its start time, the command line (this add-on's module for this folder) and
    the nonce challenge on its port, and names the pid. Also: same user, add-on active here."""
    if not isinstance(pid, int) or not services.pid_alive(pid) or not _same_user(pid):
        return "can't verify"
    try:
        m = services._services(root).get(name)
        if m is None:
            return "can't verify"
        res = services._call(root, name, m, "status")
    except Exception:  # noqa: BLE001 - a forged folder must not break the update
        return "can't verify"
    if res.get("running") is not True or res.get("pid") != pid:
        return "can't verify"
    return None


def _is_up(services, root: Path, name: str, old_pid: int | None) -> bool:
    """Running again under a NEW pid (the old process is gone)."""
    return any(
        e.get("addon") == name
        and e["workspace"] == str(root)
        and e.get("pid") != old_pid
        and services.pid_alive(e.get("pid"))
        for e in services.running()
    )


def _restart_locked(services, root: Path, olds: dict[str, int]) -> tuple[list[str], list[str]]:
    """Restart these add-ons of one workspace. Returns (labels restarted, lines for what went wrong)."""
    label = lambda n: f"{n} ({root.name})"  # noqa: E731
    if not (root / ".orch").is_dir():
        return [], [
            f"Restart {label(n)} to use the new version (workspace folder is gone)" for n in sorted(olds)
        ]
    # running.json is only a hint (anything under ORCH_HOME may write it): act on a service only after the
    # add-on itself verified it live, and never start a workspace whose service was not verified.
    lines, names = [], set()
    for n in sorted(olds):
        why = _unverified(services, root, n, olds[n])
        if why:
            lines.append(f"{label(n)} not restarted ({why}); run orch start in {root}")
        else:
            names.add(n)
    if not names:
        return [], lines
    try:
        stops = {r["addon"]: r for r in services.stop(root, only=names)}
    except Exception as e:
        why = services._printable(e)
        return [], [f"Restart {label(n)} to use the new version (stop failed: {why})" for n in sorted(names)]
    stopped = {n for n in names if stops.get(n, {}).get("stopped")}
    for n in sorted(names - stopped):
        why = services._printable(stops.get(n, {}).get("error") or "did not stop")
        lines.append(f"Restart {label(n)} to use the new version (stop failed: {why})")
    errors: dict[str, str] = {}
    todo = set(stopped)
    for _attempt in range(2):  # one retry for what did not come up
        if not todo:
            break
        try:
            rows = services.start(root, only=set(todo))
        except Exception as e:
            for n in todo:
                errors.setdefault(n, services._printable(e))
            continue
        by = {r["addon"]: r for r in rows}
        for n in list(todo):
            if by.get(n, {}).get("running") and _is_up(services, root, n, olds[n]):
                todo.discard(n)
                errors.pop(n, None)
            elif by.get(n, {}).get("error"):
                errors.setdefault(n, services._printable(by[n]["error"]))
    for n in sorted(todo):
        lines.append(
            f"{label(n)} stopped, start it with: orch start" + (f" ({errors[n]})" if n in errors else "")
        )
    return [label(n) for n in sorted(stopped - todo)], lines


def update(
    root: Path,
    project_only: bool = False,
    after_install: bool = False,
    *,
    json_output: bool = False,
    report: list[str] | None = None,
    nonce: str | None = None,
) -> list[str]:
    """Reinstall orch + every installed add-on together, then refresh this project's skills and blocks.
    after_install: the install script just put a bare orch in place; put the registered add-ons back."""
    if after_install:
        _save_installed(_source_sha())
        reg = _current_registry()
        if reg:
            names = ", ".join(e["name"] for e in reg)
            if _reinstall(reg, save=True, then=[], root=root, done=f"add-ons installed again: {names}"):
                print("Add-ons installed again: " + names)
        return []
    if not project_only:
        import time

        nonce = secrets.token_hex(16)
        snapshot = {
            "nonce": nonce,
            "root": str(root.resolve()),
            "time": time.time(),
            "orch": _orch_version(),
            "addons": {e["name"]: e["version"] for e in registry()},
            "sha": _stored_sha(),
        }
        before_path = home() / "update-before.json"
        _write_atomic(before_path, json.dumps(snapshot))
        try:
            _reinstall(
                _current_registry(),
                save=False,
                then=[
                    [
                        "update",
                        "--project-only",
                        "--update-nonce",
                        nonce,
                        *(["--json"] if json_output else []),
                    ]
                ],
                root=root,
                done="orch updated",
            )
        except BaseException:
            before_path.unlink(missing_ok=True)  # a failed install leaves no stale snapshot
            raise
        return []
    before = _load_snapshot(root, nonce)
    done = []
    if (root / ".orch" / "harness" / "skills" / "orch").is_dir():
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
    sha = _source_sha()
    if before is not None:
        lines, _changed = _update_lines(before, found, sha)
        if not json_output:
            _say("\n".join(lines))
        restart_lines = _restart_updated(root)  # whatever changed: what runs is the old install
        if restart_lines and not json_output:
            _say("\n".join(restart_lines))
        if report is not None:
            report.extend(lines)
        reg = registry()
        for entry in reg:
            if entry["name"] in found:
                entry["version"] = found[entry["name"]]["version"]
        _save_registry(reg)
        if sha:
            _save_installed(sha)
    return done
