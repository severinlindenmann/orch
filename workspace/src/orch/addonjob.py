"""The add-on job: several add-ons added in one background run, with its steps in a file a page can read.

The dashboard starts `orch addon add <names> --yes --job` detached (`launch`) and reads `addon-job.json`
(`read`) while it runs, also across the restart of the dashboard itself at its end. The file lives in the
machine-level orch home (one tool folder serves every workspace), is written atomically under a lock and
names the workspace that started it. The running command reports its steps through the functions below;
outside such a run (no `--job`) they do nothing.

A runner that died is found by its pid (stale check), a run that hangs is failed after 30 minutes, and a
result is kept 10 minutes so a second tab or the restarted page still sees it. On Windows the command ends
before the work (a finisher replaces orch once it has exited): the result then comes from the finisher's log
after the offset this run stored, like the Update button's status (pagelaunch.take_update_status)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from orch.errors import Refused

FILE = "addon-job.json"
LOCK = "addon-job.lock"
KEEP = 600  # seconds a finished or failed result is kept
HARD_STOP = 1800  # seconds: a run still going after 30 minutes counts as failed
RESTART_GRACE = 120  # seconds a restart may take after the command itself ended
ENV = "ORCH_ADDON_JOB"  # the job id launch() hands to the command it starts
LIVE = ("running", "restarting")
DONE = ("finished", "failed")
STEP_STATES = ("waiting", "running", "done", "failed", "skipped")

BUSY = "orch is already adding add-ons. You can add more when this is done."
UPDATING = "orch is being updated. You can add add-ons when this is done."
STOPPED_UNCHANGED = "The add-on install stopped unexpectedly. Nothing was changed."
STOPPED_CHANGED = "It stopped unexpectedly. Check the add-on list."
TOO_LONG = "The add-on install took too long and was stopped. Check the add-on list."
RESTART_FAILED = (
    "The add-ons are on, but some parts of orch did not start again. Run orch stop, then orch start."
)

_CURRENT: dict = {}  # {"id": ...} while this process reports a job (orch addon add --job)


# ------------------------------------------------------------------ the file


def _home() -> Path:
    from orch import addons

    return addons.home()


def _path() -> Path:
    return _home() / FILE


@contextlib.contextmanager
def _locked():
    from orch import home as orch_home

    h = _home()
    h.mkdir(parents=True, exist_ok=True)
    try:
        with orch_home._file_lock(h, LOCK):
            yield
    except Refused as e:
        if "key store" in str(e):  # the lock's own words: say it for this job
            raise Refused("orch is busy. Try again in a moment.") from None
        raise


def _load() -> dict | None:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("steps"), list) else None


def _store(job: dict) -> None:
    job["at"] = int(time.time())  # the last change: the stale check of a restart counts from here
    p = _path()
    tmp = p.with_name(f".{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job, f)
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _registry_hash() -> str:
    from orch import addons

    try:
        return hashlib.sha256(addons.registry_path().read_bytes()).hexdigest()
    except OSError:
        return ""


# ------------------------------------------------------------------ words and steps


def title(name: str) -> str:
    """The add-on's display title (its manifest's label), else its name capitalised."""
    from orch import addons

    return addons.display_title(name)


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def ordered(names, requires=None) -> list[str]:
    """`names` with every needed add-on before the one that needs it (else in the given order)."""
    from orch import addons

    names = list(dict.fromkeys(names))
    req = {n: [r for r in (requires or {}).get(n, addons.requires_of(n)) if r in names] for n in names}
    out: list[str] = []

    def put(n: str, seen: tuple) -> None:
        if n in out or n in seen:  # a loop: keep the given order
            return
        for r in req[n]:
            put(r, (*seen, n))
        out.append(n)

    for n in names:
        put(n, ())
    return out


def _steps(names: list[str]) -> list[dict]:
    titles = [title(n) for n in names]
    return [
        {"key": "ready", "label": f"Getting {_join(titles)} ready", "state": "waiting"},
        *(
            {"key": f"on:{n}", "label": f"Turning on {t}", "state": "waiting"}
            for n, t in zip(names, titles, strict=True)
        ),
        {"key": "restart", "label": "Restarting orch", "state": "waiting"},
    ]


def _new(root: Path, names: list[str], pid: int) -> dict:
    names = ordered(names)
    return {
        "v": 1,
        "id": f"j_{secrets.token_hex(4)}",
        "workspace": str(Path(root).resolve()),
        "pid": pid,
        "started": int(time.time()),
        "names": names,
        "state": "running",
        "steps": _steps(names),
        "failed": None,
        "reason": "",
        "ended": None,
        "registry": _registry_hash(),
    }


_PATHISH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s\\/]+){2,}[\\/]?")


def plain_reason(e: BaseException | str) -> str:
    """A short plain sentence for the page: the refusal's first line, with no log pointer, no path and no
    secret-looking value. Anything that is not an orch refusal gets a general sentence."""
    if isinstance(e, BaseException) and not isinstance(e, Refused):
        return "Something went wrong while adding the add-ons. Nothing more was changed."
    text = str(e).strip().removeprefix("Refused:").strip()
    text = (text.splitlines() or [""])[0]
    text = re.split(r"\s*Log:", text, maxsplit=1)[0]
    text = _PATHISH.sub("", text)
    text = re.sub(r"[A-Za-z0-9_\-]{32,}", "", text)  # long tokens
    text = " ".join(text.split())
    return text[:200] or "Adding the add-ons failed."


# ------------------------------------------------------------------ the page side


def _ended(job: dict, state: str, reason: str) -> dict:
    job["state"] = state
    job["reason"] = reason[:200]
    job["ended"] = int(time.time())
    return job


def _resolve(job: dict, now: float) -> tuple[dict, bool]:
    """The job as it really is now (stale, hung, a Windows finisher's result). Returns (job, changed)."""
    from orch import services, winfinish

    state = job.get("state")
    if state not in LIVE:
        return job, False
    started = job.get("started") if isinstance(job.get("started"), (int, float)) else now
    if isinstance(job.get("finish_offset"), int):  # Windows: the finisher does the work
        h = _home()
        if winfinish.pending(h) or winfinish.updating(h):
            if now - started > HARD_STOP:
                return _fail_steps(_ended(job, "failed", TOO_LONG)), True
            return job, False
        if winfinish.result_ok_since(h, job["finish_offset"]):
            for s in job["steps"]:
                if s.get("state") != "skipped":
                    s["state"] = "done"
            return _ended(job, "finished", ""), True
        _fail_steps(job)
        why = winfinish.fail_reason_since(h, job["finish_offset"]) or ""
        why = why.replace("background update", "add-on install").replace("Run it again", "Try again")
        return _ended(job, "failed", why or "The add-on install did not finish. Try again."), True
    if now - started > HARD_STOP:
        return _fail_steps(_ended(job, "failed", TOO_LONG)), True
    if services.pid_alive(job.get("pid")):
        return job, False
    at = job.get("at") if isinstance(job.get("at"), (int, float)) else started
    if state == "restarting" and now - at <= RESTART_GRACE:
        return job, False  # the command ended; the services restart a moment later
    unchanged = _registry_hash() == job.get("registry")
    _fail_steps(job)
    return _ended(job, "failed", STOPPED_UNCHANGED if unchanged else STOPPED_CHANGED), True


def _fail_steps(job: dict) -> dict:
    for s in job["steps"]:
        if s.get("state") == "running":
            s["state"] = "failed"
        elif s.get("state") == "waiting":
            s["state"] = "skipped"
    return job


def _current(now: float | None = None) -> dict | None:
    """Under the lock: the resolved job, stored when it changed; None when there is none or it expired."""
    now = time.time() if now is None else now
    job = _load()
    if job is None:
        return None
    job, changed = _resolve(job, now)
    ended = job.get("ended")
    if job.get("state") in DONE and (not isinstance(ended, (int, float)) or now - ended > KEEP):
        with contextlib.suppress(OSError):
            _path().unlink()
        return None
    if changed:
        with contextlib.suppress(OSError):
            _store(job)
    return job


def _shown(job: dict, root: Path | None) -> dict:
    out = {k: v for k, v in job.items() if k not in ("registry", "finish_offset", "at")}
    if root is not None:
        out["here"] = job.get("workspace") == str(Path(root).resolve())
    return out


def read(root: Path | None = None) -> dict | None:
    """The current job for a page, or None (no job, or its result is older than 10 minutes)."""
    try:
        with _locked():
            job = _current()
    except (Refused, OSError):
        job = _load()  # busy lock: show what is there
    return _shown(job, root) if job else None


def live() -> bool:
    """A job is running or restarting (an automatic update and a second launch wait for it)."""
    job = read()
    return bool(job and job.get("state") in LIVE)


def _update_running() -> bool:
    from orch import autoupdate

    try:
        return autoupdate._update_under_way()
    except Exception:  # noqa: BLE001 - unknown is not quiet
        return True


def launch(root: Path, names, orch_bin: str, env: dict) -> dict:
    """Start `orch addon add <names> --yes --job` detached in `root` and return the job at once. Refused
    while a job is live or orch updates. The job file exists before this returns."""
    from orch import addons, pagelaunch, pagesession

    names = list(dict.fromkeys(names or []))
    if not names or any(not isinstance(n, str) or not addons.NAME_RE.fullmatch(n) for n in names):
        raise Refused("Pick at least one add-on.")
    root = Path(root).resolve()
    with _locked():
        cur = _current()
        if cur and cur.get("state") in LIVE:
            raise Refused(BUSY)
        if _update_running():
            raise Refused(UPDATING)
        job = _new(root, names, 0)
        _store(job)
        try:
            log = pagelaunch.key_dir(root) / "addon-job.log"
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        except (Refused, OSError):
            fd = None
        kw: dict = {"start_new_session": True}
        if sys.platform == "win32":
            kw = {"creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        child = {**pagesession.child_env(env, orch_bin), ENV: job["id"]}
        try:
            p = _popen(
                [*pagesession.argv0(orch_bin), "addon", "add", *job["names"], "--yes", "--job"],
                cwd=str(root),
                env=child,
                stdin=subprocess.DEVNULL,
                stdout=fd if fd is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT if fd is not None else subprocess.DEVNULL,
                **kw,
            )
        except OSError:
            with contextlib.suppress(OSError):
                _path().unlink()
            raise Refused("orch could not start adding the add-ons. Try again.") from None
        finally:
            if fd is not None:
                os.close(fd)
        job["pid"] = p.pid
        _store(job)
    return _shown(job, root)


def _popen(argv: list[str], **kw):
    """Start the command and reap it when it ends (a dead child left unreaped would look alive). Tests
    replace this."""
    p = subprocess.Popen(argv, **kw)  # noqa: S603
    threading.Thread(target=p.wait, daemon=True).start()
    return p


# ------------------------------------------------------------------ the command side (orch addon add --job)


def attach(root: Path, names) -> dict:
    """This command reports into a job: the one launch() started for it, else a new one (refused while
    another is live)."""
    want = os.environ.get(ENV, "")
    with _locked():
        cur = _current()
        if cur and want and cur.get("id") == want:
            _CURRENT["id"] = want
            return cur
        if cur and cur.get("state") in LIVE:
            raise Refused(BUSY)
        if _update_running():
            raise Refused(UPDATING)
        job = _new(root, list(names), os.getpid())
        _store(job)
    _CURRENT["id"] = job["id"]
    return job


def detach() -> None:
    _CURRENT.clear()


def reporting() -> bool:
    return bool(_CURRENT.get("id"))


def _change(fn) -> None:
    """Apply fn to this command's job (if any, and not ended yet). Never raises: progress is never worth a
    failed install."""
    jid = _CURRENT.get("id")
    if not jid:
        return
    try:
        with _locked():
            job = _load()
            if not job or job.get("id") != jid or job.get("state") in DONE:
                return
            if fn(job) is not False:
                _store(job)
    except Exception:  # noqa: BLE001
        pass


def _step(job: dict, key: str) -> dict | None:
    return next((s for s in job["steps"] if s.get("key") == key), None)


def progress(key: str, state: str) -> None:
    """Set one step's state (`ready`, `on:<name>`, `restart`). Unknown steps are added before restart."""
    if state not in STEP_STATES or not reporting():
        return

    def fn(job):
        s = _step(job, key)
        if s is None:
            if not key.startswith("on:"):
                return False
            s = {"key": key, "label": f"Turning on {title(key[3:])}", "state": "waiting"}
            at = next(
                (i for i, x in enumerate(job["steps"]) if x.get("key") in ("restart", "rollback")), None
            )
            job["steps"].insert(len(job["steps"]) if at is None else at, s)
        s["state"] = state

    _change(fn)


def failing() -> None:
    """The step at work failed: later steps are skipped; the add-on it turned on is named."""

    def fn(job):
        for s in job["steps"]:
            if s.get("state") == "running" and s.get("key") != "rollback":
                s["state"] = "failed"
                if s["key"].startswith("on:") and not job.get("failed"):
                    job["failed"] = s["key"][3:]
            elif s.get("state") == "waiting":
                s["state"] = "skipped"

    _change(fn)


def rollback(state: str) -> None:
    """The rollback step (added on first use): running, done or failed."""

    def fn(job):
        s = _step(job, "rollback")
        if s is None:
            s = {"key": "rollback", "label": "Putting things back as they were", "state": "waiting"}
            job["steps"].append(s)
        if s["state"] != "failed":  # a failed part of the rollback stays failed
            s["state"] = state

    _change(fn)


def restarting() -> str | None:
    """The services restart after this command (restartlater): the job waits in `restarting`. Returns the
    job id to hand over, or None."""
    jid = _CURRENT.get("id")

    def fn(job):
        s = _step(job, "restart")
        if s is not None:
            s["state"] = "running"
        job["state"] = "restarting"

    _change(fn)
    return jid


def restart_failed(lines) -> bool:
    """The lines of _restart_updated/_start_added name a service that did not come back."""
    return any(
        ln.startswith("Restart ") or " did not start" in ln or ln.startswith("Could not start")
        for ln in lines
    )


def restarted(lines, jid: str | None = None) -> None:
    """The services restarted: restart done and the job finished, or failed with a plain reason."""
    bad = restart_failed(lines)

    def fn(job):
        s = _step(job, "restart")
        if s is not None:
            s["state"] = "failed" if bad else "done"
        for x in job["steps"]:
            if x.get("state") in ("waiting", "running") and x.get("key") not in ("restart", "rollback"):
                x["state"] = "done"
        _ended(job, "failed" if bad else "finished", RESTART_FAILED if bad else "")

    if jid is None:
        _change(fn)
        return
    _CURRENT["id"] = jid  # restartlater: a separate process hands the id over
    try:
        _change(fn)
    finally:
        detach()


def helper(jid: str) -> None:
    """restartlater took the job over: its pid stands in for the command's from now on, so a slow exit or
    restart is not read as a run that stopped (the stale check follows the process that still works)."""
    pid = os.getpid()

    def fn(job):
        job["pid"] = pid

    _CURRENT["id"] = jid
    try:
        _change(fn)
    finally:
        detach()


def deferred(offset: int) -> None:
    """Windows: the finisher does the work once this command has exited; its log after `offset` tells."""

    def fn(job):
        s = _step(job, "ready")
        if s is not None:
            s["state"] = "running"
        job["finish_offset"] = int(offset)

    _change(fn)


def finish() -> None:
    """The command ended well. A job handed to restartlater or to the Windows finisher is left to them."""

    def fn(job):
        if job.get("state") != "running" or isinstance(job.get("finish_offset"), int):
            return False
        for s in job["steps"]:
            if s.get("state") in ("waiting", "running"):
                s["state"] = "skipped" if s["key"] in ("restart", "rollback") else "done"
        _ended(job, "finished", "")

    _change(fn)


def fail(e: BaseException | str) -> None:
    """The command failed: the step at work failed, the rest skipped, the rollback (if it ran) done."""
    reason = plain_reason(e)

    def fn(job):
        for s in job["steps"]:
            if s.get("key") == "rollback" and s.get("state") == "running":
                s["state"] = "done"
            elif s.get("state") == "running":
                s["state"] = "failed"
                if s["key"].startswith("on:") and not job.get("failed"):
                    job["failed"] = s["key"][3:]
            elif s.get("state") == "waiting":
                s["state"] = "skipped"
        _ended(job, "failed", reason)

    _change(fn)
