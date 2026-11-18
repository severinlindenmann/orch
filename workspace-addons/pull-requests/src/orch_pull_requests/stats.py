"""`orch pull-requests queue stats`: what one day cost the merge queue (ORCH-554). No AI call.

- runs per merged pull request: every run of the main check workflow (default `ci.yml`) that started that day,
  whatever started it (pull request, push, queue group, by hand), divided by the pull requests merged into the
  queue's base branches that day. Queue group pull requests (`orch-queue/` branches) carry members and are not
  counted as merges.
- minutes from ready to merged: from the last time a pull request was marked ready for review (or opened, when it
  was never a draft) to its merge; the middle value and the slowest tenth.

`--save-baseline` keeps the numbers shown in the queue's folder; later days show it next to theirs. ORCH-545 counted
18 Nov 2026 up to 14:10 by hand: 62 merges, 365 runs, about 5.9 runs per merged pull request.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from . import settings, store

WORKFLOW = "ci.yml"
QUEUE_BRANCH = "orch-queue/"


def _file(root: Path) -> Path:
    return store.folder(root) / "baseline.json"


def _z(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _t(s) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def window(day: date, until: str | None = None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """The day in this computer's time zone, as [start, end) in UTC; `until` (HH:MM) cuts it short, and a day that is
    not over yet ends now."""
    start = datetime.combine(day, time(0, 0)).astimezone()
    end = start + timedelta(days=1)
    if until:
        try:
            h, m = (int(x) for x in until.split(":", 1))
            end = start.replace(hour=h, minute=m) if (h, m) != (24, 0) else end
        except ValueError:
            raise store.Refused("--until is a time like 14:10.") from None
    now = now or datetime.now(UTC)
    return start.astimezone(UTC), min(end.astimezone(UTC), max(now, start.astimezone(UTC)))


def _middle(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _slowest_tenth(xs: list[float]) -> float | None:
    """The time nine in ten were faster than (the 90th percentile, nearest rank)."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, -(-9 * len(s) // 10) - 1)]


def count(gh, repo: str, bases: list[str], start: datetime, end: datetime, workflow: str = WORKFLOW) -> dict:
    """{runs, by_event, merged, minutes, unknown} for one repository. None values: GitHub did not answer."""
    runs = gh.runs(repo, workflow, _z(start), _z(end - timedelta(seconds=1)))
    merged: list[dict] = []
    unknown = []
    for base in bases:
        got = gh.merged_ready(repo, base, _z(start), _z(end - timedelta(seconds=1)))
        if got is None:
            unknown.append(f"{repo} {base}")
            continue
        merged += [r for r in got if not str(r.get("headRefName") or "").startswith(QUEUE_BRANCH)]
    minutes = []
    for r in merged:
        m, ready = _t(r.get("mergedAt")), _t(r.get("readyAt") or r.get("createdAt"))
        if m and ready and m >= ready:
            minutes.append(round((m - ready).total_seconds() / 60, 1))
    by_event: dict[str, int] = {}
    for r in runs or []:
        e = str(r.get("event") or "other")
        by_event[e] = by_event.get(e, 0) + 1
    if runs is None:
        unknown.append(f"{repo} {workflow} runs")
    return {
        "repo": repo, "runs": None if runs is None else len(runs), "by_event": by_event,
        "merged": len(merged), "minutes": minutes, "unknown": unknown,
    }  # fmt: skip


def run(root: Path, gh, day: date, until: str | None = None, repo: str | None = None,
        workflow: str = WORKFLOW, now: datetime | None = None) -> dict:  # fmt: skip
    start, end = window(day, until, now)
    repos = [repo] if repo else sorted({str(r.get("repo")) for r in store.read(root) if r.get("repo")})
    if not repos:
        raise store.Refused(
            "No repository known yet: the merge queue has had no pull request. Name it with --repo."
        )
    parts = [count(gh, r, settings.bases(root), start, end, workflow) for r in repos]
    runs = None if any(p["runs"] is None for p in parts) else sum(p["runs"] for p in parts)
    merged = sum(p["merged"] for p in parts)
    minutes = [m for p in parts for m in p["minutes"]]
    by_event: dict[str, int] = {}
    for p in parts:
        for k, v in p["by_event"].items():
            by_event[k] = by_event.get(k, 0) + v
    return {
        "day": day.isoformat(), "start": _z(start), "end": _z(end), "repos": repos, "workflow": workflow,
        "runs": runs, "by_event": by_event, "merged": merged,
        "runs_per_merge": round(runs / merged, 1) if runs is not None and merged else None,
        "ready_to_merged_minutes": {"middle": _middle(minutes), "slowest_tenth": _slowest_tenth(minutes),
                                    "count": len(minutes)},
        "unknown": [u for p in parts for u in p["unknown"]],
    }  # fmt: skip


def save_baseline(root: Path, report: dict) -> None:
    if report["unknown"] or report["runs"] is None:
        raise store.Refused("GitHub did not answer for every part; the baseline was not saved. Try again.")
    if not report["merged"]:
        raise store.Refused("No pull request was merged that day; it cannot be the baseline.")
    f = _file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps({**report, "saved": _z(datetime.now(UTC))}, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def baseline(root: Path) -> dict | None:
    try:
        got = json.loads(_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) and got.get("day") else None


def _span(r: dict) -> str:
    a, b = _t(r["start"]), _t(r["end"])
    d = datetime.fromisoformat(r["day"]).strftime("%d %b %Y").lstrip("0")
    if a and b and (b - a) < timedelta(days=1):
        return f"{d} (to {b.astimezone().strftime('%H:%M')})"
    return d


def _min(x) -> str:
    return "-" if x is None else f"{round(x)} min"


def text(report: dict, base: dict | None) -> str:
    rtm = report["ready_to_merged_minutes"]
    runs = "not known (GitHub did not answer)" if report["runs"] is None else str(report["runs"])
    events = ", ".join(f"{v} {k}" for k, v in sorted(report["by_event"].items(), key=lambda kv: -kv[1]))
    per = "-" if report["runs_per_merge"] is None else f"{report['runs_per_merge']:.1f}"
    lines = [
        f"Merge queue numbers for {_span(report)}:",
        f"- {report['merged']} pull requests merged, {runs} check runs ({report['workflow']}"
        + (f": {events}" if events else "") + ")",
        f"- Runs per merged pull request: {per}",
        f"- From ready to merged: middle {_min(rtm['middle'])}, slowest tenth {_min(rtm['slowest_tenth'])}",
    ]  # fmt: skip
    lines += [f"- {u}: GitHub did not answer; not counted." for u in report["unknown"]]
    if base:
        b_rtm = base.get("ready_to_merged_minutes") or {}
        b_per = base.get("runs_per_merge")
        lines.append(
            f"Baseline {_span(base)}: {'-' if b_per is None else f'{b_per:.1f}'} runs per merged pull request, "
            f"ready to merged middle {_min(b_rtm.get('middle'))}, slowest tenth {_min(b_rtm.get('slowest_tenth'))}"
        )
    else:
        lines.append("No baseline saved yet (save one with --save-baseline).")
    return "\n".join(lines)
