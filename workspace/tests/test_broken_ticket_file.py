"""ORCH-2019: a ticket file with no valid JSON (a hand typo, an empty file) is never left out silently. `orch
ticket list`, `orch ticket show` and `orch doctor` name the file and say how to fix it, and nothing rewrites
it (R8.2)."""

import json
import shutil

import pytest

from orch import adapters, addons, ticketindex, tickets

FIX = "fix the JSON by hand or restore it from git"


@pytest.fixture
def broken(proj, run):
    """(id, key, path) of a ticket whose file gets the given text, beside one good ticket."""
    run("init")

    def _b(text):
        code, out, err = run("ticket", "new", "Broken one", "--json", "--by", "human:t")
        assert code == 0, err
        t = json.loads(out)
        assert run("ticket", "new", "Good one", "--by", "human:t")[0] == 0
        p = tickets.ticket_path(proj, t["id"])
        p.write_text(text(p.read_text(encoding="utf-8")), encoding="utf-8")
        return t["id"], t["key"], p

    return _b


TYPO = pytest.param(lambda good: good.replace('"title"', "title", 1), id="typo")
EMPTY = pytest.param(lambda good: "", id="empty")


@pytest.mark.parametrize("text", [TYPO, EMPTY])
def test_list_names_the_broken_file(broken, run, text):
    tid, _, p = broken(text)
    before = p.read_bytes()
    code, out, _ = run("ticket", "list")
    assert code == 0
    assert "Good one" in out and "Broken one" not in out
    assert f".orch/tickets/{tid}.json is broken" in out and FIX in out
    assert p.read_bytes() == before  # never repaired or rewritten


def test_list_with_only_a_broken_file_points_at_it(proj, run):
    run("init")
    code, out, _ = run("ticket", "new", "Only one", "--json", "--by", "human:t")
    tid = json.loads(out)["id"]
    tickets.ticket_path(proj, tid).write_text("", encoding="utf-8")
    code, out, _ = run("ticket", "list")
    assert code == 0 and "No open tickets." in out and f"{tid}.json is broken" in out
    assert "create one" not in out and f"Next: {FIX}: .orch/tickets/{tid}.json" in out


@pytest.mark.parametrize("text", [TYPO, EMPTY])
def test_show_by_id_says_the_file_is_broken(broken, run, text):
    tid, _, _ = broken(text)
    code, _, err = run("ticket", "show", tid)
    assert code != 0
    assert f".orch/tickets/{tid}.json is broken" in err and FIX in err
    assert "doesn't exist" not in err and "being updated" not in err


def test_show_by_key_finds_the_broken_file_that_names_it(broken, run):
    tid, key, _ = broken(lambda good: good.replace('"title"', "title", 1))
    code, _, err = run("ticket", "show", key.lower())
    assert code != 0
    assert f"Ticket {key} can't be read" in err and f"{tid}.json is broken" in err and FIX in err


def test_show_by_key_of_an_empty_file_names_the_broken_files(broken, run):
    tid, key, _ = broken(lambda good: "")
    code, _, err = run("ticket", "show", key)
    assert code != 0
    assert f"{tid}.json" in err and FIX in err


def test_show_of_an_unknown_key_without_broken_files_is_unchanged(proj, run):
    run("init")
    code, _, err = run("ticket", "show", "ZZ-99")
    assert code != 0 and "doesn't exist" in err and FIX not in err


@pytest.mark.parametrize("text", [TYPO, EMPTY])
def test_doctor_reports_the_broken_file(broken, run, monkeypatch, text):
    monkeypatch.setattr(
        adapters, "detect", lambda **_: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}")
    monkeypatch.setattr(addons, "_which_uv", lambda: "/usr/bin/uv")
    tid, _, p = broken(text)
    before = p.read_bytes()
    code, out, _ = run("doctor")
    assert code == 0
    assert f".orch/tickets/{tid}.json is broken" in out and FIX[:1].upper() + FIX[1:] + "." in out
    assert "Nothing wrong." not in out
    assert p.read_bytes() == before


def test_an_index_from_before_learns_which_files_are_broken(broken, proj):
    tid, _, _ = broken(lambda good: "")
    ticketindex.rows(proj)
    ip = ticketindex.index_path(proj)
    data = json.loads(ip.read_text(encoding="utf-8"))
    del data["files"][tid]["broken"]  # an entry written by an orch before ORCH-2019
    ip.write_text(json.dumps(data), encoding="utf-8")
    assert ticketindex.broken(proj) == [f"{tid}.json"]
