"""A changed state as only what changed since the revision the page holds (ORCH-517).

ORCH-145 made an unchanged state cost a few bytes. On a busy workspace the state changes every few seconds (helpers
write their tickets), so every poll still sent the whole state: 500 tickets, 6 MB (1.2 MB gzipped), twelve times a
minute per open tab. Now the server keeps a small fingerprint (a short hash per top-level key and per ticket field)
of the last few revisions it served; a poll with `?have=<rev>` of one of them gets the keys and ticket fields that
differ, and the page applies them (helpers.js applyStateDelta). An unknown revision still gets the whole state.
"""

import hashlib
import json

# Always sent in a delta: small, and the served copy may change them without a new build (state_cache._served).
VOLATILE = ("now", "rev", "auto_update_note", "start_line")
KEEP = 8  # fingerprints of this many revisions: a page that missed a few polls still gets a delta


def _h(value) -> bytes:
    return hashlib.blake2b(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(), digest_size=8
    ).digest()


def fingerprint(state: dict) -> dict | None:
    """Hashes of every top-level key and of every field of every ticket. None when the tickets cannot be told
    apart by id (then only the whole state is sent)."""
    tickets = state.get("tickets")
    if not isinstance(tickets, list):
        return None
    per: dict[str, dict[str, bytes]] = {}
    lens: dict[
        str, dict[str, int]
    ] = {}  # list fields (history, checklist ...): a longer list may be sent as its new end
    for t in tickets:
        tid = t.get("id") if isinstance(t, dict) else None
        if not isinstance(tid, str) or tid in per:
            return None
        per[tid] = {k: _h(v) for k, v in t.items()}
        lens[tid] = {k: len(v) for k, v in t.items() if isinstance(v, list)}
    # a top-level object (runs, settings): a hash per entry and per field of an entry that is an object, so a
    # change sends only the entries and fields that changed (ORCH-524: a run's age ticks every poll)
    sub: dict[str, dict[str, bytes | dict[str, bytes]]] = {}
    for k, v in state.items():
        if k != "tickets" and k not in VOLATILE and isinstance(v, dict):
            sub[k] = {
                sk: {f: _h(x) for f, x in sv.items()} if isinstance(sv, dict) else _h(sv)
                for sk, sv in v.items()
            }
    return {
        "sub": sub,
        "keys": {k: _h(v) for k, v in state.items() if k != "tickets" and k not in VOLATILE},
        "tickets": per,
        "lens": lens,
        "order": _h(list(per)),
    }


def delta(base: dict, cur: dict, state: dict, have: str) -> dict:
    """What the page holding `base` needs to get `state` (fingerprint `cur`)."""
    out: dict = {"delta": True, "base": have}
    changed_keys = [
        k for k in state if k != "tickets" and (k in VOLATILE or base["keys"].get(k) != cur["keys"].get(k))
    ]
    out["set"], patch = {}, {}
    for k in changed_keys:
        old_sub, new_sub = base.get("sub", {}).get(k), cur["sub"].get(k)
        if old_sub is None or new_sub is None:
            out["set"][k] = state[k]
        else:
            patch[k] = _patch(old_sub, new_sub, state[k])
    if patch:
        out["patch"] = patch
    # every top-level key of the state: the page keeps only these (a click's answer may have added its own)
    out["keys"] = list(state)
    upsert = []
    for t in state["tickets"]:
        old, new = base["tickets"].get(t["id"]), cur["tickets"][t["id"]]
        if old is None:
            upsert.append(t)
            continue
        changed = {k: v for k, v in t.items() if old.get(k) != new[k]}
        gone = [k for k in old if k not in new]
        if changed or gone:
            row: dict = {"id": t["id"]}
            n_old = base["lens"].get(t["id"], {})
            for k, v in changed.items():
                n = n_old.get(k)
                if isinstance(v, list) and n is not None and 0 < n < len(v) and _h(v[:n]) == old[k]:
                    row.setdefault("~append", {})[k] = v[n:]  # a helper wrote a history line: only that line
                else:
                    row[k] = v
            if gone:
                row["~drop"] = gone
            upsert.append(row)
    if upsert:
        out["upsert"] = upsert
    removed = [tid for tid in base["tickets"] if tid not in cur["tickets"]]
    if removed:
        out["remove"] = removed
    if base["order"] != cur["order"]:
        out["order"] = order_parts(list(base["tickets"]), list(cur["tickets"]))
    return out


def _patch(old: dict, new: dict, value: dict) -> dict:
    """The entries of one top-level object that changed: `set` whole entries, `fields` only the changed fields of
    an entry that is an object on both sides, `drop` entries that are gone. A field that is gone sends the entry."""
    out: dict = {}
    for sk, h in new.items():
        was = old.get(sk)
        if was == h:
            continue
        if isinstance(h, dict) and isinstance(was, dict) and set(was) <= set(h):
            out.setdefault("fields", {})[sk] = {f: value[sk][f] for f, fh in h.items() if was.get(f) != fh}
        else:
            out.setdefault("set", {})[sk] = value[sk]
    gone = [sk for sk in old if sk not in new]
    if gone:
        out["drop"] = gone
    return out


def order_parts(held: list[str], ids: list[str]) -> list:
    """The new ticket order as pieces of the order the page holds (ORCH-524): `[start, count]` is that run of the
    held order, a string is one ticket id. A helper's change moves its ticket to the top, so 10,000 ids (about
    60 KB packed, on every poll) become a few pieces. The page builds the order back (helpers.js applyStateDelta);
    an older page sees a piece that is not an id and asks for the whole state."""
    at = {tid: i for i, tid in enumerate(held)}
    out: list = []
    run_start, run_len = -1, 0

    def close():
        if run_len == 1:
            out.append(held[run_start])
        elif run_len > 1:
            out.append([run_start, run_len])

    for tid in ids:
        i = at.get(tid)
        if i is not None and run_len and i == run_start + run_len:
            run_len += 1
            continue
        close()
        if i is None:
            out.append(tid)
            run_start, run_len = -1, 0
        else:
            run_start, run_len = i, 1
    close()
    return out


def base_rev(have: str) -> str:
    """The stored revision a served one came from: `_served` may add `-u...` (update note) or `-l...` (start line)."""
    return have.split("-", 1)[0]
