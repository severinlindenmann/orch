"""Update orch by itself (Settings > About & updates; off until a person turns it on).

The running dashboard calls tick() about once a minute (no daemon of its own). When the setting is on, it
asks the install source for a newer version (updateinfo: releases on main; a development build follows its
own branch) at most once an hour, and starts the same detached `orch update` the Update button runs, but
only at a quiet moment: no helper at work in any workspace of this machine, no update or service restart
under way and no click of a person still in progress. Not quiet: it looks again in a few minutes. Afterwards
(in the restarted dashboard) the outcome is kept as one note for Home: the new version and what changed, or
why it failed (orch then stays on the old version, and tries again some hours later).

Machine-wide, in the orch home: one install serves every workspace. Files: auto-update.json (the setting),
auto-update-state.json (next check, the update under way), auto-update-note.json (the note for Home)."""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from orch.errors import Refused

CHECK_EVERY = 3600  # seconds between two looks at the install source
RETRY_BUSY = 300  # not a quiet moment: look again after five minutes
RETRY_FAILED = 6 * 3600  # an update that failed: try again after six hours
QUIET_AFTER_CLICK = 120  # a person clicked in the dashboard less than two minutes ago: not quiet yet
NOTE_MAX_AGE = 14 * 86400  # an unread note is dropped after two weeks


def _home() -> Path:
    from orch import addons

    return addons.home()


def _read(name: str) -> dict:
    try:
        d = json.loads((_home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write(name: str, data: dict | None) -> None:
    p = _home() / name
    if data is None:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(data).encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------ the setting


def enabled() -> bool:
    return _read("auto-update.json").get("on") is True


def set_enabled(on: bool, by: str = "human:owner") -> bool:
    """Turn it on or off. Only a person turns it on (it installs code by itself); an agent may turn it off."""
    if on and by.startswith("agent:"):
        raise Refused("Only a person can turn on automatic updates (Settings > About & updates).")
    _write("auto-update.json", {"on": bool(on), "by": by[:80], "at": int(time.time())})
    if on:  # look soon after it was turned on, not in an hour
        st = _read("auto-update-state.json")
        st["next"] = 0
        _write("auto-update-state.json", st)
    return bool(on)


# ------------------------------------------------------------------ a quiet moment


def _helpers_at_work(roots) -> int:
    """Helpers working right now (a live claim) in these workspaces."""
    from orch import runs

    n = 0
    for root in roots:
        folder = runs.run_dir(Path(root)) / "tickets"
        try:
            files = sorted(folder.glob("t_*.json"))
        except OSError:
            continue
        for f in files:
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("run") and runs.state(rec) == "alive":
                n += 1
    return n


def _update_under_way() -> bool:
    """An `orch update` (or its Windows finisher) is running: its snapshot is fresh, or the finisher works."""
    from orch import addons, winfinish

    home = _home()
    try:
        snap = json.loads((home / "update-before.json").read_text(encoding="utf-8"))
        if time.time() - float(snap.get("time")) < addons.SNAPSHOT_MAX_AGE:
            return True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        return bool(winfinish.pending(home) or winfinish.updating(home))
    except Exception:  # noqa: BLE001 - unknown is not quiet
        return True


def _services_busy() -> bool:
    """Another orch process is starting, stopping or restarting services right now (it holds the lock)."""
    from orch import services

    try:
        with services.locked(timeout=0.5):
            return False
    except Exception:  # noqa: BLE001 - timed out: someone holds it
        return True


def busy_reason(root: Path, last_click: float | None = None, clicking: bool = False) -> str | None:
    """Why now is not a quiet moment (plain words for the log), or None. `last_click` (time.time()) and
    `clicking` come from the dashboard: a person's click still under way, or one a moment ago."""
    from orch import addons

    if clicking or (last_click and time.time() - last_click < QUIET_AFTER_CLICK):
        return "a person is using the dashboard"
    try:
        roots = addons._registered_workspaces(root)
    except Exception:  # noqa: BLE001
        roots = {Path(root).resolve()}
    n = _helpers_at_work(roots)
    if n:
        return f"{n} helper{'s are' if n > 1 else ' is'} working"
    if _update_under_way():
        return "an update is already running"
    if _services_busy():
        return "orch is restarting its services"
    return None


# ------------------------------------------------------------------ the note for Home


def note() -> dict | None:
    """The note Home shows after an automatic update, or None."""
    d = _read("auto-update-note.json")
    if d.get("state") not in ("updated", "failed") or not isinstance(d.get("at"), (int, float)):
        return None
    if time.time() - d["at"] > NOTE_MAX_AGE:
        _write("auto-update-note.json", None)
        return None
    from orch.services import _printable

    out = {
        "state": d["state"],
        "at": int(d["at"]),
        "from": _printable(str(d.get("from") or ""))[:60],
        "to": _printable(str(d.get("to") or ""))[:60],
        "changes": [_printable(str(c))[:120] for c in (d.get("changes") or [])[:6] if isinstance(c, str)],
    }
    if d["state"] == "failed":
        out["reason"] = _printable(str(d.get("reason") or ""))[:160]
    return out


def dismiss_note() -> None:
    _write("auto-update-note.json", None)


def _fail_reason(root: Path) -> str:
    try:
        from orch import pagelaunch, pagesession

        log = pagelaunch.key_dir(root, create=False) / "update.log"
        return pagesession._short_reason(log.read_text(encoding="utf-8", errors="replace")[-4000:])
    except Exception:  # noqa: BLE001
        return "it did not finish"


def _settle(root: Path, st: dict, now: float) -> str:
    """The update this tick started earlier has ended (or still runs): keep its outcome as the note."""
    from orch import pagelaunch, services, updateinfo

    a = st.get("attempt") or {}
    pid, at = a.get("pid"), a.get("at")
    at = at if isinstance(at, (int, float)) else 0
    if isinstance(pid, int) and services.pid_alive(pid) and now - at < pagelaunch.UPDATE_TIMEOUT + 120:
        return "updating"
    if _update_under_way() and now - at < pagelaunch.UPDATE_TIMEOUT + 120:
        return "updating"  # Windows: the finisher renames the tool environment after the runner exited
    have = updateinfo.installed()
    ok = bool(have["sha"]) and have["sha"] != a.get("from_sha")
    if ok:
        to = updateinfo.label(have["release"], have["sha"], a.get("ref") or "main")
        _write(
            "auto-update-note.json",
            {
                "state": "updated",
                "at": int(now),
                "from": a.get("from"),
                "to": to,
                "changes": a.get("changes"),
            },
        )
        st.update(next=now + CHECK_EVERY)
    else:
        _write(
            "auto-update-note.json",
            {
                "state": "failed",
                "at": int(now),
                "from": a.get("from"),
                "to": a.get("to"),
                "reason": _fail_reason(Path(a.get("root") or root)),
            },
        )
        st.update(next=now + RETRY_FAILED)
    st.pop("attempt", None)
    updateinfo.forget()
    return "updated" if ok else "failed"


# ------------------------------------------------------------------ the tick


def tick(
    root: Path, start, last_click: float | None = None, clicking: bool = False, now: float | None = None
) -> str:
    """One look (the dashboard calls it about once a minute). `start()` runs the detached `orch update` and
    returns its pid. Returns what happened: off | updating | updated | failed | later | current | unknown |
    waiting: <why> | started | error."""
    from orch import services, updateinfo

    now = time.time() if now is None else now
    st = _read("auto-update-state.json")
    if st.get(
        "attempt"
    ):  # an update this tick started: its outcome, even if the setting was turned off since
        out = _settle(root, st, now)
        if out != "updating":
            _write("auto-update-state.json", st)
        return out
    if not enabled():
        return "off"
    nxt = st.get("next")
    if isinstance(nxt, (int, float)) and now < nxt:
        return "later"
    info = updateinfo.info(use_cache=False)
    if info.get("update_available") is not True or not info.get("newest"):
        st["next"] = now + CHECK_EVERY
        _write("auto-update-state.json", st)
        return "current" if info.get("newest") else "unknown"
    why = busy_reason(root, last_click, clicking)
    if why:
        st["next"] = now + RETRY_BUSY
        _write("auto-update-state.json", st)
        return f"waiting: {why}"
    try:
        with services.locked(timeout=1):  # one dashboard of this machine starts it, never two
            st = _read("auto-update-state.json")
            if st.get("attempt"):
                return "updating"
            have, newest = info["installed"], info["newest"]
            st["attempt"] = {
                "at": int(now),
                "root": str(Path(root).resolve()),
                "from": have.get("label"),
                "from_sha": have.get("sha"),
                "to": newest.get("label"),
                "to_sha": newest.get("sha"),
                "ref": _ref(),
                "changes": list(info.get("changes") or [])[:6],
            }
            _write("auto-update-state.json", st)
            try:
                st["attempt"]["pid"] = int(start())
            except Exception:  # noqa: BLE001 - not started: a plain note, try again later
                st.pop("attempt", None)
                st["next"] = now + RETRY_FAILED
                _write("auto-update-state.json", st)
                _write(
                    "auto-update-note.json",
                    {
                        "state": "failed",
                        "at": int(now),
                        "from": have.get("label"),
                        "to": newest.get("label"),
                        "reason": "the update could not be started",
                    },
                )
                return "failed"
            _write("auto-update-state.json", st)
    except Exception:  # noqa: BLE001 - the lock timed out: not quiet
        st = _read("auto-update-state.json")
        st["next"] = now + RETRY_BUSY
        _write("auto-update-state.json", st)
        return "waiting: orch is restarting its services"
    return "started"


def _ref() -> str:
    try:
        from orch import addons

        return addons.ref()
    except Exception:  # noqa: BLE001
        return "main"


def status() -> dict:
    """For Settings and `orch config get update.auto`: on/off, the source it follows, the next look."""
    st = _read("auto-update-state.json")
    ref = _ref()
    return {
        "on": enabled(),
        "ref": ref[:100],
        "branch": ref != "main",  # a development build follows its own branch
        "updating": bool(st.get("attempt")),
    }
