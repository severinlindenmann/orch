"""Who a ticket's person fields show as: ONE rule for every reader (contracts/history.md, human-proof.md
"What a machine shows as the person").

A ticket can hold person attribution in several fields: history[].by, checklist[].evidence[].by,
checklist[].by and wont_by, verdicts[].person, questions[].answered_by, refs[].by, plan.by and
description_by. Once sync is ENABLED for a workspace (sync_enabled), a field whose value is not a plain agent
label shows as written only when this core can prove it here:

  (a) core created that exact object (a history line, a piece of evidence, a reference, a step's "doing" mark)
      on this machine: the ONE history-append point (tickets.add_history), the ONE evidence-append point
      (tickets.add_evidence), the ref-add point and the step-start point (tickets.check_start: the step's id,
      state, by and at) mark the object they create (`created`); tickets._write, the one write path, records
      the canonical digest of every marked object that is in the ticket it writes (`register_written`) in a
      local store, .orch/run/own-lines/<ticket id>.json (never synced), carrying this core's local1 MAC. The
      old file is never diffed against the new one: a line core did not create in this process is never
      recorded. A store that cannot be written leaves the object unverified (fail closed); or
  (b) a decision this core verifies binds it: the line a current verdict or a Won't do this core's ledger
      vouches for was signed with (person, {text, via} digest, at), matched ONCE (the closest line within 5 s
      of the decision; any other copy is not the decision's), the decision's own person field (wont_by,
      verdict person, the step's by on a verified Won't do), and a question's answered_by when a proven line
      of that actor records exactly that answer.

Everything else is shown as SYNC_BY ("(synced, not verified here) " before a history text), to people and
agents alike. The stored bytes are never changed (both machines keep the same file).

A workspace where sync was never enabled is not touched: shown_ticket returns the very same object, no store
is read or written, so the output is byte-for-byte what it was without this module.

Readers never read `history` or evidence `by` themselves (tests/test_history_lint.py): they take `lines`,
`shown_ticket` or `shown_json` with the workspace root (required: a caller without one looks it up).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from orch import humanproof, safefile

SYNC_BY = "agent:sync"  # reserved: tickets.current_actor refuses it, only core and the sync merge write it
SYNCED_UNVERIFIED = "(synced, not verified here) "
RESERVED_AGENT_LABELS = ("sync",)
OWN_LINES = (".orch", "run", "own-lines")  # local-only (run/ is never synced); one MAC'd file per ticket
SYNC_REPO = (".orch", ".git")  # the sync add-on's state repository
SYNC_RUN = (".orch", "run", "sync")  # the sync add-on's local records
ENABLED_DIR = "sync-enabled"  # guarded orch home: <sha256("path:"+realpath)>.json and <sha256("ws:"+id)>.json
OWN_MAX = 20_000  # digests kept per kind and ticket (the oldest go first)
OWN_BYTES = 4 * 1024 * 1024  # a larger store file verifies nothing for THAT ticket only
DECISION_SECONDS = 5
_TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
KINDS = ("lines", "evidence", "refs", "steps")
_REF_LOOSE = ("title", "status", "thumb")  # an add-on or a person edits these later; not part of the digest
_STEP_MARK = ("id", "state", "by", "at")  # a step's "doing" mark (tickets.check_start); the rest changes


def is_agent_history_author(by) -> bool:
    """Only explicit agent labels are safe as unverified attribution (orch_sync.merge has the same rule)."""
    if not isinstance(by, str) or not by.isascii() or by != unicodedata.normalize("NFKC", by):
        return False
    label = by.casefold()
    return bool(re.fullmatch(r"agent:[a-z0-9._-]{1,40}", label)) and not label[6:].startswith(
        ("relay", "phone", "ph_")
    )


def is_reserved_label(by) -> bool:
    """agent:sync (any case): only core and the sync merge give a line this label, never a real agent."""
    return isinstance(by, str) and by.casefold() in {f"agent:{x}" for x in RESERVED_AGENT_LABELS}


def needs_proof(by) -> bool:
    """A value that would be believed as written (not a plain agent label) needs proof once sync is on."""
    return not is_agent_history_author(by)


def is_person_line(line) -> bool:
    """A SHOWN line or entry (from `lines` / `shown_ticket`) is the person's: its author is human:<name>.
    Never ask this of a raw stored value."""
    by = line.get("by") if isinstance(line, dict) else line
    return isinstance(by, str) and by.startswith("human:") and len(by) > len("human:")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(kind: str, obj) -> str | None:
    """sha256 of the canonical JSON of [kind, object]; None when it cannot be written canonically (NaN, a lone
    surrogate, ...): such an object is never verified."""
    try:
        if kind == "refs" and isinstance(obj, dict):
            obj = {k: v for k, v in obj.items() if k not in _REF_LOOSE}
        if kind == "steps" and isinstance(obj, dict):
            obj = {k: obj.get(k) for k in _STEP_MARK}
        return hashlib.sha256(_canon([kind, obj]).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError):
        return None


def line_digest(line) -> str | None:
    return _digest("lines", line)


# ----------------------------------------------------------------------- objects core created (append points)

_CREATED: dict[int, tuple[str, object]] = {}  # id(obj) -> (kind, obj); the reference keeps the id unique
_CREATED_LOCK = threading.Lock()
_CREATED_MAX = 4096


def created(kind: str, obj) -> None:
    """Called by core's append points ONLY (tickets.add_history, tickets.add_evidence, tickets.ref_add and the
    step-start point tickets.check_start): this exact object was made by core in this call. It is recorded
    when the ticket holding it is written."""
    if kind not in KINDS or not isinstance(obj, dict):
        return
    with _CREATED_LOCK:
        if len(_CREATED) >= _CREATED_MAX:  # objects of ops that never wrote (refused): the oldest go
            for k in list(_CREATED)[: _CREATED_MAX // 2]:
                del _CREATED[k]
        _CREATED[id(obj)] = (kind, obj)


def _take_created(ticket: dict) -> dict[str, list]:
    """The marked objects that are in `ticket` (by identity, never by content), removed from the marks."""
    found: dict[str, list] = {k: [] for k in KINDS}
    with _CREATED_LOCK:
        if not _CREATED:
            return found

        def take(kind, obj):
            hit = _CREATED.get(id(obj))
            if hit is not None and hit[1] is obj and hit[0] == kind:
                del _CREATED[id(obj)]
                found[kind].append(obj)

        for h in ticket.get("history") if isinstance(ticket.get("history"), list) else []:
            take("lines", h)
        for c in ticket.get("checklist") if isinstance(ticket.get("checklist"), list) else []:
            if isinstance(c, dict):
                take("steps", c)
            for ev in (c.get("evidence") if isinstance(c, dict) else None) or []:
                take("evidence", ev)
        for r in ticket.get("refs") if isinstance(ticket.get("refs"), list) else []:
            take("refs", r)
    return found


def register_written(root: Path, ticket: dict) -> None:
    """tickets._write, under the ticket lock, before the file is replaced: record the objects core created for
    this ticket in this process (`created`). Only once sync is enabled. Never raises; a failure leaves them
    unverified (fail closed)."""
    try:
        if not isinstance(ticket, dict):
            return
        found = _take_created(ticket)
        if not any(found.values()) or not sync_enabled(root):
            return
        remember(root, ticket.get("id"), found)
    except Exception:  # noqa: BLE001 - recording is best effort; a missed object only shows as not verified
        pass


# ------------------------------------------------------------------------------------- sync enabled

_ENABLED: dict[str, object] = {}  # realpath -> True (for good in this process) | the state key of a "no"
_TICKET_MARKS: dict[tuple, bool] = {}  # (path, mtime_ns, size) -> the file shows sync


def _keys(root: Path) -> list[str]:
    out = ["path:" + os.path.realpath(root)]
    with contextlib.suppress(Exception):
        from orch import addons

        ws = addons.workspace_id(Path(root), create=False)
        if ws:
            out.append("ws:" + ws)
    return out


def _enabled_paths(root: Path) -> list[Path]:
    """Where the enabled record may be: per key (the workspace's real path AND its id), in the guarded home
    and in the account's default orch home (an environment that makes the guarded home refuse cannot hide a
    real install's record)."""
    names = [hashlib.sha256(k.encode()).hexdigest()[:32] + ".json" for k in _keys(root)]
    homes = []
    with contextlib.suppress(Exception):
        homes.append(humanproof.guarded_home(root))
    with contextlib.suppress(Exception):
        homes.append(humanproof.account_home() / ".orch-tool")
    return [h / ENABLED_DIR / n for h in homes for n in names]


def enabled_recorded(root: Path) -> bool:
    return any(os.path.lexists(p) for p in _enabled_paths(Path(root)))


def _ticket_shows_sync(p: Path) -> bool:
    try:
        st = os.lstat(p)
        key = (str(p), st.st_mtime_ns, st.st_size)
        if key in _TICKET_MARKS:
            return _TICKET_MARKS[key]
        raw = p.read_bytes() if st.st_size <= 64 * 1024 * 1024 else b""
        hit = False
        if b"agent:sync" in raw or b'"sync"' in raw:
            doc = json.loads(raw)
            ext = doc.get("ext") if isinstance(doc, dict) else None
            hist = doc.get("history") if isinstance(doc, dict) else None
            hist = hist if isinstance(hist, list) else []
            hit = (isinstance(ext, dict) and "sync" in ext) or any(
                isinstance(h, dict) and is_reserved_label(h.get("by")) for h in hist
            )
    except (OSError, ValueError, RecursionError, AttributeError):
        return False
    if len(_TICKET_MARKS) > 20_000:
        _TICKET_MARKS.clear()
    _TICKET_MARKS[key] = hit
    return hit


def tickets_show_sync(root: Path) -> bool:
    """Some ticket carries sync's own traces (ext.sync, or a line by the reserved sync label)."""
    folder = Path(root, ".orch", "tickets")
    try:
        files = sorted(folder.glob("t_*.json"))
    except OSError:
        return False
    return any(_ticket_shows_sync(p) for p in files)


def _state_key(root: Path) -> tuple:
    out = []
    for parts in ((".orch",), (".orch", "run"), (".orch", "tickets")):
        try:
            out.append(os.lstat(Path(root, *parts)).st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def sync_enabled(root: Path) -> bool:
    """Is sync enabled for this workspace (now or ever)? Any of: the sync repository (.orch/.git), the sync
    add-on's local records (.orch/run/sync), the enabled record (keyed by real path AND workspace id), or a
    ticket showing sync's traces. Only "none of these" is sync-free. `root` is required."""
    if root is None:
        raise TypeError("history.sync_enabled needs the workspace root")
    root = Path(root)
    rp = os.path.realpath(root)
    if _ENABLED.get(rp) is True:
        return True
    state = _state_key(root)
    if _ENABLED.get(rp) == state:
        return False
    found = (
        os.path.lexists(Path(root, *SYNC_REPO))
        or os.path.lexists(Path(root, *SYNC_RUN))
        or enabled_recorded(root)
        or tickets_show_sync(root)
    )
    _ENABLED[rp] = True if found else state
    return found


def ensure_key(root: Path) -> None:
    """The workspace's local id and human key exist (the store and the record are signed with it). Raises
    Refused when the guarded orch home cannot be used."""
    from orch import addons

    addons.workspace_id(Path(root), create=True)
    humanproof.key_dir(Path(root))
    humanproof.human_key(Path(root))
    _KEYS.pop(os.path.realpath(root), None)  # a cached "no key" answer is stale now


def enable_sync(root: Path, adopt: bool = False) -> bool:
    """The sync add-on calls this first in every repo.ensure, whatever state the repository is in (before it
    can refuse). Once per workspace and only with `adopt` (the add-on passes it for a workspace that never
    synced: no state repository, no earlier step's state): adopt the person fields already in this machine's
    tickets as its own, but NEVER when a ticket already shows sync's traces (they may hold another machine's
    lines) or the record exists; then write the record (keyed by real path and workspace id). True when this
    call adopted. Raises Refused when the record cannot be written: sync must not run without it."""
    from orch.errors import Refused

    root = Path(root)
    ensure_key(root)
    adopted = False
    if adopt and not enabled_recorded(root) and not tickets_show_sync(root):
        adopt_local_objects(root)
        adopted = True
    home = humanproof.guarded_home(root)
    folder = home / ENABLED_DIR
    humanproof._private_dir(folder, home)
    keys = _keys(root)
    record = {"schema": "orch.sync-enabled/2", "keys": keys, "at": int(time.time())}
    mac = humanproof.local_sign(root, "sync-enabled", record)
    if not mac:
        raise Refused("orch could not record that sync is on here; sync was not started.")
    body = json.dumps({**record, "mac": mac}) + "\n"
    for k in keys:  # one file per key: a moved folder (same id) or a new id (same folder) still finds one
        p = folder / (hashlib.sha256(k.encode()).hexdigest()[:32] + ".json")
        if not os.path.lexists(p):
            humanproof._write_private(p, body)
    _ENABLED[os.path.realpath(root)] = True
    return adopted


# ----------------------------------------------------------------------------------- own-objects store

_OWN_CACHE: dict[tuple, dict | None] = {}
_KEYS: dict[str, tuple[float, object]] = {}
_KEY_FOR = 2.0  # seconds the workspace key is reused in one process


def _ctx_key(root: Path):
    rp = os.path.realpath(root)
    got = _KEYS.get(rp)
    if got and time.monotonic() - got[0] < _KEY_FOR:
        return got[1]
    ctx = humanproof.local_key(root)
    _KEYS[rp] = (time.monotonic(), ctx)
    return ctx


def _own_path(root: Path, tid: str) -> Path:
    return Path(root, *OWN_LINES, f"{tid}.json")


def _own_record(tid: str, have: dict) -> dict:
    # "steps" is in the record (and the file) only once it holds a digest: a store written before it verifies
    return {"ticket": tid, **{k: have[k] for k in KINDS if k != "steps" or have.get(k)}}


def _parse_own(raw: bytes, tid: str, root: Path, ctx) -> dict | None:
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("schema") != "orch.own-lines/2" or data.get("ticket") != tid:
        return None
    have = {}
    for k in KINDS:
        v = data.get(k, [] if k == "steps" else None)
        if not isinstance(v, list) or len(v) > OWN_MAX:
            return None
        if not all(isinstance(d, str) and _DIGEST_RE.fullmatch(d) for d in v):
            return None
        have[k] = v
    if not humanproof.local_ok(root, "own-lines", _own_record(tid, have), data.get("mac"), ctx):
        return None
    return have


def _read_own(root: Path, tid: str, ctx) -> dict | None:
    try:
        st = os.lstat(_own_path(root, tid))
        if st.st_size > OWN_BYTES:
            return None
        raw = safefile._read_parts(Path(root), list(OWN_LINES), [f"{tid}.json"], OWN_BYTES)
    except (OSError, safefile.TooLarge, ValueError):
        return None
    return _parse_own(raw, tid, Path(root), ctx) if raw is not None else None


def _own(root: Path, tid, ctx) -> dict | None:
    """The digests this core recorded for ticket `tid`, as sets per kind: parsed once per file state. None =
    nothing verifies (no store, unreadable, oversized, MAC fails, a bad ticket id)."""
    if ctx is None or not isinstance(tid, str) or not _TID_RE.fullmatch(tid):
        return None
    p = _own_path(root, tid)
    try:
        st = os.lstat(p)
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size, st.st_ino, hashlib.sha256(ctx[1]).hexdigest()[:16])
    if key in _OWN_CACHE:
        return _OWN_CACHE[key]
    have = _read_own(root, tid, ctx)
    out = {k: frozenset(v) for k, v in have.items()} if have is not None else None
    if len(_OWN_CACHE) > 4096:
        _OWN_CACHE.clear()
    _OWN_CACHE[key] = out
    return out


def remember(root: Path, tid, found: dict[str, list]) -> bool:
    """Record these objects of ticket `tid` (per kind) as made by this core. The caller holds the ticket's
    lock. False when nothing could be recorded (they then show as not verified here: fail closed). A store
    that cannot be trusted is started again (what it held shows as not verified)."""
    if not isinstance(tid, str) or not _TID_RE.fullmatch(tid):
        return False
    new = {k: [d for d in (_digest(k, o) for o in found.get(k) or []) if d] for k in KINDS}
    if not any(new.values()):
        return True
    root = Path(root)
    ctx = humanproof.local_key(root)
    if ctx is None:
        return False
    have = _read_own(root, tid, ctx) if os.path.lexists(_own_path(root, tid)) else None
    have = have or {k: [] for k in KINDS}
    merged = {k: list(dict.fromkeys([*have[k], *new[k]]))[-OWN_MAX:] for k in KINDS}
    if merged == have:
        return True
    mac = humanproof.local_sign(root, "own-lines", _own_record(tid, merged), ctx)
    if not mac:
        return False
    body = {"schema": "orch.own-lines/2", **_own_record(tid, merged), "mac": mac}
    p = _own_path(root, tid)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{secrets.token_hex(4)}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(body, separators=(",", ":")))
            os.replace(tmp, p)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
    except OSError:
        return False
    return True


def adopt_local_objects(root: Path) -> int:
    """The one-time adoption when sync is first enabled (enable_sync, BEFORE the first fetch and only when no
    ticket shows sync's traces): the person fields already in this machine's tickets are its own. Returns how
    many tickets were adopted."""
    from orch import tickets

    root = Path(root)
    folder = tickets.tickets_dir(root)
    if not folder.is_dir():
        return 0
    n = 0
    for p in sorted(folder.glob("t_*.json")):
        tid = p.stem
        if not _TID_RE.fullmatch(tid) or p.is_symlink():
            continue
        try:
            with tickets._locked(root, tid):
                doc = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(doc, dict) or doc.get("id") != tid:
                    continue
                found = {
                    "lines": [h for h in doc.get("history") or [] if isinstance(h, dict)],
                    "evidence": [
                        e
                        for c in doc.get("checklist") or []
                        if isinstance(c, dict)
                        for e in c.get("evidence") or []
                        if isinstance(e, dict)
                    ],
                    "refs": [r for r in doc.get("refs") or [] if isinstance(r, dict)],
                    "steps": [c for c in doc.get("checklist") or [] if isinstance(c, dict) and "by" in c],
                }
                if remember(root, tid, found):
                    n += 1
        except Exception:  # noqa: BLE001 - a ticket that cannot be read adopts nothing (its lines: unverified)
            continue
    return n


# ------------------------------------------------------------------------------------- decisions (b)


def _at(v) -> float | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


class _Proof:
    """Everything one read needs to judge person fields, built once per call (shown_json over many tickets
    shares it): the key, the verdict checker (ledger snapshot), the Won't do ledger (read once)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.ctx = _ctx_key(self.root)
        self._checker = None
        self._wont = None
        self._wont_read = False

    def verdict_state(self, entry, ticket) -> str | None:
        if self._checker is None:
            self._checker = humanproof.VerdictChecker(self.root, snapshot=True)
        try:
            return self._checker.state(entry, ticket)
        except Exception:  # noqa: BLE001 - fail closed
            return None

    def wont_ok(self, step, tid) -> bool:
        if not isinstance(step, dict) or not isinstance(tid, str) or self.ctx is None:
            return False
        if not self._wont_read:
            self._wont_read = True
            self._wont = humanproof._ledger_read(self.root)
        led = self._wont
        mac, cur = step.get("wont_mac"), (led or {}).get(f"{tid}:{step.get('id')}")
        if not isinstance(mac, str) or not mac or not isinstance(cur, str) or mac != cur:
            return False
        try:
            return humanproof.wontdo_is_human(
                self.ctx[1], self.ctx[0], tid, humanproof.wont_decision(step), mac, False
            )
        except Exception:  # noqa: BLE001
            return False


def _decision_lines(proof: _Proof, ticket: dict, hist: list) -> set[int]:
    """Indexes of the history lines a verified decision on this ticket was signed with: per decision
    (person, line digest, at) the ONE matching line closest to its time (within DECISION_SECONDS)."""
    tid = ticket.get("id")
    decisions = []
    for e in ticket.get("verdicts") if isinstance(ticket.get("verdicts"), list) else []:
        if (
            isinstance(e, dict)
            and isinstance(e.get("line"), str)
            and proof.verdict_state(e, ticket) == "current"
        ):
            decisions.append((e.get("person"), e["line"], _at(e.get("at"))))
    for c in ticket.get("checklist") if isinstance(ticket.get("checklist"), list) else []:
        if (
            isinstance(c, dict)
            and c.get("wont_do") is True
            and isinstance(c.get("wont_line"), str)
            and proof.wont_ok(c, tid)
        ):
            decisions.append((c.get("wont_by"), c["wont_line"], _at(c.get("wont_at"))))
    out: set[int] = set()
    for person, digest, at in decisions:
        if not isinstance(person, str) or at is None:
            continue
        best = None
        for i, h in enumerate(hist):
            if i in out or not isinstance(h, dict) or h.get("by") != person:
                continue
            if (
                set(h) - {"at", "by", "via", "text", "chat_message"}
                or h.get("chat_message", False) is not False
            ):
                continue
            hat = _at(h.get("at"))
            if hat is None or abs(hat - at) > DECISION_SECONDS:
                continue
            try:
                if humanproof.history_digest(h.get("text"), h.get("via")) != digest:
                    continue
            except (TypeError, ValueError):
                continue
            if best is None or abs(hat - at) < best[0]:
                best = (abs(hat - at), i)
        if best is not None:
            out.add(best[1])
    return out


# ------------------------------------------------------------------------------------------- shown


def _demoted_line(h: dict) -> dict:
    return {**h, "by": SYNC_BY, "text": SYNCED_UNVERIFIED + str(h.get("text", ""))}


def _shown(proof: _Proof, t: dict) -> dict:
    tid = t.get("id")
    own = _own(proof.root, tid, proof.ctx) or {}
    has = lambda kind, obj: (d := _digest(kind, obj)) is not None and d in own.get(kind, ())  # noqa: E731
    out = dict(t)
    changed = False

    hist = t.get("history") if isinstance(t.get("history"), list) else None
    if hist is not None and any(isinstance(h, dict) and needs_proof(h.get("by")) for h in hist):
        decided = None
        new_hist = []
        for i, h in enumerate(hist):
            if isinstance(h, dict) and needs_proof(h.get("by")) and not has("lines", h):
                if decided is None:
                    decided = _decision_lines(proof, t, hist)
                if i not in decided:
                    new_hist.append(_demoted_line(h))
                    continue
            new_hist.append(h)
        if new_hist != hist:
            out["history"], changed = new_hist, True
    proven_lines = [
        h for h in (out.get("history") if isinstance(out.get("history"), list) else []) if isinstance(h, dict)
    ]

    checklist = t.get("checklist") if isinstance(t.get("checklist"), list) else None
    if checklist is not None:
        new_list = []
        for c in checklist:
            if not isinstance(c, dict):
                new_list.append(c)
                continue
            nc = c
            evs = c.get("evidence") if isinstance(c.get("evidence"), list) else None
            if evs is not None:
                # Every piece not in the own store is the sync role, with or without a `by` (an agent's too):
                # readers would otherwise give it an author (evidence_author falls back to the step's line).
                new_evs = [
                    {**e, "by": SYNC_BY} if isinstance(e, dict) and not has("evidence", e) else e for e in evs
                ]
                if new_evs != evs:
                    nc = {**nc, "evidence": new_evs}
            wont_proven = None
            for field in ("wont_by", "by"):
                if field == "by" and has("steps", c):  # a "doing" mark core made here (tickets.check_start)
                    continue
                if field in c and needs_proof(c.get(field)):
                    if wont_proven is None:
                        wont_proven = c.get("wont_do") is True and proof.wont_ok(c, tid)
                    if not wont_proven:
                        nc = {**nc, field: SYNC_BY}
            new_list.append(nc)
        if any(a is not b for a, b in zip(new_list, checklist, strict=True)):
            out["checklist"], changed = new_list, True

    verdicts = t.get("verdicts") if isinstance(t.get("verdicts"), list) else None
    if verdicts is not None:
        new_v = [
            {**e, "person": SYNC_BY}
            if isinstance(e, dict) and "person" in e and proof.verdict_state(e, t) != "current"
            else e
            for e in verdicts
        ]
        if any(a is not b for a, b in zip(new_v, verdicts, strict=True)):
            out["verdicts"], changed = new_v, True

    questions = t.get("questions") if isinstance(t.get("questions"), list) else None
    if questions is not None:
        said = {(h.get("by"), h.get("text")) for h in proven_lines if not is_reserved_label(h.get("by"))}
        new_q = []
        for q in questions:
            if (
                isinstance(q, dict)
                and q.get("answered_by") is not None
                and needs_proof(q.get("answered_by"))
                and (q.get("answered_by"), f"Answered {q.get('id')}: {q.get('answer')}") not in said
            ):
                q = {**q, "answered_by": SYNC_BY}
            new_q.append(q)
        if any(a is not b for a, b in zip(new_q, questions, strict=True)):
            out["questions"], changed = new_q, True

    refs_ = t.get("refs") if isinstance(t.get("refs"), list) else None
    if refs_ is not None:
        new_r = [
            {**r, "by": SYNC_BY}
            if isinstance(r, dict) and "by" in r and needs_proof(r.get("by")) and not has("refs", r)
            else r
            for r in refs_
        ]
        if any(a is not b for a, b in zip(new_r, refs_, strict=True)):
            out["refs"], changed = new_r, True

    if "description_by" in t and needs_proof(t.get("description_by")):
        out["description_by"], changed = SYNC_BY, True
    if isinstance(t.get("plan"), dict) and "by" in t["plan"] and needs_proof(t["plan"].get("by")):
        out["plan"], changed = {**t["plan"], "by": SYNC_BY}, True
    return out if changed else t


def answer_proven(root: Path, ticket, question) -> bool:
    """May an answer act as an AUTHORITY here (relay.apply_allow_answers)? Sync never enabled: yes, as before.
    Otherwise only when this core made the answer's own line here: the "Answered <id>: <answer>" line of
    exactly `answered_by` (and `via`) in this machine's own-lines store (tickets.answer registers it at core's
    append point; the phone and relay answer through it too). Any label counts only so, an agent's too: a
    peer's synced answer never decides on this machine. Never raises (an error is no proof)."""
    root = _need_root(root)
    try:
        if not sync_enabled(root):
            return True
        if not isinstance(ticket, dict) or not isinstance(question, dict):
            return False
        by, ans = question.get("answered_by"), question.get("answer")
        if not isinstance(by, str) or ans is None or is_reserved_label(by):
            return False
        own = _own(root, ticket.get("id"), _ctx_key(root)) or {}
        text = f"Answered {question.get('id')}: {ans}"
        hist = ticket.get("history") if isinstance(ticket.get("history"), list) else []
        return any(
            isinstance(h, dict)
            and h.get("by") == by
            and h.get("text") == text
            and ("via" not in question or h.get("via") == question.get("via"))
            and line_digest(h) in own.get("lines", ())
            for h in hist
        )
    except Exception:  # noqa: BLE001 - fail closed
        return False


def _need_root(root) -> Path:
    if root is None:
        raise TypeError("orch.history needs the workspace root (look it up; never None)")
    return Path(root)


def shown_ticket(root: Path, ticket, _proof: _Proof | None = None):
    """The ticket to SHOW or give to an agent: every person field this core cannot prove here is SYNC_BY (a
    history text gets "(synced, not verified here) " in front). A copy; the input is never changed. Sync never
    enabled: the very same object. Idempotent."""
    root = _need_root(root)
    if not isinstance(ticket, dict) or not sync_enabled(root):
        return ticket
    try:
        return _shown(_proof or _Proof(root), ticket)
    except Exception:  # noqa: BLE001 - never show a person we could not check: every person field demoted
        return _all_demoted(ticket)


def _all_demoted(t: dict) -> dict:
    out = dict(t)
    if isinstance(t.get("history"), list):
        out["history"] = [
            _demoted_line(h) if isinstance(h, dict) and needs_proof(h.get("by")) else h for h in t["history"]
        ]
    if isinstance(t.get("checklist"), list):
        out["checklist"] = [
            {
                **c,
                **{f: SYNC_BY for f in ("by", "wont_by") if f in c and needs_proof(c.get(f))},
                "evidence": [
                    {**e, "by": SYNC_BY} if isinstance(e, dict) else e for e in c.get("evidence") or []
                ],
            }
            if isinstance(c, dict)
            else c
            for c in t["checklist"]
        ]
    for field, key in (("verdicts", "person"), ("questions", "answered_by"), ("refs", "by")):
        if isinstance(t.get(field), list):
            out[field] = [
                {**x, key: SYNC_BY}
                if isinstance(x, dict) and x.get(key) is not None and needs_proof(x[key])
                else x
                for x in t[field]
            ]
    if "description_by" in t:
        out["description_by"] = SYNC_BY if needs_proof(t.get("description_by")) else t["description_by"]
    return out


def lines(root: Path, ticket) -> list:
    """The ticket's history as shown (shown_ticket). [] for anything that is not a ticket with a history."""
    shown = shown_ticket(root, ticket)
    hist = shown.get("history") if isinstance(shown, dict) else None
    return hist if isinstance(hist, list) else []


def length(ticket) -> int:
    """How many history lines the stored ticket has (a position, never an author)."""
    hist = ticket.get("history") if isinstance(ticket, dict) else None
    return len(hist) if isinstance(hist, list) else 0


def _is_ticket(data) -> bool:
    return (
        isinstance(data, dict) and isinstance(data.get("id"), str) and isinstance(data.get("history"), list)
    )


def shown_json(root: Path, data, _proof: _Proof | None = None, _depth: int = 0):
    """JSON an agent or a person reads (`orch ticket show --json`, `list --json`, ...): every ticket in `data`
    (a ticket, or one inside a list or a dict) through shown_ticket. Other data is returned as it is."""
    root = _need_root(root)
    if _depth > 64 or not sync_enabled(root):
        return data
    proof = _proof or _Proof(root)
    if _is_ticket(data):
        return shown_ticket(root, data, proof)
    if isinstance(data, list):
        return [shown_json(root, x, proof, _depth + 1) for x in data]
    if isinstance(data, dict):
        return {k: shown_json(root, v, proof, _depth + 1) for k, v in data.items()}
    return data


def evidence_author(ticket: dict, check: dict, ev: dict) -> str:
    """ "person" or "agent" for one piece of evidence of a SHOWN ticket: its own `by`, else the author of the
    step's "Check <id> done" line."""
    by = ev.get("by") if isinstance(ev, dict) else None
    if not by:
        hist = ticket.get("history") if isinstance(ticket.get("history"), list) else []
        line = next(
            (
                h
                for h in reversed(hist)
                if isinstance(h, dict) and h.get("text") == f"Check {check.get('id')} done"
            ),
            None,
        )
        by = line.get("by") if line else ""
    return "person" if is_person_line(by) else "agent"


def here() -> Path:
    """The workspace of this command when a caller holds no root: ORCH_ROOT, else the nearest folder with
    .orch above the current folder, else the current folder (sync_enabled then answers for that folder)."""
    with contextlib.suppress(OSError, ValueError, RuntimeError):
        env = os.environ.get("ORCH_ROOT")
        start = Path(env).resolve() if env else Path.cwd().resolve()
        return next((p for p in (start, *start.parents) if (p / ".orch").is_dir()), start)
    return Path.cwd()


def args_root(args) -> Path:
    """The root a CLI command runs in (cli.run sets args.orch_root), looked up when a caller set none."""
    root = getattr(args, "orch_root", None)
    return Path(root) if root is not None else here()


def ticket_root(path) -> Path | None:
    """The workspace a ticket file belongs to (<root>/.orch/tickets/<id>.json), for readers that only hold a
    path."""
    p = Path(path)
    return p.parent.parent.parent if p.parent.name == "tickets" and p.parent.parent.name == ".orch" else None
