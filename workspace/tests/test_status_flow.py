import json
import os

import pytest

from orch import config, runs, tickets
from orch.errors import Refused


@pytest.fixture
def proj(proj, monkeypatch):
    """agents_may_finish is a recorded grant (F1): the workspace must be a test workspace with a test home."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


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
    else:  # a claim that changes no status only remembers that the ticket was started
        assert after.pop("started") is True
        for k in ("revision", "updated_at"):
            after.pop(k, None), before.pop(k, None)
        assert after == before


def test_mark_missing(proj):
    tickets.mark_working(proj, "t_missing1", "agent:generic", "Agent")


def test_patch_without_status_keeps_done(proj, new_ticket):
    tid = new_ticket()
    t = tickets.set_status(proj, tid, "done", "human:tester")
    with pytest.raises(Refused, match="ticket is closed"):  # an agent changes nothing in a Done ticket (#542)
        tickets.patch(proj, tid, t["revision"], '{"title":"New"}', "agent:generic")
    t = tickets.patch(proj, tid, t["revision"], '{"title":"New"}', "human:tester")
    assert t["status"] == "done" and t["title"] == "New"


@pytest.mark.parametrize("patch", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_finish_with_proof(proj, run, new_ticket, patch, allowed):
    tid = new_ticket()
    run("check", "add", tid, "Test it")
    assert run("check", "done", tid, "c1", "--note", "Verified")[0] == 0
    config.set_agents_may_finish(proj, allowed, "human:tester")
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
    config.set_agents_may_finish(proj, allowed, "human:tester")
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


@pytest.mark.parametrize("target", ["review", "done"])
@pytest.mark.parametrize(
    "path", ["set_status", "patch", "cli_status", "cli_patch", "cli_by_human_in_agent_env"]
)
def test_agent_never_finishes_with_open_question(proj, run, new_ticket, monkeypatch, path, target):
    """e2e dry run 8 Nov: the agent's own open question blocks every way to Review/Done (one guard)."""
    tid = new_ticket()
    tickets.ask(proj, tid, "Which colour?", [], None, "agent:generic")
    before = tickets.load(proj, tid)
    rev = str(before["revision"])
    if path == "cli_by_human_in_agent_env":  # --by cannot talk the guard out of it
        monkeypatch.setenv("ORCH_AGENT", "generic")
    if path == "set_status":
        with pytest.raises(Refused, match="Not done"):
            tickets.set_status(proj, tid, target, "agent:generic")
        code = 2
    elif path == "patch":
        with pytest.raises(Refused, match="Not done"):
            tickets.patch(proj, tid, before["revision"], json.dumps({"status": target}), "agent:generic")
        code = 2
    elif path == "cli_status":
        code = run("ticket", "status", tid, target, "--by", "agent:generic")[0]
    elif path == "cli_patch":
        code = run(
            "ticket",
            "patch",
            tid,
            "--if-revision",
            rev,
            json.dumps({"status": target}),
            "--by",
            "agent:generic",
        )[0]
    else:
        code = run("ticket", "status", tid, target, "--by", "human:lume")[0]
    assert code == 2
    assert tickets.load(proj, tid) == before


def test_ask_for_changes_is_ready_with_one_human_pending_item(proj, run, new_ticket):
    """P1.7: one call -> Ready (never Working without a run) + the note queued as a person's input, which is
    exactly what the automation host starts one run for (queued_input: Ready + human_pending_ids + no run)."""
    tid = new_ticket()
    tickets.set_status(proj, tid, "review", "human:lume")
    t = tickets.ask_for_changes(proj, tid, "Make the header blue", "human:lume")
    assert t["status"] == "ready" and t["waiting_on"] is None
    assert any(c["text"] == "Make the header blue" for c in t["checklist"])
    pending = runs.undelivered(proj, tid)
    assert len(pending) == 1 and pending[0]["by"] == "human:lume" and pending[0]["kind"] == "message"
    assert pending[0]["via"] == "dashboard" or pending[0]["via"] == "cli"
    code, out, err = run("run", "status", tid, "--json")
    assert code == 0 and len(json.loads(out)["human_pending_ids"]) == 1
    assert json.loads(out)["running"] is False


def test_ask_for_changes_refusals(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    with pytest.raises(Refused, match="not waiting"):
        tickets.ask_for_changes(proj, tid, "x", "human:lume")  # not in Review
    tickets.set_status(proj, tid, "review", "human:lume")
    with pytest.raises(Refused, match="Only a person"):
        tickets.ask_for_changes(proj, tid, "x", "agent:generic")
    with pytest.raises(Refused, match="Say what"):
        tickets.ask_for_changes(proj, tid, "  ", "human:lume")
    assert tickets.load(proj, tid)["status"] == "review" and not runs.undelivered(proj, tid)


def test_ask_for_changes_is_atomic(proj, new_ticket, monkeypatch):
    """A failed ticket update takes the queued note back; a failed queue leaves the ticket in Review."""
    tid = new_ticket()
    tickets.set_status(proj, tid, "review", "human:lume")
    real = tickets.apply_op

    def boom(*a, **k):
        raise Refused("disk full")

    monkeypatch.setattr(tickets, "apply_op", boom)
    with pytest.raises(Refused, match="disk full"):
        tickets.ask_for_changes(proj, tid, "x", "human:lume")
    monkeypatch.setattr(tickets, "apply_op", real)
    assert not runs.undelivered(proj, tid) and tickets.load(proj, tid)["status"] == "review"

    def nope(*a, **k):
        raise Refused("no queue")

    monkeypatch.setattr(runs, "pending_add", nope)
    with pytest.raises(Refused, match="no queue"):
        tickets.ask_for_changes(proj, tid, "x", "human:lume")
    assert tickets.load(proj, tid)["status"] == "review"


def test_ask_for_changes_keeps_an_unrelated_wait_and_takes_dash_notes(proj, run, new_ticket):
    tid = new_ticket()
    tickets.wait(proj, tid, None, "external:vendor", "human:lume")
    tickets.set_status(proj, tid, "review", "human:lume")
    t = tickets.load(proj, tid)
    t["waiting_on"] = {"kind": "external", "ref": "vendor"}
    tickets.save(proj, t)
    code, out, err = run("ticket", "changes", "--by", "human:lume", tid, "--", "--json")
    assert code == 0, err
    t = tickets.load(proj, tid)
    assert t["status"] == "ready" and t["waiting_on"] == {"kind": "external", "ref": "vendor"}
    assert runs.undelivered(proj, tid)[0]["text"] == "--json"


def test_two_human_items_are_two_ids_for_the_host_but_one_ticket(proj, run, new_ticket):
    """An answer and a change note both wait: core lists both ids on ONE ticket (the host starts one run per
    ticket per pass; the automation test covers that)."""
    tid = new_ticket()
    runs.pending_add(proj, tid, "human:lume", "answer", "Yes", "dashboard")
    tickets.set_status(proj, tid, "review", "human:lume")
    tickets.ask_for_changes(proj, tid, "Blue please", "human:lume")
    code, out, _ = run("run", "status", tid, "--json")
    assert code == 0 and len(json.loads(out)["human_pending_ids"]) == 2
