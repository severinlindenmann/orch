"""`orch pull-requests queue stats` (ORCH-554): runs per merged pull request, minutes from ready to merged, baseline."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from orch_pull_requests import cli, stats, store

REPO = "acme/app"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


class StatsGitHub:
    def __init__(self, runs, merged, fail=False):
        self._runs, self._merged, self.fail, self.asked = runs, merged, fail, []

    def runs(self, repo, workflow, since, until):
        self.asked.append(("runs", repo, workflow, since, until))
        return None if self.fail else self._runs

    def merged_ready(self, repo, base, since, until):
        self.asked.append(("merged", repo, base, since, until))
        return self._merged


def merged(n, merged_at, created, ready=None, head="feat/x"):
    return {"number": n, "url": f"https://github.com/{REPO}/pull/{n}", "headRefName": head,
            "createdAt": created, "mergedAt": merged_at, "readyAt": ready}  # fmt: skip


def runs(**by_event):
    return [{"event": e} for e, n in by_event.items() for _ in range(n)]


def sample():
    return StatsGitHub(
        runs(pull_request=10, push=2),
        [
            merged(1, "2026-11-18T10:30:00Z", "2026-11-18T10:00:00Z"),  # never a draft: 30 min
            merged(2, "2026-11-18T12:00:00Z", "2026-11-18T08:00:00Z", ready="2026-11-18T11:00:00Z"),  # 60 min
            merged(3, "2026-11-18T13:30:00Z", "2026-11-18T12:00:00Z"),  # 90 min
            merged(
                9, "2026-11-18T13:00:00Z", "2026-11-18T12:30:00Z", head="orch-queue/develop-1-abc"
            ),  # a group
        ],
    )


def test_counts_runs_per_merged_pull_request_and_minutes_from_ready(ws):
    gh = sample()
    r = stats.run(ws, gh, date(2026, 11, 18), repo=REPO, now=NOW)
    assert r["runs"] == 12 and r["merged"] == 3  # the queue group is not a merge of its own
    assert r["runs_per_merge"] == 4.0
    assert r["ready_to_merged_minutes"] == {"middle": 60.0, "slowest_tenth": 90.0, "count": 3}
    assert r["by_event"] == {"pull_request": 10, "push": 2}
    assert ("runs", REPO, "ci.yml") == gh.asked[0][:3]


def test_the_day_is_local_and_until_cuts_it(ws, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Zurich")
    import time

    time.tzset()
    try:
        start, end = stats.window(date(2026, 11, 18), "14:10", now=NOW)
        assert (start, end) == (
            datetime(2026, 11, 17, 23, 0, tzinfo=UTC),
            datetime(2026, 11, 18, 13, 10, tzinfo=UTC),
        )
        start, end = stats.window(date(2026, 11, 19), now=NOW)  # not over yet: ends now
        assert end == NOW
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_until_must_be_a_time(ws):
    with pytest.raises(store.Refused):
        stats.window(date(2026, 11, 18), "soon")


def test_baseline_is_saved_and_shown_next_to_a_later_day(ws):
    stats.save_baseline(ws, stats.run(ws, sample(), date(2026, 11, 18), repo=REPO, now=NOW))
    later = stats.run(ws, StatsGitHub(runs(pull_request=3), [merged(4, "2026-11-19T10:30:00Z", "2026-11-19T10:00:00Z")]),
                      date(2026, 11, 19), repo=REPO, now=NOW)  # fmt: skip
    out = stats.text(later, stats.baseline(ws))
    assert "Runs per merged pull request: 3.0" in out
    assert "Baseline 18 Nov 2026" in out and "4.0 runs per merged pull request" in out


def test_no_baseline_when_github_did_not_answer(ws):
    r = stats.run(ws, StatsGitHub([], [merged(1, "2026-11-18T10:30:00Z", "2026-11-18T10:00:00Z")], fail=True),
                  date(2026, 11, 18), repo=REPO, now=NOW)  # fmt: skip
    assert r["runs"] is None and r["runs_per_merge"] is None
    with pytest.raises(store.Refused):
        stats.save_baseline(ws, r)
    assert stats.baseline(ws) is None
    assert "not known" in stats.text(r, None)


def test_no_repository_known_is_refused_in_plain_words(ws):
    with pytest.raises(store.Refused, match="--repo"):
        stats.run(ws, sample(), date(2026, 11, 18), now=NOW)


def test_cli_saves_the_baseline_and_prints_json(ws, monkeypatch, capsys):
    monkeypatch.chdir(ws)
    monkeypatch.setattr(cli, "_github", sample)
    args = ["queue", "stats", "--day", "2026-11-18", "--repo", REPO]
    assert cli.main([*args, "--save-baseline"]) == 0
    assert "Saved as the baseline." in capsys.readouterr().out
    assert cli.main([*args, "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["runs_per_merge"] == 4.0 and got["baseline"]["day"] == "2026-11-18"
    assert cli.main(["queue", "stats", "--day", "18 Nov"]) == 2
