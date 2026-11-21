"""ORCH-417: the person picked in the dashboard ("You: <name>") is who works here, everywhere; a helper works
for the person who started its run ("Agent - Severin") or on its own ("Agent")."""

import json

import pytest

from orch import history, people, runs, tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def pick(root, name):
    p = people.home_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({people.key(root): name}), encoding="utf-8")


@pytest.fixture
def no_run_env(monkeypatch):
    for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT", "ORCH_ROOT"):
        monkeypatch.delenv(k, raising=False)


def as_run(monkeypatch, root, tid, started_by, agent="claude"):
    """This process is the helper of a run of `tid` that `started_by` started."""
    rec = {"run": "r_testrun1", "ticket": tid, "by": started_by, "agent": agent, "mode": "live"}
    p = runs.record_path(root, tid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_RUN", "r_testrun1")
    monkeypatch.setenv("ORCH_TICKET", tid)
    monkeypatch.setenv("ORCH_AGENT", agent)


def test_terminal_uses_the_pick(proj, run, new_ticket, no_run_env):
    tid = new_ticket()
    run("log", tid, "before")
    assert read(proj, tid)["history"][-1]["by"] != "human:Severin"
    pick(proj, "Severin")
    run("log", tid, "after")
    assert read(proj, tid)["history"][-1]["by"] == "human:Severin"


def test_new_ticket_owner_is_the_pick(proj, run, no_run_env):
    code, out, _ = run("ticket", "new", "Nobody picked", "--json")
    assert code == 0 and "owner" not in read(proj, json.loads(out)["id"])
    pick(proj, "Severin")
    code, out, _ = run("ticket", "new", "Picked", "--json")
    assert read(proj, json.loads(out)["id"])["owner"] == "Severin"
    code, out, _ = run("ticket", "new", "Typed owner", "--owner", "Anna", "--json")
    assert read(proj, json.loads(out)["id"])["owner"] == "Anna"  # a typed owner wins
    code, out, _ = run("ticket", "new", "Other person", "--by", "human:tester", "--json")
    assert "owner" not in read(proj, json.loads(out)["id"])  # only the picked person is made owner


def test_helper_started_by_a_person_works_for_them(proj, run, new_ticket, monkeypatch, no_run_env):
    tid = new_ticket()
    as_run(monkeypatch, proj, tid, "human:Severin")
    assert run("log", tid, "helper note")[0] == 0
    line = read(proj, tid)["history"][-1]
    assert line["by"] == "agent:claude" and line["for"] == "Severin"
    assert history.author(line) == "agent:claude for Severin"
    code, out, _ = run("ticket", "new", "Made by the helper", "--json")
    assert code == 0 and read(proj, json.loads(out)["id"])["owner"] == "Severin"
    code, out, _ = run("ticket", "show", tid)
    assert "agent:claude for Severin: helper note" in out


def test_helper_on_its_own_is_just_agent(proj, run, new_ticket, monkeypatch, no_run_env):
    pick(proj, "Severin")  # a pick does not make an automation run work for that person
    tid = new_ticket()
    as_run(monkeypatch, proj, tid, "agent:automation")
    assert run("log", tid, "automation note")[0] == 0
    line = read(proj, tid)["history"][-1]
    assert line["by"] == "agent:claude" and "for" not in line
    code, out, _ = run("ticket", "new", "Made on its own", "--json")
    assert "owner" not in read(proj, json.loads(out)["id"])


def test_helper_started_by_hand_works_for_the_pick(proj, run, new_ticket, monkeypatch, no_run_env):
    tid = new_ticket()
    pick(proj, "Severin")
    monkeypatch.setenv("CLAUDECODE", "1")  # no ORCH_RUN: a person started this helper by hand
    run("log", tid, "by hand")
    line = read(proj, tid)["history"][-1]
    assert line["by"] == "agent:claude" and line["for"] == "Severin"


def test_other_labels_are_not_stamped(proj, run, new_ticket, monkeypatch, no_run_env):
    tid = new_ticket()
    as_run(monkeypatch, proj, tid, "human:Severin")
    run("log", tid, "as another helper", "--by", "agent:codex")
    assert "for" not in read(proj, tid)["history"][-1]


def test_unproven_for_is_never_shown():
    line = {"at": "2026-11-18T08:00:00Z", "by": "agent:claude", "for": "Mallory", "text": "x"}
    assert history.line_needs_proof(line)
    shown = history._demoted_line(line)
    assert "for" not in shown and shown["by"] == history.SYNC_BY
    assert not history.line_needs_proof({"by": "agent:claude", "text": "x"})


def test_ticket_with_for_is_valid(proj, run, new_ticket, monkeypatch, no_run_env, validate):
    tid = new_ticket()
    as_run(monkeypatch, proj, tid, "human:Severin")
    run("log", tid, "helper note")
    validate(read(proj, tid))
    assert tickets.load(proj, tid)["history"][-1]["for"] == "Severin"
