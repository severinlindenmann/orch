"""Read .orch/ files of a workspace into one JSON-able state. Read only; never writes."""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor as _Executor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import look, mobile, people, phone_delivery

_run = subprocess.run  # tests patch this name, never the global subprocess.run (other threads use that)


class ThreadPoolExecutor(_Executor):
    """A pool whose jobs run in a copy of the caller's context, so a read inside load_state shares its one look
    at the ticket files (ticketindex.reuse, ORCH-1621)."""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)


def _reuse_index():
    """ticketindex.reuse() of the core, or nothing for an older core without it."""
    try:
        from orch import ticketindex

        return ticketindex.reuse()
    except (ImportError, AttributeError):
        return contextlib.nullcontext()


def _me(root: Path | None = None) -> str:
    from .actions import actor  # actions imports this module

    return actor(root)


STATUS_ORDER = ["open", "ready", "active", "waiting", "review", "done", "dropped"]
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ICONS = (
    "clock",
    "calendar",
    "inbox",
    "list",
    "chart",
    "bell",
    "book",
    "globe",
    "link",
    "check",
    "star",
    "box",
    "chat",
    "folder",
    "user",
    "bolt",
    "target",
    "hammer",
    "cloud",
    "share",
    "users",
)
FORMATS = ("text", "time", "cron-human", "chips", "yes-no", "open-page")


def find_workspace(start: Path) -> Path | None:
    """Walk up from start to the first folder that has .orch/."""
    p = start.resolve()
    for d in [p, *p.parents]:
        if (d / ".orch").is_dir():
            return d
    return None


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _json_files(folder: Path):
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file() and not p.is_symlink())


# Slow-changing read-only answers (the add-on list is asked 2-3 times per page poll): kept 10 s, and dropped
# whenever the page makes a change (actions.run_op calls forget_static), so a reply never shows old settings.
STATIC_TTL = 10.0
_STATIC_CMDS = (("addon", "list"), ("agents",))
_STATIC: dict[tuple, tuple[float, object]] = {}


def forget_static() -> None:
    _STATIC.clear()


def _addon_files_mark(root: Path) -> tuple:
    """The add-on files' state: `orch addon add|remove|uninstall` in the terminal misses the kept answer at once,
    else a rebuild right after it stored the old add-on list under the new revision until the 120 s safety rebuild."""
    mark = []
    with contextlib.suppress(Exception):
        from orch import addons

        for path in (addons.activation_path(root), addons.registry_path()):
            try:
                st = os.stat(path)
                mark.append((st.st_mtime_ns, st.st_size))
            except OSError:
                mark.append(None)
    return tuple(mark)


def _argv0(orch_bin):
    try:
        from orch.pagesession import argv0
    except ImportError:
        return [orch_bin]
    return argv0(orch_bin)


def _child_env(env, orch_bin):
    try:
        from orch.pagesession import child_env
    except ImportError:
        return {**env, "ORCH_BIN": orch_bin}
    return child_env(env, orch_bin)


SELF = "orch:self"  # orch.pagesession.SELF: the real server, which runs in the core's own interpreter
_MISS = object()
READS = {"process": 0, "here": 0, "worker": 0}  # how each read was answered (the tests count the processes)


def _read_here(orch_bin: str, args: list[str], root: Path):
    """The real server only: the hot reads (ticket list, run status, review list) are answered by the core in
    this process (orch.reads), the same JSON as the command, without a new Python process each (ORCH-102: a
    dozen processes per build made one build take seconds while helpers ran). _MISS = start the command."""
    if orch_bin != SELF:
        return _MISS
    try:
        from orch import reads
        from orch.errors import Refused
    except ImportError:  # an older core without orch.reads
        return _MISS
    try:
        return reads.answer(root, args)
    except reads.NotHere:
        return _MISS
    except Refused:  # the command would refuse (exit 2): the same None as a failed command
        return None
    except Exception:  # noqa: BLE001 - anything unexpected: the command gets its chance
        return _MISS


def run_orch(orch_bin: str | None, args: list[str], root: Path, timeout: float = 5.0):
    """Run `$ORCH_BIN <args>` in the workspace and return its parsed stdout JSON, or None on any failure."""
    if not orch_bin:
        return None
    if any(tuple(args[: len(c)]) == c for c in _STATIC_CMDS):
        # the cache comes first even for a read answered here: the add-on list costs a look at every add-on
        key, mark = (orch_bin, str(root), tuple(args)), _addon_files_mark(root)
        hit = _STATIC.get(key)
        if hit and time.monotonic() - hit[0] < STATIC_TTL and hit[2] == mark:
            return hit[1]
        out = _read(orch_bin, args, root, timeout)
        if out is not None:
            _STATIC[key] = (time.monotonic(), out, mark)
        return out
    return _read(orch_bin, args, root, timeout)


def _read(orch_bin: str, args: list[str], root: Path, timeout: float):
    here = _read_here(orch_bin, args, root)
    if here is not _MISS:
        READS["here"] += 1
        return here
    return _run_orch(orch_bin, args, root, timeout)


# Reads the core allows a person only (workspace Chat). The page reads them for the person who is signed in, so they
# run without an agent tool's variables: a dashboard started from a helper's shell (a test install, a click-through)
# would otherwise read them as that helper, be refused and answer 404 (ORCH-383). Clicks do the same (actions).
_PERSON_READS = (("chat", "sync"), ("chat", "contacts"), ("chat", "thread"))


def _person_environ(environ) -> dict | None:
    """environ without the agent tools' variables (orch.adapters.human_environ); None when that list can not be read
    (fail closed: the read is not made rather than made as the agent)."""
    try:
        from orch.adapters import human_environ

        return human_environ(environ)
    except Exception:  # noqa: BLE001 - an old orch or a bad adapter file
        return None


def _by_worker(orch_bin: str, args: list[str], root: Path, timeout: float, env: dict):
    """The real server only: a read orch.reads does not answer goes to this process's read worker (ORCH-634)
    instead of a new `python -I -P -m orch` per read. _MISS = start the command (an older core, or no worker
    could answer)."""
    if orch_bin != SELF or _run is not subprocess.run:  # a test that replaced the process starter: no worker
        return _MISS
    try:
        from orch import readworker
    except ImportError:
        return _MISS
    try:
        got = readworker.run(root, args, timeout=timeout, environ=env)
    except Exception:  # noqa: BLE001 - the command gets its chance
        return _MISS
    if got is None:
        return _MISS
    READS["worker"] += 1
    code, out = got
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def _run_orch(orch_bin: str, args: list[str], root: Path, timeout: float):
    env = {**os.environ, "ORCH_ROOT": str(root)}
    if tuple(args[:2]) in _PERSON_READS:
        env = _person_environ(env)
        if env is None:
            return None
    got = _by_worker(orch_bin, args, root, timeout, env)
    if got is not _MISS:
        return got
    READS["process"] += 1
    try:
        r = _run(
            [*_argv0(orch_bin), *args],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_child_env(env, orch_bin),
        )
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _valid_ticket(t, stem: str | None = None) -> bool:
    return (
        isinstance(t, dict)
        and t.get("schema") == "orch.ticket/1"
        and isinstance(t.get("id"), str)
        and (stem is None or t["id"] == stem)
        and isinstance(t.get("title"), str)
        and t.get("status") in STATUS_ORDER
    )


@functools.lru_cache(maxsize=8)
def _resolved(root: str) -> Path:
    """The workspace folder with links resolved, worked out once per process (it was once per proof file)."""
    return Path(root).resolve()


def _file_here(root: Path, tid: str, ref: str) -> int | None:
    """Size of this proof file if it is on this computer, else None. Looked up under the workspace or the ticket's evidence folder, never outside."""
    base = _resolved(str(root))
    for cand in (root / ref, root / ".orch" / "tickets" / tid / "evidence" / Path(ref).name):
        try:
            p = cand.resolve()
            p.relative_to(base)
        except (OSError, ValueError, RuntimeError):
            continue
        if p.is_file():
            try:
                return p.stat().st_size
            except OSError:
                return 0
    return None


def _proof_changed(root: Path, tid: str, ev: dict) -> bool:
    """The core's answer to "does the file on disk differ from this copied proof" (ORCH-1874); no core, no hint."""
    try:
        from orch.tickets import proof_changed
    except ImportError:
        return False
    try:
        return bool(proof_changed(root, tid, ev))
    except Exception:  # noqa: BLE001 - a hint, never a reason for the page to fail
        return False


def _mark_missing_proofs(root: Path, t: dict, tail: int | None = None) -> None:
    """`missing` / `size` / `changed` on each file proof. tail=n: only the last n proofs per task (a live row
    shows no more, slim_row)."""
    for c in t.get("checklist", []):
        evs = c.get("evidence", []) if isinstance(c, dict) and isinstance(c.get("evidence"), list) else []
        for ev in evs[-tail:] if tail else evs:
            if (
                isinstance(ev, dict)
                and ev.get("type") == "file"
                and isinstance(ev.get("ref"), str)
                and "\x00" not in ev["ref"]
            ):
                size = _file_here(root, str(t["id"]), ev["ref"])
                ev["missing"] = size is None
                ev.pop("changed", None)  # only ever from the files on disk, never from the ticket file
                if size is not None:
                    ev["size"] = size
                    if ev.get("source") and _proof_changed(root, str(t["id"]), ev):
                        ev["changed"] = True


SYNC_BY = "agent:sync"  # orch.history.SYNC_BY (the dashboard needs it when the core cannot be imported)
SYNCED_UNVERIFIED = "(synced, not verified here) "


def _demote_all(t: dict) -> dict:
    """Without the core nothing can be proven: every person field is the sync role (fail closed)."""

    def agent(by) -> bool:  # orch.history.is_agent_history_author, the same rule
        if not isinstance(by, str) or not by.isascii() or by != unicodedata.normalize("NFKC", by):
            return False
        label = by.casefold()
        return bool(re.fullmatch(r"agent:[a-z0-9._-]{1,40}", label)) and not label[6:].startswith(
            mobile.NOT_PLAIN_AGENTS
        )

    out = dict(t)
    if isinstance(t.get("history"), list):
        out["history"] = [
            {**h, "by": SYNC_BY, "text": SYNCED_UNVERIFIED + str(h.get("text", ""))}
            if isinstance(h, dict) and not agent(h.get("by"))
            else h
            for h in t["history"]
        ]
    if isinstance(t.get("checklist"), list):
        out["checklist"] = [
            {
                **c,
                **{f: SYNC_BY for f in ("by", "wont_by") if f in c and not agent(c.get(f))},
                **(
                    {
                        "evidence": [
                            {**e, "by": SYNC_BY} if isinstance(e, dict) else e  # any author: none is proven
                            for e in c["evidence"]
                        ]
                    }
                    if isinstance(c.get("evidence"), list)
                    else {}
                ),
            }
            if isinstance(c, dict)
            else c
            for c in t["checklist"]
        ]
    for field, key in (("verdicts", "person"), ("questions", "answered_by"), ("refs", "by")):
        if isinstance(t.get(field), list):
            out[field] = [
                {**x, key: SYNC_BY}
                if isinstance(x, dict) and x.get(key) is not None and not agent(x[key])
                else x
                for x in t[field]
            ]
    if "description_by" in t and not agent(t.get("description_by")):
        out["description_by"] = SYNC_BY
    if isinstance(t.get("plan"), dict) and "by" in t["plan"] and not agent(t["plan"].get("by")):
        out["plan"] = {**t["plan"], "by": SYNC_BY}
    return out


def shown(root: Path, t):
    """The ticket as this machine can prove its person fields (orch.history.shown_ticket, the one rule).
    Without the core (ImportError): every person field demoted, never shown as the person (fail closed)."""
    try:
        from orch.history import shown_ticket
    except ImportError:
        return _demote_all(t) if isinstance(t, dict) else t
    return shown_ticket(root, t)


def _plain(text, cap: int = 120) -> str:
    """One untrusted fragment (a path name an agent chose) as one plain line, like the core's
    the core's card text: control and format characters and line breaks become spaces, runs of space collapse,
    double quotes become single ones (it cannot fake the quotes around it), at most `cap` characters."""
    import unicodedata

    t = "".join(
        " " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c
        for c in str(text if text is not None else "")
    )
    t = " ".join(t.split()).translate({ord(c): "'" for c in '"\u201c\u201d\u201e\u2033\u00ab\u00bb'})
    return t[:cap] + "\u2026" if len(t) > cap else t


_REVIEW_CACHE: dict = {}  # (root, ticket, project HEAD, copy tip) -> `copy review` result
_REVIEW_CACHE_MAX = 64


def _review_key(root: Path, tid: str):
    """(root, ticket, HEAD sha, copy tip sha) from one `git rev-parse`, or None when either cannot be read."""
    try:
        r = _run(
            ["git", "-C", str(root), "rev-parse", "HEAD", f"refs/heads/orch/{tid}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    shas = r.stdout.split()
    if r.returncode != 0 or len(shas) != 2 or not all(re.fullmatch(r"[0-9a-f]{40,64}", x) for x in shas):
        return None
    return (str(Path(root).resolve()), tid, shas[0], shas[1])


def _copy_review(orch_bin, root: Path, tid: str):
    """`orch copy review <tid> --json`, run again only when the project HEAD or the copy's tip moved (the
    subprocess ran on every state load). The result is only ever shown with the tip it was made for; the core
    still re-checks on approve. No cache when HEAD or the tip cannot be read."""
    args = ["copy", "review", tid, "--json"]
    key = _review_key(root, tid)
    if key is None:
        return run_orch(orch_bin, args, root)
    if key in _REVIEW_CACHE:
        return json.loads(json.dumps(_REVIEW_CACHE[key]))
    out = run_orch(orch_bin, args, root)
    if isinstance(out, dict) and out.get("tip") == key[3]:  # never keep a result for another tip than its key
        while len(_REVIEW_CACHE) >= _REVIEW_CACHE_MAX:
            _REVIEW_CACHE.pop(next(iter(_REVIEW_CACHE)))
        _REVIEW_CACHE[key] = json.loads(json.dumps(out))
    return out


EMPTY_COPY = "The copy has no changes to add. Nothing to apply."


def _bring_back_view(back: dict, review) -> dict:
    """The waiting state for the ticket page: what the core's `copy review` says, checked and made plain
    HERE (server side), so the approval dialog shows exactly the tip, the count and the paths it binds."""
    code = back.get("reason_code")
    view = {
        "state": "waiting",
        "reason": _plain(back.get("reason") or "", 200),
        "reason_code": code if isinstance(code, str) and re.fullmatch(r"[a-z-]{1,20}", code) else "waiting",
    }
    if not isinstance(review, dict):
        return view
    tip, count, digest = review.get("tip"), review.get("control_paths", 0), review.get("paths_hash")
    paths = review.get("paths") if isinstance(review.get("paths"), list) else []
    if (
        isinstance(tip, str)
        and re.fullmatch(r"[0-9a-f]{40,64}", tip)
        and type(count) is int
        and count >= 0
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{8}", digest)
    ):
        shown = [_plain(p) for p in paths[:5]]
        for key in ("commits", "files"):  # how much the tip brings (shown next to the control paths)
            n = review.get(key)
            if type(n) is int and n >= 0:
                view[key] = n
        if view.get("commits") == 0 and view.get("files") == 0:
            # nothing to apply (ORCH-1809): no tip, so no Apply changes button that could only be refused
            view.update(empty=True, reason=EMPTY_COPY)
            return view
        view.update(
            tip=tip,
            control_paths=count,
            paths_hash=digest,
            paths=shown,
            paths_more=max(0, count - len(shown)),
            paths_summary=", ".join(shown)
            + (f" and {count - len(shown)} more" if count > len(shown) else ""),
        )
    return view


def _review_tip(root: Path, tid: str, branches: dict) -> str | None:
    """The tip recorded when the ticket entered Review (B13g): the ticket page shows it and its Done sends it
    back, so the core can tell whether new changes arrived after the person looked. None when there is none.
    `branches`: one per-load cache; the work branches are listed with ONE git call, and not at all while
    copies are off (nothing to look up then)."""
    try:
        from orch import worktrees

        if "set" not in branches:
            from orch import config

            # copies off: no branch is listed (a registered copy is still looked up by review_tip itself)
            branches["set"] = set() if config.copies_mode(root) == "off" else worktrees.work_branches(root)
        tip = worktrees.review_tip(root, tid, branches["set"])
    except Exception:  # noqa: BLE001 - no tip shown: the Done is judged as without one
        return None
    return tip if isinstance(tip, str) and re.fullmatch(r"[0-9a-f]{40,64}", tip) else None


def _add_question_digests(t: dict, root: Path | None = None) -> None:
    """Each question gets the digest of what the page shows of it: an answer sends it back and the person's
    proof binds it, so an answer to a question changed since is refused (core tickets.question_digest)."""
    try:
        from orch.tickets import question_digest
    except ImportError:  # standalone, without the core: no digest, so no answer can be sent (fail closed)
        return
    for q in t["questions"]:
        if isinstance(q, dict):
            q["digest"] = question_digest(q)
            card = q.get("card")
            if isinstance(card, dict) and card.get("kind") == "run" and q.get("answer") is None:
                # a run card's last failed try (ORCH-848), so Home and the ticket page keep its error; an older
                # core has none: the card shows without it
                with contextlib.suppress(Exception):
                    from orch.review import run_last

                    try:
                        q.update(run_last(t, q, card, root))
                    except TypeError:  # an older core: no sign-in in the terminal
                        q.update(run_last(t, q, card))


# The live page's state (ORCH-522): open tickets and those finished in the last RECENT_DAYS (at most RECENT_MAX);
# older finished tickets load when a page asks (GET /api/ticket/<id>, the Tickets list's own pages). Rows in the
# live state are cut short (history tail, last evidence per task): the ticket page reads the whole ticket itself.
RECENT_DAYS = 7
RECENT_MAX = 200
HISTORY_TAIL = 3
EVIDENCE_TAIL = 2
FINISHED = ("done", "dropped")
ANSWERED_MAX = 200  # decided questions in the live state (Review > Answered), newest first


_ROWS: dict[str, tuple[str, list[dict]]] = {}  # per workspace: (ticket files' look, their index rows)


def _tickets_look(root: Path) -> str | None:
    """Name, times and size of every ticket file in one scandir pass (tens of ms at 10,000): the index rows of the
    same look are the same, so they are kept instead of read again (a quarter second each at 10,000)."""
    rows = []
    try:
        with os.scandir(root / ".orch" / "tickets") as it:
            for e in it:
                if e.name.endswith(".json"):
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    rows.append(f"{e.name}\0{st.st_mtime_ns}\0{st.st_ctime_ns}\0{st.st_size}\0{st.st_ino}")
    except OSError:
        return None
    rows.sort()
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _index_rows(root: Path) -> list[dict] | None:
    """Every ticket's short row from the core's ticket index (ORCH-521), hidden ones left out; None without one.
    Kept while no ticket file changed (the ticket page, a key lookup and a click each asked for all of them)."""
    try:
        from orch import ticketindex
    except ImportError:
        return None
    look = _tickets_look(root)  # taken before the read: a change during it makes the kept rows stale
    kept = _ROWS.get(str(root))
    if look is not None and kept is not None and kept[0] == look:
        return [dict(r) for r in kept[1]]  # each caller its own rows
    try:
        rows = ticketindex.rows(root)
    except Exception:  # noqa: BLE001 - a broken index: the full read below still answers
        return None
    if not isinstance(rows, list):
        return None
    rows = [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)]
    if look is not None:
        _ROWS[str(root)] = (look, [dict(r) for r in rows])
    return rows


def _when(value) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def live_ids(rows: list[dict], now: float | None = None) -> list[str]:
    """The ids the live state holds: every open ticket, plus finished ones changed in the last RECENT_DAYS (the
    RECENT_MAX newest of them)."""
    cutoff = (time.time() if now is None else now) - RECENT_DAYS * 86400
    open_ = [r["id"] for r in rows if r.get("status") not in FINISHED]
    done = [r for r in rows if r.get("status") in FINISHED and _when(r.get("updated_at")) >= cutoff]
    done.sort(key=lambda r: _when(r.get("updated_at")), reverse=True)
    return open_ + [r["id"] for r in done[:RECENT_MAX]]


def ticket_counts(rows: list[dict]) -> dict:
    """{"total": n, "by_status": {status: n}} over every ticket (finished ones too)."""
    by: dict[str, int] = {}
    for r in rows:
        st = r.get("status")
        if st in STATUS_ORDER:
            by[st] = by.get(st, 0) + 1
    return {"total": sum(by.values()), "by_status": by}


def _parts(rows: list[dict]) -> dict[str, dict]:
    """Per parent id: its children's ids and how many of them are done, from every ticket's row."""
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: str(r.get("updated_at", "")), reverse=True):
        parent = r.get("parent")
        if isinstance(parent, str) and parent:
            p = out.setdefault(parent, {"children": [], "parts_done": 0, "parts_total": 0})
            p["children"].append(r["id"])
            p["parts_total"] += 1
            p["parts_done"] += int(r.get("status") == "done")
    return out


def _raw_list(root: Path, orch_bin: str | None) -> list[tuple]:
    """(ticket, file stem) of every ticket: `orch ticket list --all --json`, else the files themselves."""
    raw = run_orch(orch_bin, ["ticket", "list", "--all", "--json"], root)
    if isinstance(raw, dict):
        raw = raw.get("tickets")
    if isinstance(raw, list):
        return [(t, None) for t in raw]
    items = [(_load(f), f.stem) for f in _json_files(root / ".orch" / "tickets")]
    for t, _stem in items:  # without the core nothing can verify a verdict: a raw Done is Review (V1)
        if isinstance(t, dict) and t.get("status") == "done":
            t["status"], t["verdict_needed"] = "review", True
    return items


def _read_many(root: Path, ids: list[str]) -> list[dict]:
    """These tickets as `orch ticket show <id> --json` prints each, read in this process in one pass: the history
    proof worked out once for all of them (ORCH-522; the core keeps the active add-ons between tickets). A ticket
    that cannot be read is left out."""
    try:
        from orch import history
        from orch import tickets as core
        from orch.cli import visible
        from orch.errors import Refused
    except ImportError:
        return [t for t in (_show_here(root, tid) for tid in ids) if t is not None]
    out = []
    for tid in ids:
        try:
            out.append(visible(root, core.load(root, tid)))
        except (Refused, OSError, ValueError, KeyError, TypeError):
            continue
    return json.loads(json.dumps(history.shown_json(root, out), ensure_ascii=False))


def _show_here(root: Path, tid: str):
    """One ticket as `orch ticket show <id> --json` prints it, read in this process (the real server only)."""
    try:
        from orch import reads
        from orch.errors import Refused
    except ImportError:
        return None
    try:
        return reads.answer(root, ["ticket", "show", tid, "--json"])
    except (reads.NotHere, Refused):
        return None
    except Exception:  # noqa: BLE001 - a ticket the core cannot read is left out, never an error
        return None


def load_tickets(root: Path, orch_bin: str | None = None) -> tuple[list[dict], int]:
    """Every valid-looking ticket (schema orch.ticket/1, id, title, status), finished ones too. Returns
    (tickets, skipped). Read through `$ORCH_BIN ticket list --all --json` (without --all, done and dropped tickets
    would vanish); without the orch command (standalone use) from .orch/tickets. Snapshots use this; the live page
    uses load_live_tickets."""
    tickets, skipped, rows = _shape_items(root, orch_bin, _raw_list(root, orch_bin))
    _add_parts(tickets, _parts(rows))
    return tickets, skipped


def load_live_tickets(root: Path, orch_bin: str | None = None) -> tuple[list[dict], int, dict]:
    """The live page's tickets (live_ids) and the counts of all tickets: (tickets, skipped, counts). On the real
    server the ticket index names them and only their files are read; elsewhere the full list is cut the same way."""
    rows = _index_rows(root) if orch_bin == SELF else None
    if rows is not None:
        ids = live_ids(rows)
        tickets, skipped, _ = _shape_items(root, orch_bin, [(t, None) for t in _read_many(root, ids)], True)
        counts = ticket_counts(rows)
    else:  # no index (an older core, a test's orch): the full list, cut before it is shaped
        items = _raw_list(root, orch_bin)
        rows = _rows_of(items)
        keep = set(live_ids(rows))
        keep_items = [(t, s) for t, s in items if not _valid_ticket(t, s) or t["id"] in keep]
        tickets, skipped, _ = _shape_items(root, orch_bin, keep_items, True)
        counts = ticket_counts(rows)
    _add_parts(tickets, _parts(rows))
    return tickets, skipped, counts


def _rows_of(items: list[tuple]) -> list[dict]:
    """The short rows (id, key, status, parent, updated_at) of read tickets, the General conversation left out."""
    return [
        {k: t.get(k) for k in ("id", "key", "status", "parent", "updated_at")}
        for t, stem in items
        if _valid_ticket(t, stem) and t.get("general") is not True
    ]


def _shape_items(
    root: Path, orch_bin: str | None, items: list[tuple], live: bool = False
) -> tuple[list[dict], int, list[dict]]:
    """Shape the read tickets as the page reads them: (tickets newest first, skipped, rows of all of them)."""
    branch_cache: dict = {}  # the work branches, listed once per load (see _review_tip)
    tickets, skipped = [], 0
    for t, stem in items:
        if isinstance(t, dict) and t.get("general") is True:  # the hidden General conversation is no ticket
            continue
        if not _valid_ticket(t, stem):
            skipped += 1
            continue
        tail = EVIDENCE_TAIL if live else None  # a live row shows the last proofs only (slim_row)
        tickets.append(_shape_ticket(root, orch_bin, t, branch_cache, stem is not None, tail))
    _mark_tickets(root, tickets)
    tickets.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
    rows = [
        {"id": t["id"], "status": t["status"], "parent": t.get("parent"), "updated_at": t.get("updated_at")}
        for t in tickets
    ]
    return tickets, skipped, rows


def _add_parts(tickets: list[dict], parts: dict[str, dict]) -> None:
    for t in tickets:
        p = parts.get(t["id"]) or {}
        t.update(
            children=list(p.get("children") or []),
            parts_done=p.get("parts_done", 0),
            parts_total=p.get("parts_total", 0),
        )


def _done_entry(history: list) -> int | None:
    for i in range(len(history) - 1, -1, -1):
        e = history[i]
        if isinstance(e, dict) and (
            e.get("kind") == "done"
            or re.search(r"(?:->|to) done\b|^Done\b", str(e.get("text") or ""), re.IGNORECASE)
        ):
            return i
    return None


# only the ticket page reads these (it reads the whole ticket); a list row does without them
PAGE_ONLY = ("refs", "art")
# asked_at and answered_at place the question and its answer in a session's chat (ORCH-1658: without them the live
# layer said "No messages yet" for a session whose question was answered)
ANSWER_KEEP = {"id", "text", "answer", "answered_by", "via", "at", "asked_at", "answered_at", "kind", "check"}


def slim_row(t: dict) -> dict:
    """A ticket as a live-state row: the last HISTORY_TAIL history lines (and the line that marked it done, and
    the lines shown in Chat), the last EVIDENCE_TAIL proofs per task, answered questions without their card,
    no links (PAGE_ONLY). Marked "slim": true with what was left out
    ("history_more"), so the ticket page reads the whole ticket (GET /api/ticket/<id>). Unchanged when nothing
    was cut."""
    history = t.get("history") if isinstance(t.get("history"), list) else []
    keep = set(range(max(0, len(history) - HISTORY_TAIL), len(history)))
    done = _done_entry(history)
    if done is not None:
        keep.add(done)
    keep |= {i for i, e in enumerate(history) if isinstance(e, dict) and e.get("in_chat") is True}
    checklist = t.get("checklist") if isinstance(t.get("checklist"), list) else []
    cut_evidence = any(
        isinstance(c, dict) and isinstance(c.get("evidence"), list) and len(c["evidence"]) > EVIDENCE_TAIL
        for c in checklist
    )
    questions = t.get("questions") if isinstance(t.get("questions"), list) else []
    answered = [q for q in questions if isinstance(q, dict) and q.get("answer") is not None]
    cut_answers = any(set(q) - ANSWER_KEEP for q in answered)
    page_only = [k for k in PAGE_ONLY if t.get(k)]
    if len(keep) == len(history) and not (cut_evidence or cut_answers or page_only):
        return t
    out = dict(t)
    for k in page_only:
        out.pop(k)
    if (
        cut_answers
    ):  # an answered question: what was answered, by whom (the card and its digest are the page's)
        out["questions"] = [
            {k: v for k, v in q.items() if k in ANSWER_KEEP}
            if isinstance(q, dict) and q.get("answer") is not None
            else q
            for q in questions
        ]
    out["history"] = [e for i, e in enumerate(history) if i in keep]
    out["history_more"] = len(history) - len(out["history"])
    if cut_evidence:
        out["checklist"] = [
            {
                **c,
                "evidence": c["evidence"][-EVIDENCE_TAIL:],
                "evidence_more": len(c["evidence"]) - EVIDENCE_TAIL,
            }
            if isinstance(c, dict)
            and isinstance(c.get("evidence"), list)
            and len(c["evidence"]) > EVIDENCE_TAIL
            else c
            for c in checklist
        ]
    out["slim"] = True
    return out


def ticket_rows_view(tickets: list[dict]) -> list[dict]:
    """Shaped tickets as the rows a list shows (the live state's rows; the Tickets list's pages use the same)."""
    return [slim_row(t) for t in tickets]


def _shape_ticket(
    root: Path,
    orch_bin: str | None,
    t: dict,
    branch_cache: dict,
    from_file: bool = True,
    evidence_tail: int | None = None,
) -> dict:
    """One ticket as the page reads it (a full build does this for every ticket, a click for its own).
    from_file=False: the core's answer, already shown as provable here (ORCH-522: doing it again for every
    ticket took 7 s at 10,000); a ticket read from its file is shown here."""
    if from_file:
        t = shown(root, t)
    for k in ("checklist", "refs", "questions", "history"):
        if not isinstance(t.get(k), list):
            t[k] = []
    _add_question_digests(t, root)
    t.pop("review_tip", None)  # only ever from the core's signed record (the ticket file is not)
    if t["status"] == "review":
        tip = _review_tip(root, t["id"], branch_cache)
        if tip:
            t["review_tip"] = tip
    back = (t.get("work") or {}).get("bring_back") or {}
    if back.get("state") == "waiting":
        t["bring_back"] = _bring_back_view(back, _copy_review(orch_bin, root, t["id"]))
    _mark_missing_proofs(root, t, evidence_tail)
    mobile.mark_chat_history(t)
    return t


def _mark_tickets(root: Path, tickets: list[dict]) -> None:
    phone_delivery.mark(root, tickets)
    add_proof_state(tickets, root)
    add_artifact_marks(tickets)
    add_quiet(tickets)
    add_stuck(tickets)


def add_proof_state(tickets: list[dict], root: Path | None = None) -> None:
    """`proof` on each ticket: the core's proof_state (per task, what is not covered, the one-line summary).
    With `root` it also tells when files changed since a recorded check (one cached git read, a few seconds)."""
    try:
        from orch import tickets as core
    except ImportError:
        return
    for t in tickets:
        try:  # a ticket the core cannot read gets no line, never an error
            t["proof"] = core.proof_state(t, root, cache=True)
        except (KeyError, TypeError, ValueError):
            t.pop("proof", None)


def add_quiet(tickets: list[dict]) -> None:
    """`quiet_since` on a Working ticket with no news for 6 h (G2): the core's one rule, asked here for the CLI
    listing and the file fallback alike. Not stored; no field on the ticket file."""
    try:
        from orch import tickets as core
    except ImportError:
        return
    for t in tickets:
        t.pop("quiet_since", None)
        try:
            since = core.quiet_since(t)
        except (TypeError, ValueError, AttributeError):
            since = None
        if since:
            t["quiet_since"] = since


def add_stuck(tickets: list[dict]) -> None:
    """`stuck` ("question" | "quiet" | "overdue") from the core's one rule (ORCH-189); a stuck helper is added by
    the page from the run. Not stored."""
    try:
        from orch import tickets as core
    except ImportError:
        return
    for t in tickets:
        t.pop("stuck", None)
        try:
            why = core.stuck_why(t)
        except (TypeError, ValueError, AttributeError):
            why = None
        if why:
            t["stuck"] = why


def load_counts(
    tickets: list[dict], runs: dict, root: Path | None = None, needs: list | None = None
) -> dict | None:
    """ORCH-476: the core's one count of everything a page shows (needs you, working, stuck, step x of y,
    won't do), over the same tickets and runs the page draws. None with an older core: the page counts as before.
    ORCH-1741: with root, a ticket the merge queue holds and a Check card that gives way to the ticket's other
    card are left out, as the Review page's cards are. #2385: needs = the needs rows the page draws (`orch
    needs`); its rows of work that stopped count in the number, so Home adds nothing of its own."""
    try:
        from orch import counts as core
    except ImportError:
        return None
    hidden = None
    if root is not None and hasattr(core, "quiet"):
        try:
            hidden = core.quiet(root, tickets)
        except Exception:  # noqa: BLE001 - counted as before
            hidden = None
    kw: dict = {"hidden": hidden} if hidden else {}
    if isinstance(needs, list) and hasattr(core, "stopped_rows"):
        kw["stopped"] = needs
    try:
        return core.summary(tickets, runs, **kw)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def add_spend(root: Path, tickets: list[dict], background: bool = False) -> None:
    """`spend` {cost, seconds} on tickets a helper worked on: helper time and money at list price, read from the
    helpers' conversation files by the core (cached per file). Left out of snapshots (ORCH-189)."""
    try:
        from orch import usage
    except ImportError:
        return
    try:
        got = usage.spend(root, tickets)
    except (OSError, TypeError, ValueError):
        return
    for t in tickets:
        t.pop("spend", None)
        if t.get("id") in got:
            t["spend"] = got[t["id"]]
    add_range(root, tickets, background)


def _range_now(root: Path) -> str:
    try:
        from orch import usage

        return usage.range_words(usage.estimate_range(root))
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return ""


RANGE_TTL = 600.0  # the range moves only when tickets finish: the live page works it out again this often
_RANGES: dict[str, list] = {}  # workspace -> [worked out at (monotonic), words, a thread is working it out]
_RANGES_LOCK = threading.Lock()


def _range_later(root: Path) -> str:
    """The live page's range: the last one worked out (at most RANGE_TTL old), worked out again in a thread of
    its own. It reads every finished ticket (seconds at 10,000), so the state build never waits for it
    (ORCH-522); until the first one is ready the tickets show none."""
    key = str(root)
    with _RANGES_LOCK:
        at, words, busy = _RANGES.get(key) or [None, "", False]
        if not busy and (at is None or time.monotonic() - at > RANGE_TTL):
            _RANGES[key] = [at, words, True]

            def work():
                got = _range_now(root)
                with _RANGES_LOCK:
                    _RANGES[key] = [time.monotonic(), got, False]

            threading.Thread(target=work, name="orch-range", daemon=True).start()
    return words


def add_range(root: Path, tickets: list[dict], background: bool = False) -> None:
    """`range` ("about 20-40 min · $2.00-$4.00") on tickets nobody has worked on yet: the time and cost range
    before Start, from this workspace's own finished tickets (the core's usage.estimate_range; ORCH-297).
    background=True (the live page): the last range worked out, never waiting for a new one."""
    words = _range_later(root) if background else _range_now(root)
    for t in tickets:
        t.pop("range", None)
        if words and t.get("status") in ("open", "ready") and not t.get("sessions") and "spend" not in t:
            t["range"] = words


def add_artifact_marks(tickets: list[dict]) -> None:
    """`art` on each ticket: {address: {id, rev, kind}} for its links and its pr/commit/url proof, with the same id, rev
    and kind (html, pr, commit, link) the phone gets (the core's phone_view); nothing is uploaded."""
    try:
        from orch import phone_view
    except ImportError:
        return
    for t in tickets:
        art: dict[str, dict] = {}
        links = t.get("refs") if isinstance(t.get("refs"), list) else []
        pairs = [("link", ln.get("url")) for ln in links if isinstance(ln, dict)]
        for c in t.get("checklist") if isinstance(t.get("checklist"), list) else []:
            evs = c.get("evidence") if isinstance(c, dict) and isinstance(c.get("evidence"), list) else []
            pairs += [
                (ev["type"], ev.get("ref"))
                for ev in evs
                if isinstance(ev, dict) and ev.get("type") in ("url", "pr", "commit")
            ]
        for source, ref in pairs[:100]:
            if not isinstance(ref, str) or not ref.startswith(("http://", "https://")):
                continue
            try:  # one bad entry never hides the others
                kind, rev = phone_view._url_art(source, ref)
                art[ref] = {"id": phone_view.artifact_id(source, ref), "rev": rev, "kind": kind}
            except ValueError:
                continue
        t["art"] = art


def _hidden_files(root: Path) -> list[Path]:
    """The ticket files that can hold a conversation (Chat, Manager, sessions without a ticket): only those the
    ticket index marks hidden when there is one (ORCH-522: every file was read twice per build, 1.5 s at
    10,000), else every file."""
    folder = root / ".orch" / "tickets"
    try:
        from orch import ticketindex

        rows = ticketindex.rows(root, include_hidden=True)
    except Exception:  # noqa: BLE001 - no index (or a broken one): every file, as before
        return _json_files(folder)
    names = sorted(f"{r['id']}.json" for r in rows if r.get("hidden") and isinstance(r.get("id"), str))
    return [p for p in (folder / n for n in names) if p.is_file() and not p.is_symlink()]


def load_general(root: Path) -> dict | None:
    """The General conversation of the phone (the hidden ticket with `general: true`): {id, history}, oldest first."""
    for f in _hidden_files(root):
        t = _load(f)
        if (
            isinstance(t, dict)
            and t.get("general") is True
            and isinstance(t.get("id"), str)
            and t["id"] == f.stem
        ):
            t = shown(root, t)
            raw = t.get("history") if isinstance(t.get("history"), list) else []
            hist = [h for h in raw if isinstance(h, dict) and isinstance(h.get("text"), str)]
            hist = [h for h in hist if mobile.is_chat_entry(h)]  # messages only
            return {"id": t["id"], "history": hist[-200:]}
    return None


# Sessions without a ticket (ORCH-364, core sessions.py): the hidden tickets that hold one, in the New menu's order.
SESSION_TITLES = {
    "empty": "Empty helper",
    "chat": "Chat helper",
    "terminal": "Plain terminal",
    "manager": "Manager",
}


def _session_kind(t: dict) -> str | None:
    if t.get("general") is True:
        return "chat"
    if t.get("manager") is True:
        return "manager"
    return t["session"] if t.get("session") in ("empty", "terminal") else None


def load_sessions(root: Path) -> list[dict]:
    """[{id, kind, title, closed}]: every session without a ticket this workspace made (read from the ticket
    files, no orch call). Whether a helper's is on comes from its run; the plain terminal is open until closed."""
    found: dict[str, dict] = {}
    for f in _hidden_files(root):
        t = _load(f)
        if not (isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"] == f.stem):
            continue
        kind = _session_kind(t)
        if kind and kind not in found:
            found[kind] = {
                "id": t["id"],
                "kind": kind,
                "title": SESSION_TITLES[kind],
                "closed": bool(t.get("closed_at")),
            }
            if kind == "empty":
                found[kind]["model"] = _next_model(t)
            if kind == "terminal" and not t.get("closed_at") and _signin_shown(root, t["id"]):
                found[kind].update(
                    title="Sign-in", signin=True
                )  # a sign-in card's window in front (ORCH-865)
    return [found[k] for k in SESSION_TITLES if k in found]


def _signin_shown(root: Path, tid: str) -> bool:
    """The plain terminal shows a sign-in card's window now (core sessions._signin_shown); False without the core."""
    try:
        from orch import sessions as core_sessions

        return core_sessions.shell_on(root, tid) and core_sessions._signin_shown(root, tid)
    except Exception:  # noqa: BLE001 - an older core or no tmux: the plain terminal as usual
        return False


def load_session_modes(root: Path, sessions: list[dict]) -> dict | None:
    """ORCH-818: {kind: {current, label, choices: [{mode, label, allowed}], full_warned, running, running_label}}
    for the Manager, Empty helper and Chat helper: the Start choice's permission row and the pane header's mode
    in words (core sessionmode.py). None when this orch has no such modes or no tool (the row is left out)."""
    try:
        from orch import adapters, sessionmode
        from orch import runs as core_runs
    except ImportError:
        return None
    try:
        name = adapters.chosen(root)
    except Exception:  # noqa: BLE001 - no tool here: nothing to choose
        return None
    ids = {s["kind"]: s["id"] for s in sessions}
    out = {}
    for kind in sessionmode.KINDS:
        try:
            row = sessionmode.offer(root, kind, name)
            run = None
            if kind in ids and core_runs.running(root, ids[kind]):
                v = (core_runs.read(root, ids[kind]) or {}).get("permissions")
                run = v if v in sessionmode.RANK else None
            row["running"] = run
            row["running_label"] = sessionmode.label(name, run, root) if run else None
        except Exception:  # noqa: BLE001, S112 - one kind that cannot be read shows no row
            continue
        out[kind] = row
    return out


def _next_model(t: dict) -> str | None:
    """The model the Empty helper starts on (or runs on): the New menu shows and preselects it (ORCH-710)."""
    try:
        from orch import tickets as core

        return core.next_model(t)
    except Exception:  # noqa: BLE001 - an older core: the page shows no model
        return None


def shape_sessions(sessions: list[dict], runs: dict) -> list[dict]:
    """[{id, kind, title, open, model?}] for the bar and the wall: a helper is open while its session runs; the
    Empty helper says the model it starts on."""
    out = []
    for s in sessions:
        on = (runs.get(s["id"]) or {}).get("running") is True
        out.append(
            {
                "id": s["id"],
                "kind": s["kind"],
                "title": s["title"],
                "open": not s["closed"] if s["kind"] == "terminal" else on,
                **({"signin": True} if s.get("signin") else {}),
                **({"model": s["model"]} if s.get("model") else {}),
            }
        )
    return out


def load_chat(root: Path, orch_bin: str | None) -> dict | None:
    """`orch chat status --json`: {helper, ticket, day, messages, activity, days, running}. None = not readable."""
    d = run_orch(orch_bin, ["chat", "status", "--json"], root)
    return d if isinstance(d, dict) else None


DASHBOARD_READER = "dashboard"  # one read mark for this computer's dashboard until sign-in (team chat step 3)


def load_ticket_chats(root: Path, orch_bin: str | None) -> list | None:
    """`orch chat list --json`: the ticket chats for the Chats page, newest first, with the dashboard's unread
    counts. None = not readable (an older core without the list)."""
    d = run_orch(orch_bin, ["chat", "list", "--reader", DASHBOARD_READER, "--json"], root)
    return d if isinstance(d, list) else None


def load_chat_days(root: Path, orch_bin: str | None) -> list | None:
    d = run_orch(orch_bin, ["chat", "days", "--json"], root)
    return d if isinstance(d, list) else None


def load_chat_day(root: Path, orch_bin: str | None, day: str) -> dict | None:
    """One day of History, read only (`orch chat day <day> --json`)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return None
    d = run_orch(orch_bin, ["chat", "day", day, "--json"], root)
    return d if isinstance(d, dict) else None


# The native cards the page knows how to draw (addons.py checks the same set); browser = the Browser page, ORCH-1494
PANELS = ("repeats", "links", "phone", "browser")


def load_addons(root: Path, orch_bin: str | None, raw=None) -> list[dict]:
    """Active add-ons that have a dashboard tab and/or ticket rows, from `orch addon list --json`, by `order`."""
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root) if raw is None else raw
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not (
            isinstance(a, dict)
            and a.get("active") is True
            and isinstance(a.get("name"), str)
            and _NAME.match(a["name"])
        ):
            continue
        d = a.get("dashboard") if isinstance(a.get("dashboard"), dict) else None
        if d and not (isinstance(d.get("label"), str) and d.get("icon") in ICONS):
            d = None
        tv = [
            r
            for r in a.get("ticket_view") or []
            if isinstance(r, dict)
            and isinstance(r.get("field"), str)
            and isinstance(r.get("label"), str)
            and r.get("format") in FORMATS
        ]
        pg = a.get("page") if isinstance(a.get("page"), dict) else None
        if pg and not (
            isinstance(pg.get("path"), str)
            and re.fullmatch(r"/[A-Za-z0-9_./-]*", pg["path"])
            and ".." not in pg["path"]
        ):
            pg = None
        tf = _ticket_fields(a.get("ticket_fields"))
        acts = [
            v for v in a.get("acts") or [] if isinstance(v, str) and re.fullmatch(r"[a-z][a-z-]{0,20}", v)
        ]
        kinds = [
            k.get("kind")
            for k in a.get("ticket_links") or []
            if isinstance(k, dict) and isinstance(k.get("kind"), str)
        ]
        if d or tv or tf or acts or kinds:
            out.append(
                {
                    "name": a["name"],
                    "dashboard": d
                    and {
                        "label": d["label"][:24],
                        "icon": d["icon"],
                        "order": d.get("order", 50),
                        "panel": d.get("panel") if d.get("panel") in PANELS else None,
                        "place": "settings" if d.get("place") == "settings" else "nav",
                        "stage": "preview" if d.get("stage") == "preview" else None,
                        "title": str(d["title"])[:40] if isinstance(d.get("title"), str) else None,
                        "subtitle": str(d["subtitle"])[:120] if isinstance(d.get("subtitle"), str) else None,
                    },
                    "ticket_view": tv,
                    # live_session: this add-on's page shows a ticket's live session; the ticket's
                    # "Watch live" button looks for it, so it must reach the page (ORCH-15)
                    "page": pg
                    and {
                        "path": pg["path"],
                        "label": str(pg.get("label") or "")[:40],
                        **({"live_session": True} if pg.get("live_session") is True else {}),
                    },
                    "ticket_fields": tf,
                    "acts": acts,
                    "link_kinds": kinds,
                    # orch-shipped (an installed package) vs a local folder someone added: the page of the
                    # latter runs sandboxed, with no way to use the person's session (H1)
                    "shipped": a.get("source") == "built-in",
                }
            )
    out.sort(key=lambda a: (a["dashboard"] or {}).get("order", 50))
    return out


FIELD_TYPES = ("text", "number", "date", "choice", "url")


def _ticket_fields(tf) -> dict | None:
    """`ticket_fields` of `orch addon list --json` (core already typed the schema): section, show_on_card, fields."""
    if not (
        isinstance(tf, dict) and isinstance(tf.get("section"), str) and isinstance(tf.get("fields"), list)
    ):
        return None
    fields = []
    for f in tf["fields"]:
        if not (
            isinstance(f, dict)
            and isinstance(f.get("key"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", f["key"])
            and f.get("type") in FIELD_TYPES
            and isinstance(f.get("title"), str)
        ):
            continue
        out = {
            "key": f["key"],
            "title": f["title"][:40],
            "type": f["type"],
            "read_only": f.get("read_only") is True,
            "hidden": f.get("hidden") is True,
        }
        if f["type"] == "choice":
            out["options"] = [
                {"value": o["value"], "label": str(o.get("label") or o["value"])[:40]}
                for o in f.get("options") or []
                if isinstance(o, dict) and isinstance(o.get("value"), str)
            ]
        fields.append(out)
    card = [k for k in tf.get("show_on_card") or [] if isinstance(k, str)][:3]
    return {"section": tf["section"][:24], "show_on_card": card, "fields": fields}


def link_kinds(raw) -> list[dict]:
    """The link types of the active add-ons (`orch addon list --json` rows), for orch.refs.describe."""
    out, seen = [], set()
    for a in sorted(
        (a for a in raw if isinstance(a, dict) and a.get("active") is True) if isinstance(raw, list) else [],
        key=lambda a: str(a.get("name")),
    ):
        for k in a.get("ticket_links") or []:
            if (
                isinstance(k, dict)
                and isinstance(k.get("kind"), str)
                and k["kind"] not in seen
                and isinstance(k.get("label"), str)
                and isinstance(k.get("icon"), str)
                and isinstance(k.get("match"), list)
            ):
                seen.add(k["kind"])
                out.append({**k, "addon": a["name"]})
    return out


def add_link_views(tickets: list[dict], kinds: list[dict]) -> None:
    """Each ticket link gets `view` (label, icon, mono, title, status, group) from the core's one link module."""
    try:
        from orch import refs
    except ImportError:  # standalone use without orch: no view, so the page shows no Links card
        return
    for t in tickets:
        for ln in t.get("refs") or []:
            if isinstance(ln, dict) and isinstance(ln.get("url"), str):
                ln["view"] = refs.describe(ln, kinds)
                ln["view"].update(
                    shown_type=shown_type(ln["view"].get("label"), ln["url"], refs),
                    **dict(zip(("host_head", "domain"), host_parts(ln["url"]))),
                )


# What a link row says it is: one rule (the phone app has the same one, LinkFace in ChatParts.swift).
# Type: an allowlist. Each " · " part is a known site's name, kept only on that site's own address, or a plain
# label of ASCII letters, digits, spaces and "-", at most 24, naming no site even with spaces and "-" taken out; else
# dropped, and with nothing left the type is "Link". Host: the registrable domain (never cut) and the rest before it.
_PLAIN = re.compile(r"[A-Za-z0-9 -]{1,24}")
TWO_PART_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "ne.jp",
        "or.jp",
        "com.br",
        "com.cn",
        "com.mx",
        "co.in",
        "co.za",
        "com.tr",
        "com.sg",
        "com.hk",
        "co.kr",
        "github.io",
        "gitlab.io",
    }
)


def _squeeze(s: str) -> str:
    return s.lower().replace(" ", "").replace("-", "")


def shown_type(label, url: str, refs) -> str:
    names = {h["name"].lower() for h in refs.known_sites()["hosts"]}
    on = (refs.site(url) or {}).get("name", "").lower()
    parts = []
    for p in (label if isinstance(label, str) else "").split(" · "):
        if p.lower() in names:
            if p.lower() == on:
                parts.append(p)
        elif _PLAIN.fullmatch(p) and not any(_squeeze(n) in _squeeze(p) for n in names):
            parts.append(p)  # a free label that names no site, even squeezed ("G i t-Hub PR" is just "Link")
    return " · ".join(parts) or "Link"


def domain(host: str) -> str:
    """The registrable part of a host (eTLD+1): github.com.evil.example -> evil.example. An IP stays whole."""
    parts = host.split(".")
    if len(parts) <= 2 or all(x.isdigit() for x in parts) or ":" in host:
        return host
    return ".".join(parts[-3:] if ".".join(parts[-2:]) in TWO_PART_SUFFIXES else parts[-2:])


def host_parts(url: str) -> tuple[str, str]:
    """(the host before the domain, e.g. "gist.", the domain)."""
    try:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        host = ""
    d = domain(host)
    return host[: len(host) - len(d)], d


def _consent(r: dict) -> str:
    """What turning an add-on on does, in the same words as `orch addon add` asks (built from `orch addon list`)."""
    name, d = r["name"], r.get("dashboard") if isinstance(r.get("dashboard"), dict) else None
    desc = str(r.get("description") or "").strip()
    head = f"{name} {r.get('version', '')}".replace("  ", " ").strip()
    lines = [desc, head] if desc else [head]
    if r.get("source") == "local":
        lines.append("Source: local folder (not checked by orch). It runs code on this computer.")
    lines.append(f"Lets helpers and you use it from the terminal: orch {name}")
    lines.append("Teaches your helpers how to use it.")
    if r.get("ticket_view"):
        lines.append("Keeps some extra information on your tickets.")
    if d and isinstance(d.get("label"), str):
        lines.append(f"Adds a dashboard tab: {d['label']}")
    if r.get("background"):
        lines.append("Keeps running in the background while it is on.")
    return "\n".join(lines)[:1200]


def _host(url) -> str:
    m = re.match(r"^https?://[^/\s]+", str(url or ""))
    return m.group(0)[:120] if m and "@" not in m.group(0) else ""


def _addon_detail(root: Path, name: str) -> dict | None:
    """Connection facts for an add-on that has a saved server link (.orch/secrets/<name>.json) and, if it keeps
    one, a list of other workspaces (.agents/skills/orch-<name>/workspaces.json). Never the token."""
    link = _load(root / ".orch" / "secrets" / f"{name}.json")
    if not isinstance(link, dict) or "url" not in link:
        return None
    url = _host(link.get("url"))
    out = {"connected": bool(url), "address": url, "workspaces": []}
    d = _load(root / ".agents" / "skills" / f"orch-{name}" / "workspaces.json")
    for w in (
        d.get("workspaces") if url and isinstance(d, dict) and isinstance(d.get("workspaces"), list) else []
    )[:50]:
        if isinstance(w, dict) and isinstance(w.get("name"), str):
            out["workspaces"].append({"name": w["name"][:60], "online": w.get("online") is True})
    return out


_DISK: dict = {}  # root -> {"at": monotonic, "val": dict | None, "busy": bool}
_DISK_LOCK = threading.Lock()
DISK_TTL = 20.0


def _disk_count(root: Path, key: str) -> None:
    try:
        from orch import worktrees

        val = worktrees.usage(root, seconds=3.0)
    except Exception:  # noqa: BLE001 - nothing could be measured: show an honest "none", never a stuck "..."
        val = {"copies": 0, "bytes": 0, "partial": False, "orphaned": [], "changed": 0, "stuck": []}
    with _DISK_LOCK:
        _DISK[key] = {"at": time.monotonic(), "val": val, "busy": False}


def _diag_stats(root: Path) -> dict:
    """Reports (count, newest) and saved notes (bytes, since): numbers only, read from the folder."""
    try:
        from orch import diag

        return diag.stats(root)
    except Exception:  # noqa: BLE001 - the card then says nothing; never an error in the settings
        return {"notes": {"bytes": 0, "files": 0, "since": None}, "reports": {"count": 0, "last": None}}


def copies_disk(root: Path) -> dict | None:
    """{copies, bytes, partial} for the settings line "Copies on this computer", or None only while the first
    count runs (the page shows "Counting…"); a count that fails reads as none. The walk runs on a thread
    (capped by core), never on the request."""
    from orch import worktrees

    def current(val):
        if val is None:
            return None
        try:
            return {**val, "copies": worktrees.count(root)}
        except Exception:  # noqa: BLE001 - keep the last measured count
            return val

    key = str(root)
    with _DISK_LOCK:
        e = _DISK.get(key)
        fresh = e is not None and time.monotonic() - e["at"] < DISK_TTL
        if e is not None and (fresh or e["busy"]):
            return current(e["val"])
        _DISK[key] = {"at": e["at"] if e else 0.0, "val": e["val"] if e else None, "busy": True}
        old = e["val"] if e else None
    threading.Thread(target=_disk_count, args=(root, key), daemon=True).start()
    return current(old)


def copies_disk_forget(root: Path) -> None:
    with _DISK_LOCK:
        _DISK.pop(str(root), None)


def _ws_tags(root: Path) -> list[str]:
    """The workspace's own tags; [] with an older core that has none."""
    from orch import config

    get = getattr(config, "workspace_tags", None)
    return list(get(root))[:4] if get else []


def person_list(root: Path) -> dict:
    """The workspace's person list for Settings, People (core orch.people); an older core has none: off."""
    try:
        from orch import people as orch_people
    except ImportError:
        return {"state": "off", "revision": None, "people": []}
    return orch_people.view(root)


def person_names(root: Path) -> dict:
    """{person id: name} so history lines by `human:pr_...` read as the person's name ("Lea (removed)")."""
    try:
        from orch import people as orch_people
    except ImportError:
        return {}
    return orch_people.names(root)


def load_settings(root: Path, orch_bin: str | None) -> dict:
    """What the Settings page shows: agents from `orch agents --json`, every installed add-on from `orch addon list --json`."""
    # the four `orch ... --json` reads side by side (one after the other they took seconds with helpers running)
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_agents = pool.submit(run_orch, orch_bin, ["agents", "--json"], root)
        f_rows = pool.submit(run_orch, orch_bin, ["addon", "list", "--json"], root)
        f_private = pool.submit(run_orch, orch_bin, ["private", "--json"], root)
        f_perm = pool.submit(run_orch, orch_bin, ["config", "get", "workspace.permissions", "--json"], root)
    agents, rows, private = f_agents.result(), f_rows.result(), f_private.result()
    manifests = _manifests(rows)  # ORCH-1739: what each add-on that is off needs
    private = private if isinstance(private, dict) else {}
    private_lines = private.get("lines")
    git_private = {
        "count": private.get("count") if type(private.get("count")) is int else 0,
        "lines": [line[:300] for line in private_lines if isinstance(line, str)][:4]
        if isinstance(private_lines, list)
        else [],
        "agent_command_ignored": private.get("agent_command_ignored") is True,
        "pending": [
            {
                "name": str(x.get("name")),
                "key": str(x.get("key")),
                "showable": x.get("showable") is True,
                **{
                    k: x[k]
                    for k in ("adapter", "command", "interactive", "prompt")
                    if isinstance(x.get(k), str)
                },
            }
            for x in (
                private.get("pending_agents") if isinstance(private.get("pending_agents"), list) else []
            )[:5]
            if isinstance(x, dict)
            and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", str(x.get("name")))
            and re.fullmatch(r"[0-9a-f]{64}", str(x.get("key")))
        ],
    }
    keep = ("name", "label", "adapter", "found", "version", "can", "status", "chosen", "models")
    perm = f_perm.result()
    perm = perm.get("workspace.permissions") if isinstance(perm, dict) else None
    from orch.config import (
        agents_may_finish,
        auto_reviewer_on,
        away_on,
        copies_max,
        copies_mode,
        copy_setup,
        diag_enabled,
        focus_session_typing,
        focus_terminal_typing,
        live_max,
        prepare_daily_limit,
        prepare_on_save_on,
        release_merge_on,
        reviewer_kinds,
        reviewer_on,
        workspace_description,
        workspace_name,
    )

    try:  # read-only look: the entry `orch share on` writes (a link is never followed)
        f = root / "AGENTS.md"
        share = (
            f.is_file()
            and not f.is_symlink()
            and "<!-- orch:begin share -->" in f.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        share = False
    return {
        "people_list": person_list(root),  # Settings, People: the workspace's person list (orch people)
        "agents_may_finish": agents_may_finish(root),
        "release_merge_on": release_merge_on(root),  # Settings: "Merge releases without my click"
        "prepare_on_save": prepare_on_save_on(root),  # Settings: "Prepare tickets when I save" (ORCH-741)
        "prepare_daily_limit": prepare_daily_limit(root),
        "auto_reviewer_on": auto_reviewer_on(root),  # ORCH-424: new tickets start without human review
        "reviewer_kinds": reviewer_kinds(root),  # ORCH-645: the kinds it accepts by itself
        "away_on": away_on(root),  # ORCH-425: Away mode, the Review page's second switch
        "reviewer_on": reviewer_on(root),  # Settings: "Accept small finished work for me" (workflow.reviewer)
        # ORCH-971: the two pull-request switches above show only where the workspace has pull requests
        "pull_requests": _has_pull_requests(root, rows),
        "copies": copies_mode(root),
        "copies_max": copies_max(root),
        "live_max": live_max(root),  # Settings > Helper > Helpers at once: None = no limit (the default)
        "copy_setup": copy_setup(root) or "",
        "ws_name": workspace_name(root) or "",
        "ws_description": workspace_description(root) or "",
        "ws_tags": _ws_tags(root),  # the workspace's own tags (Settings > Workspace profile)
        "typing_on": focus_session_typing(root),  # Settings > Add-ons: "Let me type into the helper's screen"
        "terminal_typing_on": focus_terminal_typing(root),  # "Let me type into the plain terminal" (ORCH-261)
        "diag_enabled": diag_enabled(root),  # the debug log switch (Settings > Report a problem)
        "diag": _diag_stats(root),
        "copies_disk": copies_disk(root),
        "folder": str(root),
        "share": share,
        "git_private": git_private,
        "permissions": perm if perm in ("ask", "auto", "full") else "auto",  # core's default is Auto
        "agents": [
            {k: a.get(k) for k in keep}
            for a in (agents if isinstance(agents, list) else [])
            if isinstance(a, dict) and isinstance(a.get("name"), str)
        ],
        "addons": [
            {
                "name": r["name"],
                "label": _label(r),  # the menu name (Shared links, Contacts), same as the sidebar
                "description": str(r.get("description") or "")[:200],
                "active": r.get("active") is True,
                "consent": _consent(r),
                **_requires(r, manifests),
                "detail": _addon_detail(root, r["name"]),
                "removable": r["name"] not in _core_addons(),  # core says: part of orch, only turned off
                # the add-on page of a live-session add-on carries the Typing switch
                **(
                    {"page": {"live_session": True}}
                    if isinstance(r.get("page"), dict) and r["page"].get("live_session") is True
                    else {}
                ),
            }
            for r in _addon_rows(rows)
            if r.get("installed") is not False
        ],
        # shipped with orch but not installed yet (`installed: false`): the catalogue lists them, Add turns one on
        "available": [
            {
                "name": r["name"],
                "label": _label(r),
                "description": str(r.get("description") or "")[:200],
                "version": str(r.get("version") or "")[:20],
                "recommended": r.get("recommended") is True,
                "background": r.get("background") is True,
                "consent": _consent(r),
                **_requires(r, manifests),
            }
            for r in _addon_rows(rows)
            if r.get("installed") is False
        ],
    }


def _core_addons() -> tuple[str, ...]:
    """The add-ons that are part of orch (core refuses `orch addon uninstall` for them)."""
    try:
        from orch.addons import CORE_ADDONS

        return tuple(CORE_ADDONS)
    except Exception:  # noqa: BLE001 - without the core list the CLI still refuses, in plain words
        return ()


def _has_pull_requests(root: Path, rows) -> bool:
    """True when the workspace has pull requests: a github.com remote on its folder, or the pull-requests
    add-on is on (a workspace of several repos, like orch's own, has no remote of its own)."""
    if any(r["name"] == "pull-requests" and r.get("active") is True for r in _addon_rows(rows)):
        return True
    try:
        from orch.skillrender import has_github_remote

        return has_github_remote(root)
    except (ImportError, OSError, ValueError):
        return False


def _addon_rows(rows) -> list[dict]:
    return [
        r
        for r in (rows if isinstance(rows, list) else [])
        if isinstance(r, dict) and isinstance(r.get("name"), str) and _NAME.match(r["name"])
    ]


def _requires(r: dict, manifests: dict | None = None) -> dict:
    """The add-ons this one needs (manifest `requires`): the pick list adds a needed add-on to the picks (ORCH-1739;
    the core refuses a run that misses one). From the listing row when it says, else from the manifests read once
    per settings build (`_manifests`). Only for add-ons that are off; nothing when none are needed."""
    if r.get("active") is True:
        return {}
    rq = r.get("requires")
    if not isinstance(rq, list):
        m = (manifests or {}).get(r["name"])
        rq = m.get("requires") if isinstance(m, dict) else None
    if not isinstance(rq, list):
        return {}
    names = [x for x in rq if isinstance(x, str) and _NAME.match(x)][:8]
    return {"requires": names} if names else {}


def _manifests(rows) -> dict:
    """The manifests of the add-ons that are off (their `requires`), read once; empty without the core."""
    if not any(r.get("active") is not True for r in _addon_rows(rows)):
        return {}
    try:
        from orch import addons

        return {**addons.bundled_manifests(), **addons.discover()}
    except Exception:  # noqa: BLE001  without the manifests the core still names a missing add-on plainly
        return {}


def _label(r: dict) -> str:
    d = r.get("dashboard") if isinstance(r.get("dashboard"), dict) else None
    lab = d.get("label") if d else None
    return lab[:40] if isinstance(lab, str) and lab.strip() else r["name"].capitalize()


def load_services(root: Path, orch_bin: str | None) -> list[dict]:
    """Background add-ons of this workspace, running or not. Source: `orch status --json` only (rows: addon, running, url)."""
    raw = run_orch(orch_bin, ["status", "--json"], root)
    here = str(root.resolve())
    for w in raw if isinstance(raw, list) else []:
        if isinstance(w, dict) and w.get("workspace") == here and isinstance(w.get("addons"), list):
            return [r for r in w["addons"] if isinstance(r, dict) and isinstance(r.get("addon"), str)]
    return []


_RUNS: dict[tuple[str, str], tuple[float, dict | None]] = {}
_RUN_SIGNATURES = {}
RUNS_TTL = 30.0  # as the state cache's safety refresh: changes of the run files force a fresh read anyway
RUNS_MAX = 30


def load_runs(
    root: Path,
    orch_bin: str | None,
    tickets: list[dict],
    fresh: bool = False,
    some: bool = False,
    extra: list[str] | None = None,
) -> dict[str, dict]:
    """Run status for tickets that can have a run (not done or dropped, or with a claim file), from `orch run status <id> --json`.
    Cached for a few seconds so the 3 s page poll costs nothing; an action's reply passes fresh=True.
    some=True: only these tickets (a click's answer); the next full build still sees the files as changed."""
    if not orch_bin:
        return {}
    from .events import Revisions

    if not some:
        signature = Revisions(root).fingerprint()
        if _RUN_SIGNATURES.get(str(root)) != signature:
            fresh = True
            _RUN_SIGNATURES[str(root)] = signature
    claims = root / ".orch" / "run" / "tickets"  # a done ticket can still have its live session open
    ids = [t["id"] for t in tickets if t["status"] not in ("done", "dropped")][:RUNS_MAX]
    first = set(ids)  # every ticket with a run claim too: a live session past the first RUNS_MAX (ORCH-359)
    ids += [t["id"] for t in tickets if t["id"] not in first and (claims / f"{t['id']}.json").exists()]
    ids += [i for i in extra or [] if i not in ids]  # sessions without a ticket (their tickets are hidden)
    now = time.monotonic()
    todo = [
        i for i in ids if fresh or (str(root), i) not in _RUNS or now - _RUNS[(str(root), i)][0] > RUNS_TTL
    ]
    if todo:
        # one process for all tickets (a process per ticket was most of the idle cost of an open page)
        batch = run_orch(orch_bin, ["run", "status", *todo, "--json"], root, timeout=5.0 + 0.5 * len(todo))
        rows = batch.get("runs") if isinstance(batch, dict) else None
        if rows is None and len(todo) == 1 and isinstance(batch, dict) and batch:
            rows = {
                todo[0]: batch
            }  # one ticket: the core answers its run itself, not {runs: {...}} (ORCH-884)
        rows = rows if isinstance(rows, dict) else {}
        got = [
            rows.get(i) if isinstance(rows.get(i), dict) and "error" not in rows[i] else None for i in todo
        ]
        for i, r in zip(todo, got, strict=True):
            if isinstance(r, dict) and "hold" in r:  # the core's one-line reason a live run waits: text only
                r["hold"] = " ".join(r["hold"].split())[:200] if isinstance(r["hold"], str) else None
                if not r["hold"]:
                    r.pop("hold")
            if (
                isinstance(r, dict) and "shared_folder" in r
            ):  # core's quiet line: text only, nothing else passes
                sf = r.pop("shared_folder")
                text = sf.get("line") if isinstance(sf, dict) else None
                text = " ".join(text.split())[:200] if isinstance(text, str) else ""
                if text:
                    r["shared_folder"] = {"line": text}
            _RUNS[(str(root), i)] = (now, r if isinstance(r, dict) else None)
    return {i: _RUNS[(str(root), i)][1] for i in ids if _RUNS[(str(root), i)][1]}


def add_warmth(root: Path, tickets: list[dict], statuses: dict) -> None:
    """Count down from live.since, as idle cleanup does; heartbeats do not reset it."""
    try:
        from orch.config import live_idle_minutes
    except ImportError:
        return
    limit, now = live_idle_minutes(root) * 60, time.time()
    for t in tickets:
        t.pop("warmth", None)
        status = statuses.get(t["id"]) or {}
        rec = status.get("claim") or {}
        if status.get("running") is not True or rec.get("mode") != "live":
            continue
        try:
            since = datetime.fromisoformat(rec["live"]["since"]).timestamp()
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            continue
        t["warmth"] = {"seconds_left": max(0, int(limit - (now - since)))}


def _answered_newest(root: Path, orch_bin: str | None):
    """`orch review list --answered --json`; on the real server the core's own walk that stops after the newest
    ANSWERED_MAX (ORCH-522: the command reads every ticket)."""
    if orch_bin == SELF:
        try:
            from orch.cli_review import _answered

            return json.loads(json.dumps(_answered(root, limit=ANSWERED_MAX), ensure_ascii=False))
        except Exception:  # noqa: BLE001, S110 - an older core without the limit: the command gets its chance
            pass
    return run_orch(orch_bin, ["review", "list", "--answered", "--json"], root)


def load_review(root: Path, orch_bin: str | None) -> dict:
    """The Review page's data: what waits (`orch review list --json`) and what was decided
    (`orch review list --answered --json`). Empty lists when orch cannot say."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_cards = pool.submit(run_orch, orch_bin, ["review", "list", "--json"], root)
        f_done = pool.submit(_answered_newest, root, orch_bin)
        f_acc = pool.submit(run_orch, orch_bin, ["review", "accepted", "--json"], root)
    cards, done, acc = f_cards.result(), f_done.result(), f_acc.result()
    acc = acc.get("accepted") if isinstance(acc, dict) else None
    if isinstance(cards, dict):  # {workspace, cards}
        cards = cards.get("cards")
    if isinstance(done, dict):
        done = done.get("answered", done.get("entries"))
    return {
        "cards": [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else [],
        # newest first; the live state carries the newest ANSWERED_MAX only (ORCH-522: thousands at 10,000 tickets)
        "answered": [c for c in done if isinstance(c, dict)][:ANSWERED_MAX] if isinstance(done, list) else [],
        # Tickets the Reviewer accepted for the owner today (`orch review accepted --json`); [] when off or none.
        "accepted": [c for c in acc if isinstance(c, dict)] if isinstance(acc, list) else [],
    }


_KINDS: dict[str, list] = {}  # the link kinds of the last full build, per workspace


def _drop_addon_names(tickets: list[dict]) -> None:
    for t in tickets:
        for h in t.get("history") or []:
            if isinstance(h, dict):
                h.pop("addon", None)  # ORCH-1946 add-on lines: a snapshot does not name the add-on


def _shape_refs(root: Path, tickets: list[dict], with_settings: bool) -> None:
    try:
        from orch.refs import local_refs
    except ImportError:  # the core is not importable here: no local references
        local_refs = None
    for t in tickets:
        stored = t.get("refs", [])
        for n, r in enumerate(stored, 1):  # the stored number: what `orch ref list` and `orch ref rm` use
            if isinstance(r, dict):
                r["n"] = n
        t["refs"] = [r for r in stored if not (isinstance(r, dict) and r.get("local"))]
        if (
            with_settings and local_refs
        ):  # only the live local server: a snapshot is shared and must not carry local paths
            try:
                more = local_refs(root, t["id"])
            except (ValueError, TypeError, OSError):
                more = []
            more = [r for r in more if isinstance(r, dict)] if isinstance(more, list) else []
            t["refs"] += [{**r, "n": len(stored) + i} for i, r in enumerate(more, 1)]


def state_rev(state: dict) -> str:
    return hashlib.sha1(
        json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True).encode()
    ).hexdigest()[:12]


def ticket_id(root: Path, orch_bin: str | None, ref: str) -> str | None:
    """The ticket id for an id or a key (any case) the page names; None when no ticket has it."""
    if re.fullmatch(r"t_[a-z0-9]{6,16}", ref):
        return ref
    rows = _index_rows(root) if orch_bin == SELF else None
    if rows is None:
        got = run_orch(orch_bin, ["ticket", "show", ref, "--json"], root) if orch_bin else None
        return got["id"] if isinstance(got, dict) and isinstance(got.get("id"), str) else None
    up = ref.upper()
    return next((r["id"] for r in rows if str(r.get("key") or "").upper() == up), None)


def read_ticket(root: Path, orch_bin: str | None, tid: str, live: dict | None = None) -> dict | None:
    """One whole ticket as the page reads it (GET /api/ticket/<id>, ORCH-522): the ticket page asks for it when its
    live row is cut short or a finished ticket is not in the live state. None when there is no such ticket."""
    raw = (
        _show_here(root, tid)
        if orch_bin == SELF
        else run_orch(orch_bin, ["ticket", "show", tid, "--json"], root)
    )
    if not orch_bin:  # standalone: the file itself
        raw = (
            _load(root / ".orch" / "tickets" / f"{tid}.json")
            if re.fullmatch(r"t_[a-z0-9]{6,16}", tid)
            else None
        )
        if isinstance(raw, dict) and raw.get("status") == "done":
            raw["status"], raw["verdict_needed"] = "review", True
    if not (isinstance(raw, dict) and raw.get("general") is not True and _valid_ticket(raw)):
        return None
    t = _shape_ticket(root, orch_bin, raw, {}, from_file=not orch_bin)
    _mark_tickets(root, [t])
    add_spend(root, [t], background=True)
    _shape_refs(root, [t], True)
    add_link_views([t], _KINDS.get(str(root), []))
    if isinstance(live, dict) and live.get("id") == t["id"] and isinstance(live.get("children"), list):
        # its row in the live state already counts every part (from all rows at the last build): no scan of every
        # ticket file per page (with other requests running, that scan alone took half a second at 10,000)
        _add_parts([t], {t["id"]: live})
        return t
    rows = _index_rows(root) if orch_bin == SELF else None
    if rows is not None:
        _add_parts([t], _parts(rows))
    elif orch_bin:  # without the index: every ticket's row from the full list (slow, as before ORCH-521)
        _add_parts([t], _parts(_rows_of(_raw_list(root, orch_bin))))
    return t


def patch_ticket(root: Path, orch_bin: str | None, state: dict, tid: str) -> dict | None:
    """A click's answer (ORCH-102): the last full state with the clicked ticket read again, its run and the
    review cards fresh; everything else stays as it was until the background build replaces it. Before, every
    click waited for a full build (seconds with helpers running). None when the ticket cannot be read (the
    caller builds in full)."""
    raw = run_orch(orch_bin, ["ticket", "show", tid, "--json"], root)
    if not orch_bin:  # standalone: the file itself
        path = root / ".orch" / "tickets" / f"{tid}.json"
        raw = None if path.is_symlink() else _load(path)
        if isinstance(raw, dict) and raw.get("status") == "done":
            raw["status"], raw["verdict_needed"] = "review", True
    if not (isinstance(raw, dict) and raw.get("general") is not True and _valid_ticket(raw, tid)):
        return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_review = pool.submit(load_review, root, orch_bin)
        t = _shape_ticket(root, orch_bin, raw, {}, from_file=not orch_bin)
        _mark_tickets(root, [t])
        _shape_refs(root, [t], True)
        add_link_views([t], _KINDS.get(str(root), []))
        runs = load_runs(root, orch_bin, [t], fresh=True, some=True)
        review = f_review.result()
    out = dict(state)
    old = {x["id"]: x for x in state.get("tickets") or []}
    before = old.get(tid) or {}
    t.update(
        children=list(before.get("children") or []),
        parts_done=before.get("parts_done", 0),
        parts_total=before.get("parts_total", 0),
    )
    tickets = [t if x["id"] == tid else x for x in state.get("tickets") or []]
    if tid not in old:
        tickets.insert(0, t)
    parent = t.get("parent")
    if isinstance(parent, str) and parent in old:  # its parent counts done parts
        rows = _index_rows(root) if orch_bin == SELF else None
        if rows is not None:  # every part, finished ones too (the live rows hold only recent ones)
            done = _parts(rows).get(parent, {}).get("parts_done", 0)
        else:
            was = int(before.get("status") == "done") if before else 0
            done = old[parent].get("parts_done", 0) - was + int(t["status"] == "done")
        tickets = [{**x, "parts_done": max(0, done)} if x["id"] == parent else x for x in tickets]
    out["tickets"] = tickets
    # ORCH-1047: a question of this ticket that is no longer open (answered, taken back) leaves the needs list at
    # once; the cached list would bring an answered question back on Home until the background build runs, and a
    # click on it is refused ("q1 is already answered.").
    open_qs = {
        q.get("id") for q in raw.get("questions") or [] if isinstance(q, dict) and q.get("answer") is None
    }
    mine = f"core:q:{tid}:"
    out["needs"] = [
        n
        for n in state.get("needs") or []
        if not (
            isinstance(n, dict)
            and str(n.get("id", "")).startswith(mine)
            and n["id"][len(mine) :] not in open_qs
        )
    ]
    if orch_bin and any(
        q not in (before.get("questions") or [])
        for q in t.get("questions") or []
        if isinstance(q, dict) and q.get("answer") is None
    ):
        # A new or edited question must also reach Home's needs list, not just the open ticket.
        needs = run_orch(orch_bin, ["needs", "--json"], root)
        if isinstance(needs, list):
            out["needs"] = needs
    out["runs"] = {k: v for k, v in (state.get("runs") or {}).items() if k != tid}
    if runs.get(tid):
        out["runs"][tid] = runs[tid]
    add_warmth(root, [t], out["runs"])
    out["review"] = review
    out["counts"] = load_counts(
        tickets, out["runs"], root, out["needs"]
    )  # the clicked ticket changes the numbers at once too
    out["now"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["rev"] = state_rev(out)
    return out


def patch_settings(root: Path, orch_bin: str | None, state: dict, op: str) -> dict:
    """A Settings click's answer (ORCH-227): the last full state with the Settings values read again (and Mobile
    mode for a phone choice); everything else stays until the background build replaces it. Before, every choice
    waited for a full build and the page showed the old choice for 4 to 12 s."""
    out = dict(state)
    out["settings"] = load_settings(root, orch_bin)
    if op.startswith("mobile."):
        out["mobile_mode"] = mobile.load_mobile(root, orch_bin)
    out["now"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["rev"] = state_rev(out)
    return out


def load_state(
    root: Path,
    orch_bin: str | None = None,
    with_addons: bool = True,
    fresh: bool = False,
    with_settings: bool = False,
) -> dict:
    """with_addons=False (snapshots by default): no add-on tabs, no ticket rows, `ext` dropped from tickets.
    One look at the ticket files serves every read of this build (ORCH-1621)."""
    with _reuse_index():
        return _load_state(root, orch_bin, with_addons, fresh, with_settings)


def _load_state(root: Path, orch_bin, with_addons: bool, fresh: bool, with_settings: bool) -> dict:
    from .actions import actor, computer_user

    # The independent `orch ... --json` reads run side by side; .result() in the old order raises as before.
    with ThreadPoolExecutor(max_workers=6) as pool:
        # the live page holds open and recent tickets only (ORCH-522); a snapshot keeps every ticket
        f_tickets = pool.submit(load_live_tickets if with_settings else load_tickets, root, orch_bin)
        f_raw = pool.submit(run_orch, orch_bin, ["addon", "list", "--json"], root)
        f_needs = pool.submit(run_orch, orch_bin, ["needs", "--json"], root) if with_addons else None
        # the cards and decisions are for the live page only (a snapshot is shared and carries none)
        f_review = pool.submit(load_review, root, orch_bin) if with_settings else None
        f_general = pool.submit(load_general, root) if with_addons else None
        f_sessions = pool.submit(load_sessions, root) if with_settings else None
        f_chat = pool.submit(load_chat, root, orch_bin) if with_addons else None
        f_ticket_chats = pool.submit(load_ticket_chats, root, orch_bin) if with_addons else None
        f_services = pool.submit(load_services, root, orch_bin) if with_addons else None
        f_groups = pool.submit(mobile.load_groups, root, orch_bin) if with_addons else None
        f_mobile = pool.submit(mobile.load_mobile, root, orch_bin) if with_settings else None
        f_look = pool.submit(look.load_look, root, orch_bin, fresh) if with_settings else None
        f_settings = pool.submit(load_settings, root, orch_bin) if with_settings else None
    got = f_tickets.result()
    tickets, skipped = got[0], got[1]
    counts = got[2] if len(got) > 2 else ticket_counts(tickets)
    raw = f_raw.result()
    addons = load_addons(root, orch_bin, raw) if with_addons else []
    if not with_addons:
        for t in tickets:
            t.pop("ext", None)
        _drop_addon_names(tickets)
    else:
        add_spend(root, tickets, background=with_settings)
    _shape_refs(root, tickets, with_settings)
    kinds = link_kinds(raw) if with_addons else []
    if with_settings:
        _KINDS[str(root)] = kinds  # a click's answer shapes its ticket's links the same way
    add_link_views(tickets, kinds)  # snapshots: known sites only, no add-on names
    needs = f_needs.result() if f_needs else None
    general = f_general.result() if f_general else None
    chat = f_chat.result() if f_chat else None
    ticket_chats = f_ticket_chats.result() if f_ticket_chats else None
    services = f_services.result() if f_services else []
    sessions = f_sessions.result() if f_sessions else []
    runs = load_runs(root, orch_bin, tickets, fresh, extra=[x["id"] for x in sessions]) if with_addons else {}
    groups = f_groups.result() if f_groups else None
    mobile_mode = f_mobile.result() if f_mobile else None
    look_ = _with_own_needs(f_look.result() if f_look else None, needs)
    settings = f_settings.result() if f_settings else None
    state = {
        "workspace": root.name,
        "who": actor(root).removeprefix("human:"),
        "login": computer_user(),  # the computer's login name: old lines recorded under it are the person's own
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "me": _me(root) if with_settings else None,
        "people": people.load(root)
        if with_settings
        else None,  # the "You: ..." switch (live page only)  # who "You" is in a history line (the live page only)
        # human:pr_... -> the person's name (people list, ORCH-1161); live page only, never in a shared copy
        "person_names": person_names(root) if with_settings else None,
        "tickets": ticket_rows_view(tickets) if with_settings else tickets,
        # every ticket's count per status, finished ones too (the live rows above are open and recent only)
        "ticket_counts": counts,
        "skipped": skipped,
        "addons": addons,
        "general": general,  # snapshots carry no phone chat
        # Chat (former General): helper name, today's texts with cards, the strip counts, the History list.
        "chat": chat,
        # Chats page (team chat step 1): tickets with chat lines or an open question, newest first, unread counts
        "ticket_chats": ticket_chats,
        "needs": needs if isinstance(needs, list) else [],
        "review": f_review.result() if f_review else {"cards": [], "answered": [], "accepted": []},
        "services": services,  # snapshots name no add-on
        "runs": runs,
        "counts": load_counts(
            tickets, runs, root, needs if isinstance(needs, list) else None
        ),  # ORCH-476: the one source of every number the pages show
        # Sessions without a ticket (ORCH-364): empty helper, chat helper, plain terminal, Manager; live page only
        "sessions": shape_sessions(sessions, runs),
        # ORCH-818: the permission row of the Start choice and the pane header's mode; live page only
        "session_modes": load_session_modes(root, sessions) if with_settings else None,
        "groups": groups,  # group chats; snapshots carry none
        "mobile_mode": mobile_mode,  # the live page only, never a snapshot
        "look": look_,  # the live page only, never a snapshot
        "settings": settings,  # only the live local server: it holds the folder path
        # Home: the note after an automatic update (new version and what changed, or why it failed); live page only
        "auto_update_note": _auto_update_note() if with_settings else None,
        "update_check": _update_check() if with_settings else None,
        # Where this orch came from ('release' / 'development'): the top bar marks a development build; live page only
        "build": _build() if with_settings else None,
        # Home and Settings > Helper: what helpers need (tool logins, connections, keys); live page only
        "logins": load_logins(root) if with_settings else None,
        # Home: tickets waiting in line for a helper and why none starts now (ORCH-266); live page only
        "start_line": start_line(root) if with_settings else None,
    }
    add_warmth(root, tickets, state["runs"])
    state["rev"] = state_rev(state)
    return state


def _with_own_needs(look_: dict | None, needs) -> dict | None:
    """The workspace list of the look with this workspace's count from the state's own needs list: `orch needs`
    ran once for the state, not again for the list (ORCH-1621). A copy: the look is kept between builds."""
    if (
        not isinstance(look_, dict)
        or not isinstance(look_.get("workspaces"), list)
        or not isinstance(needs, list)
    ):
        return look_
    rows = [
        {**w, "needs": len(needs)} if isinstance(w, dict) and w.get("here") else w
        for w in look_["workspaces"]
    ]
    return {**look_, "workspaces": rows}


def load_logins(root: Path) -> dict | None:
    """The last check of every tool login, connection and key a helper needs here (orch.health, ORCH-45): states,
    end times and the tickets they stop, never a secret. Live page only; None when never checked."""
    try:
        from orch import health
    except ImportError:  # an older orch without the check: nothing to show
        return None
    try:
        doc = health.last(root)
    except Exception:  # noqa: BLE001  a broken result never breaks the page
        return None
    if not doc:
        return None
    keep = ("name", "label", "kind", "state", "ends_at", "helper", "chosen")
    items = []
    for r in doc["items"]:
        if not isinstance(r, dict) or r.get("state") not in health.STATES:
            continue
        row = {k: r.get(k) for k in keep}
        row["kind"] = row["kind"] if row["kind"] in ("login", "connection", "key", "tool") else "login"
        # the renew step (ORCH-46) adds these two: orch can start the tool's own sign-in / the key's name to replace
        if r.get("renew") is True:
            row["renew"] = True
        if isinstance(r.get("key"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", r["key"]):
            row["key"] = r["key"]
        # ORCH-48: what the person does to renew when orch cannot start the sign-in (plain text, one line)
        if isinstance(r.get("how"), str) and re.fullmatch(r"[^\x00-\x1f\x7f<>]{1,160}", r["how"]):
            row["how"] = r["how"]
        # ORCH-218: the terminal command that signs in again, shown with a Copy button (never run)
        sign_in = r.get("sign_in")
        if isinstance(sign_in, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._:=/@,'\"+-]{0,119}", sign_in):
            row["sign_in"] = sign_in
        # #1549: a workspace check file that waits for the person: what it runs and the content hash Approve sends
        if r.get("approve") in ("new", "changed", "broken"):
            row["approve"] = r["approve"]
            runs, short = r.get("runs"), r.get("hash")
            if (
                r["approve"] != "broken"
                and isinstance(runs, str)
                and re.fullmatch(r"[^\x00-\x1f\x7f]{1,400}", runs)
                and isinstance(short, str)
                and re.fullmatch(r"[0-9a-f]{32}", short)
            ):
                row["runs"], row["hash"] = runs, short
        row["stops"] = [
            {"id": t.get("id"), "key": t.get("key"), "title": t.get("title")}
            for t in (r.get("stops") or [])
            if isinstance(t, dict)
        ]
        items.append(row)
    return {"checked_at": doc.get("checked_at"), "items": items}


def _build() -> str | None:
    from . import update

    return update.build()


def start_line(root: Path) -> dict | None:
    """{"waiting": [ticket ids], "why": plain reason or None, "limit": n or None}, or None when nothing waits."""
    try:
        from orch import runs_live

        return runs_live.line_status(root)
    except Exception:  # noqa: BLE001 - an older orch or an unreadable line: Home simply shows no line
        return None


def _auto_update_note() -> dict | None:
    from . import update

    return update.auto_note()


def _update_check() -> dict | None:
    from . import update

    return update.check_card()


def publish_connected(root: Path, orch_bin: str | None) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    if not isinstance(rows, list) or not any(
        isinstance(r, dict) and r.get("name") == "publish" and r.get("active") is True for r in rows
    ):
        return False
    who = run_orch(orch_bin, ["publish", "whoami", "--json"], root)
    return isinstance(who, dict) and isinstance(who.get("id"), str) and bool(who["id"]) and "error" not in who


def load_links(root: Path, orch_bin: str | None) -> dict:
    if not publish_connected(root, orch_bin):
        return {"links": []}
    raw = run_orch(orch_bin, ["publish", "list", "--quick", "--json"], root)
    if not isinstance(raw, dict):  # the CLI gave nothing at all: say so, never "no links"
        return {"links": [], "unreachable": True}
    files = raw.get("files", []) if isinstance(raw, dict) else []
    # The server's file list carries no link: rebuild it here from the saved publish address, the file id and
    # the key saved on this computer (publish list merges it in). The key is never sent to the server.
    # Never an address the server supplies: a compromised server could steer copied links (with the key) to itself.
    saved = _load(root / ".orch" / "secrets" / "publish.json")
    base = str(saved.get("url") or "").rstrip("/") if isinstance(saved, dict) else ""
    if not re.fullmatch(r"https?://[A-Za-z0-9.:\[\]-]+(/[A-Za-z0-9._~-]+)*", base):
        base = ""
    links = []
    for f in files if isinstance(files, list) else []:
        if (
            not isinstance(f, dict)
            or not isinstance(f.get("id"), str)
            or not re.fullmatch(r"f_[a-z0-9]+", f["id"])
        ):
            continue
        expires = f.get("expires_at")
        try:
            when = datetime.fromisoformat(expires)
            expired = (when if when.tzinfo else when.replace(tzinfo=UTC)) <= datetime.now(UTC)
        except (ValueError, TypeError, AttributeError):
            expired = False
        key, url = f.get("key"), f"{base}/f/{f['id']}" if base else None
        ok = (
            isinstance(key, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key)
            and isinstance(url, str)
            and re.fullmatch(r"https?://[A-Za-z0-9.:\[\]-]+/[!-~]*", url.split("#", 1)[0])
        )
        link = url.split("#", 1)[0] + "#k=" + key if ok else None
        links.append(
            {
                "id": f["id"],
                "name": f.get("name"),
                "size": f.get("size"),
                "expires_at": expires,
                "expired": expired,
                "link": link,
                "copy": link is not None,
            }
        )
    # publish gave no answer: these rows are this computer's own record (the page greys out share and stop)
    return {"links": links, **({"unreachable": True} if raw.get("unreachable") is True else {})}


# Workspace DM reads use the same CLI boundary as Chat History.
# The open Chat page asks every 2 s. A poll must not start an `orch` process each time (B1): the answer is kept while
# nothing a message arrives in has changed (the inbox, the stored threads) and for CHAT_TTL seconds at most.
CHAT_TTL = 30.0
_CHAT: dict[tuple, tuple[float, tuple, object]] = {}
_CHAT_LOCK = threading.Lock()


def _chat_fingerprint(root: Path) -> tuple:
    rows = []
    for folder in (root / ".orch" / "inbox", root / ".orch" / "chat" / "dm"):
        try:
            with os.scandir(folder) as it:
                for e in it:
                    if e.name.endswith(".json"):
                        st = e.stat(follow_symlinks=False)
                        rows.append((e.path, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    # who can be messaged changes when an add-on is turned on or off or a connection is made: the add-on list and
    # the connection files in .orch/secrets (time and size only, never read). Without them a contacts list read
    # before the connection stayed for CHAT_TTL and a ticket chat showed no + Add (ORCH-1652).
    paths = [root / ".orch" / "addons.json"]
    try:
        with os.scandir(root / ".orch" / "secrets") as it:
            paths += [Path(e.path) for e in it if e.name.endswith(".json")]
    except OSError:
        pass
    for path in paths:
        try:
            st = path.stat()
            rows.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(sorted(rows))


def _chat_cached(key: tuple, root: Path, build):
    fp = _chat_fingerprint(root)
    with _CHAT_LOCK:
        hit = _CHAT.get(key)
    if hit and hit[1] == fp and time.monotonic() - hit[0] < CHAT_TTL:
        return hit[2]
    data = build()
    # the fingerprint is taken before the read, so a message that lands meanwhile is picked up by the next poll
    if data is not None:
        with _CHAT_LOCK:
            _CHAT[key] = (time.monotonic(), fp, data)
            while len(_CHAT) > 64:
                _CHAT.pop(next(iter(_CHAT)))
    return data


def load_chat_contacts(root: Path, orch_bin: str | None) -> list | None:
    def build():
        # `chat sync` imports new workspace texts first and prints the contacts; if that cannot run (busy lock), read as is.
        data = run_orch(orch_bin, ["chat", "sync", "--json"], root)
        if not isinstance(data, list):
            data = run_orch(orch_bin, ["chat", "contacts", "--json"], root)
        return data if isinstance(data, list) else None

    return _chat_cached(("contacts", orch_bin, str(root)), root, build)


def load_chat_thread(root: Path, orch_bin: str | None, ws: str) -> dict | None:
    if not re.fullmatch(r"ws_[a-z0-9]{10}", ws):
        return None

    def build():
        data = run_orch(orch_bin, ["chat", "thread", ws, "--sync", "--json"], root)
        if not isinstance(data, dict):
            data = run_orch(orch_bin, ["chat", "thread", ws, "--json"], root)
        return data if isinstance(data, dict) else None

    return _chat_cached(("thread", orch_bin, str(root), ws), root, build)
