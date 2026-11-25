"""Actions meetings / meeting: the calls orch Companion recorded, with their transcript (ORCH-1269).

Companion writes, per recording (ORCH-1267, ORCH-1268):
  recordings/<id>/info.json        {"v":1,"id","app","started","ended","state":"recording|done|stopped",
                                    "consent":{"answer":"agreed","at"},"for":[<workspace>..]}  a hint, no audio
  recordings/<id>/pick.json        {"v":1,"for":[<workspace>..],"at"}  the workspaces the person picked after the
                                    call; a call made for one workspace only goes to it without a question
  recordings/<id>/transcript.json  {"v":1,"id","state":"waiting|done|failed","problem","started","minutes",
                                    "lines":[{"start","end","who":"me|others","text"}]}
A call is a meeting once its transcript is done. A call still being recorded or transcribed, or whose transcript
failed, is listed under "pending" with plain words so Meetings can say so. A workspace sees only the calls made
while it used Companion, and of those only the ones the person gave it: nothing at all, not even the time, before
the person picked in Companion. Nothing is written here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone

import companion_files

ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MAX_INFO = 16 * 1024
MAX_TRANSCRIPT = 16 * 1024 * 1024
MAX_LIST = 50
PAGE = 500
WHO = {"me": "Me", "others": "Others"}
PENDING_WORDS = {
    "recording": "Being recorded.",
    "waiting": "Being transcribed. It arrives here when the transcript is ready.",
    "failed": "The transcript could not be made. The recording is kept.",
}


def _read(path, limit: int):
    """One JSON object from a plain file no larger than limit, else None."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        with open(path, "rb") as f:
            data = json.loads(f.read(limit).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("v") == 1 else None


def _when(v):
    """A time with its zone (a time without one counts as UTC), else None."""
    try:
        # a closing Z is spelled out: the python3 that comes with macOS (3.9) cannot read it
        t = (
            datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
            if isinstance(v, str)
            else None
        )
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t and t.tzinfo is None else t  # noqa: UP017 (runs on the Mac python3)


def _base():
    base = companion_files.home() / "recordings"
    return base if base.is_dir() and not base.is_symlink() and not base.parent.is_symlink() else None


def _ok(folder) -> bool:
    return bool(ID.fullmatch(folder.name)) and folder.is_dir() and not folder.is_symlink()


def _folders():
    base = _base()
    return [p for p in base.iterdir() if _ok(p)] if base else []


def _call(folder):
    """(row, state, problem, transcript) of one recording, or None when it is not a usable recording."""
    info = _read(folder / "info.json", MAX_INFO)
    if not info or info.get("id") != folder.name:
        return None
    consent = info.get("consent") if isinstance(info.get("consent"), dict) else {}
    if consent.get("answer") != "agreed":
        return None  # Companion records only after everyone agreed; anything else is never shown
    made_for = (
        [w for w in info.get("for") or [] if isinstance(w, str)] if isinstance(info.get("for"), list) else []
    )
    if companion_files.me() not in made_for:
        return None  # made while this workspace did not use Companion
    pick = _read(folder / "pick.json", MAX_INFO)
    picked = (
        [w for w in pick.get("for") or [] if isinstance(w, str)]
        if pick and isinstance(pick.get("for"), list)
        else None
    )
    if picked is None and len(made_for) == 1:
        picked = made_for
    if picked is None or companion_files.me() not in picked:
        return None  # not picked yet (Companion asks), or the person gave it to another workspace
    started = _when(info.get("started"))
    if not started:
        return None
    ended = _when(info.get("ended"))
    app = info.get("app") if isinstance(info.get("app"), str) and info["app"] else "Call"
    row = {
        "ref": folder.name,
        "title": f"{app[:40]} call",
        "started": info["started"][:32],
        "minutes": max(0, round((ended - started).total_seconds() / 60)) if ended else 0,
        "people": [],
        "agreed_at": str(consent.get("at") or "")[:32],
    }
    if info.get("state") == "recording" and not ended:
        return row, "recording", None, None
    t = _read(folder / "transcript.json", MAX_TRANSCRIPT)
    if not t or t.get("id") != folder.name:
        return row, "waiting", None, None
    problem = t.get("problem") if isinstance(t.get("problem"), str) and t["problem"].strip() else None
    if t.get("state") == "done" and isinstance(t.get("lines"), list):
        if isinstance(t.get("minutes"), (int, float)) and 0 < t["minutes"] < 24 * 60:
            row["minutes"] = round(t["minutes"])
        return row, "done", None, t
    return row, "failed" if t.get("state") == "failed" else "waiting", problem, None


def _rev(t) -> str:
    return hashlib.sha256(json.dumps(t.get("lines"), sort_keys=True).encode()).hexdigest()[:16]


def _at(seconds) -> str:
    try:
        s = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


def meetings() -> dict:
    done, pending = [], []
    for folder in _folders():
        try:
            got = _call(folder)
        except (TypeError, ValueError, OverflowError, OSError):
            got = None  # one odd recording never hides the others
        if not got:
            continue
        row, state, problem, t = got
        if state == "done":
            done.append({**row, "rev": _rev(t)})
        else:
            words = (problem or PENDING_WORDS[state]).strip()[:300]
            pending.append(
                {
                    "ref": row["ref"],
                    "title": row["title"],
                    "started": row["started"],
                    "state": state,
                    "words": words,
                }
            )
    done.sort(key=lambda r: r["started"], reverse=True)
    pending.sort(key=lambda r: r["started"], reverse=True)
    return {"meetings": done[:MAX_LIST], "pending": pending[:10]}


def meeting(values: dict) -> dict:
    ref = values.get("ref")
    if not isinstance(ref, str) or not ID.fullmatch(ref):
        raise LookupError
    base = _base()
    folder = base / ref if base else None
    try:
        got = _call(folder) if folder and _ok(folder) else None
    except (TypeError, ValueError, OverflowError, OSError):
        got = None
    if not got or got[1] != "done":
        raise LookupError
    t = got[3]
    lines = [
        x for x in t["lines"] if isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip()
    ]
    try:
        start = max(0, int(values.get("cursor") or 0))
    except (TypeError, ValueError):
        start = 0
    return {
        "rev": _rev(t),
        "summary": "",
        "steps": [],
        "transcript": [
            {"who": WHO.get(x.get("who"), "Others"), "at": _at(x.get("start")), "text": x["text"].strip()}
            for x in lines[start : start + PAGE]
        ],
        "next": str(start + PAGE) if start + PAGE < len(lines) else None,
    }


req = json.loads(sys.stdin.read() or "{}")
if req.get("action") == "meeting":
    try:
        print(json.dumps(meeting(req.get("values") or {})))
    except LookupError:
        print("That meeting is not in orch Companion.", file=sys.stderr)
        sys.exit(1)
else:
    print(json.dumps(meetings()))
