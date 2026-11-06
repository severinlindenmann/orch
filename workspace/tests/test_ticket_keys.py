"""Ticket keys (contracts/local-files.md "Ticket keys"): DM1-12 for people, the t_ id stays the identity."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import CONTRACTS

from orch import config, tickets
from orch.errors import Refused

VEC = json.loads((CONTRACTS / "vectors" / "ticket-key-v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("name", "want"), VEC["suggest"])
def test_suggest_code_matches_contract_vector(name, want):
    assert config.suggest_code(name) == want


def test_new_ticket_gets_key_and_counter(proj, run, validate):
    config.set_code(proj, "dm1")
    code, out, _ = run("ticket", "new", "First", "--json", "--by", "human:tester")
    t1 = json.loads(out)
    assert code == 0 and t1["key"] == "DM1-1" and t1["id"].startswith("t_")
    validate(t1)
    code, out, _ = run("ticket", "new", "Second", "--by", "human:tester")
    assert code == 0 and out.startswith('Created DM1-2 "Second"') and "orch check add DM1-2" in out
    assert json.loads((proj / ".orch" / "ticket-counter.json").read_text()) == {"last": 2}


def test_sub_ticket_gets_key(proj, run):
    config.set_code(proj, "MEC")
    parent = tickets.create(proj, "Parent", "human:tester")
    code, out, _ = run("ticket", "new", "Child", "--parent", "mec-1", "--json", "--by", "human:tester")
    child = json.loads(out)
    assert code == 0 and child["key"] == "MEC-2" and child["parent"] == parent["id"]


def test_no_code_takes_folder_suggestion_and_saves_it(proj):
    t = tickets.create(proj, "x", "human:tester")
    want = config.suggest_code(proj.resolve().name)
    assert t["key"] == f"{want}-1" and config.workspace_code(proj) == want


def test_counter_concurrent_creates_get_distinct_numbers(proj):
    config.set_code(proj, "AB")
    with ThreadPoolExecutor(8) as pool:
        made = list(pool.map(lambda i: tickets.create(proj, f"t{i}", "human:tester"), range(16)))
    assert sorted(int(t["key"].split("-")[1]) for t in made) == list(range(1, 17))


def test_numbers_never_reused_and_code_change_keeps_old_keys(proj, run):
    config.set_code(proj, "AB")
    a = tickets.create(proj, "a", "human:tester")
    b = tickets.create(proj, "b", "human:tester")
    tickets.ticket_path(proj, b["id"]).unlink()  # a deleted ticket's number stays gone
    assert run("config", "set", "workspace.code", "xy")[0] == 0
    c = tickets.create(proj, "c", "human:tester")
    assert c["key"] == "XY-3"
    assert tickets.load(proj, a["id"])["key"] == "AB-1"


def test_counter_catches_up_with_existing_keys(proj):
    """A lost or older counter file never hands out a number a ticket already has."""
    config.set_code(proj, "AB")
    for _ in range(3):
        tickets.create(proj, "x", "human:tester")
    (proj / ".orch" / "ticket-counter.json").write_text('{"last": 1}')
    assert tickets.create(proj, "y", "human:tester")["key"] == "AB-4"


def test_key_works_wherever_an_id_does(proj, run):
    config.set_code(proj, "DM1")
    t = tickets.create(proj, "Work", "human:tester")
    other = tickets.create(proj, "Blocker", "human:tester")
    assert run("check", "add", "dm1-1", "step one")[0] == 0
    assert run("log", "DM1-1", "hello")[0] == 0
    assert run("ticket", "wait", "DM1-1", "--on", "ticket:dm1-2")[0] == 0
    got = tickets.load(proj, t["id"])
    assert got["checklist"][0]["text"] == "step one"
    assert got["waiting_on"] == {"kind": "ticket", "ref": other["id"]}
    code, out, _ = run("ticket", "show", "dm1-1", "--json")
    assert code == 0 and json.loads(out)["key"] == "DM1-1"
    code, out, _ = run("ticket", "show", "DM1-1")
    assert out.startswith("DM1-1  Work  [")


def test_unknown_key_is_refused(proj, run):
    config.set_code(proj, "DM1")
    tickets.create(proj, "Work", "human:tester")
    code, _, err = run("ticket", "show", "DM1-9")
    assert code == 2 and "Ticket DM1-9 doesn't exist" in err
    with pytest.raises(Refused):
        tickets.resolve(proj, "dm1-9")
    assert tickets.resolve(proj, "t_abcdef") == "t_abcdef"  # ids pass through unchanged


def test_list_shows_key_first_and_old_tickets_none(proj, run):
    config.set_code(proj, "DM1")
    tickets.create(proj, "Keyed", "human:tester")
    old = tickets.create(proj, "Old one", "human:tester")
    p = tickets.ticket_path(proj, old["id"])
    raw = json.loads(p.read_text())
    del raw["key"]
    p.write_text(json.dumps(raw))
    code, out, _ = run("ticket", "list")
    lines = out.splitlines()
    assert code == 0
    assert any(ln.startswith("DM1-1  Keyed") for ln in lines)
    assert any(ln.startswith("Old one") for ln in lines)


def test_init_code_option_and_suggestion(proj, run):
    code, out, _ = run("init", "--yes", "--code", "mec")
    assert code == 0 and config.workspace_code(proj) == "MEC" and "Ticket keys MEC-1" in out
    assert run("init", "--yes")[0] == 0 and config.workspace_code(proj) == "MEC"  # kept on a rerun
    code, _, err = run("init", "--yes", "--code", "TOOLONG")
    assert code == 2 and "2 to 4 letters or digits" in err


def test_config_code_refuses_bad_value(proj, run):
    code, _, err = run("config", "set", "workspace.code", "a")
    assert code == 2 and "2 to 4 letters or digits" in err
    code, out, _ = run("config", "get", "workspace.code", "--json")
    assert json.loads(out) == {"workspace.code": None}
