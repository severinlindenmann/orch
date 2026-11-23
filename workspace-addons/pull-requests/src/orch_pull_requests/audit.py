"""`orch pull-requests queue audit`: how a stretch of time went for the merge queue (ORCH-450). No AI call.

- merges into each base branch the queue serves (from GitHub): checked in a queue group (a group pull request on
  an `orch-queue/` branch, or a member listed in its title), merged alone by the queue (its own checks green and
  the base changed none of its files; the queue's file says it merged it), checked alone and merged by a person
  (its head carries the queue's mark), or past the queue (none of these);
- times the queue stood still (from the queue's own file): a stretch of at least STILL_MINUTES with a pull
  request in line and no merge, with the reasons the entries of that stretch gave;
- check runs per merge (ORCH-545, from GitHub): rounds of checks (one per commit and event, all workflows
  together) on pull requests, on queue groups, on pushes and other, divided by the merges;
- minutes from joining the queue to merged, for the pull requests the queue merged (from its own file);
- the busiest hour (ORCH-1129, from GitHub): the most pull requests the queue merged (in a group or alone) within
  any 60 minutes, with their links; goal HOUR_GOAL;
- group start to merged (ORCH-1129, from GitHub): minutes from opening a group pull request to its merge, the
  middle over the last LAST_GROUPS merged groups; goal under GROUP_GOAL minutes.

The night of 17/18 Nov 2026 (ORCH-446): 13 groups for 64 merges, 5 stand-stills, 3 of them avoidable.
"""

from __future__ import annotations

import itertools
import re
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import settings, store

STILL_MINUTES = 30
HOUR_GOAL = 20  # merges within one hour (ORCH-1120)
GROUP_GOAL = 6  # minutes from group start to merged, at the middle
LAST_GROUPS = 20
QUEUE_BRANCH = "orch-queue/"
_NUM = re.compile(r"#([0-9]{1,9})")


def _t(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def merges(gh, repo: str, base: str, since: datetime, queued: frozenset[str] = frozenset()) -> dict | None:
    """{groups, through, alone, by_person, past, unsure} for one base branch: lists of {number, url, mergedAt}
    (alone: its head carries the mark and the queue's file says it merged it, url in queued; unsure: GitHub did not say whether its head carries the
    mark). None when GitHub did not answer."""
    rows = gh.merged_prs(repo, base, since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if rows is None:
        return None
    groups = [r for r in rows if str(r.get("headRefName") or "").startswith(QUEUE_BRANCH)]
    inside: set[int] = set()
    for g in groups:
        title = str(g.get("title") or "")
        if title.startswith("Merge queue:"):
            inside |= {int(n) for n in _NUM.findall(title.split(":", 1)[1])}
    through, alone, by_person, past, unsure = [], [], [], [], []
    for r in rows:
        if r in groups:
            continue
        if r.get("number") in inside:
            through.append(r)
            continue
        marked = gh.has_mark(repo, str(r.get("headRefOid") or "")) if r.get("headRefOid") else False
        if marked and str(r.get("url") or "") in queued:  # the queue merged it and its head carries the mark
            alone.append(r)
            continue
        (unsure if marked is None else by_person if marked else past).append(r)
    return {
        "groups": groups, "through": through, "alone": alone, "by_person": by_person, "past": past, "unsure": unsure,
    }  # fmt: skip


def stood_still(rows: list[dict], merged_at: list[datetime], since: datetime, until: datetime) -> list[dict]:
    """Stretches of at least STILL_MINUTES between since and until with a pull request in line (added, not yet
    ended) and no merge: [{start, end, minutes, why}]."""
    spans = []
    for r in rows:
        a, e = _t(r.get("added")), _t(r.get("ended")) or until
        if a is None or e <= since or a >= until:
            continue
        spans.append((max(a, since), min(e, until), r))
    if not spans:
        return []
    marks = {since, until, *(t for t in merged_at if since < t < until)}
    marks |= {s for s, _, _ in spans} | {e for _, e, _ in spans}
    edges = sorted(marks)
    still, out = None, []
    for left, right in itertools.pairwise(edges):
        if not any(s <= left and right <= e for s, e, _ in spans):  # nothing in line
            if still is not None:
                out.append((still, left))
                still = None
            continue
        still = still or left
        if any(left < t <= right for t in merged_at):  # a merge ends the stretch
            out.append((still, right))
            still = None
    if still is not None:
        out.append((still, until))
    found = []
    for a, b in out:
        minutes = int((b - a).total_seconds() // 60)
        if minutes < STILL_MINUTES:
            continue
        why = sorted({str(r.get("why") or "") for s, e, r in spans if s < b and e > a and r.get("why")})
        found.append({"start": a, "end": b, "minutes": minutes, "why": why[:5]})
    return found


def runs(rows: list[dict] | None) -> dict | None:
    """Rounds of checks by kind: one per commit and event (the jobs of every workflow on it count once)."""
    if rows is None:
        return None
    seen: dict[tuple[str, str], str] = {}
    for r in rows:
        ev, branch = str(r.get("event") or ""), str(r.get("head_branch") or "")
        if branch.startswith(QUEUE_BRANCH):
            kind = "groups"
        elif ev == "pull_request":
            kind = "pull_requests"
        elif ev == "push":
            kind = "pushes"
        else:
            kind = "other"
        seen.setdefault((str(r.get("head_sha") or ""), ev), kind)
    got = {k: 0 for k in ("pull_requests", "groups", "pushes", "other")}
    for kind in seen.values():
        got[kind] += 1
    got["incomplete"] = len(rows) >= 1000  # GitHub lists at most 1000 runs of one time search
    return got


def busiest_hour(merged: list[dict]) -> dict:
    """The most pull requests merged within any 60 minutes: {count, start, end, prs} (prs sorted by mergedAt)."""
    rows = sorted(((t, r) for r in merged if (t := _iso(r.get("mergedAt")))), key=lambda x: x[0])
    best, left = (0, 0), 0
    for right, (t, _) in enumerate(rows):
        while t - rows[left][0] > timedelta(hours=1):
            left += 1
        if right - left + 1 > best[1] - best[0]:
            best = (left, right + 1)
    inside = rows[best[0] : best[1]]
    return {
        "count": len(inside),
        "start": inside[0][0] if inside else None,
        "end": inside[-1][0] if inside else None,
        "prs": [r for _, r in inside],
    }


def group_minutes(groups: list[dict], last: int = LAST_GROUPS) -> dict:
    """Minutes from opening a group pull request to its merge, for the last `last` merged groups in the window:
    {groups: [{number, url, createdAt, mergedAt, seconds, minutes}], middle} (middle in minutes from the exact
    seconds, None without a group; minutes per group are rounded for display only)."""
    got = []
    for g in groups:
        a, e = _iso(g.get("createdAt")), _iso(g.get("mergedAt"))
        if a and e and e >= a:
            secs = int((e - a).total_seconds())
            row = {k: g.get(k) for k in ("number", "url", "createdAt", "mergedAt")}
            got.append((e, {**row, "seconds": secs, "minutes": round(secs / 60, 1)}))
    got = [r for _, r in sorted(got, key=lambda x: x[0])][-last:]
    return {"groups": got, "middle": statistics.median(r["seconds"] for r in got) / 60 if got else None}


def waited(rows: list[dict], since: datetime, until: datetime) -> list[int]:
    """Minutes from joining the queue to merged, for the entries the queue merged in the window (sorted)."""
    out = []
    for r in rows:
        a, e = _t(r.get("added")), _t(r.get("ended"))
        if r.get("state") == store.MERGED and a and e and since <= e <= until:
            out.append(int((e - a).total_seconds() // 60))
    return sorted(out)


def run(root: Path, gh, hours: float, now: datetime | None = None) -> dict:
    """The audit of the last `hours`."""
    until = now or datetime.now(UTC)
    since = until - timedelta(hours=hours)
    rows = store.read(root)
    repos = sorted({str(r.get("repo")) for r in rows if r.get("repo")})
    bases = settings.bases(root)
    queued = frozenset(str(r.get("url")) for r in rows if r.get("state") == store.MERGED)
    report = {"since": since, "until": until, "bases": [], "still": [], "unknown": [], "runs": {}}
    report["waited"] = waited(rows, since, until)
    merged_at = [t for r in rows if r.get("state") == store.MERGED and (t := _t(r.get("ended")))]
    for repo in repos:
        for base in bases:
            got = merges(gh, repo, base, since, queued)
            if got is None:
                report["unknown"].append(f"{repo} {base}")
                continue
            every = got["groups"] + got["alone"] + got["by_person"] + got["past"] + got["unsure"]
            merged_at += [t for g in every if (t := _iso(g.get("mergedAt")))]
            report["bases"].append({"repo": repo, "base": base, **got})
        look = getattr(gh, "runs", None)
        window = (since.strftime("%Y-%m-%dT%H:%M:%SZ"), until.strftime("%Y-%m-%dT%H:%M:%SZ"))
        report["runs"][repo] = runs(look(repo, *window)) if look else None
    report["still"] = stood_still(rows, merged_at, since, until)
    report["hour"] = busiest_hour([r for b in report["bases"] for r in b["through"] + b["alone"]])
    report["group_minutes"] = group_minutes([g for b in report["bases"] for g in b["groups"]])
    return report


def _iso(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None


def text(report: dict) -> str:
    def hm(t: datetime) -> str:
        return t.astimezone().strftime("%d %b %H:%M")

    lines = [f"Merge queue from {hm(report['since'])} to {hm(report['until'])}:"]
    for b in report["bases"]:
        n_in = len(b["through"])
        total = n_in + len(b["alone"]) + len(b["by_person"]) + len(b["past"]) + len(b["unsure"])
        lines.append(
            f"- {b['repo']} {b['base']}: {total} merges; {n_in} checked in {len(b['groups'])} queue groups, "
            f"{len(b['alone'])} merged alone by the queue, "
            f"{len(b['by_person'])} checked alone and merged by a person, {len(b['past'])} past the queue"
            + (f", {len(b['unsure'])} not known (GitHub did not say)." if b["unsure"] else ".")
        )
        lines += [f"    past the queue: #{r['number']} {r.get('url', '')}" for r in b["past"]]
    for u in report["unknown"]:
        lines.append(f"- {u}: GitHub did not answer; not counted.")
    for repo, c in report.get("runs", {}).items():
        if c is None:
            lines.append(f"- {repo} check runs: GitHub did not answer; not counted.")
            continue
        merged = sum(_merges(b) for b in report["bases"] if b["repo"] == repo)
        total = c["pull_requests"] + c["groups"] + c["pushes"] + c["other"]
        per = f"{total / merged:.1f} per merge" if merged else "no merge"
        lines.append(
            f"- {repo} check runs: {total} ({per}): {c['pull_requests']} on pull requests, {c['groups']} on queue "
            f"groups, {c['pushes']} on pushes, {c['other']} other"
            + (
                " (at least: GitHub lists only 1000 runs; ask for fewer hours)."
                if c.get("incomplete")
                else "."
            )
        )
    w = report.get("waited") or []
    if w:
        lines.append(
            f"From joining the queue to merged: middle {w[len(w) // 2]} min, longest {w[-1]} min "
            f"({len(w)} merged by the queue)."
        )
    h = report.get("hour")
    if h and h["count"]:
        lines.append(
            f"Busiest hour: {h['count']} merged by the queue from {hm(h['start'])} to {hm(h['end'])} "
            f"(goal {HOUR_GOAL}: {'reached' if h['count'] >= HOUR_GOAL else 'not reached'})."
        )
        lines += [f"    #{r['number']} {r.get('url', '')} merged {hm(_iso(r['mergedAt']))}" for r in h["prs"]]
    g = report.get("group_minutes")
    if g and g["groups"]:
        n, mid = len(g["groups"]), g["middle"]
        if n < LAST_GROUPS:
            verdict = f"not known yet, {n} of {LAST_GROUPS} groups; ask for more hours"
        else:
            verdict = "reached" if mid < GROUP_GOAL else "not reached"
        longest = max(r["seconds"] for r in g["groups"]) / 60
        lines.append(
            f"Group start to merged: middle {mid:.1f} min over the last {n} groups, longest {longest:.1f} min "
            f"(goal under {GROUP_GOAL} min over {LAST_GROUPS} groups: {verdict})."
        )
    still = report["still"]
    lines.append(
        f"The queue stood still {len(still)} times (at least {STILL_MINUTES} minutes with a pull request in "
        "line and no merge)" + (":" if still else ".")
    )
    for s in still:
        lines.append(f"- {hm(s['start'])} to {hm(s['end'])} ({s['minutes']} min)")
        lines += [f"    {w[:200]}" for w in s["why"]]
    return "\n".join(lines)


def _merges(b: dict) -> int:
    return len(b["through"]) + len(b["alone"]) + len(b["by_person"]) + len(b["past"]) + len(b["unsure"])


def as_json(report: dict) -> dict:
    def pr(r):
        return {k: r.get(k) for k in ("number", "url", "mergedAt")}

    return {
        "since": report["since"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "until": report["until"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bases": [
            {
                "repo": b["repo"],
                "base": b["base"],
                "groups": len(b["groups"]),
                "through": [pr(r) for r in b["through"]],
                "alone": [pr(r) for r in b["alone"]],
                "by_person": [pr(r) for r in b["by_person"]],
                "past": [pr(r) for r in b["past"]],
                "unsure": [pr(r) for r in b["unsure"]],
            }
            for b in report["bases"]
        ],
        "still": [
            {
                "start": s["start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": s["end"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "minutes": s["minutes"],
                "why": s["why"],
            }
            for s in report["still"]
        ],
        "unknown": report["unknown"],
        "runs": report.get("runs", {}),
        "waited_minutes": report.get("waited", []),
        "hour": _hour_json(report.get("hour")),
        "group_minutes": report.get("group_minutes"),
    }


def _hour_json(h: dict | None) -> dict | None:
    if h is None:
        return None
    t = lambda v: v.strftime("%Y-%m-%dT%H:%M:%SZ") if v else None
    return {"count": h["count"], "goal": HOUR_GOAL, "start": t(h["start"]), "end": t(h["end"]),
            "prs": [{k: r.get(k) for k in ("number", "url", "mergedAt")} for r in h["prs"]]}  # fmt: skip
