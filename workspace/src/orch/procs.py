"""Small process facts shared by the ticket lock and the run lock."""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_run = subprocess.run  # module-local seam: tests must not patch subprocess.run for other threads


def orch_python_argv(*args: str) -> list[str]:
    """argv that runs this orch again. Always `-I -P`: Python must not put the current folder on sys.path
    (and ignores PYTHON* variables), or a planted orch.py / json.py in a workspace would run as the user.
    Every `-m orch` spawn uses this."""
    return [sys.executable, "-I", "-P", "-m", "orch", *args]


SELF = "orch:self"  # an orch_bin that means "this Python's own orch" (pagesession.SELF)


def orch_cmd(orch_bin: str | None = None) -> list[str]:
    """The argv prefix an add-on (or any caller) starts orch with: `orch_bin` (default `$ORCH_BIN`) when it is
    a test's fake or the orch command on macOS/Linux, else this Python's `-I -P -m orch` (ORCH-2138). On
    Windows the orch launcher (`orch` / `orch.exe`) is never started: a company computer may block .exe files,
    and an add-on runs in orch's own Python anyway. Without any orch on the PATH it is this Python as well."""
    b = os.environ.get("ORCH_BIN") if orch_bin is None else orch_bin
    if b == SELF:
        return orch_python_argv()
    if os.name == "nt":
        if not b or Path(b.replace("\\", "/")).name.lower() in ("orch", "orch.exe"):
            return orch_python_argv()
        return [b]
    if not b or b == "orch":
        import shutil

        return ["orch"] if shutil.which("orch") else orch_python_argv()
    return [b]


def python_command_line() -> str:
    """How a person or a helper types orch without the launcher: `"<python>" -m orch`."""
    return f'"{sys.executable}" -m orch'


def launcher_problem() -> str | None:
    """Windows only: "missing" when no orch launcher is on the PATH, "blocked" when it is there but does not
    start (a company rule that blocks .exe files); None when it works, and always None on macOS/Linux."""
    if os.name != "nt":
        return None
    import shutil

    exe = shutil.which("orch")
    if not exe:
        return "missing"
    try:
        r = _run([exe, "--version"], capture_output=True, timeout=15, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return "blocked"
    return None if r.returncode == 0 else "blocked"


def background_popen_kwargs() -> dict[str, int | bool]:
    """Start a background process without a visible Windows console; callers supply log streams.

    Windows: CREATE_NO_WINDOW gives the process a hidden console that its children inherit. Not
    DETACHED_PROCESS: Windows ignores CREATE_NO_WINDOW next to it, and a venv's python.exe is a launcher
    whose real-python child then allocates a NEW (visible) console, which is the stray terminal window."""
    if sys.platform == "win32":
        return {
            "creationflags": 0x00000200 | 0x08000000,  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
    return {"start_new_session": True, "stdin": subprocess.DEVNULL}


# ---- orch limits its own power (ORCH-2407) ------------------------------------------------------------
# Release 52 had an `orch needs` that started itself again without end and filled a computer until it had to
# be restarted (ORCH-2372). Three brakes, all here, so every background start of orch's own passes them:
#   1. one budget per workspace: at most `workspace.background_max` background tasks at once, each
#      holding a slot file in .orch/run/bg/ (a slot whose process is gone is taken over). The add-ons a
#      command asks for their needs have a pool of their own, BG_ASK_TIMES as large: one `orch needs` asks
#      all its add-ons side by side and never waits behind background work, yet many at once stay bounded;
#   2. a busy computer: while the 1-minute load per core is over `workspace.background_load`, background
#      work is not started (it is started by a later command);
#   3. no start from inside: a background process carries ORCH_BG_DEPTH and never starts another one.

BG_DEPTH = "ORCH_BG_DEPTH"  # set for every background process orch starts: how deep under a command it runs
BG_MAX_DEFAULT = 4  # background processes at once per workspace ([workspace] background_max)
BG_MAX_MOST = 64
BG_LOAD_DEFAULT = 1.5  # 1-minute load per core over which background work waits ([workspace] background_load)
BG_ASK_TIMES = 4  # add-ons asked at once (their `needs --json` children): this many times background_max
BG_OVER = 16  # slots of their own for a start a person asked for (never skipped, still counted)
BG_OLD = 600  # a slot older than this is checked for a pid that now belongs to another program
_BG_LOCK_WAIT = 1.0  # the longest a start waits for the slot lock; then it is skipped


def bg_depth() -> int:
    """0 in a command a person or a helper typed; 1 in a background process orch started; 2 in its child."""
    try:
        return max(0, int(os.environ.get(BG_DEPTH) or 0))
    except ValueError:
        return 1  # set, but not a number: counts as inside


def bg_env(env: dict | None = None) -> dict:
    """The environment of a background child: one level deeper than this process."""
    return {**(os.environ if env is None else env), BG_DEPTH: str(bg_depth() + 1)}


def bg_limits(root: Path | None) -> tuple[int, float]:
    """(background processes at once, load per core) as config.toml says, else the defaults. Never raises."""
    most, load = BG_MAX_DEFAULT, BG_LOAD_DEFAULT
    try:
        from orch import config

        table = config.read(Path(root)).get("workspace") if root is not None else None
    except Exception:  # noqa: BLE001  a file that cannot be read: the safe defaults
        table = None
    if isinstance(table, dict):
        m, lo = table.get("background_max"), table.get("background_load")
        if type(m) is int and 1 <= m <= BG_MAX_MOST:
            most = m
        if type(lo) in (int, float) and lo > 0:
            load = float(lo)
    return most, load


def _load_per_core() -> float | None:
    """The 1-minute load average per core; None where the system has none (Windows). Tests replace this."""
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):
        return None


def bg_busy(root: Path | None) -> bool:
    """True while this computer is too busy for background work. Windows has no load average: there only
    the budget counts. ORCH_NO_LOAD_HOLD=1 (test runners): never held back by the machine's load."""
    if os.environ.get("ORCH_NO_LOAD_HOLD") == "1":
        return False
    load = _load_per_core()
    return load is not None and load > bg_limits(root)[1]


def _bg_dir(root: Path) -> Path:
    return Path(root) / ".orch" / "run" / "bg"


@contextlib.contextmanager
def _bg_lock(root: Path):
    """The slot files are read and written by one process at a time. Yields False when the lock could not be
    had in _BG_LOCK_WAIT (the start is skipped). The lock ends with its process: never left behind."""
    d = _bg_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "lock", "a+b") as f:
        end = time.monotonic() + _BG_LOCK_WAIT
        got = False
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.monotonic() > end:
                    break
                time.sleep(0.01)
        try:
            yield got
        finally:
            if got and os.name == "nt":
                import msvcrt

                with contextlib.suppress(OSError):
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            # POSIX: closing the file ends the lock


def _slot_pid(slot: Path) -> int | None:
    try:
        return int(slot.read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _slot_held(slot: Path) -> bool:
    """True while the slot's process runs. A slot nobody can read counts as held (never over the limit); an
    old slot whose pid now belongs to a program that started after the slot was written is free."""
    try:
        age = time.time() - slot.stat().st_mtime
    except OSError:
        return False  # gone meanwhile
    pid = _slot_pid(slot)
    if pid is None:
        return age < BG_OLD  # half written, or damaged: held for a while, then taken over
    from orch import services

    if not services.pid_alive(pid):
        return False
    if age > BG_OLD:
        started = pid_started(pid)
        if started:
            with contextlib.suppress(ValueError):
                born = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
                if born > slot.stat().st_mtime + APPROX_SECONDS:
                    return False
    return True


def bg_count(root: Path, kind: str | None = None) -> int:
    """How many background tasks of this workspace run right now (slots whose process is alive): orch's own
    and the ones a person asked for. `kind="ask"`: the add-ons being asked for their needs right now."""
    try:
        slots = [s for s in _bg_dir(root).glob("*.slot") if (kind == "ask") == s.name.startswith("ask-")]
        return sum(1 for s in slots if _slot_held(s))
    except OSError:
        return 0


def bg_claim(root: Path, kind: str = "task") -> Path | None:
    """Take one free slot for a process about to start, or None when that pool is used up. The slot names
    this process until bg_bind hands it to the child. Pools: "task" (orch's own background work, at most
    background_max), "ask" (an add-on asked for its needs, BG_ASK_TIMES as many), "person" (a start a
    person asked for: its own slots, so it is never skipped and never takes a task's place). Never raises."""
    try:
        most = bg_limits(root)[0]
        size = {"task": most, "ask": most * BG_ASK_TIMES, "person": BG_OVER}[kind]
        name = "" if kind == "task" else f"{kind}-"
        with _bg_lock(root) as got:
            if not got:
                return None
            d = _bg_dir(root)
            for i in range(size):
                slot = d / f"{name}{i}.slot"
                if slot.exists() and _slot_held(slot):
                    continue
                slot.write_text(str(os.getpid()), encoding="ascii")
                return slot
    except OSError:
        pass
    return None


def bg_bind(slot: Path, pid: object) -> None:
    """The slot now belongs to the started child: held until that process ends. Never raises."""
    try:
        if type(pid) is int and pid > 1:
            slot.write_text(str(pid), encoding="ascii")
        else:
            slot.unlink(missing_ok=True)
    except OSError:
        pass


def bg_release(slot: Path | None, pid: int | None = None) -> None:
    """Give the slot back at once (the child `pid` has ended, or never started). Only while the slot still
    names that child or this process: one taken over by another start meanwhile is left alone. Without the
    lock it is left as well (a slot whose process is gone is free anyway). Never raises."""
    if slot is None:
        return
    try:
        with _bg_lock(slot.parent.parent.parent.parent) as got:
            if got and _slot_pid(slot) in (pid, os.getpid()):
                slot.unlink(missing_ok=True)
    except OSError:
        pass


def background_start(
    root: Path, argv: list[str], *, env: dict | None = None, person: bool = False, **popen
) -> bool:
    """THE way orch starts background work of its own (a refresh, a look, a check, a cleanup). True when it
    was started; False when not: this process is itself background work (it never starts more), the
    computer is busy, or the workspace's budget is used up. Callers treat False as "not now": a later
    command starts it. `person`: a start a person asked for (a sign-in they pressed) is never
    held back by the load or the budget, only counted. Raises what Popen raises."""
    if bg_depth() >= 1:
        return False
    if not person and bg_busy(root):
        return False
    slot = bg_claim(root, "person" if person else "task")
    if slot is None:
        return False
    try:
        p = subprocess.Popen(argv, env=bg_env(env), **popen)  # noqa: S603
    except BaseException:
        bg_release(slot)
        raise
    bg_bind(slot, getattr(p, "pid", None))
    if callable(getattr(p, "wait", None)):
        # a long-lived starter (a page's service) must take the ended child off the process table, or it
        # would look alive and hold its slot for as long as the starter runs; the slot is free at once
        threading.Thread(target=_bg_reap, args=(p, slot), daemon=True, name="orch-bg-reap").start()
    return True


def _bg_reap(p: subprocess.Popen, slot: Path) -> None:
    try:
        p.wait()
    except Exception:  # noqa: BLE001  nothing to wait for: the slot is free once its process is gone
        return
    bg_release(slot, getattr(p, "pid", None))


def power_words(root: Path) -> str:
    """One plain sentence for `orch doctor`: the limits and how much background work runs now."""
    most, load = bg_limits(root)
    n = bg_count(root)
    now = "none runs now" if n == 0 else f"{n} run{'s' if n == 1 else ''} now"
    per = _load_per_core()
    if os.environ.get("ORCH_NO_LOAD_HOLD") == "1":
        busy = " The load check is turned off (ORCH_NO_LOAD_HOLD)."
    elif per is None:
        busy = " This system reports no load, so only that limit counts."
    else:
        state = "over it: background work waits" if per > load else "under it"
        busy = f" It waits while the load per processor core is over {load:g} (now {per:.1f}, {state})."
    return f"orch runs at most {most} background tasks at once in this workspace ({now}).{busy}"


def _win_processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe file name) of every process, from a Toolhelp snapshot (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out: list[tuple[int, int, str]] = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _win_launcher_children(pid: int, table: list[tuple[int, int, str]]) -> list[int]:
    """The real-python child a venv launcher starts for itself: a direct child with the launcher's own image
    name (python.exe) and nothing else. Only when pid has exactly one such child; with more, which one is the
    launcher's is not certain and none is taken."""
    own = next((exe for p, _, exe in table if p == pid), None)
    if not own:
        return []
    same = [p for p, parent, exe in table if parent == pid and exe.lower() == own.lower()]
    return same if len(same) == 1 else []


def _win_taskkill(pid: int) -> None:
    _run(
        ["taskkill", "/PID", str(pid), "/F"],  # no /T: it would also end helpers the service started detached
        capture_output=True,
        timeout=5,
        check=True,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )


def stop_tree(pid: int, *, verified: Callable[[], bool]) -> bool:
    """Stop only a recorded service, after its caller's full identity check.

    Windows: the service and the real-python child its venv launcher starts, never the rest of the tree
    (taskkill /T would end merge queue runners and helpers the service started, which must keep working).
    Never walk up to a parent (which may not be ours). POSIX retains single-pid SIGTERM.
    A taskkill failure is surfaced so callers keep the record for a later stop attempt.
    """
    if type(pid) is not int or pid <= 1 or not verified():
        return False
    if sys.platform == "win32":
        try:
            try:
                targets = [pid, *_win_launcher_children(pid, _win_processes())]
            except (OSError, ValueError, AttributeError):
                targets = [pid]  # no process list: the recorded pid alone
            for target in reversed(targets):  # the child first, so the launcher does not start another
                _win_taskkill(target)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The service could not be stopped. Try again in a moment.") from exc
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return True


def wait_port_free(port: int, timeout: float = 5.0) -> bool:
    """Allow an exiting local server time to release its listening port before starting another."""
    end = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                pass
        except ConnectionRefusedError:
            return True
        except OSError:
            pass  # an inconclusive probe does not establish that the port is free
        remaining = end - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pid_started(pid: int) -> str | None:
    """Start time of a process as the OS reports it (guards against pid reuse), else None."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            k = ctypes.windll.kernel32
            k.OpenProcess.restype = wintypes.HANDLE
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(h, *(ctypes.byref(x) for x in (c, e, kt, ut))):
                    return None
                ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
                return _iso(ticks / 1e7 - 11644473600)
            finally:
                k.CloseHandle(h)
        try:
            r = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
            text = " ".join(r.stdout.split())
        except (OSError, subprocess.SubprocessError):  # no ps here (minimal Linux container)
            text = ""
        if not text:
            return _proc_started(pid)  # Linux /proc; None elsewhere or when the process is gone
        return _iso(time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y")))
    except Exception:
        return None


_btime: int | None = None
APPROX_SECONDS = 2  # start times of one pid compare within this (boot time drifts a second; ps has 1 s steps)


def _proc_started(pid: int) -> str | None:
    """Linux: start time from /proc (no ps, no locale: minimal containers have no procps), else None.
    Plain ISO like every stored start time; the boot time is read once per process so one process always
    sees one value."""
    global _btime
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])  # field 22 (starttime), after pid and comm
        if _btime is None:
            with open("/proc/stat", encoding="utf-8") as f:
                _btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return _iso(_btime + ticks // os.sysconf("SC_CLK_TCK"))
    except (OSError, IndexError, ValueError, StopIteration, AttributeError):
        return None


def same_start(a: str, b: str) -> bool:
    """Two start times of one pid are the same process: equal within APPROX_SECONDS.
    (A reused pid that close in time would need a full pid wraparound within 2 s.)"""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if a == b:
        return True
    try:
        fa, fb = (datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in (a, b))
    except ValueError:
        return False
    return abs((fa - fb).total_seconds()) <= APPROX_SECONDS


# Windows refuses to replace or delete a file another process has open (Python opens files without
# FILE_SHARE_DELETE), and our small JSON files are read lock-free all the time. That refusal is
# momentary, so it is waited out here, in the one place every replace/delete of such a file goes through.
_FILE_BUSY = os.name == "nt"
FILE_BUSY_SECONDS = 5.0


def replace(src, dst) -> None:
    """os.replace that waits out a reader holding the target open (Windows only)."""
    _wait_free(lambda: os.replace(src, dst))


def unlink(path) -> None:
    """Path.unlink(missing_ok=True) that waits out a reader holding the file open (Windows only)."""
    _wait_free(lambda: Path(path).unlink(missing_ok=True))


def _wait_free(op) -> None:
    end = time.monotonic() + FILE_BUSY_SECONDS
    while True:
        try:
            return op()
        except PermissionError:
            if not _FILE_BUSY or time.monotonic() > end:
                raise
            time.sleep(0.005)


_tokens: dict[int, str] = {}


def own_token() -> str:
    """What a lock file holds: our pid and start time, so a reused pid is not mistaken for the holder.
    Cached per pid, so a forked child does not claim its parent's token."""
    pid = os.getpid()
    if pid not in _tokens:
        _tokens[pid] = f"{pid} {pid_started(pid) or '-'}"
    return _tokens[pid]


def owner_dead(text: str) -> bool:
    """True only when the lock's holder is verifiably gone (pid dead, or the pid now has another start time).
    Anything we cannot read or verify counts as alive: never two holders."""
    from orch import services

    parts = text.split()
    try:
        pid = int(parts[0])
    except (IndexError, ValueError):
        return False
    if not services.pid_alive(pid):
        return True
    started = parts[1] if len(parts) > 1 and parts[1] != "-" else None
    now = pid_started(pid) if started else None
    return bool(started and now and not same_start(now, started))
