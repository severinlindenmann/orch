"""0909: the General helper's ticket proposal reaches the phones as ONE question;
a paired phone's "make" is the dashboard's Make ticket (contracts/vectors/proposal-question-v1.json)."""

import json
from pathlib import Path

import jsonschema
import pytest
from fakes import WS
from test_relay_client import msg

from orch import chat, relay, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"
SENTENCE = "Ready. Shall I make this a ticket?"


@pytest.fixture
def conn(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [
        {"id": PHONE, "name": "iPhone", "online": True, "last_seen": None}
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def proposals(rel):
    return [m for m in rel.sent if m["type"] == "question" and m["body"].get("proposal")]


def propose(proj, title="Rename field X", n=1):
    """The person writes from the phone, then the helper proposes (a text with a proposal card)."""
    chat.record(proj, f"m_you{n:013d}", "you", "phone", "please rename field X", phone=PHONE)
    return relay.send_text(
        proj, "phones", SENTENCE, None, None, None, general=True, refs=[{"kind": "proposal", "title": title}]
    )


def answer(rel, qmsg, text, n=1, frm=PHONE, by="human:iPhone"):
    mid = f"m_ans{n:013d}"
    rel.inbox.append(
        msg(
            mid,
            "answer",
            {"question_id": qmsg["body"]["question_id"], "answer": text, "answered_by": by},
            frm=frm,
            reply_to=qmsg["id"],
        )
    )
    return mid


def real_tickets(proj):
    return [t for t in tickets.list_all(proj) if not t.get("general")]


def test_one_question_instead_of_a_text(proj, conn):
    sent = propose(proj)
    (q,) = proposals(conn)
    assert q["id"] == sent["id"] and q["to"] == "phones" and "ticket" not in q
    assert q["body"] == {
        "question_id": f"proposal-{q['id']}",
        "title": "Rename field X",
        "text": SENTENCE,
        "options": ["make", "not_now"],
        "recommended": None,
        "proposal": "make_ticket",
    }
    jsonschema.Draft202012Validator(json.loads((CONTRACTS / "message.schema.json").read_text())).validate(q)
    assert not [m for m in conn.sent if m["type"] == "text"], "no separate text"
    # the dashboard History keeps it with its Make ticket card
    assert chat.proposal_state(proj, q["id"]) == "open"


def test_a_plain_text_or_a_person_sending_is_not_a_proposal(proj, conn):
    relay.send_text(proj, "phones", "hello", None, None, None, general=True)
    relay.send_text(
        proj,
        "phones",
        "x",
        None,
        None,
        None,
        general=True,
        sender="you",
        refs=[{"kind": "proposal", "title": "T"}],
    )
    assert not proposals(conn)


def test_title_is_cleaned_and_cut(proj, conn):
    propose(proj, title="  " + "long title " * 30)
    (q,) = proposals(conn)
    assert 0 < len(q["body"]["title"]) <= 120 and q["body"]["title"] == q["body"]["title"].strip()


def test_make_from_the_phone_creates_exactly_one_ticket(proj, run, conn):
    propose(proj)
    (q,) = proposals(conn)
    answer(conn, q, "make")
    assert "made" in run("relay", "inbox")[1]
    (t,) = real_tickets(proj)
    assert t.get("title_auto") is True and t["title"].startswith("Rename field X")
    assert chat.proposal_state(proj, q["id"]) == "made"
    acks = [m for m in conn.sent if m["type"] == "text" and m["body"].get("update", {}).get("kind") == "ack"]
    assert len(acks) == 1 and acks[0]["ticket"] == t["id"] and acks[0]["reply_to"] == q["id"]
    # the same answer again and a second one: nothing more
    answer(conn, q, "make", n=2)
    run("relay", "inbox")
    assert [x["id"] for x in real_tickets(proj)] == [t["id"]]
    assert len([m for m in conn.sent if m["body"].get("update", {}).get("kind") == "ack"]) == 1
    general = tickets.load(proj, tickets.general_id(proj))
    assert any("too late" in h["text"] or "second answer" in h["text"] for h in general["history"])


def test_not_now_is_a_history_line_only(proj, run, conn):
    propose(proj)
    (q,) = proposals(conn)
    answer(conn, q, "not_now")
    run("relay", "inbox")
    assert real_tickets(proj) == []
    general = tickets.load(proj, tickets.general_id(proj))
    assert general["history"][-1]["by"] == "human:iPhone" and "Not now" in general["history"][-1]["text"]
    answer(conn, q, "make", n=2)  # first answer wins
    run("relay", "inbox")
    assert real_tickets(proj) == []


def test_dashboard_first_closes_it(proj, run, conn):
    propose(proj)
    (q,) = proposals(conn)
    made = chat.make_ticket(proj, q["id"], None, "human:dash")
    acks = [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "ack"]
    assert len(acks) == 1 and acks[0]["ticket"] == made["ticket"], "the phone card closes"
    answer(conn, q, "make")
    run("relay", "inbox")
    assert [x["id"] for x in real_tickets(proj)] == [made["ticket"]]
    assert len([m for m in conn.sent if m["body"].get("update", {}).get("kind") == "ack"]) == 1


@pytest.mark.parametrize("frm", ["sub_abc12345", "ws_reports001", "ph_stranger01"])
def test_only_a_paired_phone_makes_a_ticket(proj, run, conn, frm):
    propose(proj)
    (q,) = proposals(conn)
    answer(conn, q, "make", frm=frm, by="human:boss")
    run("relay", "inbox")
    assert real_tickets(proj) == []
    answer(conn, q, "make", n=2)  # the question is still open for the real phone
    run("relay", "inbox")
    assert len(real_tickets(proj)) == 1


def test_group_routed_answer_is_refused(proj, run, conn):
    propose(proj)
    (q,) = proposals(conn)
    m = msg(
        "m_ansgroup00000001",
        "answer",
        {
            "question_id": q["body"]["question_id"],
            "answer": "make",
            "answered_by": "human:iPhone",
            "group": {"id": "g_x"},
        },
        frm=PHONE,
        reply_to=q["id"],
    )
    conn.inbox.append(m)
    run("relay", "inbox")
    assert real_tickets(proj) == []


def test_an_agent_session_never_applies_the_answer(proj, run, conn, monkeypatch):
    propose(proj)
    (q,) = proposals(conn)
    mid = answer(conn, q, "make")
    monkeypatch.setenv("CLAUDECODE", "1")
    run("relay", "inbox")
    assert real_tickets(proj) == []
    seen = proj / ".orch/inbox-seen.json"
    assert not seen.exists() or mid not in json.loads(seen.read_text())
    monkeypatch.delenv("CLAUDECODE")
    run("relay", "inbox")
    assert len(real_tickets(proj)) == 1


def test_other_words_do_nothing(proj, run, conn):
    propose(proj)
    (q,) = proposals(conn)
    answer(conn, q, "sure")
    run("relay", "inbox")
    assert real_tickets(proj) == []


def test_vector(proj, run, conn):
    vec = json.loads((CONTRACTS / "vectors" / "proposal-question-v1.json").read_text())
    for i, case in enumerate(vec["cases"]):
        propose(proj, n=i + 1)
        q = proposals(conn)[-1]
        if case["state"]["made"]:
            chat.make_ticket(proj, q["id"], None, "human:dash")
        before = len(real_tickets(proj))
        conn.inbox.append(
            msg(
                f"m_vec{i:013d}",
                "answer",
                {
                    "question_id": q["body"]["question_id"],
                    "answer": case["answer"],
                    "answered_by": "human:iPhone",
                },
                frm=case["from"],
                reply_to=q["id"],
            )
        )
        run("relay", "inbox")
        grew = len(real_tickets(proj)) - before
        assert grew == (1 if case["do"] == "make" else 0), case["name"]
