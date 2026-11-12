"""Record MAC: authenticated record lines, one hash chain per run.

Contract: contracts/activity.md, "Authenticated record".

Pure core, stdlib only, no I/O, no clock, no globals. It never reads a key: every function takes the record
subkey `rk` (derived once by `humanproof.record_key`). The independent reference is `contracts/validate.py`
(`record_verify`), which uses `hmac` directly and shares no code with this module.

Invariant A1: a line counts only when it carries this workspace's MAC over its exact bytes, its run, its
seq and its predecessor's MAC. `verify_run` is the one place that decides it. Nothing here logs or raises a
text that contains key material.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field

SUFFIX_LEN = 125  # b',"auth":{"k":"' + 8 + b'","p":"' + 43 + b'","m":"' + 43 + b'"}}'
_SUFFIX = re.compile(
    rb',"auth":\{"k":"([0-9a-f]{8})","p":"([A-Za-z0-9_-]{43})","m":"([A-Za-z0-9_-]{43})"\}\}\Z'
)
_TAIL = SUFFIX_LEN

_SALT = b"orch.record/1"
_D_MAC = b"orch.record.mac/1\0"
_D_KID = b"orch.record.kid/1\0"
_D_GENESIS = b"orch.record.genesis/1\0"
_D_LINE = b"orch.record.line/1\0"
_D_SPOOL = b"orch.record.spool/1\0"
_D_JOB = b"orch.record.job/1\0"
_D_JOB_GENESIS = b"orch.record.job.genesis/1\0"
_D_HEAD = b"orch.record.head/1\0"

REASONS = ("content", "removed", "unverified", "old_key")


class SealError(ValueError):
    """The body cannot be sealed (never carries key material)."""


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _mac(rk: bytes, msg: bytes) -> str:
    return _b64u(hmac.new(rk, msg, hashlib.sha256).digest())


def _enc(s: str) -> bytes:
    return s.encode("utf-8")


def canon_strict(obj) -> bytes:
    """Canonical JSON bytes (sorted keys, compact, UTF-8, no NaN/Infinity) for MACs over structures."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


# ------------------------------ key


def derive(human_key: bytes, ws: str) -> tuple[bytes, str]:
    """(rk, kid) from the workspace's human key: HKDF-SHA256 (extract, one expand block). A subkey, never the
    human key itself, so a record MAC can never pass as a profile1/action1/verdict1/local1 MAC."""
    if not isinstance(human_key, bytes | bytearray) or len(human_key) != 32:
        raise SealError("bad key")
    prk = hmac.new(_SALT, bytes(human_key), hashlib.sha256).digest()
    rk = hmac.new(prk, _D_MAC + _enc(ws) + b"\x01", hashlib.sha256).digest()
    kid = hashlib.sha256(_D_KID + rk).hexdigest()[:8]
    return rk, kid


def genesis(rk: bytes, ws: str, run: str) -> str:
    """The `p` of seq 1 of a run (a key rotation restarts at seq 1 with the new genesis)."""
    return _mac(rk, _D_GENESIS + _enc(ws) + b"\0" + _enc(run))


def job_genesis(rk: bytes, ws: str, run: str, job: str) -> str:
    return _mac(rk, _D_JOB_GENESIS + _enc(ws) + b"\0" + _enc(run) + b"\0" + _enc(job))


# ------------------------------ seal


def _line_msg(domain: bytes, ws: str, scope: tuple[str, ...], seq: int, prev: str, body: bytes) -> bytes:
    parts = [domain, _enc(ws), b"\0"]
    for s in scope:
        parts += [_enc(s), b"\0"]
    parts += [_enc(str(seq)), b"\0", _enc(prev), b"\0", body]
    return b"".join(parts)


def _seal(rk, kid, domain, ws, scope, seq, prev, body) -> bytes:
    if (
        not isinstance(body, bytes)
        or len(body) <= 2
        or body[:1] != b"{"
        or body[-1:] != b"}"
        or b"\n" in body
    ):
        raise SealError("bad body")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise SealError("bad seq")
    if not re.fullmatch(r"[0-9a-f]{8}", kid or "") or not re.fullmatch(r"[A-Za-z0-9_-]{43}", prev or ""):
        raise SealError("bad link")
    m = _mac(rk, _line_msg(domain, ws, scope, seq, prev, body))
    return (
        body[:-1] + b',"auth":{"k":"' + _enc(kid) + b'","p":"' + _enc(prev) + b'","m":"' + _enc(m) + b'"}}\n'
    )


def seal(rk: bytes, kid: str, ws: str, run: str, seq: int, prev: str, body: bytes) -> bytes:
    """One run line: `body` (the compact JSON the writer built, no `auth` key) plus the fixed-length auth
    suffix and a newline. `prev` is the MAC of the previous line (`genesis` for seq 1)."""
    return _seal(rk, kid, _D_LINE, ws, (run,), seq, prev, body)


def job_seal(rk: bytes, kid: str, ws: str, run: str, job: str, seq: int, prev: str, body: bytes) -> bytes:
    """One job-stream line (same shape, own domain, scope run + job)."""
    return _seal(rk, kid, _D_JOB, ws, (run, job), seq, prev, body)


def split(line: bytes):
    """(body, kid, prev, mac) of a sealed line (newline optional), or None when it has no auth suffix.
    The body is the exact bytes orch wrote: cutting the fixed suffix and appending `}` gives them back, no
    re-serialisation."""
    if line.endswith(b"\n"):
        line = line[:-1]
    if len(line) <= SUFFIX_LEN:
        return None
    m = _SUFFIX.search(line, len(line) - SUFFIX_LEN)
    if m is None or m.start() != len(line) - SUFFIX_LEN:
        return None
    return line[: m.start()] + b"}", m.group(1).decode(), m.group(2).decode(), m.group(3).decode()


# ------------------------------ verify


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key")
        out[k] = v
    return out


def _parse(body: bytes):
    try:
        obj = json.loads(body.decode("utf-8"), object_pairs_hook=_no_dupes)
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


@dataclass
class Verified:
    events: list = field(default_factory=list)  # parsed bodies (dicts, no auth), file order
    last_seq: int = 0
    last_mac: str | None = None
    changed: int = (
        0  # lines that are not genuine, in place (planted, edited, replayed, reordered, no auth, old key)
    )
    removed: int = 0  # genuine lines that are gone (middle deleted, tail truncated)
    reason: str | None = None  # content | removed | unverified | old_key | None


@dataclass
class State:
    """The walk of `verify_run` so far (what a per-process cache keeps for a verified prefix)."""

    out: Verified = field(default_factory=Verified)
    n_bad: int = 0
    n_noauth: int = 0
    pending: int = 0  # lines of a foreign key id before the first verified line: old segment or planted?
    gaps: list = field(default_factory=list)  # [lo, hi] seq ranges skipped by a resync

    def copy(self) -> "State":
        o = self.out
        return State(
            Verified(list(o.events), o.last_seq, o.last_mac, o.changed, o.removed, o.reason),
            self.n_bad,
            self.n_noauth,
            self.pending,
            list(self.gaps),
        )


def _origin(job, run, ws, rk):
    if job is not None:
        return _D_JOB, (run, job), job_genesis(rk, ws, run, job)
    return _D_LINE, (run,), genesis(rk, ws, run)


def scan(
    state: State, raw: bytes, run: str, ws: str, rk: bytes, kid: str, *, job: str | None = None
) -> State:
    """Walk `raw` (whole lines) on from `state` (mutated and returned)."""
    domain, scope, start = _origin(job, run, ws, rk)
    out = state.out
    for line in raw.split(b"\n"):
        if not line:
            continue
        parts = split(line)
        if parts is None:
            state.n_noauth += 1
            continue
        body, k, prev, mac = parts
        if not hmac.compare_digest(k.encode(), kid.encode()):
            # another key id: the old segment of a rotation (it comes first) or a planted line. Held until
            # the first line of the current key is known (finish): the rotation shape decides.
            if out.last_seq:
                state.n_bad += 1
            else:
                state.pending += 1
            continue
        obj = _parse(body)
        seq = obj.get("seq") if obj is not None else None
        if (
            obj is None
            or "auth" in obj
            or obj.get("run") != run
            or (job is not None and obj.get("job") != job)
            or not isinstance(seq, int)
            or isinstance(seq, bool)
            or seq < 1
        ):
            state.n_bad += 1
            continue
        want = _mac(rk, _line_msg(domain, ws, scope, seq, prev, body))
        if not hmac.compare_digest(want.encode(), mac.encode()):
            state.n_bad += 1
            continue
        # a genuine line (only the key makes one); now the chain
        if seq <= out.last_seq:
            # a replayed or duplicated line, an older copy, or a line that was moved behind its successor
            state.n_bad += 1
            if _unskip(state.gaps, seq):
                out.removed -= 1  # it was counted as removed when its successor resynced: it only moved
            continue
        if seq == out.last_seq + 1:
            if not hmac.compare_digest(prev.encode(), (out.last_mac or start).encode()):
                state.n_bad += 1  # right place, wrong link: spliced from another copy of this run
                continue
        else:
            gap = seq - out.last_seq - 1
            if gap:
                out.removed += gap
                state.gaps.append((out.last_seq + 1, out.last_seq + gap))
        out.events.append(obj)
        out.last_seq, out.last_mac = seq, mac
    return state


def finish(state: State, kid: str, head: dict | None = None) -> Verified:
    """The result for the walk so far (does not change `state`, so a cache can go on from it)."""
    s = state.copy()
    out = s.out
    n_bad, n_oldkey = s.n_bad, 0
    if s.pending:
        # the genuine rotation shape: the first verified line of the current key starts at seq 1 (its `p` is the
        # genesis then), or nothing of the current key exists and no head of it says there were lines. Anything
        # else (a gap, a missing chain) means the foreign lines are planted, not history.
        has_head = bool(head and head.get("kid") == kid and type(head.get("seq")) is int and head["seq"] >= 1)
        if out.events:
            rotation = out.events[0]["seq"] == 1
        else:
            rotation = not has_head
        if rotation:
            n_oldkey = s.pending
        else:
            n_bad += s.pending
    if head and head.get("kid") == kid and type(head.get("seq")) is int:
        out.removed += max(0, head["seq"] - out.last_seq)
    out.changed = n_bad + s.n_noauth + n_oldkey
    out.reason = _reason(out, n_bad, s.n_noauth, n_oldkey)
    return out


def verify_run(
    raw: bytes, run: str, ws: str, rk: bytes, kid: str, head: dict | None = None, *, job: str | None = None
) -> Verified:
    """Decide which lines of a run file (or, with `job`, of a job stream) count. `head` is the guarded home's
    {kid, seq, mac} for the file, already checked by the caller (None = no head). Verified lines are never
    moved, rewritten or dropped; every other line is `changed`. See activity.md for the table of cases."""
    return finish(scan(State(), raw, run, ws, rk, kid, job=job), kid, head)


def _unskip(gaps: list, seq: int) -> bool:
    for n, (lo, hi) in enumerate(gaps):
        if lo <= seq <= hi:
            gaps[n : n + 1] = [r for r in ((lo, seq - 1), (seq + 1, hi)) if r[0] <= r[1]]
            return True
    return False


def _reason(v: Verified, n_bad: int, n_noauth: int, n_oldkey: int) -> str | None:
    if v.changed:
        if n_bad or (n_noauth and v.events):
            return "content"  # lines are shown, so the plain "changed outside orch" marker
        return "unverified" if n_noauth else "old_key"
    return "removed" if v.removed else None


# ------------------------------ legacy runs (made before the MAC)


def legacy_split(raw: bytes, head_exists: bool) -> tuple[str, bytes, int]:
    """(mode, raw to verify, unchecked prefix lines). A run file with no sealed line and no chain head is a
    legacy run (made before orch sealed lines): mode "legacy", every line unchecked, nothing to verify. Any
    other file is "sealed": its unsigned lines that all come before the first sealed line are a legacy
    prefix (counted as unchecked, not verified); every later unsigned line stays in the raw to verify, so it
    is `changed`. A run that has a head or a sealed line never goes back to "legacy": stripping `auth` is a
    downgrade that does not work."""
    lines = [x for x in raw.split(b"\n") if x]
    first = next((n for n, x in enumerate(lines) if split(x) is not None), None)
    if first is None:
        if head_exists:
            return "sealed", raw, 0
        return "legacy", b"", len(lines)
    if first == 0:
        return "sealed", raw, 0
    cut, seen = 0, 0
    while seen < first:  # the byte offset of the first sealed line
        end = raw.find(b"\n", cut)
        end = len(raw) if end < 0 else end
        seen += end > cut
        cut = end + 1
    return "sealed", raw[cut:], first


# ------------------------------ spool, head, detail


def spool_mac(rk: bytes, ws: str, run: str, name: str, entry: dict) -> str:
    """`sm` of a pending/<run>/<name> entry: over {event, payload, default_id} (the file name is bound)."""
    msg = _D_SPOOL + _enc(ws) + b"\0" + _enc(run) + b"\0" + _enc(name) + b"\0" + canon_strict(entry)
    return _mac(rk, msg)


def spool_ok(rk: bytes, ws: str, run: str, name: str, entry: dict, sm) -> bool:
    if (
        not isinstance(sm, str)
        or not isinstance(entry, dict)
        or set(entry) - {"event", "payload", "default_id"}
    ):
        return False  # the MACed shape is exactly {event, payload, default_id}; sm itself is never inside
    try:
        return hmac.compare_digest(spool_mac(rk, ws, run, name, entry).encode(), sm.encode())
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False


def drain_ok(rk: bytes, ws: str, run: str, name: str, entry: dict, sm, drained, floor: str) -> bool:
    """True iff a spool entry may be drained: its `sm` fits, its name was not drained before and is not older
    than the head's `drained_floor` (a replayed genuine entry). Names are `<020d time_ns>_<32 hex>.json`."""
    if not isinstance(name, str) or not re.fullmatch(r"\d{20}_[0-9a-f]{32}\.json", name):
        return False
    if name in drained or name[:20] < floor:
        return False
    return spool_ok(rk, ws, run, name, entry, sm)


def head_mac(rk: bytes, ws: str, head: dict) -> str:
    """`hm` of a chain head: over the head without its own `hm`."""
    body = {k: v for k, v in head.items() if k != "hm"}
    return _mac(rk, _D_HEAD + _enc(ws) + b"\0" + canon_strict(body))


def head_ok(rk: bytes, ws: str, head) -> bool:
    if not isinstance(head, dict) or not isinstance(head.get("hm"), str):
        return False
    try:
        return hmac.compare_digest(head_mac(rk, ws, head).encode(), head["hm"].encode())
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False


def detail_hash(data: bytes) -> str:
    """`detail_hash` of a line: 32 hex = first 16 bytes of sha256 of the detail file's exact bytes."""
    return hashlib.sha256(data).hexdigest()[:32]
