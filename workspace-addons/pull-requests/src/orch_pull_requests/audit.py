"""`orch pull-requests queue audit`: how a stretch of time went for the merge queue (ORCH-450). No AI call.

- merges into each base branch the queue serves (from GitHub): checked in a queue group (a group pull request on
  an `orch-queue/` branch, or a member listed in its title), merged alone by the queue (its own checks green and
  the base changed none of its files; the queue's file says it merged it), checked alone and merged by a person
  (its head carries the queue's mark), or past the queue (none of these);
- times the queue stood still (from the queue's own file): a stretch of at least STILL_MINUTES with a pull
  request in line and no merge, with the reasons the entries of that stretch gave.

The night of 17/18 Nov 2026 (ORCH-446): 13 groups for 64 merges, 5 stand-stills, 3 of them avoidable.
"""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import settings, store

STILL_MINUTES = 30
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


def run(root: Path, gh, hours: float, now: datetime | None = None) -> dict:
    """The audit of the last `hours`."""
    until = now or datetime.now(UTC)
    since = until - timedelta(hours=hours)
    rows = store.read(root)
    repos = sorted({str(r.get("repo")) for r in rows if r.get("repo")})
    bases = settings.bases(root)
    queued = frozenset(str(r.get("url")) for r in rows if r.get("state") == store.MERGED)
    report = {"since": since, "until": until, "bases": [], "still": [], "unknown": []}
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
    report["still"] = stood_still(rows, merged_at, since, until)
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
    still = report["still"]
    lines.append(
        f"The queue stood still {len(still)} times (at least {STILL_MINUTES} minutes with a pull request in "
        "line and no merge)" + (":" if still else ".")
    )
    for s in still:
        lines.append(f"- {hm(s['start'])} to {hm(s['end'])} ({s['minutes']} min)")
        lines += [f"    {w[:200]}" for w in s["why"]]
    return "\n".join(lines)


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
    }
