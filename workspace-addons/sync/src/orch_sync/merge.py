"""Pure three-way merge of orch tickets (git step 2, design D8). No git, no files, no clock: the caller passes
`now`. Two machines that merge the same three versions with the same `now` get byte-identical output, in either
argument order: merge_ticket(base, a, b, now) == merge_ticket(base, b, a, now).
Shared vectors: contracts/vectors/ticket-merge-v1.json.
"""

import json
import re
from copy import deepcopy

FINAL = ("done", "dropped")
LOSER_FIELDS = ("title", "note", "summary", "owner", "due")  # a replaced value of these goes to history
SYNC_BY = "agent:sync"
SESSION_CAP = 32
_MISSING = object()
_KEY_RE = re.compile(r"^([A-Z0-9]{2,4})-([1-9][0-9]{0,8})$")
_SPECIAL = {"id", "schema", "created_at", "updated_at", "revision", "status", "checklist", "questions", "refs",
            "history", "sessions", "ext"}
_ANSWER = ("answer", "answered_by", "via")


def _canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _cm(x):
    return "\0missing" if x is _MISSING else _canon(x)


def _short(x):
    return str(x)[:200]


def _num(i):
    m = re.search(r"\d+$", i)
    return int(m.group()) if m else 0


class _Ctx:
    """One merge: which side is newer (symmetric: updated_at, then canonical json) and the history lines."""

    def __init__(self, a, b, now):
        self.now = now
        self.a_newer = (a.get("updated_at", ""), _canon(a)) >= (b.get("updated_at", ""), _canon(b))
        self.lines = set()

    def say(self, text):
        self.lines.add("sync: " + text)


def _three(ctx, base, a, b, field=None):
    """Scalar rule: changed on one side -> it; both to the same value -> it; both differ -> the newer side."""
    if _cm(a) == _cm(b):
        return a
    if _cm(a) == _cm(base):
        return b
    if _cm(b) == _cm(base):
        return a
    win, lose = (a, b) if ctx.a_newer else (b, a)
    if field in LOSER_FIELDS and lose is not _MISSING:
        ctx.say(f'{field} "{_short(lose)}" was replaced')
    return win


def _obj(ctx, base, a, b, skip=(), top=False):
    """Per-key scalar merge of three dicts."""
    out = {}
    for k in sorted(set(a) | set(b) | set(base)):
        if k in skip:
            continue
        v = _three(ctx, base.get(k, _MISSING), a.get(k, _MISSING), b.get(k, _MISSING), k if top else None)
        if v is not _MISSING:
            out[k] = v
    return out


def _deep(ctx, base, a, b, path=()):
    """ext: dicts merge per key, everything else is a leaf (a list as a whole)."""
    if path == ("sync", "old_keys"):
        vals = [x for x in (a, b, base) if isinstance(x, list)]
        return sorted({k for v in vals for k in v}) if vals else _MISSING
    isd = lambda x: isinstance(x, dict) or x is _MISSING
    if isd(a) and isd(b) and not (a is _MISSING and b is _MISSING):
        a, b = ({} if x is _MISSING else x for x in (a, b))
        bs = base if isinstance(base, dict) else {}
        out = {}
        for k in sorted(set(a) | set(b) | set(bs)):
            v = _deep(ctx, bs.get(k, _MISSING), a.get(k, _MISSING), b.get(k, _MISSING), path + (k,))
            if v is not _MISSING:
                out[k] = v
        return out
    return _three(ctx, base, a, b)


def _renumber_clashes(ctx, base, a, b, same, prefix):
    """Both sides added an item with the same id but different content: the older side keeps the id, the newer
    side's item gets the next free one. Returns the renames per side."""
    bids = {x["id"] for x in base}
    clash = [x["id"] for x in a if x["id"] not in bids and any(y["id"] == x["id"] and not same(x, y) for y in b)]
    used = {x["id"] for x in base + a + b}
    ren = {"a": {}, "b": {}}
    newer = "a" if ctx.a_newer else "b"
    for i in sorted(clash, key=lambda s: (_num(s), s)):
        new = f"{prefix}{max(_num(u) for u in used) + 1}"
        used.add(new)
        ren[newer][i] = new
        ctx.say(f"{i} renumbered to {new} (both sides added one)")
    for side, lst in (("a", a), ("b", b)):
        for x in lst:
            x["id"] = ren[side].get(x["id"], x["id"])
    return ren


def _keyed(base, a, b, ident, merge_item):
    """Union of items by identity. In base and gone on one side: gone, unless the other side edited it (edit beats delete)."""
    mb, ma, mc = ({ident(x): x for x in lst} for lst in (base, a, b))
    out = {}
    for i in list(mb) + [i for i in ma if i not in mb] + [i for i in mc if i not in mb and i not in ma]:
        x0, xa, xb = mb.get(i), ma.get(i), mc.get(i)
        if xa is not None and xb is not None:
            out[i] = merge_item(x0 or {}, xa, xb)
        elif x0 is not None:
            kept = xa if xa is not None else xb
            if kept is not None and _canon(kept) != _canon(x0):
                out[i] = kept
        else:
            out[i] = xa if xa is not None else xb
    return out


def _order(items, base_ids, key=None):
    """Base order first, additions after in a fixed order."""
    first = [i for i in base_ids if i in items]
    rest = sorted((i for i in items if i not in first), key=key or (lambda i: (_num(i), i)))
    return [items[i] for i in first + rest]


def _evidence(*lists):
    seen = {}
    for e in (e for lst in lists for e in lst):
        k = (e.get("type"), e.get("ref"))
        if k not in seen or _canon(e) > _canon(seen[k]):
            seen[k] = e
    return sorted(seen.values(), key=lambda e: (e.get("at", ""), _canon(e)))


def _check_item(ctx, x0, xa, xb):
    out = _obj(ctx, x0, xa, xb, skip=("evidence",))
    out["evidence"] = _evidence(x0.get("evidence", []), xa.get("evidence", []), xb.get("evidence", []))
    if out.get("done") and not out["evidence"]:
        out["done"] = False  # schema: done needs evidence
    return out


def _question(ctx, x0, xa, xb):
    out = _obj(ctx, x0, xa, xb, skip=_ANSWER)
    ga, gb, g0 = ({k: x.get(k) for k in _ANSWER} for x in (xa, xb, x0))
    if ga["answer"] is not None and gb["answer"] is not None and ga != gb:
        if ga == g0:
            pick = gb
        elif gb == g0:
            pick = ga
        else:
            pick, lose = (ga, gb) if ctx.a_newer else (gb, ga)
            ctx.say(f'another answer "{_short(lose["answer"])}" by {lose["answered_by"]} was replaced')
    else:  # an answered question beats an unanswered one
        pick = gb if ga["answer"] is None else ga
    out.update(pick)
    return out


def _ref_id(r):
    return _canon([r.get(k) for k in ("kind", "url", "ticket", "name", "path")])


def _merge(base, a, b, now):
    ctx = _Ctx(a, b, now)
    # the same id added on both sides with different content: the newer side's item is renumbered
    ren = _renumber_clashes(ctx, base.get("checklist", []), a.setdefault("checklist", []),
                            b.setdefault("checklist", []), lambda x, y: x.get("text") == y.get("text"), "c")
    for side, t in (("a", a), ("b", b)):
        for q in t.get("questions", []):
            if q.get("check") in ren[side]:
                q["check"] = ren[side][q["check"]]
    _renumber_clashes(ctx, base.get("questions", []), a.setdefault("questions", []),
                      b.setdefault("questions", []), lambda x, y: x.get("text") == y.get("text"), "q")

    out = _obj(ctx, base, a, b, skip=_SPECIAL, top=True)
    for f in ("id", "schema", "created_at"):
        v = a.get(f, b.get(f, base.get(f)))
        if v is not None:
            out[f] = v

    s0, sa, sb = base.get("status"), a.get("status"), b.get("status")
    if sa != sb and sa != s0 and sb != s0:  # both changed: a finished ticket is not silently reopened
        fa, fb = sa in FINAL, sb in FINAL
        win = sa if (fa and not fb) or (fa == fb and ctx.a_newer) else sb
        ctx.say(f"status {sb if win == sa else sa} was replaced by {win}")
        out["status"] = win
    else:
        out["status"] = _three(ctx, s0, sa, sb)

    def ids(lst):
        return [x["id"] for x in lst]

    cl = _keyed(base.get("checklist", []), a["checklist"], b["checklist"], lambda x: x["id"],
                lambda x0, xa, xb: _check_item(ctx, x0, xa, xb))
    out["checklist"] = _order(cl, ids(base.get("checklist", [])))
    if out["status"] == "done" and any(not c.get("done") for c in out["checklist"]):
        out["status"] = "active"
        ctx.say("reopened, a new checklist item came in")
    qs = _keyed(base.get("questions", []), a["questions"], b["questions"], lambda x: x["id"],
                lambda x0, xa, xb: _question(ctx, x0, xa, xb))
    out["questions"] = _order(qs, ids(base.get("questions", [])))
    refs = _keyed(base.get("refs", []), a.get("refs", []), b.get("refs", []), _ref_id,
                  lambda r0, ra, rb: _obj(ctx, r0, ra, rb))
    out["refs"] = _order(refs, [_ref_id(r) for r in base.get("refs", [])], key=lambda i: i)
    if any("sessions" in t for t in (base, a, b)):
        sess = _keyed(base.get("sessions", []), a.get("sessions", []), b.get("sessions", []),
                      lambda s: _canon([s.get("agent"), s.get("host")]),
                      lambda s0, sa, sb: max(sa, sb, key=lambda s: (s.get("last_used", ""), _canon(s))))
        out["sessions"] = sorted(sess.values(), key=lambda s: (s.get("last_used", ""), _canon(s)))[-SESSION_CAP:]
    if "ext" in a or "ext" in b:
        d = lambda t: t["ext"] if isinstance(t.get("ext"), dict) else {}
        out["ext"] = _deep(ctx, d(base), d(a), d(b))

    hist = {}
    for h in base.get("history", []) + a.get("history", []) + b.get("history", []):
        hist[_canon([h.get("at"), h.get("by"), h.get("text"), h.get("via")])] = h
    old = {h.get("text") for h in hist.values() if h.get("by") == SYNC_BY}  # the same line is never added twice
    for text in sorted(ctx.lines - old):
        hist[_canon([now, SYNC_BY, text, None])] = {"at": now, "by": SYNC_BY, "text": text}
    out["history"] = sorted(hist.values(), key=lambda h: (h.get("at", ""), _canon(h)))

    out["revision"] = max(a.get("revision", 0), b.get("revision", 0)) + 1
    out["updated_at"] = max(a.get("updated_at", ""), b.get("updated_at", ""), base.get("updated_at", ""))
    return out


def merge_ticket(base, upstream, mine, now):
    """Merge ticket dicts (`base` None = both sides created the file). Returns the merged dict, or None when the
    inputs cannot be merged (not objects, different ids, malformed lists): the caller pauses and keeps all three.
    The inputs are not modified."""
    base = {} if base is None else deepcopy(base)
    a, b = deepcopy(upstream), deepcopy(mine)
    try:
        if not all(isinstance(t, dict) for t in (base, a, b)) or a.get("id") != b.get("id"):
            return None
        if base and base.get("id") != a.get("id"):
            return None
        for t in (base, a, b):
            for f in ("checklist", "questions", "refs", "history", "sessions"):
                if not all(isinstance(i, dict) for i in t.get(f, [])):
                    return None
        return _merge(base, a, b, now)
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def _key_n(k):
    m = _KEY_RE.match(k) if isinstance(k, str) else None
    return int(m.group(2)) if m else 0


def merge_counter(base, a, b, keys=()):
    """ticket-counter.json: `last` = the highest of all sides and of every key number in `keys` (current and old
    keys). Other int entries: per-key max (recursively); anything else: the larger canonical json."""
    def mx(x, y):
        if isinstance(x, dict) and isinstance(y, dict):
            return {k: mx(x.get(k, _MISSING), y.get(k, _MISSING)) for k in sorted(set(x) | set(y))}
        if x is _MISSING:
            return y
        if y is _MISSING:
            return x
        if isinstance(x, int) and isinstance(y, int) and not isinstance(x, bool):
            return max(x, y)
        return max(x, y, key=_canon)
    out = mx(mx(base or {}, a or {}), b or {})
    last = out.get("last", 0)
    out["last"] = max([last if isinstance(last, int) else 0] + [_key_n(k) for k in keys])
    return out


def old_keys_of(ticket):
    sync = (ticket.get("ext") or {}).get("sync") or {}
    return list(sync.get("old_keys", []))


def renumber_key_clashes(tickets, counter, now):
    """Tickets (by id) where two different ids share a key: the one created later (then the larger id) gets the
    next number from the counter; its old key stays in ext.sync.old_keys so it still resolves ("DM1-13 moved to
    DM1-15"). Returns (changed tickets by id, new counter). Pure: the inputs are not modified."""
    tickets = {i: deepcopy(t) for i, t in tickets.items()}
    counter = merge_counter(counter, None, None, [k for t in tickets.values() for k in [t.get("key"), *old_keys_of(t)]])
    by_key = {}
    for t in tickets.values():
        if t.get("key"):
            by_key.setdefault(t["key"], []).append(t)
    changed = {}
    for key in sorted(by_key):
        for t in sorted(by_key[key], key=lambda t: (t.get("created_at", ""), t["id"]))[1:]:
            counter["last"] += 1
            new = f"{key.rsplit('-', 1)[0]}-{counter['last']}"
            sync = t.setdefault("ext", {}).setdefault("sync", {})
            sync["old_keys"] = sorted(set(sync.get("old_keys", [])) | {key})
            t["key"] = new
            t.setdefault("history", []).append(
                {"at": now, "by": SYNC_BY, "text": f"sync: key changed from {key} to {new} (another ticket had it)"})
            t["revision"] = t.get("revision", 0) + 1
            changed[t["id"]] = t
    return changed, counter
