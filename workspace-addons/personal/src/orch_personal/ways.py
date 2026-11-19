"""Ways in: the person's own small scripts that reach one source on this computer (Calendar app, Teams web,
Yogurt, a folder), run by Personal inside the workspace (owner, ORCH-649: no separate notebook app).

    .orch/addons/personal/ways/<slug>/way.toml
        name = "Teams"
        part = "messages"                      # which part it serves (shown next to it)
        selfcheck = ["./check.sh"]             # exit 0 works, exit 3 needs the person's permission, else stopped
        [actions]
        unread = ["python3", "unread.py"]      # values arrive as JSON on stdin; text comes back on stdout
    .orch/addons/personal/ways/<slug>/...      the script and the skill files it uses
    .orch/addons/personal/ways-data/<slug>/    what the script writes (ORCH_PERSONAL_WAY_DATA); never in its folder
    .orch/addons/personal/ways.json            per way in: on, fingerprint, status, checked, last worked, problem

Rules, checked here before a helper sees anything:
- A way in is off until the person turns it on; only the person turns it on or off. Turning on keeps a hash of
  its folder: any change afterwards stops it until the person turns it on again.
- Only the commands listed in way.toml run, never through a shell; a relative program stays inside its folder.
- Text only: UTF-8 without NUL, at most 64 KB, nothing that looks like a secret; 60 seconds at most.
A way in is the person's own program and runs as them: "text only" is what a helper gets, not a sandbox.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import tomllib
from pathlib import Path

from . import store
from .store import Refused

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
MAX_OUT = 65536
MAX_IN = 16384
TIMEOUT = 60
CHECK_EVERY = 24 * 3600
NEEDS_PERMISSION = 3  # self-check exit code: the source asks the person to allow access (Calendar, a sign-in)
STATUS = ("off", "permission", "stopped", "works")
STATUS_WORDS = {
    "off": "Off",
    "permission": "Needs your permission",
    "stopped": "Stopped",
    "works": "Works",
}
SECRET_REFUSED = "The answer looks like it holds a password or key, so helpers do not get it."
_LOCK = threading.Lock()


def folder(root: Path) -> Path:
    return store.base(root) / "ways"


def _clean(text: str, limit: int) -> str:
    text = "".join(c if c.isprintable() else " " for c in str(text))
    return " ".join(text.split())[:limit]


def _argv_ok(v) -> bool:
    return (
        isinstance(v, list)
        and 0 < len(v) <= 32
        and all(isinstance(x, str) and x and "\x00" not in x for x in v)
    )


def found(root: Path) -> dict[str, dict]:
    """{slug: {name, part, actions, selfcheck, dir}} for every valid ways/<slug>/way.toml."""
    out: dict[str, dict] = {}
    d = folder(root)
    for w in sorted(d.iterdir()) if d.is_dir() and not d.is_symlink() else []:
        if not w.is_dir() or w.is_symlink() or not SLUG.fullmatch(w.name):
            continue
        try:
            cfg = tomllib.loads((w / "way.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        acts = cfg.get("actions") if isinstance(cfg.get("actions"), dict) else {}
        sc = cfg.get("selfcheck")
        part = str(cfg.get("part") or "")
        out[w.name] = {
            "name": _clean(cfg.get("name") or w.name, 80) or w.name,
            "part": part if part in store.PARTS or part in store.SOON else "",
            "actions": {a: v for a, v in acts.items() if SLUG.fullmatch(a) and _argv_ok(v)},
            "selfcheck": sc if _argv_ok(sc) else None,
            "dir": w,
        }
    return out


CHANGED = "It changed since you turned it on. Turn it on again if you made the change."
MAX_FILES = 500


def fingerprint(where: Path) -> str:
    """One hash over every file in the way's folder (names and contents; a link counts as its target text). Turning
    a way in on stores it; any change afterwards (way.toml, a script, a skill file) stops the way in until the person
    turns it on again, so "on" always means the scripts the person saw."""
    h = hashlib.sha256()
    files = sorted(x for x in where.rglob("*") if x.is_symlink() or x.is_file())
    for f in files[:MAX_FILES]:
        h.update(f.relative_to(where).as_posix().encode() + b"\0")
        h.update(os.readlink(f).encode() if f.is_symlink() else f.read_bytes())
        h.update(b"\0")
    h.update(str(len(files)).encode())
    return h.hexdigest()


def _changed(slug: str, w: dict, s: dict) -> bool:
    try:
        return bool(s.get("on")) and s.get("fingerprint") != fingerprint(w["dir"])
    except OSError:
        return True


# --- saved state ---------------------------------------------------------------------------------------------
def _state_file(root: Path) -> Path:
    return store.base(root) / "ways.json"


def saved(root: Path) -> dict[str, dict]:
    raw = store._read_json(_state_file(root), {})
    return {k: v for k, v in raw.items() if SLUG.fullmatch(k) and isinstance(v, dict)}


def _update(root: Path, slug: str, **fields) -> dict:
    with _LOCK:
        data = saved(root)
        row = {**data.get(slug, {}), **fields}
        data[slug] = row
        store._atomic_write(_state_file(root), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return row


def status(root: Path) -> list[dict]:
    """One row per way in: name, part, status (off / permission / stopped / works), checked, last worked."""
    st = saved(root)
    rows = []
    for slug, w in found(root).items():
        s = st.get(slug, {})
        on = bool(s.get("on"))
        state = s.get("status") if on and s.get("status") in STATUS else ("stopped" if on else "off")
        changed = _changed(slug, w, s)
        if changed:
            state = "permission"
        rows.append(
            {
                "way": slug,
                "name": w["name"],
                "part": w["part"],
                "on": on,
                "status": state,
                "words": STATUS_WORDS[state],
                "checked": s.get("checked") if on else None,
                "last_worked": s.get("last_worked"),
                "problem": CHANGED
                if changed
                else s.get("problem")
                if on and state in ("permission", "stopped")
                else None,
                "changed": changed,
                "actions": sorted(w["actions"]),
            }
        )
    return rows


def _get(root: Path, slug: str) -> dict:
    w = found(root).get(slug)
    if not w:
        raise Refused(f"There is no way in called {slug}. See them: orch personal ways")
    return w


# --- the person turns a way in on and off --------------------------------------------------------------------
def turn(root: Path, slug: str, on: bool) -> dict:
    w = _get(root, slug)
    _update(root, slug, on=on, fingerprint=fingerprint(w["dir"]) if on else None)
    if on:
        return check(root, slug)
    return next(r for r in status(root) if r["way"] == slug)


# --- running -------------------------------------------------------------------------------------------------
def _resolve(argv: list[str], where: Path) -> list[str]:
    """A relative program (./x or x/y) must stay inside the way's folder; a bare word is a program on PATH; a full
    path is the person's own choice in way.toml."""
    first = argv[0]
    if Path(first).is_absolute():
        return list(argv)
    if "/" in first or "\\" in first:
        p = (where / first).resolve()
        if not p.is_relative_to(where.resolve()) or not p.is_file():
            raise Refused("The way in names a program outside its folder.")
        first = str(p)
    return [first, *argv[1:]]


def _data_dir(where: Path) -> Path:
    """Where a way in keeps what it writes (a cache, a login state): ways-data/<slug>, outside the folder that
    is fingerprinted."""
    d = where.parent.parent / "ways-data" / where.name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env(where: Path) -> dict:
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER") if k in os.environ}
    keep.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")
    return {**keep, "ORCH_PERSONAL_WAY": str(where), "ORCH_PERSONAL_WAY_DATA": str(_data_dir(where))}


def _group_kw() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(p: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, check=False)
        return
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(p.pid, signal.SIGKILL)


def run_command(argv: list[str], where: Path, stdin: dict, timeout: float | None = None) -> tuple[int, bytes]:
    """Run one listed command (no shell), values as JSON on stdin. Returns (exit code, stdout up to MAX_OUT + 1
    bytes). Over time or over size the whole process group is stopped (exit code -1 / -2)."""
    timeout = TIMEOUT if timeout is None else timeout
    p = subprocess.Popen(
        _resolve(argv, where),
        cwd=where,
        env=_env(where),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_group_kw(),
    )
    buf, over = bytearray(), threading.Event()

    def read_out():
        while chunk := p.stdout.read(8192):
            if len(buf) <= MAX_OUT:
                buf.extend(chunk[: MAX_OUT + 1 - len(buf)])
            if len(buf) > MAX_OUT:
                over.set()
                _kill_tree(p)
                return

    def drain_err():
        while p.stderr.read(8192):
            pass

    def feed():  # own thread: a command that never reads its input cannot hold up the time limit
        with contextlib.suppress(BrokenPipeError, OSError, ValueError):
            p.stdin.write(json.dumps(stdin).encode("utf-8"))
            p.stdin.close()

    threads = [threading.Thread(target=f, daemon=True) for f in (read_out, drain_err, feed)]
    for t in threads:
        t.start()
    try:
        code = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        p.wait()
        return -1, bytes(buf)
    threads[0].join(2)
    _kill_tree(p)  # children left behind by the command
    return (-2 if over.is_set() else code), bytes(buf)


def _secret(root: Path, text: str) -> bool:
    try:
        from orch import secretscan
    except ImportError:
        return True  # cannot check: give nothing
    return bool(secretscan.find(text, root))


def _text(root: Path, code: int, raw: bytes, name: str) -> str:
    """Text only, size, secrets: a refusal is one plain sentence."""
    if code == -1:
        raise Refused(f"{name} took longer than {TIMEOUT} seconds and was stopped.")
    if code == -2 or len(raw) > MAX_OUT:
        raise Refused(f"{name} gave more than 64 KB of text; helpers got none of it.")
    if code != 0:
        raise Refused(f"{name} did not work (it ended with code {code}).")
    try:
        text = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        text = "\x00"
    if "\x00" in text:
        raise Refused(f"{name} gave something that is not text; helpers get text only.")
    if _secret(root, text):
        raise Refused(SECRET_REFUSED)
    return text


def ask(root: Path, slug: str, action: str, values: dict | None = None) -> dict:
    """A helper asks a way in that is on: one listed action, text back."""
    w = _get(root, slug)
    if not saved(root).get(slug, {}).get("on"):
        raise Refused(f"{w['name']} is off. Only the person turns it on: orch personal ways on {slug}")
    if _changed(slug, w, saved(root).get(slug, {})):
        raise Refused(f"{w['name']}: {CHANGED} Only the person does that: orch personal ways on {slug}")
    argv = w["actions"].get(action)
    if not argv:
        listed = ", ".join(sorted(w["actions"])) or "none"
        raise Refused(f"{w['name']} has no action {action}. It has: {listed}.")
    values = values or {}
    if not isinstance(values, dict) or len(json.dumps(values)) > MAX_IN:
        raise Refused("The values must be one JSON object of at most 16 KB.")
    try:
        code, raw = run_command(argv, w["dir"], {"action": action, "values": values})
    except OSError:
        code, raw = 127, b""
    try:
        text = _text(root, code, raw, w["name"])
    except Refused as e:
        # A failed or timed-out script means the way in stopped; a rule refusal (too big, not text, a secret)
        # means the source answered and the way in itself still works.
        if code not in (0, -2):
            _update(root, slug, status="stopped", problem=str(e), checked=store.now())
        raise
    _update(root, slug, status="works", problem=None, last_worked=store.now())
    return {"way": slug, "name": w["name"], "action": action, "text": text}


def check(root: Path, slug: str) -> dict:
    """Run one way in's self-check now (Try again, or the daily look) and save what came out."""
    w = _get(root, slug)
    s = saved(root).get(slug, {})
    if not s.get("on") or _changed(slug, w, s):  # a changed way in runs nothing until it is turned on again
        return next(r for r in status(root) if r["way"] == slug)
    fields: dict = {"checked": store.now()}
    if not w["selfcheck"]:
        fields.update(status="works", problem=None, last_worked=fields["checked"])
    else:
        try:
            code, raw = run_command(w["selfcheck"], w["dir"], {"action": "selfcheck", "values": {}})
        except (Refused, OSError) as e:
            code, raw = 127, str(e).encode()
        if code == 0:
            fields.update(status="works", problem=None, last_worked=fields["checked"])
        else:
            first = next((x for x in raw.decode("utf-8", "replace").splitlines() if x.strip()), "")
            first = "" if not first or _secret(root, first) else _clean(first, 200)
            if code == NEEDS_PERMISSION:
                fields.update(status="permission", problem=first or "It asks you to allow access once.")
            else:
                why = "took too long" if code == -1 else "its self-check failed"
                fields.update(status="stopped", problem=first or f"The way in stopped working: {why}.")
    _update(root, slug, **fields)
    return next(r for r in status(root) if r["way"] == slug)


def check_due(root: Path, every: float = CHECK_EVERY) -> list[str]:
    """The daily self-check: every way in that is on and was not checked in the last day."""
    st, done = saved(root), []
    limit = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - every))
    for slug in found(root):
        s = st.get(slug, {})
        if s.get("on") and str(s.get("checked") or "") < limit:
            check(root, slug)
            done.append(slug)
    return done


def daily(root: Path, stop: threading.Event, every: float = 3600) -> threading.Thread:
    """Look once an hour (in the Personal page server) for ways in whose daily check is due."""

    def loop():
        while not stop.is_set():
            with contextlib.suppress(Exception):  # a broken way.toml must not end the page server
                check_due(root)
            stop.wait(every)

    t = threading.Thread(target=loop, name="personal-ways-daily", daemon=True)
    t.start()
    return t
