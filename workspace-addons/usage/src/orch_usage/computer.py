"""Usage is kept once per computer user (ORCH-943): the Claude and Codex logins belong to the computer user, not to a
workspace, so two workspaces that each switched by their own rules swapped the account back and forth.

Folder: `<orch tool home>/usage/` (the same home as running.json; ORCH_HOME in tests). It holds what Usage kept per
workspace before (accounts.json, history.jsonl, settings.json, switching.json, share.json, starts.json) plus:

- `workspaces.json` {"<workspace path>": {"name", "seen"}}: every workspace whose Usage looked lately.
- `switcher.json` {"workspace", "name", "since", "by"}: the one workspace whose Usage loop looks and switches.
  Its loop holds an OS lock on `switcher.lock` while it runs; a lock nobody holds means that loop is gone, so a
  dead owner frees it at once (no pid or clock guess). A person moves it with take_over(); a helper never does.
- `switch.lock`: held around one switch, with the owner checked again inside it, so a take-over can never land
  in the middle of a switch.
- `switched.jsonl`: one line per switch {"n", "at", "workspace", "name", "from", "to"}, numbered; tend in every
  workspace (with or without Usage) carries its helpers on when it sees a number it did not act on yet.

A workspace's old `.orch/addons/usage/` files are taken over once (import_local); they stay where they were, with
`moved.json` next to them saying where they went. Without orch (the add-on alone) the workspace folder is used.
Only labels, numbers and times: never a login, token, key or address.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The words people see (owner's pick on ORCH-943, card q2). {name} = the workspace that switches.
WORDS = {
    "title": "{name} switches the accounts on this computer",
    "text": "This workspace follows: same accounts, limits and order, and its helpers go on after each switch.",
    "follow": "Follow",
    "take": "Take over",
    "tag": "Switched by {name}",
    "switched": "Account switched by {name}",
}
SHARED_FILES = (
    "accounts.json",
    "history.jsonl",
    "settings.json",
    "switching.json",
    "share.json",
    "starts.json",
)
MOVED = "moved.json"
TAKE_OVER_GRACE_SECONDS = 120  # after a take-over, only the new owner may pick up the free lock this long
SEEN_DAYS = 14  # a workspace whose Usage did not look for this long is left out of the list


def local_dir(root: Path) -> Path:
    """The workspace's own Usage folder (before ORCH-943 everything was here)."""
    return root / ".orch" / "addons" / "usage"


def shared_dir(root: Path | None = None) -> Path | None:
    """`<tool home>/usage`, or None when orch cannot say where its home is (the add-on alone, or a refused home)."""
    if os.environ.get("ORCH_USAGE_LOCAL") == "1":  # tests of the old single-workspace layout
        return None
    try:
        from orch import addons
    except Exception:  # noqa: BLE001 - no orch core: the add-on keeps its files in the workspace
        return None
    try:
        return addons.home(root) / "usage"
    except Exception:  # noqa: BLE001 - a refused home (strict tests without ORCH_HOME): the workspace folder
        return None


def label(root: Path) -> str:
    """The workspace's name as people see it: [workspace] name, else the folder name."""
    try:
        from orch import config

        n = config.workspace_name(root)
    except Exception:  # noqa: BLE001
        n = None
    return n or Path(root).resolve().name


def key(root: Path) -> str:
    return str(Path(root).resolve())


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- OS locks


def _try_lock(f) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()  # POSIX: closing the file lets go of the flock


def _open_lock(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    return open(p, "a+b")


@contextmanager
def held(
    p: Path, wait: float = 10.0, busy: str = "Usage is busy saving another change. Try again in a moment."
):
    """Hold the OS lock on p for the block. A crashed holder lets go by itself (the OS drops its locks)."""
    from .store import Refused

    f = _open_lock(p)
    deadline = time.monotonic() + wait
    while not _try_lock(f):
        if time.monotonic() > deadline:
            f.close()
            raise Refused(busy)
        time.sleep(0.05)
    try:
        yield
    finally:
        _unlock(f)


# ---------------------------------------------------------------- taking over a workspace's old files


def _merge_history(old: Path, new: Path, name: str) -> None:
    rows = []
    for p, mark in ((new, None), (old, name)):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                if mark and not r.get("workspace"):
                    r["workspace"] = mark
                rows.append(r)
    rows.sort(key=lambda r: str(r.get("at") or ""))  # stable: same second keeps file order
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    fd, tmp = tempfile.mkstemp(dir=new.parent, prefix=".history.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, new)


def _merge_accounts(old: dict, new: dict, name: str) -> tuple[dict, list[str]]:
    """Accounts already kept for the computer win; accounts only this workspace had are added at the end.
    Returns (accounts file, plain notes of what was not taken)."""
    accounts = [a for a in new.get("accounts") or [] if isinstance(a, dict)]
    notes = []
    by_source = {
        (a.get("source") or {}).get("key") or a.get("label"): a for a in accounts if isinstance(a, dict)
    }
    ids = {a.get("id") for a in accounts if isinstance(a, dict)}
    from .store import _check_account

    for a in old.get("accounts") or []:
        if not isinstance(a, dict) or not _check_account(a):
            continue  # a row Usage would not read itself is not taken over
        k = (a.get("source") or {}).get("key") or a.get("label")
        mine = by_source.get(k)
        if mine is not None:
            if json.dumps(mine.get("rule"), sort_keys=True) != json.dumps(a.get("rule"), sort_keys=True):
                notes.append(f"{a.get('label')}: kept the rule already set for this computer, not {name}'s")
            continue
        a = dict(a)
        if a.get("id") in ids:
            from .store import new_id

            a["id"] = new_id(accounts)
        a["order"] = len(accounts) + 1
        accounts.append(a)
        ids.add(a["id"])
    return {**new, "accounts": accounts}, notes


def import_local(root: Path, shared: Path) -> bool:
    """Take this workspace's old Usage files into the computer's folder once (the caller holds the store lock).
    The old files stay as they were (a backup), `moved.json` marks them as taken. True when something moved."""
    loc = local_dir(root)
    if not loc.is_dir() or (loc / MOVED).exists() or loc.resolve() == shared.resolve():
        return False
    present = [n for n in SHARED_FILES if (loc / n).is_file() and not (loc / n).is_symlink()]
    if not present:
        return False
    shared.mkdir(parents=True, exist_ok=True)
    name = label(root)
    notes: list[str] = []
    for n in present:
        src, dst = loc / n, shared / n
        if n == "history.jsonl":
            _merge_history(src, dst, name)
        elif not dst.exists() and n == "accounts.json":
            from .store import SCHEMA

            merged, notes = _merge_accounts(_read(src), {"schema": SCHEMA, "accounts": []}, name)
            _write(dst, merged)
        elif not dst.exists():
            shutil.copyfile(src, dst)
        elif n == "accounts.json":
            merged, notes = _merge_accounts(_read(src), _read(dst), name)
            _write(dst, merged)
        elif n == "starts.json":
            a, b = _read(src), _read(dst)
            starts = {**(a.get("starts") or {}), **(b.get("starts") or {})}
            if starts:
                _write(dst, {**b, "starts": starts})
        elif n == "settings.json":
            a, b = _read(src), _read(dst)
            if "switching" not in b and "switching" in a:
                _write(dst, {**b, "switching": a["switching"]})
        # share.json and switching.json: the computer's own stay (one share, one loop memory)
    line = {
        "at": now(),
        "who": "usage",
        "what": f"took over {name}'s Usage settings for this computer",
        "account": None,
        "label": "Usage",
        "before": None,
        "after": "; ".join(notes) or None,
        "workspace": name,
    }
    with open(shared / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    _write(loc / MOVED, {"to": str(shared), "at": now(), "files": present})
    return True


# ---------------------------------------------------------------- workspaces that use Usage here


def note_workspace(root: Path, shared: Path) -> None:
    """This workspace's Usage looked now (for the split per workspace and the carry-on list)."""
    p = shared / "workspaces.json"
    with held(shared / ".workspaces.lock"):
        d = _read(p)
        k = key(root)
        prev = d.get(k) if isinstance(d.get(k), dict) else {}
        stamp = now()
        if prev.get("seen", "")[:15] == stamp[:15] and prev.get("name") == label(root):
            return  # once per ten minutes is enough
        d[k] = {"name": label(root), "seen": stamp}
        _write(p, d)


def workspaces(shared: Path, at: datetime | None = None) -> dict[str, dict]:
    at = at or datetime.now(UTC)
    out = {}
    for k, v in _read(shared / "workspaces.json").items():
        try:
            if isinstance(v, dict) and at - _when(v["seen"]) < timedelta(days=SEEN_DAYS):
                out[k] = v
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _when(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# ---------------------------------------------------------------- the one switcher (lease)


class Switcher:
    """The lease of one Usage loop. hold() once per look: True while this workspace is the switcher."""

    def __init__(self, root: Path, shared: Path):
        self.root, self.shared = Path(root), shared
        self._f = None

    @property
    def mine(self) -> bool:
        return self._f is not None

    def owner(self) -> dict:
        return _read(self.shared / "switcher.json")

    def hold(self) -> bool:
        me = key(self.root)
        cur = self.owner()
        if self._f is not None:
            if cur.get("workspace") == me:
                return True
            self.release()  # a person moved switching to another workspace: let go at once
            return False
        f = _open_lock(self.shared / "switcher.lock")
        if not _try_lock(f):
            f.close()
            return False  # another workspace's loop holds it
        # the lock was free: its last holder is gone (or let go after a take-over). Decide and write under the
        # switch lock, so a person's take-over at the same moment is never overwritten.
        try:
            with held(self.shared / "switch.lock", wait=5):
                cur = self.owner()
                if cur.get("workspace") not in (None, me) and just_taken(cur, self.shared):
                    _unlock(f)
                    return False  # a person just gave it to that workspace: it picks the lock up itself
                self._f = f
                if cur.get("workspace") != me:
                    prev = cur.get("name")
                    _write(
                        self.shared / "switcher.json",
                        {"workspace": me, "name": label(self.root), "since": now()},
                    )
                    _history(
                        self.shared,
                        self.root,
                        f"{label(self.root)} switches the accounts now"
                        + (f" ({prev} stopped)" if prev and not cur.get("taken") else ""),
                    )
        except Exception:
            if self._f is None:
                _unlock(f)
            raise
        return True

    def release(self) -> None:
        if self._f is not None:
            _unlock(self._f)
            self._f = None


def just_taken(cur: dict, shared: Path) -> bool:
    """A person moved switching to cur["workspace"] within the grace time, and that workspace's Usage is known."""
    if not cur.get("taken"):
        return False
    try:
        fresh = datetime.now(UTC) - _when(cur["since"]) < timedelta(seconds=TAKE_OVER_GRACE_SECONDS)
    except (KeyError, TypeError, ValueError):
        return False
    return fresh and cur.get("workspace") in workspaces(shared)


def owner(shared: Path) -> dict:
    """{"workspace", "name", "since", "running": bool}: who switches; running = its loop holds the lock now."""
    cur = _read(shared / "switcher.json")
    if not cur:
        return {}
    f = _open_lock(shared / "switcher.lock")
    free = _try_lock(f)
    _unlock(f) if free else f.close()
    return {**cur, "running": not free}


def take_over(root: Path, shared: Path, who: str) -> bool:
    """A person moves switching to this workspace. Waits for a switch in progress; the old owner's loop lets go on
    its next look. True when it changed. Refused for a helper (agent:...)."""
    from .store import Refused

    if not who.startswith("human:"):
        raise Refused("Only a person can move account switching to another workspace.")
    me = key(root)
    with held(shared / "switch.lock", wait=90, busy="A switch is running. Try again in a minute."):
        cur = _read(shared / "switcher.json")
        if cur.get("workspace") == me:
            return False
        _write(
            shared / "switcher.json",
            {"workspace": me, "name": label(root), "since": now(), "taken": True, "by": who},
        )
        _history(
            shared, root, f"{label(root)} took over switching from {cur.get('name') or 'no workspace'}", who
        )
    return True


def _history(shared: Path, root: Path, what: str, who: str = "usage") -> None:
    line = {
        "at": now(),
        "who": who,
        "what": what,
        "account": None,
        "label": "Usage",
        "before": None,
        "after": None,
        "workspace": label(root),
    }
    shared.mkdir(parents=True, exist_ok=True)
    with open(shared / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def words(name: str) -> dict:
    return {k: v.replace("{name}", name) for k, v in WORDS.items()}


def followed(root: Path) -> str | None:
    """The switcher workspace this workspace said Follow to (its notice stays small), else None."""
    v = _read(local_dir(root) / "follow.json").get("workspace")
    return v if isinstance(v, str) else None


def follow(root: Path, shared: Path, who: str) -> bool:
    """Follow: keep switching where it is and show only the small line. True when it changed."""
    o = owner(shared)
    if not o.get("workspace") or o["workspace"] == key(root):
        from .store import Refused

        raise Refused("This workspace switches the accounts itself; there is nothing to follow.")
    if followed(root) == o["workspace"]:
        return False
    _write(local_dir(root) / "follow.json", {"workspace": o["workspace"], "at": now(), "by": who})
    return True


def view(root: Path, shared: Path | None) -> dict | None:
    """What the page and `orch usage status` say about the switcher; None without a computer folder."""
    if shared is None:
        return None
    o = owner(shared)
    if not o.get("workspace"):
        return {"mine": False, "running": False, "name": None, "followed": False}
    mine = o["workspace"] == key(root)
    out = {
        "mine": mine,
        "running": bool(o.get("running")),
        "name": o.get("name"),
        "since": o.get("since"),
        "followed": followed(root) == o["workspace"],
        "workspaces": sorted(v.get("name") or k for k, v in workspaces(shared).items()),
    }
    if not mine:
        out["words"] = words(o.get("name") or "another workspace")
    return out


# ---------------------------------------------------------------- switch events (for the carry-on)


def note_switch(shared: Path, root: Path, before: str | None, after: str) -> int:
    """One numbered line per switch (the caller holds switch.lock). Returns its number."""
    p = shared / "switched.jsonl"
    last = last_switch(shared)
    n = (last.get("n") or 0) + 1 if last else 1
    row = {"n": n, "at": now(), "workspace": key(root), "name": label(root), "from": before, "to": after}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return n


def last_switch(shared: Path) -> dict:
    try:
        with open(shared / "switched.jsonl", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(tail):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("n"), int):
            return r
    return {}
