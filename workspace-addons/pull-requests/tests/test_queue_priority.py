"""ORCH-813: the pull requests of higher priority tickets go into the next queue group first; within one priority
the line order stays."""

from __future__ import annotations

from orch import tickets
from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import runner, store


def ticket(ws, priority=None):
    t = tickets.create(ws, "Some work", "human:tester")
    if priority:
        tickets.set_priority(ws, t["id"], priority, "human:tester")
    return t["id"]


def add(ws, n, tid):
    store.add(ws, url(n), tid, "agent:t", login="bot")


def config(ws):
    (ws / ".orch" / "config.toml").write_text(
        "[pull_requests]\nmax_group = 2\nmerge_alone = false\noverlap = false\n"
    )


def test_a_high_priority_ticket_goes_into_the_next_group_before_older_ones(ws):
    config(ws)
    add(ws, 1, ticket(ws))
    add(ws, 2, ticket(ws, "low"))
    add(ws, 3, ticket(ws))
    add(ws, 4, ticket(ws, "high"))
    gh = FakeGitHub({1: {}, 2: {}, 3: {}, 4: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert [gh.groups[c] for c in calls] == [[4, 1], [3, 2]]
    assert set(states(ws).values()) == {"merged"}


def test_without_priorities_the_line_order_stays(ws):
    rows = [{"url": url(n), "ticket": ticket(ws)} for n in (1, 2, 3)] + [{"url": url(4), "ticket": None}]
    assert [r["url"] for r in runner.by_priority(ws, rows)] == [url(1), url(2), url(3), url(4)]


def test_an_unknown_ticket_counts_as_normal(ws):
    rows = [{"url": url(1), "ticket": "t_gone00"}, {"url": url(2), "ticket": ticket(ws, "high")}]
    assert [r["url"] for r in runner.by_priority(ws, rows)] == [url(2), url(1)]


def test_a_high_priority_ticket_in_another_repository_goes_first(ws):
    config(ws)
    store.add(ws, "https://github.com/acme/other/pull/1", ticket(ws), "agent:t", login="bot")
    add(ws, 2, ticket(ws, "high"))
    r, _ = make(ws, FakeGitHub({2: {}}), FakeGit())
    batch = r.next_batch()
    assert [e["url"] for e in batch] == [url(2)]
