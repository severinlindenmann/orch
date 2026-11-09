"""Pure three-way merge of orch tickets (git step 2, design D8). No git, no files, no clock: the caller passes
`now`. Two machines that merge the same three versions with the same `now` get byte-identical output, in either
argument order: merge_ticket(base, a, b, now) == merge_ticket(base, b, a, now).
Shared vectors: contracts/vectors/ticket-merge-v1.json.
"""

import json
import re
from copy import deepcopy

FINAL = ("done", "dropped")
LOSER_FIELDS = ("title", "note", "summary", "owner", "due", "key", "text")  # a replaced value goes to history
SYNC_BY = "agent:sync"
SESSION_CAP = 32
_MISSING = object()
_KEY_RE = re.compile(r"^([A-Z0-9]{2,4})-([1-9][0-9]{0,8})$")
_SPECIAL = {"id", "updated_at", "revision", "status", "checklist", "questions", "refs",
            "history", "sessions", "ext"}
_ANSWER = ("answer", "answered_by", "via")
MAX_DEPTH = 32
MAX_ITEMS = {"history": 5000, "checklist": 500, "questions": 500, "refs": 500, "sessions": 200}
MAX_BYTES = 2_000_000
MAX_COUNTER = 999_000_000  # keys stay inside the schema pattern (9 digits)
_IDENT = {"checklist": lambda x: x["id"], "questions": lambda x: x["id"],
          "sessions": lambda s: _canon([s.get("agent"), s.get("host")])}


def _canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _cm(x):
    return "\0missing" if x is _MISSING else _canon(x)


def _short(x):
    """Only for the readable text of a history line; the full value is kept in the line's `lost` field."""
    s = str(x)
    return s if len(s) <= 200 else s[:200] + "..."


def _too_deep(x):
    """Iterative (no recursion): True when nesting is deeper than MAX_DEPTH."""
    stack = [(x, 1)]
    while stack:
        v, d = stack.pop()
        if isinstance(v, (dict, list)):
            if d > MAX_DEPTH:
                return True
            stack.extend((c, d + 1) for c in (v.values() if isinstance(v, dict) else v))
    return False


def _num(i):
    m = re.search(r"\d+$", i)
    return int(m.group()) if m else 0


class _Ctx:
    """One merge: which side is newer (symmetric: updated_at, then canonical json) and the history lines."""

    def __init__(self, a, b, now):
        self.now = now
        self.a_newer = (a.get("updated_at", ""), _canon(a)) >= (b.get("updated_at", ""), _canon(b))
        self.lines = {}  # (text, canonical lost) -> lost: the full replaced value, so nothing is ever cut
        self.old_keys = set()

    def say(self, text, lost=_MISSING):
        self.lines[("sync: " + text, "" if lost is _MISSING else _canon(lost))] = lost


def _three(ctx, base, a, b, field=None, label=""):
    """Scalar rule: changed on one side -> it; both to the same value -> it; both differ -> the newer side."""
    if _cm(a) == _cm(b):
        return a
    if _cm(a) == _cm(base):
        return b
    if _cm(b) == _cm(base):
        return a
    win, lose = (a, b) if ctx.a_newer else (b, a)
    if field in LOSER_FIELDS and lose is not _MISSING:
        ctx.say(f'{label}{field} "{_short(lose)}" was replaced', {"field": label + field, "value": lose})
        if field == "key" and isinstance(lose, str) and _KEY_RE.match(lose):
            ctx.old_keys.add(lose)  # the loser's key must keep finding this ticket
    return win


def _obj(ctx, base, a, b, skip=(), top=False, label=""):
    """Per-key scalar merge of three dicts."""
    out = {}
    for k in sorted(set(a) | set(b) | set(base)):
        if k in skip:
            continue
        v = _three(ctx, base.get(k, _MISSING), a.get(k, _MISSING), b.get(k, _MISSING), k if top else None, label)
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
    out = _obj(ctx, x0, xa, xb, skip=("evidence",), top=True, label=f"{xa.get('id')} ")
    out["evidence"] = _evidence(x0.get("evidence", []), xa.get("evidence", []), xb.get("evidence", []))
    if out.get("done") and not out["evidence"]:
        out["done"] = False  # schema: done needs evidence
    return out


def _question(ctx, x0, xa, xb):
    out = _obj(ctx, x0, xa, xb, skip=_ANSWER, top=True, label=f"{xa.get('id')} ")
    ga, gb, g0 = ({k: x.get(k) for k in _ANSWER} for x in (xa, xb, x0))
    if ga["answer"] is not None and gb["answer"] is not None and ga != gb:
        if ga == g0:
            pick = gb
        elif gb == g0:
            pick = ga
        else:
            pick, lose = (ga, gb) if ctx.a_newer else (gb, ga)
            ctx.say(f'another answer "{_short(lose["answer"])}" by {lose["answered_by"]} was replaced',
                    {"field": f"{xa.get('id')} answer", "value": lose})
    elif ga["answer"] is None and gb["answer"] is None:
        pick = ga if ctx.a_newer else gb  # symmetric even when only answered_by/via differ
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
    out["id"] = a["id"]

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

    if ctx.old_keys:
        ext = out.setdefault("ext", {})
        sync = ext["sync"] if isinstance(ext.get("sync"), dict) else ext.setdefault("sync", {})
        sync["old_keys"] = sorted(set(old_keys_of(out)) | ctx.old_keys)
    hist = {}
    for h in base.get("history", []) + a.get("history", []) + b.get("history", []):
        hist[_canon([h.get("at"), h.get("by"), h.get("text"), h.get("via"), h.get("lost")])] = h
    old = {(h.get("text"), _canon(h["lost"]) if "lost" in h else "") for h in hist.values()
           if h.get("by") == SYNC_BY}  # the same line is never added twice
    for text, lost_key in sorted(set(ctx.lines) - old):
        line = {"at": now, "by": SYNC_BY, "text": text}
        if ctx.lines[(text, lost_key)] is not _MISSING:
            line["lost"] = ctx.lines[(text, lost_key)]
        hist[_canon([now, SYNC_BY, text, None, line.get("lost")])] = line
    out["history"] = sorted(hist.values(), key=lambda h: (h.get("at", ""), _canon(h)))

    out["revision"] = max(a.get("revision", 0), b.get("revision", 0)) + 1
    out["updated_at"] = max(a.get("updated_at", ""), b.get("updated_at", ""), base.get("updated_at", ""))
    return out


def _valid(base, a, b):
    """Shape and size checks before any recursion or copy. False = cannot merge."""
    if not all(isinstance(t, dict) for t in (base, a, b)) or a.get("id") != b.get("id"):
        return False
    if base and base.get("id") != a.get("id"):
        return False
    if not isinstance(a.get("id"), str):
        return False
    for t in (base, a, b):
        if _too_deep(t):
            return False
        for f, cap in MAX_ITEMS.items():
            lst = t.get(f, [])
            if not isinstance(lst, list) or len(lst) > cap or not all(isinstance(i, dict) for i in lst):
                return False
        if len(_canon(t)) > MAX_BYTES:
            return False
        if not all(isinstance(x.get("id"), str) for f in ("checklist", "questions") for x in t.get(f, [])):
            return False
        for f, ident in (("checklist", _IDENT["checklist"]), ("questions", _IDENT["questions"]),
                         ("refs", _ref_id), ("sessions", _IDENT["sessions"])):
            ids = [ident(x) for x in t.get(f, [])]
            if len(ids) != len(set(ids)):
                return False  # a duplicate id would silently drop an item
    return True


def merge_ticket(base, upstream, mine, now):
    """Merge ticket dicts (`base` None = both sides created the file). Returns the merged dict, or None when the
    inputs cannot be merged (not objects, different ids, too deep or too big, duplicate item ids, malformed
    lists): the caller pauses and keeps all three. Never raises. The inputs are not modified."""
    try:
        if not _valid({} if base is None else base, upstream, mine):
            return None
        return _merge({} if base is None else deepcopy(base), deepcopy(upstream), deepcopy(mine), now)
    except Exception:  # noqa: BLE001 - a crafted ticket must never crash the sync loop
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
    def clean(x):
        return x if isinstance(x, dict) and not _too_deep(x) else {}
    try:
        out = mx(mx(clean(base), clean(a)), clean(b))
        last = out.get("last", 0)
        out["last"] = min(max([last if isinstance(last, int) and not isinstance(last, bool) else 0]
                              + [_key_n(k) for k in keys]), MAX_COUNTER + 1)
        return out
    except Exception:  # noqa: BLE001 - e.g. unsortable keys: fall back to what the keys alone say
        return {"last": min(max([0] + [_key_n(k) for k in keys]), MAX_COUNTER + 1)}


def old_keys_of(ticket):
    ext = ticket.get("ext") if isinstance(ticket, dict) else None
    sync = ext.get("sync") if isinstance(ext, dict) else None
    keys = sync.get("old_keys") if isinstance(sync, dict) else None
    return [k for k in keys if isinstance(k, str) and _KEY_RE.match(k)] if isinstance(keys, list) else []


def renumber_key_clashes(tickets, counter, now, held=()):
    """Tickets (by id) where two different ids share a key. The ticket that already held the key here (`held` =
    ids known locally before the merge) keeps it, so a backdated created_at cannot take over an existing key;
    among equals the one created first (then the smaller id) keeps it. The others get the next numbers from the
    counter, and their old key stays in ext.sync.old_keys so it still resolves ("DM1-13 moved to DM1-15").
    Returns (changed tickets by id, new counter), or None when the input is malformed (bad key, ext or
    created_at type, counter too large): the caller pauses. Pure: the inputs are not modified."""
    try:
        if not isinstance(tickets, dict) or _too_deep(tickets) or _too_deep(counter):
            return None
        tickets = deepcopy(tickets)
        held = set(held)
        for i, t in tickets.items():
            if (not isinstance(t, dict) or t.get("id") != i or not isinstance(t.get("created_at", ""), str)
                    or not isinstance(t.get("ext", {}), dict) or not isinstance(t.get("history", []), list)
                    or (t.get("key") is not None and not (isinstance(t["key"], str) and _KEY_RE.match(t["key"])))
                    or not isinstance((t.get("ext", {}).get("sync", {})), dict)):
                return None
        counter = merge_counter(counter if isinstance(counter, dict) else {}, None, None,
                                [k for t in tickets.values() for k in [t.get("key"), *old_keys_of(t)]])
        by_key = {}
        for t in tickets.values():
            if t.get("key"):
                by_key.setdefault(t["key"], []).append(t)
        changed = {}
        for key in sorted(by_key):
            order = sorted(by_key[key], key=lambda t: (t["id"] not in held, t.get("created_at", ""), t["id"]))
            for t in order[1:]:
                counter["last"] += 1
                if counter["last"] > MAX_COUNTER:
                    return None
                new = f"{key.rsplit('-', 1)[0]}-{counter['last']}"
                sync = t.setdefault("ext", {}).setdefault("sync", {})
                sync["old_keys"] = sorted(set(old_keys_of(t)) | {key})
                t["key"] = new
                t.setdefault("history", []).append({"at": now, "by": SYNC_BY, "text":
                                                    f"sync: key changed from {key} to {new} (another ticket had it)"})
                t["revision"] = t.get("revision", 0) + 1 if isinstance(t.get("revision", 0), int) else 1
                changed[t["id"]] = t
        return changed, counter
    except Exception:  # noqa: BLE001
        return None
