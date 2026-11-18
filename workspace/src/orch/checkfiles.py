"""Checks a workspace sets for itself (ORCH-529): one file per check in `.orch/checks/<name>.json`.

Each workspace says which tools, logins, connections and keys it depends on, how to test each one, how often,
and what to tell the person when a test fails. Nothing is checked unless the workspace asks for it: while a
workspace has this folder, the built-in list (known_checks.json) no longer runs by itself; it is a library
of templates (`orch checks add databricks --profile X`). A workspace without the folder keeps the old
behaviour for one release and is shown a notice pointing to `orch checks init`.

A check file (every field except the command or script may be left out):
    {"label": "Databricks dev", "kind": "login",                 # login | connection | key | tool
     "command": ["databricks", "current-user", "me", "--profile", "dev"],   # or "script": "<name>.py"
     "works": null, "ends": null,                                # JSON paths, as health.py reads them
     "interval": "30m", "timeout": "20s",
     "how": "...", "sign_in": "databricks auth login --profile dev",
     "requires": ["databricks"], "key": "<key name>"}

A command is a tool's own status command with plain arguments (health.command_ok). A script is a file next
to the check (`.py` runs with orch's own Python, so it works on macOS and Windows; `.sh` on macOS/Linux;
`.ps1` on Windows). A script check may name a key (`key`): its value reaches the script through a pipe whose
descriptor the variable ORCH_CHECK_KEY_FD names (on Windows the plain variable ORCH_CHECK_KEY), never as an
argument and never in a file. The script runs from a private copy of exactly the bytes that were approved.

Security (R5.2 and the cloned-project rule of health.py): a check file from the project folder never runs on
its own. It runs only after the person approved it (`orch checks approve <name>`); whenever its content (the
file and its script) changes, the person approves it again first. What was approved is kept as content hashes in
the guarded orch home (key folder record `checks`, field `approved`), never in `.orch/`. An agent cannot
approve. What a check prints is handled as before: only works / ends are kept, nothing is stored or shown.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from orch import health
from orch.errors import Refused

TEMPLATE_FILE = "_template.json"
SCRIPT_RUNS = {".py", ".sh", ".ps1"}
_SCRIPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_DURATION = re.compile(r"(\d{1,6})\s*([smhd]?)")
_UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
INTERVAL_MIN, INTERVAL_MAX = 60, 7 * 86400
TIMEOUT_MAX = 120
_FILE_MAX = 64 * 1024
KEY_ENV = "ORCH_CHECK_KEY"

NOT_APPROVED_BY_AGENT = (
    "Only the person approves a check: it runs a command on this computer. Ask them to look at the check "
    "file and run orch checks approve in their own terminal."
)


def folder(root: Path) -> Path:
    return Path(root) / ".orch" / "checks"


def present(root: Path) -> bool:
    """The workspace sets its own checks (the folder exists): the built-in list stops running by itself."""
    return folder(root).is_dir()


def duration(value, default: int, lo: int, hi: int) -> int | None:
    """Seconds from '30s', '15m', '2h', '1d' or a number of seconds; None when it is none of these or
    outside lo..hi. Absent (None) gives the default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        secs = value
    elif isinstance(value, str) and (m := _DURATION.fullmatch(value.strip().lower())):
        secs = int(m.group(1)) * _UNIT[m.group(2)]
    else:
        return None
    return secs if lo <= secs <= hi else None


# ------------------------------------------------------------------------------------------------ reading


def _names(root: Path) -> list[str]:
    try:
        files = sorted(folder(root).glob("*.json"))
    except OSError:
        return []
    return [f.stem for f in files if not f.name.startswith("_") and f.is_file()]


def _bytes(path: Path) -> bytes | None:
    """A small regular file's bytes, read once from one open handle; None for a link, a folder, a device, a
    file over _FILE_MAX or one that cannot be read (a check file is project content: never trusted)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(_FILE_MAX + 1)
        return raw if len(raw) <= _FILE_MAX else None
    except OSError:
        return None
    finally:
        os.close(fd)


def _load(root: Path, name: str) -> tuple[object, str | None, bytes | None]:
    """(file content, content hash, script bytes) of one check, each file read once, so what is hashed is
    exactly what is parsed and run. The hash covers the file and its script (when it names one)."""
    raw = _bytes(folder(root) / f"{name}.json")
    if raw is None:
        return None, None, None
    h = hashlib.sha256(raw)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        doc = None
    script = doc.get("script") if isinstance(doc, dict) else None
    body = None
    if isinstance(script, str) and _SCRIPT.fullmatch(script):
        body = _bytes(folder(root) / script)
        h.update(b"\0script\0" + (body if body is not None else b"\0missing\0"))
    return doc, h.hexdigest(), body


def digest(root: Path, name: str) -> str | None:
    """The content hash of one check (see _load). None when its file cannot be read."""
    return _load(root, name)[1]


def parse(name: str, doc) -> dict | None:
    """A runnable recipe from one check file, or None when it is not one (left out and never run)."""
    if not isinstance(doc, dict):
        return None
    script = doc.get("script")
    if script is not None:
        if doc.get("command") is not None:
            return None  # one or the other
        if not (isinstance(script, str) and _SCRIPT.fullmatch(script)):
            return None
        if Path(script).suffix.lower() not in SCRIPT_RUNS:
            return None
    clean = {k: v for k, v in doc.items() if not k.startswith("_")}
    r = health._recipe(name, clean, script=script is not None)
    if not r:
        return None
    interval = duration(doc.get("interval"), health.CHECK_EVERY, INTERVAL_MIN, INTERVAL_MAX)
    timeout = duration(doc.get("timeout"), health.TIMEOUT, 1, TIMEOUT_MAX)
    if interval is None or timeout is None:
        return None
    requires = doc.get("requires") or []
    if not (
        isinstance(requires, list)
        and len(requires) <= 5
        and all(isinstance(b, str) and health._BINARY.fullmatch(b) for b in requires)
    ):
        return None
    return {**r, "script": script, "interval": interval, "timeout": timeout, "requires": requires}


def _approved(root: Path) -> dict:
    from orch import keystore

    try:
        doc = keystore.record_read(Path(root), "checks") or {}
    except Exception:  # noqa: BLE001  a damaged or unsafe record approves nothing
        return {}
    got = doc.get("approved") if isinstance(doc, dict) else None
    return got if isinstance(got, dict) else {}


def entries(root: Path) -> list[dict]:
    """Every check file: {name, recipe (None when broken), digest, status: approved | new | changed}."""
    ok = _approved(root)
    out = []
    for name in _names(root):
        doc, dg, _ = _load(root, name)
        r = parse(name, doc)
        if r:
            r["v"] = (dg or "")[:16]
        status = "approved" if dg and ok.get(name) == dg else "changed" if name in ok else "new"
        out.append({"name": name, "recipe": r, "digest": dg, "status": status, "doc": doc})
    return out


def recipes(root: Path) -> list[dict]:
    """The check files that may run: well formed and approved with their current content."""
    return [e["recipe"] for e in entries(root) if e["recipe"] and e["status"] == "approved"]


def _how_to_approve(name: str, status: str) -> str:
    what = "changed" if status == "changed" else "new"
    return (
        f"This check is {what} and runs only after you approve it. "
        f"Look at .orch/checks/{name}.json, then run:"
    )


def waiting_rows(root: Path) -> list[dict]:
    """A row for every check file that waits for the person (new, changed or broken). Nothing runs; the row
    says how to approve it (the command shown with Copy, never run by orch)."""
    rows = []
    for e in entries(root):
        if e["status"] == "approved" and e["recipe"]:
            continue
        r = e["recipe"]
        doc = e["doc"] if isinstance(e["doc"], dict) else {}
        label = r["label"] if r else (doc.get("label") if isinstance(doc.get("label"), str) else e["name"])
        if not health._LABEL.fullmatch(label or ""):
            label = e["name"]
        if r:
            how, sign_in = _how_to_approve(e["name"], e["status"]), f"orch checks approve {e['name']}"
        else:
            how, sign_in = (
                f"The check file .orch/checks/{e['name']}.json cannot be read. Fix it with the template.",
                None,
            )
        rows.append(
            {
                "name": e["name"],
                "label": label.strip(),
                "kind": r["kind"] if r else "login",
                "state": "unreachable",
                "ends_at": None,
                "helper": None,
                "chosen": False,
                "stops": [],
                "renew": False,
                "key": None,
                "how": how,
                "sign_in": sign_in,
                "approve": e["status"] if r else "broken",
            }
        )
    return rows


# ------------------------------------------------------------------------------------------------ running


def _runner(ext: str, path: str) -> list[str] | None:
    if ext == ".py":
        return [sys.executable, "-I", path]
    if ext == ".sh" and os.name != "nt" and (sh := shutil.which("sh")):
        return [sh, path]
    if ext == ".ps1" and os.name == "nt" and (ps := shutil.which("powershell") or shutil.which("pwsh")):
        return [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path]
    return None


@contextlib.contextmanager
def prepared(root: Path, r: dict):
    """(argv, env, pass_fds) to run a script check, or (None, None, ()) when it may not or cannot run here.

    The check is read again and its hash compared with the approved one right now; the bytes that matched are
    written to a private copy that is run (never the project file, which could change in between) and
    removed afterwards. A named key goes through a pipe (renew.hand_over: KEY_ENV + "_FD" names it; the
    plain variable on Windows), never as an argument or a file."""
    from orch import renew

    no = (None, None, ())
    if any(not shutil.which(b) for b in r.get("requires") or ()):
        yield no
        return
    doc, dg, body = _load(root, r["name"])
    now = parse(r["name"], doc)
    if (
        body is None
        or not dg
        or _approved(root).get(r["name"]) != dg
        or not now
        or now["script"] != r["script"]
    ):
        yield no
        return
    ext = Path(r["script"]).suffix.lower()
    if not _runner(ext, "x"):
        yield no
        return
    env = {k: v for k, v in os.environ.items() if k not in (KEY_ENV, KEY_ENV + "_FD")}
    fd = None
    if now.get("key"):
        from orch import keystore

        try:
            value = keystore.get_value(Path(root), now["key"])
        except Refused:
            value = None
        if not isinstance(value, str):  # no such key, or a key file: nothing is handed over
            yield no
            return
        fd = renew.hand_over(env, KEY_ENV, value)
    tmp = Path(tempfile.mkdtemp(prefix="orch-check-"))  # 0700, this user only
    copy = tmp / f"check{ext}"
    try:
        with open(copy, "wb") as f:
            f.write(body)
        yield _runner(ext, str(copy)), env, ((fd,) if fd is not None else ())
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            copy.unlink()
        with contextlib.suppress(OSError):
            tmp.rmdir()


# ------------------------------------------------------------------------------------------------ changing


def _person(by: str | None) -> None:
    from orch import renew, tickets

    if (
        (by or "").startswith("agent:")
        or tickets.agent_tool()
        or any(os.environ.get(k) for k in renew.RUN_MARKS)
    ):
        raise Refused(NOT_APPROVED_BY_AGENT)


def _remember(root: Path, name: str, dg: str | None) -> None:
    from orch import keystore

    have = keystore.record_read(Path(root), "checks") or {}
    ok = have.get("approved") if isinstance(have.get("approved"), dict) else {}
    if dg:
        ok[name] = dg
    else:
        ok.pop(name, None)
    keystore.record_write(Path(root), "checks", {**have, "approved": ok})


def approve(root: Path, name: str, by: str | None = None) -> dict:
    """The person approves one check file as it is now; refused for an agent and for a broken file."""
    _person(by)
    e = next((x for x in entries(root) if x["name"] == name), None)
    if not e:
        raise Refused(f"There is no check called {name}. See them with: orch checks list")
    if not e["recipe"]:
        raise Refused(
            f"The check {name} cannot be read, so it cannot be approved. Fix it with {TEMPLATE_FILE}."
        )
    _remember(root, name, e["digest"])
    return e["recipe"]


def _write(root: Path, name: str, doc: dict) -> Path:
    from orch import net

    folder(root).mkdir(parents=True, exist_ok=True)
    path = folder(root) / f"{name}.json"
    net.write_json(path, doc)
    return path


def remove(root: Path, name: str) -> bool:
    """Delete one check file and forget that it was approved (a script next to it is the person's file and stays)."""
    if not health._NAME.fullmatch(name or ""):
        return False
    path = folder(root) / f"{name}.json"
    gone = path.is_file()
    if gone:
        path.unlink()
    with contextlib.suppress(Exception):
        _remember(root, name, None)
    return gone


# ------------------------------------------------------------------------------------------------ templates


def _library() -> dict:
    try:
        doc = json.loads(Path(health.__file__).with_name("known_checks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc.get("checks") or {}


def templates() -> list[dict]:
    """The built-in checks as templates: {name, label, profile (takes --profile)}."""
    return [
        {"name": n, "label": d.get("label", n), "profile": bool(d.get("profile"))}
        for n, d in _library().items()
    ]


def from_template(tname: str, profile: str | None = None, name: str | None = None) -> tuple[str, dict]:
    """(check name, check file content) from a built-in template; one check per profile where the tool has
    profiles, so each warning names its own sign-in command."""
    d = _library().get(tname)
    if not d:
        names = ", ".join(t["name"] for t in templates())
        raise Refused(f"There is no template called {tname}. Templates: {names}")
    p = d.get("profile")
    if profile is not None and not p:
        raise Refused(f"{d.get('label', tname)} has no profiles; leave out --profile.")
    if p and profile is None:
        raise Refused(f"Say which {d.get('label', tname)} profile to check: --profile <name>")
    if profile is not None and not _PROFILE.fullmatch(profile):
        raise Refused("A profile name is letters, digits, dot, dash or underscore (at most 64).")
    fill = (lambda v: v.replace("{profile}", profile)) if profile else (lambda v: v)
    if p:
        doc = {
            "label": fill(p.get("label", d.get("label", tname) + " {profile}"))[:40],
            "kind": "login",
            "command": [fill(a) for a in p["command"]],
            "sign_in": fill(p["sign_in"]),
        }
        auto = re.sub(r"[^a-z0-9-]+", "-", f"{tname}-{profile}".lower()).strip("-")[:32].rstrip("-")
    else:
        doc = {"label": d.get("label", tname), "kind": "login", "command": d["command"]}
        doc |= {k: d[k] for k in ("works", "ends", "sign_in") if d.get(k)}
        auto = tname
    name = name or auto
    if not parse(name, doc):
        raise Refused(health.BAD_CHECK)
    return name, doc


def add_from_template(root: Path, tname: str, profile: str | None = None, name: str | None = None) -> dict:
    """Write a check file from a built-in template and approve it: the content is orch's own, so nothing from
    the project runs. Refused when the name is taken (a helper tool or a check file already there)."""
    name, doc = from_template(tname, profile, name)
    if name in {x["name"] for x in health.helper_recipes()}:
        raise Refused(f"orch already checks {name} by itself; pick another name with --name.")
    if (folder(root) / f"{name}.json").exists():
        raise Refused(f"There is already a check called {name}. Remove it first: orch checks remove {name}")
    _write(root, name, doc)
    _remember(root, name, digest(root, name))
    return parse(name, doc) | {"v": (digest(root, name) or "")[:16]}


TEMPLATE = {
    "_doc": (
        "A check this workspace depends on (ORCH-529). Copy this file to <name>.json (small letters, digits, "
        "dash); files starting with _ never run. A new or changed check runs only after the person approved "
        "it: orch checks approve <name>. Fields starting with _ are notes and are ignored."
    ),
    "_label": "What the person reads on the warning, at most 40 characters.",
    "_kind": "login, connection, key or tool.",
    "_command": (
        "The tool's own status command, one word per item, plain arguments (no shell, no script runner). "
        "Leave it out when you use script."
    ),
    "_script": (
        "Instead of command: a script next to this file (.py runs with orch's Python on macOS and Windows, "
        ".sh on macOS/Linux, .ps1 on Windows). Exit code 0 = works, unless works is set."
    ),
    "_works": (
        "Optional: a field of the JSON the command prints that must be true (profiles.*.valid = all items)."
    ),
    "_ends": "Optional: a field of that JSON with the end time; the warning starts 3 days before.",
    "_interval": "How often to check: 30m, 2h, 1d (at least 1m, at most 7d). Default 15m.",
    "_timeout": (
        "How long the check may take before it counts as unreachable: 20s (at most 120s). Default 10s."
    ),
    "_how": "The one plain step the person takes when it stops working, shown word for word.",
    "_sign_in": "The terminal command that signs in again, shown with a Copy button; orch never runs it.",
    "_requires": "Tools that must be installed; when one is missing the check is unreachable, not 'renew'.",
    "_key": (
        "For a script: the name of a key (orch keys). The script reads it from the file descriptor in "
        "ORCH_CHECK_KEY_FD (Windows: the variable ORCH_CHECK_KEY). The script runs from a private copy."
    ),
    "label": "Databricks dev",
    "kind": "login",
    "command": ["databricks", "current-user", "me", "--profile", "dev"],
    "interval": "30m",
    "timeout": "20s",
    "sign_in": "databricks auth login --profile dev",
    "requires": ["databricks"],
}


def init(root: Path) -> dict:
    """Make the check folder with the documented template. From now on only this workspace's own checks
    run (plus the helper tools' logins). Returns the templates that fit tools set up on this computer."""
    path = folder(root) / TEMPLATE_FILE
    made = not folder(root).is_dir()
    if not path.exists():
        _write(root, TEMPLATE_FILE[:-5], TEMPLATE)
    used = [r["name"] for r in health.known_recipes()]
    return {"made": made, "folder": ".orch/checks", "set_up_here": used}


def notice(root: Path) -> str | None:
    """For a workspace without a check folder whose computer still runs built-in checks (the old way, one
    release): one line pointing to orch checks init."""
    if present(root):
        return None
    labels = [r["label"] for r in health.known_recipes()]
    if not labels:
        return None
    return (
        f"orch still checks {', '.join(labels)} for every workspace on this computer. Choose what this "
        "workspace needs: orch checks init"
    )
