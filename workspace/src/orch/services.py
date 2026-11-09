"""`orch start | stop | status`: background processes of active add-ons (contracts/addon-manifest.md).

The core knows no add-on by name. An active add-on with `background = true` implements `start --json`,
`stop --json` and `status --json`; `orch start` calls `start` on each, `orch stop` calls `stop`. What runs
where is kept in the user's orch folder (`running.json`: workspace, name, add-on, pid, url); dead pids are
dropped on read.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, skills
from orch.errors import Refused


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


def _services(root: Path) -> dict[str, dict]:
    """Active add-ons of this workspace that have a background process."""
    return {n: m for n, m in sorted(addons.active_manifests(root).items()) if m["background"]}


def _call(root: Path, name: str, m: dict, sub: str) -> dict:
    env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": addons.orch_bin()}
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-m", m["run"], sub, "--json"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
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


def _printable(v: object) -> str:
    """Add-on text for the terminal: no control characters (no escape sequences), at most 200 characters."""
    return "".join(c for c in str(v) if c.isprintable())[:200]


def _workspace_root(root: Path) -> Path:
    if not (root / ".orch").is_dir():
        raise Refused(
            "No orch workspace here (no .orch/ folder). Go to your workspace folder, or run: orch init"
        )
    return root


def start(root: Path, only: set[str] | None = None) -> list[dict]:
    """Start the background process of every active add-on here. One row per add-on."""
    root = _workspace_root(root).resolve()
    skills.ensure_gitignore(root)  # .orch/run/ (runtime files of the add-ons) stays out of git
    rows = []
    entries = [
        e for e in running() if e["workspace"] != str(root) or (only is not None and e["addon"] not in only)
    ]
    for name, m in _services(root).items():
        if only is not None and name not in only:
            continue
        res = _call(root, name, m, "start")
        row = {"addon": name, "running": bool(res.get("running")) and "error" not in res}
        if pid_alive(res.get("pid")):
            row["pid"] = res["pid"]
        if local_url(res.get("url")):
            row["url"] = res["url"]
        if "error" in res:
            row["error"] = _printable(res["error"])
        rows.append(row)
        if row["running"] and isinstance(row.get("pid"), int):
            entries.append(
                {
                    "workspace": str(root),
                    "name": root.name,
                    "addon": name,
                    "pid": row["pid"],
                    **({"url": row["url"]} if row.get("url") else {}),
                    "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    _save(entries)
    workspace_rows(root)  # notes when each was last seen running
    return rows


def stop(root: Path, only: set[str] | None = None) -> list[dict]:
    """Stop every background process of this workspace. An add-on that is no longer on here is not run:
    its process sees that and ends by itself."""
    root = root.resolve()
    workspace_rows(root)  # notes that they were running now
    rows = []
    for name, m in _services(root).items():
        if only is not None and name not in only:
            continue
        res = _call(root, name, m, "stop")
        row = {"addon": name, "stopped": bool(res.get("stopped"))}
        if "error" in res:
            row["error"] = _printable(res["error"])
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
