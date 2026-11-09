"""fb8: a ticket in Review asks the phones "Is this done?" (review-<n>); a phone's answer accepts it or asks
for changes, once, only while the ticket is in Review (contracts/vectors/review-question-v1.json)."""

import json
from pathlib import Path

import jsonschema
import pytest
from fakes import WS
from test_relay_client import msg

from orch import phone_view, relay, runs, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"


@pytest.fixture
def conn(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [{"id": PHONE, "name": "iPhone", "online": True, "last_seen": None}]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def review_questions(rel):
    return [m for m in rel.sent if m["type"] == "question" and m["body"].get("review")]


def to_review(proj, tid):
    tickets.set_status(proj, tid, "review", "human:t")


def answer(rel, qmsg, text, n=1, frm=PHONE, by="human:iPhone", qid=None):
    mid = f"m_ans{n:013d}"
    rel.inbox.append(
        msg(
            mid,
            "answer",
            {"question_id": qid or qmsg["body"]["question_id"], "answer": text, "answered_by": by},
            frm=frm,
            ticket=qmsg["ticket"],
            reply_to=qmsg["id"],
        )
    )
    return mid


def status(run, tid):
    return json.loads(run("ticket", "show", tid, "--json")[1])


def test_review_question_matches_the_contract(proj, run, new_ticket, conn):
    tid = new_ticket("Make the html")
    assert phone_view.sync_reviews(proj) == []  # not in review: nothing
    to_review(proj, tid)
    assert phone_view.sync_reviews(proj) == [tid]
    (q,) = review_questions(conn)
    assert q["to"] == "phones" and q["ticket"] == tid
    assert q["body"] == {
        "question_id": "review-1",
        "title": "Make the html",
        "text": "Is this done?",
        "options": ["accept", "changes"],
        "recommended": None,
        "review": True,
    }
    schema = json.loads((CONTRACTS / "message.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate({**q, "schema": "orch.msg/1"})
    assert phone_view.sync_reviews(proj) == [] and len(review_questions(conn)) == 1  # once per review


def test_no_phone_no_question(proj, run, new_ticket, rel):
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    tid = new_ticket()
    to_review(proj, tid)
    assert phone_view.sync_reviews(proj) == [] and not review_questions(rel)


def test_accept_from_the_phone_finishes_the_ticket_once(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    mid = answer(conn, q, "accept")
    code, out, _ = run("relay", "inbox")
    assert "accepted" in out
    t = status(run, tid)
    assert t["status"] == "done"
    last = t["history"][-1]
    assert last["by"] == "human:iPhone" and last["via"] == "phone"
    assert mid in json.loads((proj / ".orch/inbox-seen.json").read_text())
    # the same answer again, and a second one: nothing more happens
    n = len(t["history"])
    answer(conn, q, "accept", n=2)
    run("relay", "inbox")
    assert len(status(run, tid)["history"]) == n + 1  # only the "too late" line
    assert status(run, tid)["status"] == "done"


def test_changes_from_the_phone_is_ask_for_changes(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "Please also rename Y")
    assert "asked for changes" in run("relay", "inbox")[1]
    t = status(run, tid)
    assert t["status"] == "ready"
    assert t["checklist"][-1]["text"] == "Change: Please also rename Y"
    (item,) = runs._pending_read(proj, tid)
    assert item["by"] == "human:iPhone" and item["text"] == "Please also rename Y"


def test_answer_after_the_ticket_left_review_changes_nothing(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    tickets.set_status(proj, tid, "done", "human:dash")  # the dashboard decided first
    answer(conn, q, "accept")
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "done" and "too late" in t["history"][-1]["text"] + t["history"][-2]["text"]
    assert not any(h["by"] == "human:iPhone" and h["text"].startswith("Status") for h in t["history"])


def test_stale_round_and_new_round(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q1,) = review_questions(conn)
    tickets.set_status(proj, tid, "ready", "human:dash")
    assert phone_view.sync_reviews(proj) == []  # leaving review closes round 1
    to_review(proj, tid)
    assert phone_view.sync_reviews(proj) == [tid]
    q2 = review_questions(conn)[-1]
    assert q2["body"]["question_id"] == "review-2"
    answer(conn, q1, "accept")  # the old question: stale
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"
    answer(conn, q2, "accept", n=2)
    run("relay", "inbox")
    assert status(run, tid)["status"] == "done"


@pytest.mark.parametrize("frm", ["sub_abc12345", "ws_reports001"])
def test_only_a_paired_phone_may_accept(proj, run, new_ticket, conn, frm):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "accept", frm=frm, by="human:boss")
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"
    # and the round is still open for the real phone
    answer(conn, q, "accept", n=2)
    run("relay", "inbox")
    assert status(run, tid)["status"] == "done"


def test_empty_answer_is_ignored(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "   ")
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"


def test_an_agent_session_never_applies_the_answer(proj, run, new_ticket, conn, monkeypatch):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    mid = answer(conn, q, "accept")
    monkeypatch.setenv("CLAUDECODE", "1")
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"
    seen = proj / ".orch/inbox-seen.json"
    assert not seen.exists() or mid not in json.loads(seen.read_text())
    monkeypatch.delenv("CLAUDECODE")
    run("relay", "inbox")  # the workspace's own process applies it
    assert status(run, tid)["status"] == "done"


def test_agents_cannot_accept_directly(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    to_review(proj, tid)
    with pytest.raises(tickets.Refused):
        tickets.accept_review(proj, tid, "agent:claude-code")
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(tickets.Refused):
        tickets.accept_review(proj, tid, "human:me")


def test_vector_cases(proj, run, new_ticket, conn):
    """Every outcome of contracts/vectors/review-question-v1.json."""
    vec = json.loads((CONTRACTS / "vectors" / "review-question-v1.json").read_text())
    asked_round = int(vec["question"]["body"]["question_id"].split("-")[1])
    for i, case in enumerate(vec["cases"]):
        tid = new_ticket(case["name"])
        qs = {}
        for r in range(1, case["state"]["round"] + 1):  # enter Review once per round
            to_review(proj, tid)
            phone_view.sync_reviews(proj)
            qs[r] = review_questions(conn)[-1]
            if r < case["state"]["round"]:
                tickets.set_status(proj, tid, "ready", "human:dash")
                phone_view.sync_reviews(proj)
        q = qs[asked_round]
        if case["state"]["status"] != "review":
            tickets.set_status(proj, tid, case["state"]["status"], "human:dash")
        mid = f"m_vec{i:013d}"
        conn.inbox.append(
            msg(
                mid,
                "answer",
                {"question_id": q["body"]["question_id"], "answer": case["answer"], "answered_by": "human:iPhone"},
                frm=case["from"],
                ticket=tid,
                reply_to=q["id"],
            )
        )
        run("relay", "inbox")
        t = status(run, tid)
        want = {"accept": "done", "changes": "ready"}.get(case["do"])
        if want:
            assert t["status"] == want, case["name"]
        else:
            assert t["status"] == case["state"]["status"], case["name"]


def test_leaving_and_reentering_review_between_syncs_makes_the_old_round_stale(proj, run, new_ticket, conn):
    """Opus M1: no sync_reviews between the two status changes; the old accept must not apply."""
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q1,) = review_questions(conn)
    tickets.set_status(proj, tid, "ready", "human:dash")
    to_review(proj, tid)  # an agent/run brings it back; still no sync
    answer(conn, q1, "accept")
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"
    phone_view.sync_reviews(proj)  # (the inbox call already did) a new round asks again
    assert review_questions(conn)[-1]["body"]["question_id"] == "review-2"


def test_a_round_is_bound_to_its_own_message(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    conn.inbox.append(
        msg("m_ans0000000000099", "answer", {"question_id": "review-1", "answer": "accept", "answered_by": "human:x"},
            frm=PHONE, ticket=tid, reply_to="m_other00000000001")
    )
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"


def test_an_unpaired_phone_and_group_messages_are_refused(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "accept", frm="ph_stranger01")
    mid = answer(conn, q, "accept", n=2)
    conn.inbox[-1]["body"]["group"] = {"id": "grp_x"}
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"


def test_attribution_comes_from_the_paired_phone_not_the_body(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "accept", by="human:Alice The Boss")
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "done" and t["history"][-1]["by"] == "human:iPhone"


def test_a_bare_changes_answer_is_a_history_line_only(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "changes")
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "review" and "without a note" in t["history"][-1]["text"]
    answer(conn, q, "Rename Y", n=2)  # the round is still open for a real note
    run("relay", "inbox")
    assert status(run, tid)["status"] == "ready"
