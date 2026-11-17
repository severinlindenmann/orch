"""Windows: the small keeper a service's scheduled task starts (`pythonw -P -m orch_services.keeper <file>`).

Task Scheduler starts a task at sign-in and on demand, but it does not start a program again after a crash, and a
console program would show a window. So the task starts this keeper (pythonw: no window), and the keeper:
- starts the program with a hidden console, output appended to the service's log,
- starts it again after a crash (exit code other than 0), after 2 seconds, longer when it keeps crashing,
- writes `<id>.run.json` next to its settings file: its own pid and the program's pid, each with its start time,
- holds the program in a job, so ending the keeper ends the program and everything it started,
- never starts the program again once the settings are gone (the service was removed).
Exit code 0 ends the service (like systemd's Restart=on-failure)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import winproc

FIRST_DELAY = 2.0
MAX_DELAY = 60.0
STEADY = 60.0  # a program that ran this long counts as healthy again: the next crash waits FIRST_DELAY


def run_file(settings: Path) -> Path:
    return settings.with_name(settings.stem + ".run.json")


def read_run(settings: Path) -> dict | None:
    try:
        d = json.loads(run_file(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _write_run(settings: Path, data: dict) -> None:
    p = run_file(settings)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    for _ in range(20):  # Windows: a reader may hold the file for a moment
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _note(log: Path, text: str) -> None:
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"[orch services {_now()}] {text}\n")
    except OSError:
        pass


def next_delay(delay: float, ran: float) -> float:
    if ran >= STEADY:
        return FIRST_DELAY
    return min(MAX_DELAY, max(FIRST_DELAY, delay * 2))


def keep(settings: Path, sleep=time.sleep) -> int:
    cfg = json.loads(settings.read_text(encoding="utf-8"))
    argv, cwd, log = list(cfg["argv"]), cfg["cwd"], Path(cfg["log"])
    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
    me, me_start = os.getpid(), winproc.started(os.getpid())
    old = read_run(settings)
    if old and old.get("keeper") != me and winproc.is_same(old.get("keeper"), old.get("keeper_start")):
        return 0  # one keeper per service: this one came second
    winproc.keep_children_with_me()
    idle = {"keeper": me, "keeper_start": me_start, "pid": None}
    _write_run(settings, idle)  # who I am, before any program starts: a stop finds me from now on
    log.parent.mkdir(parents=True, exist_ok=True)
    delay = FIRST_DELAY / 2  # the first crash waits FIRST_DELAY
    while True:
        if not settings.exists():
            return 0
        t0 = time.monotonic()
        try:
            with open(log, "ab") as out:
                child = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    creationflags=winproc.CREATE_NO_WINDOW if winproc.WIN else 0,
                )
        except OSError as e:
            _note(log, f"Could not start the program ({e.strerror or e}).")
            code = None
        else:
            started = winproc.started(child.pid)
            _write_run(settings, {**idle, "pid": child.pid, "pid_start": started, "since": _now()})
            code = child.wait()
            if code == 0:
                _write_run(settings, {**idle, "exit": 0})
                return 0
        delay = next_delay(delay, time.monotonic() - t0)
        _write_run(settings, {**idle, "exit": code})
        if code is not None:
            _note(log, f"The program stopped with code {code}; it starts again in {delay:.0f} seconds.")
        sleep(delay)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        return 2
    return keep(Path(args[0]))


if __name__ == "__main__":
    sys.exit(main())
