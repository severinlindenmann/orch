"""Windows: reinstall orch after this orch has exited.

Windows does not let a program delete (or even rename) the files it runs from. `uv tool install --reinstall`
replaces orch's own tool folder, so when orch ran it, uv stopped halfway ("Access is denied") and left orch
broken (`No module named 'orch'`). On Windows orch therefore hands the reinstall to a small finisher: a
standalone script run by the base Python (outside the tool folder, it imports nothing from orch). It waits
until orch has exited and the folder is free, runs uv, saves the add-on list and runs the follow-up step
(e.g. turning the add-on on in the workspace). Its log: <orch home>/finish.log.

The entry guard reads <orch home>/finish.updating (a decimal owner PID), beside finish.pending and
finish/job.json. The finisher holds it from before the folder probe/reinstall through RESULT ok/fail,
and removes it in finally. Dead owners or markers older than 15 minutes are ignored. POSIX holds the
same marker around its in-place package reinstall. The top-level orch_entry checks both ORCH_HOME and
the account's ~/.orch-tool (orch may reject an untrusted override). Internal `python -m orch` follow-up
commands deliberately remain usable while the finisher owns the marker."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

from orch_entry import marker_path, updating

# The finisher. Kept free of orch imports: it runs while orch's own files are being replaced.
FINISHER = r'''
import json, os, subprocess, sys, time

job = json.load(open(sys.argv[1], encoding="utf-8"))
job.setdefault("updating", os.path.join(os.path.dirname(job["pending"]), "finish.updating"))
log = open(job["log"], "a", encoding="utf-8")
registry_written = False
registry_before = None
final_line = None
stopped = []  # workspaces whose services this finisher stopped: they are started again at the end


def say(text):
    log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    log.flush()


def free(path):
    """Nothing runs from `path` any more: Windows lets us rename it (and we rename it straight back)."""
    if not os.path.exists(path):
        return True
    probe = path + ".free-check"
    try:
        os.rename(path, probe)
    except OSError:
        return False
    for _ in range(40):  # never leave orch's folder under the probe name
        try:
            os.rename(probe, path)
            return True
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("could not rename " + probe + " back to " + path + ": rename it back by hand")


def busy():
    """Keep the pending mark fresh while this finisher works (orch refuses a second job meanwhile)."""
    try:
        os.utime(job["pending"])
    except OSError:
        pass


def result(text):
    """The RESULT line is written last, after the services are back (the page waits for it)."""
    global final_line
    final_line = "RESULT " + text


def orch(verb, *args, cwd=None):
    r = subprocess.run([job["py"], "-I", "-P", "-m", "orch", verb, *args], cwd=cwd, capture_output=True,
                       text=True, timeout=120)
    return r


def stop_services():
    """The dashboard and the other add-on services run from the tool folder: stop them like `orch stop`."""
    for ws in job.get("services") or []:
        try:
            r = orch("stop", ws, cwd=ws)
            say("stopped the services in " + ws + (" (exit %d)" % r.returncode if r.returncode else ""))
            stopped.append(ws)
        except Exception as e:  # keep going: the folder check below says if something still runs
            say("could not stop the services in " + ws + ": " + str(e)[:200])
            stopped.append(ws)


def start_services():
    for ws in stopped:
        try:
            r = orch("start", "--no-open", cwd=ws)
            say("started the services in " + ws + " again" if r.returncode == 0
                else "could not start the services in " + ws + ": " + (r.stderr or r.stdout).strip()[-300:])
        except Exception as e:
            say("could not start the services in " + ws + ": " + str(e)[:200])


def main():
    global registry_written, registry_before
    with open(job["updating"], "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    busy()
    if job.get("services"):
        time.sleep(job.get("stop_delay", 3))  # the update that started us is just ending
        stop_services()
    say("waiting for orch to exit (pid %d; folders: %s)" % (os.getpid(), ", ".join(job["free"])))
    deadline = time.time() + job["wait"]
    while True:
        busy_paths = [p for p in job["free"] if not free(p)]
        if not busy_paths:
            break
        if time.time() > deadline:
            result("fail: still in use after %ds: %s. Nothing was changed. Run the command again."
                   % (job["wait"], ", ".join(busy_paths)))
            return 1
        busy()
        time.sleep(0.5)
    busy()
    try:
        env = dict(os.environ)
        env.update(job.get("env") or {})  # e.g. UV_TOOL_DIR pinned to where the person installed orch
        r = subprocess.run(job["uv"], capture_output=True, text=True, timeout=job["uv_timeout"], env=env)
    except subprocess.TimeoutExpired:
        result("fail: uv took too long. Run it again: orch update")
        return 1
    busy()
    if r.returncode != 0:
        say("uv failed: " + (r.stderr or r.stdout).strip()[-1500:])
        result("fail: the reinstall failed. Run it again: orch update")
        return 1
    if job.get("record"):  # the reinstall drops the install record: put it back
        rpath, rtext = job["record"]
        with open(rpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(rtext)
    if job.get("registry"):
        path, data = job["registry"]
        if os.path.exists(path):
            with open(path, "rb") as f:
                registry_before = f.read()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
        registry_written = True
    for cmd in job["then"]:
        r = subprocess.run(cmd["argv"], cwd=cmd["cwd"], capture_output=True, text=True)
        say((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            result("fail: " + " ".join(cmd["argv"][3:]) + " failed (see above)")
            return 1
    result("ok: " + job["done"])
    return 0


code = 1
try:
    code = main()
except Exception:
    import traceback

    result("fail: " + traceback.format_exc())
finally:
    try:
        os.remove(job["updating"])
    except OSError:
        pass
    if code != 0 and registry_written:
        path = job["registry"][0]
        if registry_before is None:
            os.remove(path)
        else:
            with open(path, "wb") as f:
                f.write(registry_before)
    if code != 0 and job.get("consents"):  # the consents this install recorded turn nothing on later
        try:
            cpath, wid, names = job["consents"]
            with open(cpath, encoding="utf-8") as f:
                items = json.load(f)
            items = [e for e in items if not (e.get("workspace_id") == wid and e.get("name") in names)]
            with open(cpath + ".tmp", "w", encoding="utf-8") as f:
                f.write(json.dumps(items, indent=2))
            os.replace(cpath + ".tmp", cpath)
        except Exception:
            say("could not drop the consents: " + str(job["consents"]))
    try:
        start_services()  # also after a failure: what ran before runs again
    except Exception:
        pass
    if final_line:
        say(final_line)
    try:
        os.remove(job["pending"])
    except OSError:
        pass
sys.exit(code)
'''


PENDING_MAX_AGE = 600  # seconds without a sign of life: the finisher has died
UV_TIMEOUT = 480  # below PENDING_MAX_AGE: the mark is refreshed right before uv starts


class Busy(RuntimeError):
    """Another finisher is still at work."""


def needed() -> bool:
    """A reinstall must wait until orch has exited (only on Windows)."""
    return sys.platform == "win32"


def result_ok_since(home: Path, offset: object) -> bool:
    """Did the finisher log `RESULT ok` (and no `RESULT fail`) after byte `offset` of finish.log?
    Bounded read; a bad offset or an unreadable log counts as not ok."""
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return False
    try:
        with log_path(home).open("rb") as log:
            log.seek(offset)
            result = log.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return False
    return "RESULT ok:" in result and "RESULT fail:" not in result


def fail_reason_since(home: Path, offset: object) -> str:
    """A plain reason for the page, from the `RESULT fail:` line the finisher logged after `offset`."""
    default = "The background update failed. Run it again."
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return default
    try:
        with log_path(home).open("rb") as log:
            log.seek(offset)
            text = log.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return default
    line = next((x for x in text.splitlines() if "RESULT fail:" in x), "")
    why = line.split("RESULT fail:", 1)[-1].strip()
    if "still in use" in why:
        return "orch was still running, so nothing was changed. Run the update again."
    if "took too long" in why:
        return "The reinstall took too long. Run the update again."
    if "reinstall failed" in why:
        return "The reinstall failed. Run the update again."
    if why:
        return "The background update failed; nothing more was changed. Run it again."
    return default


def log_path(home: Path) -> Path:
    return home / "finish.log"


def pending(home: Path) -> bool:
    """A finisher is still at work. Each job carries the whole add-on list, so a second one started now
    would undo the first (e.g. bring back an add-on that was just removed). The mark holds the finisher's
    process id: a finisher that died (e.g. ended with the SSH session that started it) does not block."""
    import time

    mark = home / "finish.pending"
    try:
        fresh = time.time() - mark.stat().st_mtime < PENDING_MAX_AGE
        text = mark.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not fresh:
        return False
    return not text.isdigit() or _alive(int(text))


def _alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def start(home: Path, uv_argv: list[str], then: list[list[str]], cwd: Path, done: str,
          registry: tuple[Path, str] | None = None, extra: dict | None = None) -> Path:  # fmt: skip
    """Start the finisher detached and return its log. `then`: orch commands run afterwards (in `cwd`)."""
    base = getattr(sys, "_base_executable", None)
    if not base or Path(base).resolve().is_relative_to(Path(sys.prefix).resolve()):
        # the finisher must not run from orch's own folder: it would keep that folder locked
        raise RuntimeError("no Python outside orch's tool folder to finish the install with")
    env_dir = Path(sys.prefix)  # the uv tool folder this orch runs from
    py = env_dir / "Scripts" / "python.exe"
    free = [str(env_dir)]
    launcher = Path(sys.argv[0])
    if launcher.suffix.lower() == ".exe" and launcher.is_file():
        free.append(str(launcher))  # orch.exe in uv's bin folder: uv replaces it too
    job = {
        "uv": uv_argv,
        "free": free,
        "wait": 120,
        "uv_timeout": UV_TIMEOUT,
        "registry": [str(registry[0]), registry[1]] if registry else None,
        "env": (extra or {}).get("env"),
        "record": (extra or {}).get("record"),
        "consents": (extra or {}).get("consents"),  # [consent.json, workspace id, names]: dropped on failure
        "then": [{"argv": [str(py), "-I", "-P", "-m", "orch", *t], "cwd": str(cwd)} for t in then],
        "py": str(py),
        "services": [str(w) for w in (extra or {}).get("services") or []],
        "log": str(log_path(home)),
        "done": done,
        "pending": str(home / "finish.pending"),
        "updating": str(marker_path(home)),
    }
    # In orch's own folder, not %TEMP% (which can be shared, e.g. C:\Windows\Temp for tasks).
    d = home / "finish"
    d.mkdir(parents=True, exist_ok=True)
    (d / "finish.py").write_text(FINISHER, encoding="utf-8")
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS, NEW_PROCESS_GROUP, NO_WINDOW
    breakaway = (
        0x01000000  # CREATE_BREAKAWAY_FROM_JOB: outlive the job (e.g. an SSH session) that started orch
    )
    kw = dict(
        cwd=str(d),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
    )
    argv = [base, "-I", str(d / "finish.py"), str(d / "job.json")]
    mark = home / "finish.pending"
    _claim(home, mark)  # no second job from here on
    try:
        try:
            pid = _popen(argv, creationflags=flags | breakaway, **kw)
        except OSError:  # the job does not allow breaking away: start it inside the job
            pid = _popen(argv, creationflags=flags, **kw)
        mark.write_text(str(pid), encoding="utf-8")
    except Exception as e:  # any failure: free the mark, or it would block installs for 10 minutes
        mark.unlink(missing_ok=True)
        raise RuntimeError(f"could not start the finisher: {e}") from e
    return log_path(home)


def _claim(home: Path, mark: Path) -> None:
    """Create the pending mark atomically (two orch commands at the same moment: only one gets it). A mark
    left by a finisher that is gone is taken over."""
    for _ in range(2):
        try:
            fd = os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if pending(home):
                raise Busy("an add-on install or update is still finishing in the background") from None
            mark.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("starting")
        return
    raise Busy("an add-on install or update is still finishing in the background")


def _popen(argv: list[str], **kw) -> int:
    """Start the finisher; its process id. Tests replace this."""
    return subprocess.Popen(argv, **kw).pid


@contextlib.contextmanager
def replacing(home: Path):
    """POSIX in-place reinstall: same PID marker and RESULT-before-release as Windows."""
    home.mkdir(parents=True, exist_ok=True)
    mark = marker_path(home)
    if updating(home):
        raise Busy("orch is still updating, try again in a moment.")
    mark.write_text(str(os.getpid()), encoding="utf-8")
    result = "fail"
    try:
        yield
        result = "ok"
    finally:
        try:
            with log_path(home).open("a", encoding="utf-8") as log:
                log.write(f"RESULT {result}: package reinstall\n")
        finally:
            mark.unlink(missing_ok=True)
