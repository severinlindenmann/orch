"""One long-lived orch process that answers read commands for a server, instead of one new process per read
(ORCH-634).

The dashboard, the Factory watcher and Focus read through `orch <read> --json`. The hot reads are
answered in their own process (orch.reads); every other read used to start `python -I -P -m orch ...`: with
ten helpers working that was several hundred Python starts a minute, each loading about 400 modules. A caller
now keeps one worker: a child `python -I -P -m orch.readworker` started once, which runs the same
`orch.cli.main` for each request and sends back the exit code and what the command printed. The answer is the
command's own answer; the worker is only a way to not start Python again.

Wire format (the worker's own stdin and stdout, one JSON object per line):
  request  {"argv": [...], "root": "<workspace folder>"}
  answer   {"code": <exit code>, "out": "<what the command wrote on stdout>"}
The command itself never sees these pipes: the worker keeps private copies of them and points its own stdin
and stdout (the file descriptors, so a child process the command starts inherits them too) at the null device.

Only reads go here (the caller's choice: a write keeps its own process, so its `--by` and its caller's
environment stay what they were). A worker that does not answer in time is ended and the next read starts a
new one; a worker retires after RETIRE_AFTER answers or RETIRE_SECONDS, so no state of one command can live
long."""

from __future__ import annotations

import contextlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

RETIRE_AFTER = 2000  # answers per worker
RETIRE_SECONDS = 1800  # seconds a worker lives at most
IDLE_SECONDS = 120  # an idle worker (of any environment) is ended after this long without a read
# the spare workers of one environment (all but the one used last) are ended sooner: a burst of reads
# needs up to MAX_WORKERS, a quiet page one; each worker holds 50-100 MB (ORCH-609)
SPARE_IDLE_SECONDS = 30
REAP_EVERY = 10  # seconds between two looks of the reaper thread, which runs only while a worker is idle
STARTS = {
    "worker": 0,
    "answers": 0,
    "failed": 0,
}  # per process: workers started, reads answered, reads not answered


class _Worker:
    def __init__(self, env: dict):
        self.started = self.used = time.monotonic()
        self.answers = 0
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-P", "-m", "orch.readworker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        STARTS["worker"] += 1
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True, name="orch-readworker").start()

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except Exception:  # noqa: BLE001 - a closed or missing pipe: the worker is gone
            pass
        self.lines.put(None)

    def idle_too_long(self, limit: float | None = None) -> bool:
        return time.monotonic() - self.used > (IDLE_SECONDS if limit is None else limit)

    def alive(self) -> bool:
        return (
            getattr(self.proc, "poll", lambda: 0)() is None
            and self.answers < RETIRE_AFTER
            and time.monotonic() - self.started < RETIRE_SECONDS
        )

    def ask(self, root: Path, argv: list[str], timeout: float) -> tuple[int, str] | None:
        try:
            self.proc.stdin.write(json.dumps({"argv": list(argv), "root": str(root)}) + "\n")
            self.proc.stdin.flush()
            line = self.lines.get(timeout=timeout)
        except (OSError, ValueError, queue.Empty):
            self.stop()
            return None
        if line is None:
            self.stop()
            return None
        try:
            got = json.loads(line)
            code, out = int(got["code"]), got["out"]
        except (ValueError, KeyError, TypeError):
            self.stop()
            return None
        if not isinstance(out, str):
            self.stop()
            return None
        self.answers += 1
        return code, out

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.proc.stdin.close()
        with contextlib.suppress(Exception):
            self.proc.kill()
        with contextlib.suppress(Exception):
            self.proc.wait(timeout=2)


MAX_WORKERS = 3  # per environment: a slow read (a look at the network) does not hold up the others
_COND = threading.Condition()
_IDLE: dict[tuple, list[_Worker]] = {}  # environment -> workers waiting for a read
_BUSY: dict[tuple, int] = {}  # environment -> workers answering a read now
_REAPER: list[threading.Thread] = []  # the one reaper thread while it runs


def _env_key(env: dict) -> tuple:
    return tuple(sorted((k, v) for k, v in env.items() if k != "ORCH_ROOT"))


def worker_env(environ=None) -> dict:
    """The worker's environment: the caller's, without what would make Python load other code or point orch at
    another program (pagesession.child_env for `orch:self`)."""
    out = dict(os.environ if environ is None else environ)
    out.pop("ORCH_BIN", None)
    for k in [k for k in out if k.startswith(("LD_", "DYLD_", "PYTHON"))]:
        out.pop(k)
    out["PYTHONIOENCODING"] = "utf-8"
    return out


def _take(key: tuple, env: dict, timeout: float) -> _Worker | None:
    """An idle live worker for this environment, a new one while fewer than MAX_WORKERS are busy, else
    wait."""
    end = time.monotonic() + timeout
    with _COND:
        for w in _reap_locked():
            w.stop()
        while True:
            idle = _IDLE.setdefault(key, [])
            while idle:
                w = idle.pop()
                if w.alive():
                    _BUSY[key] = _BUSY.get(key, 0) + 1
                    return w
                w.stop()
            if _BUSY.get(key, 0) < MAX_WORKERS:
                _BUSY[key] = _BUSY.get(key, 0) + 1
                break
            left = end - time.monotonic()
            if left <= 0 or not _COND.wait(left):
                return None
    try:
        return _Worker(env)
    except Exception:  # noqa: BLE001 - no worker: the caller starts the command as before
        with _COND:
            _BUSY[key] -= 1
            _COND.notify()
        return None


def _reap_locked() -> list[_Worker]:
    """Take out (under _COND) every idle worker that retired, sat idle longer than IDLE_SECONDS, or is a spare
    idle longer than SPARE_IDLE_SECONDS; the caller stops them outside the lock."""
    out = []
    for ws in _IDLE.values():
        last = max(ws, key=lambda w: w.used, default=None)  # the one kept longest: the next read takes it
        for w in list(ws):
            if not w.alive() or w.idle_too_long() or (w is not last and w.idle_too_long(SPARE_IDLE_SECONDS)):
                ws.remove(w)
                out.append(w)
    return out


def _reaper() -> None:
    """Ends idle workers while nobody reads: without it a worker lived until the next read, for good when none
    came (a page closed, a quiet night)."""
    while True:
        time.sleep(REAP_EVERY)
        with _COND:
            gone = _reap_locked()
            last = not any(_IDLE.values())
            if last:
                _REAPER.clear()
        for w in gone:
            w.stop()
        if last:
            return


def _give_back(key: tuple, w: _Worker, ok: bool) -> None:
    with _COND:
        _BUSY[key] -= 1
        if ok and w.alive():
            w.used = time.monotonic()
            _IDLE.setdefault(key, []).append(w)
            if not _REAPER:
                t = threading.Thread(target=_reaper, daemon=True, name="orch-readworker-reaper")
                _REAPER.append(t)
                t.start()
        else:
            w.stop()
        _COND.notify()


def run(root: Path, argv: list[str], *, timeout: float = 10.0, environ=None) -> tuple[int, str] | None:
    """(exit code, stdout) of `orch <argv>` in `root`, answered by one of this process's workers; None when no
    worker could answer in time (the caller starts the command as before)."""
    env = worker_env(environ)
    key = _env_key(env)
    w = _take(key, env, timeout)
    if w is None:
        STARTS["failed"] += 1
        return None
    got = None
    try:
        got = w.ask(root, argv, timeout)
    except Exception:  # noqa: BLE001 - whatever went wrong, the worker is ended and its place given back
        got = None
    finally:
        _give_back(key, w, got is not None)
    if got is not None and got[0] == 0 and not got[1].strip():
        got = None  # a read that printed nothing: let the caller run the command itself
    STARTS["answers" if got is not None else "failed"] += 1
    return got


def workers() -> list[_Worker]:
    """Every idle worker of this process (tests)."""
    with _COND:
        return [w for ws in _IDLE.values() for w in ws]


def stop_all() -> None:
    with _COND:
        for ws in _IDLE.values():
            for w in ws:
                w.stop()
        _IDLE.clear()


# --- the worker side ---


def _answer(request: dict) -> dict:
    argv, root = request.get("argv"), request.get("root")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv) or not isinstance(root, str):
        return {"code": 2, "out": ""}
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
    code = 1
    # what a child process of the command writes (an add-on command runs as one) lands in this file: fd 1
    # points at it for this request only, then back at the null device
    spill = tempfile.TemporaryFile()
    os.dup2(spill.fileno(), 1)
    try:
        os.chdir(root)
        os.environ["ORCH_ROOT"] = root
        sys.argv = ["orch", *argv]
        from orch import cli

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:  # noqa: BLE001 - a crash of one command is that command's exit 1, never the worker's end
        code = 1
    finally:
        null = os.open(os.devnull, os.O_RDWR)
        os.dup2(null, 1)
        os.close(null)
    with contextlib.suppress(Exception):
        out.flush()
    spill.seek(0)
    child = spill.read()
    spill.close()
    text = (raw.getvalue() + child).decode("utf-8", "replace")
    # the same text a caller read from `orch` as a child in text mode (Windows writes \r\n)
    return {"code": int(code or 0), "out": text.replace("\r\n", "\n")}


def serve() -> int:
    """The worker: read one request per line until stdin closes."""
    proto_in = os.fdopen(os.dup(0), "r", encoding="utf-8")
    proto_out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 1)
    os.close(null)
    sys.stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115 - lives as long as the worker
    for line in proto_in:
        try:
            request = json.loads(line)
        except ValueError:
            request = {}
        answer = _answer(request if isinstance(request, dict) else {})
        proto_out.write(json.dumps(answer, ensure_ascii=False) + "\n")
        proto_out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
