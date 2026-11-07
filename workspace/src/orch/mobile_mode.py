"""Mobile mode (relay add-on): questions also go to the phone, and this computer stays awake.

State lives in .orch/run/mobile-mode.json (per machine, gitignored). A detached keeper process
(`orch relay mobile keeper`) holds the keep-awake assertion and ends when the state says off, the lease
runs out, or the state file belongs to another keeper. Only the keeper's own child is ever stopped.
"""

from __future__ import annotations

import contextlib
import os
import platform as _platform
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import keepawake, net, procs
from orch.errors import Refused
from orch.text import clean_untrusted

HOURS = (4, 8, 12, 24)
DEFAULT_HOURS = 12
TICK = 5  # seconds between keeper checks
HEARTBEAT = 60  # seconds between heartbeats to the relay
START_WAIT = 6.0
ENDED_WORDS = {
    "off": "Mobile mode was turned off.",
    "phone": "Mobile mode was turned off from your phone.",
    "lease": "Mobile mode ended after its time ran out.",
    "restart": "Mobile mode ended when the computer restarted.",
}


def _path(root: Path) -> Path:
    return root / ".orch" / "run" / "mobile-mode.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _read(root: Path) -> dict:
    d = net.read_json(_path(root), {})
    return d if isinstance(d, dict) else {}


def _write(root: Path, d: dict) -> None:
    net.write_json(_path(root), d)


def _hours(v) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise Refused(f"Pick one of {', '.join(map(str, HOURS))} hours.") from None
    if v not in HOURS:
        raise Refused(f"Pick one of {', '.join(map(str, HOURS))} hours.")
    return v


def default_hours(root: Path) -> int:
    v = _read(root).get("default_hours")
    return v if v in HOURS else DEFAULT_HOURS


def set_default_hours(root: Path, hours) -> int:
    d = _read(root)
    d["default_hours"] = _hours(hours)
    _write(root, d)
    return d["default_hours"]


def keeper_alive(d: dict) -> bool:
    pid, started = d.get("keeper_pid"), d.get("keeper_started")
    return bool(pid) and procs.pid_started(pid) is not None and procs.pid_started(pid) == started


def settle(root: Path, now: datetime | None = None) -> dict:
    """Read the state; a mode that is on but whose lease is over or whose keeper is gone is ended here
    (a reboot kills the keeper and leaves the file on). Returns the state."""
    d = _read(root)
    if not d.get("on"):
        return d
    now = now or _now()
    end = _parse(d.get("ends_at"))
    pid = d.get("keeper_pid")
    if end is not None and now >= end:
        return _end(root, d, "lease", now)
    if pid and not keeper_alive(d):
        return _end(root, d, "restart", now)
    if not pid and (_parse(d.get("since")) or now) < now - timedelta(seconds=30):
        return _end(root, d, "restart", now)  # the keeper never came up
    return d


def _end(root: Path, d: dict, reason: str, now: datetime | None = None) -> dict:
    d = {
        "default_hours": d.get("default_hours"),
        "on": False,
        "ended": {"at": _iso(now or _now()), "reason": reason, "text": ENDED_WORDS[reason]},
    }
    if d["default_hours"] is None:
        del d["default_hours"]
    _write(root, d)
    return d


def is_on(root: Path) -> bool:
    return bool(settle(root).get("on"))


def status(root: Path) -> dict:
    d = settle(root)
    out = {
        "on": bool(d.get("on")),
        "default_hours": default_hours(root),
        "hours_choices": list(HOURS),
        "awake": d.get("awake") if d.get("on") else None,
        "since": d.get("since") if d.get("on") else None,
        "ends_at": d.get("ends_at") if d.get("on") else None,
        "machine": d.get("machine") if d.get("on") else machine_name(),
        "ended": d.get("ended"),
    }
    return out


def machine_name() -> str:
    """One line of plain text, at most 60 characters: no control, bidi or zero-width characters."""
    name = " ".join(clean_untrusted(_platform.node().split(".")[0], 200).replace("\n", " ").split())
    return name[:60] or "this computer"


def payload(root: Path) -> dict:
    """The `mobile_mode` object the heartbeat carries (contracts/relay-api.md)."""
    d = settle(root)
    if not d.get("on"):
        out: dict = {"on": False}
        reason = (d.get("ended") or {}).get("reason")
        if reason in ("lease", "restart"):
            out["ended"] = reason
        elif reason:
            out["ended"] = "off"  # off and phone are both 'turned off by a person'
        return out
    return {
        "on": True,
        "since": d.get("since"),
        "ends_at": d.get("ends_at"),
        "machine": d.get("machine")[:60],
    }


def heartbeat(root: Path) -> None:
    """Tell the relay now (best effort: never fails the caller)."""
    from orch import relay

    with contextlib.suppress(Exception):
        relay.heartbeat(root, payload(root))


def routes_to_phone(root: Path) -> bool:
    """True when a new question should also go to the phones: mode on, relay add-on on and connected."""
    from orch import addons

    try:
        if not is_on(root) or "relay" not in addons.active(root):
            return False
        net.load_service(root, "relay")
    except Refused:
        return False
    return True


def turn_on(root: Path, hours=None, spawn=None) -> dict:
    """Start Mobile mode (a second call refreshes the lease). `spawn(root)` starts the keeper."""
    from orch import addons

    if "relay" not in addons.active(root):
        raise Refused(addons.not_on_message(root, "relay"))
    cur = settle(root)
    n = _hours(hours) if hours is not None else default_hours(root)
    now = _now()
    d = {
        "on": True,
        "since": cur.get("since") if cur.get("on") else _iso(now),
        "ends_at": _iso(now + timedelta(hours=n)),
        "hours": n,
        "machine": machine_name(),
        "default_hours": cur.get("default_hours") or DEFAULT_HOURS,
    }
    if cur.get("on") and keeper_alive(cur):
        d.update({k: cur[k] for k in ("keeper_pid", "keeper_started", "awake", "method") if k in cur})
        _write(root, d)
    else:
        _write(root, d)
        (spawn or _spawn_keeper)(root)
        end = time.monotonic() + START_WAIT
        while time.monotonic() < end and "awake" not in _read(root):
            time.sleep(0.1)
    heartbeat(root)
    return status(root)


def turn_off(root: Path, reason: str = "off") -> dict:
    d = _read(root)
    if d.get("on"):
        _end(root, d, reason if reason in ENDED_WORDS else "off")
    heartbeat(root)
    return status(root)


def acknowledge_ended(root: Path) -> None:
    d = _read(root)
    if d.pop("ended", None) is not None:
        _write(root, d)


def _spawn_keeper(root: Path) -> None:
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "orch", "relay", "mobile", "keeper"],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kw,
    )


# ---- the keeper process ------------------------------------------------------------------------


def run_keeper(
    root: Path, acquire=keepawake.acquire, sleep=time.sleep, now=_now, max_ticks: int | None = None
) -> str:
    """Hold the computer awake until the state says stop. Returns why it ended: off | lease | gone."""
    me = os.getpid()
    d = _read(root)
    if not d.get("on"):
        return "off"
    end = _parse(d.get("ends_at")) or now()
    hold = acquire(max(60, int((end - now()).total_seconds())), owner_pid=me)
    d = _read(root)
    if not d.get("on"):
        if hold:
            hold.release()
        return "off"
    d.update(
        keeper_pid=me,
        keeper_started=procs.pid_started(me),
        awake="ok" if hold else "could_not_keep_awake",
        method=hold.method if hold else None,
    )
    _write(root, d)
    why, ticks, last_hb = "gone", 0, 0.0
    try:
        while max_ticks is None or ticks < max_ticks:
            ticks += 1
            d = _read(root)
            if not d.get("on") or d.get("keeper_pid") != me:
                why = "off"
                break
            e = _parse(d.get("ends_at"))
            if e is not None and now() >= e:
                _end(root, d, "lease")
                why = "lease"
                break
            if hold is not None and not hold.alive():
                hold = acquire(max(60, int(((e or now()) - now()).total_seconds())), owner_pid=me)
                d["awake"] = "ok" if hold else "could_not_keep_awake"
                _write(root, d)
            if time.monotonic() - last_hb >= HEARTBEAT:
                last_hb = time.monotonic()
                heartbeat(root)
                with contextlib.suppress(Exception):
                    from orch import relay

                    relay.mobile_controls(root)
            sleep(TICK)
    finally:
        if hold:
            hold.release()
        if why != "off":
            heartbeat(root)
    return why
