"""Adversarial tests for the inbox-phone MAC (security delta review review-p2sec2 of F1).

An agent can write .orch/inbox/. A message read back from there (not fetched in this pull) must count only
when this core MAC'd it at pull time, bound to its full content and id. Tests marked xfail(strict) document
a finding: they pass once it is fixed."""

import json

import pytest
from test_relay_client import connect, msg

from orch import humanproof, relay


def _phone_question(run, rel, tid):
    run("ask", tid, "Ship it?", "--option", "Yes", "--option", "No", "--phone", "--by", "agent:x")
    return next(m for m in rel.sent if m["type"] == "question")


def _plant(proj, m):
    d = proj / ".orch" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{m['id']}.json").write_text(json.dumps(m))


def _q1(run, tid):
    return json.loads(run("ticket", "show", tid, "--json")[1])["questions"][0]


def test_a_valid_mac_swapped_onto_other_content_is_not_applied(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    q = _phone_question(run, rel, tid)
    body = {"question_id": "q1", "answer": "Yes", "answered_by": "human:severin"}
    genuine = msg("m_genuine000000001", "text", {"text": "hi"}, frm="ph_iphone0001", ticket=tid)
    mac = humanproof.local_sign(proj, relay.INBOX_MAC_KIND, genuine)
    assert mac
    forged = msg("m_genuine000000001", "answer", body, frm="ph_iphone0001", ticket=tid, reply_to=q["id"])
    _plant(proj, {**forged, "_inbox_mac": mac})  # same id, other content, the old MAC
    run("relay", "inbox")
    assert _q1(run, tid)["answer"] is None


def test_an_old_signed_answer_under_a_new_id_is_not_applied(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    q = _phone_question(run, rel, tid)
    body = {"question_id": "q1", "answer": "Yes", "answered_by": "human:severin"}
    old = msg("m_oldanswer0000001", "answer", body, frm="ph_iphone0001", ticket=tid, reply_to=q["id"])
    mac = humanproof.local_sign(proj, relay.INBOX_MAC_KIND, old)
    _plant(proj, {**old, "id": "m_newanswer0000001", "_inbox_mac": mac})  # id is inside the MAC
    run("relay", "inbox")
    assert _q1(run, tid)["answer"] is None


def test_a_mac_of_another_local_kind_does_not_pass(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    q = _phone_question(run, rel, tid)
    body = {"question_id": "q1", "answer": "Yes", "answered_by": "human:severin"}
    m = msg("m_otherkind0000001", "answer", body, frm="ph_iphone0001", ticket=tid, reply_to=q["id"])
    mac = humanproof.local_sign(proj, relay.QUESTION_MAC_KIND, m)  # domain-separated by kind
    _plant(proj, {**m, "_inbox_mac": mac})
    run("relay", "inbox")
    assert _q1(run, tid)["answer"] is None


@pytest.mark.xfail(
    strict=True,
    reason="N1: _saved_phone_msg gates only from=ph_; a file planted in .orch/inbox/ with from=sub_<x> "
    "answers a question sent to the phones (as agent:sub_<x>), which `orch answer` refuses to an agent "
    "('Only a human answers it'). Fix: MAC every saved relay message; require it for files not fetched now",
)
def test_a_subscriber_answer_planted_in_the_inbox_folder_is_not_applied(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    q = _phone_question(run, rel, tid)
    body = {"question_id": "q1", "answer": "Yes", "answered_by": "agent:sub_planted01"}
    _plant(proj, msg("m_subplant00000001", "answer", body, frm="sub_planted01", ticket=tid, reply_to=q["id"]))
    run("relay", "inbox")
    assert _q1(run, tid)["answer"] is None
