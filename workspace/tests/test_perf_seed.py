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


def test_refuses_a_folder_that_is_not_throwaway(proj, run):
    seed = _seed_module()
    with pytest.raises(SystemExit, match="not under"):
        seed.refuse_unsafe(seed.real_home() / "workspace-not-a-test")
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
