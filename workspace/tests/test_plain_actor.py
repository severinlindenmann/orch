"""#799 P1: no op is human-only. A command from a plain terminal is the person's, a command under an agent
tool is recorded as `agent:<tool>`, and nothing hands the person off to a dashboard."""

import json

import pytest
from conftest import CONTRACTS  # noqa: F401
from fakes import WS

from orch import config, keystore, tickets

PEER = "ws_reports001"
NO_HANDOFF = ("dashboard on this computer", "Waiting for your click", "Only a human can do this")


def _plain(out, err):
    text = out + err
    assert not any(w in text for w in NO_HANDOFF), text


def _question(run, new_ticket):
    tid = new_ticket()
    code, out, err = run(
        "ask",
        tid,
        "Which file?",
        "--option",
        "a",
        "--option",
        "b",
        "--recommend",
        "a",
        "--by",
        "agent:claude",
        "--json",
    )
    assert code == 0, out + err
    return tid, json.loads(out)["id"]


def test_proof_stdin_is_gone(proj, run, capsys):
    try:
        code = run("ticket", "list", "--proof-stdin")[0]
    except SystemExit as e:
        code = e.code
    assert code == 2


def test_dev_proof_commands_are_gone(proj, run):
    for word in ("dev-proof", "dev-mark"):
        try:
            code = run(word)[0]
        except SystemExit as e:
            code = e.code
        assert code == 2


def test_relay_connect_from_a_plain_terminal(proj, run, rel):
    code, out, err = run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)
    assert code == 0, out + err
    _plain(out, err)
    assert json.loads((proj / ".orch/secrets/relay.json").read_text())["token"] == rel.token


def test_relay_allow_from_a_plain_terminal(proj, run, rel):
    run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)
    rel.inbox.append(
        {
            "schema": "orch.msg/1",
            "id": "m_deleg00000000001",
            "from": PEER,
            "to": WS,
            "type": "delegate",
            "created_at": "2026-11-04T10:00:00Z",
            "body": {"title": "Use event_time", "text": "x"},
        }
    )
    run("relay", "inbox")
    code, out, err = run("relay", "allow", "m_deleg00000000001", "--once")
    assert code == 0, out + err
    _plain(out, err)
    assert [m["type"] for m in rel.sent] == ["text", "allow"]  # the "Delivered" receipt, then the allow


def test_answer_from_a_plain_terminal_is_the_persons(proj, run, new_ticket, monkeypatch):
    tid, qid = _question(run, new_ticket)
    monkeypatch.setattr(tickets, "attended", lambda: True)
    code, out, err = run("answer", tid, qid, "a")
    assert code == 0, out + err
    _plain(out, err)
    q = tickets.load(proj, tid)["questions"][0]
    assert q["answer"] == "a" and q["answered_by"].startswith("human:")


def test_an_agent_answer_is_recorded_as_the_agent(proj, run, new_ticket, monkeypatch):
    tid, qid = _question(run, new_ticket)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    code, out, err = run("answer", tid, qid, "b", "--by", "human:pat")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["questions"][0]["answered_by"] == "agent:claude"


def test_unattended_done_leaves_human_review_pending(proj, run, new_ticket, monkeypatch):
    monkeypatch.setattr(tickets, "attended", lambda: False)
    tid = new_ticket()
    run("check", "add", tid, "Write it")
    assert run("check", "done", tid, "c1", "--note", "wrote it")[0] == 0
    code, out, err = run("ticket", "status", tid, "done")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["status"] == "review"


@pytest.mark.parametrize(
    "words,refusal",
    [
        (("ticket", "edit", "{tid}", "--human-review", "no"), "Only a person"),
        (("config", "set", "workflow.reviewer_answers", "on"), "Only the owner"),
        (("people", "on"), "Only the owner"),
        (("github", "release-exception", "unit", "--ticket", "off"), "Only a person"),
        (("run", "take-back", "{tid}", "p_nothere01"), "Only a person"),
        (("chat", "say", "Hello"), "Only a person"),
        (("chat", "contacts"), "Only a person"),
        (("chat", "thread", PEER), "Only a person"),
        (("chat", "sync", PEER), "Only a person"),
        (("chat", "send", PEER, "Hello"), "Only a person"),
    ],
)
def test_person_commands_refuse_an_unattended_caller(proj, run, new_ticket, words, refusal, monkeypatch):
    monkeypatch.setattr(tickets, "attended", lambda: False)
    tid = new_ticket()
    code, out, err = run(*(word.format(tid=tid) for word in words))
    assert code == 2 and refusal in out + err


def test_marking_done_from_a_plain_terminal(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Write it")
    code, out, err = run("check", "done", tid, "c1", "--note", "wrote it", "--by", "human:pat")
    assert code == 0, out + err  # an item
    _plain(out, err)
    code, out, err = run("ticket", "status", tid, "done", "--by", "human:pat")
    assert code == 0, out + err  # the ticket
    _plain(out, err)
    assert tickets.load(proj, tid)["status"] == "done"


def test_an_agent_changes_a_setting_and_is_recorded(proj, run, monkeypatch):
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    code, out, err = run("config", "set", "workflow.agents_may_finish", "on")
    assert code == 0, out + err
    _plain(out, err)
    assert config.agents_may_finish(proj) is True


def test_old_files_with_a_mac_still_load(proj, run):
    """The settings record and the profile ledger of an older orch sit in the orch home: nothing reads them
    any more, and nothing breaks because they are there."""
    home = proj.parent / f"{proj.name}_home" / "orchhome"
    home.mkdir(parents=True, exist_ok=True)
    (home / "human-settings.json").write_text(
        json.dumps(
            {
                "schema": "orch.human-settings/1",
                "workspaces": {"w": {"focus.live_session": {"value": False, "mac": "x"}}},
            }
        )
    )
    (home / "profile.json").write_text(json.dumps({"schema": "x", "profiles": {"p": {"mac": "x"}}}))
    config.set_key(proj, "insights", "share_names", True)
    assert config.insights_share_names(proj) is True
    assert run("config", "get", "insights.share_names", "--json")[0] == 0
    assert keystore.read_profiles(proj) == {}


def test_orch_update_runs_at_once_and_queues_nothing(proj, run, monkeypatch):
    from orch import addons

    called = []
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.setattr(addons, "update", lambda *a, **k: called.append(1) or [])
    code, out, err = run("update", "--project-only")
    _plain(out, err)
    assert called
