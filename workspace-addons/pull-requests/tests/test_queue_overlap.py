"""The next group while one runs (ORCH-432): built on top of the running group's commit, checked at the same time,
merged only after the group before it merged. Real git and the real core waiter, as in test_queue_safety."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import test_queue_safety as qs
from orch import prwait
from test_queue_safety import Src, add, make, nothing_left_behind, out, states

from orch_pull_requests import runner, store

world = qs.world  # the same stand-in for GitHub, with real git


@pytest.fixture(autouse=True)
def groups_of_two(monkeypatch):
    monkeypatch.setattr(runner.settings, "max_group", lambda root: 2)


def overlapping(w, seen: dict):
    """A waiter that gives the next group time to be built while a group runs, and lets a group on top of
    another wait until that one ended (stopped, or merged). seen['most']: most groups open at once."""

    def waiter(u, before_merge, merge=True, stop=None):
        end = time.monotonic() + 10
        if stop is None:  # a group that may get one on top of it: give it a moment to be built
            mine = list(w.groups).index(u) if u in w.groups else -1
            while len(w.groups) <= mine + 1 and time.monotonic() < end - 9.5:
                time.sleep(0.01)
        else:  # on top of another: wait until that one ended
            while not stop() and any(g["state"] == "OPEN" for x, g in w.groups.items() if x != u):
                if time.monotonic() > end:
                    break
                time.sleep(0.01)
        seen["most"] = max(seen.get("most", 0), len(w.open_groups()))
        return prwait.run_one(u, merge, src=Src(w, u), before_merge=before_merge, stop=stop)

    return waiter


def _config(ws: Path, text: str) -> None:
    (ws / ".orch" / "config.toml").write_text(text, encoding="utf-8")


def test_the_next_group_is_checked_on_top_of_the_running_one(ws, world):
    seen: dict = {}
    add(ws, 1, 2, 3, 4)
    make(ws, world, waiter=overlapping(world, seen)).run()
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged", 4: "merged"}
    first, second = world.groups.values()
    assert first["members"] == [1, 2] and second["members"] == [3, 4]
    assert seen["most"] == 2  # both groups' checks ran at the same time
    # built on the first group's own commit, not on develop after it merged
    parents = out(world.bare, "rev-list", "--parents", "-n", "1", second["head"]).split()
    assert out(world.bare, "merge-base", first["head"], second["head"]) == first["head"]
    assert first["head"] in out(world.bare, "rev-list", second["head"]).split() and len(parents) >= 2
    assert all(world.landed(n) for n in (1, 2, 3, 4))
    nothing_left_behind(ws, world)


def test_a_red_group_stops_the_one_on_top_and_costs_it_no_try(ws, world):
    world.bad = {1}
    seen: dict = {}
    logs: list[str] = []
    add(ws, 1, 2, 3, 4)
    make(ws, world, waiter=overlapping(world, seen), logs=logs).run()
    assert any(x.startswith("Next group on top of") for x in logs)
    assert any("before it was not merged" in x for x in logs), logs
    assert states(ws) == {1: "out", 2: "merged", 3: "merged", 4: "merged"}
    assert not world.landed(1) and all(world.landed(n) for n in (2, 3, 4))
    rows = {r["number"]: r for r in store.read(ws)}
    assert not rows[3].get("tries") and not rows[4].get("tries")  # stopped on top of a red group: no try
    nothing_left_behind(ws, world)


def test_overlap_off_checks_one_group_at_a_time(ws, world):
    _config(ws, "[pull_requests]\noverlap = false\n")
    seen: dict = {}
    add(ws, 1, 2, 3, 4)
    make(ws, world, waiter=overlapping(world, seen)).run()
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged", 4: "merged"}
    assert seen["most"] == 1
    nothing_left_behind(ws, world)


def test_trouble_with_the_group_on_top_uses_no_try(ws, world):
    seen: dict = {}
    add(ws, 1, 2, 3, 4)
    r = make(ws, world, waiter=overlapping(world, seen))
    real = r.make_git
    built = []

    def flaky(repo):
        g = real(repo)
        if r._ahead is not None and not built:  # the first group on top of another cannot be built
            built.append(1)

            def broken(*a, **k):
                raise store.Refused("git build failed: a test hiccup")

            g.build = broken
        return g

    r.make_git = flaky
    r.run()
    assert built and states(ws) == {1: "merged", 2: "merged", 3: "merged", 4: "merged"}
    rows = {x["number"]: x for x in store.read(ws)}
    assert not rows[3].get("tries") and not rows[4].get("tries")
