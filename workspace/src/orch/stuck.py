"""Work that stopped short of its last step, as rows for `orch needs` (read-only):

- a ticket in Review whose pull request is open with every check passed, and no helper working on it
  (the helper left without merging);
- a live helper idle at its prompt with nothing running for IDLE_MINUTES, on a ticket that is not finished;
- a stuck ticket (ORCH-426), listed whether or not the ticket needs a person's review: a helper waiting on a
  person's OK on its screen (a permission) for PERMISSION_MINUTES, a step whose last FAILED_RUNS recorded
  checks failed, and a ticket in Review the Reviewer left for the person (it was not sure). STUCK_KINDS; the
  same rows go to the phone (phone_stuck.py).

GitHub is never asked while a command waits: `orch needs` reads the last look from a small file and, when
that is older than CHECK_EVERY, starts one detached look (`orch needs --look-at-pulls`). No gh, no login or
no network: no row, never an error.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from orch import ghmerge, runs, runwatch

IDLE_MINUTES = 10
PERMISSION_MINUTES = 2  # a permission prompt this long with nobody answering it: stuck
FAILED_RUNS = 2  # recorded checks in a row that failed on one step: stuck
STUCK_KINDS = ("helper:permission", "helper:failing", "reviewer:unsure")
CHECK_EVERY = 180  # seconds between two looks at one pull request
ASK_EVERY = 30  # seconds between two detached looks
MAX_PULLS = 10  # pull requests per look
FINISHED = ("review", "done", "dropped")
GONE = ("merged", "closed", "not found")
UNMERGED = "The pull request passed its checks but was not merged, and no helper is working on it."


def _cache_path(root: Path) -> Path:
    return root / ".orch" / "run" / "pull-checks.json"


def _read(root: Path) -> dict:
    try:
        data = json.loads(_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("pulls", {}), dict) else {}


def _write(root: Path, data: dict) -> None:
    p = _cache_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    except OSError:
        pass


def open_pulls(ticket: dict) -> list[str]:
    """The ticket's GitHub pull request references not recorded as merged or closed."""
    out = []
    for r in ticket.get("refs") or []:
        url = r.get("url") if isinstance(r, dict) else None
        if ghmerge.is_pr_url(url) and (r.get("status") or "") not in GONE and url not in out:
            out.append(url)
    return out


def finish_hint(ticket: dict) -> str | None:
    """The next step for a helper that sends a ticket to Review while its pull request is not recorded as
    merged or closed. A hint only: the move itself always works."""
    pulls = open_pulls(ticket) if ticket.get("status") == "review" else []
    if not pulls:
        return None
    key = ticket.get("key") or ticket["id"]
    return (
        f"the pull request is still open ({pulls[0]}). If the ticket says to merge it once its checks pass, "
        f"wait for them and merge it: orch ref wait {key} --merge"
    )


def _helper(root: Path, ticket: dict) -> tuple[str, dict | None]:
    """(none | idle | busy, run record): busy = a helper works or waits on something; idle = at its prompt."""
    rec = runs.read(root, ticket["id"])
    if not rec or runs.state(rec) != "alive":
        return "none", rec
    sig = runwatch.signal(rec, runwatch.waiting_on(root, rec, ticket))
    return ("idle" if sig == "idle" else "busy"), rec


def _left_open(root: Path, tickets_: list[dict]) -> list[tuple[dict, str, str]]:
    """(ticket, helper state, pull request) for every ticket in Review with an open pull request and no
    helper at work."""
    out = []
    for t in tickets_:
        if t.get("status") != "review" or t.get("general") is True:
            continue
        pulls = open_pulls(t)
        if not pulls:
            continue
        helper, _ = _helper(root, t)
        if helper != "busy":
            out += [(t, helper, url) for url in pulls]
    return out


def look(root: Path, tickets_: list[dict], now: float | None = None) -> int:
    """Ask GitHub about the pull requests whose last look is older than CHECK_EVERY and keep the answers.
    Returns how many were read. Run detached (`orch needs --look-at-pulls`); never raises."""
    now = time.time() if now is None else now
    data = _read(root)
    pulls = data.get("pulls") or {}
    wanted = {url for _, _, url in _left_open(root, tickets_)}
    stale = [u for u in sorted(wanted) if now - float((pulls.get(u) or {}).get("at") or 0) >= CHECK_EVERY]
    n = 0
    for url in stale[:MAX_PULLS]:
        old = pulls.get(url) or {}
        got = ghmerge.checks(url) or {"state": "UNKNOWN", "head": "", "green": False}  # asked again later
        same = old.get("green") and got["green"] and old.get("head") == got["head"]
        pulls[url] = {**got, "at": now, "green_since": old.get("green_since") if same else now}
        n += 1
    data = _read(root)  # another look may have finished meanwhile: keep its answers
    data["pulls"] = {u: v for u, v in {**(data.get("pulls") or {}), **pulls}.items() if u in wanted}
    _write(root, data)
    return n


def _spawn_look(root: Path) -> None:
    """One detached `orch needs --look-at-pulls`, from a neutral folder (as the copies cleanup does)."""
    if os.environ.get("ORCH_NO_PULL_LOOK"):  # tests: never the real GitHub
        return
    from orch import procs

    env = {**os.environ, "ORCH_ROOT": str(root)}
    subprocess.Popen(
        procs.orch_python_argv("needs", "--look-at-pulls"),
        cwd=Path(os.path.realpath(tempfile.gettempdir())),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _unmerged_rows(root: Path, tickets_: list[dict], now: float) -> list[dict]:
    left = _left_open(root, tickets_)
    if not left:
        return []
    data = _read(root)
    pulls = data.get("pulls") or {}
    rows, due = [], False
    for t, helper, url in left:
        seen = pulls.get(url) if isinstance(pulls.get(url), dict) else None
        if seen is None or now - float(seen.get("at") or 0) >= CHECK_EVERY:
            due = True
        if not seen or seen.get("green") is not True or seen.get("state") != "OPEN":
            continue
        tid = t["id"]
        if any(r["ticket"] == tid for r in rows):
            continue  # one row per ticket: its first pull request that is ready
        key = t.get("key") or tid
        rows.append(
            {
                "id": f"core:unmerged:{tid}",
                "source": "core",
                "kind": "helper:unmerged",
                "ticket": tid,
                "title": " ".join(str(t.get("title") or tid).split())[:200] or tid,
                "text": UNMERGED,
                "tone": "needs-you",
                "since": _iso(float(seen.get("green_since") or seen.get("at") or now)),
                "cli": f"orch run start {key}",
                "pull": {"url": url, "head": seen["head"]},
                "helper": helper,
            }
        )
    if due and shutil.which("gh") and now - float(data.get("asked_at") or 0) >= ASK_EVERY:
        _write(root, {**data, "asked_at": now})
        try:
            _spawn_look(root)
        except OSError:
            pass
    return rows


def _idle_rows(root: Path, tickets_: list[dict], now: float) -> list[dict]:
    rows = []
    for t in tickets_:
        if t.get("status") in (*FINISHED, "waiting") or t.get("general") is True:
            continue
        if any(q.get("answer") is None for q in t.get("questions") or []):
            continue  # it asked a person: that question is the row
        helper, rec = _helper(root, t)
        since = runwatch.idle_since(rec) if helper == "idle" else None
        secs = runwatch._age(since, now)
        if secs is None or secs < IDLE_MINUTES * 60:
            continue
        tid = t["id"]
        rows.append(
            {
                "id": f"core:idle:{tid}",
                "source": "core",
                "kind": "helper:idle",
                "ticket": tid,
                "title": " ".join(str(t.get("title") or tid).split())[:200] or tid,
                "text": f"The helper has been idle for {runwatch.span(secs)} with nothing running.",
                "tone": "warn",
                "since": since,
                "cli": f'orch run send {t.get("key") or tid} "Carry on with the open tasks."',
            }
        )
    return rows


def _title(t: dict) -> str:
    return " ".join(str(t.get("title") or t["id"]).split())[:200] or t["id"]


def _clip(text: str, n: int = 500) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _open_question(t: dict) -> bool:
    return any(q.get("answer") is None for q in t.get("questions") or [] if isinstance(q, dict))


def _permission_rows(root: Path, tickets_: list[dict], now: float) -> list[dict]:
    """A live helper that has waited on a person's OK on its screen (a permission prompt) too long."""
    rows = []
    for t in tickets_:
        if t.get("status") in FINISHED or t.get("general") is True:
            continue
        rec = runs.read(root, t["id"])
        live = (rec or {}).get("live") or {}
        if not rec or rec.get("mode") != "live" or live.get("state") != "attention":
            continue
        if runs.state(rec) != "alive":
            continue
        secs = runwatch._age(live.get("since"), now)
        if secs is None or secs < PERMISSION_MINUTES * 60:
            continue
        key = t.get("key") or t["id"]
        rows.append(
            {
                "id": f"core:permission:{t['id']}",
                "source": "core",
                "kind": "helper:permission",
                "ticket": t["id"],
                "title": _title(t),
                "text": f"The helper has waited {runwatch.span(secs)} for your OK on its screen.",
                "tone": "needs-you",
                "since": live["since"],
                "cli": f"orch run screen {key}",
            }
        )
    return rows


def _check_runs(item: dict) -> list[dict]:
    """The step's recorded check runs (command evidence with an exit code), oldest first."""
    return [
        e
        for e in item.get("evidence") or []
        if isinstance(e, dict) and e.get("type") == "command" and "exit" in e
    ]


def failed_runs(item: dict) -> int:
    """How many of the step's last recorded check runs failed in a row (non-zero exit)."""
    n = 0
    for e in reversed(_check_runs(item)):
        if e.get("exit") in (0, None):
            break
        n += 1
    return n


def _failing_rows(root: Path, tickets_: list[dict], now: float) -> list[dict]:
    """An open step whose last FAILED_RUNS recorded checks all failed: the helper keeps failing at it."""
    rows = []
    for t in tickets_:
        if t.get("status") in FINISHED or t.get("general") is True:
            continue
        for item in t.get("checklist") or []:
            if not isinstance(item, dict) or item.get("done") or item.get("wont_do"):
                continue
            n = failed_runs(item)
            if n < FAILED_RUNS:
                continue
            last = _check_runs(item)[-1]
            step = " ".join(str(item.get("text") or "").split())[:120]
            since = last.get("ran_at") or last.get("at") or _iso(now)
            rows.append(
                {
                    "id": f"core:failing:{t['id']}",
                    "source": "core",
                    "kind": "helper:failing",
                    "ticket": t["id"],
                    "title": _title(t),
                    "text": _clip(f'The check failed {n} times in a row on the step "{step}".'),
                    "tone": "bad",
                    "since": since,
                    "cli": f"orch ticket show {t.get('key') or t['id']}",
                }
            )
            break  # one row per ticket: its first failing step
    return rows


def _unsure_rows(root: Path, tickets_: list[dict], now: float) -> list[dict]:
    """A ticket in Review the Reviewer left for the person (reviewer.json `left`): it was not sure. A ticket
    whose own question waits has that question as its row."""
    from orch import reviewer

    state = reviewer._read_state(root)
    rows = []
    for t in tickets_:
        mine = state.get(t["id"]) or {}
        why = mine.get("left")
        if t.get("status") != "review" or not isinstance(why, str) or not why or _open_question(t):
            continue
        rows.append(
            {
                "id": f"core:unsure:{t['id']}",
                "source": "core",
                "kind": "reviewer:unsure",
                "ticket": t["id"],
                "title": _title(t),
                "text": _clip("The Reviewer was not sure and left it for you: " + why.rstrip(".") + "."),
                # ORCH-1717: Home shows this one plain reason with a calm Check mark (the phone and orch needs keep text)
                "short": reviewer.plain_left(why),
                "tone": "needs-you",
                "since": t.get("updated_at") or _iso(now),
                "cli": f"orch ticket show {t.get('key') or t['id']}",
            }
        )
    return rows


def stuck_rows(root: Path, tickets_: list[dict], now: float | None = None) -> list[dict]:
    """Only the stuck tickets (STUCK_KINDS), for the phone. Never raises."""
    now = time.time() if now is None else now
    out: list[dict] = []
    for make in (_permission_rows, _failing_rows, _unsure_rows):
        try:
            out += make(root, tickets_, now)
        except Exception:  # noqa: BLE001, S112 - what waits for a person must always be listed
            continue
    return out


def rows(root: Path, tickets_: list[dict], now: float | None = None) -> list[dict]:
    """The rows for `orch needs`. A broken run record or cache never breaks the list."""
    now = time.time() if now is None else now
    out: list[dict] = stuck_rows(root, tickets_, now)
    for make in (_unmerged_rows, _idle_rows):
        try:
            out += make(root, tickets_, now)
        except Exception:  # noqa: BLE001, S112 - what waits for a person must always be listed
            continue
    return out
