"""`orch pull-requests queue audit` (ORCH-450): merges past the queue and times the queue stood still."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from orch_pull_requests import audit, cli, store

REPO = "acme/app"
NOW = datetime(2026, 11, 18, 9, 40, tzinfo=UTC)


def z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(h: int, m: int = 0) -> datetime:  # a time of the night of 17/18 Nov, UTC
    day = 17 if h >= 12 else 18
    return datetime(2026, 11, day, h, m, tzinfo=UTC)


class AuditGitHub:
    def __init__(self, merged, marked=()):
        self.merged, self.marked, self.asked = merged, set(marked), []

    def merged_prs(self, repo, base, since):
        self.asked.append((repo, base, since))
        return self.merged

    def has_mark(self, repo, sha):
        return sha in self.marked


def pr(n, head="feat/x", title="", merged=None):
    merged = merged or at(23)
    return {"number": n, "title": title or f"Change {n}", "headRefName": head, "headRefOid": f"{n:040d}",
            "mergedAt": z(merged), "url": f"https://github.com/{REPO}/pull/{n}"}  # fmt: skip


def entry(ws, n, added, ended=None, state=None, why="waiting in line"):
    store.add(ws, f"https://github.com/{REPO}/pull/{n}", None, "agent:t", login="bot", base="develop")

    def go(rows):
        r = store.find(rows, f"https://github.com/{REPO}/pull/{n}")
        r.update(added=z(added), why=why)
        if ended:
            r.update(ended=z(ended), state=state or store.MERGED)

    store.change(ws, go)


def test_merges_are_sorted_into_through_the_queue_by_a_person_and_past_it(ws):
    entry(ws, 1, at(22), at(22, 20))
    gh = AuditGitHub(
        [pr(500, "orch-queue/develop-1-abc", "Merge queue: #1, #2"), pr(1), pr(2), pr(3), pr(4)],
        marked={f"{4:040d}"},  # proved alone, merged by the owner with the Merge card
    )
    report = audit.run(ws, gh, 14, now=NOW)
    b = report["bases"][0]
    assert [r["number"] for r in b["through"]] == [1, 2] and len(b["groups"]) == 1
    assert [r["number"] for r in b["by_person"]] == [4] and [r["number"] for r in b["past"]] == [3]
    assert gh.asked == [(REPO, "develop", z(NOW - timedelta(hours=14)))]
    out = audit.text(report)
    assert "5 merges" not in out and "4 merges; 2 checked in 1 queue groups" in out
    assert "1 past the queue" in out and "past the queue: #3" in out


def test_a_stand_still_is_30_minutes_in_line_without_a_merge(ws):
    # #1 waits from 02:10; the fix waits behind it; nothing merges until 03:07: 57 minutes still
    entry(ws, 1, at(2, 10), at(3, 7), why="develop itself is red in the same checks; waits for the fix")
    entry(ws, 2, at(2, 30), at(3, 7))
    # a quiet stretch with nothing in line is not standing still
    entry(ws, 3, at(5, 0), at(5, 10))
    report = audit.run(ws, AuditGitHub([]), 14, now=NOW)
    still = report["still"]
    assert len(still) == 1 and still[0]["minutes"] == 57
    assert still[0]["start"] == at(2, 10) and still[0]["end"] == at(3, 7)
    assert "waits for the fix" in still[0]["why"][0]


def test_a_group_merge_ends_a_stand_still(ws):
    entry(ws, 1, at(1, 0))  # still waiting at the end
    gh = AuditGitHub([pr(500, "orch-queue/develop-9-abc", "Merge queue: #7", merged=at(1, 20))])
    report = audit.run(ws, gh, 14, now=NOW)
    # 01:00-01:20 is short; from 01:20 to 09:40 it stands still
    assert [(s["start"], s["end"]) for s in report["still"]] == [(at(1, 20), NOW)]


def test_a_mark_github_did_not_say_is_not_counted_as_past(ws):
    entry(ws, 1, at(22), at(22, 5))
    gh = AuditGitHub([pr(3)])
    gh.has_mark = lambda repo, sha: None
    b = audit.run(ws, gh, 14, now=NOW)["bases"][0]
    assert b["past"] == [] and [r["number"] for r in b["unsure"]] == [3]


def test_a_merge_by_a_person_also_ends_a_stand_still(ws):
    entry(ws, 1, at(1, 0), at(1, 50), state=store.OUT)  # left without a merge of its own
    gh = AuditGitHub([pr(4, merged=at(1, 25))], marked={f"{4:040d}"})
    assert audit.run(ws, gh, 14, now=NOW)["still"] == []  # 25 + 25 minutes, neither long enough


def test_github_not_answering_is_said_not_counted(ws):
    entry(ws, 1, at(22), at(22, 5))
    gh = AuditGitHub(None)
    report = audit.run(ws, gh, 14, now=NOW)
    assert report["bases"] == [] and report["unknown"] == [f"{REPO} develop"]
    assert "did not answer" in audit.text(report)


def test_the_audit_command_prints_json(ws, monkeypatch, capsys):
    entry(ws, 1, at(22), at(22, 5))
    monkeypatch.setattr(cli, "_github", lambda: AuditGitHub([pr(1)]))
    monkeypatch.chdir(ws)
    assert cli.main(["queue", "audit", "--hours", "24", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["bases"][0]["past"][0]["number"] == 1 and got["still"] == []
    assert cli.main(["queue", "audit", "--hours", "0"]) == 2
