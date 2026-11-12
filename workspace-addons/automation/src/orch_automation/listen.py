"""LS-09: listen for the relay. A long poll (`orch relay inbox --since <cursor> --wait 30`) wakes the loop when
something new arrived; the loop then handles it. The cursor and the "listening" state live in listen.json."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from . import orchcli
from .runner import sdir

NOT_LISTENING = "Not listening: the relay is not set up here"
PAUSE_OFF = 60  # seconds to sleep when the relay is off


def path(root: Path) -> Path:
    return sdir(root) / "listen.json"


def read(root: Path) -> dict:
    try:
        d = json.loads(path(root).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, RuntimeError):
        return {}


def _write(root: Path, **kw) -> None:
    cur = read(root)
    cur.update(kw)
    d = sdir(root)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".listen-")
    with os.fdopen(fd, "w") as f:
        json.dump(cur, f)
    os.replace(tmp, d / "listen.json")


class Listener:
    def __init__(self, root: Path, wake: threading.Event, wait: int = 30):
        self.root, self.wake, self.wait = root, wake, wait

    def step(self) -> float:
        """One poll. Sets `wake` when an arrival is not handled yet. Returns seconds to pause before the next."""
        if not orchcli.relay_ready(self.root):
            _write(self.root, listening=False, note=NOT_LISTENING, at=time.time())
            return PAUSE_OFF
        cursor = read(self.root).get("cursor")
        r = orchcli.relay_since(self.root, cursor if isinstance(cursor, int) else 0, self.wait)
        if r is None or r.get("warning"):  # unreachable relay: the CLI answers at once with the saved list
            _write(
                self.root,
                listening=False,
                note="Not listening: the relay could not be reached just now",
                at=time.time(),
            )
            return 10
        nxt = r.get("next")
        _write(
            self.root,
            listening=True,
            note="",
            at=time.time(),
            **({"cursor": nxt} if isinstance(nxt, int) else {}),
        )
        if any(isinstance(i, dict) and i.get("seen") is False for i in r.get("items") or []):
            self.wake.set()
        return 0

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                pause = self.step()
            except Exception:  # noqa: BLE001 - a listener must never take the scheduler down
                pause = 10
            if pause and stop.wait(pause):
                return
