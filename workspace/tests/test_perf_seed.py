"""The seed script for big test workspaces (e2e/perf/seed.py, ORCH-518): realistic tickets orch reads as its
own, the same workspace for the same seed, and never a folder that is not a throwaway one."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from orch import tickets

SEED = Path(__file__).resolve().parents[2] / "e2e" / "perf" / "seed.py"
NOW = "2026-11-18T12:00:00Z"


def _seed_module():
    spec = importlib.util.spec_from_file_location("perf_seed", SEED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ws(proj: Path, run, name: str) -> Path:
    ws = proj / name
    ws.mkdir()
    import os

    old = Path.cwd()
    os.chdir(ws)
    try:
        assert run("init")[0] == 0
    finally:
        os.chdir(old)
    return ws


def test_seeds_tickets_orch_reads(proj, run, capsys, validate):
    ws = _ws(proj, run, "big")
    seed = _seed_module()
    assert seed.main([str(ws), "--tickets", "300", "--live", "3", "--now", NOW]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["tickets"] == 300 and out["live"] == 3
    listed = tickets.list_all(ws)
    assert len(listed) == 300
    assert {t["status"] for t in listed} >= {"done", "open"}
    assert any(t.get("parent") for t in listed)
    assert any(t["checklist"] and t["checklist"][0]["evidence"] for t in listed)
    for t in listed:
        validate(t)  # the ticket contract (sync refuses a ticket that breaks it)
    for t in listed[:10]:
        assert tickets.load(ws, t["id"])["id"] == t["id"]  # each file passes orch's own reader
    pics = list((ws / ".orch" / "tickets").glob("t_*/artifacts/*.png"))
    assert pics and all(p.stat().st_nlink == 1 for p in pics)  # own files: sync refuses hard links
    assert len(list((ws / ".orch" / "run" / "tickets").glob("t_*.json"))) == 3
    assert any((ws / ".orch" / "tickets").glob("t_*/artifacts/*.png"))
    counter = json.loads((ws / ".orch" / "ticket-counter.json").read_text())
    assert counter["last"] == 300


def test_live_records_name_a_stand_in_never_the_caller(proj, run, capsys):
    """orch stops a live run whose terminal is gone (kill_tree of its pid): with the caller's pid in the
    records that stop ended the measuring script itself and the 10,000-ticket check never finished
    (ORCH-1609)."""
    import os

    seed = _seed_module()
    ws = _ws(proj, run, "live")
    assert seed.main([str(ws), "--tickets", "60", "--live", "3", "--now", NOW]) == 0
    stand_in = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["live_pid"]
    try:
        pids = {json.loads(p.read_text())["pid"] for p in (ws / ".orch" / "run" / "tickets").glob("t_*.json")}
        assert pids == {stand_in}
        assert stand_in not in (os.getpid(), os.getppid())
        os.kill(stand_in, 0)  # running, so the dashboard shows the runs as live
        if hasattr(os, "getsid"):
            # its own session: a stop of its group reaches nothing else
            assert os.getsid(stand_in) == stand_in
    finally:
        seed.stand_in_end(stand_in)


def test_same_seed_same_workspace(proj, run, capsys):
    seed = _seed_module()
    a, b = _ws(proj, run, "a"), _ws(proj, run, "b")
    for ws in (a, b):
        assert seed.main([str(ws), "--tickets", "25", "--live", "0", "--now", NOW]) == 0
    names = lambda ws: sorted(p.name for p in (ws / ".orch" / "tickets").glob("t_*.json"))  # noqa: E731
    assert names(a) == names(b)
    first = names(a)[0]
    ta = json.loads((a / ".orch" / "tickets" / first).read_text())
    tb = json.loads((b / ".orch" / "tickets" / first).read_text())
    ta.pop("key"), tb.pop("key")  # the code comes from the folder name
    assert ta["title"] == tb["title"] and ta["history"] == tb["history"]


def test_refuses_a_folder_that_is_not_throwaway(proj, run, monkeypatch):
    seed = _seed_module()
    # a home outside the temp folder: the test run home is a temp folder (Windows: USERPROFILE)
    home = Path(Path.cwd().anchor) / "home-not-a-test"
    monkeypatch.setattr(seed, "real_home", lambda: home)
    with pytest.raises(SystemExit, match="not under"):
        seed.refuse_unsafe(home / "workspace-not-a-test")
    bare = proj / "bare"
    bare.mkdir()
    with pytest.raises(SystemExit, match="no workspace"):
        seed.refuse_unsafe(bare)


def test_refuses_tickets_it_did_not_seed(proj, run, monkeypatch):
    ws = _ws(proj, run, "own")
    monkeypatch.chdir(ws)
    assert run("ticket", "new", "A real ticket")[0] == 0
    seed = _seed_module()
    with pytest.raises(SystemExit, match="did not seed"):
        seed.refuse_unsafe(ws)


def test_refuses_without_a_strict_orch_home(proj, run, monkeypatch):
    ws = _ws(proj, run, "strict")
    monkeypatch.delenv("ORCH_HOME_STRICT", raising=False)
    seed = _seed_module()
    with pytest.raises(SystemExit, match="ORCH_HOME_STRICT"):
        seed.refuse_unsafe(ws)


def _limits_module():
    import sys

    sys.path.insert(0, str(SEED.parent))  # check_limits imports baseline from its own folder
    spec = importlib.util.spec_from_file_location("perf_check_limits", SEED.parent / "check_limits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_limits_name_every_passed_limit():
    """The CI check at 10,000 tickets (ORCH-525) fails on a slow command, a slow or failed page and a costly
    idle minute, and passes when all are within the owner's limits."""
    mod = _limits_module()
    lim = json.loads((SEED.parent / "limits.json").read_text(encoding="utf-8"))
    assert lim["tickets"] == 10000 and lim["page_seconds"] == 2.0 and lim["idle_minute_bytes"] == 204800
    fast = {"ticket list": 0.4, "needs": 0.6}
    rows = [{"page": "Home", "ms": 900}, {"page": "Idle Home 60 s", "ms": None, "enc": 50_000}]
    assert mod.check(lim, fast, {"rows": rows})[1] == []
    slow = {"ticket list": 5.9, "needs": 0.6}
    rows = [
        {"page": "Home", "ms": 2600},
        {"page": "Tickets board", "ms": None, "err": "page.reload: Timeout"},
        {"page": "Idle Home 60 s", "ms": None, "enc": 14_000_000},
    ]
    bad = mod.check(lim, slow, {"rows": rows})[1]
    assert len(bad) == 4
    assert bad[0].startswith("orch ticket list took 5.9 s")
    assert any(b.startswith("Tickets board was usable after fails") for b in bad)
    assert mod.check(lim, {"ticket list": 0.4}, None)[1] == ["orch needs took None s (limit 1.0 s)"]
    short = [{"page": "Idle Home 20 s", "ms": None, "enc": 100_000}]  # 300 KB a minute
    assert mod.check(lim, fast, {"rows": short})[1] == ["An idle Home minute fetched 293 KB (limit 200 KB)"]


def test_against_develop_fails_only_on_more_than_30_percent_slower():
    """The merge queue's verdict (ORCH-1609, R8.3): never the absolute limit, only >30% (and above the noise
    floor) worse than develop; a page that fails on develop too never fails the group."""
    mod = _limits_module()
    develop = {
        "commands": {"ticket list": 0.6, "needs": 1.4},
        "dash": {
            "rows": [
                {"page": "Home", "ms": 3000},
                {"page": "Search", "ms": 100},
                {"page": "Focus", "ms": None, "err": "Timeout"},
                {"page": "Idle Home 60 s", "ms": None, "enc": 13_000},
            ]
        },
    }
    same = {
        "rows": [
            {"page": "Home", "ms": 3800},  # +27%: over the owner's 2 s, but not a regression
            {"page": "Search", "ms": 250},  # +150%, but only 0.15 s: runner noise
            {"page": "Focus", "ms": None, "err": "Timeout"},  # fails on develop too
            {"page": "Idle Home 60 s", "ms": None, "enc": 30_000},  # doubled, but under 20 KB more
            {"page": "New page", "ms": 9000},  # develop has no number: shown, never fails
        ]
    }
    assert mod.regressions({"ticket list": 0.7, "needs": 1.8}, same, develop)[1] == []
    worse = {"rows": [{"page": "Home", "ms": None, "err": "Timeout"}, {"page": "Search", "ms": 400}]}
    lines, bad = mod.regressions({"ticket list": 0.85, "needs": 1.4}, worse, develop)
    assert bad == [
        "orch ticket list: 0.85 s, +42% against develop (0.60 s)",
        "Home fails here but works on develop (3.00 s)",
        "Search: 0.40 s, +300% against develop (0.10 s)",
    ]
    assert "| orch ticket list | 0.85 s | 0.60 s | +42% |" in lines


def test_against_develop_without_develop_numbers_passes(tmp_path, capsys):
    mod = _limits_module()
    over = ["needs too slow"]
    assert mod.against_develop(tmp_path / "missing.json", {"needs": 9.0}, None, "table\n", over) == 0
    assert "No develop numbers" in capsys.readouterr().out
    (tmp_path / "d.json").write_text(json.dumps({"commands": {"needs": 1.0}, "dash": None}))
    assert mod.against_develop(tmp_path / "d.json", {"needs": 1.5}, None, "table\n", []) == 1
