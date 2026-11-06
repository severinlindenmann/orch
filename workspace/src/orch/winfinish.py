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
import tempfile
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
    os.rename(probe, path)
    return True


say("waiting for orch to exit")
deadline = time.time() + job["wait"]
while not all(free(p) for p in job["free"]):
    if time.time() > deadline:
        say("RESULT fail: orch did not exit in time; nothing was changed. Run the command again.")
        sys.exit(1)
    time.sleep(0.5)
r = subprocess.run(job["uv"], capture_output=True, text=True)
if r.returncode != 0:
    say("uv failed: " + (r.stderr or r.stdout).strip()[-1500:])
    say("RESULT fail: the reinstall failed. Run it again: orch update")
    sys.exit(1)
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
        sys.exit(1)
say("RESULT ok: " + job["done"])
'''


def needed() -> bool:
    """A reinstall must wait until orch has exited (only on Windows)."""
    return sys.platform == "win32"


def log_path(home: Path) -> Path:
    return home / "finish.log"


def start(home: Path, uv_argv: list[str], then: list[list[str]], cwd: Path, done: str,
          registry: tuple[Path, str] | None = None) -> Path:  # fmt: skip
    """Start the finisher detached and return its log. `then`: orch commands run afterwards (in `cwd`)."""
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
        "registry": [str(registry[0]), registry[1]] if registry else None,
        "then": [{"argv": [str(py), "-P", "-m", "orch", *t], "cwd": str(cwd)} for t in then],
        "log": str(log_path(home)),
        "done": done,
    }
    home.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="orch-finish-"))
    (d / "finish.py").write_text(FINISHER, encoding="utf-8")
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    base = getattr(sys, "_base_executable", None) or sys.executable
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS, NEW_PROCESS_GROUP, NO_WINDOW
    subprocess.Popen(
        [base, "-I", str(d / "finish.py"), str(d / "job.json")],
        cwd=str(d),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
        env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
    )
    return log_path(home)
