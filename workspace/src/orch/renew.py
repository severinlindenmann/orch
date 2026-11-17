"""Renew a tool login or replace a key from the warning (ORCH-46), so waiting helpers can go on.

A tool login: orch starts the tool's OWN sign-in step (adapter `login.renew`, agents/login.json) in a
small background worker and hands the person exactly one thing from what the tool prints: the sign-in
link, and only when it starts with one of the adapter's `login.links`. When the sign-in page shows a
code, the person pastes it; orch passes it straight to the tool's input and keeps nothing (the code file
lives under a second and is removed before it is used). When the tool ends, orch checks every login
again (health.check): the warning goes away by itself, and the tickets that wait only for this login go on.

A key: the person puts the new value in through the existing safe way (keystore.add, the same as
`orch secret add`, value on stdin). It is never printed, logged or shown again. Then the same re-check.

    <run dir>/renew/<name>/state.json  {schema, name, state, link?, started_at, beat_at, ends_at?, went_on?}
    <run dir>/renew/<name>/code        0600, at most a second: the pasted code on its way to the tool
    <run dir>/renew/<name>/stop        the person pressed Close: the worker ends the tool

States: starting | link (the link is ready; again=true when the tool did not take the last code and waits for
it once more) | checking (a code went in) | done | failed | stopped.
Nothing else the tool prints is kept, shown or logged (R5.2).
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import adapters, health, net, runs, tickets
from orch.errors import Refused

SCHEMA = "orch.renew/1"
FINAL = ("done", "failed", "stopped")
LIMIT = 15 * 60  # seconds a sign-in may take before the worker ends the tool
BEAT = 10  # seconds without a heartbeat: the worker is gone
ASKS_AGAIN = 2.0  # quiet seconds after the tool answered a code and still runs: it asks for the code again
_LINK = re.compile(r"https://[^\s\"'<>\x00-\x1f\x7f]{1,2000}")
_CODE = re.compile(r"[A-Za-z0-9#_.~+/=-]{4,512}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")
_BUF = 16384  # bytes of the tool's output looked at for the link; the rest is dropped unread
BY = "orch"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir(root: Path, name: str) -> Path:
    if not _NAME.fullmatch(name or ""):
        raise Refused("That is not the name of a login orch checks here.")
    return runs.run_dir(Path(root)) / "renew" / name


def _write(root: Path, name: str, doc: dict) -> dict:
    d = _dir(root, name)
    d.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    doc = {"schema": SCHEMA, "name": name, **doc}
    net.write_json(d / "state.json", doc)
    with contextlib.suppress(OSError):
        os.chmod(d / "state.json", 0o600)
    return doc


def _read(root: Path, name: str) -> dict | None:
    doc = net.read_json(_dir(root, name) / "state.json", None)
    return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else None


def _age(iso: str | None) -> float:
    try:
        return time.time() - datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return float("inf")


def _alive(doc: dict | None) -> bool:
    return bool(doc) and doc.get("state") not in FINAL and _age(doc.get("beat_at")) < BEAT


# ---------------------------------------------------------------------------------------- what can renew


def spec(root: Path, name: str) -> dict | None:
    """{binary, argv, links, helper, label} for a helper tool whose sign-in orch can start, else None."""
    if name not in adapters.builtin_names():
        return None
    a = adapters.load(name, root)
    login, binary = a.get("login") or {}, (a.get("detect") or {}).get("binary")
    renew, links = login.get("renew"), login.get("links")
    if not (binary and isinstance(renew, list) and renew and isinstance(links, list) and links):
        return None
    return {"binary": binary, "argv": [binary, *renew], "links": links, "helper": name, "label": a["label"]}


def link_in(text: str, links: list[str]) -> str | None:
    """The first https link in the tool's output that starts with an allowed prefix, else None."""
    for m in _LINK.finditer(text):
        url = m.group(0).rstrip(".,;)")
        if any(url.startswith(p) for p in links):
            return url
    return None


# ------------------------------------------------------------------------------------- the person's side


def status(root: Path, name: str) -> dict:
    """The renew state for the page: {name, state, link?, ends_at?, went_on?}. A worker that stopped beating
    before it finished reads as failed."""
    doc = _read(root, name)
    if not doc:
        return {"name": name, "state": "none"}
    if doc.get("state") not in FINAL and not _alive(doc) and _age(doc.get("started_at")) > BEAT:
        doc = {**doc, "state": "failed"}
    return {k: doc[k] for k in ("name", "state", "link", "again", "ends_at", "went_on") if k in doc}


def start(root: Path, name: str) -> dict:
    """Start the tool's own sign-in in a background worker (one per login). A sign-in still running from an
    earlier Renew is ended first."""
    s = spec(root, name)
    if not s:
        raise Refused("orch cannot start this sign-in. Sign in again with the tool itself, then check again.")
    if not shutil.which(s["binary"]):
        raise Refused(f"{s['label']} is not installed on this computer.")
    d = _dir(root, name)
    if _alive(
        _read(root, name)
    ):  # Renew again: the person wants a fresh sign-in (an old code fits only the old one)
        (d / "stop").touch()
        end = time.time() + 5
        while time.time() < end and _alive(_read(root, name)):
            time.sleep(0.2)
    for f in ("code", "stop"):
        with contextlib.suppress(OSError):
            (d / f).unlink()
    _write(root, name, {"state": "starting", "started_at": _now(), "beat_at": _now()})
    from orch import procs

    subprocess.Popen(
        procs.orch_python_argv("logins", "renew", name, "--worker"),
        cwd=Path(os.path.realpath(tempfile.gettempdir())),
        env={**os.environ, "ORCH_ROOT": str(root)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **procs.background_popen_kwargs(),
    )
    return status(root, name)


def code(root: Path, name: str, text: str) -> dict:
    """Pass the code the sign-in page shows to the waiting tool. Kept nowhere: the worker removes the file
    before it writes the code to the tool's input."""
    text = (text or "").strip()
    if not _CODE.fullmatch(text):
        raise Refused("That does not look like the code from the sign-in page. Copy it again and paste it.")
    doc = _read(root, name)
    if not _alive(doc):
        raise Refused("The sign-in is no longer waiting. Press Renew again.")
    d = _dir(root, name)
    tmp = d / f".code-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, d / "code")
    return status(root, name)


def cancel(root: Path, name: str) -> dict:
    """The person closed the window: the worker ends the tool."""
    doc = _read(root, name)
    if _alive(doc):
        (_dir(root, name) / "stop").touch()
    return status(root, name)


def replace_key(root: Path, name: str, value: str) -> dict:
    """Put a new value in for the key a check names (the existing safe way: keystore.add, as
    `orch secret add`), then check again. The value is never printed, logged or kept anywhere else."""
    from orch import keystore

    row = next((r for r in (health.last(root) or {}).get("items") or [] if r.get("name") == name), None)
    if not row:
        row = next((r for r in health.workspace_recipes(root) if r["name"] == name), None)
    key = (row or {}).get("key")
    if not key:
        raise Refused("This check names no key to replace.")
    old = next((k for k in keystore.list_keys(root) if k.get("name") == key), None)
    kind = (old or {}).get("type") or "token"
    if kind == "key-file":
        raise Refused("This key is a file. Replace it with orch secret add on this computer.")
    keystore.add(root, key, kind, value)
    return after(root, name)


# ----------------------------------------------------------------------------------------- after a renew


def after(root: Path, name: str) -> dict:
    """Check every login again (the warning goes away by itself) and, when this one works now, let the
    tickets that wait only for it go on. {state, ends_at, went_on}."""
    doc = health.check(root)
    row = next((r for r in doc["items"] if r.get("name") == name), None)
    st = (row or {}).get("state")
    went: list[str] = []
    if st in ("works", "soon"):
        went = go_on(root, (row or {}).get("helper"))
    return {"state": st or "unreachable", "ends_at": (row or {}).get("ends_at"), "went_on": went}


def _waits_for_login(t: dict) -> bool:
    w = t.get("waiting_on") or {}
    return (
        t.get("status") == "waiting" and w.get("start") is True and "login" in str(w.get("ref") or "").lower()
    )


def go_on(root: Path, helper: str | None) -> list[str]:
    """Tickets that wait only because this tool's login stopped (a start that failed for no login, or a live
    session that shows the tool's login screen): end what is left of the run and start it again, continuing
    the conversation. Returns the ticket keys. Never raises; a ticket that cannot start says so itself."""
    if not helper:
        return []
    from orch import runs_live

    went = []
    for t in tickets.list_all(root):
        try:
            if not _waits_for_login(t):
                continue
            tid = t["id"]
            rec = runs.read(root, tid)
            agent = (rec or {}).get("agent") or adapters.chosen(root)
            if adapters.load(str(agent), root)["adapter"] != helper:
                continue
            if rec:
                runs_live.stop(root, tid)  # the login screen in the old session does not go away by itself
            runs.start(root, tid, runs_live.AUTOMATION_BY)
            tickets.log(root, tid, "The login works again, so the helper goes on.", BY)
            went.append(t.get("key") or tid)
        except Exception:  # noqa: BLE001  one ticket never holds up the others
            continue
    return went


# -------------------------------------------------------------------------------------------- the worker


def work(root: Path, name: str) -> int:
    """`orch logins renew <name> --worker`: run the tool's sign-in, pass on the link and the code, end with a
    re-check. Writes only the few facts above."""
    s = spec(root, name)
    binary = shutil.which(s["binary"]) if s else None
    started = _now()
    if not binary:
        _write(root, name, {"state": "failed", "started_at": started, "beat_at": _now()})
        return 1
    d = _dir(root, name)
    try:
        proc = subprocess.Popen(
            [binary, *s["argv"][1:]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=Path(os.path.realpath(tempfile.gettempdir())),
        )
    except OSError:
        _write(root, name, {"state": "failed", "started_at": started, "beat_at": _now()})
        return 1
    found: dict = {"n": 0, "at": 0.0}  # how many bytes the tool printed and when it last did (never the text)
    buf = bytearray()

    def read() -> None:
        # the tool's output is looked at for the link only, in memory, and never written anywhere
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                return
            found["n"], found["at"] = found["n"] + len(chunk), time.time()
            if "link" not in found and len(buf) < _BUF:
                buf.extend(chunk[: _BUF - len(buf)])
                url = link_in(buf.decode("utf-8", "replace"), s["links"])
                if url:
                    found["link"] = url

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    state, end, sent, again = "starting", time.time() + LIMIT, None, False
    while proc.poll() is None:
        if (d / "stop").exists() or time.time() > end:
            proc.kill()
            proc.wait()
            with contextlib.suppress(OSError):
                (d / "stop").unlink()
            _write(root, name, {"state": "stopped", "started_at": started, "beat_at": _now()})
            return 1
        if state == "starting" and "link" in found:
            state = "link"
        quiet = time.time() - found["at"] > ASKS_AGAIN
        if state == "checking" and sent is not None and found["n"] > sent and quiet:
            state, sent, again = "link", None, True  # the tool answered and still waits: it wants the code
        cf = d / "code"
        if cf.exists():
            try:
                text = cf.read_bytes()[:600]
            finally:
                with contextlib.suppress(OSError):
                    cf.unlink()
            with contextlib.suppress(OSError, ValueError):
                sent = found["n"]
                proc.stdin.write(text.strip() + b"\n")
                proc.stdin.flush()
                state, again = "checking", False
        doc = {"state": state, "started_at": started, "beat_at": _now()}
        if "link" in found:
            doc["link"] = found["link"]
        if again:
            doc["again"] = True  # the last code was not taken: the window asks for it once more
        _write(root, name, doc)
        time.sleep(0.4)
    reader.join(timeout=2)
    _write(root, name, {"state": "checking", "started_at": started, "beat_at": _now()})
    res = after(root, name) if proc.returncode == 0 else {"state": "renew"}
    ok = res["state"] in ("works", "soon")
    final = {"state": "done" if ok else "failed", "started_at": started, "beat_at": _now()}
    if ok:
        final["ends_at"] = res.get("ends_at")
        final["went_on"] = res.get("went_on") or []
    _write(root, name, final)
    return 0 if ok else 1
