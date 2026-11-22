"""The workspace's person list (several people in one workspace, ORCH-1161, build plan ORCH-1160 section 3).

One file, `.orch/local/people.json` (this machine only, never synced: `.orch/local/` is left out of sync).
It is written only here, through `orch people ...` or the dashboard's Settings at the machine, and refused
from a helper's environment. A workspace without the file works exactly as before ("off").

    {"schema": "orch.people/1", "revision": 3,
     "people": [{"id": "pr_k3f9q2m1xa", "name": "Lea", "rights": ["write"], "owner": false,
                 "added_at": "...", "removed_at": null}],
     "devices": [],                      # phones tied to a person come with step 4 (ORCH-1162)
     "log": [{"at": "...", "by": "human:pr_...", "device": "machine", "what": "Added Lea"}]}

Rules:
- A person id is `pr_` + 10 random [a-z0-9], made once, never changed and never reused (removed people stay in
  the file with `removed_at`, so their id stays taken and old history still shows "Lea (removed)").
- Exactly one owner in the first slice: the person at this machine, who turns the list on. The owner has every
  right and can't be removed (the last owner is never removed).
- Rights: write, decide, start (shown as Write, Decide, Start work; placeholders until the owner picks the
  words, R4.2). A new person starts with write only.
- A broken file is never "everyone allowed": `load` raises Broken and nothing is stamped or shown from it.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import secrets
import string
import tempfile
import time
import unicodedata
from pathlib import Path

from orch.errors import Refused

SCHEMA = "orch.people/1"
RIGHTS = ("write", "decide", "start")
RIGHT_WORDS = {"write": "Write", "decide": "Decide", "start": "Start work"}
DEFAULT_RIGHTS = ("write",)
MACHINE = "machine"  # the device id of the workspace's own computer (dashboard and CLI at the machine)
MAX_PEOPLE = 50
MAX_LOG = 200
_ID_RE = re.compile(r"pr_[a-z0-9]{10}")
_ALPHABET = string.ascii_lowercase + string.digits
NOT_HERE = (
    "Only the owner at this computer can change the people list. Ask the owner to do it in Settings, People."
)
# Set by the dashboard on the orch it runs for a token-login browser (ORCH-1035): that is another person,
# signed in from anywhere, never the owner at this computer (ORCH-1486).
BROWSER_ENV = "ORCH_BROWSER_PERSON"


class Broken(Refused):
    """The people file is there but can't be read or is not in the expected form (fail closed)."""


def path(root: Path) -> Path:
    return Path(root) / ".orch" / "local" / "people.json"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_name(value) -> str:
    """One short plain name: printable letters of any language, digits, spaces and . _ @ ' -; 1 to 40 long."""
    if not isinstance(value, str):
        raise Refused("Type a name.")
    value = unicodedata.normalize("NFC", value)
    kept = "".join(ch for ch in value if ch.isalnum() or ch in " ._@'-")
    name = " ".join(kept.split())[:40].strip()
    if not name:
        raise Refused("Type a name (letters, digits and spaces).")
    return name


def clean_rights(value) -> list[str]:
    """A list of rights in the fixed order; unknown words are refused (never silently dropped)."""
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\s]+", value) if v]
    if not isinstance(value, (list, tuple)):
        raise Refused("Rights are a list: write, decide, start.")
    words = {
        str(v).strip().lower().replace("start-work", "start").replace("start_work", "start") for v in value
    }
    bad = sorted(w for w in words if w not in RIGHTS)
    if bad:
        raise Refused(f"Unknown right: {', '.join(bad)}. Use write, decide or start.")
    return [r for r in RIGHTS if r in words]


# ------------------------------------------------------------------ read


def _valid(doc) -> bool:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("revision"), int):
        return False
    people, devices, log = doc.get("people"), doc.get("devices", []), doc.get("log", [])
    if not isinstance(people, list) or not isinstance(devices, list) or not isinstance(log, list):
        return False
    if any(not isinstance(d, dict) for d in devices) or any(not isinstance(x, dict) for x in log):
        return False
    ids = set()
    for p in people:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not _ID_RE.fullmatch(p["id"]):
            return False
        if p["id"] in ids or not isinstance(p.get("name"), str) or not p["name"].strip():
            return False
        if not isinstance(p.get("rights"), list) or any(r not in RIGHTS for r in p["rights"]):
            return False
        ids.add(p["id"])
    owners = [p for p in people if p.get("owner") is True and not p.get("removed_at")]
    return len(owners) >= 1


_CACHE: dict[str, tuple[tuple, dict | None]] = {}


def load(root: Path) -> dict | None:
    """The person list, or None when it is off (no file). A file that can't be read raises Broken."""
    p = path(root)
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Broken("The people list can't be read.") from e
    key = (st.st_mtime_ns, st.st_size, st.st_ino)
    hit = _CACHE.get(str(p))
    if hit and hit[0] == key:
        if hit[1] is None:
            raise Broken("The people list is damaged. The owner sets it up again in Settings, People.")
        return json.loads(json.dumps(hit[1]))
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    good = doc if _valid(doc) else None
    _CACHE[str(p)] = (key, good)
    if good is None:
        raise Broken("The people list is damaged. The owner sets it up again in Settings, People.")
    return json.loads(json.dumps(good))


def state(root: Path) -> str:
    """off (no list), on, or broken."""
    try:
        return "on" if load(root) is not None else "off"
    except Broken:
        return "broken"


def owner(doc: dict | None) -> dict | None:
    for p in (doc or {}).get("people") or []:
        if p.get("owner") is True and not p.get("removed_at"):
            return p
    return None


def find(doc: dict, who: str, *, active: bool = True) -> dict:
    """A person by id, or by name (any case). Refused when there is none or the name is not unique."""
    who = (who or "").strip()
    if who.startswith("human:"):
        who = who[6:]
    people = [p for p in doc.get("people") or [] if not (active and p.get("removed_at"))]
    for p in people:
        if p["id"] == who:
            return p
    hits = [p for p in people if p["name"].casefold() == who.casefold()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Refused(f"Several people are called {who}. Use the person's id.")
    raise Refused(f"There is no person {who} in the list.")


def name_of(doc: dict | None, by: str) -> str | None:
    """The name for `human:pr_...` (or a bare pr_ id): "Lea", "Lea (removed)"; None for anything else."""
    pid = by[6:] if isinstance(by, str) and by.startswith("human:") else by
    if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
        return None
    for p in (doc or {}).get("people") or []:
        if p["id"] == pid:
            return p["name"] + (" (removed)" if p.get("removed_at") else "")
    return "Someone removed"


def names(root: Path) -> dict[str, str]:
    """{person id: name to show}, everyone ever on the list (removed marked). Empty when off or broken."""
    try:
        doc = load(root)
    except Broken:
        return {}
    return {p["id"]: name_of(doc, p["id"]) for p in (doc or {}).get("people") or []}


def show(root: Path, by: str) -> str:
    """How an actor reads for a person: a person id becomes the name; everything else stays as written (old
    history keeps `human:<os user>`, `human:<phone name>`, `human:ph_...`)."""
    try:
        doc = load(root)
    except Broken:
        doc = None
    return name_of(doc, by) or by


def line_who(names_: dict[str, str], by: str, person=None) -> str:
    """Who a history line or answer reads as in the terminal (same rule as the dashboard): a line stamped with
    a person of the list (a phone's line, `person`) is that person's name, a `human:pr_...` actor its name;
    anything else stays as written. `names_` comes from names(root), once per read; with the list off or
    damaged it is empty and every actor stays as written."""
    if isinstance(person, str) and person in names_:
        return names_[person]
    pid = by[6:] if isinstance(by, str) and by.startswith("human:") else None
    if names_ and pid is not None and _ID_RE.fullmatch(pid):
        return names_.get(pid, "Someone removed")
    return by


def view(root: Path) -> dict:
    """What Settings shows: {state, revision, owner, people: [{id, name, rights, owner, removed}]}."""
    try:
        doc = load(root)
    except Broken:
        return {"state": "broken", "revision": None, "people": []}
    if doc is None:
        return {"state": "off", "revision": None, "people": []}
    return {
        "state": "on",
        "revision": doc["revision"],
        "people": [
            {
                "id": p["id"],
                "name": p["name"],
                "rights": list(p["rights"]),
                "owner": bool(p.get("owner")),
                "removed": bool(p.get("removed_at")),
            }
            for p in doc["people"]
        ],
        "phones": phones_view(root, doc),
    }


def phones_view(root: Path, doc: dict) -> list[dict]:
    """The phones Settings shows: every phone paired on the relay now (its last snapshot) plus every phone
    the list knows, with whose it is: [{id, name, kind, paired, person, cut}]. Names come from the relay
    (display text only); `kind` is "browser" for a browser signed in on the relay's own page (ORCH-1197),
    else "phone".
    A browser is tied, cut and checked exactly like a phone. Nothing when the relay is not set up."""
    snap = Path(root) / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    try:
        paired = json.loads(snap.read_text(encoding="utf-8")).get("phones") or []
    except (OSError, ValueError, AttributeError):
        paired = []
    out, seen = [], set()
    for ph in paired:
        if isinstance(ph, dict) and isinstance(ph.get("id"), str) and PHONE_RE.fullmatch(ph["id"]):
            seen.add(ph["id"])
            name = _phone_name(ph.get("name"), ph["id"])
            out.append({"id": ph["id"], "name": name, "kind": _kind(ph), "paired": True})
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id") not in seen and PHONE_RE.fullmatch(str(d.get("id"))):
            # no longer on the relay (removed there): the name it had when it was tied, else its id
            out.append(
                {
                    "id": d["id"],
                    "name": _phone_name(d.get("name"), d["id"]),
                    "kind": _kind(d),
                    "paired": False,
                }
            )
    for ph in out:
        d = _device(doc, ph["id"]) or {}
        ph["person"], ph["cut"] = d.get("person"), bool(d.get("cut_at"))
    return out


def _kind(rec) -> str:
    """'browser' or 'phone' (anything else, or nothing, from an older relay: a phone)."""
    return "browser" if isinstance(rec, dict) and rec.get("kind") == "browser" else "phone"


def paired_kind(root: Path, phone: str) -> str:
    """The kind the relay's last snapshot gives this device ('phone' when it is not there)."""
    snap = Path(root) / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    try:
        phones = json.loads(snap.read_text(encoding="utf-8")).get("phones") or []
    except (OSError, ValueError, AttributeError):
        phones = []
    return next((_kind(p) for p in phones if isinstance(p, dict) and p.get("id") == phone), "phone")


def _phone_name(value, fallback: str) -> str:
    name = " ".join("".join(c for c in str(value or "") if c.isprintable()).split())[:40]
    return name or fallback


# ------------------------------------------------------------------ stamping new history lines


LOCAL_VIA = ("cli", "dashboard")  # where a line made at this computer comes from (tickets._env_via)


def stamp(root: Path, line: dict) -> None:
    """A NEW history line core made in this process (tickets._write calls it before the digest is recorded):
    once the list is on, a person's action at this machine records the owner's person id and device `machine`.
    Allowlist only: a human line made at this machine's CLI or dashboard (via cli / dashboard), not from a
    helper's environment and not a phone (`human:ph_...`). A person id typed in `--by` still stamps the owner
    (whoever sits at the machine is the owner). Everything else stays unstamped: phones (step 4), relay and
    chat lines from other workspaces, helpers, system lines. A line that names a person is left alone.
    Never raises."""
    try:
        if not isinstance(line, dict) or "person" in line:
            return
        by, via = line.get("by"), line.get("via")
        acting = _ACTING.get()
        if via == "phone" and acting is not None:  # a phone the people check let in (who_sent): its person
            line["person"], line["device"] = acting
            return
        # what that phone's text made (its "Ticket created" line): the same person, for showing only
        if acting is not None and by == f"agent:relay from {acting[1]}":
            line["person"], line["device"] = acting
            return
        if not isinstance(by, str) or not by.startswith("human:") or via not in LOCAL_VIA:
            return
        if by.startswith(("human:ph_", "human:br_")):
            return
        from orch import tickets

        if tickets.agent_tool() or os.environ.get(BROWSER_ENV):  # a token-login browser is not the owner
            return
        o = owner(load(root))
        if o is None:
            return
        line["person"], line["device"] = o["id"], MACHINE
    except Exception:  # noqa: BLE001 - a broken or missing list stamps nothing
        return


def stamp_lines(root: Path, lines: list) -> None:
    """stamp() for each new line; nothing is read when there are none or the list is off."""
    if lines and path(root).exists():
        for line in lines:
            stamp(root, line)


# ------------------------------------------------------------------ write


def _guard(by: str | None = None) -> None:
    """Only the owner at this computer changes the list (ORCH-1160 rights table: people and devices, owner).
    Refused: a helper's environment, a token-login browser of the dashboard, a phone's message being handled,
    and an acting --by that is a phone, a browser or a person id. A person id of the owner is checked against
    the list in _change (owner_only)."""
    from orch import tickets

    if tickets.agent_tool() or os.environ.get(BROWSER_ENV) or _ACTING.get() is not None:
        raise Refused(NOT_HERE)
    if by is None:
        return
    if not isinstance(by, str) or not by.startswith("human:") or by.startswith(("human:ph_", "human:br_")):
        raise Refused(NOT_HERE)


def _owner_only(doc: dict | None, by: str | None) -> None:
    """--by human:pr_... is allowed only for the owner's own id (fail closed without a list)."""
    pid = by[6:] if isinstance(by, str) and by.startswith("human:pr_") else None
    if pid is None:
        return
    o = owner(doc)
    if o is None or o["id"] != pid:
        raise Refused(NOT_HERE)


@contextlib.contextmanager
def _locked(root: Path):
    from orch import tickets

    with tickets._locked(Path(root), "people-list"):
        yield


def _save(root: Path, doc: dict) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-people-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _new_id(doc: dict) -> str:
    taken = {p["id"] for p in doc.get("people") or []}
    while True:
        pid = "pr_" + "".join(secrets.choice(_ALPHABET) for _ in range(10))
        if pid not in taken:
            return pid


def _active_names(doc: dict, but: str | None = None) -> set[str]:
    return {p["name"].casefold() for p in doc["people"] if not p.get("removed_at") and p["id"] != but}


def _change(root: Path, what, *, expect: int | None = None, by: str | None = None) -> dict:
    """Under the lock: load, check the revision the person saw (if given), apply `what(doc) -> log`, save."""
    _guard(by)
    with _locked(root):
        doc = load(root)
        if doc is None:
            raise Refused("The people list is off. Turn it on first: orch people on.")
        _owner_only(doc, by)
        if expect is not None and doc["revision"] != expect:
            raise Refused("The people list changed meanwhile. Look again and try once more.")
        text = what(doc)
        o = owner(doc)
        doc["revision"] += 1
        doc.setdefault("log", []).append(
            {"at": now(), "by": "human:" + o["id"], "device": MACHINE, "what": text}
        )
        doc["log"] = doc["log"][-MAX_LOG:]
        _save(root, doc)
        return doc


def turn_on(root: Path, owner_name: str, *, by: str | None = None) -> dict:
    """Make the list with the person at this machine as its owner. Refused when it is already on."""
    _guard(by)
    _owner_only(None, by)  # nobody has a person id before the list is on
    name = clean_name(owner_name)
    with _locked(root):
        p = path(root)
        if p.exists():
            raise Refused(
                "The people list is already on."
                if state(root) == "on"
                else ("The people list is damaged. Move .orch/local/people.json away, then turn it on again.")
            )
        doc = {"schema": SCHEMA, "revision": 1, "people": [], "devices": [], "log": []}
        pid = _new_id(doc)
        doc["people"].append(
            {
                "id": pid,
                "name": name,
                "rights": list(RIGHTS),
                "owner": True,
                "added_at": now(),
                "removed_at": None,
            }
        )
        doc["log"].append(
            {"at": now(), "by": "human:" + pid, "device": MACHINE, "what": f"Turned on, owner {name}"}
        )
        _save(root, doc)
        return doc


def add(root: Path, name: str, rights=None, *, expect: int | None = None, by: str | None = None) -> dict:
    """Add a person (write only unless rights say more). Returns the new person."""
    name = clean_name(name)
    rights = clean_rights(list(DEFAULT_RIGHTS) if rights is None else rights)
    made = {}

    def what(doc):
        if name.casefold() in _active_names(doc):
            raise Refused(f"{name} is already in the list.")
        if sum(1 for p in doc["people"] if not p.get("removed_at")) >= MAX_PEOPLE:
            raise Refused(f"A workspace holds at most {MAX_PEOPLE} people.")
        made.update(id=_new_id(doc), name=name, rights=rights, owner=False, added_at=now(), removed_at=None)
        doc["people"].append(dict(made))
        return f"Added {name} ({_words(rights)})"

    _change(root, what, expect=expect, by=by)
    return made


def rename(root: Path, who: str, name: str, *, expect: int | None = None, by: str | None = None) -> dict:
    name = clean_name(name)
    out = {}

    def what(doc):
        p = find(doc, who)
        if name.casefold() in _active_names(doc, but=p["id"]):
            raise Refused(f"{name} is already in the list.")
        old, p["name"] = p["name"], name
        out.update(p)
        return f"Renamed {old} to {name}"

    _change(root, what, expect=expect, by=by)
    return out


def set_rights(root: Path, who: str, rights, *, expect: int | None = None, by: str | None = None) -> dict:
    rights = clean_rights(rights)
    out = {}

    def what(doc):
        p = find(doc, who)
        if p.get("owner"):
            raise Refused("The owner always has every right.")
        p["rights"] = rights
        out.update(p)
        return f"Rights of {p['name']}: {_words(rights) or 'none'}"

    _change(root, what, expect=expect, by=by)
    return out


def remove(root: Path, who: str, *, expect: int | None = None, by: str | None = None) -> dict:
    """Mark a person removed (kept in the file, so history stays readable). The last owner never goes."""
    out = {}

    def remove_from(doc):
        p = find(doc, who)
        if p.get("owner"):
            others = [x for x in doc["people"] if x.get("owner") and not x.get("removed_at") and x is not p]
            if not others:
                raise Refused(f"{p['name']} is the last owner and can't be removed.")
        p["removed_at"] = now()
        for d in doc.get("devices") or []:
            if isinstance(d, dict) and d.get("person") == p["id"] and not d.get("cut_at"):
                d["cut_at"] = p["removed_at"]
        out.update(p)
        return f"Removed {p['name']}"

    _change(root, remove_from, expect=expect, by=by)
    return out


def _words(rights) -> str:
    return ", ".join(RIGHT_WORDS[r] for r in rights)


# ------------------------------------------------------------------ phones (step 4) and rights (step 5)
# Owner, 21 Nov: the ticks are enforced in the same pull request as the list (steps 3 to 5 together).
# A phone is paired on the relay admin page (never here). Once the list is on, the owner ties each paired
# phone to one person in Settings, at this computer; a phone that is not tied, is cut, or whose person was
# removed is refused on EVERY phone path (relay.py calls who_sent first). Rights are checked on the workspace,
# never on the relay or the phone: when a message arrives (write, decide) and again when queued work really
# starts (start).

PHONE_RE = re.compile(r"ph_[A-Za-z0-9_-]{1,64}")
ACTIONS = {  # what each phone action needs (build plan ORCH-1160 section 2)
    "text": ("write",),
    "answer": ("decide",),
    "merge": ("decide", "start"),
    "allow": ("decide", "start"),
    "mobile_off": ("decide",),
    "start": ("start",),
}
ACTION_WORDS = {
    "text": "write",
    "answer": "decide",
    "merge": "decide and start work",
    "allow": "decide and start work",
    "mobile_off": "decide",
    "start": "start work",
}
_ACTING: contextvars.ContextVar = contextvars.ContextVar("orch_people_acting", default=None)


class PhoneRefused(Refused):
    """A phone may not do this (not tied, cut, its person removed, or a right missing). `why` is plain."""


def _device(doc: dict, phone: str) -> dict | None:
    for d in doc.get("devices") or []:
        if isinstance(d, dict) and d.get("id") == phone:
            return d
    return None


def _person_by_id(doc: dict, pid: str) -> dict | None:
    return next((p for p in doc.get("people") or [] if p["id"] == pid), None)


def may(doc: dict, pid: str, *rights: str) -> bool:
    """The person has every one of `rights` (the owner has all); a removed person has none."""
    p = _person_by_id(doc, pid)
    if p is None or p.get("removed_at"):
        return False
    return bool(p.get("owner")) or all(r in p["rights"] for r in rights)


def who_sent(root: Path, phone: str, action: str, *, paired: bool = True) -> tuple[str, str] | None:
    """The person and device for a message from `phone` that wants to do `action`. None: the list is off, so
    nothing changes (as before). Raises PhoneRefused when the list is on (or damaged: fail closed) and the
    phone is unknown, not paired any more, not tied, cut, its person removed, or the person lacks a right."""
    try:
        doc = load(root)
    except Broken:
        raise PhoneRefused("the people list is damaged, so no phone is let in") from None
    if doc is None:
        return None
    if not isinstance(phone, str) or not PHONE_RE.fullmatch(phone):
        raise PhoneRefused("not a phone")
    if not paired:
        raise PhoneRefused("this phone is not paired with this workspace any more")
    d = _device(doc, phone)
    if d is None or not d.get("person"):
        raise PhoneRefused("this phone is not tied to a person yet; the owner ties it in Settings, People")
    p = _person_by_id(doc, d["person"])
    if p is None or p.get("removed_at"):
        raise PhoneRefused("the person of this phone was removed")
    if d.get("cut_at"):
        raise PhoneRefused("this phone was cut off")
    need = ACTIONS.get(action)
    if need is None:
        raise PhoneRefused("unknown action")
    if not may(doc, p["id"], *need):
        raise PhoneRefused(f"{p['name']} may not {ACTION_WORDS[action]} here")
    return p["id"], phone


@contextlib.contextmanager
def acting(who: tuple[str, str] | None):
    """While a checked phone's message is handled: its person is the actor (phone_actor) and its new history
    lines carry person and device (stamp). None (list off): nothing changes."""
    token = _ACTING.set(who)
    try:
        yield
    finally:
        _ACTING.reset(token)


def acting_phone() -> str | None:
    """The phone whose message is being handled (inside acting), else None."""
    who = _ACTING.get()
    return who[1] if who is not None else None


def phone_actor(phone: str) -> str | None:
    """`human:pr_...` while the people check let this phone in (inside acting), else None."""
    who = _ACTING.get()
    return f"human:{who[0]}" if who is not None and who[1] == phone else None


def note_refused(root: Path, phone: str, why: str) -> None:
    """One line per refused phone message in .orch/local/people-refused.jsonl (newest 200 kept; no message
    content). Written from any process (also a helper's inbox read), so not in people.json."""
    p = Path(root) / ".orch" / "local" / "people-refused.jsonl"
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = p.read_text(encoding="utf-8").splitlines()[-199:] if p.exists() else []
        lines.append(json.dumps({"at": now(), "device": phone[:70], "why": why[:200]}, ensure_ascii=False))
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, p)


def refused(root: Path, limit: int = 20) -> list[dict]:
    p = Path(root) / ".orch" / "local" / "people-refused.jsonl"
    out = []
    with contextlib.suppress(OSError):
        for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
            with contextlib.suppress(ValueError):
                x = json.loads(line)
                if isinstance(x, dict):
                    out.append(x)
    return out


def paired_now(root: Path, phone: str) -> bool:
    """The phone is in the relay's last snapshot of phones paired with this workspace (refresh writes it)."""
    snap = Path(root) / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    try:
        phones = json.loads(snap.read_text(encoding="utf-8")).get("phones") or []
    except (OSError, ValueError, AttributeError):
        return False
    return any(isinstance(p, dict) and p.get("id") == phone for p in phones)


def phone_may_start(root: Path, phone: str, queued_at: str | None = None) -> bool:
    """For queued work at the moment it would start: True when the list is off (as before), else only a tied,
    uncut phone of a person who may start work, and only for work queued after the phone's latest tie (tying a
    cut phone again never revives what it queued before). Never raises."""
    try:
        if load(root) is None:
            return True  # list off
        who_sent(root, phone, "start", paired=paired_now(root, phone))
        d = _device(load(root), phone) or {}
        if d.get("tied_at") and not queued_at:
            return False  # no time on the queued item: it can't be shown to come after the tie (fail closed)
        # same second as the tie counts as before it (times have 1 s steps): fail closed
        return not (queued_at and d.get("tied_at") and str(queued_at) <= str(d["tied_at"]))
    except PhoneRefused:
        return False
    except Exception:  # noqa: BLE001 - anything unexpected: no start (fail closed)
        return False


def tie(root: Path, phone: str, who: str, *, expect: int | None = None, by: str | None = None) -> dict:
    """Tie a paired phone to a person (at this computer only). A phone tied before keeps its id; work it
    queued before is never revived by tying it again (each queued item is checked when it starts)."""
    if not isinstance(phone, str) or not PHONE_RE.fullmatch(phone):
        raise Refused("That is not a phone id (ph_...).")
    out = {}
    kind = paired_kind(root, phone)  # a browser (ORCH-1197) is tied like a phone; the log says which it is

    def tie_to(doc):
        p = find(doc, who)
        d = _device(doc, phone)
        if d is None:
            d = {"id": phone, "kind": kind, "person": None, "tied_at": None, "cut_at": None}
            doc.setdefault("devices", []).append(d)
        d.update(person=p["id"], tied_at=now(), cut_at=None, kind=kind)
        if relay_name := _relay_phone_name(root, phone):  # kept for Settings once the relay forgets the phone
            d["name"] = relay_name
        out.update(d)
        return f"Tied {kind} {phone} to {p['name']}"

    _change(root, tie_to, expect=expect, by=by)
    return out


def _relay_phone_name(root: Path, phone: str) -> str | None:
    snap = Path(root) / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    try:
        for ph in json.loads(snap.read_text(encoding="utf-8")).get("phones") or []:
            if isinstance(ph, dict) and ph.get("id") == phone and ph.get("name"):
                return _phone_name(ph["name"], phone)
    except (OSError, ValueError, AttributeError):
        pass
    return None


def cut(root: Path, phone: str, *, expect: int | None = None, by: str | None = None) -> dict:
    """Cut one phone (a lost phone): every message from it is refused from now on; its person keeps the
    others. The caller (cli_people) then takes this workspace off the phone's list on the relay
    (drop_cut_phones), so it sees nothing more either; the relay admin page still lists the phone itself."""
    out = {}

    def cut_it(doc):
        d = _device(doc, phone)
        if d is None:
            raise Refused("That phone is not in the list.")
        if d.get("cut_at"):
            raise Refused("That phone is already cut off.")
        d["cut_at"] = now()
        out.update(d)
        return f"Cut {_kind(d)} {phone}"

    _change(root, cut_it, expect=expect, by=by)
    return out


def drop_cut_phones(root: Path, just_cut=()) -> list[str]:
    """Take this workspace off a cut phone's list on the relay (relay.drop_phone), so what goes to `phones`
    no longer reaches it: every cut phone (cut alone, or its person removed) the relay's last snapshot still
    lists, plus `just_cut` (the phones this command cut) even when an old snapshot does not list them. Called
    after a cut or a removal and again before every relay refresh, so a relay that could not be reached is
    tried again. The list off, damaged, or no relay: nothing. Returns the phones the relay confirmed off
    ("off" or "absent"). Never raises."""
    done: list[str] = []
    try:
        doc = load(root)
        if doc is None:
            return []
        from orch import relay

        cut_ids = [d.get("id") for d in doc.get("devices") or [] if isinstance(d, dict) and d.get("cut_at")]
        for ph in dict.fromkeys(cut_ids):
            if not isinstance(ph, str) or not PHONE_RE.fullmatch(ph):
                continue
            if ph not in just_cut and not paired_now(root, ph):
                continue
            try:
                relay.drop_phone(root, ph)
                done.append(ph)
            except Exception:  # noqa: BLE001 - no relay, offline, an old relay: the next refresh tries again
                continue
    except Exception:  # noqa: BLE001 - a damaged list or snapshot never undoes the cut or breaks a refresh
        pass
    return done


def ticket_may_start(root: Path, tid: str) -> tuple[bool, str | None]:
    """The run for a ticket a phone text made (ext.relay.origin = phone) starts only when that phone's person
    may start work now. Any other ticket, or the list off: yes."""
    from orch import tickets

    t = tickets.load(root, tid)
    relay = ((t.get("ext") or {}).get("relay")) or {}
    phone = relay.get("from") if relay.get("origin") == "phone" else None
    if not isinstance(phone, str):
        return True, None
    try:
        doc = load(root)
        if doc is None:
            return True, None
        who_sent(root, phone, "start", paired=paired_now(root, phone))
    except PhoneRefused as e:
        return False, str(e)
    except Broken:
        return False, "the people list is damaged"
    tied = (_device(doc, phone) or {}).get("tied_at")
    if tied and str(t.get("created_at") or "") <= str(tied):
        # made before the phone's latest tie (cut, then tied again, maybe to someone else): never revived
        return False, "this ticket came from the phone before it was tied again"
    return True, None


def start_allowed(root: Path, tid: str, by: str) -> tuple[bool, str | None]:
    """runs.start, the one place every helper start goes through (also a start that waited for a slot, and
    the helper resuming after an answer): with the list on, a start on behalf of a person of the list needs
    their Start work right; a start by orch itself (automation, a slot opening) of a ticket a phone text made
    needs that phone's person to have it, now. The person at this computer, and the list off: as before."""
    try:
        if load(root) is None:
            return True, None
    except Broken:
        return False, "the people list is damaged"
    if isinstance(by, str) and by.startswith("human:"):
        if person_may(root, by, "start"):
            return True, None
        return False, f"{show(root, by)} may not start work here"
    return ticket_may_start(root, tid)


def person_may(root: Path, by: str, *rights: str) -> bool:
    """For work checked again when it takes effect: True unless `by` is a person of the list (human:pr_...)
    who is removed or lacks a right now. A damaged list: False for a person id (fail closed)."""
    pid = by[6:] if isinstance(by, str) and by.startswith("human:") else None
    if pid is None or not _ID_RE.fullmatch(pid):
        return True
    try:
        doc = load(root)
    except Broken:
        return False
    return doc is None or may(doc, pid, *rights)  # list off: nothing is checked, as before


def _answers_path(root: Path) -> Path:
    return Path(root) / ".orch" / "local" / "people-answers.json"


def remember_answer(root: Path, tid: str, qid: str, phone: str) -> None:
    """A question whose answer takes effect later (a workspace allow): which phone answered it, so the check
    when it takes effect also covers that phone (cut, unpaired, tied to someone else since)."""
    p = _answers_path(root)
    with contextlib.suppress(OSError, ValueError):
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        d = d if isinstance(d, dict) else {}
        d[f"{tid}/{qid}"] = phone
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")  # never trimmed: a lost record would allow
        os.replace(tmp, p)


def answer_still_ok(root: Path, tid: str, qid: str, by: str, *rights: str, via: str | None = None) -> bool:
    """person_may, plus: when a phone of the list answered it, that phone is still paired, tied to the same
    person and not cut. A phone answer whose phone is not known (record missing) is refused (fail closed)."""
    if not person_may(root, by, *rights):
        return False
    pid = by[6:] if isinstance(by, str) and by.startswith("human:") else None
    if pid is None or not _ID_RE.fullmatch(pid):
        return True
    try:
        phone = json.loads(_answers_path(root).read_text(encoding="utf-8")).get(f"{tid}/{qid}")
    except (OSError, ValueError, AttributeError):
        phone = None
    if not phone:
        return via != "phone"  # answered at this computer: person_may decided; a phone we can't name: no
    try:
        doc = load(root)
    except Broken:
        return False
    d = _device(doc or {}, phone) or {}
    return d.get("person") == pid and not d.get("cut_at") and paired_now(root, phone)
