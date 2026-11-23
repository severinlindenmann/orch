"""Found on this computer: background jobs of this person's account that orch did not make. Read-only.

`scan(root)` only reads: the person's LaunchAgent plists (Label, the program and its words, RunAtLoad, the log path),
`launchctl print` / `systemctl --user show` state, and `ps`. It never reads environment variables or files of other
programs, never writes a file and never starts, stops or changes anything. Every command line it returns has been
through the core secret scan (a hit shows as ••••••).

Processes: a program of this user without a terminal whose working folder is inside this workspace. On Linux the
folder comes from /proc/<pid>/cwd. On macOS only `lsof` can tell it; when lsof is missing (as on the develop Mac)
processes are skipped, because without the folder there is no way to tell a workspace job from any other program.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import store
from .store import Refused

# Labels and units orch writes itself, and vendor helpers nobody needs to see. Keep this list short.
ORCH_LABEL = "ch.orch.svc."
ORCH_UNIT = "orch-svc-"
VENDOR_LABELS = ("com.apple.", "com.google.", "com.microsoft.")
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh", "deno", "bun", "uv"}
PROC = Path("/proc")
LSOF = "/usr/sbin/lsof"
ID_RE = re.compile(r"(launchd|systemd):[A-Za-z0-9@._-]{1,200}|process:\d{1,10}")
PAGE_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")  # a plain item id of the page (addon-view schema)
HASHED_ID = re.compile(r"found-[0-9a-f]{12}")
TOOL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
WINDOWS_NOTE = (
    "On Windows orch cannot look for other background jobs yet; services orch adds are listed as usual."
)


def _real_account_home() -> Path:
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


def _test_home_on_real_account() -> bool:
    """A test install (ORCH_HOME aimed at a folder that is not the real ~/.orch-tool) whose process still has the real
    HOME: the real LaunchAgents / systemd units are not its own, so Found must not list them (nobody may adopt the
    real forwarder into a test workspace)."""
    env = os.environ.get("ORCH_HOME")
    if not env:
        return False
    try:
        real = _real_account_home().resolve()
        if Path(env).resolve() == (real / ".orch-tool").resolve():
            return False
        return Path.home().resolve() == real
    except OSError:
        return False


def _tool(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess | None:
    """Run a read-only platform tool; None when it is missing or does not answer."""
    env = {**os.environ, "LC_ALL": "C"}  # C locale: ps dates in one form
    env.setdefault("PATH", TOOL_PATH)
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _utc_from_ps(text: str) -> str | None:
    try:
        t = time.strptime(" ".join(text.split()), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    return datetime.fromtimestamp(time.mktime(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plain_label(label: str) -> str:
    """com.example.web-preview -> web-preview; homebrew.mxcl.postgresql@14 -> postgresql@14."""
    parts = label.split(".")
    if len(parts) >= 3:
        return ".".join(parts[2:])
    return parts[-1]


def script_name(argv: list[str]) -> str:
    """The program's name, or the script's name when the program is an interpreter (python3 app.py -> app.py)."""
    if not argv:
        return "?"
    prog = Path(argv[0]).name
    if _interpreter(prog):
        for a in argv[1:]:
            if a == "-m" or a in ("run", "exec"):  # a tuple holding "-m" looks like a spawn to the lint
                continue
            if not a.startswith("-"):
                return Path(a).name
    return prog


def _masked(root: Path, argv: list[str]) -> list[str]:
    from .cli import _masked_command

    return _masked_command(root, argv) if argv else []


def _shown(root: Path, text: str) -> str:
    """A found job's name or description as shown (and the default name on adopt); one with a secret is masked."""
    from .cli import MASK, _masked_command

    return MASK if text and _masked_command(root, [text]) != [text] else text


def page_id(fid: str) -> str:
    """The id the page uses for a found item: the found id when it is a plain page id, else a stable hash of it.
    `get` takes either, so Manage with orch on the page sends the page id and adopt finds the real job."""
    if PAGE_ID.fullmatch(fid):
        return fid
    return "found-" + hashlib.sha1(fid.encode("utf-8")).hexdigest()[:12]


def _item(root: Path, fid: str, name: str, running: bool, since, what: str, how: dict, argv, auto) -> dict:
    return {
        "id": fid,
        "name": _shown(root, name[: store.MAX_NAME]) or fid,
        "running": bool(running),
        "since": since,
        "what": _shown(root, what),
        "how": how,
        "command": _masked(root, list(argv)),
        "auto": bool(auto),
    }


def _adopted(root: Path) -> set[str]:
    """Found ids that already have a record (adopted earlier): they show in the services list instead."""
    recs, _bad = store.load_all(root)
    out = set()
    for r in recs:
        a = r.get("adopted")
        if isinstance(a, dict) and isinstance(a.get("entry"), str):
            out.add(f"{a.get('kind')}:{a['entry']}")
    return out


# ---------------------------------------------------------------- macOS


def _launchd(root: Path) -> tuple[list[dict], set[int]]:
    folder = Path.home() / "Library" / "LaunchAgents"
    tool = shutil.which("launchctl") or "/bin/launchctl"
    domain = f"gui/{os.getuid()}"
    items, pids = [], set()
    if not folder.is_dir():
        return items, pids
    from .drivers.launchd import disabled_labels

    cp = _tool([tool, "print-disabled", domain])
    off = disabled_labels(cp.stdout) if cp and cp.returncode == 0 else set()
    for p in sorted(folder.glob("*.plist")):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            with open(p, "rb") as f:
                d = plistlib.load(f)
        except Exception:  # noqa: BLE001, S112 - a plist we cannot read is not ours to judge; skip it
            continue
        label = d.get("Label") if isinstance(d, dict) else None
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9@._-]{1,200}", label):
            continue
        if label.startswith(ORCH_LABEL) or label.startswith(VENDOR_LABELS):
            continue
        argv = d.get("ProgramArguments") or ([d["Program"]] if isinstance(d.get("Program"), str) else [])
        argv = [a for a in argv if isinstance(a, str) and a][:64]
        running, pid, since = False, None, None
        cp = _tool([tool, "print", f"{domain}/{label}"])
        if cp and cp.returncode == 0:
            state = re.search(r"^\s*state = (\S+)", cp.stdout, re.MULTILINE)
            m = re.search(r"^\s*pid = (\d+)", cp.stdout, re.MULTILINE)
            if state and state.group(1) == "running" and m:
                running, pid = True, int(m.group(1))
                pids.add(pid)
                ps = _tool(["ps", "-o", "lstart=", "-p", str(pid)])
                since = _utc_from_ps(ps.stdout) if ps and ps.returncode == 0 else None
        how = {"kind": "launchd", "label": label, "path": str(p)}
        if pid:
            how["pid"] = pid
        what = f"A job of your account that runs {script_name(argv)}" if argv else "A job of your account"
        items.append(
            _item(
                root,
                f"launchd:{label}",
                plain_label(label),
                running,
                since,
                what,
                how,
                argv,
                bool(d.get("RunAtLoad")) and label not in off,  # a switched-off label is not loaded at login
            )
        )
    return items, pids


def launchd_log(path: Path) -> Path | None:
    """The log file a found plist names (StandardOutPath, else StandardErrorPath), for orch services log."""
    try:
        with open(path, "rb") as f:
            d = plistlib.load(f)
    except Exception:  # noqa: BLE001
        return None
    for k in ("StandardOutPath", "StandardErrorPath"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, str) and v.startswith("/") and "\n" not in v:
            return Path(v)
    return None


# ---------------------------------------------------------------- Linux


def _systemd_user_dirs() -> tuple[Path, ...]:
    home = Path.home()
    return (home / ".config" / "systemd" / "user", home / ".local" / "share" / "systemd" / "user")


def _execstart_argv(text: str) -> list[str]:
    """`{ path=/usr/bin/x ; argv[]=/usr/bin/x a b ; ... }` -> ['/usr/bin/x', 'a', 'b']."""
    m = re.search(r"argv\[\]=(.*?) ;", text)
    return m.group(1).split()[:64] if m else []


def _systemd_since(text: str) -> str | None:
    from .drivers.systemd import _utc

    return _utc(text)


def _systemd(root: Path) -> tuple[list[dict], set[int]]:
    tool = shutil.which("systemctl")
    items, pids = [], set()
    if not tool:
        return items, pids
    names: set[str] = set()
    dirs = _systemd_user_dirs()
    for d in dirs:
        if d.is_dir():
            names.update(p.name for p in d.glob("*.service") if "@" not in p.name)
    cp = _tool(
        [tool, "--user", "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"]
    )
    if cp and cp.returncode == 0:
        for line in cp.stdout.splitlines():
            w = line.split()
            if w and w[0].endswith(".service"):
                names.add(w[0])
    names = {n for n in names if not n.startswith(ORCH_UNIT) and re.fullmatch(r"[A-Za-z0-9@._-]{1,200}", n)}
    if not names:
        return items, pids
    props = "Id,Description,FragmentPath,ActiveState,MainPID,ActiveEnterTimestamp,UnitFileState,ExecStart"
    cp = _tool(
        [tool, "--user", "show", *sorted(names), f"--property={props}", "--timestamp=utc", "--no-pager"]
    )
    if not cp or cp.returncode != 0:
        return items, pids
    for block in re.split(r"\n\s*\n", cp.stdout.strip()):
        v = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        unit, frag = v.get("Id", ""), v.get("FragmentPath", "")
        if unit not in names or not frag:
            continue
        fp = Path(frag)
        if not any(fp.parent == d for d in dirs):  # only units the person installed for their own account
            continue
        running = v.get("ActiveState") == "active"
        pid = int(v["MainPID"]) if v.get("MainPID", "").isdigit() and int(v["MainPID"]) > 0 else None
        if running and pid:
            pids.add(pid)
        argv = _execstart_argv(v.get("ExecStart", ""))
        desc = v.get("Description", "").strip()
        what = desc[:120] if desc and desc != unit else f"A job of your account that runs {script_name(argv)}"
        how = {"kind": "systemd", "unit": unit, "path": frag}
        if running and pid:
            how["pid"] = pid
        since = _systemd_since(v.get("ActiveEnterTimestamp", "")) if running else None
        name = unit.removesuffix(".service")
        auto = v.get("UnitFileState") == "enabled"
        items.append(_item(root, f"systemd:{unit}", name, running, since, what, how, argv, auto))
    return items, pids


# ---------------------------------------------------------------- processes


def _cwd_linux(pid: int) -> Path | None:
    try:
        return Path(os.readlink(PROC / str(pid) / "cwd"))
    except OSError:
        return None


def _cwds_lsof(pids: list[int]) -> dict[int, Path]:
    lsof = shutil.which("lsof") or (LSOF if Path(LSOF).exists() else None)
    if not lsof or not pids:
        return {}
    cp = _tool([lsof, "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, pids))])
    if not cp:
        return {}
    out, pid = {}, None
    for line in cp.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            out[pid] = Path(line[1:])
    return out


def _interpreter(prog: str) -> bool:
    """python3.12, Python (the macOS framework app), node ... count as interpreters."""
    return re.sub(r"[\d.]+$", "", prog.lower()) in INTERPRETERS


def _is_orch(argv: list[str]) -> bool:
    """orch itself, or one of its own parts (orch_dashboard, orch_automation ...), also behind interpreter flags
    such as `Python -P -m orch_dashboard`: orch's own background pages are never found items."""
    prog = Path(argv[0]).name if argv else ""
    if prog == "orch" or any(a == "orch" or a.startswith("orch_") for a in argv[1:3]):
        return True
    if not _interpreter(prog):
        return False
    for a in argv[1:6]:
        if a.startswith("-"):
            continue
        name = Path(a).name
        return name == "orch" or name.startswith("orch_") or "/orch_" in a
    return False


def _same_command(argv: list[str], commands: frozenset[str]) -> bool:
    """The process runs a managed service's own command: exactly, or behind its interpreter (a script with a
    shebang shows in ps as `/bin/sh /path/crash.sh`, or `/bin/sh -e /path/crash.sh` with a shebang flag).
    ps joins the words with spaces, so whole command lines are compared (a path may hold a space)."""
    if " ".join(argv) in commands:
        return True
    if len(argv) < 2 or not _interpreter(Path(argv[0]).name):
        return False
    i = 1
    while i < len(argv) - 1 and argv[i].startswith("-"):
        i += 1
    return " ".join(argv[i:]) in commands


def _processes(root: Path, skip: set[int], commands: frozenset[str] = frozenset()) -> list[dict]:
    cp = _tool(["ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,ppid=,tty=,lstart=,command="])
    if not cp or cp.returncode != 0:
        return []
    rows = {}
    for line in cp.stdout.splitlines():
        w = line.split()
        if len(w) < 9 or not w[0].isdigit() or not w[1].isdigit():
            continue
        rows[int(w[0])] = {"ppid": int(w[1]), "tty": w[2], "lstart": " ".join(w[3:8]), "argv": w[8:]}
    # Never this run itself or what started it, nothing orch started (and what those started), nothing with a
    # terminal (a person's shell or a helper's session is not a background job).
    mine, p = set(), os.getpid()
    while p in rows and p not in mine:
        mine.add(p)
        p = rows[p]["ppid"]
    mine.add(os.getpid())

    # orch's own add-on servers by the pids orch recorded for them (the command line alone can mislead, e.g. a
    # program path with a space in it), and the services orch keeps: neither they nor what they started are found.
    # A recorded add-on pid counts only while its command line still names orch: after a crash or a restart the
    # number can belong to another program.
    addons = _addon_pids()

    def from_orch(pid: int) -> bool:
        """orch started it, or a job orch keeps or the computer keeps (skip) runs it: its main process, the same
        command started again by launchd after a crash with a new pid, or anything those started, such as the
        `sleep` of a ticker (ORCH-847, ORCH-1130): never a found item."""
        seen = set()
        while pid in rows and pid not in seen:
            seen.add(pid)
            argv = rows[pid]["argv"]
            if (
                pid in skip
                or _is_orch(argv)
                or (pid in addons and "orch" in " ".join(argv).lower())
                or _same_command(argv, commands)
            ):
                return True
            pid = rows[pid]["ppid"]
        return False

    cand = [
        pid
        for pid, r in rows.items()
        if pid not in mine and r["tty"] in ("?", "??", "-") and not from_orch(pid)
    ]
    if sys.platform.startswith("linux"):
        cwds = {pid: c for pid in cand if (c := _cwd_linux(pid))}
    else:
        cwds = _cwds_lsof(cand)  # no lsof: no processes (see the module comment)
    base = root.resolve()
    items = []
    for pid in sorted(set(cwds) & set(cand)):  # only the candidates, whatever lsof answered
        try:
            cwds[pid].resolve().relative_to(base)
        except (ValueError, OSError):
            continue
        r = rows[pid]
        name = script_name(r["argv"])
        how = {"kind": "process", "pid": pid}
        items.append(
            _item(
                root,
                f"process:{pid}",
                name,
                True,
                _utc_from_ps(r["lstart"]),
                "A program running in this workspace folder",
                how,
                r["argv"],
                False,
            )
        )
    return items


# ---------------------------------------------------------------- the list


def scan(root: Path, processes: bool = False) -> list[dict]:
    """Every found job orch can take over (launchd / systemd), sorted by name. Reads only; an item already managed
    by orch is left out. Plain programs (tail, hand-run scripts) cannot be taken over and are no items: they are
    only counted by `others`, unless `processes` is set (adopt looks one up to explain why it cannot)."""
    if _test_home_on_real_account():
        units, pids = [], set()
    elif sys.platform == "darwin":
        units, pids = _launchd(root)
    elif sys.platform.startswith("linux"):
        units, pids = _systemd(root)
    else:
        return []
    done = _adopted(root)
    units = [u for u in units if u["id"] not in done]
    kept, commands = _managed(root)
    items = units + (_processes(root, pids | kept, commands) if processes else [])
    items.sort(key=lambda i: (i["name"].lower(), i["id"]))
    return items


def others(root: Path) -> int:
    """How many plain programs run in this workspace folder (shown as one line, never as items)."""
    if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        return 0
    _units, pids = _launchd(root) if sys.platform == "darwin" else _systemd(root)
    kept, commands = _managed(root)
    return len(_processes(root, pids | kept, commands))


def _addon_pids() -> set[int]:
    """Pids of orch's own add-on servers (every workspace) as orch recorded them when it started them. Read only."""
    try:
        from orch import services as core

        data = json.loads(core.running_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no core or no file: nothing recorded, the command line check still runs
        return set()
    if not isinstance(data, list):
        return set()
    return {e["pid"] for e in data if isinstance(e, dict) and isinstance(e.get("pid"), int) and e["pid"] > 0}


def _managed(root: Path) -> tuple[set[int], frozenset[str]]:
    """The services orch keeps (made or adopted): their main pids and the commands they run. Their processes,
    and what those start, are not found again, also while launchd brings a crashing one back with a new pid."""
    from . import drivers
    from .cli import _spec, _workspace_id

    pids: set[int] = set()
    argvs: set[str] = set()  # whole command lines, as ps shows them
    recs, _bad = store.load_all(root)
    if not recs:
        return pids, frozenset()
    try:
        drv = drivers.get()
        drv.check()
        wid = _workspace_id(root)
    except Refused:
        return pids, frozenset()
    for r in recs:
        try:
            spec = _spec(root, r, wid, strict=False)
        except Refused:
            continue
        # The command counts only while the person wants the service running (started, or starts by itself): a
        # stopped service's command run by hand is not orch's. An adopted job's words are only shown.
        wanted = store.read_state(root, r["id"]).get("running") is True or bool(r.get("auto"))
        if wanted and not spec.external:
            argvs.add(" ".join(spec.argv))
        try:
            st = drv.status(spec)
        except Refused:
            continue
        if st.running and st.pid:
            pids.add(st.pid)
    return pids, frozenset(argvs)


def note() -> str | None:
    """One plain sentence when this computer has no found list yet (Windows), else None."""
    return WINDOWS_NOTE if sys.platform == "win32" else None


def get(root: Path, fid: str) -> dict:
    if not isinstance(fid, str) or not (ID_RE.fullmatch(fid) or HASHED_ID.fullmatch(fid)):
        raise Refused(f"'{fid}' is not a found service. Run orch services found to see them.")
    for it in scan(root, processes=fid.startswith("process:")):
        if it["id"] == fid or (HASHED_ID.fullmatch(fid) and page_id(it["id"]) == fid):
            return it
    raise Refused(f"There is no found service {fid} (any more). Run orch services found to see them.")
