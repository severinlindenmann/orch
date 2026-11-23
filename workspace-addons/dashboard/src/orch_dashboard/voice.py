"""Voice into the message box of the new Focus (ORCH-696, draft D feature 13): the page records a few seconds in the
browser and posts the sound here (POST /api/voice/words); this turns it into words through the connected relay
(orch.relay.transcribe: the relay keeps the speech key) and answers {text}. The words go back into the box for the
person to check and change; nothing is sent to a helper from here. Only while the relay add-on is on and connected
(R1.1: the page shows no microphone otherwise), and every refusal is one plain sentence."""

from __future__ import annotations

import json
from pathlib import Path

from .data import _addon_detail, run_orch

TYPES = (
    "audio/webm",
    "audio/mp4",
    "audio/m4a",
    "audio/wav",
)  # what a browser's MediaRecorder makes (and the relay takes)
MAX_AUDIO = 10 * 1024 * 1024  # the relay's limit; two minutes of Opus is far below

OFF = "Speaking needs the relay, and it is not on here."
NO_KEY = "Speaking is not set up on your relay, so type your message instead."
BUSY = "Too many tries in a minute; wait a moment, then speak again."
LONG = "That was too long; speak for at most two minutes at a time."
EMPTY = "No words were heard; try again a little closer to the microphone."
FAILED = "Your words could not be written down right now; try again or type them."
UNREACHABLE = "Your relay can't be reached right now, so type your message instead."


def relay_on(root: Path, orch_bin: str | None) -> bool:
    """The relay add-on is on and this folder is connected to a relay (the same facts the page reads)."""
    detail = _addon_detail(root, "relay")
    if not (isinstance(detail, dict) and detail.get("connected")):
        return False
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root) if orch_bin else None
    return any(
        isinstance(r, dict) and r.get("name") == "relay" and r.get("active") is True
        for r in (rows if isinstance(rows, list) else [])
    )


def words(root: Path, orch_bin: str | None, audio: bytes, mime: str) -> tuple[int, bytes, str]:
    """(http status, body, content type). 200 = {"text": ...} (text "" never: nothing heard is EMPTY)."""
    plain = "text/plain; charset=utf-8"
    kind = str(mime or "").split(";", 1)[0].strip().lower()
    if kind not in TYPES:
        return 415, b"This kind of recording can't be turned into words.", plain
    if not relay_on(root, orch_bin):
        return 409, OFF.encode(), plain
    try:
        from orch import relay
        from orch.errors import Refused
    except ImportError:
        return 503, FAILED.encode(), plain
    if not hasattr(relay, "transcribe"):  # an older orch under this dashboard
        return 503, FAILED.encode(), plain
    try:
        out = relay.transcribe(root, audio, kind)
    except Refused as e:
        status = getattr(e, "status", None)
        if status == 503:
            return 503, NO_KEY.encode(), plain
        if status == 429:
            return 429, BUSY.encode(), plain
        if status == 413:
            return 413, LONG.encode(), plain
        if status == 422:
            return 422, EMPTY.encode(), plain
        if status is None:  # the relay did not answer at all (down, no network): say so, not "try again"
            return 503, UNREACHABLE.encode(), plain
        return 502, FAILED.encode(), plain
    except OSError:
        return 503, UNREACHABLE.encode(), plain
    except ValueError:
        return 502, FAILED.encode(), plain
    text = str(out.get("text") or "").strip()
    if not text:
        return 422, EMPTY.encode(), plain
    return 200, json.dumps({"text": text}).encode(), "application/json"
