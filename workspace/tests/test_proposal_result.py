"""Workspace replay of the proposal-result contract, including durable retries."""

import json

import jsonschema
import pytest
from test_phone_proposal import CONTRACTS, answer, proposals, propose, real_tickets
from test_phone_proposal import conn as conn

from orch import chat, config, relay, tickets

VECTORS = json.loads((CONTRACTS / "vectors/proposal-result-v1.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(json.loads((CONTRACTS / "message.schema.json").read_text()))


@pytest.fixture(autouse=True)
def proposal_flow_only(monkeypatch):
    # Inbox also syncs unrelated ticket views before applying answers. Keep this replay about
    # proposal answers, with every message they send still checked (including unexpected acks).
    monkeypatch.setattr(relay, "sync_phone_views", lambda root: None)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_result_vector(proj, run, conn, monkeypatch, case):
    if case["from"] == "ph_iphone0002":
        conn.snapshot["workspaces"]["phones"].append({"id": "ph_iphone0002", "name": "iPad"})
        assert run("relay", "refresh")[0] == 0
    if case["authorised"]:
        assert relay._paired_phone(proj, case["from"]) is not None
    propose(proj)
    q = proposals(conn)[0]
    config.set_code(proj, "DM1")
    (proj / ".orch/ticket-counter.json").write_text('{"last": 11}')
    state = case["state"]
    first = None
    if state == "made":
        chat.make_ticket(proj, q["id"], None, "human:dash")
        assert len([m for m in conn.sent if m["body"].get("update", {}).get("kind") == "ack"]) == 1
    elif state == "gone":
        day = chat.day_key(proj)
        doc = chat.read_day(proj, day)
        for m in doc["messages"]:
            if m["id"] == q["id"]:
                m["refs"] = []
        chat._day_path(proj, day).write_text(json.dumps(doc))
    elif state in ("answered_make", "answered_not_now", "result_recorded"):
        answer(conn, q, "not_now" if state == "answered_not_now" else "make")
        assert run("relay", "inbox")[0] == 0
        if state != "answered_not_now":
            assert conn.sent[-1]["body"].get("proposal_result") == {"result": "made", "key": "DM1-12"}, (
                conn.sent
            )
        if state == "result_recorded":
            first = conn.sent[-1]
            (proj / ".orch/inbox-seen.json").write_text("{}")
            monkeypatch.setattr(tickets, "now", lambda: "2030-01-01T00:00:00Z")

    raw_error = None
    if case.get("make", "").startswith("refused:"):
        raw_error = (
            "Only a person makes a ticket from Chat."
            if case["make"] == "refused:human_proof"
            else "Something internal /home/x/y.py failed"
        )

        def refuse(*args, **kwargs):
            raise tickets.Refused(raw_error)

        monkeypatch.setattr(chat, "make_ticket", refuse)
    attempts = []
    post = relay._post_message

    def capture(root, raw):
        attempts.append(json.loads(raw))
        return post(root, raw)

    monkeypatch.setattr(relay, "_post_message", capture)
    start = len(conn.sent)
    if case["answer"] == "(dashboard)":
        chat.make_ticket(proj, q["id"], None, "human:dash")
    else:
        if not first:
            answer(conn, q, case["answer"], n=2, frm=case["from"])
        assert run("relay", "inbox")[0] == 0
    sent = attempts if first else conn.sent[start:]
    acks = [m for m in sent if m["body"].get("update", {}).get("kind") == "ack"]
    assert len(acks) == int(case.get("got_it_ack", False))
    results = [m for m in sent if m not in acks]
    if case["send"] is None:
        assert results == [], json.dumps(results)
    else:
        (m,) = results
        assert m["body"] == {
            "text": relay._proposal_result_text(case["send"]),
            "proposal_result": case["send"],
        }
        assert m["to"] == case["to"] and m["reply_to"] == q["id"]
        assert "ticket" not in m and "key" not in m
        VALIDATOR.validate(m)
        recorded = relay._asked_edit(proj, lambda a: list(a[q["id"]]["results"].values())[-1]["result"])
        assert recorded == {"id": m["id"], "to": case["to"], "body": case["send"]}
        assert not any(e["id"] == m["id"] for e in chat.read_day(proj, chat.day_key(proj))["messages"])
    if case.get("skipped"):
        assert relay._asked_edit(
            proj, lambda a: list(a[q["id"]]["results"].values())[0]["result"]["body"]
        ) == {
            "result": "made",
            "key": case["key"],
        }
    if case.get("resend_same_message_id"):
        assert results == [first], "retry preserves every envelope byte, including created_at"
        assert len(real_tickets(proj)) == 1
    if raw_error:
        assert raw_error not in json.dumps(conn.sent)


@pytest.mark.parametrize("valid", VECTORS["valid"], ids=lambda v: v["name"])
def test_canonical_text(valid):
    body = valid["message"]["body"]
    assert relay._proposal_result_text(body["proposal_result"]) == body["text"]


def test_refusal_attribute():
    exc = tickets.Refused("private detail")
    exc.needs_person = True
    assert relay._refusal_reason(exc) == "needs_person"


@pytest.mark.parametrize("failure", ["422", "oserror", "offline"])
def test_send_failure_keeps_result_for_retry(proj, run, conn, monkeypatch, failure):
    propose(proj)
    q = proposals(conn)[0]
    answer(conn, q, "make")
    original = relay._post_message
    attempts = []

    def fail(root, raw):
        sent = json.loads(raw)
        saved = relay._asked_edit(root, lambda a: list(a[q["id"]]["results"].values())[-1]["result"])
        assert saved == {"id": sent["id"], "to": sent["to"], "body": sent["body"]["proposal_result"]}
        attempts.append(raw)
        if failure == "oserror":
            raise OSError("network broke")
        if failure == "offline":
            raise tickets.Refused("Cannot reach relay")
        exc = tickets.Refused("422: invalid proposal_result")
        exc.status = 422
        raise exc

    monkeypatch.setattr(relay, "_post_message", fail)
    assert run("relay", "inbox")[0] == 0
    saved = relay._asked_edit(proj, lambda a: list(a[q["id"]]["results"].values())[-1]["result"])
    assert saved["body"]["result"] == "made"
    assert "proposal result" in (proj / ".orch/run/relay-errors.log").read_text()
    (proj / ".orch/inbox-seen.json").write_text("{}")

    def unexpected_make(*args, **kwargs):
        pytest.fail("a recorded result must not be recomputed")

    monkeypatch.setattr(chat, "make_ticket", unexpected_make)
    monkeypatch.setattr(relay, "_post_message", original)
    monkeypatch.setattr(tickets, "now", lambda: "2030-01-01T00:00:00Z")
    assert run("relay", "inbox")[0] == 0
    assert conn.sent[-1] == json.loads(attempts[0])
    assert len(real_tickets(proj)) == 1


def test_group_routed_make_sends_nothing(proj, run, conn):
    propose(proj)
    q = proposals(conn)[0]
    answer(conn, q, "make")
    conn.inbox[-1]["body"]["group"] = {"id": "g_x"}
    assert run("relay", "inbox")[0] == 0
    assert conn.sent == [q]
    assert real_tickets(proj) == []


def test_crash_between_make_and_record_resends_made_with_same_id(proj, run, conn, monkeypatch):
    """The ticket was made, the process died before the result was recorded: the retry still says
    `made` to every phone (not decided to one), with the id reserved before making."""
    propose(proj)
    q = proposals(conn)[0]
    config.set_code(proj, "DM1")
    answer(conn, q, "make")
    monkeypatch.setattr(relay, "_set_asked", _crash_on_results(relay._set_asked))
    with pytest.raises(RuntimeError):
        run_inbox_raw(proj)
    monkeypatch.setattr(relay, "_set_asked", relay._set_asked.__wrapped__)
    (proj / ".orch/inbox-seen.json").write_text("{}")
    assert run("relay", "inbox")[0] == 0
    results = [m for m in conn.sent if m["body"].get("proposal_result")]
    assert len(results) == 1 and results[0]["to"] == "phones"
    assert results[0]["body"]["proposal_result"]["result"] == "made"


def _crash_on_results(orig):
    def wrapper(root, mid, **fields):
        if "results" in fields:
            raise RuntimeError("crash before the result is recorded")
        return orig(root, mid, **fields)

    wrapper.__wrapped__ = orig
    return wrapper


def run_inbox_raw(proj):
    relay.inbox(proj)
