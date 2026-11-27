"""`orch start | stop | status`: background processes of active add-ons (contracts/addon-manifest.md).

The core knows no add-on by name. An active add-on with `background = true` implements `start --json`,
`stop --json` and `status --json`; `orch start` calls `start` on each, `orch stop` calls `stop`. What runs
where is kept in the user's orch folder (`running.json`: workspace, name, add-on, pid, url); dead pids are
dropped on read.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, launchenv, skills
from orch.errors import Refused

_local = threading.local()  # lock depth per thread: reentrant inside one thread only


@contextlib.contextmanager
def locked(timeout: float = 180.0):
    """One lock (ORCH_HOME/services.lock) around every start, stop and restart, so two orch processes never
    interleave their read-modify-write of running.json or stop what the other just started. Reentrant in this
    process. Gives up after `timeout` seconds with a clear message (the lock dies with its process)."""
    if getattr(_local, "depth", 0):
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    path = addons.home() / "services.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        end = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > end:
                    raise Refused(
                        "Another orch start or stop is still running. Try again in a minute."
                    ) from None
                time.sleep(0.2)
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0
            if os.name == "nt":
                import msvcrt

                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass  # closing the file releases it; never mask the original exception
            # POSIX: closing the file releases the flock


def running_path() -> Path:
    return addons.home() / "running.json"


def pid_alive(pid: int) -> bool:
    """True when pid > 1 names a running process. Never signals: 0, 1 and negatives are refused."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    if (
        os.name == "nt"
    ):  # os.kill(pid, 0) would end the process on Windows; exit code 259 is not proof of life
        import ctypes

        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        k.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        k.WaitForSingleObject.restype = ctypes.c_ulong
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


URL_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):[0-9]{1,5}(/[!-~]*)?$")


def local_url(u: object) -> str | None:
    """Only a link to this computer (http://127.0.0.1:<port> or localhost) is printed or opened."""
    return u if isinstance(u, str) and len(u) <= 200 and URL_RE.match(u) else None


def _load() -> list[dict]:
    try:
        data = json.loads(running_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        e
        for e in data
        if isinstance(e, dict)
        and isinstance(e.get("workspace"), str)
        and isinstance(e.get("addon"), str)
        and isinstance(e.get("pid"), int)
        and (e.get("url") is None or local_url(e["url"]))
    ]


def _save(entries: list[dict]) -> None:
    p = running_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def running() -> list[dict]:
    """What runs now, by workspace: entries whose pid is gone are dropped (and the file is rewritten)."""
    entries = _load()
    alive = [e for e in entries if pid_alive(e["pid"])]
    if len(alive) != len(entries):
        _save(alive)
    return alive


def _ports_path() -> Path:
    return running_path().parent / "ports.json"


def _port_key(root: Path, name: str) -> str:
    return f"{root.resolve()}\t{name}"


def last_port(root: Path, name: str) -> int | None:
    """The port this workspace's add-on had when it last ran (kept across stop/start and updates), or None."""
    try:
        data = json.loads(_ports_path().read_text(encoding="utf-8"))
        v = data.get(_port_key(root, name)) if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
    return v if isinstance(v, int) and not isinstance(v, bool) and 1024 <= v < 65536 else None


def _remember_ports(found: dict[str, int], root: Path) -> None:
    """Best effort; a start never fails because this file cannot be written."""
    if not found:
        return
    try:
        try:
            data = json.loads(_ports_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.update({_port_key(root, n): p for n, p in found.items()})
        p = _ports_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except OSError:
        pass


def _url_port(u: object) -> int | None:
    m = re.search(r":(\d{1,5})(?:/|$)", u) if isinstance(u, str) else None
    return int(m.group(1)) if m else None


def _services(root: Path) -> dict[str, dict]:
    """Active add-ons of this workspace that have a background process."""
    return {n: m for n, m in sorted(addons.active_manifests(root).items()) if m["background"]}


def _command_line(pid: int) -> str | None:
    """The command line of a process of THIS user, or None (another user, gone, or it can't be read)."""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                capture_output=True, text=True, timeout=15, check=False, stdin=subprocess.DEVNULL,
            )  # fmt: skip
            return r.stdout.strip() or None  # the process list only shows this user's command lines
        r = subprocess.run(
            ["ps", "-ww", "-o", "uid=,command=", "-p", str(int(pid))],  # -ww: never cut short (Linux)
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    uid, _, cmd = r.stdout.strip().partition(" ")
    return cmd.strip() if uid == str(os.getuid()) and cmd.strip() else None


def _retire(root: Path, stopped: list[str] | None = None) -> list[str]:
    """A process the list of running services names for an add-on of this workspace that no longer runs in the
    background (an update made its page one the dashboard draws, ORCH-816: Focus) keeps the old code running
    and holds its port. The same for an add-on that is still on but whose package is gone (a reinstall that
    could not put it back, ORCH-1878): nothing else can stop it. It is stopped once its own command line shows
    it is that add-on's background process for this folder (`-m orch_<name> --dir <folder> serve|run|watch`),
    then dropped from the list. Lines for what was done; `stopped` gets the add-on names."""
    root = root.resolve()
    keep, lines = _services(root), []
    on = set(addons.active(root))
    entries = running()
    gone: set[int] = set()
    for e in entries:
        if e["workspace"] != str(root) or e["addon"] in keep or not addons.NAME_RE.match(e["addon"]):
            continue
        cmd = _command_line(e["pid"])
        wants = [
            f" -m orch_{e['addon']} --dir {d} {sub}"
            for d in (root, f'"{root}"')  # Windows quotes a path with spaces
            for sub in ("serve", "run", "watch")
        ]
        if not cmd or not any(cmd.endswith(w) or f"{w} " in cmd for w in wants):
            continue  # not verified: never signal a process orch can't name
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(e["pid"]), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                import signal

                os.kill(e["pid"], signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            continue
        for _ in range(30):
            if not pid_alive(e["pid"]):
                break
            time.sleep(0.1)
        else:
            continue  # still there: it stays listed, the next start, stop or update tries again
        gone.add(e["pid"])
        if stopped is not None:
            stopped.append(e["addon"])
        if e["addon"] in on:
            lines.append(
                f"Stopped {e['addon']} in {root.name}: its add-on is not installed. Put it back: orch update"
            )
        else:
            lines.append(
                f"Stopped the old {e['addon']} page of {root.name}: it is now part of the dashboard."
            )
    if gone:
        _save([e for e in _load() if e["pid"] not in gone])
    return lines


def _default_signals() -> None:
    """In the child before exec: the add-on and the daemon it starts get normal SIGHUP/SIGPIPE handling even
    when this process ignores them (an ignored signal is inherited through exec)."""
    import signal

    for sig in ("SIGHUP", "SIGPIPE"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), signal.SIG_DFL)


RESTART_ENV = "ORCH_SERVICE_RESTART"  # set to "1" on the stop of a restart: the add-on comes straight back


def _call(
    root: Path, name: str, m: dict, sub: str, launch: dict[str, str] | None = None, restart: bool = False
) -> dict:
    """`launch`: overrides over the caller's environment (a restart: the system's HOME and ORCH_HOME, see
    launchenv). Nothing recorded is replayed. `restart`: this stop is half of a restart (an add-on was added,
    removed or updated); the add-on may keep what a real stop would end (Focus keeps the runs it started)."""
    base = launchenv.apply(dict(os.environ), launch) if launch else dict(os.environ)
    env = {**base, "ORCH_ADDON": name, "ORCH_ROOT": str(root.resolve()), "ORCH_BIN": addons.orch_bin()}
    env.pop(RESTART_ENV, None)
    if restart and sub == "stop":
        env[RESTART_ENV] = "1"
    env.pop("ORCH_PREFERRED_PORT", None)
    if sub == "start" and (pref := last_port(root, name)):
        env["ORCH_PREFERRED_PORT"] = str(pref)  # sticky ports: the add-on tries this one first
    if sub == "start":
        env = launchenv.with_tmux(
            env
        )  # a short PATH never hides an installed tmux from the service (ORCH-2367)
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-m", m["run"], sub, "--json"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            **({"preexec_fn": _default_signals} if os.name != "nt" else {}),
        )
    except subprocess.TimeoutExpired:
        return {"error": f"'{name} {sub}' did not answer within 60 seconds."}
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    try:
        data = json.loads(lines[-1]) if lines else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if r.returncode != 0 and "error" not in data and sub != "status":
        err = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
        data["error"] = err.removeprefix("Refused: ")
    return data


_BIDI = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _printable(v: object) -> str:
    """Add-on text for the terminal: no control characters (no escape sequences, also C1 ones) and no
    direction overrides, at most 200 characters."""
    return "".join(c for c in str(v) if c.isprintable() and not 0x80 <= ord(c) <= 0x9F and c not in _BIDI)[
        :200
    ]


def _workspace_root(root: Path) -> Path:
    if not (root / ".orch").is_dir():
        raise Refused(
            "No orch workspace here (no .orch/ folder). Go to your workspace folder, or run: orch init"
        )
    return root


def start(
    root: Path,
    only: set[str] | None = None,
    envs: dict[str, dict[str, str]] | None = None,
    retire: bool = True,
) -> list[dict]:
    """envs: per add-on the (validated) recorded launch environment to start it with (a restart).
    retire=False: an additive start (orch Companion) never stops anything, not even a retired add-on's
    process."""
    with locked():
        return _start(root, only, envs or {}, retire)


def _older_files(m: dict, pid: int) -> bool:
    """True when a file of the add-on changed after its running process started (a hand-made fix, a dev copy):
    `orch start` leaves a running add-on as it is, so it still runs the old code (#1391). Compiled caches are
    not its files."""
    from orch import procs

    base, started = m.get("dir"), procs.pid_started(pid)
    if not isinstance(base, Path) or not started:
        return False
    try:
        limit = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return False
    limit += procs.APPROX_SECONDS
    for folder, subs, files in os.walk(base):
        subs[:] = [d for d in subs if d != "__pycache__" and not d.startswith(".")]
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            try:
                if os.stat(os.path.join(folder, f)).st_mtime > limit:
                    return True
            except OSError:
                continue
    return False


def _start(
    root: Path, only: set[str] | None, envs: dict[str, dict[str, str]], retire: bool = True
) -> list[dict]:
    """Start the background process of every active add-on here. One row per add-on."""
    root = _workspace_root(root).resolve()
    skills.ensure_gitignore(root)  # .orch/run/ (runtime files of the add-ons) stays out of git
    if retire:
        _retire(root)
    rows = []
    before = running()
    entries = [
        e for e in before if e["workspace"] != str(root) or (only is not None and e["addon"] not in only)
    ]
    for name, m in _services(root).items():
        if only is not None and name not in only:
            continue
        res = _call(root, name, m, "start", envs.get(name))
        row = {"addon": name, "running": bool(res.get("running")) and "error" not in res}
        if res.get("off") is True and not row["running"]:
            row["idle"] = True  # the add-on is off on purpose (its own setting): not a failure
        if pid_alive(res.get("pid")):
            row["pid"] = res["pid"]
        if local_url(res.get("url")):
            row["url"] = res["url"]
        if "error" in res:
            row["error"] = _printable(res["error"])
        if res.get("warning"):
            row["warning"] = _printable(res["warning"])
        rows.append(row)
        if row["running"] and isinstance(row.get("pid"), int):
            old = next((e for e in before if e["workspace"] == str(root) and e["addon"] == name), None)
            if old and old.get("pid") == row["pid"] and _older_files(m, row["pid"]):
                late = f"{name} runs older files than are installed; {addons.RESTART_BY_HAND} {root}"
                row["warning"] = f"{row['warning']} {late}" if row.get("warning") else late
            if old and old.get("pid") == row["pid"] and old.get("env") and name not in envs:
                launch = launchenv.clean(old["env"])  # already running: its record stays (size-limited)
            else:
                launch = launchenv.capture(launchenv.apply(dict(os.environ), envs.get(name, {})))
            entries.append(
                {
                    "workspace": str(root),
                    "name": root.name,
                    "addon": name,
                    "pid": row["pid"],
                    **({"url": row["url"]} if row.get("url") else {}),
                    "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "env": launch,
                }
            )
    _save(entries)
    _remember_ports(
        {r["addon"]: p for r in rows if r.get("running") and (p := _url_port(r.get("url")))}, root
    )
    workspace_rows(root)  # notes when each was last seen running
    return rows


def stop(root: Path, only: set[str] | None = None, restart: bool = False) -> list[dict]:
    with locked():
        return _stop(root, only, restart)


def _stop(root: Path, only: set[str] | None = None, restart: bool = False) -> list[dict]:
    """Stop every background process of this workspace. An add-on that is no longer on here is not run:
    its process sees that and ends by itself. `restart`: they are started again right after (see _call)."""
    root = root.resolve()
    workspace_rows(root)  # notes that they were running now
    orphans: list[str] = []
    _retire(root, orphans)
    rows = [{"addon": n, "stopped": True} for n in orphans if only is None or n in only]
    for name, m in _services(root).items():
        if only is not None and name not in only:
            continue
        res = _call(root, name, m, "stop", restart=restart)
        row = {"addon": name, "stopped": bool(res.get("stopped"))}
        if "error" in res:
            row["error"] = _printable(res["error"])
        if res.get("warning"):
            row["warning"] = _printable(res["warning"])
        rows.append(row)
    _save(
        [e for e in running() if e["workspace"] != str(root) or (only is not None and e["addon"] not in only)]
    )
    return rows


def status() -> list[dict]:
    """[{workspace, name, addons: [{addon, pid, url?}]}], one entry per workspace with something running."""
    out: dict[str, dict] = {}
    for e in running():
        w = out.setdefault(
            e["workspace"], {"workspace": e["workspace"], "name": e.get("name") or "", "addons": []}
        )
        w["addons"].append({k: e[k] for k in ("addon", "pid", "url") if k in e})
    return sorted(out.values(), key=lambda w: (w["name"].lower(), w["workspace"]))


def find(target: str) -> Path:
    """A workspace by folder path or by name (from what is running)."""
    p = Path(target).expanduser()
    if (p / ".orch").is_dir():
        return p.resolve()
    hits = sorted({w["workspace"] for w in status() if w["name"] == target or w["workspace"] == target})
    if len(hits) == 1:
        return Path(hits[0])
    if hits:
        raise Refused(
            f"More than one running workspace is called {target}. Give the folder: " + ", ".join(hits)
        )
    raise Refused(f"No running workspace is called {target}. See what runs: orch status")


# ---------------------------------------------------------------- per-workspace rows


def _seen_path(root: Path) -> Path:
    return root / ".orch" / "run" / "last-seen.json"


def _seen(root: Path) -> dict[str, str]:
    try:
        data = json.loads(_seen_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(data, dict)
        else {}
    )


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _idle(root: Path, name: str) -> bool:
    """The add-on says it is off on purpose (its own setting): `.orch/run/<name>/idle` is a file. Only a hint
    that silences a "not running" warning; it never starts, stops or trusts anything."""
    try:
        return (root / ".orch" / "run" / name / "idle").is_file()
    except OSError:
        return False


def workspace_rows(root: Path) -> list[dict]:
    """One row per active background add-on here: {addon, name, running, since, last_seen, pid?, url?}.
    `last_seen` is the last time it was seen running (kept in .orch/run/last-seen.json)."""
    root = root.resolve()
    svc = _services(root)
    if not svc:
        return []
    mine = {e["addon"]: e for e in running() if e["workspace"] == str(root)}
    seen = _seen(root)
    rows, changed = [], False
    for name in svc:
        e = mine.get(name)
        if e is not None:
            seen[name] = _now()
            changed = True
        row = {
            "addon": name,
            "name": name,
            "running": e is not None,
            "since": e.get("started_at") if e else None,
            "last_seen": seen.get(name),
        }
        if e is not None:
            row.update({k: e[k] for k in ("pid", "url") if k in e})
        elif _idle(root, name):
            row["idle"] = True  # not running because the person turned it off: nothing to warn about
        rows.append(row)
    if changed:
        p = _seen_path(root)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(seen, f)
            os.replace(tmp, p)
        except OSError:
            pass
    return rows


def ago(iso: str | None) -> str:
    """'3 h ago' style, for a time like 2026-11-05T09:00:00Z."""
    if not iso:
        return "never seen"
    try:
        secs = (
            datetime.now(UTC) - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        ).total_seconds()
    except ValueError:
        return "a while ago"
    secs = max(0, int(secs))
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{round(secs / 60)} min ago"
    if secs < 129600:
        return f"{round(secs / 3600)} h ago"
    return f"{round(secs / 86400)} d ago"
