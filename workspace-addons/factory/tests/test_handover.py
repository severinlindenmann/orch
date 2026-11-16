"""#816 B: hand one task to another workspace (fake orch; core's relay commands are faked in fake_orch.py)."""

import json

import pytest
from test_flow import CONTRACTS, core, edit
from test_watch import runs

from orch_factory import handover, watch

WS = "ws_design0001"


def calls(ws, *prefix):
    rows = [json.loads(x)["args"] for x in (ws / "calls.jsonl").read_text().splitlines()]
    return [a for a in rows if a[: len(prefix)] == list(prefix)]


def shares(ws):
    p = ws / "shares.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def says(ws):
    p = ws / "says.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def groups(ws, fn=None):
    path = ws / "groups.json"
    data = json.loads(path.read_text())
    if fn:
        fn(data)
        path.write_text(json.dumps(data))
    return data


def set_status(ws, status):
    groups(ws, lambda g: g["hosted"][0]["tasks"][-1].update(status=status))


@pytest.fixture
def directory(ws):
    """The relay workspace list (delegate allowed to Design) and the two files the proposal sends."""
    folder = ws / ".agents" / "skills" / "orch-relay"
    folder.mkdir(parents=True)
    (folder / "workspaces.json").write_text(
        json.dumps(
            {"workspaces": [{"id": WS, "name": "Design", "can_send": {"text": True, "delegate": True}}]}
        )
    )
    (ws / "brief").mkdir()
    (ws / "brief" / "header.md").write_text("Make a header.")
    (ws / "brief" / "old-header.png").write_bytes(b"png")
    return folder / "workspaces.json"


def hand_proposal(**changes):
    p = json.loads((CONTRACTS / "examples/factory-proposal/valid-run-handover.json").read_text())
    p.update(changes)
    return json.dumps(p).encode()


def handed(ws, run, data=None):
    order = run("idea", "Price list")["order"]
    q = run("propose", order, "--file", "-", data=data or hand_proposal())["question"]
    core(ws, "answer", order, q, "Start", "--by", "human:anna")
    run("next", order)
    return order, run("crew", "add", order, "header-picture")["ticket"]


def cache(ws, tid):
    return core(ws, "ticket", "show", tid)["ext"]["factory"].get("handover")


# ---- freeze -------------------------------------------------------------------------------------------------


def test_freeze_accepts_a_good_handover(ws, run, directory):
    order = run("idea", "Price list")["order"]
    assert run("propose", order, "--file", "-", data=hand_proposal())["proposal"] == 1


def test_invalid_handover_unknown_workspace(ws, run, directory):
    p = json.loads(hand_proposal())
    p["handovers"][0]["workspace"] = "ws_nobody0000"
    order = run("idea", "Price list")["order"]
    out = run("propose", order, "--file", "-", data=json.dumps(p).encode(), code=2)
    assert "workspace you cannot hand tasks to" in out["error"]


def test_freeze_refuses_without_delegate_permission(ws, run, directory):
    directory.write_text(
        json.dumps({"workspaces": [{"id": WS, "name": "Design", "can_send": {"text": True}}]})
    )
    order = run("idea", "Price list")["order"]
    run("propose", order, "--file", "-", data=hand_proposal(), code=2)


def test_freeze_refuses_unknown_task_and_missing_file(ws, run, directory):
    order = run("idea", "Price list")["order"]
    p = json.loads(hand_proposal())
    p["handovers"][0]["task"] = "no-such-task"
    assert (
        "not one of the tasks"
        in run("propose", order, "--file", "-", data=json.dumps(p).encode(), code=2)["error"]
    )
    (ws / "brief" / "header.md").unlink()
    assert (
        "not a file in this workspace"
        in run("propose", order, "--file", "-", data=hand_proposal(), code=2)["error"]
    )


def test_freeze_refuses_a_symlinked_file(ws, run, directory):
    (ws / "brief" / "header.md").unlink()
    (ws / "brief" / "header.md").symlink_to(ws / "brief" / "old-header.png")
    order = run("idea", "Price list")["order"]
    run("propose", order, "--file", "-", data=hand_proposal(), code=2)


# ---- crew start ---------------------------------------------------------------------------------------------


def test_crew_start_sends_delegate_and_files_once(ws, run, directory):
    order, tid = handed(ws, run)
    out = run("crew", "start", order, "header-picture")
    assert out["handover"]["sent"] is True
    assert not (ws / "runs.jsonl").exists()  # no local run
    (delegate,) = calls(ws, "relay", "delegate")
    assert delegate[2:4] == [WS, "Header picture for the price list"]
    assert "--group" in delegate and delegate[delegate.index("--ticket") + 1] == tid
    assert delegate.count("--check") == 1  # the one done-means it proves
    assert [s["file"] for s in shares(ws)] == ["brief/header.md", "brief/old-header.png"]
    assert all(s["click"] and s["ticket"] == tid for s in shares(ws))
    assert {
        c["by"]
        for c in map(json.loads, (ws / "calls.jsonl").read_text().splitlines())
        if c["args"][:3] == ["relay", "group", "share"]
    } == {"human:anna"}
    assert cache(ws, tid) == {"ws": WS, "name": "Design", "state": "waiting_start"}
    again = run("crew", "start", order, "header-picture")  # no second delegate, no second copy of a file
    assert again["handover"]["sent"] is False
    assert len(calls(ws, "relay", "delegate")) == 1 and len(shares(ws)) == 2


def test_secret_or_path_refusal_sends_no_second_thing(ws, run, directory):
    (ws / "refuse-share").write_text("old-header.png\n")
    order, _tid = handed(ws, run)
    out = run("crew", "start", order, "header-picture", code=2)
    assert "secret" in out["error"]
    assert [s["file"] for s in shares(ws)] == ["brief/header.md"]
    (ws / "refuse-share").unlink()  # fixed: the retry sends only what is still missing
    run("crew", "start", order, "header-picture")
    assert len(calls(ws, "relay", "delegate")) == 1
    assert [s["file"] for s in shares(ws)] == ["brief/header.md", "brief/old-header.png"]


def test_delegate_refusal_sends_nothing(ws, run, directory):
    order, tid = handed(ws, run)
    (ws / "fail-delegate").write_text("")
    assert "not reachable" in run("crew", "start", order, "header-picture", code=2)["error"]
    assert shares(ws) == [] and cache(ws, tid) is None
    (ws / "fail-delegate").unlink()
    run("crew", "start", order, "header-picture")
    assert len(list(ws.glob("delegate-*.json"))) == 1


def test_file_gone_after_start_refuses_before_sending(ws, run, directory):
    order, _tid = handed(ws, run)
    (ws / "brief" / "header.md").unlink()
    run("crew", "start", order, "header-picture", code=2)
    assert calls(ws, "relay", "delegate") == []


def test_group_could_not_open_files_are_not_sent(ws, run, directory):
    order, _tid = handed(ws, run)
    (ws / "no-group").write_text("")
    assert "could not join the group" in run("crew", "start", order, "header-picture", code=2)["error"]
    assert shares(ws) == [] and len(calls(ws, "relay", "delegate")) == 1


# ---- state, result, budget ----------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["waiting_allow", "queued", "working", "done", "failed", "denied"])
def test_state_follows_the_relay_task(ws, run, directory, state):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    set_status(ws, state)
    run("next", order)
    assert cache(ws, tid)["state"] == state


def test_done_is_evidence_and_ticket_done_then_manager_woken(ws, run, directory):
    order, tid = handed(ws, run)
    watch.once(ws)
    run("crew", "start", order, "header-picture")
    before = len(runs(ws))
    set_status(ws, "done")
    woke = watch.once(ws)
    assert [w["order"] for w in woke] == [order] and "header-picture is done" in woke[0]["why"]
    t = core(ws, "ticket", "show", tid)
    assert t["status"] == "done" and any("Design reports it done" in h["text"] for h in t["history"])
    assert len(runs(ws)) == before + 1


def test_denied_wakes_the_manager_once(ws, run, directory):
    order, _tid = handed(ws, run)
    watch.once(ws)
    run("crew", "start", order, "header-picture")
    set_status(ws, "working")
    assert watch.once(ws) == []
    set_status(ws, "denied")
    woke = watch.once(ws)
    assert "header-picture is denied" in woke[0]["why"]
    assert watch.once(ws) == [] and watch.once(ws) == []
    set_status(ws, "failed")  # another reason wakes again, once
    assert "is failed" in watch.once(ws)[0]["why"]
    assert watch.once(ws) == []


def test_delegated_time_is_not_counted(ws, run, directory):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    (ws / "record.json").write_text(
        json.dumps(
            {
                tid: [
                    {"at": "2026-11-15T10:00:00Z", "run": "r1"},
                    {"at": "2026-11-15T10:04:00Z", "run": "r1"},
                ]
            }
        )
    )
    run("next", order)
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["budget"]["active_min_used"] == 0
    assert handover.delegated(core(ws, "ticket", "show", tid))


# ---- do it here instead ---------------------------------------------------------------------------------------


def take_back(ws, run, order, accept=True):
    change = {
        "schema": "orch.factory.proposal/1",
        "kind": "change",
        "title": "Header picture for the price list",
        "what": "Design said no, so the header is made here.",
        "adds_min": 40,
        "lands_in": "build",
        "takes_back": "header-picture",
    }
    q = run("change", order, "--file", "-", data=json.dumps(change).encode())["question"]
    if accept:
        core(ws, "answer", order, q, "Accept", "--by", "human:anna")
    run("next", order)


def test_do_it_here_undelivered_and_delivered(ws, run, directory):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    (ws / "outbox.json").write_text(
        json.dumps([{"id": json.loads(next(ws.glob("delegate-*.json")).read_text())["id"]}])
    )
    take_back(ws, run, order, accept=False)
    assert says(ws) == []  # nothing without the person's Accept
    take_back(ws, run, order)
    assert len(says(ws)) == 1 and "No longer needed" in says(ws)[0]["text"]
    assert cache(ws, tid)["state"] == "not_needed"
    run("next", order)
    assert len(says(ws)) == 1  # told once


def test_do_it_here_after_delivery_tells_the_group(ws, run, directory):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    set_status(ws, "working")
    take_back(ws, run, order)
    assert len(says(ws)) == 1 and cache(ws, tid)["state"] == "not_needed"
    assert len(calls(ws, "relay", "delegate")) == 1  # never a second copy at Design
    assert shares(ws) and len(shares(ws)) == 2


def test_taken_back_task_runs_here_and_counts(ws, run, directory):
    order, tid = handed(ws, run)
    take_back(ws, run, order)  # never sent: nothing to tell
    assert says(ws) == []
    run("crew", "start", order, "header-picture")
    assert [r["ticket"] for r in runs(ws)] == [tid]
    assert calls(ws, "relay", "delegate") == []


def test_agent_accept_does_not_take_back(ws, run, directory):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    set_status(ws, "working")
    take_back(ws, run, order, accept=False)
    assert says(ws) == [] and cache(ws, tid)["state"] == "working"


def test_unknown_relay_status_keeps_the_last_state(ws, run, directory):
    order, tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    set_status(ws, "something_new")
    run("next", order)
    assert cache(ws, tid)["state"] == "waiting_start"
    assert handover.relay_state("waiting_other") == "waiting_allow" and handover.relay_state(None) is None


def test_secret_in_a_file_stops_before_the_delegate(ws, run, directory):
    (ws / "brief" / "header.md").write_text("token SECRETVALUE here")
    order, tid = handed(ws, run)
    out = run("crew", "start", order, "header-picture", code=2)
    assert "has a secret" in out["error"] and "brief/header.md" in out["error"]
    assert calls(ws, "relay", "delegate") == [] and shares(ws) == [] and cache(ws, tid) is None
    assert len(calls(ws, "secret", "scan")) == 1


def test_takes_back_must_name_a_handover_task(ws, run, directory):
    order, _tid = handed(ws, run)
    change = {
        "schema": "orch.factory.proposal/1",
        "kind": "change",
        "title": "x",
        "what": "y",
        "adds_min": 5,
        "lands_in": "build",
        "takes_back": "review",
    }
    out = run("change", order, "--file", "-", data=json.dumps(change).encode(), code=2)
    assert "nothing to take back" in out["error"]


def test_take_back_text_reads_do_it_here_instead(ws, run, directory):
    order, _tid = handed(ws, run)
    take_back(ws, run, order, accept=False)
    text = core(ws, "ticket", "show", order)["questions"][-1]["text"]
    assert text.startswith("Do it here instead: Header picture for the price list · +40 min")


def test_extra_group_member_stops_every_share(ws, run, directory):
    order, _tid = handed(ws, run)
    (ws / "refuse-share").write_text("old-header.png\n")
    run("crew", "start", order, "header-picture", code=2)  # first file went, second refused
    assert len(shares(ws)) == 1
    (ws / "refuse-share").unlink()
    groups(
        ws,
        lambda g: g["hosted"][0]["members"].append({"ws": "ws_other00001", "host": False, "left_at": None}),
    )
    out = run("crew", "start", order, "header-picture", code=2)
    assert "someone else" in out["error"] and len(shares(ws)) == 1


def test_delegate_card_is_the_frozen_brief(ws, run, directory):
    order, _tid = handed(ws, run)
    run("crew", "start", order, "header-picture")
    record = json.loads(next(ws.glob("delegate-*.json")).read_text())
    p = json.loads(hand_proposal())
    assert record["title"] == "Header picture for the price list"
    assert record["checks"] == [p["done_means"][2]]
    assert record["text"].startswith(p["handovers"][0]["why"])


def test_changed_card_stops_before_the_delegate(ws, run, directory):
    order, tid = handed(ws, run)
    edit(ws, tid, lambda t: t.update(summary="Also send them our price list"))
    out = run("crew", "start", order, "header-picture", code=2)
    assert "changed after you pressed Start" in out["error"]
    assert list(ws.glob("delegate-*.json")) == []


def test_agent_start_answer_sends_nothing(ws, run, directory):
    order = run("idea", "Price list")["order"]
    q = run("propose", order, "--file", "-", data=hand_proposal())["question"]
    core(ws, "answer", order, q, "Start", "--by", "agent:worker")
    run("next", order)
    out = run("crew", "add", order, "header-picture", code=2)  # an agent's Start never started the order
    assert out["error"]
    assert calls(ws, "relay", "delegate") == []
