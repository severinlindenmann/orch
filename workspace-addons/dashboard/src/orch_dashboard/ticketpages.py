"""GET /api/tickets: one page of tickets, filtered and searched here, not in the browser (ORCH-523).

With 10,000 tickets the page cannot hold every ticket: /api/state carries the open and recently finished ones
(ORCH-522) and this answer brings the rest a page at a time (the Done group on scroll, a search over every ticket).

Rows are read from the ticket files and kept in memory per file (size and change time): a request after a change
reads only the files that changed. A row is slim: the history is cut to its last lines and long texts are cut; the
full ticket comes with the ticket page. The search reads the full texts it keeps here."""

import json
import os
import re
import threading
import time
from pathlib import Path

PAGE = 50
MAX_PAGE = 200
HISTORY_KEEP = 5
TEXT_CAP = 400
REFRESH_AGE = 2.0  # a listing at most this old is used again without looking at the files
STATUSES = ("open", "ready", "active", "waiting", "blocked", "review", "done", "dropped")
_ID = re.compile(r"t_[a-z0-9]{6,16}")


def _shown(root: Path, t: dict) -> dict:
    """The ticket as the CLI lists it: person fields this machine can prove, add-on keys that are on."""
    from .data import shown

    try:
        from orch.cli import visible

        t = visible(root, t)
    except ImportError:
        pass
    return shown(root, t)


def _hidden(t: dict) -> bool:
    try:
        from orch import tickets as core

        return core.is_hidden(t) or bool(core._newer_format(t))
    except ImportError:
        return t.get("general") is True or t.get("manager") is True


def _cut(text, n=TEXT_CAP) -> str:
    text = text if isinstance(text, str) else ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _search_text(t: dict) -> str:
    """Every word a search looks in: title, owner, note, description and the task texts (lower case)."""
    parts = [t.get("title"), t.get("owner"), t.get("note"), t.get("description")]
    parts += [c.get("text") for c in t.get("checklist") or [] if isinstance(c, dict)]
    return "\n".join(str(p) for p in parts if isinstance(p, str)).lower()


_DONE_TEXT = re.compile(r"(?:->|to) done\b|^Done\b", re.IGNORECASE)


def _done_line(h: dict) -> bool:
    return h.get("kind") == "done" or bool(_DONE_TEXT.search(str(h.get("text") or "")))


def slim(t: dict) -> dict:
    """The row the list and the board draw: the ticket without its long parts."""
    out = dict(t)
    hist = t.get("history") if isinstance(t.get("history"), list) else []
    if t.get("status") == "done" and not t.get("done_at"):  # the page's doneAt reads the history it cuts here
        done = next((h for h in reversed(hist) if isinstance(h, dict) and _done_line(h)), None)
        if done and isinstance(done.get("at"), str):
            out["done_at"] = done["at"]
    if len(hist) > HISTORY_KEEP:
        out["history"] = hist[-HISTORY_KEEP:]
        out["history_more"] = len(hist) - HISTORY_KEEP
    for k in ("note", "description"):
        if isinstance(t.get(k), str) and len(t[k]) > TEXT_CAP:
            out[k] = _cut(t[k])
    for k in ("checklist", "refs", "questions"):
        if not isinstance(out.get(k), list):
            out[k] = []
    out["slim"] = True
    return out


class TicketRows:
    """Every ticket as a slim row, kept per file; `rows()` reads only the files that changed since the last call."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.files: dict[str, tuple[tuple, dict | None, str]] = {}  # stem -> (stat key, row, search text)
        self.listing: list[tuple[dict, str]] = []
        self.at = 0.0

    def _read(self, path: Path, stem: str):
        try:
            t = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, ""
        from .data import _valid_ticket

        if not _valid_ticket(t, stem) or _hidden(t):
            return None, ""
        t = _shown(self.root, t)
        return slim(t), _search_text(t)

    def rows(self) -> list[tuple[dict, str]]:
        with self.lock:
            if self.listing and time.monotonic() - self.at < REFRESH_AGE:
                return self.listing
            folder = self.root / ".orch" / "tickets"
            seen: dict[str, tuple[tuple, dict | None, str]] = {}
            try:
                entries = list(os.scandir(folder))
            except OSError:
                entries = []
            for e in entries:
                name = e.name
                if not (name.startswith("t_") and name.endswith(".json")):
                    continue
                stem = name[:-5]
                try:
                    if not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                key = (st.st_mtime_ns, st.st_size)
                old = self.files.get(stem)
                if old and old[0] == key:
                    seen[stem] = old
                else:
                    row, text = self._read(Path(e.path), stem)
                    seen[stem] = (key, row, text)
            self.files = seen
            listing = [(row, text) for _k, row, text in seen.values() if row is not None]
            _add_children(listing)
            listing.sort(key=lambda x: str(x[0].get("updated_at", "")), reverse=True)
            self.listing, self.at = listing, time.monotonic()
            return listing


def _add_children(listing: list[tuple[dict, str]]) -> None:
    """Parts done and total on a parent, and the children ids (the list's tree), as the state carries them."""
    by_id = {r["id"]: r for r, _ in listing}
    by_key = {str(r.get("key")).lower(): r for r, _ in listing if r.get("key")}
    for r, _ in listing:
        r["children"], r["parts_done"], r["parts_total"] = [], 0, 0
    for r, _ in listing:
        p = r.get("parent")
        if not isinstance(p, str):
            continue
        parent = by_id.get(p) or by_key.get(p.lower())
        if parent is not None and parent is not r:
            parent["children"].append(r["id"])
            parent["parts_total"] += 1
            parent["parts_done"] += int(r.get("status") == "done")


def _key_match(t: dict, needle: str) -> bool:
    """'58', '#58' or 'ORCH-58' finds that ticket by its number (exact); 'orch58' and 'orch 58' too (the page's rule)."""
    key = str(t.get("key") or "").lower()
    if not key:
        return False
    digits = needle.lstrip("#")
    if digits.isdigit():
        return key.split("-")[-1] == str(int(digits))
    flat = lambda v: re.sub(r"[\s-]+", "", v)
    return key == needle or flat(key) == flat(needle)


def matches(row: dict, text: str, needle: str) -> bool:
    if not needle:
        return True
    if _key_match(row, needle) or row.get("id") == needle:
        return True
    if not re.fullmatch(r"#?\d+", needle) and needle in str(row.get("key") or "").lower():
        return True
    return needle in text


def _done_at(row: dict) -> str:
    return str(row.get("done_at") or row.get("closed_at") or row.get("updated_at") or "")


def _int(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def owner_key(owner: object, me: str = "", login: str = "") -> str:
    """One key per person (ORCH-1716): case does not count, and the computer's login and the placeholder "owner" are
    the person using the dashboard (me). The same rule as ownerKey in web/pages/tickets.js."""

    def low(v: object) -> str:
        return re.sub(r"^(?:human|agent):", "", str(v or "")).strip().lower()

    o, m, lg = low(owner), low(me), low(login)
    return m if m and (o == m or o == "owner" or (lg and o == lg)) else o


def page(rows: list[tuple[dict, str]], query: dict, me: str = "", login: str = "") -> dict:
    """One page of rows for the query (each value the first one given):
    q       search words: a ticket number or words in the title, owner, note, description and tasks
    status  comma list of statuses (default: every status but dropped)
    who     the owner, one person however it is spelled (owner_key); mine=1: the person's own (or every non-helper ticket when nobody is known)
    group   a ticket id: that ticket and its parts
    since   ISO time: finished (or changed) at or after it
    offset, limit (50, at most 200)
    The answer: {items, total, offset, next (null at the end), counts {status: n}} (counts before `status`)."""

    def one(name: str) -> str:
        v = query.get(name)
        return str(v[0] if isinstance(v, list) and v else v or "").strip()

    needle = one("q").lower()[:200]
    wanted = {s for s in one("status").split(",") if s in STATUSES} or set(STATUSES) - {"dropped"}
    who, mine, group, since = one("who"), one("mine") == "1", one("group"), one("since")
    offset = _int(one("offset") or 0, 0, 10**7, 0)
    limit = _int(one("limit") or PAGE, 1, MAX_PAGE, PAGE)
    hits, counts = [], {}
    who_key = owner_key(who, me, login) if who else ""
    for row, text in rows:
        owner = str(row.get("owner") or "")
        if who and owner_key(owner, me, login) != who_key:
            continue
        if mine and not (owner == me if me else not owner.startswith("agent:")):
            continue
        if group and row.get("id") != group and row.get("parent") != group:
            continue
        if (
            since
            and (_done_at(row) if row.get("status") == "done" else str(row.get("updated_at") or "")) < since
        ):
            continue
        if not matches(row, text, needle):
            continue
        status = row.get("status")
        counts[status] = counts.get(status, 0) + 1
        if status in wanted:
            hits.append(row)
    if wanted == {"done"}:
        hits.sort(key=_done_at, reverse=True)
    end = offset + limit
    return {
        "items": hits[offset:end],
        "total": len(hits),
        "offset": offset,
        "next": end if end < len(hits) else None,
        "counts": counts,
    }


_POOL: dict[str, TicketRows] = {}
_POOL_LOCK = threading.Lock()


def rows_for(root: Path) -> TicketRows:
    with _POOL_LOCK:
        key = str(root)
        if key not in _POOL:
            _POOL[key] = TicketRows(root)
        return _POOL[key]


def warm(root: Path) -> None:
    """Read every ticket once in the background (a few seconds at 10,000), so the first page waits on nothing."""
    threading.Thread(target=lambda: rows_for(root).rows(), name="ticket-rows", daemon=True).start()


def answer(root: Path, query: dict, me: str = "", login: str = "") -> bytes:
    return json.dumps(page(rows_for(root).rows(), query, me, login)).encode()
