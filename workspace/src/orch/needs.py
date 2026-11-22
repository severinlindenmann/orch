"""`orch needs`: what waits for a person. One list for every surface (contracts/needs.schema.json).

Core rows come from tickets, runs and services alone: open questions, waits past their `until`, active
background add-ons that are not running, and work that stopped short (stuck.py: a pull request left open
after its checks passed, a helper idle at its prompt). An active add-on with `needs = true` adds rows through
`orch <name> needs --json`. The add-ons are asked side by side, while the core rows are made (ORCH-603):
an add-on with a saved answer gets FAST_BUDGET from the start, one without gets PULL_TIMEOUT. A late add-on
answers from its saved answer and one detached `orch needs --refresh-addon <name>` saves a fresh one for the
next call; saved rows come back with stale = true when the pull failed or the saved answer is older than
STALE_AFTER. So `orch needs` takes about as long as its core part, however many add-ons are on.
The core names no add-on.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, history, services, ticketindex, tickets
from orch.errors import Refused

PULL_TIMEOUT = 2  # the longest an add-on is waited for: first answer, background refresh
FAST_BUDGET = 0.6  # seconds from the start of needs: a later add-on with a saved answer answers from it
STALE_AFTER = 120  # a saved answer older than this is shown as not up to date
TONES = ("needs-you", "bad", "warn")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}:[A-Za-z0-9_.:-]{1,200}$")
KIND_RE = re.compile(r"^(question|overdue-wait|[a-z][a-z0-9-]{1,31}:[a-z][a-z0-9-]{1,31})$")
TIME_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
TID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")
OPEN = ("done", "dropped")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(v: str, n: int) -> str:
    v = " ".join(str(v).split()) or "-"
    return v if len(v) <= n else v[: n - 1] + "…"


def _asked_at(root: Path, t: dict, qid: str) -> str:
    for h in history.lines(root, t):
        if isinstance(h, dict) and h.get("text", "").startswith(f"Asked {qid},") and h.get("at"):
            return h["at"]
    return t.get("updated_at") or t.get("created_at") or _now()


def _bring_back_row(tid: str, title: str, back: dict, now: str) -> dict:
    """The text comes from the fixed reason table by CODE (unknown code: the generic text); never the free
    `reason`/`at` of a record (the pending file is unsigned and agent-writable)."""
    from orch.worktrees import BRING_BACK_REASONS

    code = back.get("reason_code")
    reason = BRING_BACK_REASONS.get(
        code if isinstance(code, str) else "waiting", BRING_BACK_REASONS["waiting"]
    )
    return {
        "id": f"core:bring-back:{tid}",
        "source": "core",
        "kind": "copies:bring-back",
        "ticket": tid,
        "title": _clip(f"Your work from {title} is on its own branch", 200),
        "text": "Bring it back into your project?",
        "reason": reason,
        "tone": "needs-you",
        "since": now,
        "cli": f"orch copy approve {tid}",
        "button": "Review and bring back",
    }


def _may_need(r: dict, live: set[str]) -> bool:
    """True when the ticket of index row r could give a row below: a bring-back that waits, or an open ticket
    with an open question, a wait with an end time, a step that keeps failing (stuck.py), a ticket in Review
    (stuck.py) or a helper record (an idle helper, stuck.py). Every other ticket gives none, so its file is
    not read."""
    if r.get("bring_back"):
        return True
    if r.get("status") in OPEN:
        return False
    w = r.get("waiting_on") or {}
    return bool(
        r.get("questions_open")
        or r.get("failing")  # a step that keeps failing (stuck.py)
        or isinstance(w.get("until"), str)
        or r.get("status") == "review"
        or r["id"] in live
    )


def _candidates(root: Path) -> list[dict]:
    """The tickets core_rows looks at, read in full, in list_all order: only those the index says may
    need a person (ORCH-521: with 10,000 tickets reading every file took seconds)."""
    try:
        live = {
            e.name[:-5] for e in os.scandir(root / ".orch" / "run" / "tickets") if e.name.endswith(".json")
        }
    except OSError:
        live = set()
    out = []
    for r in ticketindex.rows(root):
        if not _may_need(r, live):
            continue
        try:
            t = tickets.load(root, r["id"])
        except (Refused, OSError):
            continue  # a listing never stalls on a bad file
        if not tickets.is_hidden(t):
            out.append(t)
    return out


def core_rows(root: Path, now: str | None = None) -> list[dict]:
    now = now or _now()
    rows = []
    seen = set()
    shown = history.shown_json(root, _candidates(root))  # every person field as proven here
    for t in shown:
        seen.add(t["id"])
        back = (t.get("work") or {}).get("bring_back") or {}
        if back.get("state") == "waiting":
            rows.append(_bring_back_row(t["id"], t.get("title", t["id"]), back, now))
        if t.get("status") in OPEN or not isinstance(t.get("id"), str):
            continue
        title = _clip(t.get("title", t["id"]), 200)
        for q in t.get("questions") or []:
            if q.get("answer") is not None:
                continue
            rows.append(
                {
                    "id": f"core:q:{t['id']}:{q['id']}",
                    "source": "core",
                    "kind": q.get("kind") or "question",
                    "ticket": t["id"],
                    "title": title,
                    "text": _clip(q.get("text", ""), 500),
                    "tone": "needs-you",
                    "since": _asked_at(root, t, q["id"]),
                    "answer": {
                        "question": q["id"],
                        "options": list(q.get("options") or []),
                        "labels": _option_labels(q),
                        "recommended": q.get("recommended"),
                        "digest": tickets.question_digest(q),  # the question as shown: bound into the proof
                    },
                }
            )
        w = t.get("waiting_on") or {}
        until = w.get("until")
        if isinstance(until, str) and until < now:
            if w.get("kind") == "time":
                text = "Wake time passed and no helper started. Continue starts it."
                cli = f"orch run start {t['id']}"
            else:
                text = f"Waiting on {w.get('kind')} {w.get('ref', '')}".strip() + f", past {until}"
                cli = None
            row = {
                "id": f"core:wait:{t['id']}",
                "source": "core",
                "kind": "overdue-wait",
                "ticket": t["id"],
                "title": title,
                "text": _clip(text, 500),
                "tone": "warn",
                "since": until,
            }
            if cli:
                row["cli"] = cli
            rows.append(row)
    from orch import worktrees

    for item in worktrees._pending(root)["kept"]:
        if item.get("bring_back") and item["ticket"] not in seen:
            rows.append(_bring_back_row(item["ticket"], item["ticket"], item, now))
    from orch import stuck

    rows += stuck.rows(root, shown)  # a pull request left open, a helper idle at its prompt
    from orch import health

    health.soon(root)  # tool logins: a stale result is checked again in the background (ORCH-44)
    from orch import doctorpass

    doctorpass.soon(root)  # the machine's health checks, when set up here and due (ORCH-104)
    for r in services.workspace_rows(root):
        if not r["running"] and not r.get("idle"):
            rows.append(
                {
                    "id": f"core:down:{r['name']}",
                    "source": "core",
                    "kind": "addon:not-running",
                    "ticket": None,
                    "title": r["name"],
                    "text": f"{r['name']} is not running (last seen {services.ago(r['last_seen'])})",
                    "tone": "bad",
                    "since": r["last_seen"] or now,
                    "cli": "orch start",
                }
            )
    return rows


# ---------------------------------------------------------------- add-on rows


def _cache_path(root: Path, name: str) -> Path:
    return root / ".orch" / "run" / "needs-cache" / f"{name}.json"


def _valid_row(name: str, r: object) -> dict | None:
    """A row from an add-on: the right shape, its own source, ids under its own name. Else dropped."""
    if not isinstance(r, dict):
        return None
    try:
        ok = (
            r["source"] == name
            and isinstance(r["id"], str)
            and ID_RE.match(r["id"])
            and r["id"].startswith(name + ":")
            and isinstance(r["kind"], str)
            and KIND_RE.match(r["kind"])
            and (r["ticket"] is None or (isinstance(r["ticket"], str) and TID_RE.match(r["ticket"])))
            and isinstance(r["title"], str)
            and 0 < len(r["title"]) <= 200
            and isinstance(r["text"], str)
            and 0 < len(r["text"]) <= 500
            and r["tone"] in TONES
            and isinstance(r["since"], str)
            and TIME_RE.match(r["since"])
        )
    except KeyError:
        return None
    if not ok:
        return None
    out = {k: v for k, v in r.items() if k != "stale"}
    out["stale"] = False
    return out


def _read_cache(root: Path, name: str) -> list[dict] | None:
    try:
        data = json.loads(_cache_path(root, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [r for r in (_valid_row(name, x) for x in data) if r]


def _write_cache(root: Path, name: str, rows: list[dict]) -> None:
    p = _cache_path(root, name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f)
        os.replace(tmp, p)
    except OSError:
        pass


def _argv(m: dict) -> list[str]:
    return [sys.executable, "-P", "-m", m["run"], "needs", "--json"]


def _parse(name: str, out: str) -> list[dict] | None:
    if len(out) > 256 * 1024:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [x for x in (_valid_row(name, y) for y in data) if x]


class _Pull(threading.Thread):
    """One add-on's `needs --json` in its own child, read by a daemon thread, so all add-ons and the core
    rows are made at the same time. `rows` is None until a good answer came; `stop()` ends a late child."""

    def __init__(self, root: Path, name: str, m: dict):
        super().__init__(daemon=True, name=f"needs-{name}")
        self.root, self.name_, self.m = root, name, m
        self.rows: list[dict] | None = None
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stopped = False

    def run(self) -> None:
        env = {
            **os.environ,
            "ORCH_ADDON": self.name_,
            "ORCH_ROOT": str(self.root),
            "ORCH_BIN": addons.orch_bin(),
            "PYTHONIOENCODING": "utf-8",  # read as UTF-8 below, whatever the system's code page
        }
        own_group = (
            {"creationflags": 0x00000200}  # CREATE_NEW_PROCESS_GROUP: stopped as a tree (taskkill /T)
            if os.name == "nt"
            else {"start_new_session": True}  # its own process group: stopped with what it started
        )
        try:
            with self._lock:
                if self._stopped:
                    return
                self.proc = subprocess.Popen(
                    _argv(self.m),
                    cwd=self.root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **own_group,
                )
            out, _ = self.proc.communicate(timeout=PULL_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.stop()
            return
        except (subprocess.SubprocessError, OSError, ValueError):
            return
        if self.proc.returncode == 0:
            self.rows = _parse(self.name_, out)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            p = self.proc
        if p is not None and p.poll() is None:
            _kill_tree(p)


def _kill_tree(p: subprocess.Popen) -> None:
    """Stop a late add-on and what it started (Factory runs `orch ticket list`): its own process group on
    POSIX, taskkill /T on Windows. Only the child this process started; never raises."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        else:
            import signal

            os.killpg(p.pid, signal.SIGKILL)  # start_new_session: the group id is the child's pid
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
        p.wait(timeout=1)
    except (OSError, subprocess.SubprocessError):
        pass


def _pull(root: Path, name: str, m: dict) -> list[dict] | None:
    """One add-on's rows, waited for up to PULL_TIMEOUT (the background refresh)."""
    p = _Pull(root, name, m)
    p.start()
    p.join(PULL_TIMEOUT + 1)
    if p.is_alive():
        p.stop()
        return None
    return p.rows


def _refresh_mark(root: Path, name: str) -> Path:
    return _cache_path(root, name).with_suffix(".refreshing")


def _spawn_refresh(root: Path, name: str) -> bool:
    """Start one detached `orch needs --refresh-addon <name>` that saves a fresh answer, at most one per
    add-on at a time (the mark is made atomically; one older than PULL_TIMEOUT + 3 s was left behind and is
    taken over). Never raises, never waits."""
    try:
        if os.environ.get("ORCH_NO_NEEDS_REFRESH"):
            return False
        mark = _refresh_mark(root, name)
        mark.parent.mkdir(parents=True, exist_ok=True)
        try:
            if time.time() - mark.stat().st_mtime >= PULL_TIMEOUT + 3:
                mark.unlink()  # left by a refresh that never finished
        except OSError:
            pass
        try:
            os.close(os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # one caller wins
        except FileExistsError:
            return False
        from orch import procs

        subprocess.Popen(
            procs.orch_python_argv("needs", "--refresh-addon", name),
            cwd=Path(os.path.realpath(tempfile.gettempdir())),
            env={**os.environ, "ORCH_ROOT": str(root)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **procs.background_popen_kwargs(),
        )
        return True
    except Exception:  # noqa: BLE001  a refresh that cannot start never holds up needs
        return False


def refresh(root: Path, name: str) -> bool:
    """`orch needs --refresh-addon <name>`: ask that add-on once and save a good answer. True when saved."""
    try:
        m = addons.active_manifests(root).get(name)
        if not m or not m.get("needs"):
            return False
        rows = _pull(root, name, m)
        if rows is None:
            return False
        _write_cache(root, name, rows)
        return True
    finally:
        try:
            _refresh_mark(root, name).unlink()
        except OSError:
            pass


def _cache_age(root: Path, name: str) -> float | None:
    try:
        return time.time() - _cache_path(root, name).stat().st_mtime
    except OSError:
        return None


def _unavailable(name: str) -> list[dict]:
    return [
        {
            "id": f"{name}:needs-unavailable",
            "source": name,
            "kind": f"{name}:needs",
            "ticket": None,
            "title": name,
            "text": f"{name} did not answer, so what it needs from you may be missing.",
            "tone": "warn",
            "since": _now(),
            "stale": True,
        }
    ]


def _settle(root: Path, name: str, p: _Pull, deadline: float | None) -> list[dict]:
    """The rows of one started pull: its answer when it came by the deadline (saved for next time), else the
    saved answer (a late one starts a background refresh), else one warn row."""
    if deadline is not None:
        p.join(max(0.0, deadline - time.monotonic()))
    late = p.is_alive()
    if late:
        p.stop()
    elif p.rows is not None:
        _write_cache(root, name, p.rows)
        return p.rows
    cached = _read_cache(root, name)
    if cached is None:
        return _unavailable(name)
    if late:
        _spawn_refresh(root, name)
        age = _cache_age(root, name)
        stale = age is None or age > STALE_AFTER
    else:
        stale = True  # the add-on answered, but not with good rows
    return [{**r, "stale": stale} for r in cached]


def addon_rows(root: Path, name: str, m: dict) -> list[dict]:
    """One add-on's rows on their own (waits up to PULL_TIMEOUT)."""
    p = _Pull(root, name, m)
    p.start()
    return _settle(root, name, p, time.monotonic() + PULL_TIMEOUT + 1)


def _option_labels(q: dict) -> list[str]:
    """One short line per option: "A Title" when a card option has its own title."""
    pv = (q.get("card") or {}).get("preview") or {}
    titles = {o.get("id"): o.get("title") for o in pv.get("options") or [] if isinstance(o, dict)}
    out = []
    for o in q.get("options") or []:
        t = titles.get(o)
        out.append(f"{o} {_clip(t, 40)}" if t and t != o else str(o))
    return out


def needs(root: Path) -> list[dict]:
    start = time.monotonic()
    pulls = {}
    for name, m in sorted(addons.active_manifests(root).items()):
        if m.get("needs"):
            pulls[name] = _Pull(root, name, m)
            pulls[name].start()  # side by side, while the core rows are made
    try:
        core = core_rows(root)
    except BaseException:
        for p in pulls.values():
            p.stop()
        raise
    seen = {r["id"] for r in core}
    answered = {(r["ticket"], r["answer"]["question"]) for r in core if "answer" in r}
    rows = list(core)
    for name, p in pulls.items():
        budget = FAST_BUDGET if _cache_path(root, name).is_file() else PULL_TIMEOUT + 1
        for r in _settle(root, name, p, start + budget):
            ans = r.get("answer")
            same_q = isinstance(ans, dict) and (r["ticket"], ans.get("question")) in answered
            if r["id"] in seen or same_q:
                continue
            seen.add(r["id"])
            rows.append(r)
    order = {t: i for i, t in enumerate(TONES)}
    rows.sort(key=lambda r: (order[r["tone"]], r["since"], r["id"]))
    return rows
