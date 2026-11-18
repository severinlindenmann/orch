"""Updates for the tools a workspace uses (ORCH-589): the helper tools (Claude Code, Codex) and any tool
the workspace's checks name (Databricks CLI, GitHub CLI, a Google Ads CLI ...). For each one: the installed
version, the newest one, the update notes in between and, when orch can tell how the tool was installed,
an update the person starts (`orch tools update <name>`, or Update in Settings).

Generic by design: a tool is known by its command name. The built-in library (known_tools.json) covers common
tools; a workspace adds its own with an `update` block in one of its check files (.orch/checks/<name>.json),
which therefore runs only after the person approved that file (checkfiles.py):

    "update": {"label": "Google Ads CLI", "latest": {"pypi": "google-ads-cli"},
               "notes": {"github": "owner/repo", "tag_prefix": "v"},
               "installs": [{"via": "brew", "formula": "..."}, {"via": "npm", "package": "..."}]}

Safety (plan challenged on the ticket):
  - Versions and notes come only from typed sources on fixed HTTPS hosts (npm, PyPI, GitHub, Homebrew), with a
    time and size limit and no redirect to another host; never a free URL.
  - Update is offered only for an install orch recognises from the real path of the command (a Homebrew cellar
    or cask folder of the named formula, node_modules/<the named package>, or a recipe path such as Claude
    Code's own versions folder). The update is a fixed argument list built here, never a shell; it runs from
    the home folder, never from the project (no project .npmrc). Otherwise the person updates it themselves.
  - Only a person starts an update (refused inside a helper run). One update at a time; it is never killed.
  - Release notes are text from outside: shown to the person as plain lines, never given to a helper.
Best effort: a network problem keeps the last good answer with its time and says why the check failed.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from orch.errors import Refused

CACHE_SECONDS = 6 * 3600
HTTP_TIMEOUT = 8
HTTP_LIMIT = 2 * 1024 * 1024
VERSION_TIMEOUT = 10
MAX_NOTE_LINES = 15
PER_VERSION = 5  # lines shown per version; the rest is counted
MAX_RELEASES = 5  # release notes read per tool and check
LINE_MAX = 200
LOG_KEEP = 64 * 1024
ALLOWED_HOSTS = frozenset(
    {"registry.npmjs.org", "pypi.org", "api.github.com", "raw.githubusercontent.com", "formulae.brew.sh"}
)
CACHE_FILE = "tool-updates.json"
JOB_FILE = "tool-update-job.json"
LOG_FILE = "tool-update.log"
LOCK_FILE = "tool-update.lock"

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_NPM = re.compile(r"(@[a-z0-9][a-z0-9._-]{0,63}/)?[a-z0-9][a-z0-9._-]{0,113}")
_PYPI = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_FILE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._/-]{1,200}"
)
_BREW = re.compile(r"[a-z0-9][a-z0-9@._+-]{0,99}")
_PREFIX = re.compile(r"[A-Za-z0-9._-]{0,20}")
_LABEL = re.compile(r"[^\x00-\x1f\x7f<>]{1,40}")
_VERSION = re.compile(
    r"(?<![\w.])v?(\d+\.\d+\.\d+(?:\.\d+)?)((?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)(?![\w])"
)
_PLAIN = re.compile(r"\d+(?:\.\d+){1,3}")
_HEADING = re.compile(r"^##\s+\[?v?(\d+(?:\.\d+){1,3})\]?", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]{0,300})\]\([^)]{0,500}\)")
SOURCE_KINDS = ("npm", "pypi", "github", "github_file", "brew", "cask")
VIA_WORDS = {"self": "its own updater", "brew": "Homebrew", "npm": "npm"}


# ------------------------------------------------------------------------------------------------ files


def _home() -> Path:
    from orch import addons

    return addons.home()


def _read(name: str) -> dict:
    try:
        d = json.loads((_home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write(name: str, data: dict) -> None:
    p = _home() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(data).encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------------------------------------ recipes


def library() -> dict:
    try:
        doc = json.loads(Path(__file__).with_name("known_tools.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for name, d in (doc.get("tools") or {}).items():
        r = recipe(name, d)
        if r:
            out[name] = r
    return out


def _source(doc) -> dict | None:
    if not isinstance(doc, dict):
        return None
    kinds = [k for k in SOURCE_KINDS if k in doc]
    if len(kinds) != 1 or set(doc) - {kinds[0], "tag_prefix"}:
        return None
    kind, value = kinds[0], doc[kinds[0]]
    pattern = {
        "npm": _NPM,
        "pypi": _PYPI,
        "github": _REPO,
        "github_file": _FILE,
        "brew": _BREW,
        "cask": _BREW,
    }
    if not (isinstance(value, str) and pattern[kind].fullmatch(value)) or ".." in value:
        return None
    prefix = doc.get("tag_prefix", "")
    if not (isinstance(prefix, str) and _PREFIX.fullmatch(prefix)):
        return None
    return {"kind": kind, "name": value, "tag_prefix": prefix}


def _command_ok(cmd, binary: str) -> bool:
    from orch import health

    return health.command_ok(cmd) and cmd[0] == binary


def _install(doc, binary: str) -> dict | None:
    if not isinstance(doc, dict):
        return None
    via = doc.get("via")
    if via == "brew":
        kind = "cask" if "cask" in doc else "formula"
        name = doc.get(kind)
        if set(doc) - {"via", kind} or not (isinstance(name, str) and _BREW.fullmatch(name)):
            return None
        return {"via": "brew", kind: name}
    if via == "npm":
        pkg = doc.get("package")
        if set(doc) - {"via", "package"} or not (isinstance(pkg, str) and _NPM.fullmatch(pkg)):
            return None
        return {"via": "npm", "package": pkg}
    if via == "self":
        path, cmd = doc.get("path"), doc.get("command")
        ok_path = (
            isinstance(path, str) and path.startswith("{home}/") and ".." not in path and len(path) < 200
        )
        if set(doc) - {"via", "path", "command"} or not ok_path or not _command_ok(cmd, binary):
            return None
        return {"via": "self", "path": path, "command": list(cmd)}
    return None


def recipe(binary: str, doc) -> dict | None:
    """A checked tool recipe, or None (a bad one is left out, never used)."""
    from orch import health

    if not (isinstance(binary, str) and _NAME.fullmatch(binary) and isinstance(doc, dict)):
        return None
    if health._runner(binary):
        return None  # a shell or package tool is never "the tool"
    label = doc.get("label", binary)
    if not (isinstance(label, str) and _LABEL.fullmatch(label)):
        return None
    latest = _source(doc.get("latest")) if doc.get("latest") is not None else None
    notes = _source(doc.get("notes")) if doc.get("notes") is not None else None
    if (doc.get("latest") is not None and not latest) or (doc.get("notes") is not None and not notes):
        return None
    if notes and notes["kind"] not in ("github", "github_file"):
        return None
    version = doc.get("version", [binary, "--version"])
    if not _command_ok(version, binary):
        return None
    raw = doc.get("installs") or []
    if not isinstance(raw, list) or len(raw) > 5:
        return None
    installs = [_install(i, binary) for i in raw]
    if any(i is None for i in installs):
        return None
    return {
        "binary": binary,
        "label": label.strip(),
        "version": list(version),
        "latest": latest,
        "notes": notes,
        "installs": installs,
    }


def tools_for(root: Path) -> list[dict]:
    """The tools of this workspace, each once: the helper tools, then every tool the workspace's checks run
    that the library knows, then the tools a check file brings its own `update` block for. Only tools
    installed on this computer."""
    from orch import adapters, checkfiles, health

    lib, out, taken = library(), [], set()

    def add(binary: str, r: dict | None, helper: bool) -> None:
        if binary in taken or not r:
            return
        path = shutil.which(binary)
        if not path:
            return
        taken.add(binary)
        out.append({**r, "path": path, "helper": helper})

    for name in adapters.builtin_names():
        binary = (adapters.load(name).get("detect") or {}).get("binary")
        if binary:
            add(binary, lib.get(binary), True)
    try:
        recs = health.recipes(Path(root))
    except Exception:  # noqa: BLE001  a broken check never hides the helper tools
        recs = []
    for r in recs:
        for b in ([r["command"][0]] if r.get("command") else []) + list(r.get("requires") or []):
            add(b, lib.get(b), False)
    try:
        files = checkfiles.entries(Path(root)) if checkfiles.present(Path(root)) else []
    except Exception:  # noqa: BLE001
        files = []
    for e in files:
        doc, r = e.get("doc"), e.get("recipe")
        if e.get("status") != "approved" or not r or not isinstance(doc, dict) or "update" not in doc:
            continue
        binary = (r.get("command") or [None])[0] or (r.get("requires") or [None])[0]
        if binary and binary not in lib:
            add(binary, recipe(binary, doc["update"]), False)
    return out


# ------------------------------------------------------------------------------------------------ install


def _real(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _parts(path: str) -> str:
    return path.replace("\\", "/")


def install_of(r: dict, path: str) -> dict | None:
    """How this copy of the tool was installed, positively recognised from its real path, with the update to
    run: {via, argv, brew/cask/package}. None when orch is not sure."""
    real = _parts(_real(path))
    home = _parts(str(Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())))
    for i in r["installs"]:
        if i["via"] == "self":
            if real.startswith(i["path"].replace("{home}", home.rstrip("/"))):
                return {**i, "argv": [path, *i["command"][1:]]}
        elif i["via"] == "brew":
            folder, name = ("Caskroom", i["cask"]) if "cask" in i else ("Cellar", i["formula"])
            mark = f"/{folder}/{name}/"
            if mark in real:
                brew = real.split(mark)[0] + "/bin/brew"
                if os.path.isfile(brew):
                    argv = [brew, "upgrade", *(["--cask"] if "cask" in i else []), name]
                    return {**i, "argv": argv}
        elif i["via"] == "npm":
            npm = _npm_for(real, path, i["package"])
            if npm:
                return {**i, "argv": [npm, "install", "-g", f"{i['package']}@latest"]}
    return None


def _npm_for(real: str, path: str, package: str) -> str | None:
    """The npm of the global npm folder this command belongs to, or None when it is not that package's.
    Unix: the command links into <prefix>/lib/node_modules/<package>/. Windows: npm writes a plain
    <prefix>/<name>.cmd shim next to <prefix>/node_modules/<package>/ and <prefix>/npm.cmd."""
    mark = f"/node_modules/{package}/"
    if sys.platform != "win32":
        if mark not in real:
            return None
        npm = real.split(mark)[0].removesuffix("/lib") + "/bin/npm"
        return npm if os.path.isfile(npm) else None
    if mark in real:
        prefix = real.split(mark)[0]
    elif Path(path).suffix.lower() in (".cmd", ".ps1", ""):
        prefix = _parts(os.path.dirname(path))
        if not os.path.isdir(prefix + mark):
            return None
    else:
        return None
    npm = prefix + "/npm.cmd"
    return npm if os.path.isfile(npm) else None


def _version_of(text: str) -> str | None:
    m = _VERSION.search(text or "")
    return (m.group(1) + m.group(2)) if m else None


def installed_version(r: dict, path: str) -> str | None:
    try:
        p = subprocess.run(
            [path, *r["version"][1:]],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=VERSION_TIMEOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(Path.home()),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _version_of((p.stdout or "")[:4000] + "\n" + (p.stderr or "")[:4000])


def _key(v: str | None) -> tuple | None:
    return tuple(int(x) for x in v.split(".")) if v and _PLAIN.fullmatch(v) else None


def newer(installed: str | None, newest: str | None) -> bool | None:
    """True / False when both are plain versions, else None (orch cannot tell)."""
    a, b = _key(installed), _key(newest)
    if a is None or b is None:
        return None
    n = max(len(a), len(b))
    return (b + (0,) * (n - len(b))) > (a + (0,) * (n - len(a)))


# ------------------------------------------------------------------------------------------------ outside


class _SameHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise urllib.error.URLError("redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _allowed(url: str) -> bool:
    u = urllib.parse.urlsplit(url)
    return u.scheme == "https" and u.hostname in ALLOWED_HOSTS and u.port in (None, 443)


def get(url: str) -> bytes:
    """One GET to an allowed host, size-limited; raises OSError/ValueError on any problem. ORCH_NO_TOOL_CHECK
    (demo and test installs) turns every outside question off."""
    if os.environ.get("ORCH_NO_TOOL_CHECK"):
        raise OSError("outside checks are off here")
    if not _allowed(url):
        raise ValueError("not an allowed address")
    from orch import net

    opener = urllib.request.build_opener(
        _SameHosts, *([urllib.request.HTTPSHandler(context=net._tls())] if net._tls() else [])
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/plain"})
    with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read(HTTP_LIMIT + 1)
    if len(raw) > HTTP_LIMIT:
        raise ValueError("answer too big")
    return raw


def _json(url: str):
    return json.loads(get(url).decode("utf-8", "replace"))


def _strip(tag: str, prefix: str) -> str:
    tag = tag.removeprefix(prefix) if prefix else tag
    return tag.removeprefix("v")


def newest_of(src: dict) -> str | None:
    kind, name = src["kind"], src["name"]
    q = urllib.parse.quote
    if kind == "npm":
        v = _json(f"https://registry.npmjs.org/{q(name, safe='@/')}/latest").get("version")
    elif kind == "pypi":
        v = (_json(f"https://pypi.org/pypi/{q(name)}/json").get("info") or {}).get("version")
    elif kind == "github":
        v = _strip(
            str(_json(f"https://api.github.com/repos/{name}/releases/latest").get("tag_name") or ""),
            src["tag_prefix"],
        )
    elif kind == "brew":
        v = (_json(f"https://formulae.brew.sh/api/formula/{q(name)}.json").get("versions") or {}).get(
            "stable"
        )
    elif kind == "cask":
        v = str(_json(f"https://formulae.brew.sh/api/cask/{q(name)}.json").get("version") or "").split(",")[0]
    else:
        return None
    return _version_of(str(v or "")) if v else None


def _clean(line: str) -> str:
    from orch.services import _printable

    t = _LINK.sub(r"\1", line)
    t = t.replace("**", "").replace("`", "")
    t = " ".join(_printable(t).split())
    return t if len(t) <= LINE_MAX else t[: LINE_MAX - 1] + "…"


def _bullets(body: str) -> list[str]:
    out = []
    for raw in (body or "").splitlines():
        s = raw.strip()
        if s[:2] in ("- ", "* ", "+ "):
            t = _clean(s[2:])
            if t:
                out.append(t)
    return out


def _wanted(v: str | None, installed: str | None, newest: str | None) -> bool:
    if _key(v) is None:
        return False
    if installed is None or _key(installed) is None:
        return v == newest
    return bool(newer(installed, v)) and not newer(newest, v)


def notes_of(src: dict, installed: str | None, newest: str | None) -> tuple[list[dict], str]:
    """([{version, lines}] newest first, the link to the full notes) for the versions after `installed` up to
    `newest`."""
    name = src["name"]
    if src["kind"] == "github":
        # the release list carries every download of every release (megabytes): read the tag names, then
        # only the wanted releases, newest first
        url = f"https://github.com/{name}/releases"
        tags = _json(f"https://api.github.com/repos/{name}/tags?per_page=100")
        wanted = []
        for tag in tags if isinstance(tags, list) else []:
            tname = str((tag or {}).get("name") or "") if isinstance(tag, dict) else ""
            if src["tag_prefix"] and not tname.startswith(src["tag_prefix"]):
                continue
            v = _strip(tname, src["tag_prefix"])
            if _wanted(v, installed, newest):
                wanted.append((_key(v), v, tname))
        out = []
        for _, v, tname in sorted(wanted, reverse=True)[:MAX_RELEASES]:
            try:
                rel = _json(f"https://api.github.com/repos/{name}/releases/tags/{urllib.parse.quote(tname)}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue  # a tag without a release
                raise
            if isinstance(rel, dict) and not rel.get("prerelease") and not rel.get("draft"):
                out.append({"version": v, "lines": _bullets(str(rel.get("body") or ""))})
        return out, url
    owner, repo, branch, path = name.split("/", 3)
    url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
    text = get(f"https://raw.githubusercontent.com/{name}").decode("utf-8", "replace")
    out, marks = [], list(_HEADING.finditer(text))
    for n, m in enumerate(marks):
        if _wanted(m.group(1), installed, newest):
            end = marks[n + 1].start() if n + 1 < len(marks) else len(text)
            out.append({"version": m.group(1), "lines": _bullets(text[m.end() : end])})
    return out, url


def _cap(sections: list[dict]) -> tuple[list[dict], int]:
    """At most MAX_NOTE_LINES lines in all, newest first; the rest is counted."""
    left, out, more = MAX_NOTE_LINES, [], 0
    for s in sections:
        keep = s["lines"][: min(PER_VERSION, left)]
        left -= len(keep)
        more += len(s["lines"]) - len(keep)
        if keep:
            out.append({"version": s["version"], "lines": keep})
    if not out and sections:
        out = [{"version": sections[0]["version"], "lines": []}]
    return out, more


# ------------------------------------------------------------------------------------------------ status


def _fingerprint(r: dict, path: str) -> str:
    real = _real(path)
    try:
        st = os.stat(real)
        stamp = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        stamp = "-"
    doc = json.dumps({k: r[k] for k in ("version", "latest", "notes", "installs")}, sort_keys=True)
    return hashlib.sha256(f"{doc}|{real}|{stamp}".encode()).hexdigest()[:16]


def _check(r: dict, path: str, last: dict | None) -> dict:
    inst = install_of(r, path)
    installed = installed_version(r, path)
    row = {
        "name": r["binary"],
        "label": r["label"],
        "helper": bool(r.get("helper")),
        "installed": installed,
        "via": inst["via"] if inst else None,
        "how": VIA_WORDS.get(inst["via"]) if inst else None,
        "checked_at": _now(),
        "at": time.time(),
    }
    error = None
    newest = None
    try:
        brew_src = None
        if inst and inst["via"] == "brew":
            brew_src = {
                "kind": "cask" if "cask" in inst else "brew",
                "name": inst.get("cask") or inst.get("formula"),
                "tag_prefix": "",
            }
        if brew_src:
            try:
                newest = newest_of(brew_src)  # what Homebrew can install, which may lag behind the maker
            except (OSError, ValueError):
                newest = None
        if newest is None and r["latest"]:
            newest = newest_of(r["latest"])
    except (OSError, ValueError, KeyError, AttributeError) as e:
        error = _why(e)
    notes, url, more = [], None, 0
    if r["notes"]:
        try:
            got, url = notes_of(r["notes"], installed, newest)
            notes, more = _cap(got)
        except (OSError, ValueError, KeyError, AttributeError) as e:
            error = error or _why(e)
            url = None
    if error and last and last.get("newest"):
        newest, notes, more, url = (
            last["newest"],
            last.get("notes") or [],
            last.get("more", 0),
            last.get("notes_url"),
        )
        row["last_good_at"] = last.get("last_good_at") or last.get("checked_at")
    elif not error:
        row["last_good_at"] = row["checked_at"]
    upd = newer(installed, newest)
    row.update(
        {
            "newest": newest,
            "update": bool(upd),
            "compare": "unknown" if upd is None else ("newer" if upd else "current"),
            "can_update": bool(inst) and bool(upd),
            "notes": notes if upd or not installed else [],
            "more": more if upd or not installed else 0,
            "notes_url": url,
            "error": error,
            "manual": None
            if inst
            else "orch cannot tell how it was installed; update it the way you installed it.",
        }
    )
    return row


def _why(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"The update source answered {e.code}."
    if isinstance(e, urllib.error.URLError | TimeoutError | OSError):
        return "The update source could not be reached."
    return "The update source gave an answer orch cannot read."


def status(root: Path, refresh: bool = False, only: str | None = None) -> dict:
    """Every tool of this workspace with installed / newest version, notes and how it updates. Network
    answers are kept for CACHE_SECONDS per tool (a changed install or recipe asks again)."""
    cache = _read(CACHE_FILE)
    items = cache.get("items") if isinstance(cache.get("items"), dict) else {}
    rows, changed = [], False
    for r in tools_for(root):
        if only and r["binary"] != only:
            continue
        fp = _fingerprint(r, r["path"])
        have = items.get(r["binary"]) if isinstance(items.get(r["binary"]), dict) else None
        fresh = have and have.get("fp") == fp and time.time() - float(have.get("at") or 0) < CACHE_SECONDS
        if fresh and not refresh:
            row = dict(have)
        else:
            row = _check(r, r["path"], have)
            row["fp"] = fp
            items[r["binary"]] = row
            changed = True
        row["helper"] = bool(r.get("helper"))
        rows.append(row)
    if changed:
        try:
            _write(CACHE_FILE, {"items": items})
        except OSError:
            pass
    job = job_state()
    return {
        "tools": [{k: v for k, v in x.items() if k not in ("fp", "at")} for x in rows],
        "updates": sum(1 for x in rows if x.get("update")),
        "job": job,
    }


# ------------------------------------------------------------------------------------------------ update


def _alive(pid, started: str | None = None) -> bool:
    """The update process still runs (same start time, so a reused pid does not count)."""
    from orch import procs

    if not isinstance(pid, int):
        return False
    now = procs.pid_started(pid)
    return bool(now) and (not started or procs.same_start(now, started))


def job_state() -> dict | None:
    j = _read(JOB_FILE)
    if not j:
        return None
    if j.get("status") == "running" and not _alive(j.get("pid"), j.get("pid_started")):
        j["status"] = "stopped"  # the update ended without saying how (closed, crashed)
    return {
        k: j.get(k) for k in ("name", "label", "status", "from", "to", "started_at", "finished_at", "say")
    }


def in_helper() -> bool:
    """This command runs inside a helper (an agent tool or a helper run)."""
    from orch import renew, tickets

    return bool(tickets.agent_tool() or any(os.environ.get(k) for k in renew.RUN_MARKS))


def for_helper(doc: dict) -> dict:
    """The same answer without the release notes: they are text from outside and never go to a helper."""
    tools = [
        {**t, "notes": [], "more": 0, "notes_hidden": bool(t.get("notes"))} for t in doc.get("tools") or []
    ]
    return {**doc, "tools": tools}


def _person() -> None:
    if in_helper():
        raise Refused(
            "Only a person starts a tool update. Tell them it is there: orch tools (or Settings > About & "
            "updates)."
        )


def _log_tail(path: Path, lines: int = 5) -> list[str]:
    try:
        raw = path.read_bytes()[-LOG_KEEP:]
    except OSError:
        return []
    from orch.services import _printable

    return [_printable(x)[:LINE_MAX] for x in raw.decode("utf-8", "replace").splitlines() if x.strip()][
        -lines:
    ]


@contextlib.contextmanager
def _only_one():
    """Hold the one tool-update lock for the whole update (two clicks at once: the second is refused)."""
    from orch import procs

    p = _home() / LOCK_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            try:
                other = json.loads(p.read_text(encoding="utf-8"))
                young = False
            except (OSError, ValueError):
                other = {}
                try:
                    young = time.time() - p.stat().st_mtime < 30  # being written right now
                except OSError:
                    young = False
            if young or _alive(other.get("pid"), other.get("started")):
                label = _read(JOB_FILE).get("label") or "Another tool"
                raise Refused(f"{label} is being updated. Try again when it is done.") from None
            p.unlink(missing_ok=True)  # left behind by an update that ended without cleaning up
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "started": procs.pid_started(os.getpid())}))
        try:
            yield
        finally:
            p.unlink(missing_ok=True)
        return
    raise Refused("Another tool update is starting. Try again in a moment.")


def update(root: Path, name: str) -> dict:
    """Run the update of one tool now (a person only; one at a time; never killed). Returns the job."""
    _person()
    r = next((t for t in tools_for(root) if t["binary"] == name), None)
    if not r:
        names = ", ".join(t["binary"] for t in tools_for(root)) or "none"
        raise Refused(f"There is no tool called {name} here. Tools: {names}")
    inst = install_of(r, r["path"])
    if not inst:
        raise Refused(f"orch cannot tell how {r['label']} was installed; update it the way you installed it.")
    with _only_one():
        return _run_update(root, r, inst)


def _run_update(root: Path, r: dict, inst: dict) -> dict:
    from orch import procs

    name = r["binary"]
    before = installed_version(r, r["path"])
    log = _home() / LOG_FILE
    job = {
        "name": name,
        "label": r["label"],
        "status": "running",
        "pid": os.getpid(),
        "pid_started": procs.pid_started(os.getpid()),
        "from": before,
        "to": None,
        "started_at": _now(),
        "finished_at": None,
        "say": None,
    }
    _write(JOB_FILE, job)
    env = dict(os.environ)
    tool_dir = os.path.dirname(inst["argv"][0])
    env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")  # npm next to its own node (nvm)
    code = None
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "wb") as out:
            code = subprocess.run(
                inst["argv"],
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(Path.home()),
                env=env,
            ).returncode
    except OSError:
        code = None
    after = installed_version(r, r["path"])
    if code == 0 and after and after != before:
        job.update(status="done", say=f"{r['label']} is now {after}.")
    elif code == 0:
        job.update(status="done", say=f"{r['label']} is up to date ({after or before or 'version unknown'}).")
    else:
        job.update(status="failed", say=f"The update of {r['label']} did not work. orch kept its output.")
    if r.get("helper") and job["status"] == "done":
        job["say"] += " Helpers working now keep going; they use the new version from their next start."
    job.update(to=after, finished_at=_now(), tail=_log_tail(log) if job["status"] == "failed" else [])
    _write(JOB_FILE, job)
    try:
        status(root, refresh=True, only=name)
    except Exception:  # noqa: BLE001  the next look checks again
        pass
    return job
