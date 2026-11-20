"""ORCH-943: one account switcher per computer. Two test workspaces share one temp tool home (ORCH_HOME), with a fake
account switcher: settings are kept once, only one Usage loop switches, a person can take over, a dead owner frees
it, and 100 rounds of both loops never swap the account back and forth. A second tool home is another computer."""

import itertools
import json
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import jrun
from test_switching import T0, never_the_real_switcher, seed  # noqa: F401  (an autouse fixture)

from orch_usage import computer, store, switching
from orch_usage.cli import main


def at(seconds):
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def two(tmp_path, ws, capsys):
    """A second workspace next to `ws` on the same computer, and a runner for each."""
    other = tmp_path / "fernscout"
    (other / ".orch" / "tickets").mkdir(parents=True)

    def runner(root):
        def run(*argv):
            code = main(["--dir", str(root), *argv])
            out = capsys.readouterr()
            return code, out.out, out.err

        return run

    return {"a": ws, "b": other, "run_a": runner(ws), "run_b": runner(other)}


def shared(root) -> Path:
    d = computer.shared_dir(root)
    assert d is not None and d.parent == Path(os.environ["ORCH_HOME"]).resolve()
    return d


# ---------------------------------------------------------------- settings once per computer


def test_a_change_in_one_workspace_shows_in_the_other_with_who_changed_it(two, switcher):
    seed(two["run_a"])
    code, d = jrun(two["run_b"], "list")
    assert code == 0
    first = next(a for a in d["accounts"] if a["label"].startswith("first"))
    assert first["rule"]["limits"][0]["value"] == 95  # set in ws, seen in fernscout
    assert jrun(two["run_b"], "limit", "first", "80%", "--period", "5h", "--by", "human:owner")[0] == 0
    rows = store.history(two["a"])
    assert rows[0]["workspace"] == "fernscout" and "80" in json.dumps(rows[0])
    assert store.usage_dir(two["a"]) == store.usage_dir(two["b"]) == shared(two["a"])


def test_the_page_and_the_history_name_the_workspace_a_change_came_from(two, switcher):
    from orch_usage import page

    seed(two["run_a"])
    assert jrun(two["run_b"], "limit", "first", "80%", "--period", "5h", "--by", "human:owner")[0] == 0
    seen_in_ws = page.history_rows(two["a"])[0]
    assert seen_in_ws["who"] == "You in fernscout" and "80" in seen_in_ws["text"]
    assert page.history_rows(two["b"])[0]["who"] == "You"  # its own change needs no name
    code, out, _ = two["run_a"]("history")
    assert code == 0 and "(by owner in fernscout)" in out.splitlines()[0]


def test_switching_on_is_one_setting_for_the_computer(two):
    assert jrun(two["run_a"], "switching", "on", "--by", "human:owner")[0] == 0
    assert switching.switching_on(two["b"]) is True


def test_old_workspace_files_are_taken_over_once_and_kept_as_they_were(two, switcher):
    seed(two["run_a"])
    accounts = json.loads((shared(two["a"]) / "accounts.json").read_text())
    # fernscout had its own old file: the same accounts with another rule, and one account only it knew
    old = json.loads(json.dumps(accounts))
    for a in old["accounts"]:
        a["rule"]["limits"] = [{"value": 50, "unit": "%", "period": "week"}]
    extra = dict(
        old["accounts"][0], id="a_zzzzzz", label="Only here", source={"reader": "none", "key": "k_x"}
    )
    old["accounts"].append(extra)
    loc = computer.local_dir(two["b"])
    loc.mkdir(parents=True)
    (loc / "accounts.json").write_text(json.dumps(old))
    (loc / "history.jsonl").write_text(
        json.dumps({"at": "2026-01-01T00:00:00Z", "who": "usage", "what": "x"}) + "\n"
    )
    before = (loc / "accounts.json").read_text()

    labels = [a["label"] for a in store.load(two["b"])["accounts"]]
    assert "Only here" in labels and len(labels) == len(accounts["accounts"]) + 1
    kept = next(a for a in store.load(two["b"])["accounts"] if a["label"].startswith("first"))
    assert kept["rule"]["limits"][0]["value"] == 95  # the computer's rule won
    took = [r for r in store.history(two["b"]) if r["what"].startswith("took over")]
    assert len(took) == 1 and "kept the rule" in took[0]["after"]
    assert (loc / "accounts.json").read_text() == before and (loc / computer.MOVED).exists()
    # a second look (another process: nothing cached) does not take it again
    store._ENSURED.clear()
    store.load(two["b"])
    assert len([r for r in store.history(two["b"]) if r["what"].startswith("took over")]) == 1


# ---------------------------------------------------------------- the one switcher


def test_only_one_loop_holds_the_switcher(two):
    a = computer.Switcher(two["a"], shared(two["a"]))
    b = computer.Switcher(two["b"], shared(two["b"]))
    try:
        assert a.hold() is True and b.hold() is False
        o = computer.owner(shared(two["a"]))
        assert o["running"] and o["name"] == two["a"].name
        assert switching.following(two["b"], shared(two["b"])) == two["a"].name
        assert switching.following(two["a"], shared(two["a"])) is None
        a.release()
        assert b.hold() is True  # the lock was let go: fernscout switches now
        assert any("(ws stopped)" in r["what"] for r in store.history(two["a"]))
    finally:
        a.release()
        b.release()


def test_the_follower_never_switches_and_says_who_does(two, switcher):
    seed(two["run_a"])
    jrun(two["run_a"], "switching", "on", "--by", "human:owner")
    a = computer.Switcher(two["a"], shared(two["a"]))
    try:
        assert a.hold()
        r = switching.look(two["b"], at(0))
        assert r["did"] == "follow" and r["owner"] == two["a"].name
        assert switcher.changes() == []
        _, out, _ = two["run_b"]("status")
        assert f"{two['a'].name} switches the accounts on this computer" in out
        _, d = jrun(two["run_b"], "switching", "on", "--by", "human:owner")
        assert "orch usage take-over" in d["next"]
    finally:
        a.release()


def test_take_over_is_for_a_person_and_the_old_owner_lets_go(two):
    a = computer.Switcher(two["a"], shared(two["a"]))
    b = computer.Switcher(two["b"], shared(two["b"]))
    try:
        assert a.hold()
        code, d = jrun(two["run_b"], "take-over", "--by", "agent:claude")
        assert code == 2 and "Only a person" in d["error"]
        assert computer.owner(shared(two["a"]))["name"] == two["a"].name
        code, d = jrun(two["run_b"], "take-over", "--by", "human:owner")
        assert code == 0 and d["changed"] is True
        assert b.hold() is False  # ws still holds the lock until its next look
        assert a.hold() is False  # ws sees it was moved and lets go
        assert b.hold() is True
        assert computer.owner(shared(two["a"]))["workspace"] == computer.key(two["b"])
        rows = [r["what"] for r in store.history(two["a"])]
        assert any(w.startswith("fernscout took over switching from ws") for w in rows)
    finally:
        a.release()
        b.release()


def test_a_third_workspace_does_not_grab_a_switcher_a_person_just_moved(two, tmp_path):
    c_root = tmp_path / "third"
    (c_root / ".orch").mkdir(parents=True)
    sd = shared(two["a"])
    a, c = computer.Switcher(two["a"], sd), computer.Switcher(c_root, sd)
    try:
        computer.note_workspace(two["b"], sd)
        assert a.hold()
        computer.take_over(two["b"], sd, "human:owner")
        assert a.hold() is False  # let go
        assert c.hold() is False  # fernscout was just given it and picks it up itself
    finally:
        a.release()
        c.release()


def test_follow_keeps_the_notice_small(two):
    a = computer.Switcher(two["a"], shared(two["a"]))
    try:
        a.hold()
        v = computer.view(two["b"], shared(two["b"]))
        assert v["running"] and not v["mine"] and not v["followed"]
        assert v["words"]["title"] == "ws switches the accounts on this computer"
        code, d = jrun(two["run_b"], "follow", "--by", "human:owner")
        assert code == 0 and d["changed"] is True
        assert computer.view(two["b"], shared(two["b"]))["followed"] is True
        code, d = jrun(two["run_a"], "follow", "--by", "human:owner")
        assert code == 2  # the switcher itself has nothing to follow
    finally:
        a.release()


def test_a_take_over_waits_for_a_switch_in_progress(two, switcher):
    seed(two["run_a"])
    jrun(two["run_a"], "switching", "on", "--by", "human:owner")
    sd = shared(two["a"])
    a = computer.Switcher(two["a"], sd)
    inside, go = threading.Event(), threading.Event()

    def slow_switch(slot):
        inside.set()
        go.wait(10)
        return switching._switch(slot)

    try:
        assert a.hold()
        t = threading.Thread(target=lambda: switching.look(two["a"], at(0), switch=slow_switch))
        t.start()
        assert inside.wait(10)
        done = []
        tb = threading.Thread(target=lambda: done.append(computer.take_over(two["b"], sd, "human:owner")))
        tb.start()
        time.sleep(0.3)
        assert done == []  # the take-over waits for the switch
        go.set()
        t.join(10)
        tb.join(10)
        assert done == [True]
        assert switcher.changes()  # the switch that was running finished
        assert computer.last_switch(sd)["name"] == "ws"
        assert a.hold() is False
    finally:
        go.set()
        a.release()


def test_a_dead_owner_frees_the_switcher_at_once(two):
    sd = shared(two["a"])
    code = (
        "import sys, time; from pathlib import Path; from orch_usage import computer; "
        f"s = computer.Switcher(Path({str(two['a'])!r}), Path({str(sd)!r})); "
        "assert s.hold(); print('held', flush=True); time.sleep(60)"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, env=env, text=True)
    b = computer.Switcher(two["b"], sd)
    try:
        assert p.stdout.readline().strip() == "held"
        assert b.hold() is False and computer.owner(sd)["running"] is True
        p.kill()  # like a crash: no clean exit
        p.wait(10)
        assert computer.owner(sd)["running"] is False
        assert b.hold() is True  # no waiting for a timeout
        assert computer.owner(sd)["name"] == "fernscout"
    finally:
        if p.poll() is None:
            p.kill()
        b.release()


def test_another_computer_has_its_own_switcher(two, tmp_path, monkeypatch):
    sd1 = shared(two["a"])
    a = computer.Switcher(two["a"], sd1)
    try:
        assert a.hold()
        monkeypatch.setenv("ORCH_HOME", str(Path(os.environ["HOME"]) / "other-computer"))
        sd2 = computer.shared_dir(two["b"])
        assert sd2 is not None and sd2 != sd1
        b = computer.Switcher(two["b"], sd2)
        assert b.hold() is True  # independent: its own lease
        b.release()
    finally:
        a.release()


# ---------------------------------------------------------------- no back-and-forth


def test_two_loops_in_100_rounds_never_swap_the_account_back_and_forth(two, switcher):
    """Both workspaces run their loop's steps alternately for 100 rounds while the work uses up the account in use.
    Only the switcher's loop ever switches, and no account is taken back within the back-and-forth window."""
    seed(two["run_a"])
    jrun(two["run_a"], "switching", "on", "--by", "human:owner")
    sd = shared(two["a"])
    leases = {"a": computer.Switcher(two["a"], sd), "b": computer.Switcher(two["b"], sd)}
    calls = {"a": 0, "b": 0}

    def switch_of(name):
        def go(slot):
            calls[name] += 1
            return switching._switch(slot)

        return go

    use = {1: [10.0, 20.0], 2: [5.0, 30.0], 3: [0.0, 10.0]}
    names = {1: "first", 2: "second", 3: "third"}
    seen = []  # (round, active)
    switcher.use(**{names[n]: tuple(v) for n, v in use.items()})
    try:
        for i in range(100):
            for name in ("a", "b") if i % 2 == 0 else ("b", "a"):
                leases[name].hold()
                switching.look(two[name], at(i * 30), switch=switch_of(name))
            act = switcher.active()
            seen.append((i, act))
            use[act][0] = min(100.0, use[act][0] + 3.0)  # the work uses the account in use
            switcher.use(**{names[n]: tuple(v) for n, v in use.items()})
    finally:
        for lease in leases.values():
            lease.release()
    assert calls["b"] == 0 and calls["a"] >= 1  # only the switcher switched
    changes = [(i, act) for k, (i, act) in enumerate(seen) if k and seen[k - 1][1] != act]
    assert changes, "the work should have forced at least one switch"
    for (i1, a1), (i2, a2) in itertools.pairwise(changes):
        prev = seen[seen.index((i1, a1)) - 1][1]
        if a2 == prev:
            assert (i2 - i1) * 30 >= switching.BACK_MINUTES * 60, f"back to {a2} after {(i2 - i1) * 30} s"
    flips = [r for r in store.history(two["a"]) if r["what"].startswith("another program switched back")]
    assert flips == []


def test_a_helper_cannot_take_over_even_naming_a_person(two, monkeypatch):
    monkeypatch.setenv("ORCH_RUN", "r_test")
    code, d = jrun(two["run_b"], "take-over", "--by", "human:owner")
    assert code == 2 and "Only a person" in d["error"]


def test_a_loop_that_lost_the_switcher_does_not_look(two, switcher):
    seed(two["run_a"])
    jrun(two["run_a"], "switching", "on", "--by", "human:owner")
    sd = shared(two["a"])
    a = computer.Switcher(two["a"], sd)
    try:
        assert a.hold()
        computer.note_workspace(two["b"], sd)
        computer.take_over(two["b"], sd, "human:owner")
        a.release()  # ws let go; fernscout has not picked the lock up yet
        logs, on = [], iter([True, False])
        switching.run_forever(two["a"], once=True, log=logs.append, active=lambda r: next(on))
        assert switcher.changes() == []  # no look, no switch in between
        assert switching.look(two["a"], at(0))["did"] == "follow"  # a single look follows too
    finally:
        a.release()


def test_a_linked_or_broken_old_file_is_not_taken_over(two, tmp_path):
    loc = computer.local_dir(two["b"])
    loc.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"schema": store.SCHEMA, "accounts": []}))
    (loc / "accounts.json").symlink_to(elsewhere)
    (loc / "share.json").write_text("{}")
    store.load(two["b"])
    assert not (shared(two["b"]) / "accounts.json").exists()
    bad = computer.local_dir(two["a"])
    bad.mkdir(parents=True)
    (bad / "accounts.json").write_text(json.dumps({"schema": store.SCHEMA, "accounts": [{"id": "nope"}]}))
    assert store.load(two["a"])["accounts"] == []


# ---------------------------------------------------------------- use of every workspace counts (ORCH-947)


def _key_source(day_limit):
    return [
        {
            "id": "a_key001",
            "label": "OpenAI credit",
            "tool": "codex",
            "type": "api-key",
            "on": True,
            "left": 100.0,
            "day_limit": day_limit,
            "spent_today": 0.0,
            "models": {"sonnet": "gpt-small"},
        },
        {
            "id": "a_sub001",
            "label": "Claude main",
            "tool": "claude",
            "type": "subscription",
            "on": True,
            "week_used": 10.0,
        },
    ]


_KEY_FIRST = {"order": ["a_key001", "a_sub001"], "credit_kinds": ["reviews"]}


def _req(n):
    return {"start": f"s{n}", "ticket": f"ORCH-{n}", "kind": "reviews", "model": "sonnet"}


def test_every_workspace_writes_its_starts_to_the_one_store_of_the_computer(two):
    from orch_usage import picker

    picker.pick(two["a"], _req(1), _KEY_FIRST, _key_source(10.0), T0)
    picker.pick(two["b"], _req(2), _KEY_FIRST, _key_source(10.0), T0)
    assert not (computer.local_dir(two["a"]) / picker.STARTS).exists()
    assert not (computer.local_dir(two["b"]) / picker.STARTS).exists()
    starts = json.loads((shared(two["a"]) / picker.STARTS).read_text(encoding="utf-8"))["starts"]
    assert {k: v["workspace"] for k, v in starts.items()} == {
        "s1": computer.label(two["a"]),
        "s2": computer.label(two["b"]),
    }


def test_a_day_limit_counts_what_both_workspaces_spent(two):
    from orch_usage import picker

    src = _key_source(2.0)  # room for one hold of 1.05, not two
    first = picker.pick(two["a"], _req(1), _KEY_FIRST, src, T0)
    second = picker.pick(two["b"], _req(2), _KEY_FIRST, src, T0)
    assert first.source == "a_key001"
    assert second.source == "a_sub001" and "OpenAI credit at its day limit" in second.why
    day = T0.date().isoformat()
    assert picker.spread(two["b"], day) == picker.spread(two["a"], day)


def test_the_usage_page_shows_the_split_per_workspace_in_both_workspaces(two):
    from orch_usage import picker, spread

    for n, root in enumerate([two["a"], two["b"], two["b"]]):
        picker.pick(root, _req(n), _KEY_FIRST, _key_source(10.0), T0)
    accounts = [{**a, "limits": []} for a in _key_source(10.0)]
    a, b = spread.build(two["a"], accounts, T0), spread.build(two["b"], accounts, T0)
    assert a["starts"] == b["starts"] == 3
    assert (
        a["workspaces"]
        == b["workspaces"]
        == [
            {"name": computer.label(two["b"]), "starts": 2, "dollars": 2.1},
            {"name": computer.label(two["a"]), "starts": 1, "dollars": 1.05},
        ]
    )
    assert sum(w["starts"] for w in a["workspaces"]) == a["starts"]


def test_one_workspace_alone_shows_no_split(two):
    from orch_usage import picker, spread

    picker.pick(two["a"], _req(1), _KEY_FIRST, _key_source(10.0), T0)
    assert spread.build(two["a"], [], T0)["workspaces"] == []
