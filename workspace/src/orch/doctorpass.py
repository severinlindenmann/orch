"""`orch doctor pass`: the machine's health checks and clean-up, every 15 minutes by themselves (ORCH-104).

Built in, so no repeat on a ticket carries it: a ticket that moves to Done can no longer switch the checks off
(the hand-made system keeper stopped that way on 16 Nov). No AI call anywhere: a pass that finds nothing costs
nothing and makes nothing.

Turned on per computer by a setup in the guarded orch home (key folder record `watch`,
keystore.RECORDS), never in the project folder, so a cloned project cannot bring addresses, process
names or folders that orch then checks or cleans by itself. `orch doctor setup <file>` stores it;
without a setup nothing runs on a schedule.

    {"every_min": 15,
     "disk": {"warn_gb": 20, "hold_gb": 10, "resume_gb": 12},
     "load_max": 30,
     "urls":      [{"name": "dash", "label": "Dashboard front", "url": "http://127.0.0.1:8791/"}],
     "processes": [{"name": "guard", "label": "Account guard", "match": "guard.sh", "count": 1}],
     "services":  [{"name": "fwd", "label": "Port forwarder", "launch_agent": "<launchd label>"}],
     "clean": {"repos": ["~/code/app"], "worktree_roots": ["~/copies"], "base": "origin/develop",
               "worktree_idle_h": 3, "build_idle_h": 24, "test_roots": ["~/.app-test"], "test_idle_h": 24},
     "repeats": {"late_min": 30},
     "accounts": {"command": ["cswap", "list", "--json"], "cap_pct": 95},
     "parent": "ORCH-75"}

Repeats are always checked: a repeat (ext.automation of a ticket, written by the automation add-on)
whose planned next run (next_run) is more than max(late_min, one interval, at most a day) in the past
has stopped. Accounts are checked only with a command: it prints JSON, never text for people, either
orch's own shape
{"accounts": [{"week_pct": 97, "week_resets_at": "<ISO time>"}]} or the switcher shape (usage.sevenDay.pct);
one ticket when every account that has a reading is at cap_pct or more of its week.

One pass: clean up by exact path, run the checks, open one ticket per problem (never a second while the
first is open, none when all is fine), and hold back automatic helper starts while the disk is almost full
(`orch pause`, resumed only when this pass paused it). The last pass is kept in .orch/run/doctor.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from orch import keystore, net, runs
from orch.errors import Refused

BY = "agent:doctor"
GB = 1024**3
EVERY_MIN = 15
ASK_EVERY = 60  # seconds between two background starts
DEFAULTS = {"warn_gb": 20.0, "hold_gb": 10.0, "resume_gb": 12.0}
LOAD_MAX = 30.0
BUILD_DIRS = ("relay/target", "publish/target", "target")
# mktemp names: <tag>.XXXX (mktemp -d dir/tag.XXXX) and tmp.XXXX (mktemp -d without a template)
TEMP_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[A-Za-z0-9]{4,}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_LABEL = re.compile(r"^[^\x00-\x1f\x7f]{1,60}$")
LIST_KEYS = {"urls": "url", "processes": "match", "services": "launch_agent"}
CLOSED = ("done", "dropped")
REPEAT_OPEN = ("open", "ready", "active", "waiting", "review")  # and done: the next run opens it again
LATE_MIN = 30
CAP_PCT = 95.0
DAY = 86400


# ------------------------------------------------------------------------------------------------ setup


def _num(v, name: str, lo: float = 0, hi: float = 1e6) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
        raise Refused(f"The setup's {name} must be a number from {lo:g} to {hi:g}.")
    return float(v)


def _paths(v, name: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(p, str) and p.strip() for p in v):
        raise Refused(f"The setup's {name} must be a list of folders.")
    out = []
    for p in v:
        full = Path(os.path.expanduser(p))
        if not full.is_absolute():
            raise Refused(f"The setup's {name} needs full folder paths ({p} is not one).")
        if full.resolve() in (Path.home().resolve(), Path("/")):
            raise Refused(f"The setup's {name} cannot be your home folder or the disk root.")
        out.append(str(full))
    return out


def clean_setup(doc) -> dict:
    """The setup as stored: only known keys, checked values. Refused with a plain reason otherwise."""
    if not isinstance(doc, dict):
        raise Refused("The setup is a JSON object.")
    known = {"every_min", "disk", "load_max", "parent", "clean", "repeats", "accounts", *LIST_KEYS}
    extra = set(doc) - known
    if extra:
        raise Refused(f"The setup has unknown keys: {', '.join(sorted(extra))}.")
    out: dict = {"every_min": int(_num(doc.get("every_min", EVERY_MIN), "every_min", 5, 1440))}
    disk = doc.get("disk") or {}
    if not isinstance(disk, dict) or set(disk) - set(DEFAULTS):
        raise Refused("The setup's disk takes warn_gb, hold_gb and resume_gb.")
    out["disk"] = {k: _num(disk.get(k, d), f"disk {k}", 0, 1e5) for k, d in DEFAULTS.items()}
    if not out["disk"]["hold_gb"] <= out["disk"]["resume_gb"]:
        raise Refused("The setup's disk resume_gb must be at least hold_gb.")
    out["load_max"] = _num(doc.get("load_max", LOAD_MAX), "load_max", 1, 10000)
    for key, field in LIST_KEYS.items():
        items = doc.get(key) or []
        if not isinstance(items, list):
            raise Refused(f"The setup's {key} is a list.")
        rows = []
        for it in items:
            if not isinstance(it, dict) or not _NAME.match(str(it.get("name", ""))):
                raise Refused(f"Each of {key} needs a short name (a-z, 0-9, -).")
            if (
                not _LABEL.match(str(it.get("label", "")))
                or not isinstance(it.get(field), str)
                or not it[field]
            ):
                raise Refused(f"{key} {it['name']} needs a label and a {field}.")
            row = {"name": it["name"], "label": it["label"], field: it[field][:300]}
            if key == "urls" and not re.match(r"^https?://[^/@?#\s]+(/[^?#@\s]*)?$", it["url"]):
                raise Refused(
                    f"urls {it['name']}: an http or https address without a name, password or query part."
                )
            if key == "processes":
                row["count"] = int(_num(it.get("count", 1), f"processes {it['name']} count", 0, 100))
            rows.append(row)
        if len({r["name"] for r in rows}) != len(rows):
            raise Refused(f"Two of {key} have the same name.")
        out[key] = rows
    clean = doc.get("clean") or {}
    if not isinstance(clean, dict):
        raise Refused("The setup's clean is an object.")
    ckeys = {
        "repos",
        "worktree_roots",
        "base",
        "worktree_idle_h",
        "build_idle_h",
        "test_roots",
        "test_idle_h",
    }
    if set(clean) - ckeys:
        raise Refused(f"The setup's clean takes: {', '.join(sorted(ckeys))}.")
    base = clean.get("base", "origin/develop")
    if not isinstance(base, str) or not re.match(r"^[A-Za-z0-9._/-]{1,100}$", base) or base.startswith("-"):
        raise Refused("The setup's clean base is a branch such as origin/develop.")
    out["clean"] = {
        "repos": _paths(clean.get("repos", []), "clean repos"),
        "worktree_roots": _paths(clean.get("worktree_roots", []), "clean worktree_roots"),
        "test_roots": _paths(clean.get("test_roots", []), "clean test_roots"),
        "base": base,
        "worktree_idle_h": _num(clean.get("worktree_idle_h", 3), "clean worktree_idle_h", 1, 10000),
        "build_idle_h": _num(clean.get("build_idle_h", 24), "clean build_idle_h", 1, 10000),
        "test_idle_h": _num(clean.get("test_idle_h", 24), "clean test_idle_h", 1, 10000),
    }
    reps = doc.get("repeats") or {}
    if not isinstance(reps, dict) or set(reps) - {"late_min"}:
        raise Refused("The setup's repeats takes late_min.")
    out["repeats"] = {"late_min": _num(reps.get("late_min", LATE_MIN), "repeats late_min", 5, 10080)}
    acc = doc.get("accounts")
    if acc is not None:
        if not isinstance(acc, dict) or set(acc) - {"command", "cap_pct"}:
            raise Refused("The setup's accounts takes command and cap_pct.")
        cmd = acc.get("command")
        if (
            not isinstance(cmd, list)
            or not 1 <= len(cmd) <= 20
            or not all(isinstance(a, str) and a and len(a) <= 300 and "\x00" not in a for a in cmd)
        ):
            raise Refused(
                'The setup\'s accounts command is a list of words, such as ["cswap", "list", "--json"].'
            )
        out["accounts"] = {
            "command": list(cmd),
            "cap_pct": _num(acc.get("cap_pct", CAP_PCT), "accounts cap_pct", 1, 100),
        }
    parent = doc.get("parent")
    if parent is not None and (not isinstance(parent, str) or not re.match(r"^[A-Za-z0-9_-]{1,40}$", parent)):
        raise Refused("The setup's parent is a ticket id or key.")
    if parent:
        out["parent"] = parent
    return out


def setup(root: Path) -> dict | None:
    """The stored setup, or None (the scheduled checks are off on this computer)."""
    try:
        doc = keystore.record_read(Path(root), "watch")
    except Refused:
        return None
    if not doc:
        return None
    try:
        return clean_setup(doc)
    except Refused:
        return None


def save_setup(root: Path, doc) -> dict:
    clean = clean_setup(doc)
    keystore.record_write(Path(root), "watch", clean)
    return clean


def remove_setup(root: Path) -> bool:
    if keystore.record_read(Path(root), "watch") is None:
        return False
    keystore.record_write(Path(root), "watch", {})
    return True


# ------------------------------------------------------------------------------------------------ probes


class Probes:
    """What the checks read from the machine. Tests pass `sim` ({"disk_free_gb", "load", "http": {url: code},
    "procs": [command lines], "launch_agents": {label: bool}, "logins": [rows], "repeats": [tickets],
    "accounts": <the command's JSON>}) instead."""

    def __init__(self, root: Path, sim: dict | None = None, now: datetime | None = None):
        self.root = Path(root)
        self.sim = sim
        self.now = now or datetime.now(UTC)

    def _has(self, key: str) -> bool:
        return self.sim is not None and key in self.sim

    def disk_free_gb(self) -> float:
        if self._has("disk_free_gb"):
            return float(self.sim["disk_free_gb"])
        return shutil.disk_usage(self.root).free / GB

    def load(self) -> float | None:
        if self._has("load"):
            return float(self.sim["load"])
        try:
            return os.getloadavg()[0]
        except (AttributeError, OSError):  # Windows has no load average
            return None

    def http(self, url: str) -> int:
        if self.sim is not None:
            return int((self.sim.get("http") or {}).get(url, 200))
        try:
            with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310  an address the person set up
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:  # noqa: BLE001  down, refused, timeout
            return 0

    def procs(self) -> list[str]:
        if self._has("procs"):
            return list(self.sim["procs"])
        if os.name == "nt":
            return []
        r = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=30)
        return [x for x in r.stdout.splitlines() if x.strip()]

    def launch_agent(self, label: str) -> bool | None:
        """True when the launch agent runs, False when it does not, None when it cannot be known here."""
        if self._has("launch_agents"):
            return (self.sim["launch_agents"] or {}).get(label, True)
        if sys.platform != "darwin":
            return None
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == label:
                return parts[0] != "-"
        return False

    def logins(self) -> list[dict]:
        if self._has("logins"):
            return list(self.sim["logins"])
        from orch import health

        try:
            return health.check(self.root)["items"]
        except Exception:  # noqa: BLE001  a check that cannot run is not a problem of the machine
            return []

    def repeats(self) -> list[dict]:
        """The tickets that carry a repeat."""
        if self._has("repeats"):
            return list(self.sim["repeats"])
        from orch import tickets

        try:
            return [t for t in tickets.list_all(self.root) if _sched(t).get("recurring") is True]
        except (Refused, OSError):
            return []

    def accounts(self, command: list[str]):
        """The account command's JSON, or None when it cannot be read now (then nothing is known)."""
        if self._has("accounts"):
            return self.sim["accounts"]
        exe = shutil.which(os.path.expanduser(command[0]))
        if not exe:
            return None
        try:
            r = subprocess.run(
                [exe, *command[1:]],
                capture_output=True,
                text=True,
                timeout=60,
                stdin=subprocess.DEVNULL,
                cwd=Path(os.path.realpath(tempfile.gettempdir())),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout)
        except ValueError:
            return None


def _sched(t: dict) -> dict:
    a = (t.get("ext") or {}).get("automation") if isinstance(t, dict) else None
    return a if isinstance(a, dict) else {}


def _when(ts) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(UTC) if d.tzinfo else None


def _utc(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M UTC")


def overdue_repeats(rows: list[dict], now: datetime, late_min: float) -> list[dict]:
    """Repeats that stopped: [{ticket, key, title, planned, last}]. A repeat is late when its planned next
    run lies more than max(late_min, one interval, at most a day) in the past. Paused repeats, closed
    tickets and repeats without a planned time (set before orch saved one; they get it with their next
    run) are left out."""
    out = []
    for t in rows:
        a = _sched(t)
        if a.get("recurring") is not True or a.get("paused") is True:
            continue
        if t.get("status") not in (*REPEAT_OPEN, "done"):
            continue
        planned, last_run = _when(a.get("next_run")), _when(a.get("last_run"))
        if planned is None:
            continue
        gap = (planned - last_run).total_seconds() if last_run and last_run < planned else 0
        late = (now - planned).total_seconds()
        if late >= max(late_min * 60, min(gap, DAY)):
            out.append(
                {
                    "ticket": str(t.get("id", "")),
                    "key": str(t.get("key") or t.get("id") or ""),
                    "title": str(t.get("title") or "")[:120],
                    "planned": planned,
                    "last": last_run,
                }
            )
    return out


def week_use(doc) -> list[dict]:
    """[{pct, resets}] of every account with a weekly reading, from the account command's JSON: orch's
    own shape (week_pct, week_resets_at) or the switcher shape (usage.sevenDay.pct / resetsAt).
    Anything else is skipped."""
    rows = doc.get("accounts") if isinstance(doc, dict) else doc if isinstance(doc, list) else None
    out = []
    for a in rows if isinstance(rows, list) else []:
        if not isinstance(a, dict) or a.get("disabled") is True:
            continue
        pct, resets = a.get("week_pct"), a.get("week_resets_at")
        if pct is None:
            week = (a.get("usage") or {}).get("sevenDay") if isinstance(a.get("usage"), dict) else None
            if isinstance(week, dict):
                pct, resets = week.get("pct"), week.get("resetsAt")
        if isinstance(pct, bool) or not isinstance(pct, int | float) or not 0 <= pct <= 1000:
            continue
        out.append({"pct": float(pct), "resets": _when(resets)})
    return out


# ------------------------------------------------------------------------------------------------ checks


def checks(cfg: dict, p: Probes, mem: dict) -> list[dict]:
    """The problems found now: [{key, title, note}]. `mem` keeps what must hold on two passes in a row."""
    out: list[dict] = []

    def add(key: str, title: str, note: str) -> None:
        out.append({"key": key, "title": title[:200], "note": note[:1900]})

    d = cfg["disk"]
    free = p.disk_free_gb()
    mem["disk_free_gb"] = round(free, 1)
    if free < d["warn_gb"]:
        held = (
            f" New helpers do not start by themselves until {d['resume_gb']:.0f} GB are free again."
            if free < d["hold_gb"]
            else ""
        )
        add(
            "disk",
            f"Disk almost full: {free:.0f} GB free",
            f"This computer has {free:.1f} GB free (warning under {d['warn_gb']:.0f} GB, new helpers "
            f"held back "
            f"under {d['hold_gb']:.0f} GB).{held} The clean-up already removed the finished copies, old test "
            "folders and build output it may remove. Look for what else is big and free space by exact path.",
        )

    load = p.load()
    high = load is not None and load > cfg["load_max"]
    if high and mem.get("load_high"):
        add(
            "load",
            f"Machine load stays high: {load:.0f}",
            f"Load {load:.1f} is over {cfg['load_max']:.0f} on two checks in a row. "
            "Too many helpers or tests "
            "run at once.",
        )
    mem["load_high"] = high

    for it in p.logins():
        if it.get("state") in ("soon", "renew", "unreachable"):
            name = it.get("label") or it.get("name") or "A tool"
            when = f" (ends {str(it['ends_at'])[:16].replace('T', ' ')} UTC)" if it.get("ends_at") else ""
            add(
                f"login-{it.get('name')}",
                f"{name} login needs renewing{when}",
                f"orch logins says {it.get('state')} for {name}. Every helper on it stops when it lapses. "
                "A person renews the login.",
            )

    for u in cfg.get("urls") or []:
        code = p.http(u["url"])
        if code != 200:
            where = u["url"].split("/")[2]  # the host only: a path can carry a token
            add(f"url-{u['name']}", f"{u['label']} does not answer", f"{where} gave {code or 'no answer'}.")

    if cfg.get("processes"):
        lines = p.procs()
        for pr in cfg["processes"]:
            n = sum(1 for line in lines if pr["match"] in line)
            if n != pr["count"]:
                state = "is not running" if n == 0 else f"runs {n} times"
                add(
                    f"proc-{pr['name']}",
                    f"{pr['label']} {state}",
                    f"Expected {pr['count']} process(es) matching '{pr['match']}', found {n}. "
                    "Start it, or stop "
                    "the extra one by its own process number (orch doctor stop-pids).",
                )

    for s in cfg.get("services") or []:
        if p.launch_agent(s["launch_agent"]) is False:
            add(
                f"svc-{s['name']}",
                f"{s['label']} is not running",
                f"The launch agent {s['launch_agent']} is not running.",
            )

    late_min = (cfg.get("repeats") or {}).get("late_min", LATE_MIN)
    for r in overdue_repeats(p.repeats(), p.now, late_min):
        last_s = f"It last ran {_utc(r['last'])}." if r["last"] else "It has not run yet."
        add(
            f"repeat-{r['ticket']}",
            f"Repeat stopped: {r['title'] or r['key']}",
            f"The repeat on {r['key']} ({r['title']}) should have run at {_utc(r['planned'])}. {last_s} "
            "Look whether the automation runs (orch automation status) and whether the repeat is still "
            "wanted; pause or turn it off when it is not.",
        )

    acc = cfg.get("accounts")
    if acc:
        weeks = week_use(p.accounts(acc["command"]))
        if weeks and min(w["pct"] for w in weeks) >= acc["cap_pct"]:
            pcts = ", ".join(f"{w['pct']:.0f}%" for w in weeks)
            resets = sorted(w["resets"] for w in weeks if w["resets"])
            when = f" The first one starts a new week at {_utc(resets[0])}." if resets else ""
            add(
                "accounts-week",
                "Every account has used up its week",
                f"All {len(weeks)} accounts are at {acc['cap_pct']:.0f}% or more of their weekly use "
                f"({pcts}). Helpers stop when the last one runs "
                f"out.{when} Add an account or hold back helper starts until then.",
            )
    return out


# ------------------------------------------------------------------------------------------------ clean-up


def untouched(path: Path, hours: float, depth: int = 2, now: float | None = None) -> bool:
    """Nothing in the top `depth` levels changed in the last `hours`."""
    cut = (now if now is not None else time.time()) - hours * 3600
    stack = [(path, 0)]
    while stack:
        d, lvl = stack.pop()
        try:
            if d.lstat().st_mtime > cut:
                return False
            if lvl < depth and d.is_dir() and not d.is_symlink():
                stack.extend((c, lvl + 1) for c in d.iterdir())
        except OSError:
            continue
    return True


def _git(cwd: Path, args: list[str], timeout: int = 60, read_only: bool = True) -> tuple[int, str]:
    """git through orch.safegit (no repository hooks, filters or network). (exit code, output)."""
    from orch import safegit

    rc, out, _ = safegit.run(args, cwd, timeout, read_only=read_only)
    return rc, out


def worktrees(repo: Path) -> list[Path]:
    rc, out = _git(repo, ["worktree", "list", "--porcelain"])
    return [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")] if rc == 0 else []


def _du(path: Path) -> int:
    r = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=300)
    try:
        return int(r.stdout.split()[0]) * 1024
    except (ValueError, IndexError):
        return 0


def process_dirs() -> list[str] | None:
    """The current folders of all running processes, or None when they cannot be read (then nothing is in use
    is unknown, and no copy is removed)."""
    if os.name == "nt" or not shutil.which("lsof"):
        return None
    try:
        r = subprocess.run(["lsof", "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [line[1:] for line in r.stdout.splitlines() if line.startswith("n")]


def _in_use(path: Path, cwds: list[str]) -> bool:
    p = str(path)
    return any(c == p or c.startswith(p + "/") for c in cwds)


def _own(path: Path) -> bool:
    try:
        return not hasattr(os, "getuid") or path.lstat().st_uid == os.getuid()
    except OSError:
        return False


def _inside(base: Path, rel: str) -> bool:
    """base/rel is a real folder inside base: no part of it is a link that leads elsewhere."""
    p = base
    for part in Path(rel).parts:
        p = p / part
        if p.is_symlink():
            return False
    try:
        return p.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


def clean(cfg: dict, apply: bool, now: float | None = None) -> list[str]:
    """Finished copies of a repository (clean, in the base branch, untouched, no process inside: `git worktree
    remove` without --force, so git itself refuses anything unclean), build output of copies untouched for
    a day, and test folders made by mktemp untouched for a day. Exact paths only: never a pattern, never a
    kill."""
    c = cfg.get("clean") or {}
    done: list[str] = []
    roots = {Path(r).resolve() for r in c.get("worktree_roots") or []}
    cwds = process_dirs() if roots else []
    verb = "removed" if apply else "would remove"
    for repo_s in c.get("repos") or []:
        repo = Path(repo_s)
        if not (repo / ".git").exists() or not roots:
            continue
        try:  # no fetch (orch's git has no network): the base is as new as the last fetch of this clone
            listed = worktrees(repo)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for wt in listed:
            try:
                if wt.resolve().parent not in roots or not wt.is_dir() or wt.is_symlink():
                    continue
                rc, out = _git(wt, ["status", "--porcelain"])
                unclean = rc != 0 or bool(out.strip())  # a status that could not be read counts as changed
                merged = _git(wt, ["merge-base", "--is-ancestor", "HEAD", c["base"]])[0] == 0
                if (
                    merged
                    and not unclean
                    and cwds is not None
                    and not _in_use(wt, cwds)
                    and untouched(wt, c["worktree_idle_h"], now=now)
                ):
                    size = _du(wt) // 2**20
                    if not apply:
                        done.append(f"would remove finished copy {wt} ({size} MB)")
                        continue
                    rc, _ = _git(repo, ["worktree", "remove", str(wt)], timeout=300, read_only=False)
                    done.append(f"removed finished copy {wt} ({size} MB)" if rc == 0 else f"git kept {wt}")
                    continue
                if untouched(
                    wt, c["build_idle_h"], now=now
                ):  # a kept copy, even a changed one: its build output can go
                    for rel in BUILD_DIRS:
                        b = wt / rel
                        if _inside(wt, rel) and b.is_dir() and (b / "CACHEDIR.TAG").is_file():
                            size = _du(b) // 2**20
                            if apply:
                                shutil.rmtree(b)
                            done.append(f"{verb} build output {b} ({size} MB)")
            except (OSError, subprocess.TimeoutExpired):
                continue
    for root_s in c.get("test_roots") or []:
        troot = Path(root_s)
        if not troot.is_dir() or troot.is_symlink():
            continue
        for d in sorted(troot.iterdir()):
            try:
                if not TEMP_RE.match(d.name) or d.is_symlink() or not d.is_dir() or not _own(d):
                    continue
                if (d / ".git").exists() or not untouched(d, c["test_idle_h"], depth=3, now=now):
                    continue
                size = _du(d) // 2**20
                if apply:
                    shutil.rmtree(d)
                done.append(f"{verb} test folder {d} ({size} MB)")
            except OSError:
                continue
    return done


# ------------------------------------------------------------------------------------------------ by hand


def temp_roots(root: Path) -> list[Path]:
    out = {Path(os.path.realpath(tempfile.gettempdir())), Path(os.path.realpath("/tmp"))}
    cfg = setup(root) or {}
    out |= {Path(os.path.realpath(p)) for p in (cfg.get("clean") or {}).get("test_roots") or []}
    return sorted(out)


def remove_temp(root: Path, paths: list[str]) -> list[dict]:
    """Delete folders or files your own mktemp made, after strict checks. Each path is directly inside the
    temp folder (or a test folder of the setup), named like mktemp names (<tag>.XXXX), yours, not a link,
    not a git copy, and not the current folder or one around it. Anything else is refused and left
    alone."""
    allowed = temp_roots(root)
    here = Path(os.getcwd()).resolve()
    out = []
    for raw in paths:
        p = Path(raw.rstrip("/") or raw)
        try:
            real = p.parent.resolve() / p.name
        except OSError:
            real = p
        why = None
        if real.parent not in allowed or not TEMP_RE.match(real.name):
            why = "not a folder your own mktemp made in the temp folder"
        elif not real.exists() and not real.is_symlink():
            out.append({"path": raw, "result": "gone"})
            continue
        elif real.is_symlink() or not _own(real) or (real / ".git").exists():
            why = "a link, someone else's, or a git copy"
        elif here == real or real in here.parents:
            why = "the current folder is inside it"
        if why:
            out.append({"path": raw, "result": "refused", "why": why})
            continue
        try:
            if real.is_dir():
                shutil.rmtree(real)
            else:
                real.unlink()
            out.append({"path": raw, "result": "removed"})
        except OSError as e:
            out.append({"path": raw, "result": "failed", "why": e.strerror or str(e)})
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_pids(pids: list[str], wait: float = 5.0, sleep=time.sleep) -> list[dict]:
    """Stop exactly these processes, one by one, and prove they are gone: TERM, then KILL after
    `wait` seconds. Each argument is one process number; a list in one argument is refused, never split."""
    out = []
    for raw in pids:
        if not re.fullmatch(r"[1-9][0-9]{0,9}", raw.strip()):
            out.append({"pid": raw, "result": "refused", "why": "not one process number"})
            continue
        pid = int(raw)
        if pid == os.getpid():
            out.append({"pid": raw, "result": "refused", "why": "that is orch itself"})
            continue
        if not _alive(pid):
            out.append({"pid": raw, "result": "not running"})
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except PermissionError:
            out.append({"pid": raw, "result": "refused", "why": "not your process"})
            continue
        except ProcessLookupError:
            out.append({"pid": raw, "result": "stopped"})
            continue
        steps = max(1, int(wait * 5))
        for _ in range(steps):
            if not _alive(pid):
                break
            sleep(wait / steps)
        if _alive(pid) and hasattr(signal, "SIGKILL"):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            sleep(0.5)
        out.append({"pid": raw, "result": "STILL RUNNING" if _alive(pid) else "stopped"})
    return out


# ------------------------------------------------------------------------------------------------ the pass


def _path(root: Path) -> Path:
    return runs.run_dir(Path(root)) / "doctor.json"


def last(root: Path) -> dict:
    d = net.read_json(_path(root), None)
    return d if isinstance(d, dict) else {}


def _now_s(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status(root: Path, tid: str) -> str | None:
    from orch import tickets

    try:
        return tickets.load(root, tid)["status"]
    except (Refused, OSError, KeyError, ValueError):
        return None


def _open_ticket(root: Path, parent: str | None, prob: dict) -> str | None:
    from orch import tickets

    note = (
        prob["note"]
        + f"\n\n(Opened by the scheduled health checks, problem '{prob['key']}'. No second ticket "
        "opens while this one is open.)"
    )
    pid = None
    if parent:
        try:
            pid = tickets.load(root, tickets.resolve(root, parent))["id"]
        except (Refused, OSError, KeyError, ValueError):
            pid = None
    t = tickets.create(root, prob["title"], BY, parent=pid, fields={"note": note[:2000]})
    return t["id"]


def _hold(root: Path, cfg: dict, free: float, mem: dict) -> str | None:
    """Under hold_gb pause automatic starts; at resume_gb resume them, only when this pass paused them."""
    from orch import brake

    d = cfg["disk"]
    rec = brake.paused(root)
    if free < d["hold_gb"] and rec is None:
        brake.pause(root, BY, f"Disk almost full: {free:.0f} GB free")
        mem["paused"] = True
        return "paused"
    if free >= d["resume_gb"] and mem.get("paused"):
        mem["paused"] = False
        if rec and rec.get("by") == BY:
            brake.resume(root)
            return "resumed"
    return None


def run_pass(
    root: Path,
    *,
    sim: dict | None = None,
    apply: bool = True,
    cleanup: bool = True,
    now: datetime | None = None,
) -> dict:
    """One pass. Returns {at, problems, opened, kept, cleaned, hold, disk_free_gb}. apply=False only lists."""
    from orch import tickets

    root = Path(root)
    cfg = setup(root)
    if cfg is None:
        raise Refused(
            "The scheduled health checks are not set up on this computer. "
            "Set them up: orch doctor setup <file>"
        )
    mem = last(root)
    known = mem.get("problems") if isinstance(mem.get("problems"), dict) else {}
    cleaned = clean(cfg, apply) if cleanup and sim is None else []
    found = checks(cfg, Probes(root, sim, now), mem)
    hold = _hold(root, cfg, mem["disk_free_gb"], mem) if apply else None
    opened, kept = [], []
    now_s = _now_s(now)
    found_keys = {p["key"] for p in found}
    for prob in found:
        old = known.get(prob["key"])
        if old and _status(root, old.get("ticket", "")) not in (None, *CLOSED):
            kept.append(old["ticket"])
            continue
        if not apply:
            opened.append({"key": prob["key"], "title": prob["title"], "ticket": None})
            continue
        try:
            tid = _open_ticket(root, cfg.get("parent"), prob)
        except (Refused, OSError):
            continue
        known[prob["key"]] = {"ticket": tid, "at": now_s}
        opened.append({"key": prob["key"], "title": prob["title"], "ticket": tid})
    if apply:  # a problem that went away: said once on its still open ticket
        for key, rec in list(known.items()):
            if key in found_keys or not isinstance(rec, dict) or rec.get("cleared"):
                continue
            if _status(root, rec.get("ticket", "")) in (None, *CLOSED):
                known.pop(key)
                continue
            try:
                tickets.log(
                    root, rec["ticket"], "The scheduled health checks no longer see this problem.", BY
                )
                rec["cleared"] = now_s
            except (Refused, OSError):
                pass
        for key in found_keys:
            if isinstance(known.get(key), dict):
                known[key].pop("cleared", None)
    res = {
        "at": now_s,
        "problems": [p["key"] for p in found],
        "opened": opened,
        "kept": kept,
        "cleaned": cleaned,
        "hold": hold,
        "disk_free_gb": mem["disk_free_gb"],
    }
    if apply:
        mem.update({"problems": known, "last_pass": res})
        net.write_json(_path(root), mem)
    return res


# ------------------------------------------------------------------------------------------------ by itself


def _last_at(root: Path) -> float | None:
    at = (last(root).get("last_pass") or {}).get("at")
    try:
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except (TypeError, ValueError):
        return None


def due(root: Path, now: float | None = None) -> bool:
    """True when the checks are set up here and the last pass is older than every_min."""
    cfg = setup(root)
    if cfg is None:
        return False
    t = _last_at(root)
    if t is None:
        return True
    age = (now if now is not None else time.time()) - t
    return age < 0 or age >= cfg["every_min"] * 60  # a time in the future is not believed


def soon(root: Path, now: float | None = None) -> bool:
    """Start one background `orch doctor pass` when it is due, at most once per ASK_EVERY. Never waits, never
    raises. True when one was started. Called by the automation loop and by the pages' needs list, so no
    ticket     and no repeat carries the checks."""
    try:
        if os.environ.get("ORCH_NO_HEALTH_CHECK"):  # tests: never the real machine
            return False
        now = now if now is not None else time.time()
        if not due(root, now):
            return False
        mark = runs.run_dir(Path(root)) / "doctor-asked"
        try:
            if 0 <= now - mark.stat().st_mtime < ASK_EVERY:
                return False
        except OSError:
            pass
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
        os.utime(mark, (now, now))
        from orch import procs

        log = runs.run_dir(Path(root)) / "doctor-pass.log"
        with open(log, "ab") as out:
            subprocess.Popen(
                procs.orch_python_argv("doctor", "pass", "--json"),
                cwd=Path(os.path.realpath(tempfile.gettempdir())),
                env={**os.environ, "ORCH_ROOT": str(root)},
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                start_new_session=os.name != "nt",
            )
        return True
    except Exception:  # noqa: BLE001  a check that cannot start never holds up a page or the loop
        return False


def overdue_row(root: Path, now: float | None = None) -> dict | None:
    """For `orch doctor`: the scheduled checks are set up but have not run for three of their intervals."""
    cfg = setup(root)
    if cfg is None:
        return None
    t = _last_at(root)
    age = None if t is None else ((now if now is not None else time.time()) - t) / 60
    ok = age is not None and 0 <= age < cfg["every_min"] * 3
    fact = (
        f"The scheduled health checks ran {age:.0f} minutes ago."
        if age is not None
        else "The scheduled health checks are set up but have not run yet."
    )
    return {"name": "scheduled checks", "ok": ok, "fact": fact, "next": None if ok else "Run: orch start"}
