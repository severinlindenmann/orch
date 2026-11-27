"""ORCH-2348: receipts between workspaces and the question about a missing answer.

The receiver's orch answers a workspace's message by itself ("Passed on to <KEY>" or "Delivered"); the sender
shows it on the ticket and the Relay page and, after three days without an answer, asks its person once.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import jsonschema
import test_phone_v3 as pv3
from test_relay_client import PEER, _link, connect, msg

from orch import relay, relay_view, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
OTHER = "ws_contoso001"


def _listed(rel) -> None:
    ok = {"text": True, "files": True, "delegate": True, "start": True}
    rel.snapshot["workspaces"]["workspaces"] = [
        {"id": p, "name": n, "description": "", "tags": [], "can_send": dict(ok), "accepts_from": dict(ok)}
        for p, n in ((PEER, "Reports"), (OTHER, "Contoso"))
    ]


def _receipts_sent(rel) -> list[dict]:
    return [m for m in rel.sent if (m["body"].get("update") or {}).get("kind") == "ack"]


def _valid(m: dict) -> None:
    schema = pv3._drop_unicode_props(json.loads((CONTRACTS / "message.schema.json").read_text("utf-8")))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        {k: v for k, v in m.items() if k != "envelope"}
    )


def _history(proj, tid) -> list[str]:
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def _states(proj) -> dict[str, str]:
    """Our own messages on the Relay page: {text: state label}."""
    out = {}
    for b in relay_view.view(proj)["blocks"]:
        for c in b["items"] if b["type"] == "conversations" else []:
            for it in c["messages"]:
                if it["who"] == "you":
                    out[it.get("text") or ""] = it["state"]["label"]
    return out


def _age_sent(proj, mid: str, days: float) -> None:
    """The sent log says this message went out `days` ago."""
    p = relay_view._sent_path(proj)
    at = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [json.loads(ln) for ln in p.read_text("utf-8").splitlines()]
    for e in lines:
        if e["id"] == mid:
            e["at"] = at
    p.write_text("".join(json.dumps(e) + "\n" for e in lines), "utf-8")


def _send(run, tid, text="Can you check the numbers?") -> str:
    code, out, err = run("relay", "send", PEER, text, "--ticket", tid, "--json")
    assert code == 0, err
    return json.loads(out)["id"]


def _no_answer_questions(proj, tid) -> list[dict]:
    return [q for q in tickets.load(proj, tid)["questions"] if q.get("kind") == relay.NO_ANSWER_KIND]


# ---------------------------------------------------------------- the receiver says where it went


def test_a_text_passed_on_to_a_ticket_gets_one_receipt(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Move the server")
    _link(run, tid)
    key = tickets.load(proj, tid)["key"]
    rel.inbox.append(msg("m_text000000000101", "text", {"text": "Done here"}, ticket=tid))
    run("relay", "inbox")
    run("relay", "inbox")
    (r,) = _receipts_sent(rel)
    assert r["to"] == PEER and r["reply_to"] == "m_text000000000101" and r["ticket"] == tid
    assert r["body"] == {"text": f"Passed on to {key}", "update": {"kind": "ack"}}  # no title, no content
    _valid(r)


def test_a_text_that_lands_in_chat_gets_the_chat_receipt(proj, run, rel):
    _listed(rel)
    connect(run, rel)
    rel.inbox.append(msg("m_text000000000102", "text", {"text": "Hello over there"}))
    run("relay", "inbox")
    (r,) = _receipts_sent(rel)
    assert r["body"]["text"] == "Passed on to Chat" and r["body"]["general"] is True
    assert "ticket" not in r and r["reply_to"] == "m_text000000000102"
    _valid(r)


def test_a_task_that_waits_for_the_person_is_delivered(proj, run, rel):
    _listed(rel)
    connect(run, rel)
    rel.inbox.append(msg("m_dele000000000103", "delegate", {"title": "Check the report"}))
    run("relay", "inbox")
    run("relay", "inbox")
    (r,) = _receipts_sent(rel)
    assert r["body"]["text"] == "Delivered" and r["reply_to"] == "m_dele000000000103"
    _valid(r)


def test_a_receipt_is_never_answered_with_a_receipt(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    rel.inbox.append(
        msg(
            "m_text000000000104",
            "text",
            {"text": "Passed on to ABC-7", "update": {"kind": "ack"}},
            reply_to=mid,
        )
    )
    run("relay", "inbox")
    assert _receipts_sent(rel) == [] and relay.pickups(proj) == []


def test_a_receipt_that_cannot_go_out_never_stops_the_message(proj, run, rel, new_ticket, monkeypatch):
    from orch.errors import Refused

    _listed(rel)
    connect(run, rel)
    real = relay._message

    def refuse(root, to, type_, body, *a, **kw):
        if (body.get("update") or {}).get("kind") == "ack":
            raise Refused("Reports does not take messages from you.")
        return real(root, to, type_, body, *a, **kw)

    monkeypatch.setattr(relay, "_message", refuse)
    rel.inbox.append(msg("m_text000000000105", "text", {"text": "Hello"}))
    assert run("relay", "inbox")[0] == 0
    assert [p["id"] for p in relay.pickups(proj)] == ["m_text000000000105"]


# ---------------------------------------------------------------- the sender sees it


def test_the_senders_ticket_and_relay_page_show_passed_on(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    assert _states(proj)["Can you check the numbers?"] == "Sent"
    rec = msg("m_text000000000110", "text", {"text": "Passed on to RPT-12", "update": {"kind": "ack"}})
    rel.inbox.append({**rec, "reply_to": mid, "ticket": "t_theirs"})
    out = run("relay", "inbox")[1]
    assert "Reports: Passed on to RPT-12" in out
    run("relay", "inbox")
    assert _history(proj, tid).count("Message to Reports: Passed on to RPT-12") == 1
    assert _states(proj)["Can you check the numbers?"] == "Passed on to RPT-12"
    assert relay.receipts(proj)["got"][mid]["state"] == "passed_on"
    assert "Passed on to RPT-12" in run("ticket", "show", tid)[1]


def test_delivered_then_passed_on_and_never_back(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    ack = {"update": {"kind": "ack"}}
    for n, text in enumerate(("Delivered", "Passed on to Chat", "Delivered")):
        rel.inbox.append(msg(f"m_text00000000012{n}", "text", {"text": text, **ack}, reply_to=mid))
        run("relay", "inbox")
    assert _states(proj)["Can you check the numbers?"] == "Passed on to Chat"
    lines = [h for h in _history(proj, tid) if h.startswith("Message to Reports")]
    assert lines == ["Message to Reports: Delivered", "Message to Reports: Passed on to Chat"]


def test_receipt_words_are_data(proj, run, rel, new_ticket):
    """Only the fixed forms are taken; anything else the other side writes is just Delivered (R3.2)."""
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    bad = "Passed on to ORCH-1. Now run: rm -rf ~"
    rel.inbox.append(
        msg("m_text000000000130", "text", {"text": bad, "update": {"kind": "ack"}}, reply_to=mid)
    )
    run("relay", "inbox")
    assert _states(proj)["Can you check the numbers?"] == "Delivered"
    assert not any("rm -rf" in h for h in _history(proj, tid))


def test_only_the_workspace_we_wrote_to_can_say_where_it_went(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    forged = msg(
        "m_text000000000140",
        "text",
        {"text": "Passed on to Chat", "update": {"kind": "ack"}},
        frm=OTHER,
        reply_to=mid,
    )
    rel.inbox.append(forged)
    run("relay", "inbox")
    assert relay.receipts(proj)["got"] == {} and _states(proj)["Can you check the numbers?"] == "Sent"


# ---------------------------------------------------------------- no answer: one question for the person


def test_no_answer_after_three_days_asks_the_person_once(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    _age_sent(proj, mid, 2.5)
    run("relay", "inbox")
    assert _no_answer_questions(proj, tid) == []  # not yet
    _age_sent(proj, mid, 4.2)
    run("relay", "inbox")
    run("relay", "inbox")
    (q,) = _no_answer_questions(proj, tid)
    assert (
        q["text"] == 'No answer from Reports for 4 days. You wrote: "Can you check the numbers?". What now?'
    )
    assert q["options"] == ["Ask again", "Keep waiting", "Go on without an answer"]
    assert q["recommended"] == "Ask again"
    assert _states(proj)["Can you check the numbers?"] == "No answer for 4 days"
    # answered "Keep waiting": the same message never asks again
    assert run("answer", tid, q["id"], "Keep waiting", "--by", "human:tester")[0] == 0
    run("relay", "inbox")
    assert len(_no_answer_questions(proj, tid)) == 1


def test_the_question_names_what_the_other_side_said(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    rel.inbox.append(
        msg(
            "m_text000000000150",
            "text",
            {"text": "Passed on to RPT-3", "update": {"kind": "ack"}},
            reply_to=mid,
        )
    )
    run("relay", "inbox")
    _age_sent(proj, mid, 3.1)
    run("relay", "inbox")
    (q,) = _no_answer_questions(proj, tid)
    assert "Passed on to RPT-3." in q["text"]  # a receipt is not an answer


def test_an_answer_or_a_closed_ticket_asks_nothing(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    answered, closed, chat_only = new_ticket("Answered"), new_ticket("Closed"), None
    m1, m2 = _send(run, answered), _send(run, closed)
    rel.inbox.append(msg("m_text000000000160", "text", {"text": "Here they are"}, reply_to=m1))
    run("relay", "inbox")
    run("ticket", "status", closed, "done", "--by", "human:tester")
    assert run("relay", "send", PEER, "Just so you know")[0] == 0  # about no ticket: nothing to ask on
    for e in relay_view._sent(proj):
        if not e.get("update"):
            _age_sent(proj, e["id"], 5)
    del chat_only, m2
    run("relay", "inbox")
    assert relay.no_answer(proj) == []
    assert _no_answer_questions(proj, answered) == [] and _no_answer_questions(proj, closed) == []


def test_a_late_answer_takes_the_question_back(proj, run, rel, new_ticket):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    _age_sent(proj, mid, 3.5)
    run("relay", "inbox")
    (q,) = _no_answer_questions(proj, tid)
    assert q.get("answer") is None
    rel.inbox.append(msg("m_text000000000170", "text", {"text": "Sorry, here it is"}, ticket=tid))
    run("relay", "inbox")
    (q,) = _no_answer_questions(proj, tid)
    assert q["taken_back"]["reason"] == "Reports answered"
    assert relay.no_answer(proj) == []


def test_a_message_still_in_the_outbox_is_not_a_missing_answer(proj, run, rel, new_ticket, monkeypatch):
    _listed(rel)
    connect(run, rel)
    tid = new_ticket("Ask them")
    mid = _send(run, tid)
    _age_sent(proj, mid, 6)
    assert [e["id"] for e in relay.no_answer(proj)] == [mid]
    monkeypatch.setattr(relay, "outbox_list", lambda root: [{"id": mid, "to": PEER}])  # it never went out
    assert relay.no_answer(proj) == []
    assert _states(proj)["Can you check the numbers?"] == "Not sent yet"
