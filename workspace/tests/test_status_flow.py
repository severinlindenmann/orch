import os

import pytest

from orch import config, runs, tickets
from orch.errors import Refused


@pytest.mark.parametrize("path", ["status", "patch"])
def test_agent_finish(proj, run, new_ticket, path):
    tid = new_ticket()
    args = (
        ("status", tid, "done")
        if path == "status"
        else (
            "patch",
            tid,
            "--if-revision",
            str(tickets.load(proj, tid)["revision"]),
            '{"status":"done"}',
        )
    )
    code, out, err = run("ticket", *args, "--by", "agent:generic")
    assert (code, out, err) == (0, tickets.REVIEW_MESSAGE + "\n", "")
    t = tickets.load(proj, tid)
    assert t["status"] == "review"
    assert any(
        h["by"] == "agent:generic" and h["text"] == "agent:generic finished the work and moved it to Review"
        for h in t["history"]
    )


@pytest.mark.parametrize("patch", [False, True])
@pytest.mark.parametrize("checked", [False, True])
def test_agent_checks(proj, run, new_ticket, patch, checked):
    tid = new_ticket()
    run("check", "add", tid, "Test it")
    t = tickets.load(proj, tid)
    if checked:
        t["checklist"][0]["done"] = True
        tickets.save(proj, t)
    before = tickets.load(proj, tid)
    with pytest.raises(Refused, match="Not done"):
        if patch:
            tickets.patch(proj, tid, before["revision"], '{"status":"done"}', "agent:generic")
        else:
            tickets.set_status(proj, tid, "done", "agent:generic")
    assert tickets.load(proj, tid) == before


@pytest.mark.parametrize("patch", [False, True])
def test_human_done(proj, run, new_ticket, patch):
    tid = new_ticket()
    run("check", "add", tid, "Test it")
    t = tickets.load(proj, tid)
    if patch:
        t = tickets.patch(proj, tid, t["revision"], '{"status":"done"}', "human:tester")
    else:
        t = tickets.set_status(proj, tid, "done", "human:tester")
    assert t["status"] == "done"


def test_switch(proj, run, new_ticket):
    tid = new_ticket()
    assert not config.agents_may_finish(proj)
    assert run("config", "set", "workflow.agents_may_finish", "on")[0] == 0
    assert config.agents_may_finish(proj)
    assert tickets.set_status(proj, tid, "done", "agent:generic")["status"] == "done"
    config.set_agents_may_finish(proj, False)
    assert not config.agents_may_finish(proj)


@pytest.mark.parametrize("status", ["open", "ready", "review", "active", "waiting", "done", "dropped"])
def test_claim_working(proj, new_ticket, status):
    tid = new_ticket()
    tickets.set_status(proj, tid, status, "human:tester")
    before = tickets.load(proj, tid)
    runs.claim(proj, tid, "agent:generic", "generic", pid=os.getpid())
    after = tickets.load(proj, tid)
    if status in ("open", "ready", "review"):
        assert after["status"] == "active"
        assert after["history"][-1]["text"].endswith(" started")
        assert after["history"][-1]["by"] == "agent:generic"
    else:
        assert after == before


def test_mark_missing(proj):
    tickets.mark_working(proj, "t_missing1", "agent:generic", "Agent")


def test_patch_without_status_keeps_done(proj, new_ticket):
    tid = new_ticket()
    t = tickets.set_status(proj, tid, "done", "human:tester")
    t = tickets.patch(proj, tid, t["revision"], '{"title":"New"}', "agent:generic")
    assert t["status"] == "done"


@pytest.mark.parametrize("patch", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_finish_with_proof(proj, run, new_ticket, patch, allowed):
    tid = new_ticket()
    run("check", "add", tid, "Test it")
    assert run("check", "done", tid, "c1", "--note", "Verified")[0] == 0
    config.set_agents_may_finish(proj, allowed)
    before = tickets.load(proj, tid)
    if patch:
        after = tickets.patch(proj, tid, before["revision"], '{"status":"done"}', "agent:generic")
    else:
        after = tickets.set_status(proj, tid, "done", "agent:generic")
    assert after["status"] == ("done" if allowed else "review")


def test_actor_from_environment_and_explicit_override(proj, run, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setattr(tickets, "agent_tool", lambda: "generic")
    assert run("ticket", "status", tid, "done")[1] == tickets.REVIEW_MESSAGE + "\n"
    assert tickets.load(proj, tid)["status"] == "review"
    # an agent in the environment counts as an agent whatever --by says
    assert run("ticket", "status", tid, "done", "--by", "human:tester")[1] == tickets.REVIEW_MESSAGE + "\n"
    assert tickets.load(proj, tid)["status"] == "review"
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    assert run("ticket", "status", tid, "done", "--by", "human:tester")[0] == 0
    assert tickets.load(proj, tid)["status"] == "done"


def test_agent_cannot_turn_the_switch_on(proj, run, monkeypatch):
    monkeypatch.setattr(tickets, "agent_tool", lambda: "generic")
    code, out, err = run("config", "set", "workflow.agents_may_finish", "on", "--by", "human:tester")
    assert code != 0 and "Only a person" in err + out
    assert not config.agents_may_finish(proj)
    assert run("config", "set", "workflow.agents_may_finish", "off")[0] == 0


def test_list_order_and_closed_filter(proj, run, new_ticket):
    for status in reversed(tickets.STATUSES):
        tid = new_ticket(status)
        tickets.set_status(proj, tid, status, "human:tester")
    code, out, err = run("ticket", "list", "--json")
    import json

    assert code == 0 and not err
    assert [t["status"] for t in json.loads(out)] == list(tickets.OPEN_STATUSES)


@pytest.mark.parametrize("path", ["status", "patch"])
@pytest.mark.parametrize("status", ["active", "done"])
@pytest.mark.parametrize("allowed", [False, True])
def test_status_history_uses_resolved_actor(proj, run, new_ticket, monkeypatch, path, status, allowed):
    tid = new_ticket()
    config.set_agents_may_finish(proj, allowed)
    before = tickets.load(proj, tid)
    monkeypatch.setenv("ORCH_AGENT", "generic")
    args = (
        ("status", tid, status)
        if path == "status"
        else ("patch", tid, "--if-revision", str(before["revision"]), '{"status":"' + status + '"}')
    )
    code, _, err = run("ticket", *args, "--by", "human:x")
    assert code == 0, err
    history = tickets.load(proj, tid)["history"][len(before["history"]) :]
    assert history and all(h["by"] == "agent:generic" for h in history)
