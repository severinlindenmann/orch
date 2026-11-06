"""Windows: reinstall orch after this orch has exited.

Windows does not let a program delete (or even rename) the files it runs from. `uv tool install --reinstall`
replaces orch's own tool folder, so when orch ran it, uv stopped halfway ("Access is denied") and left orch
broken (`No module named 'orch'`). On Windows orch therefore hands the reinstall to a small finisher: a
standalone script run by the base Python (outside the tool folder, it imports nothing from orch). It waits
until orch has exited and the folder is free, runs uv, saves the add-on list and runs the follow-up step
(e.g. turning the add-on on in the workspace). Its log: <orch home>/finish.log."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# The finisher. Kept free of orch imports: it runs while orch's own files are being replaced.
FINISHER = r'''
import json, os, subprocess, sys, time

job = json.load(open(sys.argv[1], encoding="utf-8"))
log = open(job["log"], "a", encoding="utf-8")


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


def main():
    busy()
    say("waiting for orch to exit")
    deadline = time.time() + job["wait"]
    while not all(free(p) for p in job["free"]):
        if time.time() > deadline:
            say("RESULT fail: orch did not exit in time; nothing was changed. Run the command again.")
            return 1
        busy()
        time.sleep(0.5)
    busy()
    try:
        r = subprocess.run(job["uv"], capture_output=True, text=True, timeout=job["uv_timeout"])
    except subprocess.TimeoutExpired:
        say("RESULT fail: uv took too long. Run it again: orch update")
        return 1
    busy()
    if r.returncode != 0:
        say("uv failed: " + (r.stderr or r.stdout).strip()[-1500:])
        say("RESULT fail: the reinstall failed. Run it again: orch update")
        return 1
    if job.get("registry"):
        path, data = job["registry"]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    for cmd in job["then"]:
        r = subprocess.run(cmd["argv"], cwd=cmd["cwd"], capture_output=True, text=True)
        say((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            say("RESULT fail: " + " ".join(cmd["argv"][3:]) + " failed (see above)")
            return 1
    say("RESULT ok: " + job["done"])
    return 0


code = 1
try:
    code = main()
except Exception:
    import traceback

    say("RESULT fail: " + traceback.format_exc())
finally:
    try:
        os.remove(job["pending"])
    except OSError:
        pass
sys.exit(code)
'''


PENDING_MAX_AGE = 600  # seconds without a sign of life: the finisher has died
UV_TIMEOUT = 480  # below PENDING_MAX_AGE: the mark is refreshed right before uv starts


def needed() -> bool:
    """A reinstall must wait until orch has exited (only on Windows)."""
    return sys.platform == "win32"


def log_path(home: Path) -> Path:
    return home / "finish.log"


def pending(home: Path) -> bool:
    """A finisher is still at work. Each job carries the whole add-on list, so a second one started now
    would undo the first (e.g. bring back an add-on that was just removed)."""
    import time

    try:
        return time.time() - (home / "finish.pending").stat().st_mtime < PENDING_MAX_AGE
    except OSError:
        return False


def start(home: Path, uv_argv: list[str], then: list[list[str]], cwd: Path, done: str,
          registry: tuple[Path, str] | None = None) -> Path:  # fmt: skip
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
        "then": [{"argv": [str(py), "-P", "-m", "orch", *t], "cwd": str(cwd)} for t in then],
        "log": str(log_path(home)),
        "done": done,
        "pending": str(home / "finish.pending"),
    }
    # In orch's own folder, not %TEMP% (which can be shared, e.g. C:\Windows\Temp for tasks).
    d = home / "finish"
    d.mkdir(parents=True, exist_ok=True)
    (d / "finish.py").write_text(FINISHER, encoding="utf-8")
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS, NEW_PROCESS_GROUP, NO_WINDOW
    try:
        (home / "finish.pending").write_text(str(os.getpid()), encoding="utf-8")
        _popen(
            [base, "-I", str(d / "finish.py"), str(d / "job.json")],
            cwd=str(d),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
            env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
        )
    except OSError as e:
        (home / "finish.pending").unlink(missing_ok=True)
        raise RuntimeError(f"could not start the finisher: {e}") from e
    return log_path(home)


def _popen(*args, **kw) -> None:
    """Tests replace this."""
    subprocess.Popen(*args, **kw)
