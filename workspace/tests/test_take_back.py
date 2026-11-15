"""`orch ask T --take-back q3 "reason"`: a helper takes back its own question that no longer matters."""

import json

import pytest

from orch import relay, review, tickets
from orch.errors import Refused


@pytest.fixture
def tk(proj, run):
    code, out, _ = run("ticket", "new", "Invoice export", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _ask(run, tid, text="Which format?", *extra):
    code, out, err = run(
        "ask", tid, text, "--option", "CSV", "--option", "XLSX", *extra, "--json", "--by", "agent:x"
    )
    assert code == 0, out + err
    return json.loads(out)


def _take(run, tid, qid, reason="not needed"):
    return run("ask", tid, "--take-back", qid, reason, "--json", "--by", "agent:x")


def test_take_back_take_back_removes_it_everywhere(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    assert tickets.load(root, tid)["waiting_on"] == {"kind": "question", "ref": q["id"]}
    assert any(r["ticket"] == tid for r in json.loads(run("needs", "--json")[1]))
    code, out, err = run("ask", tid, "--take-back", q["id"], "not needed", "--by", "agent:x")
    assert code == 0, out + err
    assert out.strip() == f"Taken back {q['id']}.\nNext: keep working on the ticket."
    t = tickets.load(root, tid)
    got = t["questions"][0]
    assert got["taken_back"]["reason"] == "not needed" and got["taken_back"]["by"] == "agent:x"
    assert got["taken_back"]["at"]
    assert t["waiting_on"] is None and t["status"] != "waiting"
    assert t["history"][-1]["text"] == "Taken back: not needed"
    assert json.loads(run("needs", "--json")[1]) == []
    assert json.loads(run("review", "list", "--json")[1])["cards"] == []
    assert review.stack(root) == []
    assert tickets._open_questions(t) == []


def test_waiting_on_another_question_moves_on(tk, run):
    root, tid = tk
    q1 = _ask(run, tid, "First?")
    q2 = _ask(run, tid, "Second?")
    assert _take(run, tid, q1["id"])[0] == 0
    t = tickets.load(root, tid)
    assert t["waiting_on"] == {"kind": "question", "ref": q2["id"]} and t["status"] == "waiting"


def test_answers_are_refused_with_the_reason(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    assert _take(run, tid, q["id"], "plan changed")[0] == 0
    with pytest.raises(Refused, match="This question was taken back: plan changed"):
        tickets.answer(root, tid, q["id"], "CSV", "human:pat", "dashboard")
    code, out, err = run("answer", tid, q["id"], "CSV", "--by", "human:pat")
    assert code != 0 and "This question was taken back: plan changed" in out + err
    code, out, err = run(
        "review", "answer", tid, q["id"], "--verdict", "ok", "--picked", "CSV", "--by", "human:pat"
    )
    assert code != 0 and "taken back: plan changed" in out + err
    with pytest.raises(Refused, match="taken back"):
        review.change(root, tid, q["id"], "ok", "CSV", by="human:pat", via="cli")
    assert tickets.load(root, tid)["questions"][0]["taken_back"]["reason"] == "plan changed"


def test_a_card_question_can_be_taken_back(tk, run):
    root, tid = tk
    code, out, err = run(
        "ask", tid, "New block", "--draft", "New block", "--then", "I build it.", "--json", "--by", "agent:x"
    )
    assert code == 0, out + err
    qid = json.loads(out)["id"]
    assert len(review.stack(root)) == 1
    assert _take(run, tid, qid)[0] == 0
    assert review.stack(root) == []
    assert json.loads(run("review", "list", "--answered", "--json")[1]) == []


def test_refusals(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    code, out, err = _take(run, tid, "q9")
    assert code != 0 and "has no question q9" in out + err
    code, out, err = run("ask", tid, "--take-back", q["id"], " ", "--by", "agent:x")
    assert code != 0 and "A reason is needed" in out + err
    assert tickets.answer(root, tid, q["id"], "CSV", "human:pat", "cli")
    code, out, err = _take(run, tid, q["id"])
    assert code != 0 and "already answered" in out + err
    q2 = _ask(run, tid, "Another?")
    code, out, err = run("ask", tid, "--take-back", q2["id"], "x", "--option", "A", "--by", "agent:x")
    assert code != 0 and "reason only" in out + err


def test_same_reason_again_is_a_no_op_other_reason_refused(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    assert _take(run, tid, q["id"], "gone")[0] == 0
    rev = tickets.load(root, tid)["revision"]
    code, out, err = run("ask", tid, "--take-back", q["id"], "gone", "--by", "agent:x")
    assert code == 0 and "already taken back" in out and "Next:" in out
    assert tickets.load(root, tid)["revision"] == rev
    code, out, err = _take(run, tid, q["id"], "other reason")
    assert code != 0 and "taken back: gone" in out + err


def test_ticket_text_shows_it_taken_back(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    _take(run, tid, q["id"], "gone")
    out = run("ticket", "show", tid)[1]
    assert f"Taken back {q['id']}" in out and "Answered q1" not in out


def test_phone_verdict_on_a_taken_back_question_is_decided(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    _take(run, tid, q["id"], "gone")
    got = tickets.load(root, tid)["questions"][0]
    assert relay._verdict_summary(got) == "Taken back: gone"
    assert relay._is_mine({"vpending": "m_1"}, got, "m_1", "human:pat") is False


def test_take_back_returns_what_the_phone_needs(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    t, got, changed = tickets.take_back(root, tid, q["id"], "gone", "agent:x")
    assert (t["id"], got["id"], changed) == (tid, q["id"], True)


def test_old_ticket_files_without_the_field_keep_working(tk, run):
    root, tid = tk
    q = _ask(run, tid)
    assert "taken_back" not in tickets.load(root, tid)["questions"][0]
    assert tickets.answer(root, tid, q["id"], "CSV", "human:pat", "cli")[1]["answer"] == "CSV"


# ---- nothing that arrives over the relay takes a question back ----


def _asked_question(proj):
    from conftest import ensure_signing

    ensure_signing(proj)
    tid = tickets.create(proj, "Deploy", "human:tester")["id"]
    tickets.ask(proj, tid, "Deploy to staging?", ["yes", "no"], None, "agent:claude")
    rec = {
        "ticket": tid,
        "question_id": "q1",
        "to": "phones",
        "question_digest": tickets.question_digest(tickets.load(proj, tid)["questions"][0]),
    }
    relay.sign_asked(proj, "m_q00000000000001", rec)
    relay._asked_path(proj).parent.mkdir(parents=True, exist_ok=True)
    relay._asked_path(proj).write_text(json.dumps({"m_q00000000000001": rec}))
    return tid


def _inbound(tid, frm, body, mtype="answer"):
    from test_relay_client import msg

    return msg("m_ans7000000000007", mtype, body, frm=frm, ticket=tid, reply_to="m_q00000000000001")


def test_no_inbound_message_takes_a_question_back(proj):
    tid = _asked_question(proj)
    evil = {"taken_back": {"reason": "x", "by": "ph"}, "take_back": "q1", "answer": "--take-back q1 gone"}
    for frm, extra in (
        ("ws_other00001", {}),  # another workspace
        ("ws_other00001", {"group": {"id": "g_x", "kind": "group"}}),  # a group-routed message
        ("ph_iphone0001", {}),  # a phone
    ):
        for mtype in ("answer", "text"):
            relay._apply_answer(proj, _inbound(tid, frm, {**evil, **extra, "question_id": "q1"}, mtype))
        q = tickets.load(proj, tid)["questions"][0]
        assert "taken_back" not in q, frm
        assert q["answer"] in (None, "--take-back q1 gone")  # at most a plain answer, never a take-back
        assert not any(h["text"].startswith("Taken back") for h in tickets.load(proj, tid)["history"])
        if q["answer"] is not None:  # reset for the next sender
            p = tickets.ticket_path(proj, tid)
            t = json.loads(p.read_text())
            t["questions"][0].update(answer=None, answered_by=None, via=None)
            p.write_text(json.dumps(t))


def test_a_phone_answer_to_a_taken_back_question_is_refused(proj):
    tid = _asked_question(proj)
    tickets.take_back(proj, tid, "q1", "plan changed", "agent:claude")
    ans = _inbound(tid, "ph_iphone0001", {"question_id": "q1", "answer": "yes", "answered_by": "human:a"})
    note, applied = relay._apply_answer(proj, ans)
    assert applied is None and "taken back: plan changed" in note
    q = tickets.load(proj, tid)["questions"][0]
    assert q["answer"] == "Taken back: plan changed"


def test_only_the_cli_calls_take_back():
    """Structural: no relay, inbox, group, phone or add-on code can reach the take-back function."""
    from pathlib import Path

    src = Path(relay.__file__).parent
    hits = {
        p.name for p in src.rglob("*.py") if "take_back" in p.read_text(encoding="utf-8", errors="ignore")
    }
    assert hits <= {"tickets.py", "cli.py"}, hits
