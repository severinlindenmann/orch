"""Personal's own files: which parts are on, their rules, what was handed to which ticket, what helpers did.

All plain JSON under `.orch/addons/personal/` (gitignored), written atomically. Rules are checked here, in the
workspace, before a helper sees anything; ways in (ways.py) check theirs on every run.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path


class Refused(Exception):
    """A plain sentence for the person or helper, plus what to do next (exit 2)."""


PARTS = {
    "notes": {
        "label": "Notes",
        "text": "Your knowledge as linked notes that helpers can look things up in.",
        "through": "the notes folder on this computer",
    },
    "meetings": {
        "label": "Meetings",
        "text": "Record calls on this computer; get the transcript, a summary and next steps here.",
        "through": "the recorder on this computer",
    },
    "mail": {
        "label": "Mail",
        "text": "Only the mails that need you, from every mailbox. Helpers draft replies; they never send.",
        "through": "a way in on this computer (the Mail app, the Microsoft access or Outlook web)",
    },
    "messages": {
        "label": "Messages",
        "text": "Work chats that need you. Helpers draft replies; you send them yourself.",
        "through": "a way in on this computer (the Microsoft access or Teams web)",
    },
    "calendar": {
        "label": "Calendar",
        "text": "Work, private and family calendars in one week view.",
        "through": "the Calendar app on this computer",
    },
}
# Shown on Add so the person sees what comes next; they cannot be added yet.
SOON: dict = {}
LATER = {
    "files": ("Files", "Your documents from OneDrive, iCloud Drive and this computer."),
    "tasks": ("Tasks", "Your own to-dos next to the tickets."),
    "people": ("People", "Who is who, with the last meeting, mail and chat."),
}

READ = ("never", "attached", "all")
WRITE = ("never", "add", "change")
DEFAULTS = {
    "notes": {"on": True, "folder": "", "read": "attached", "write": "add"},
    # Meetings: write "add" lets a helper write a summary and next steps where the recorder gave none.
    "meetings": {"on": True, "folder": "", "read": "attached", "write": "add"},
    # Mail and Messages: write "add" = helpers make drafts; there is no send rule at all. Each source (a way in)
    # starts closed to helpers ("helpers"); for the Mail app the person picks which accounts count ("accounts").
    "mail": {
        "on": True,
        "folder": "",
        "read": "attached",
        "write": "add",
        "helpers": {},
        "accounts": {},
        "vip": [],
    },
    "messages": {
        "on": True,
        "folder": "",
        "read": "attached",
        "write": "add",
        "helpers": {},
        "accounts": {},
        "vip": [],
    },
    # Calendar: per calendar what helpers may use (missing = nothing); one rule for adding or moving events.
    "calendar": {"on": True, "source": "app", "cals": {}, "moves": "suggest"},
}
LEVELS = ("nothing", "busy", "titles")
MOVES = ("never", "suggest")
INBOX_PARTS = ("mail", "messages")
INBOX_WRITE = ("never", "add")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
READ_WORDS = {
    "never": "Never",
    "attached": "Only in a ticket you attach it to",
    "all": "All notes",
}
WRITE_WORDS = {"never": "Never", "add": "Add new notes", "change": "Add and change"}
ACTIVITY_KEEP = 500
_USED_LOCK = threading.Lock()  # the page server answers clicks in threads: one hand-over at a time


def base(root: Path) -> Path:
    d = root / ".orch" / "addons" / "personal"
    for p in (root / ".orch", root / ".orch" / "addons", d):
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            raise Refused(
                f"{p} is a link or not a folder; orch will not write there. Make it a plain folder."
            )
    return d


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise Refused(
            f"{path} could not be read. Fix or delete it; Personal then starts from its defaults."
        ) from None
    return data if isinstance(data, type(default)) else default


def settings(root: Path) -> dict:
    """{"parts": {name: {...}}}: only parts the person added are listed."""
    raw = _read_json(base(root) / "settings.json", {})
    parts = {}
    for name, value in (raw.get("parts") or {}).items():
        if name in PARTS and isinstance(value, dict):
            p = {**DEFAULTS[name], **{k: v for k, v in value.items() if k in DEFAULTS[name]}}
            p["on"] = bool(p["on"])
            if name == "calendar":
                parts[name] = _clean_calendar(p)
            elif name in INBOX_PARTS:
                parts[name] = _clean_notes(p)
                _clean_inbox(parts[name])
            else:
                parts[name] = _clean_notes(p)
    return {"parts": parts}


def _clean_notes(p: dict) -> dict:
    if p["read"] not in READ:
        p["read"] = "never"
    if p["write"] not in WRITE:
        p["write"] = "never"
    p["folder"] = str(p["folder"] or "")
    return p


def _clean_calendar(p: dict) -> dict:
    """Anything unreadable falls back to the closed choice: a calendar at nothing, moves never."""
    cals = {}
    for cid, c in (p["cals"] if isinstance(p["cals"], dict) else {}).items():
        if isinstance(cid, str) and 0 < len(cid) <= 200 and isinstance(c, dict):
            level = c.get("level") if c.get("level") in LEVELS else "nothing"
            cals[cid] = {"level": level, "title": str(c.get("title") or "")[:200]}
    p["cals"] = cals
    if p["moves"] not in MOVES:
        p["moves"] = "never"
    src = str(p["source"] or "app")
    p["source"] = src if src == "app" or re.fullmatch(r"way:[a-z0-9][a-z0-9-]{0,31}", src) else "app"
    return p


def _clean_inbox(p: dict) -> None:
    """Mail and Messages: drafts or nothing; per source a helper switch and, for the Mail app, the chosen accounts."""
    if p["write"] not in INBOX_WRITE:
        p["write"] = "never"
    h = p.get("helpers") if isinstance(p.get("helpers"), dict) else {}
    p["helpers"] = {k: v for k, v in h.items() if isinstance(k, str) and SLUG.fullmatch(k) and v is True}
    a = p.get("accounts") if isinstance(p.get("accounts"), dict) else {}
    p["accounts"] = {
        k: [str(x)[:120] for x in v if isinstance(x, str) and x.strip()][:20]
        for k, v in a.items()
        if isinstance(k, str) and SLUG.fullmatch(k) and isinstance(v, list)
    }
    vip = p.get("vip") if isinstance(p.get("vip"), list) else []
    p["vip"] = [" ".join(str(x).split())[:80] for x in vip if isinstance(x, str) and x.strip()][:50]


def save(root: Path, data: dict) -> None:
    _atomic_write(base(root) / "settings.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def part(root: Path, name: str) -> dict:
    p = settings(root)["parts"].get(name)
    if not p or not p["on"]:
        label = PARTS.get(name, {}).get("label", name)
        raise Refused(
            f"{label} is not turned on in Personal. The person turns it on: orch personal add {name}"
        )
    return p


def add_part(root: Path, name: str) -> dict:
    if name not in PARTS:
        if name in SOON or name in LATER:
            ready = " and ".join(m["label"] for m in PARTS.values())
            raise Refused(f"{(SOON.get(name) or LATER[name])[0]} is not ready yet. {ready} can be added now.")
        raise Refused(f"There is no part called {name}. Parts: {', '.join(PARTS)}.")
    data = settings(root)
    data["parts"][name] = {**DEFAULTS[name], **data["parts"].get(name, {}), "on": True}
    save(root, data)
    return data["parts"][name]


def remove_part(root: Path, name: str) -> None:
    data = settings(root)
    if name in data["parts"]:
        data["parts"][name]["on"] = False  # rules and folder stay for when it is turned on again
        save(root, data)


def set_rules(root: Path, name: str, read: str | None, write: str | None, folder: str | None) -> dict:
    data = settings(root)
    p = data["parts"].get(name)
    if not p:
        raise Refused(f"Add {PARTS[name]['label']} first: orch personal add {name}")
    if read is not None:
        if read not in READ:
            raise Refused(f"Read can be {', '.join(READ)}.")
        p["read"] = read
    if write is not None:
        allowed = INBOX_WRITE if name in INBOX_PARTS else WRITE
        if write not in allowed:
            if name in INBOX_PARTS:
                raise Refused("Reply can be never or add (helpers make drafts). Helpers never send.")
            raise Refused(f"Write can be {', '.join(WRITE)}.")
        p["write"] = write
    if folder is not None:
        p["folder"] = folder
    save(root, data)
    return p


def set_source(
    root: Path, name: str, way: str, helpers: bool | None = None, accounts: list[str] | None = None
) -> dict:
    """Mail / Messages: may helpers use this source (a way in)? Which Mail app accounts count?"""
    if name not in INBOX_PARTS:
        raise Refused("Sources are chosen for Mail and Messages only.")
    if not SLUG.fullmatch(way or ""):
        raise Refused("There is no such way in. See them: orch personal ways")
    data = settings(root)
    p = data["parts"].get(name)
    if not p:
        raise Refused(f"Add {PARTS[name]['label']} first: orch personal add {name}")
    if helpers is not None:
        if helpers:
            p["helpers"][way] = True
        else:
            p["helpers"].pop(way, None)
    if accounts is not None:
        p["accounts"][way] = accounts
    save(root, data)
    return settings(root)["parts"][name]


# --- handed to tickets (Use in a ticket) ---------------------------------------------------------------------
def used(root: Path) -> dict:
    raw = _read_json(base(root) / "used.json", {})
    return {k: v for k, v in raw.items() if re.fullmatch(r"t_[a-z0-9]{6,16}", k) and isinstance(v, list)}


def mark_used(root: Path, ticket: str, part_name: str, item: str, by: str, attached: str) -> None:
    with _USED_LOCK:
        _mark_used(root, ticket, part_name, item, by, attached)


def forget_used(root: Path, part_name: str) -> None:
    """A new source (another notes folder): what was attached from the old one no longer opens anything new."""
    with _USED_LOCK:
        data = {t: [r for r in rows if r.get("part") != part_name] for t, rows in used(root).items()}
        _atomic_write(
            base(root) / "used.json",
            json.dumps({t: r for t, r in data.items() if r}, ensure_ascii=False, indent=2) + "\n",
        )


def _mark_used(root: Path, ticket: str, part_name: str, item: str, by: str, attached: str) -> None:
    data = used(root)
    rows = [r for r in data.get(ticket, []) if not (r.get("part") == part_name and r.get("id") == item)]
    rows.append({"part": part_name, "id": item, "by": by, "at": now(), "file": attached})
    data[ticket] = rows
    _atomic_write(base(root) / "used.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def used_on(root: Path, ticket: str | None, part_name: str) -> set[str]:
    if not ticket:
        return set()
    return {r["id"] for r in used(root).get(ticket, []) if r.get("part") == part_name and "id" in r}


def tickets_using(root: Path, part_name: str, item: str) -> list[str]:
    return [
        t
        for t, rows in used(root).items()
        if any(r.get("part") == part_name and r.get("id") == item for r in rows)
    ]


# --- what helpers did (no content, only what and where) ------------------------------------------------------
def log(root: Path, part_name: str, what: str, by: str, ticket: str | None = None) -> None:
    f = base(root) / "activity.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now(), "part": part_name, "what": what[:200], "by": by, "ticket": ticket}
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    lines = [*lines[-(ACTIVITY_KEEP - 1) :], json.dumps(row, ensure_ascii=False)]
    _atomic_write(f, "\n".join(lines) + "\n")


def activity(root: Path, days: int = 7, limit: int = 20) -> list[dict]:
    f = base(root) / "activity.jsonl"
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    out = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and str(row.get("at", "")) >= since:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
