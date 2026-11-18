"""A fix for a release (label "fix for release N", ORCH-552) goes first and is checked alone: no other change
rides along into the N.1 release."""

from __future__ import annotations

from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import runner, store


def add(ws, n, **kw):
    store.add(ws, url(n), None, "agent:t", login="bot", base="develop", **kw)


def test_admit_reads_the_fix_label(ws):
    class Labelled(FakeGitHub):
        def pr(self, u):
            v = super().pr(u)
            n = int(u.rsplit("/", 1)[1])
            v["labels"] = [{"name": "Fix for release 33"}] if n == 2 else [{"name": "urgent"}]
            return v

    gh = Labelled({1: {}, 2: {}})
    assert runner.admit(ws, gh, url(2)) == {"base": "develop", "login": "bot", "fix_release": 33}
    assert "fix_release" not in runner.admit(ws, gh, url(1))


def test_a_release_fix_goes_first_and_alone(ws):
    for n in (1, 2, 3):
        add(ws, n)
    add(ws, 4, fix_release=33)  # added last
    gh = FakeGitHub({n: {} for n in (1, 2, 3, 4)})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert calls[0] == url(4)  # alone, to the core waiter, before the rest
    assert all(4 not in members for members in gh.groups.values())
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged", 4: "merged"}


def test_without_a_fix_the_line_still_groups(ws):
    for n in (1, 2, 3):
        add(ws, n)
    gh = FakeGitHub({n: {} for n in (1, 2, 3)})
    make(ws, gh, FakeGit())[0].run()
    assert any(len(m) == 3 for m in gh.groups.values())
