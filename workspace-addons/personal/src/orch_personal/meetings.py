"""Meetings (ORCH-650): calls recorded on this computer arrive with transcript, summary and next steps; the sound
never leaves the recorder.

A recorder is a way in (ways.py) with part = "meetings" and two actions:

    meetings  stdin {"action": "meetings", "values": {}}
              stdout {"meetings": [{"ref", "rev", "title", "started", "minutes", "people": [..], "agreed_at"}],
                      "pending": [{"ref", "title", "started", "words"}]}
              finished meetings only, newest first, at most MAX_LIST. "agreed_at" (optional): the recorder itself
              asked before it recorded and everyone agreed then (orch Companion), so Meetings does not ask again.
              "pending" (optional): calls not finished yet (being transcribed, or a plain problem), shown as is
    meeting   stdin {"action": "meeting", "values": {"ref", "rev", "cursor"}}
              stdout {"rev", "summary", "steps": [{"text", "who", "due"}], "transcript": [{"who", "at", "text"}],
                      "next": "<cursor>" | null}
              one page; summary and steps on the first page only; the same rev on every page

Consent (Swiss Criminal Code art. 179bis ff.): nothing of a meeting but its title, time and people is read until the
person said that everyone on the call agreed before the recording started. A "no" means it is never read; it stays
in the recorder, where only the person can delete it. orch cannot see or stop the recorder itself.

    .orch/addons/personal/meetings.json        per recorder meeting (way:ref): waiting / agreed / declined / in /
                                               stuck / deleted, consent, problem, the meeting id once taken in
    .orch/addons/personal/meetings/<id>.json   a meeting taken in (text only)
    .orch/addons/personal/meetings-pending.json per recorder: its calls not finished yet, from the last pickup
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
from pathlib import Path

from . import store
from . import ways as ways_mod
from .store import Refused

PART = "meetings"
MAX_LIST = 50
MAX_PAGES = 40
MAX_LINES = 20000
MAX_STEPS = 30
PICKUP_EVERY = 300
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")
ID = re.compile(r"m_[0-9a-f]{12}")
CONSENT_WORDS = "Everyone on the call agreed before the recording started."
STATES = ("waiting", "agreed", "declined", "in", "stuck", "deleted")
_THREADS = threading.Lock()
_PICKUP = threading.Lock()  # one pickup at a time in this process


@contextlib.contextmanager
def _locked(root: Path):
    """meetings.json and the meeting files: one writer at a time across the CLI and the page server."""
    with ways_mod._file_lock(root, "meetings.lock", _THREADS):
        yield


def folder(root: Path) -> Path:
    return store.base(root) / "meetings"


def _state_file(root: Path) -> Path:
    return store.base(root) / "meetings.json"


def _pending_file(root: Path) -> Path:
    return store.base(root) / "meetings-pending.json"


def _read_pending(root: Path) -> dict:
    raw = store._read_json(_pending_file(root), {})
    return raw if isinstance(raw, dict) else {}


def _clean(v, limit: int) -> str:
    text = "".join(c if c.isprintable() or c == "\n" else " " for c in str(v or ""))
    return text.strip()[:limit]


def _line(v, limit: int) -> str:
    return " ".join(_clean(v, limit * 2).split())[:limit]


def meeting_id(way: str, ref: str) -> str:
    return "m_" + hashlib.sha256(f"{way}\0{ref}".encode()).hexdigest()[:12]


# --- saved state ---------------------------------------------------------------------------------------------
def seen(root: Path) -> dict[str, dict]:
    raw = store._read_json(_state_file(root), {})
    return {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("state") in STATES}


def _save_seen(root: Path, data: dict) -> None:
    store._atomic_write(_state_file(root), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load(root: Path, mid: str) -> dict:
    if not ID.fullmatch(mid or ""):
        raise Refused(f"There is no meeting {mid}. See them: orch personal meetings list")
    try:
        m = json.loads((folder(root) / f"{mid}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"There is no meeting {mid}. See them: orch personal meetings list") from None
    except (OSError, ValueError):
        raise Refused(f"The meeting {mid} could not be read. Delete it and take it in again.") from None
    if not isinstance(m, dict):
        raise Refused(f"The meeting {mid} could not be read. Delete it and take it in again.")
    return m


def save_meeting(root: Path, m: dict) -> None:
    store._atomic_write(folder(root) / f"{m['id']}.json", json.dumps(m, ensure_ascii=False, indent=2) + "\n")


def all_meetings(root: Path) -> list[dict]:
    out = []
    d = folder(root)
    for f in sorted(d.glob("m_*.json")) if d.is_dir() else []:
        with contextlib.suppress(Refused):
            out.append(load(root, f.stem))
    out.sort(key=lambda m: str(m.get("started") or ""), reverse=True)
    return out


# --- recorders -----------------------------------------------------------------------------------------------
def recorders(root: Path) -> list[dict]:
    """Ways in for meetings that are on and unchanged since the person turned them on."""
    return [w for w in ways_mod.status(root) if w["part"] == PART and w["on"] and w["status"] != "permission"]


def _ask_json(root: Path, way: str, action: str, values: dict) -> dict:
    text = ways_mod.ask(root, way, action, values)["text"]
    try:
        data = json.loads(text)
    except ValueError:
        raise Refused("The recorder did not answer in the agreed form (JSON).") from None
    if not isinstance(data, dict):
        raise Refused("The recorder did not answer in the agreed form (one JSON object).")
    return data


def _listed(row) -> dict | None:
    if not isinstance(row, dict) or not isinstance(row.get("ref"), str) or not REF.fullmatch(row["ref"]):
        return None
    people = row.get("people") if isinstance(row.get("people"), list) else []
    try:
        minutes = max(0, min(int(row.get("minutes") or 0), 24 * 60))
    except (TypeError, ValueError):
        minutes = 0
    return {
        "ref": row["ref"],
        "rev": _line(row.get("rev"), 64),
        "title": _line(row.get("title"), 160) or "Meeting",
        "started": _line(row.get("started"), 32),
        "minutes": minutes,
        "people": [_line(p, 80) for p in people[:40] if _line(p, 80)],
        "agreed_at": _line(row.get("agreed_at"), 32),
    }


def _pending_row(row, name: str) -> dict | None:
    if not isinstance(row, dict) or not isinstance(row.get("ref"), str) or not REF.fullmatch(row["ref"]):
        return None
    words = _line(row.get("words"), 300)
    if not words:
        return None
    return {
        "title": _line(row.get("title"), 160) or "Meeting",
        "started": _line(row.get("started"), 32),
        "words": words,
        "source": name,
    }


def _fetch(root: Path, way: str, ref: str, rev: str) -> dict:
    """Every page of one meeting at one rev. A rev that changes between pages starts over once."""
    for _attempt in range(2):
        cursor, pages, summary, steps, lines, got_rev = None, 0, "", [], [], None
        while True:
            pages += 1
            if pages > MAX_PAGES:
                raise Refused(f"The recorder gave more than {MAX_PAGES} pages for one meeting.")
            page = _ask_json(root, way, "meeting", {"ref": ref, "rev": rev, "cursor": cursor})
            prev = _line(page.get("rev"), 64)
            if got_rev is None:
                got_rev = prev
            elif prev != got_rev:
                break  # it changed while we read it: start over
            if pages == 1:
                summary = _clean(page.get("summary"), 8000)
                raw_steps = page.get("steps") if isinstance(page.get("steps"), list) else []
                steps = [s for s in (_step(x) for x in raw_steps[:MAX_STEPS]) if s]
            for x in page.get("transcript") if isinstance(page.get("transcript"), list) else []:
                if isinstance(x, dict) and _clean(x.get("text"), 4000):
                    lines.append(
                        {
                            "who": _line(x.get("who"), 80),
                            "at": _line(x.get("at"), 32),
                            "text": _clean(x.get("text"), 4000),
                        }
                    )
            if len(lines) > MAX_LINES:
                raise Refused(f"The transcript has more than {MAX_LINES} lines.")
            nxt = page.get("next")
            if nxt in (None, ""):
                return {"rev": got_rev, "summary": summary, "steps": steps, "transcript": lines}
            if not isinstance(nxt, str) or len(nxt) > 256 or nxt == cursor:
                raise Refused("The recorder gave a page marker that cannot be followed.")
            cursor = nxt
    raise Refused("The meeting kept changing while it was read. It is tried again later.")


def _step(x) -> dict | None:
    if isinstance(x, str):
        x = {"text": x}
    if not isinstance(x, dict) or not _line(x.get("text"), 200):
        return None
    return {"text": _line(x.get("text"), 200), "who": _line(x.get("who"), 80), "due": _line(x.get("due"), 32)}


def _numbered(steps: list[dict], keep: list[dict] | None = None) -> list[dict]:
    """Each step gets a stable number; a step that already made a ticket keeps it."""
    done = {s["text"]: s for s in keep or [] if s.get("ticket")}
    out = [s for s in done.values()]
    for s in steps:
        if s["text"] not in done:
            out.append({**s, "ticket": None})
    return [{**s, "n": i + 1} for i, s in enumerate(out)]


def pickup(root: Path) -> dict:
    """Look at every recorder that is on: list new finished meetings (waiting for the person's OK) and take in
    those the person agreed to. Returns counts and problems in plain words."""
    # The recorder runs outside the lock (a page can take a minute); the lock only guards reading and writing the
    # saved state, so a click on the page (agree, delete) is never lost or held up.
    with _PICKUP:
        new, taken, problems = 0, 0, []
        on = recorders(root)
        pend = {k: v for k, v in _read_pending(root).items() if k in {w["way"] for w in on}}
        for w in on:
            way = w["way"]
            try:
                listed = _ask_json(root, way, "meetings", {})
            except Refused as e:
                problems.append(f"{w['name']}: {e}")
                continue
            rows = listed.get("meetings") if isinstance(listed.get("meetings"), list) else []
            raw_pend = listed.get("pending") if isinstance(listed.get("pending"), list) else []
            pend[way] = [r for r in (_pending_row(x, w["name"]) for x in raw_pend[:10]) if r]
            with _locked(root):
                data = seen(root)
                for raw in rows[:MAX_LIST]:
                    m = _listed(raw)
                    if not m:
                        continue
                    key = f"{way}:{m['ref']}"
                    if key not in data:
                        data[key] = {
                            "way": way,
                            "name": w["name"],
                            **m,
                            "state": "waiting",
                            "seen": store.now(),
                        }
                        if m["agreed_at"]:  # the recorder asked before it recorded: not asked a second time
                            data[key].update(
                                state="agreed",
                                consent={
                                    "by": f"recorder:{w['name']}",
                                    "at": m["agreed_at"],
                                    "words": CONSENT_WORDS,
                                },
                            )
                        else:
                            new += 1  # new and waiting for the person's answer
                    elif data[key]["state"] in ("waiting", "agreed", "stuck"):
                        data[key].update({k: v for k, v in m.items() if k != "ref"})
                _save_seen(root, data)
            todo = [
                (k, r)
                for k, r in data.items()
                if r.get("way") == way and r["state"] in ("agreed", "stuck") and r.get("consent")
            ]
            for key, row in todo:
                try:
                    got = _fetch(root, way, row["ref"], row.get("rev") or "")
                except Refused as e:
                    with _locked(root):
                        data = seen(root)
                        if data.get(key, {}).get("state") in ("agreed", "stuck"):
                            data[key].update(state="stuck", problem=str(e))
                            _save_seen(root, data)
                    problems.append(f"{row['title']}: {e}")
                    continue
                mid = meeting_id(way, row["ref"])
                m = {
                    "schema": "orch.personal.meeting/1",
                    "id": mid,
                    "way": way,
                    "source": w["name"],
                    "ref": row["ref"],
                    "rev": got["rev"],
                    "title": row["title"],
                    "started": row["started"],
                    "minutes": row["minutes"],
                    "people": row["people"],
                    "consent": row["consent"],
                    "summary": got["summary"],
                    "summary_by": "recorder" if got["summary"] else None,
                    "steps": _numbered(got["steps"]),
                    "transcript": got["transcript"],
                    "arrived": store.now(),
                }
                with _locked(root):
                    data = seen(root)
                    if data.get(key, {}).get("state") not in ("agreed", "stuck"):
                        continue  # the person said no while it was read
                    save_meeting(root, m)
                    data[key].update(state="in", id=mid, problem=None)
                    _save_seen(root, data)
                taken += 1
        with _locked(root):
            store._atomic_write(_pending_file(root), json.dumps(pend, ensure_ascii=False, indent=2) + "\n")
        return {"new": new, "taken": taken, "problems": problems}


def pending(root: Path) -> list[dict]:
    """Calls a recorder has not finished yet (being transcribed, or a plain problem), from the last pickup."""
    on = {w["way"] for w in recorders(root)}
    rows = [
        r
        for way, items in _read_pending(root).items()
        if way in on and isinstance(items, list)
        for r in items
        if isinstance(r, dict) and isinstance(r.get("words"), str)
    ]
    rows.sort(key=lambda r: str(r.get("started") or ""), reverse=True)
    return rows


def waiting(root: Path) -> list[dict]:
    """Meetings the recorder finished that wait for the person: did everyone agree? Or that could not be read."""
    rows = []
    for key, r in seen(root).items():
        if r["state"] in ("waiting", "stuck"):
            rows.append(
                {
                    "key": key,
                    "state": r["state"],
                    "title": r.get("title") or "Meeting",
                    "started": r.get("started") or "",
                    "minutes": r.get("minutes") or 0,
                    "people": r.get("people") or [],
                    "source": r.get("name") or r.get("way") or "",
                    "problem": r.get("problem"),
                }
            )
    rows.sort(key=lambda r: r["started"], reverse=True)
    return rows


def agree(root: Path, key: str, yes: bool, by: str) -> dict:
    with _locked(root):
        data = seen(root)
        row = data.get(key)
        if not row or row["state"] not in ("waiting", "stuck", "agreed"):
            raise Refused("That meeting is not waiting for you any more. Reload Meetings.")
        if yes:
            row.update(state="agreed", consent={"by": by, "at": store.now(), "words": CONSENT_WORDS})
        else:
            row.update(state="declined", consent=None, declined={"by": by, "at": store.now()})
        _save_seen(root, data)
        return row


def delete(root: Path, mid: str) -> dict:
    m = load(root, mid)
    with _locked(root):
        (folder(root) / f"{mid}.json").unlink(missing_ok=True)
        key, data = f"{m['way']}:{m['ref']}", seen(root)
        if key in data:
            data[key].update(state="deleted", id=None)
            _save_seen(root, data)
    return m


def set_summary(root: Path, mid: str, summary: str, steps: list[dict], by: str, guard=None) -> dict:
    with _locked(root):
        m = load(root, mid)
        if guard:
            guard(m)
        m["summary"] = _clean(summary, 8000)
        m["summary_by"] = by
        m["steps"] = _numbered([s for s in (_step(x) for x in steps[:MAX_STEPS]) if s], m.get("steps"))
        save_meeting(root, m)
        return m


def as_markdown(m: dict, with_transcript: bool, note: str) -> str:
    when = (
        f"{m.get('started', '')[:16].replace('T', ' ')} · {m.get('minutes') or 0} min · {m.get('source', '')}"
    )
    out = [f"<!-- {note} From Personal > Meetings: {m['id']} -->", "", f"# {m['title']}", "", when]
    if m.get("people"):
        out.append("With: " + ", ".join(m["people"]))
    out += ["", "## Summary", "", m.get("summary") or "No summary yet."]
    if m.get("steps"):
        out += ["", "## Next steps", ""]
        for s in m["steps"]:
            extra = " · ".join(x for x in (s.get("who"), s.get("due") and f"until {s['due']}") if x)
            out.append(f"- {s['text']}" + (f" ({extra})" if extra else ""))
    if with_transcript:
        out += ["", "## Transcript", ""]
        out += [f"{x['who'] or '?'} {x['at']}: {x['text']}" for x in m.get("transcript") or []]
    return "\n".join(out) + "\n"


def pickup_loop(root: Path, stop: threading.Event, every: float = PICKUP_EVERY) -> threading.Thread:
    """In the Personal page server: look for finished meetings every few minutes."""

    def loop():
        while not stop.is_set():
            with contextlib.suppress(Exception):  # a broken recorder must not end the page server
                if store.settings(root)["parts"].get(PART, {}).get("on"):
                    pickup(root)
            stop.wait(every)

    t = threading.Thread(target=loop, name="personal-meetings", daemon=True)
    t.start()
    return t
