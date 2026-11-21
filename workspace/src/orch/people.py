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
    }


# ------------------------------------------------------------------ stamping new history lines


LOCAL_VIA = ("cli", "dashboard")  # where a line made at this computer comes from (tickets._env_via)


def stamp(root: Path, line: dict) -> None:
    """A NEW history line core made in this process (tickets._write calls it before the digest is recorded):
    once the list is on, a person's action at this machine records the owner's person id and device `machine`.
    Allowlist only: a human line from this computer's CLI or dashboard (via cli / dashboard), not from a
    helper's environment and not a phone (`human:ph_...`). A person id typed in `--by` still stamps the owner
    (whoever sits at the machine is the owner). Everything else stays unstamped: phones (step 4), relay and
    chat lines from other workspaces, helpers, system lines. A line that names a person is left alone.
    Never raises."""
    try:
        if not isinstance(line, dict) or "person" in line:
            return
        by, via = line.get("by"), line.get("via")
        if not isinstance(by, str) or not by.startswith("human:") or via not in LOCAL_VIA:
            return
        if by.startswith(("human:ph_", "human:br_")):
            return
        from orch import tickets

        if tickets.agent_tool():
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


def _guard() -> None:
    from orch import tickets

    if tickets.agent_tool():
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


def _change(root: Path, what, *, expect: int | None = None) -> dict:
    """Under the lock: load, check the revision the person saw (if given), apply `what(doc) -> log`, save."""
    _guard()
    with _locked(root):
        doc = load(root)
        if doc is None:
            raise Refused("The people list is off. Turn it on first: orch people on.")
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


def turn_on(root: Path, owner_name: str) -> dict:
    """Make the list with the person at this machine as its owner. Refused when it is already on."""
    _guard()
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


def add(root: Path, name: str, rights=None, *, expect: int | None = None) -> dict:
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

    _change(root, what, expect=expect)
    return made


def rename(root: Path, who: str, name: str, *, expect: int | None = None) -> dict:
    name = clean_name(name)
    out = {}

    def what(doc):
        p = find(doc, who)
        if name.casefold() in _active_names(doc, but=p["id"]):
            raise Refused(f"{name} is already in the list.")
        old, p["name"] = p["name"], name
        out.update(p)
        return f"Renamed {old} to {name}"

    _change(root, what, expect=expect)
    return out


def set_rights(root: Path, who: str, rights, *, expect: int | None = None) -> dict:
    rights = clean_rights(rights)
    out = {}

    def what(doc):
        p = find(doc, who)
        if p.get("owner"):
            raise Refused("The owner always has every right.")
        p["rights"] = rights
        out.update(p)
        return f"Rights of {p['name']}: {_words(rights) or 'none'}"

    _change(root, what, expect=expect)
    return out


def remove(root: Path, who: str, *, expect: int | None = None) -> dict:
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

    _change(root, remove_from, expect=expect)
    return out


def _words(rights) -> str:
    return ", ".join(RIGHT_WORDS[r] for r in rights)
