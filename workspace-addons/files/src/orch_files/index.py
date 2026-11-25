"""The one search index of a workspace: `.orch/cache/files/index.db` (SQLite, standard library).

Two parts: `files` (path, folder, name, kind, size, changed time, ticket, title, whether its text was read) and
`fts`, a full-text table with the trigram tokenizer, so any part of a word matches ("invo" finds Invoice-2026.pdf
and "...invoiced in March..."); accents are folded ("muller" finds Müller). A refresh walks the folder, reads only
files whose size or changed time differ, and forgets files that are gone. Names are written first, text after,
so search works while the text is still being read. The index can be deleted at any time: it builds itself again.
"""

from __future__ import annotations

import calendar
import contextlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import extract, walk
from .state import load as person_state

SCHEMA = 4
MAX_TEXT_READ = extract.TEXT_LIMIT
MAX_HITS = 200
TEXT_BATCH = 64
_LOCK = threading.Lock()  # one writer per process (the page's background pass and a request may overlap)


def cache_dir(root: Path) -> Path:
    return Path(root) / ".orch" / "cache" / "files"


def db_path(root: Path) -> Path:
    return cache_dir(root) / "index.db"


def fold(s: str) -> str:
    """Lower case without accents: Müller -> muller, Ærø -> ærø (only marks are dropped)."""
    n = unicodedata.normalize("NFKD", s)
    return "".join(c for c in n if not unicodedata.combining(c)).casefold()


def _trigram_options(con: sqlite3.Connection) -> str:
    """`trigram remove_diacritics 1` when this SQLite has it (3.45+); else plain trigram (text is folded here)."""
    try:
        con.execute("CREATE VIRTUAL TABLE temp.probe USING fts5(x, tokenize='trigram remove_diacritics 1')")
        con.execute("DROP TABLE temp.probe")
        return "trigram remove_diacritics 1"
    except sqlite3.OperationalError:
        return "trigram"


def has_fts5() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def connect(root: Path, write: bool = False) -> sqlite3.Connection:
    p = db_path(root)
    if write:
        p.parent.mkdir(parents=True, exist_ok=True)
    elif not p.exists():
        raise FileNotFoundError(p)
    con = sqlite3.connect(str(p), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    if write:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        _ensure(con)
    return con


def _ensure(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    if row and row[0] == str(SCHEMA):
        return
    for t in ("fts", "files", "tickets", "texts"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    tok = _trigram_options(con)
    con.executescript(
        """
        CREATE TABLE files(
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, folder TEXT NOT NULL, name TEXT NOT NULL,
            kind TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL, ticket TEXT, private INTEGER NOT NULL,
            title TEXT, text_state INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX files_folder ON files(folder);
        CREATE INDEX files_ticket ON files(ticket);
        CREATE INDEX files_mtime ON files(mtime);
        CREATE INDEX files_state ON files(text_state);
        CREATE TABLE tickets(id TEXT PRIMARY KEY, key TEXT, title TEXT, status TEXT, updated TEXT, sig TEXT);
        CREATE TABLE texts(id INTEGER PRIMARY KEY, z BLOB NOT NULL);
        """
    )
    # Contentless (SQLite 3.43+): the full-text table keeps only what it needs to find a file, not a second copy
    # of the text; the text for the found line is kept compressed in `texts`.
    try:
        con.execute(
            f"CREATE VIRTUAL TABLE fts USING fts5(name, body, tokenize='{tok}', content='', contentless_delete=1)"
        )
    except sqlite3.OperationalError:
        con.execute(f"CREATE VIRTUAL TABLE fts USING fts5(name, body, tokenize='{tok}')")
    con.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
    con.execute("INSERT OR REPLACE INTO meta VALUES('tokenizer', ?)", (tok,))
    con.commit()


def _folds(con: sqlite3.Connection) -> bool:
    """True when the text must be folded here (the SQLite of this computer cannot drop accents itself)."""
    row = con.execute("SELECT v FROM meta WHERE k='tokenizer'").fetchone()
    return not (row and "remove_diacritics" in row[0])


def _put(
    con: sqlite3.Connection, rowid: int, name: str, body: str | None, folds: bool, new: bool = False
) -> None:
    """Write one file's name and text to the full-text table (and its text, compressed, for the found line).
    body None keeps the text already there (only the name changes)."""
    if body is None:
        body = _body(con, rowid)
    else:
        if not new:
            con.execute("DELETE FROM texts WHERE id=?", (rowid,))
        if body:
            con.execute(
                "INSERT INTO texts(id, z) VALUES(?, ?)", (rowid, zlib.compress(body.encode("utf-8"), 6))
            )
    if not new:
        con.execute("DELETE FROM fts WHERE rowid=?", (rowid,))
    con.execute(
        "INSERT INTO fts(rowid, name, body) VALUES(?,?,?)",
        (rowid, fold(name) if folds else name, fold(body) if folds else body),
    )


def _body(con: sqlite3.Connection, rowid: int) -> str:
    row = con.execute("SELECT z FROM texts WHERE id=?", (rowid,)).fetchone()
    try:
        return zlib.decompress(row[0]).decode("utf-8") if row else ""
    except (zlib.error, UnicodeDecodeError):
        return ""


# ---- tickets: title, key, where it stands, and the titles helpers gave their files
VERSION = re.compile(r"^(?P<base>.+?)[-_ .]?v(?:ersion)?[-_ ]?(?P<n>\d{1,3})$", re.IGNORECASE)


def _tickets(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    base = Path(root) / ".orch" / "tickets"
    try:
        names = [n for n in os.listdir(base) if n.endswith(".json") and walk.TICKET_ID.fullmatch(n[:-5])]
    except OSError:
        return out
    for n in names:
        p = base / n
        try:
            st = p.stat()
            if st.st_size > 8 * 1024 * 1024:
                continue
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(t, dict):
            continue
        titles: dict[str, str] = {}
        for c in t.get("checklist") or []:
            for ev in (c or {}).get("evidence") or [] if isinstance(c, dict) else []:
                if isinstance(ev, dict) and ev.get("type") == "file" and ev.get("title") and ev.get("ref"):
                    titles.setdefault(str(ev["ref"]).rsplit("/", 1)[-1], str(ev["title"])[:160])
        out[n[:-5]] = {
            "key": str(t.get("key") or n[:-5])[:32],
            "title": " ".join(str(t.get("title") or "").split())[:200] or n[:-5],
            "status": str(t.get("status") or ""),
            "updated": str(t.get("updated_at") or t.get("created_at") or ""),
            "titles": titles,
        }
    return out


def nice_title(name: str) -> str:
    """A plain title from a file name: price-check_summary-v2.md -> Price check summary."""
    stem = name.rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem.lstrip(".") else stem
    m = VERSION.match(stem)
    if m:
        stem = m.group("base")
    words = re.sub(r"[-_]+", " ", stem).strip() or name
    return words[:1].upper() + words[1:]


def version_of(name: str) -> tuple[str, int] | None:
    stem = name.rsplit("/", 1)[-1]
    ext = stem.rsplit(".", 1)[-1] if "." in stem else ""
    stem = stem.rsplit(".", 1)[0] if ext else stem
    m = VERSION.match(stem)
    if not m:
        return None
    return m.group("base").lower() + "." + ext.lower(), int(m.group("n"))


def _name_text(path: str, title: str | None, ticket: dict | None) -> str:
    name = path.rsplit("/", 1)[-1]
    where = ticket["title"] + " " + ticket["key"] if ticket else path.rsplit("/", 1)[0] if "/" in path else ""
    return "  ".join(x for x in (title or "", name, where) if x)


# ---- refresh
@dataclass
class Progress:
    total: int = 0
    unread: int = 0
    changed: int = 0
    removed: int = 0
    read: int = 0
    seconds: float = 0.0
    building: bool = False

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def leave_out(root: Path) -> tuple[str, ...]:
    try:
        d = json.loads(
            (Path(root) / ".orch" / "addons" / "files" / "settings.json").read_text(encoding="utf-8")
        )
        v = d.get("leave_out") if isinstance(d, dict) else None
        return tuple(str(x) for x in v if isinstance(x, str)) if isinstance(v, list) else ()
    except (OSError, ValueError):
        return ()


def refresh(root: Path, text_seconds: float | None = None, on_progress=None) -> Progress:
    """Bring the index up to date. Names of every file first; then the text of files not read yet, newest first,
    for at most `text_seconds` (None: all of them). Returns what was done."""
    root = Path(root).resolve()
    t0 = time.monotonic()
    pr = Progress()
    with _LOCK:
        con = connect(root, write=True)
        try:
            folds = _folds(con)
            tickets = _tickets(root)
            changed_tickets = _store_tickets(con, tickets)
            known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, id, size, mtime FROM files")}
            seen: set[str] = set()
            cur = con.cursor()
            n = 0
            show = person_state(root)["show_ignored"]
            for e in walk.walk(str(root), leave_out(root), show_ignored=show):
                seen.add(e.path)
                k = known.get(e.path)
                if k and k[1] == e.size and k[2] == e.mtime:
                    continue
                kind = extract.kind_of(e.path)
                t = tickets.get(e.ticket) if e.ticket else None
                fname = e.path.rsplit("/", 1)[-1]
                title = (t or {}).get("titles", {}).get(fname) if t else None
                state = 0 if not e.private and e.size <= extract.NAME_ONLY else 2
                if kind in ("picture", "video", "audio", "archive") and not e.private:
                    state = 2
                folder = e.path.rsplit("/", 1)[0] if "/" in e.path else ""
                ntext = _name_text(e.path, title, t)
                if k:
                    cur.execute(
                        "UPDATE files SET size=?, mtime=?, kind=?, private=?, title=?, text_state=?, ticket=? "
                        "WHERE id=?",
                        (e.size, e.mtime, kind, int(e.private), title, state, e.ticket, k[0]),
                    )
                    _put(con, k[0], ntext, "", folds)
                else:
                    cur.execute(
                        "INSERT INTO files(path, folder, name, kind, size, mtime, ticket, private, title, "
                        "text_state) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            e.path,
                            folder,
                            fname,
                            kind,
                            e.size,
                            e.mtime,
                            e.ticket,
                            int(e.private),
                            title,
                            state,
                        ),
                    )
                    _put(con, cur.lastrowid, ntext, "", folds, new=True)
                pr.changed += 1
                n += 1
                if n % 5000 == 0:
                    con.commit()
            gone = [v[0] for p, v in known.items() if p not in seen]
            for i in range(0, len(gone), 500):
                part = gone[i : i + 500]
                q = ",".join("?" * len(part))
                cur.execute(f"DELETE FROM files WHERE id IN ({q})", part)
                cur.execute(f"DELETE FROM fts WHERE rowid IN ({q})", part)
                cur.execute(f"DELETE FROM texts WHERE id IN ({q})", part)
            pr.removed = len(gone)
            if changed_tickets:
                _rename_ticket_files(con, tickets, changed_tickets, folds)
            con.execute("INSERT OR REPLACE INTO meta VALUES('names_at', ?)", (str(time.time()),))
            con.execute("INSERT OR REPLACE INTO meta VALUES('ignored_shown', ?)", ("1" if show else "0",))
            con.commit()
            con.execute("UPDATE files SET text_state=0 WHERE text_state=3")  # last pass could not read them
            _read_texts(con, root, folds, text_seconds, pr, on_progress)
            pr.total = con.execute("SELECT count(*) FROM files").fetchone()[0]
            pr.unread = con.execute("SELECT count(*) FROM files WHERE text_state=0").fetchone()[0]
            con.execute("INSERT OR REPLACE INTO meta VALUES('checked_at', ?)", (str(time.time()),))
            con.commit()
        finally:
            con.close()
    pr.seconds = round(time.monotonic() - t0, 3)
    return pr


def _store_tickets(con: sqlite3.Connection, tickets: dict[str, dict]) -> set[str]:
    old = {r[0]: r[1] for r in con.execute("SELECT id, sig FROM tickets")}
    changed: set[str] = set()
    for tid, t in tickets.items():
        sig = json.dumps([t["key"], t["title"], t["titles"]], sort_keys=True)
        if old.get(tid) != sig:
            changed.add(tid)
        con.execute(
            "INSERT OR REPLACE INTO tickets(id, key, title, status, updated, sig) VALUES(?,?,?,?,?,?)",
            (tid, t["key"], t["title"], t["status"], t["updated"], sig),
        )
    for tid in set(old) - set(tickets):
        con.execute("DELETE FROM tickets WHERE id=?", (tid,))
    return {t for t in changed if t in old}  # new tickets' files get their names when they are first seen


def _rename_ticket_files(con, tickets, changed, folds) -> None:
    for tid in changed:
        t = tickets[tid]
        for r in con.execute("SELECT id, path, title FROM files WHERE ticket=?", (tid,)).fetchall():
            title = t["titles"].get(r["path"].rsplit("/", 1)[-1]) or r["title"]
            ntext = _name_text(r["path"], title, t)
            con.execute("UPDATE files SET title=? WHERE id=?", (title, r["id"]))
            _put(con, r["id"], ntext, None, folds)


def secret_in(text: str, root: Path) -> bool:
    """The orch secret check on the whole text, in windows of the check's size that overlap (a key on a border
    is still seen): secrets by their shape (keys, tokens) and the workspace's stored key values. Its line rule for
    key=value lines is left out on purpose: it would flag nearly every config and code file. A text it flags never
    enters the index and is never shown or served."""
    try:
        from orch import secretscan
    except ImportError:
        return False
    step = max(1024, secretscan.MAX_BYTES - 4096)
    try:
        for at in range(0, max(1, len(text)), step):
            if secretscan.find(text[at : at + secretscan.MAX_BYTES], root, strict=False, labels=False):
                return True
        return False
    except Exception:  # noqa: BLE001 - a check that cannot run keeps the text out (fail closed)
        return True


def _read_texts(con, root: Path, folds: bool, seconds, pr: Progress, on_progress) -> None:
    end = None if seconds is None else time.monotonic() + seconds
    while True:
        rows = con.execute(
            "SELECT id, path, kind, size, ticket, title FROM files WHERE text_state=0 ORDER BY mtime DESC LIMIT ?",
            (TEXT_BATCH,),
        ).fetchall()
        if not rows:
            return
        for r in rows:
            kind, path = r["kind"], r["path"]
            want = extract.needs_bytes(kind, path)
            data = walk.read_head(str(root), path, want) if want else b""
            body, title, state, secret = "", r["title"], 2, False
            if data is None:
                state = 3  # could not be read now (locked, being synced): tried again on the next pass
            elif data:
                kind2, body, found_title = extract.text_of(path, kind, data)
                if (body or found_title) and secret_in(body + "\n" + (found_title or ""), root):
                    body, secret, found_title = "", True, None  # nothing of it is kept, not even a title
                elif kind in ("doc", "pdf") or extract.ext_of(path) == "xlsx":
                    # every part of the file, not only the text kept for search; unreadable parts count as a hit
                    whole = extract.pdf_scan(data) if kind == "pdf" else extract.office_scan(data)
                    if whole is None or secret_in(whole, root):
                        body, secret, found_title = "", True, None
                if body:
                    state = 1
                kind = kind2
                if found_title and not title:
                    title = found_title
            # a file whose text the secret check flags is private from now on: name only, never shown or served
            con.execute(
                "UPDATE files SET text_state=?, kind=?, title=?, private=max(private, ?) WHERE id=?",
                (state, kind, title, int(secret), r["id"]),
            )
            if body or title != r["title"]:
                tk = con.execute("SELECT key, title FROM tickets WHERE id=?", (r["ticket"],)).fetchone()
                ntext = _name_text(path, title, dict(tk) if tk else None)
                _put(con, r["id"], ntext, body, folds)
            pr.read += 1
        con.commit()
        if on_progress:
            on_progress(pr)
        if end is not None and time.monotonic() > end:
            return


# ---- search
def _terms(q: str) -> tuple[list[str], list[str]]:
    words = [w for w in fold(q).split() if w]
    return [w for w in words if len(w) >= 3], [w for w in words if len(w) < 3]


def _match(words: list[str], column: str | None = None) -> str:
    inner = " AND ".join('"' + w.replace('"', '""') + '"' for w in words)
    return f"{{{column}}} : ({inner})" if column else f"({inner})"


def _line(body: str, words: list[str]) -> str | None:
    if not body:
        return None
    for line in body.splitlines():
        f = fold(line)
        if any(w in f for w in words):
            t = line.strip().lstrip("#>-* \t")
            first = min((fold(t).find(w) for w in words if w in fold(t)), default=0)
            if first > 40:
                t = "…" + t[first - 24 :]
            return t[:240]
    return None


def _row(r: sqlite3.Row) -> dict:
    return {
        "path": r["path"],
        "name": r["name"],
        "folder": r["folder"],
        "kind": r["kind"],
        "word": extract.word_of(r["name"], r["kind"]),
        "size": r["size"],
        "changed": r["mtime"] // 1_000_000_000,
        "ticket": r["ticket"],
        "title": r["title"] or nice_title(r["name"]),
        "private": bool(r["private"]),
    }


COLS = "f.id, f.path, f.name, f.folder, f.kind, f.size, f.mtime, f.ticket, f.title, f.private"


def search(root: Path, q: str, limit: int = 50, names_only: bool = False) -> dict:
    """Name hits first (best match, newer wins a tie), then files that hold the words in their text (bm25: most
    about the words, in the shortest file). Every word must be in the name or the text. A file shows once."""
    t0 = time.perf_counter()
    limit = max(1, min(int(limit), MAX_HITS))
    try:
        con = connect(root)
    except (FileNotFoundError, sqlite3.Error):
        return {"query": q, "items": [], "total": 0, "unread": 0, "ms": 0, "ready": False}
    try:
        long, short = _terms(q)
        items: list[dict] = []
        if long:
            names = con.execute(
                f"SELECT {COLS} FROM fts JOIN files f ON f.id = fts.rowid WHERE fts MATCH ? "
                "ORDER BY bm25(fts, 1.0, 0.0), f.mtime DESC LIMIT ?",
                (_match(long, "name"), limit + len(short) * limit),
            ).fetchall()
            seen = set()
            for r in names:
                if short and not all(s in fold(r["name"] + " " + (r["title"] or "")) for s in short):
                    continue
                seen.add(r["id"])
                items.append({**_row(r), "found": "name"})
            if len(items) < limit and not names_only:
                rest = con.execute(
                    f"SELECT {COLS} FROM fts JOIN files f ON f.id = fts.rowid WHERE fts MATCH ? "
                    "ORDER BY bm25(fts, 0.0, 1.0), f.mtime DESC LIMIT ?",
                    (_match(long), limit * 2),
                ).fetchall()
                for r in rest:
                    if r["id"] in seen:
                        continue
                    line = _line(_body(con, r["id"]), long + short)
                    if short and not all(s in fold(r["name"]) or (line and s in fold(line)) for s in short):
                        continue
                    seen.add(r["id"])
                    items.append({**_row(r), "found": "text", "line": line})
                    if len(items) >= limit:
                        break
        elif short:
            like = "%" + short[0].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = con.execute(
                f"SELECT {COLS} FROM files f WHERE lower(f.name) LIKE ? ESCAPE '\\' "
                "OR lower(coalesce(f.title, '')) LIKE ? ESCAPE '\\' ORDER BY f.mtime DESC LIMIT ?",
                (like, like, limit * 4),
            ).fetchall()
            for r in rows:
                hay = fold(r["name"] + " " + (r["title"] or ""))
                if all(s in hay for s in short):
                    items.append({**_row(r), "found": "name"})
                if len(items) >= limit:
                    break
        total = con.execute("SELECT count(*) FROM files").fetchone()[0]
        unread = con.execute("SELECT count(*) FROM files WHERE text_state=0").fetchone()[0]
    except sqlite3.Error:
        return {"query": q, "items": [], "total": 0, "unread": 0, "ms": 0, "ready": False}
    finally:
        con.close()
    return {
        "query": q,
        "items": items[:limit],
        "total": total,
        "unread": unread,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
        "ready": True,
        "names_only": names_only,
    }


# ---- reads for the page
def status(root: Path) -> dict:
    try:
        con = connect(root)
    except (FileNotFoundError, sqlite3.Error):
        return {"ready": False, "total": 0, "unread": 0, "checked_at": None}
    try:
        total = con.execute("SELECT count(*) FROM files").fetchone()[0]
        unread = con.execute("SELECT count(*) FROM files WHERE text_state=0").fetchone()[0]
        row = con.execute("SELECT v FROM meta WHERE k='checked_at'").fetchone()
        names = con.execute("SELECT v FROM meta WHERE k='names_at'").fetchone()
        shown = con.execute("SELECT v FROM meta WHERE k='ignored_shown'").fetchone()
        return {
            "ready": bool(names),
            "total": total,
            "unread": unread,
            "checked_at": float(row[0]) if row else None,
            "ignored_shown": bool(shown and shown[0] == "1"),  # the list was read with that switch
        }
    except sqlite3.Error:
        return {"ready": False, "total": 0, "unread": 0, "checked_at": None}
    finally:
        con.close()


def folder(root: Path, path: str) -> dict:
    """The sub-folders (with how many files are inside each, all levels) and the files of one of your folders."""
    con = connect(root)
    try:
        path = path.strip("/")
        prefix = path + "/" if path else ""
        files = [
            _row(r)
            for r in con.execute(
                f"SELECT {COLS} FROM files f WHERE f.ticket IS NULL AND f.folder=? ORDER BY f.name COLLATE NOCASE",
                (path,),
            )
        ]
        subs: dict[str, int] = {}
        if prefix:
            like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = con.execute(
                "SELECT folder, count(*) FROM files WHERE ticket IS NULL AND folder LIKE ? ESCAPE '\\' GROUP BY folder",
                (like,),
            )
        else:
            rows = con.execute(
                "SELECT folder, count(*) FROM files WHERE ticket IS NULL AND folder<>'' GROUP BY folder"
            )
        for f, n in rows:
            rest = f[len(prefix) :]
            if not rest:
                continue
            top = rest.split("/", 1)[0]
            subs[top] = subs.get(top, 0) + n
        return {
            "path": path,
            "folders": [
                {"path": prefix + k, "name": k, "count": v}
                for k, v in sorted(subs.items(), key=lambda x: x[0].lower())
            ],
            "files": files,
        }
    finally:
        con.close()


def tree(root: Path) -> dict:
    """Every folder of your folders with its file count (all levels), for the left tree."""
    con = connect(root)
    try:
        counts: dict[str, int] = {"": 0}
        for f, n in con.execute("SELECT folder, count(*) FROM files WHERE ticket IS NULL GROUP BY folder"):
            parts = f.split("/") if f else []
            counts[""] += n
            for i in range(1, len(parts) + 1):
                k = "/".join(parts[:i])
                counts[k] = counts.get(k, 0) + n
        return {"folders": [{"path": k, "count": v} for k, v in sorted(counts.items())]}
    finally:
        con.close()


def recent(root: Path, limit: int = 30, since: float | None = None) -> list[dict]:
    con = connect(root)
    try:
        if since:
            rows = con.execute(
                f"SELECT {COLS} FROM files f WHERE f.mtime > ? ORDER BY f.mtime DESC LIMIT ?",
                (int(since * 1_000_000_000), limit),
            )
        else:
            rows = con.execute(f"SELECT {COLS} FROM files f ORDER BY f.mtime DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]
    finally:
        con.close()


def count_since(root: Path, since: float) -> int:
    con = connect(root)
    try:
        return con.execute(
            "SELECT count(*) FROM files WHERE mtime > ?", (int(since * 1_000_000_000),)
        ).fetchone()[0]
    finally:
        con.close()


def by_paths(root: Path, paths: list[str]) -> list[dict]:
    if not paths:
        return []
    con = connect(root)
    try:
        out = []
        for i in range(0, len(paths), 500):
            part = paths[i : i + 500]
            q = ",".join("?" * len(part))
            out += [_row(r) for r in con.execute(f"SELECT {COLS} FROM files f WHERE f.path IN ({q})", part)]
        return out
    finally:
        con.close()


def one(root: Path, path: str) -> dict | None:
    """The indexed row of one path (only indexed files can be shown or served)."""
    try:
        con = connect(root)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        r = con.execute(f"SELECT {COLS} FROM files f WHERE f.path=?", (path,)).fetchone()
        return _row(r) if r else None
    finally:
        con.close()


EARLIER_DAYS = 30
WORKING = ("active", "open", "ready", "waiting", "")


def ticket_groups(root: Path, now: float | None = None) -> list[dict]:
    """The automatic folders: one per ticket that has files, under Working, In review, Done and Earlier (done more
    than 30 days ago). Built from the index; nothing is moved on disk."""
    now = now or time.time()
    con = connect(root)
    try:
        tk = {r["id"]: dict(r) for r in con.execute("SELECT id, key, title, status, updated FROM tickets")}
        per: dict[str, list[dict]] = {}
        for r in con.execute(f"SELECT {COLS} FROM files f WHERE f.ticket IS NOT NULL ORDER BY f.mtime DESC"):
            per.setdefault(r["ticket"], []).append(_row(r))
    finally:
        con.close()
    parts: dict[str, list[dict]] = {"working": [], "review": [], "done": [], "earlier": []}
    for tid, files in per.items():
        t = tk.get(tid) or {"id": tid, "key": tid, "title": tid, "status": "", "updated": ""}
        st = t["status"]
        if st == "review":
            part = "review"
        elif st in ("done", "dropped"):
            part = "earlier" if _age_days(t["updated"], now) > EARLIER_DAYS else "done"
        else:
            part = "working"
        parts[part].append(
            {
                "id": tid,
                "key": t["key"],
                "title": t["title"],
                "status": "working" if part == "working" else "review" if part == "review" else "done",
                "files": files,
                "newest": files[0]["changed"] if files else 0,
            }
        )
    labels = {"working": "Working", "review": "In review", "done": "Done", "earlier": "Earlier"}
    out = []
    for k, lst in parts.items():
        if lst:
            lst.sort(key=lambda x: -x["newest"])
            out.append({"id": k, "label": labels[k], "tickets": lst})
    return out


def _age_days(iso: str, now: float) -> float:
    try:
        t = calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0
    return (now - t) / 86400


def size_on_disk(root: Path) -> int:
    n = 0
    with contextlib.suppress(OSError):
        for p in cache_dir(root).glob("index.db*"):
            n += p.stat().st_size
    return n
