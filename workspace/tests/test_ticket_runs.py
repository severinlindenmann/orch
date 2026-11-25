"""Runs as records on a ticket and add-on lines (history.md 'Runs', 'Add-on lines'; #1781, #1783)."""

import json

from orch import runs, tickets

EV = '{"type":"note","ref":"posted it"}'


def _line(proj, tid, text, by):
    tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, by, text), by=by)


def _new(proj, run):
    tid = json.loads(run("ticket", "new", "Plan the launch", "--json", "--by", "human:t")[1])["id"]
    run("check", "add", tid, "Write the post", "--by", "human:t")
    return tid


def test_a_run_record_starts_once_ends_with_minutes_and_keeps_its_tasks(proj, run, monkeypatch):
    tid = _new(proj, run)
    rev = tickets.load(proj, tid)["revision"]
    tickets.run_started(proj, tid, "r_abcd1234", "claude")
    tickets.run_started(proj, tid, "r_abcd1234", "claude")  # a drained extra turn: still one record
    t = tickets.load(proj, tid)
    assert [r["id"] for r in t["runs"]] == ["r_abcd1234"] and t["runs"][0]["agent"] == "claude"
    assert t["revision"] == rev  # the run's own record never looks like a person's edit
    monkeypatch.setenv("ORCH_RUN", "r_abcd1234")
    tickets.check_done(proj, tid, "c1", [EV], "agent:claude")
    monkeypatch.delenv("ORCH_RUN")
    tickets.run_ended(proj, tid, "r_abcd1234")
    r = tickets.load(proj, tid)["runs"][0]
    assert r["tasks"] == ["c1"] and r["minutes"] == 0 and r["ended"] >= r["started"]
    tickets.run_ended(proj, tid, "r_abcd1234")
    assert tickets.load(proj, tid)["runs"][0]["ended"] == r["ended"]


def test_a_bad_run_id_or_an_unknown_run_writes_nothing(proj, run, monkeypatch):
    tid = _new(proj, run)
    tickets.run_started(proj, tid, "nope", "claude")
    tickets.run_ended(proj, tid, "r_unknown1")
    monkeypatch.setenv("ORCH_RUN", "r_unknown1")
    tickets.check_done(proj, tid, "c1", [EV], "agent:claude")
    assert "runs" not in tickets.load(proj, tid)


def test_the_ticket_keeps_the_last_fifty_runs(proj, run):
    tid = _new(proj, run)
    for i in range(tickets.RUNS_KEPT + 3):
        tickets.run_started(proj, tid, f"r_run{i:05d}", "claude")
    ids = [r["id"] for r in tickets.load(proj, tid)["runs"]]
    assert len(ids) == tickets.RUNS_KEPT and ids[0] == "r_run00003"


def test_a_line_from_an_add_on_command_names_the_add_on(proj, run, monkeypatch):
    tid = _new(proj, run)
    monkeypatch.setenv("ORCH_ADDON", "automation")
    _line(proj, tid, "Repeat ran", "system")
    _line(proj, tid, "I looked", "human:anna")  # a person's line is theirs, never the add-on's
    monkeypatch.setenv("ORCH_VIA", "dashboard")
    _line(proj, tid, "From the page", "agent:x")  # a page's line says where it came from instead
    monkeypatch.delenv("ORCH_VIA")
    monkeypatch.setenv("ORCH_RUN", "r_abcd1234")
    _line(proj, tid, "Inside a run", "agent:claude")  # a helper run is the helper's
    tagged = [(h["text"], h.get("addon")) for h in tickets.load(proj, tid)["history"] if "addon" in h]
    assert tagged == [("Repeat ran", "automation")]


def test_a_bad_add_on_name_is_not_written(proj, run, monkeypatch):
    tid = _new(proj, run)
    monkeypatch.setenv("ORCH_ADDON", "Bad Name!")
    _line(proj, tid, "Something", "system")
    assert all("addon" not in h for h in tickets.load(proj, tid)["history"])


def test_the_helper_never_inherits_the_add_on_that_started_it(proj, monkeypatch):
    monkeypatch.setenv("ORCH_ADDON", "automation")
    monkeypatch.setenv("ORCH_VIA", "dashboard")
    env = runs._agent_environ(proj)
    assert "ORCH_ADDON" not in env and "ORCH_VIA" not in env and env["ORCH_ROOT"] == str(proj)
