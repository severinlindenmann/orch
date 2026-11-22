"""Meetings, live (ORCH-1195): a recorder way in with a "now" action (orch Companion) says when a call runs.

The page server asks it every few seconds while Meetings is on, keeps the last answer and writes "Meeting started"
and "Meeting ended" to the activity. A stale or missing answer never ends a call: it only says orch Companion is not
running; a call ends only on a fresh "idle" from the same recorder.

    .orch/addons/personal/meetings-now.json   {"state": "none|idle|call|ended|quiet", "app", "since", "ended",
                                               "way", "name", "checked", "events": [{"what", "app", "at"}]}
"""

from __future__ import annotations

import contextlib
import json
import shutil
import threading
import time
from pathlib import Path

from . import meetings as meetings_mod
from . import store
from . import ways as ways_mod
from .store import Refused

LOOK_EVERY = 5.0
MAX_EVENTS = 20
COMPANION_WAY = "companion"
BY = "recorder:orch-companion"
CONSENTS = ("asked", "agreed", "declined")
CONSENT_HINTS = {
    "asked": "Waiting for your answer in orch Companion: did everyone agree?",
    "agreed": "Everyone agreed.",
    "declined": "Not recorded: you said no.",
}
_LOOK = threading.Lock()


def _file(root: Path) -> Path:
    return store.base(root) / "meetings-now.json"


def saved(root: Path) -> dict:
    data = store._read_json(_file(root), {})
    return data if isinstance(data, dict) else {}


def _save(root: Path, data: dict) -> None:
    store._atomic_write(_file(root), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


RECHECK_EVERY = (
    60  # seconds: a live recorder that waits for the person (not installed yet) is checked this often
)


def live_recorders(root: Path) -> list[dict]:
    """Recorders that are on and can say whether a call runs now."""
    found = ways_mod.found(root)
    return [w for w in meetings_mod.recorders(root) if "now" in found.get(w["way"], {}).get("actions", {})]


def _recheck_waiting(root: Path) -> None:
    """A live recorder turned on before its app was installed waits as "needs your permission"; look again every
    minute instead of once a day, so it starts working soon after the person opens the app."""
    found = ways_mod.found(root)
    limit = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - RECHECK_EVERY))
    for w in ways_mod.status(root):
        if (
            w["part"] == meetings_mod.PART
            and w["on"]
            and w["status"] == "permission"
            and "now" in found.get(w["way"], {}).get("actions", {})
            and str(ways_mod.saved(root).get(w["way"], {}).get("checked") or "") < limit
        ):
            ways_mod.check(root, w["way"])


def add_companion(root: Path) -> dict:
    """Put the orch Companion way in into the ways folder. It stays off until the person turns it on."""
    dest = ways_mod.folder(root) / COMPANION_WAY
    if dest.exists():
        raise Refused(f"There is already a way in called {COMPANION_WAY}. See it: orch personal ways")
    src = Path(__file__).parent / "way_templates" / COMPANION_WAY
    dest.mkdir(parents=True)
    for f in sorted(src.iterdir()):
        if f.is_file() and f.suffix in (".py", ".toml"):
            shutil.copyfile(f, dest / f.name)
    return {"way": COMPANION_WAY, "dir": str(dest)}


def _answer(root: Path, way: str) -> dict:
    try:
        data = json.loads(ways_mod.ask(root, way, "now", {})["text"])
    except (Refused, ValueError):
        return {"state": "unavailable"}
    return data if isinstance(data, dict) else {"state": "unavailable"}


def look(root: Path) -> dict:
    """Ask the first live recorder once and move the saved state on. Returns the saved state."""
    with _LOOK:
        _recheck_waiting(root)
        rec = live_recorders(root)
        old = saved(root)
        if not rec:
            if old.get("state") != "none":
                old = {"state": "none", "events": old.get("events", [])}
                _save(root, old)
            return old
        w = rec[0]
        ans = _answer(root, w["way"])
        st = ans.get("state")
        if old.get("way") not in (None, w["way"]):
            # A call belongs to the recorder that reported it: another recorder starts from nothing.
            old = {"state": "idle", "events": old.get("events", [])}
        new = dict(old, way=w["way"], name=w["name"], checked=store.now())
        new.setdefault("events", [])
        # "quiet" remembers whether a call ran when the answers stopped; an ended call stays ended.
        was_call = old.get("state") == "call" or (old.get("state") == "quiet" and old.get("in_call") is True)
        if st == "call" and isinstance(ans.get("app"), str) and isinstance(ans.get("since"), str):
            app, since = ans["app"][:40], ans["since"][:32]
            if not (was_call and old.get("since") == since):  # a new call, not the same one seen again
                _event(root, new, "started", app)
            consent = ans.get("consent") if ans.get("consent") in CONSENTS else "asked"
            if consent != old.get("consent") or not (was_call and old.get("since") == since):
                if consent == "agreed":
                    store.log(
                        root, meetings_mod.PART, f"Everyone on the call agreed to record{' in ' + app}", BY
                    )
                elif consent == "declined":
                    store.log(root, meetings_mod.PART, f"Not recorded: you said no{' in ' + app}", BY)
            recording = ans.get("recording") is True and consent == "agreed"
            rec_since = ans.get("recording_since") if recording else None
            new.update(
                state="call",
                app=app,
                since=since,
                ended=None,
                consent=consent,
                in_call=None,
                recording=recording,
                recording_since=rec_since[:32] if isinstance(rec_since, str) else None,
            )
        elif st in ("idle", "inactive"):
            if was_call:
                _event(root, new, "ended", old.get("app") or "")
                new.update(
                    state="ended",
                    ended=store.now(),
                    consent=None,
                    in_call=None,
                    recording=False,
                    recording_since=None,
                )
            elif old.get("state") == "quiet":  # back after a pause without a call: the last call stays ended
                new.update(state="ended" if old.get("ended") else "idle", in_call=None)
            elif old.get("state") != "ended":
                new.update(state="idle", app=None, since=None, in_call=None)
        else:  # unavailable or missing: keep a running call as it is, only say orch Companion is not running
            new.update(state="quiet", in_call=was_call)
        if {k: v for k, v in new.items() if k != "checked"} != {
            k: v for k, v in old.items() if k != "checked"
        }:
            _save(root, new)
        return new


def _event(root: Path, data: dict, what: str, app: str) -> None:
    data["events"] = (data.get("events") or [])[-(MAX_EVENTS - 1) :] + [
        {"what": what, "app": app, "at": store.now()}
    ]
    words = "Meeting started" if what == "started" else "Meeting ended"
    store.log(root, meetings_mod.PART, f"{words}{' in ' + app if app else ''}", BY)


def live(root: Path) -> dict | None:
    """What Meetings shows about a call right now, or None when no live recorder is on."""
    if not live_recorders(root):
        return None
    d = saved(root)
    st = d.get("state") or "idle"
    out = {
        "state": st,
        "name": d.get("name") or "orch Companion",
        "app": d.get("app"),
        "since": d.get("since"),
    }
    if st == "call":
        # Whether the call is recorded matters most (everyone must agree), so it is in the line itself.
        out["consent"] = d.get("consent") or "asked"
        out["recording"] = d.get("recording") is True and out["consent"] == "agreed"
        out["words"] = (
            f"{d.get('app') or 'Teams'} call · {'recording' if out['recording'] else 'not recording'}"
        )
        if out["recording"] and d.get("recording_since"):
            out["since"] = d["recording_since"]
        out["hint"] = CONSENT_HINTS[out["consent"]]
        if out["consent"] == "agreed" and not out["recording"]:
            out["hint"] = "Everyone agreed, but nothing is recorded. Look in orch Companion on your Mac."
    elif st == "ended":
        out.update(words="Meeting ended", ended=d.get("ended"))
    elif st == "quiet":
        out.update(words=f"{out['name']} is not running.", hint="Open it on your Mac.")
    else:
        out["words"] = f"{out['name']} is watching for calls"
    return out


def look_loop(root: Path, stop: threading.Event, every: float = LOOK_EVERY) -> threading.Thread:
    """In the Personal page server: ask the live recorder every few seconds while Meetings is on."""

    def loop():
        while not stop.is_set():
            with contextlib.suppress(Exception):  # a broken recorder must not end the page server
                if store.settings(root)["parts"].get(meetings_mod.PART, {}).get("on"):
                    look(root)
            stop.wait(every)

    t = threading.Thread(target=loop, name="personal-meetings-live", daemon=True)
    t.start()
    return t
