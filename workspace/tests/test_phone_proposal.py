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
    assert relay._asked_edit(proj, lambda a: a[q["id"]]["to"]) == "phones"
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
    assert t["title"] == proposals(conn)[0]["body"]["title"], "the phone shows the title that is made"
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


def agent_envs():
    from orch import adapters

    out = [("ORCH_AGENT", "anything")]
    for a in adapters._registry().values():
        d = a.get("detect") or {}
        if d.get("env_any"):
            out.append((d["env_any"][0], "1"))
        elif d.get("env_prefix"):
            out.append((d["env_prefix"] + "X", "1"))
    return out


@pytest.mark.parametrize("key,value", agent_envs())
def test_every_agent_runtime_is_an_agent_session(proj, run, conn, monkeypatch, key, value):
    assert tickets.agent_tool() is None
    propose(proj)
    (q,) = proposals(conn)
    answer(conn, q, "make")
    monkeypatch.setenv(key, value)
    assert tickets.agent_tool()
    run("relay", "inbox")
    assert real_tickets(proj) == []
    with pytest.raises(tickets.Refused):
        chat.make_ticket(proj, q["id"], None, "human:x")


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


def refuse_questions(rel):
    """A relay from before the proposal rule: it refuses the proposal question (422)."""

    def post(m, q, body):
        msg = json.loads(body)
        if msg["type"] == "question":
            return 422, {"error": "invalid", "message": "A ticket proposal has nothing like this."}
        rel.sent.append(msg)
        return 201, {"id": msg["id"]}

    rel.routes.insert(0, ("POST", "/v1/messages", post))


def check_local_first(proj, conn, sent):
    assert sent["sent"] is True and not sent.get("problem")
    assert chat.proposal_state(proj, sent["id"]) == "open", "the dashboard card is there"
    made = chat.make_ticket(proj, sent["id"], None, "human:dash")
    assert [x["id"] for x in real_tickets(proj)] == [made["ticket"]]
    assert chat.make_ticket(proj, sent["id"], None, "human:dash")["ticket"] == made["ticket"]


def test_relay_refusal_keeps_the_dashboard_card(proj, run, conn):
    refuse_questions(conn)
    chat.record(proj, "m_you0000000000001", "you", "phone", "please rename field X", phone=PHONE)
    sent = relay.send_text(
        proj, "phones", SENTENCE, None, None, None, general=True, refs=[{"kind": "proposal", "title": "T"}]
    )
    assert not proposals(conn)
    assert any(m["type"] == "text" and m["id"] == sent["id"] for m in conn.sent), "the phone still hears it"
    log = (proj / ".orch/relay-errors.log").read_text()
    assert f"proposal question {sent['id']} to phones refused" in log and "nothing like this" in log
    assert log.count("\n") == 1, "the text fallback went out: one line only"
    check_local_first(proj, conn, sent)


def test_relay_refusal_through_the_helper_command_says_nothing_about_the_relay(proj, run, conn):
    refuse_questions(conn)
    chat.record(proj, "m_you0000000000001", "you", "phone", "please rename field X", phone=PHONE)
    gid = tickets.ensure_general(proj, "human:t")
    code, out, err = run("relay", "send", "phones", SENTENCE, "--ticket", gid, "--ref", "proposal:Rename X")
    assert code == 0, err
    text = (out + err).lower()
    assert (proj / ".orch/relay-errors.log").is_file()
    assert "refus" not in text and "not sent" not in text and "relay" not in text.replace("sent to", "")
    (entry,) = [m for m in chat.read_day(proj, chat.day_key(proj))["messages"] if m["by"] != "you"]
    assert chat.proposal_state(proj, entry["id"]) == "open"


def test_relay_refusing_everything_logs_both_and_shows_nothing(proj, run, conn, capsys):
    conn.routes.insert(
        0, ("POST", "/v1/messages", lambda m, q, b: (422, {"error": "invalid", "message": "no"}))
    )
    chat.record(proj, "m_you0000000000001", "you", "phone", "please rename field X", phone=PHONE)
    sent = relay.send_text(
        proj, "phones", SENTENCE, None, None, None, general=True, refs=[{"kind": "proposal", "title": "T"}]
    )
    check_local_first(proj, conn, sent)
    lines = (proj / ".orch/relay-errors.log").read_text().splitlines()
    assert [("question" in x, "text" in x) for x in lines] == [(True, False), (False, True)]
    assert "no" not in capsys.readouterr().out
    general = tickets.load(proj, tickets.general_id(proj))
    assert not any("relay-errors" in h["text"] or "refused" in h["text"] for h in general["history"])


def test_relay_offline_keeps_the_dashboard_card(proj, run, conn):
    conn.server.shutdown()
    conn.server.server_close()
    chat.record(proj, "m_you0000000000001", "you", "phone", "please rename field X", phone=PHONE)
    sent = relay.send_text(
        proj, "phones", SENTENCE, None, None, None, general=True, refs=[{"kind": "proposal", "title": "T"}]
    )
    check_local_first(proj, conn, sent)


def test_review_question_refused_or_offline_never_raises(proj, new_ticket, conn):
    from orch import phone_view

    def refuse(m, q, body):
        return 422, {"error": "invalid", "message": "no"}

    conn.routes.insert(0, ("POST", "/v1/messages", refuse))
    tid = new_ticket("Review me")
    tickets.set_status(proj, tid, "review", "human:t")
    assert phone_view.sync_reviews(proj) == []  # refused: nothing raised, the ticket is untouched
    assert tickets.load(proj, tid)["status"] == "review"
    conn.server.shutdown()
    conn.server.server_close()
    tickets.set_status(proj, tid, "ready", "human:t")
    tickets.set_status(proj, tid, "review", "human:t")
    phone_view.sync_reviews(proj)  # offline: no exception either
