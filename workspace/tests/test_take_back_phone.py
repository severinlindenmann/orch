"""Workspace side of "Question taken back" (contracts/vectors/taken-back-v1.json): one text to the phones,
only when the take-back changed something and the question went to phones; nothing that arrives over the
relay takes a question back."""

import json
from pathlib import Path

import jsonschema
import pytest
from test_phone_proposal import PHONE, conn  # noqa: F401  (the fixture)
from test_relay_client import msg

from orch import relay, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/taken-back-v1.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(json.loads((CONTRACTS / "message.schema.json").read_text()))


def _new_ticket(run):
    code, out, _ = run("ticket", "new", "Invoice export", "--json", "--by", "agent:x")
    assert code == 0
    return json.loads(out)["id"]


def _ask(run, tid, *extra):
    code, out, err = run(
        "ask",
        tid,
        "Which format?",
        "--option",
        "CSV",
        "--option",
        "XLSX",
        *extra,
        "--json",
        "--by",
        "agent:x",
    )
    assert code == 0, out + err
    return json.loads(out)


def _take(run, tid, reason, qid="q1"):
    return run("ask", tid, "--take-back", qid, reason, "--json", "--by", "agent:x")


def _taken(rel):
    return [m for m in rel.sent if "taken_back" in m["body"]]


@pytest.mark.parametrize(
    "case",
    [c for c in VECTORS["cases"] if not c.get("relay_unreachable") and c["relay_on"]],
    ids=lambda c: c["name"],
)
def test_vector_cases(proj, run, conn, case):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, *(["--phone"] if case["asked_on_phones"] else []))
    asked_mid = next((m["id"] for m in conn.sent if m["type"] == "question"), None)
    if case["changed"]:
        code, out, err = _take(run, tid, case["reason_in"])
        assert code == 0, out + err
    else:
        assert _take(run, tid, case["reason_in"])[0] == 0
        before = len(conn.sent)
        assert _take(run, tid, case["reason_in"])[0] == 0  # the same reason again: no-op, nothing sent
        assert len(conn.sent) == before
        return
    got = _taken(conn)
    if case["send"] is None:
        assert got == []
        return
    assert len(got) == 1
    sent = got[0]
    assert sent["body"] == case["send"]
    assert sent["to"] == case["to"] == "phones"
    assert sent["reply_to"] == asked_mid
    assert sent["ticket"] == tid
    assert list(VALIDATOR.iter_errors(sent)) == []


def test_repeat_sends_nothing_more(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")
    assert _take(run, tid, "plans changed")[0] == 0
    assert len(_taken(conn)) == 1
    assert _take(run, tid, "plans changed")[0] == 0
    assert len(_taken(conn)) == 1


def test_relay_off_sends_nothing_and_breaks_nothing(proj, run):
    tid = _new_ticket(run)
    _ask(run, tid)
    code, out, err = _take(run, tid, "plans changed")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["questions"][0]["taken_back"]["reason"] == "plans changed"
    assert relay.send_taken_back(proj, tid, tickets.load(proj, tid)["questions"][0]) is None


def test_a_retry_sends_the_same_id_and_bytes(proj, run, conn, monkeypatch):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")
    posts = []
    real = relay._post_message

    def flaky(root, raw):
        posts.append(json.loads(raw))
        if len(posts) == 1:
            raise relay.Refused("The relay could not be reached.")
        return real(root, raw)

    monkeypatch.setattr(relay, "_unreachable", lambda e: True)
    monkeypatch.setattr(relay, "_post_message", flaky)
    assert _take(run, tid, "plans changed")[0] == 0
    assert _taken(conn) == []  # kept in the outbox
    relay.resend_outbox(proj)
    sent = _taken(conn)
    assert len(sent) == 1
    assert sent[0]["id"] == posts[0]["id"] and sent[0]["created_at"] == posts[0]["created_at"]


def test_a_refusal_by_the_relay_is_only_logged(proj, run, conn, monkeypatch):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")

    def refuse(root, raw):
        e = relay.Refused("This question was already answered.")
        e.status = 409
        raise e

    monkeypatch.setattr(relay, "_post_message", refuse)
    code, out, err = _take(run, tid, "plans changed")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["questions"][0]["taken_back"]["reason"] == "plans changed"
    assert not (proj / ".orch" / "outbox").exists() or not list((proj / ".orch" / "outbox").glob("*.json"))


def test_control_characters_and_length_are_cleaned(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")
    assert _take(run, tid, "plans‮ changed\x07 " + "x" * 280)[0] == 0
    body = _taken(conn)[0]["body"]
    assert len(body["taken_back"]["reason"]) <= 200
    assert body["text"] == "Taken back: " + body["taken_back"]["reason"]
    assert "‮" not in body["text"] and "\x07" not in body["text"]


@pytest.mark.parametrize("case", VECTORS["inbound"], ids=lambda c: c["name"])
def test_nothing_over_the_relay_takes_a_question_back(proj, run, conn, case):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")
    qmid = next(m["id"] for m in conn.sent if m["type"] == "question")
    body = {
        "text": "Taken back: plans changed",
        "taken_back": {"reason": "plans changed"},
        **case.get("body_extra", {}),
    }
    if case["type"] == "answer":
        body = {**body, "question_id": "q1", "answer": "Taken back: plans changed"}
    conn.inbox.append(
        msg("m_inb0000000000001", case["type"], body, frm=case["from"], ticket=tid, reply_to=qmid)
    )
    assert run("relay", "inbox")[0] == 0
    q = tickets.load(proj, tid)["questions"][0]
    assert "taken_back" not in q
    assert not any(h["text"].startswith("Taken back") for h in tickets.load(proj, tid)["history"])
    assert _taken(conn) == []  # and nothing is sent back out because of it


def test_late_phone_answer_is_a_history_line_only(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid, "--phone")
    qmid = next(m["id"] for m in conn.sent if m["type"] == "question")
    assert _take(run, tid, "plans changed")[0] == 0
    conn.inbox.append(
        msg(
            "m_ans0000000000001",
            "answer",
            {"question_id": "q1", "answer": "CSV", "answered_by": "human:iPhone"},
            frm=PHONE,
            ticket=tid,
            reply_to=qmid,
        )
    )
    assert run("relay", "inbox")[0] == 0
    q = tickets.load(proj, tid)["questions"][0]
    assert q["answer"] == "Taken back: plans changed"
    assert len(_taken(conn)) == 1
