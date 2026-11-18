"""The small orch app on the person's notebook (contracts/relay-api.md Notebook; Mac first).

It holds the one private connection of one workspace to this notebook over the relay. The admin adds the
notebook on
the relay admin page; the line shown there (`orch notebook connect <relay url> <code>`) is the only way to
connect.
What the workspace's helpers ask waits in the relay while the notebook sleeps; `run` fetches them, runs the
person's own scripts ("ways in") and sends back text only.

Home (ORCH_NOTEBOOK_HOME, else ~/Library/Application Support/orch-notebook on a Mac, ~/.orch-notebook
elsewhere):
  connection.json  url, notebook id, token (0600, folder 0700)
  ways/<slug>/way.toml   name, [actions] <action> = [argv...], selfcheck = [argv...]
  skills/          the person's own skill files the scripts use
  done/<ask>.json  the reply sent for a request (sent again on a repeat; kept 7 days)
  running/<ask>    a request being worked on (a crash leaves it: answered "not sure it finished")
  state.json       last self-check per way in

A way in is the person's own program and runs as them; "text only" is what crosses the connection, not a
sandbox.
The app only runs commands listed in way.toml, never through a shell; the request's values arrive as JSON on
stdin.
"""

from __future__ import annotations

import calendar
import contextlib
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
from pathlib import Path

from orch import net, secretscan
from orch.errors import Refused
from orch.text import clean_untrusted

APP_VERSION = "0.1.0"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
MAX_OUT = 65536
TIMEOUT = 60
CHECK_EVERY = 24 * 3600
DONE_KEEP = 7 * 24 * 3600
LABEL = "io.orch.notebook"
BUILTIN = "notebook"
SECRET_REFUSED = "The answer looks like it holds a password or key, so the notebook did not send it."
NOT_SURE = "The notebook stopped while working on this; not sure it finished. Ask again."


def home() -> Path:
    env = os.environ.get("ORCH_NOTEBOOK_HOME")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "orch-notebook"
    return Path.home() / ".orch-notebook"


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


def _parse(s) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, OverflowError):
        return None


def _new_id() -> str:
    import secrets

    return "m_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))


def _private_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o700)
    return p


# ---- connection --------------------------------------------------------------------------------------------


def _check_url(url: str) -> str:
    u = urllib.parse.urlsplit(url.strip())
    loopback = u.hostname in ("127.0.0.1", "localhost", "::1")
    if u.scheme != "https" and not (u.scheme == "http" and loopback):
        raise Refused(
            "The relay address starts with https://. Copy the whole line from the relay admin page."
        )
    if u.username or u.password or u.query or u.fragment:
        raise Refused("Copy the relay address exactly as the relay admin page shows it.")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def connection(h: Path | None = None) -> dict:
    c = net.read_json((h or home()) / "connection.json", None)
    if not isinstance(c, dict) or not {"url", "notebook", "token"} <= c.keys():
        raise Refused("This notebook is not connected. Run the line from the relay admin page (Notebooks).")
    return c


def _write_private(path: Path, obj: dict) -> None:
    """Write a file only this user can read (made 0600 before any byte is in it), atomically."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def connect(url: str, code: str, h: Path | None = None) -> dict:
    h = _private_dir(h or home())
    url = _check_url(url)
    if not re.fullmatch(r"nc_[A-Za-z0-9_-]{10,60}", code.strip()):
        raise Refused("That is not a notebook code. Copy the whole line from the relay admin page.")
    name = clean_untrusted(socket.gethostname().split(".")[0], 60) or "Notebook"
    _, r = net.call_json("POST", url + "/v1/notebook/pair", {}, {"code": code.strip(), "name": name}, 30)
    if not isinstance(r, dict) or not re.fullmatch(r"nb_[a-z0-9]{10}", str(r.get("notebook_id"))):
        raise Refused(
            "The relay gave an unexpected answer. Make a new line on the relay admin page and try again."
        )
    ws = r.get("workspace") if isinstance(r.get("workspace"), dict) else {}
    conn = {"url": url, "notebook": r["notebook_id"], "token": r["token"], "workspace": ws.get("name", "")}
    _write_private(h / "connection.json", conn)
    for d in ("ways", "skills", "done", "running"):
        _private_dir(h / d)
    return {k: v for k, v in conn.items() if k != "token"}


def _call(conn: dict, method: str, path: str, body=None, timeout: float = 40):
    headers = {"X-Orch-Notebook": conn["notebook"], "Authorization": f"Bearer {conn['token']}"}
    return net.call_json(method, conn["url"] + path, headers, body, timeout)


# ---- ways in -----------------------------------------------------------------------------------------------


def ways(h: Path | None = None) -> dict[str, dict]:
    """{slug: {name, actions: {name: argv}, selfcheck: argv|None, dir}} for every valid
    ways/<slug>/way.toml."""
    out = {}
    root = (h or home()) / "ways"
    for d in sorted(root.glob("*")) if root.is_dir() else []:
        if not d.is_dir() or not SLUG.fullmatch(d.name) or d.name == BUILTIN or d.is_symlink():
            continue
        try:
            cfg = tomllib.loads((d / "way.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        acts = cfg.get("actions") if isinstance(cfg.get("actions"), dict) else {}
        good = {a: v for a, v in acts.items() if SLUG.fullmatch(a) and _argv_ok(v)}
        sc = cfg.get("selfcheck")
        out[d.name] = {
            "name": clean_untrusted(str(cfg.get("name") or d.name), 80),
            "actions": good,
            "selfcheck": sc if _argv_ok(sc) else None,
            "dir": d,
        }
    return out


def _argv_ok(v) -> bool:
    return (
        isinstance(v, list)
        and 0 < len(v) <= 32
        and all(isinstance(x, str) and x and "\x00" not in x for x in v)
    )


def _resolve(argv: list[str], folder: Path) -> list[str]:
    """A relative command word naming a file (./x or x/y) must stay inside the way's folder; a bare word is a
    program
    on PATH (python3, osascript...); a full path (/usr/bin/python3) is the person's own choice in way.toml."""
    first = argv[0]
    if Path(first).is_absolute():
        return list(argv)
    if "/" in first or "\\" in first:
        p = (folder / first).resolve()
        if not p.is_relative_to(folder.resolve()) or not p.is_file():
            raise Refused("The way in names a program outside its folder.")
        first = str(p)
    return [first, *argv[1:]]


def _env(h: Path) -> dict:
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER") if k in os.environ}
    keep.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")
    return {**keep, "ORCH_NOTEBOOK_SKILLS": str(h / "skills")}


def _group_kw() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(p: subprocess.Popen) -> None:
    """Stop the command and everything it started (its process group; on Windows its process tree)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        return
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(p.pid, signal.SIGKILL)


@contextlib.contextmanager
def runner_lock(h: Path):
    """Only one app answers requests per notebook home (a second `run` is refused), so a request is never run
    twice and a request marked running really means the app stopped while working on it."""
    _private_dir(h)
    f = open(h / "run.lock", "a+")
    try:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Refused(
                "The notebook app already runs. Stop the other one first: orch notebook stop"
            ) from None
        yield
    finally:
        f.close()


def run_command(
    argv: list[str], folder: Path, stdin: dict, h: Path, timeout: float = TIMEOUT
) -> tuple[int, bytes]:
    """Run one listed command (no shell), args as JSON on stdin. Returns (exit code, stdout up to MAX_OUT + 1
    bytes).
    Over time or over size: the whole process group is stopped (exit code -1 / -2)."""
    p = subprocess.Popen(
        _resolve(argv, folder),
        cwd=folder,
        env=_env(h),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_group_kw(),
    )
    buf, over = bytearray(), threading.Event()

    def kill():
        _kill_tree(p)

    def read_out():
        while chunk := p.stdout.read(8192):
            if len(buf) <= MAX_OUT:
                buf.extend(chunk[: MAX_OUT + 1 - len(buf)])
            if len(buf) > MAX_OUT:
                over.set()
                kill()
                return

    def drain_err():
        while p.stderr.read(8192):
            pass

    def feed():  # in its own thread: a command that never reads its input cannot hold up the time limit
        with contextlib.suppress(BrokenPipeError, OSError, ValueError):
            p.stdin.write(json.dumps(stdin).encode("utf-8"))
            p.stdin.close()

    threads = [threading.Thread(target=f, daemon=True) for f in (read_out, drain_err, feed)]
    t1 = threads[0]
    for t in threads:
        t.start()
    try:
        code = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill()
        p.wait()
        return -1, bytes(buf)
    t1.join(2)
    kill()  # children left behind by the command
    return (-2 if over.is_set() else code), bytes(buf)


def _text_reply(code: int, raw: bytes, name: str) -> dict:
    """The rules on the notebook: text only, size, secrets."""
    if code == -1:
        return {"ok": False, "refused": f"{name} took longer than {TIMEOUT} seconds and was stopped."}
    if code == -2 or len(raw) > MAX_OUT:
        return {"ok": False, "refused": f"{name} gave more than 64 KB of text; the notebook sent none of it."}
    if code != 0:
        return {"ok": False, "refused": f"{name} did not work (it ended with code {code})."}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False,
            "refused": f"{name} gave something that is not text; the notebook sends text only.",
        }
    if "\x00" in text:
        return {
            "ok": False,
            "refused": f"{name} gave something that is not text; the notebook sends text only.",
        }
    if secretscan.find(text, None, strict=False):
        return {"ok": False, "refused": SECRET_REFUSED}
    return {"ok": True, "text": text}


def self_check(h: Path | None = None) -> list[dict]:
    """Run every way in's self-check now; saved in state.json. The app itself counts as a way in that
    works."""
    h = h or home()
    res = [{"way": BUILTIN, "name": "Notebook", "ok": True, "checked_at": _iso()}]
    for slug, w in ways(h).items():
        row = {"way": slug, "name": w["name"], "checked_at": _iso()}
        if not w["selfcheck"]:
            row.update(ok=True)
        else:
            try:
                code, raw = run_command(w["selfcheck"], w["dir"], {}, h)
            except (Refused, OSError) as e:
                code, raw = 1, str(e).encode()
            row["ok"] = code == 0
            if code != 0:
                first = next((x for x in raw.decode("utf-8", "replace").splitlines() if x.strip()), "")
                bad = secretscan.find(first, None, strict=False)
                row["problem"] = (
                    clean_untrusted(first, 300) if first and not bad else "Its self-check failed."
                )
        res.append(row)
    st = _state(h)
    st["checked_at"] = _iso()
    st["ways"] = res
    net.write_json(h / "state.json", st)
    return res


def _state(h: Path) -> dict:
    s = net.read_json(h / "state.json", {})
    return s if isinstance(s, dict) else {}


def send_status(conn: dict, h: Path, res: list[dict] | None = None) -> None:
    res = res if res is not None else _state(h).get("ways") or self_check(h)
    _call(
        conn,
        "POST",
        "/v1/notebook/send",
        {"id": _new_id(), "notebook": {"kind": "status", "app_version": APP_VERSION, "ways": res[:50]}},
    )


def answer(ask: dict, conn: dict, h: Path) -> dict:
    """The reply body for one ask (the rules on the notebook decide what may be sent)."""
    nb = ask.get("body", {}).get("notebook", {})
    way, action, args = nb.get("way"), nb.get("action"), nb.get("args") or {}
    if (_parse(nb.get("expires_at")) or 0) <= time.time():
        return {"ok": False, "refused": "This request expired before the notebook woke up."}
    if way == BUILTIN:
        if action == "ping":
            return {
                "ok": True,
                "text": f"Notebook here (orch notebook {APP_VERSION}, {len(ways(h))} ways in).",
            }
        if action == "check":
            res = self_check(h)
            with contextlib.suppress(Refused):
                send_status(conn, h, res)
            bad = [r["name"] for r in res if not r["ok"]]
            return {
                "ok": True,
                "text": "Every way in works." if not bad else f"Stopped working: {', '.join(bad)}.",
            }
        return {"ok": False, "refused": "The notebook app knows only ping and check."}
    w = ways(h).get(str(way))
    if not w:
        return {"ok": False, "refused": f"The notebook has no way in called {clean_untrusted(str(way), 40)}."}
    argv = w["actions"].get(str(action))
    if not argv:
        return {
            "ok": False,
            "refused": f"{w['name']} on the notebook does not offer {clean_untrusted(str(action), 40)}.",
        }
    try:
        code, raw = run_command(argv, w["dir"], {"action": action, "args": args}, h)
    except (Refused, OSError):
        return {"ok": False, "refused": f"{w['name']} could not be started on the notebook."}
    return _text_reply(code, raw, w["name"])


def handle(ask: dict, conn: dict, h: Path) -> None:
    """One request: at least once from the relay, run at most once here. Reply first, ack after the relay
    took it."""
    aid = str(ask.get("id", ""))
    if not re.fullmatch(r"m_[a-z0-9]{16}", aid):
        return
    done, running = h / "done" / f"{aid}.json", h / "running" / aid
    rec = net.read_json(done, None)
    if not isinstance(rec, dict):
        if running.exists():
            rec = {"id": _new_id(), "reply": {"ok": False, "refused": NOT_SURE}}
        else:
            _private_dir(running.parent)
            running.write_text(_iso(), encoding="utf-8")
            rec = {"id": _new_id(), "reply": answer(ask, conn, h)}
        net.write_json(done, rec)
        running.unlink(missing_ok=True)
    try:
        _call(
            conn,
            "POST",
            "/v1/notebook/send",
            {"id": rec["id"], "reply_to": aid, "notebook": {"kind": "reply", **rec["reply"]}},
        )
    except Refused as e:
        if getattr(e, "status", None) not in (409,):  # 409: answered before; anything else: try again later
            raise
    _call(conn, "POST", "/v1/notebook/ack", {"ids": [aid]})


def _tidy(h: Path) -> None:
    cut = time.time() - DONE_KEEP
    for f in (h / "done").glob("m_*.json"):
        with contextlib.suppress(OSError):
            if f.stat().st_mtime < cut:
                f.unlink()


def once(h: Path | None = None, wait: int = 30) -> int:
    """One round: fetch waiting requests (long-poll up to `wait`), answer each. Returns how many were
    handled."""
    h = h or home()
    conn = connection(h)
    st = _state(h)
    if (_parse(st.get("checked_at")) or 0) + CHECK_EVERY <= time.time():
        send_status(conn, h, self_check(h))
    _, r = _call(conn, "GET", f"/v1/notebook/requests?wait={max(0, min(30, wait))}", timeout=wait + 30)
    items = [x for x in net.items(r) if isinstance(x, dict)]
    for ask in items:
        handle(ask, conn, h)
    return len(items)


def run(h: Path | None = None, stop: threading.Event | None = None) -> None:
    """The loop the background service runs: wait for requests, answer, repeat; back off when the relay is
    away."""
    h = h or home()
    with runner_lock(h):
        _loop(h, stop)


def _loop(h: Path, stop: threading.Event | None) -> None:
    conn = connection(h)
    with contextlib.suppress(Refused, OSError):
        send_status(conn, h, self_check(h))
    pause = 5
    while not (stop and stop.is_set()):
        try:
            once(h)
            pause = 5
            _tidy(h)
        except Refused as e:
            if getattr(e, "status", None) == 401:
                print(
                    "The relay no longer knows this notebook. Connect it again from the relay admin page.",
                    file=sys.stderr,
                )
                return
            time.sleep(pause)
            pause = min(60, pause * 2)


# ---- background service (macOS launchd) --------------------------------------------------------------------


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def service_running() -> bool:
    if sys.platform != "darwin":
        return False
    r = subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True)
    return r.returncode == 0


def start() -> str:
    if sys.platform != "darwin":
        raise Refused(
            "Starting in the background works on a Mac for now. Run `orch notebook run` in a terminal."
        )
    connection()
    import plistlib

    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    log = _private_dir(home() / "log")
    data = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "orch", "notebook", "run", "--service"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log / "notebook.log"),
        "StandardErrorPath": str(log / "notebook.log"),
        "EnvironmentVariables": {"ORCH_NOTEBOOK_HOME": str(home())},
    }
    p.write_bytes(plistlib.dumps(data))
    if service_running():
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", _domain(), str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused(
            "The notebook app could not start in the background. Run `orch notebook run` to see why."
        )
    return "The notebook app runs in the background and starts again when you log in."


def stop() -> str:
    if service_running():
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True)
    _plist_path().unlink(missing_ok=True)
    return "The notebook app stopped. What helpers ask waits in the relay until you start it again."


def status(h: Path | None = None) -> dict:
    h = h or home()
    try:
        c = connection(h)
        conn = {"connected": True, "workspace": c.get("workspace"), "relay": c["url"]}
    except Refused:
        conn = {"connected": False}
    st = _state(h)
    return {
        **conn,
        "running": service_running(),
        "checked_at": st.get("checked_at"),
        "ways": st.get("ways") or [],
        "found": sorted(ways(h)),
        "home": str(h),
        "system": platform.system(),
    }
