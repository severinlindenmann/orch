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
    return {
        "keys": {k: _h(v) for k, v in state.items() if k != "tickets" and k not in VOLATILE},
        "tickets": per,
        "lens": lens,
        "order": _h(list(per)),
    }


def delta(base: dict, cur: dict, state: dict, have: str) -> dict:
    """What the page holding `base` needs to get `state` (fingerprint `cur`)."""
    out: dict = {"delta": True, "base": have}
    out["set"] = {
        k: v
        for k, v in state.items()
        if k != "tickets" and (k in VOLATILE or base["keys"].get(k) != cur["keys"].get(k))
    }
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
        out["order"] = list(cur["tickets"])
    return out


def base_rev(have: str) -> str:
    """The stored revision a served one came from: `_served` may add `-u...` (update note) or `-l...` (start line)."""
    return have.split("-", 1)[0]
