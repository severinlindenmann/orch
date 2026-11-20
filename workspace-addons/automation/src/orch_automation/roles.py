"""Runs of a repeating ticket (a role) and what came of them (ORCH-827, ORCH-814).

Three local files next to runs.jsonl in .orch/addons/automation/ (gitignored like it):
- runs.jsonl      one line per finished or skipped run: {ticket, at, took, exit, run?, script?, skipped?}
- outcomes.jsonl  the result a helper wrote for one run: {ticket, run, outcome, text, checked[], files[], cost?, at};
                  a second result for the same run replaces the first (newest line wins)
- findings.jsonl  one line per finding seen in a run: {role, run, title, match, ticket, at, files[]}

A run gets its number when it starts (`begin`, kept as state[ticket].current_run), so a result or a finding written
while it runs names that run and never a later one. Older lines without a number are numbered by their order.
The totals are one function (`totals`) used by the role ticket page and the Automation page alike.
Files: "opened" is a first open in the dashboard's file viewer (.orch/addons/dashboard/file-opens.json, written by
the dashboard); a run file older than the day that measuring started is unknown, never "unopened".
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles
from .cron import fmt, parse
from .runner import load_state, sdir, update_state

OUTCOMES = ("ok", "problems", "not-finished", "failed")
OUTCOME_WORDS = {
    "ok": "no problems found",
    "problems": "problems reported",
    "not-finished": "not finished",
    "failed": "failed",
    "skipped": "skipped, nothing changed",
    "running": "running now",
    "none": "finished, no result written",
    "stopped": "stopped early",
}
OUTCOME_TONE = {
    "ok": "ok",
    "problems": "ok",
    "not-finished": "warn",
    "failed": "bad",
    "skipped": "none",
    "running": "working",
    "none": "none",
    "stopped": "bad",
}
MAX_TEXT, MAX_LINES, MAX_FILES = 400, 12, 20
FILE_NAME = re.compile(r"[^/\\\x00]{1,240}")
OPENS = Path("addons") / "dashboard" / "file-opens.json"


def _lines(root: Path, name: str) -> list[dict]:
    try:
        raw = (sdir(root) / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if isinstance(x, dict):
            out.append(x)
    return out


def _append(root: Path, name: str, line: dict) -> None:
    with runfiles.open_append(sdir(root) / name) as f:
        f.write(json.dumps(line) + "\n")


def _plain(text: object, n: int) -> str:
    s = re.sub(r"[\x00-\x1f\x7f  ]+", " ", str(text or "")).strip()
    return s[:n]


def run_lines(root: Path, tid: str) -> list[dict]:
    """The ticket's run lines, oldest first, each with its number ("run")."""
    mine = [x for x in _lines(root, "runs.jsonl") if x.get("ticket") == tid and isinstance(x.get("at"), str)]
    mine.sort(key=lambda x: x["at"])
    used = 0
    for x in mine:
        n = x.get("run")
        if isinstance(n, int) and n > used:
            used = n
        else:
            used += 1
            x["run"] = used
    return mine


def begin(root: Path, tid: str, at: str | None = None) -> int:
    """A run starts now: give it the next number and remember it as the ticket's current run."""
    st = load_state(root).get(tid) or {}
    done = run_lines(root, tid)
    prev = st.get("current_run") or {}
    if isinstance(prev.get("run"), int) and isinstance(prev.get("at"), str) and all(x["run"] != prev["run"] for x in done):
        # a run nobody watched to its end (Run now on a helper): keep it in the list before the next one starts
        _append(root, "runs.jsonl", {"ticket": tid, "at": prev["at"], "took": None, "exit": 0, "run": prev["run"]})
        done.append({"run": prev["run"]})
    n = max([x["run"] for x in done] + [int(st.get("run_count") or 0)]) + 1
    update_state(root, tid, run_count=n, current_run={"run": n, "at": at or fmt(datetime.now(UTC))})
    return n


def current(root: Path, tid: str) -> int | None:
    cur = (load_state(root).get(tid) or {}).get("current_run") or {}
    return cur.get("run") if isinstance(cur.get("run"), int) else None


def number_for(root: Path, tid: str, at: str) -> int | None:
    """The number the run that started at `at` got (None: it was started before runs had numbers)."""
    cur = (load_state(root).get(tid) or {}).get("current_run") or {}
    return cur.get("run") if cur.get("at") == at and isinstance(cur.get("run"), int) else None


def skipped(root: Path, tid: str, at: str) -> None:
    """The quick check found nothing changed at a planned time: one run line that cost nothing."""
    n = begin(root, tid, at)
    _append(root, "runs.jsonl", {"ticket": tid, "at": at, "took": 0, "exit": 0, "run": n, "skipped": True})


def _files(files: list[str] | None) -> list[str]:
    out = []
    for f in files or []:
        name = Path(str(f)).name
        if FILE_NAME.fullmatch(name) and name not in out:
            out.append(name)
    return out[:MAX_FILES]


def result(
    root: Path,
    tid: str,
    text: str,
    outcome: str,
    checked: list[str] | None = None,
    files: list[str] | None = None,
    cost: float | None = None,
    run: int | None = None,
) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError("The outcome is one of: " + ", ".join(OUTCOMES) + ".")
    n = run if run is not None else current(root, tid)
    if not isinstance(n, int) or n < 1:
        raise ValueError("This ticket has no run yet. Say which one with --run.")
    text = _plain(text, MAX_TEXT)
    if not text:
        raise ValueError("Say in one line what the run found.")
    if cost is not None and not (0 <= cost < 10000):
        raise ValueError("The cost is a number of dollars between 0 and 10000.")
    line = {
        "ticket": tid,
        "run": n,
        "outcome": outcome,
        "text": text,
        "checked": [c for c in (_plain(c, 200) for c in (checked or [])) if c][:MAX_LINES],
        "files": _files(files),
        "at": fmt(datetime.now(UTC)),
    }
    if cost is not None:
        line["cost"] = round(float(cost), 2)
    _append(root, "outcomes.jsonl", line)
    return line


def match_name(title: str) -> str:
    """Two findings with the same match name are the same finding: lower case, letters and digits only."""
    return " ".join(re.findall(r"[a-z0-9]+", str(title).lower()))[:120]


def finding_ticket(findings: list[dict], tickets: dict, role: str, match: str) -> tuple[str | None, str | None]:
    """(open ticket to reuse, done ticket it follows) for a finding of `role` with this match name."""
    reuse = earlier = None
    for f in findings:
        if f.get("role") != role or f.get("match") != match:
            continue
        t = tickets.get(f.get("ticket"))
        if not t:
            continue
        if t.get("status") in ("done", "dropped"):
            earlier = t["id"]
        else:
            reuse = t["id"]
    return reuse, earlier


def finding_line(
    root: Path, role: str, run: int, title: str, ticket: str, match: str, files: list[str] | None = None
) -> dict:
    line = {
        "role": role,
        "run": run,
        "title": _plain(title, 200),
        "match": match,
        "ticket": ticket,
        "files": _files(files),
        "at": fmt(datetime.now(UTC)),
    }
    _append(root, "findings.jsonl", line)
    return line


def findings_of(root: Path, role: str | None = None) -> list[dict]:
    return [f for f in _lines(root, "findings.jsonl") if role is None or f.get("role") == role]


def _opens(root: Path) -> dict:
    data = runfiles.read_json(root / ".orch" / OPENS) or {}
    return data if isinstance(data, dict) else {}


def _file_state(root: Path, tid: str, name: str, opens: dict) -> str:
    """opened / unopened / unknown for one run file of a ticket."""
    since = parse(opens.get("since"))
    if (opens.get("files") or {}).get(tid, {}).get(name):
        return "opened"
    if not since:
        return "unknown"
    for kind in ("artifacts", "evidence"):
        p = root / ".orch" / "tickets" / tid / kind / name
        try:
            made = datetime.fromtimestamp(p.stat().st_mtime, UTC)
        except OSError:
            continue
        return "unopened" if made >= since else "unknown"
    return "unknown"


def runs(root: Path, t: dict, running: bool = False) -> list[dict]:
    """Every run of a role, newest first: number, when, how long, outcome (words and tone), what it checked, its
    files with their open state, its findings, cost when one was recorded."""
    tid = t["id"]
    lines = run_lines(root, tid)
    outcomes: dict[int, dict] = {}
    for o in _lines(root, "outcomes.jsonl"):
        if o.get("ticket") == tid and isinstance(o.get("run"), int):
            outcomes[o["run"]] = o
    found: dict[int, list[dict]] = {}
    for f in findings_of(root, tid):
        if isinstance(f.get("run"), int):
            found.setdefault(f["run"], []).append(f)
    opens = _opens(root)
    out = []
    for x in lines:
        n = x["run"]
        o = outcomes.get(n)
        if x.get("skipped"):
            kind = "skipped"
        elif o:
            kind = o["outcome"]
        else:
            kind = "none" if x.get("exit") == 0 else "stopped"
        files = list((o or {}).get("files") or [])
        for f in found.get(n, []):
            files += [name for name in f.get("files") or [] if name not in files]
        out.append(
            {
                "run": n,
                "at": x["at"],
                "took": x.get("took") if isinstance(x.get("took"), int) else None,
                "outcome": kind,
                "words": OUTCOME_WORDS[kind],
                "tone": OUTCOME_TONE[kind],
                "text": (o or {}).get("text") or "",
                "checked": (o or {}).get("checked") or [],
                "cost": 0 if kind == "skipped" else (o or {}).get("cost"),
                "files": [{"name": name, "state": _file_state(root, tid, name, opens)} for name in files],
                "findings": [{"title": f.get("title"), "ticket": f.get("ticket")} for f in found.get(n, [])],
                **({"script": x["script"]} if x.get("script") else {}),
            }
        )
    cur = (load_state(root).get(tid) or {}).get("current_run") or {}
    if isinstance(cur.get("run"), int) and not any(r["run"] == cur["run"] for r in out):
        o = outcomes.get(cur["run"])
        kind = "running" if running else o["outcome"] if o else "none"
        out.append(
            {
                "run": cur["run"],
                "at": cur.get("at"),
                "took": None,
                "outcome": kind,
                "words": OUTCOME_WORDS[kind],
                "tone": OUTCOME_TONE[kind],
                "text": (o or {}).get("text") or "",
                "checked": (o or {}).get("checked") or [],
                "cost": (o or {}).get("cost"),
                "files": [{"name": n2, "state": _file_state(root, tid, n2, opens)} for n2 in (o or {}).get("files") or []],
                "findings": [{"title": f.get("title"), "ticket": f.get("ticket")} for f in found.get(cur["run"], [])],
            }
        )
    return list(reversed(out))


def totals(root: Path, t: dict, tickets: dict, run_list: list[dict] | None = None) -> dict:
    """The one count both pages show: runs by outcome, findings (sightings and distinct), the tickets they became
    (fixed = done, dropped, open; each ticket once), run files opened / unopened / unknown."""
    rl = run_list if run_list is not None else runs(root, t)
    by: dict[str, int] = {}
    for r in rl:
        by[r["outcome"]] = by.get(r["outcome"], 0) + 1
    fl = findings_of(root, t["id"])
    distinct = {f.get("match") or match_name(f.get("title") or "") for f in fl}
    tix = {f.get("ticket") for f in fl if f.get("ticket")}
    fixed = sum(1 for x in tix if (tickets.get(x) or {}).get("status") == "done")
    dropped = sum(1 for x in tix if (tickets.get(x) or {}).get("status") == "dropped")
    gone = sum(1 for x in tix if x not in tickets)
    files = {"opened": 0, "unopened": 0, "unknown": 0}
    seen = set()
    for r in rl:
        for f in r["files"]:
            if f["name"] not in seen:
                seen.add(f["name"])
                files[f["state"]] += 1
    cost = [r["cost"] for r in rl if isinstance(r.get("cost"), (int, float))]
    scripts = sorted({r["script"] for r in rl if r.get("script")})
    return {
        "runs": len(rl),
        "by_outcome": by,
        "scripts": {s: sum(1 for r in rl if r.get("script") == s) for s in scripts},
        "findings": len(fl),
        "distinct_findings": len(distinct),
        "tickets": len(tix),
        "fixed": fixed,
        "dropped": dropped,
        "open": len(tix) - fixed - dropped - gone,
        "files": files,
        "files_measured": bool(_opens(root).get("since")),
        "cost": round(sum(cost), 2) if any(c for c in cost) else None,
    }


def next_number(root: Path, tid: str) -> int:
    """The number the next run will get (begin gives it once the start worked)."""
    st = load_state(root).get(tid) or {}
    return max([x["run"] for x in run_lines(root, tid)] + [int(st.get("run_count") or 0)]) + 1


def prompt(tid: str, n: int) -> str:
    """The lines a role's helper reads at the start of run n: how to write its result and its findings."""
    return (
        f" This is run {n}. First read the newest history lines that start with \"For the next run:\" (the"
        " person's notes). When you finish, write its result once:"
        f' orch automation result {tid} "<what it found, one line>" --outcome ok|problems|not-finished|failed'
        ' (add --checked "<line>" per thing checked and --file <name> per file it made).'
        f' Every problem it found: orch automation finding {tid} "<short title>" (it makes or reuses the ticket).'
    )
