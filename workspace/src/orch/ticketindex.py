"""The ticket index: one small row per ticket, so a list does not read and parse every ticket file (ORCH-521).

Kept in `.orch/run/ticket-index.json` (this computer's own state, never synced). It is a cache, never the
truth: every call looks at each ticket file's stat (inode, size, change time) and reads again only the files
that changed, appeared or went away since the index was written. So a ticket written by `orch ticket new`,
an edit, a status move, a sync step, a peer or a hand edit is seen on the next call without any write hook,
and a crash in the middle of a write leaves at worst an old or broken index that the next call repairs. A
missing, broken or other-version index file is rebuilt from the ticket files. Writing the index back is
best effort: a read-only folder only costs the speed.

A row holds what the lists need (`orch ticket list`, `orch needs`, the dashboard): see `_row`.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

VERSION = 5  # a row or entry changed shape: an index of another version is rebuilt
NOTE_HEAD = 200
_FILE_RE = re.compile(r"^(t_.*)\.json$", re.S)  # as tickets.list_all globs: t_*.json
_NEWER_RE = re.compile(r"orch\.ticket/(\d+)$")
_CLOSED = ("done", "dropped")
_NO_WRITE: contextvars.ContextVar[bool] = contextvars.ContextVar("ticketindex_no_write", default=False)


@contextlib.contextmanager
def no_write():
    """Inside: the index is brought up to date in memory only, never written (`orch diag` reads a workspace
    without changing a byte of it)."""
    token = _NO_WRITE.set(True)
    try:
        yield
    finally:
        _NO_WRITE.reset(token)


def index_path(root: Path) -> Path:
    return root / ".orch" / "run" / "ticket-index.json"


def _sig(st: os.stat_result) -> list[int]:
    """What tells a changed file: inode, size, modified time and, outside Windows, the change time, which no
    one can set back by hand (an in-place edit that keeps the size and resets the modified time is seen)."""
    return [st.st_ino, st.st_size, st.st_mtime_ns] + ([st.st_ctime_ns] if os.name != "nt" else [])


def _hidden(t: dict) -> str | None:
    from orch import tickets

    return tickets.hidden_kind(t)


def _newest(stamps: list[str]) -> str | None:
    """The newest of the history times, compared as times (as tickets.quiet_since does), kept as written."""
    best = None
    for text in stamps:
        try:
            at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if best is None or at > best[0]:
            best = (at, text)
    return best[1] if best else None


def _failing(steps: list[dict]) -> bool:
    """An open step whose last recorded checks failed often enough to count as stuck (stuck.py)."""
    from orch import stuck

    return any(
        not x.get("done") and not x.get("wont_do") and stuck.failed_runs(x) >= stuck.FAILED_RUNS
        for x in steps
    )


def _row(t: dict) -> dict:
    """The index row of one parsed ticket file."""
    steps = [x for x in t.get("checklist") or [] if isinstance(x, dict)]
    stamps = [h["at"] for h in t.get("history") or [] if isinstance(h, dict) and isinstance(h.get("at"), str)]
    note = t.get("note")
    work = t.get("work") if isinstance(t.get("work"), dict) else {}
    back = work.get("bring_back") if isinstance(work.get("bring_back"), dict) else {}
    waiting = t.get("waiting_on")
    decided = [  # answered with a decision: what `orch review list --answered` lists (before proof)
        q
        for q in t.get("questions") or []
        if isinstance(q, dict) and q.get("answer") is not None and isinstance(q.get("decision"), dict)
    ]
    return {
        "id": t["id"],
        "key": t.get("key"),
        "title": t.get("title"),
        "status": t.get("status"),
        "owner": t.get("owner"),
        "parent": t.get("parent"),
        "epic": t.get("epic"),
        "release": t.get("release"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "due": t.get("due"),
        "priority": t.get("priority"),  # ORCH-813: the list shows high and low
        "revision": t.get("revision"),
        "hidden": _hidden(t),
        "questions_open": sum(
            1 for q in t.get("questions") or [] if isinstance(q, dict) and q.get("answer") is None
        ),
        "answers": len(decided),
        "answered_at": max((q["at"] for q in decided if isinstance(q.get("at"), str)), default=None),
        "waiting_on": waiting if isinstance(waiting, dict) and waiting else None,
        "bring_back": back.get("state") == "waiting",
        "steps": {
            "done": sum(1 for x in steps if x.get("done")),
            "wont": sum(1 for x in steps if x.get("wont_do") and not x.get("done")),
            "total": len(steps),
        },
        "failing": _failing(steps),
        "last_at": _newest(stamps),
        "note_head": note[:NOTE_HEAD] if isinstance(note, str) else None,
    }


def _parse(p: Path, tid: str, size: int) -> tuple[dict | None, bool]:
    """(row, shows sync) of one ticket file. The row is None when the file is not a ticket this orch lists
    (unreadable, broken JSON, id not matching the name, a newer format): the same files list_all leaves
    out. "Shows sync" is history.doc_shows_sync of whatever JSON the file holds, as history.tickets_show_sync
    reads it (a file over 64 MB counts as not showing it there, so here too)."""
    from orch import history

    try:
        t = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None, False
    try:
        sync = size <= 64 * 1024 * 1024 and bool(history.doc_shows_sync(t))
    except (RecursionError, AttributeError):
        sync = False
    if not isinstance(t, dict) or t.get("id") != tid:
        return None, sync
    m = _NEWER_RE.match(str(t.get("schema", "")))
    if m and int(m.group(1)) > 1:
        return None, sync
    try:
        return _row(t), sync
    except (TypeError, AttributeError, ValueError, KeyError):
        return None, sync  # odd field shapes (a checklist that is no list): no row, never a broken listing


def _read_index(root: Path) -> dict:
    try:
        data = json.loads(index_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(data, dict)
        or data.get("version") != VERSION
        or not isinstance(data.get("files"), dict)
    ):
        return {}
    return data["files"]


def _write_index(root: Path, files: dict) -> None:
    p = index_path(root)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"version": VERSION, "files": files}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)  # never procs.replace: a reader holding the index on Windows must not stall a list
    except OSError:
        pass  # best effort (a busy or read-only file): the next call reads the changed files again
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _fresh(root: Path) -> dict:
    """{id: {"sig", "row", "traced"}} of every ticket file, the index first brought up to date."""
    d = root / ".orch" / "tickets"
    old = _read_index(root)
    files: dict = {}
    changed = False
    try:
        entries = list(os.scandir(d))
    except OSError:
        entries = []
    for e in entries:
        m = _FILE_RE.match(e.name)
        if not m:
            continue
        try:
            if not e.is_file():
                continue
            sig = _sig(e.stat() if os.name != "nt" else os.stat(e.path))  # DirEntry has no inode on Windows
        except OSError:
            continue
        tid = m.group(1)
        was = old.get(tid)
        if isinstance(was, dict) and was.get("sig") == sig and isinstance(was.get("traced"), bool):
            row = was.get("row", False)
            if row is None or (isinstance(row, dict) and row.get("id") == tid):
                files[tid] = was
                continue
        changed = True
        row, sync = _parse(Path(e.path), tid, sig[1])
        files[tid] = {"sig": sig, "row": row, "traced": sync}
    if (changed or set(files) != set(old)) and not _NO_WRITE.get():
        _write_index(root, files)
    return files


def rows(root: Path, include_hidden: bool = False) -> list[dict]:
    """One row per ticket, by creation time (as tickets.list_all), hidden tickets (Chat, Manager, sessions)
    left out unless include_hidden. Fresh on every call. The rows are copies the caller may change."""
    found = (f["row"] for f in _fresh(root).values())
    out = [dict(r) for r in found if isinstance(r, dict) and (include_hidden or not r.get("hidden"))]
    out.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
    return out


def any_shows_sync(root: Path) -> bool:
    """history.tickets_show_sync from the index: some ticket file carries sync's own traces."""
    return any(f.get("traced") for f in _fresh(root).values())


def counts(root: Path) -> dict:
    """{"total": n, "by_status": {status: n}} of the listed tickets (hidden ones left out)."""
    by: dict[str, int] = {}
    rs = rows(root)
    for r in rs:
        by[str(r.get("status"))] = by.get(str(r.get("status")), 0) + 1
    return {"total": len(rs), "by_status": by}


def children_counts(all_rows: list[dict]) -> dict[str, dict]:
    """{parent id: {"total", "closed", "open"}} in one pass (tickets.children_counts asks one parent at a
    time, which is quadratic over a big list)."""
    out: dict[str, dict] = {}
    for r in all_rows:
        parent = r.get("parent")
        if not isinstance(parent, str):
            continue
        c = out.setdefault(parent, {"total": 0, "closed": 0, "open": 0})
        c["total"] += 1
        c["closed" if r.get("status") in _CLOSED else "open"] += 1
    return out


def no_children() -> dict:
    return {"total": 0, "closed": 0, "open": 0}


def load(root: Path, ids) -> dict[str, dict]:
    """{id: ticket} of these tickets read in full, in the given order: the readers that pick from the index
    rows first and read only the files they need (ORCH-1622). A file that cannot be read, a hidden ticket or a
    newer orch's file is left out, as tickets.list_all leaves it out."""
    from orch import tickets
    from orch.errors import Refused

    out: dict[str, dict] = {}
    for tid in ids:
        if tid in out:
            continue
        try:
            t = tickets.load(root, tid)
        except (Refused, OSError, ValueError, KeyError):
            continue
        if isinstance(t, dict) and t.get("id") == tid and not tickets.is_hidden(t):
            out[tid] = t
    return out


def hidden_or_unknown(root: Path) -> tuple[list[str], list[str]]:
    """(ids of hidden tickets, ids of files the index has no row for: unreadable, broken or a newer orch's),
    from the index (ORCH-1622: harness._general_lines read every ticket file on every private write).
    A caller that must not miss a hidden ticket reads the second list in full itself."""
    hidden, unknown = [], []
    for tid, f in sorted(_fresh(root).items()):
        row = f.get("row")
        if isinstance(row, dict):
            if row.get("hidden"):
                hidden.append(tid)
        else:
            unknown.append(tid)
    return hidden, unknown
