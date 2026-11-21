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


def test_a_pull_request_the_queue_merged_alone_counts_as_the_queues(ws):
    """Owner, ORCH-432 q2: one alone, green, develop did not touch its files: merged by the queue, no group."""
    entry(ws, 5, at(22), at(22, 10))  # the queue's file: merged
    entry(ws, 7, at(22), at(22, 15))  # the queue's file says merged too, but someone merged it by hand first
    gh = AuditGitHub([pr(5), pr(6), pr(7)], marked={f"{5:040d}"})  # only #5's head carries the mark
    b = audit.run(ws, gh, 14, now=NOW)["bases"][0]
    assert [r["number"] for r in b["alone"]] == [5] and [r["number"] for r in b["past"]] == [6, 7]
    assert "1 merged alone by the queue" in audit.text(audit.run(ws, gh, 14, now=NOW))
    assert [r["number"] for r in audit.as_json(audit.run(ws, gh, 14, now=NOW))["bases"][0]["alone"]] == [5]


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
    entry(ws, 1, at(22), at(22, 5), state=store.OUT)  # left the queue, then merged by hand: past it
    monkeypatch.setattr(cli, "_github", lambda: AuditGitHub([pr(1)]))
    monkeypatch.chdir(ws)
    assert cli.main(["queue", "audit", "--hours", "24", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["bases"][0]["past"][0]["number"] == 1 and got["still"] == []
    assert cli.main(["queue", "audit", "--hours", "0"]) == 2


class RunsGitHub(AuditGitHub):
    def __init__(self, merged, runs):
        super().__init__(merged)
        self.rows = runs

    def runs(self, repo, since, until):
        self.window = (since, until)
        return self.rows


def run_row(sha, event="pull_request", branch="feat/x", name="ci"):
    return {"head_sha": sha, "event": event, "head_branch": branch, "name": name}


def test_check_runs_per_merge_count_one_round_per_commit_and_event(ws):
    """ORCH-545: 18 Nov had 365 ci runs for 62 merges; the audit says it in one line."""
    rows = [
        run_row("a"), run_row("a", name="rules"),  # one pull request commit: ci and rules count once
        run_row("b"),
        run_row("g", branch="orch-queue/develop-1-abc"), run_row("g", branch="orch-queue/develop-1-abc", name="rules"),
        run_row("m", event="push", branch="develop"),
        run_row("n", event="schedule", branch="develop"),
    ]  # fmt: skip
    entry(ws, 1, at(22), at(22, 20))  # the audit counts the repositories the queue knows
    gh = RunsGitHub([pr(500, "orch-queue/develop-1-abc", "Merge queue: #1, #2"), pr(1), pr(2)], rows)
    report = audit.run(ws, gh, 14, now=NOW)
    assert report["runs"][REPO] == {
        "pull_requests": 2,
        "groups": 1,
        "pushes": 1,
        "other": 1,
        "incomplete": False,
    }
    assert gh.window == (z(NOW - timedelta(hours=14)), z(NOW))
    assert "check runs: 5 (2.5 per merge): 2 on pull requests, 1 on queue groups, 1 on pushes, 1 other" in (
        audit.text(report)
    )


def test_minutes_from_joining_the_queue_to_merged(ws):
    entry(ws, 1, at(22), at(22, 30))
    entry(ws, 2, at(22), at(23, 30))
    entry(ws, 3, at(22), at(22, 10), state=store.OUT)  # left the queue: not counted
    report = audit.run(ws, RunsGitHub([], None), 14, now=NOW)
    assert report["waited"] == [30, 90]
    out = audit.text(report)
    assert "middle 90 min, longest 90 min (2 merged by the queue)" in out
    assert "check runs: GitHub did not answer" in out
    assert audit.as_json(report)["waited_minutes"] == [30, 90]


def test_a_count_at_githubs_limit_says_at_least(ws):
    entry(ws, 1, at(22), at(22, 20))
    rows = [run_row(f"s{i}") for i in range(1000)]
    report = audit.run(ws, RunsGitHub([pr(1)], rows), 14, now=NOW)
    assert report["runs"][REPO]["incomplete"] and "at least: GitHub lists only 1000 runs" in audit.text(
        report
    )


# -- ORCH-1129: the busiest hour and group start to merged ---------------------------------------------------
def group(n, members, created, merged):
    g = pr(n, f"orch-queue/develop-{n}-abc", "Merge queue: " + ", ".join(f"#{m}" for m in members), merged)
    return {**g, "createdAt": z(created)}


def test_the_busiest_hour_counts_queue_merges_within_60_minutes(ws):
    rows = [group(900, range(1, 21), at(22), at(22, 5))]
    rows += [pr(n, merged=at(22, 5) + timedelta(minutes=3 * n)) for n in range(1, 21)]  # 22:08 .. 23:05
    rows += [pr(21, merged=at(23, 30))]  # not in a group: past the queue, not counted
    entry(ws, 1, at(21))  # the queue knows the repository
    report = audit.run(ws, AuditGitHub(rows), 14, now=NOW)
    h = report["hour"]
    assert h["count"] == 20 and h["start"] == at(22, 8) and h["end"] == at(23, 5)
    assert [r["number"] for r in h["prs"]] == list(range(1, 21))
    out = audit.text(report)
    assert "Busiest hour: 20 merged by the queue" in out and "goal 20: reached" in out
    assert f"https://github.com/{REPO}/pull/20" in out


def test_merges_more_than_an_hour_apart_are_not_one_hour():
    merged = [pr(1, merged=at(22)), pr(2, merged=at(23, 1)), pr(3, merged=at(23, 30))]
    h = audit.busiest_hour(merged)
    assert h["count"] == 2 and [r["number"] for r in h["prs"]] == [2, 3]
    assert audit.busiest_hour([])["count"] == 0


def test_group_minutes_are_the_middle_of_the_last_20_groups(ws):
    rows = [group(900 + i, [i + 1], at(22) + timedelta(minutes=10 * i), at(22) + timedelta(minutes=10 * i + 4))
            for i in range(20)]  # fmt: skip
    rows.insert(0, group(899, [99], at(21), at(21, 30)))  # older than the last 20: left out
    rows[5] = {**rows[5], "createdAt": z(at(22, 39)), "mergedAt": z(at(22, 48))}  # 9 minutes
    entry(ws, 1, at(21))  # the queue knows the repository
    report = audit.run(ws, AuditGitHub(rows), 14, now=NOW)
    g = report["group_minutes"]
    assert len(g["groups"]) == 20 and 899 not in [r["number"] for r in g["groups"]]
    assert g["middle"] == 4.0 and max(r["minutes"] for r in g["groups"]) == 9.0
    assert "middle 4.0 min over the last 20 groups" in audit.text(report)
    assert "goal under 6 min over 20 groups: reached" in audit.text(report)


def test_fewer_than_20_groups_say_not_known_yet(ws):
    rows = [group(900, [1], at(22), at(22, 12)), pr(1, merged=at(22, 12))]
    entry(ws, 1, at(21))  # the queue knows the repository
    report = audit.run(ws, AuditGitHub(rows), 14, now=NOW)
    assert "not known yet, 1 of 20 groups; ask for more hours" in audit.text(report)
    data = audit.as_json(report)
    assert data["group_minutes"]["middle"] == 12.0 and data["hour"]["count"] == 1
    json.dumps(data)


def test_the_goal_is_judged_on_exact_seconds_not_rounded_minutes():
    g = [
        {**pr(n), "createdAt": "2026-11-18T08:00:00Z", "mergedAt": "2026-11-18T08:05:58Z"} for n in range(20)
    ]
    got = audit.group_minutes(g)
    assert got["middle"] < audit.GROUP_GOAL and got["groups"][0]["minutes"] == 6.0


def test_a_group_without_a_start_time_is_left_out():
    assert audit.group_minutes([{**pr(1), "createdAt": None}]) == {"groups": [], "middle": None}
