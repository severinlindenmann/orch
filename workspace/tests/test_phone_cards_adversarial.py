# ruff: noqa: F811  (conn is a fixture imported from test_phone_cards)
"""Adversarial tests for Review cards on the phone, the workspace side (security review review-p2sec).

Attacks from an agent (writes in the workspace: tickets, .orch/inbox, questions-sent.json), a peer workspace,
a subscriber or a group member against relay._apply_verdict / _card_plain / phone_view.sync_cards.
Tests marked xfail(strict) document a finding: they pass once it is fixed."""

import copy
import hashlib
import json
import os

import pytest
from test_phone_cards import (  # noqa: F401  (conn is a fixture)
    PHONE,
    VEC,
    add_card,
    card_questions,
    conn,
    img_card,
    install,
    png,
    put_answer,
    question,
    results,
    send_card,
)
from test_relay_client import msg

from orch import phone_view, relay, review, tickets


def _case(name):
    return copy.deepcopy(next(c for c in VEC["workspace"] if c["name"] == name))


def _asked(proj):
    return relay.net.read_json(relay._asked_path(proj), {})


def _write_asked(proj, data):
    relay.net.write_json(relay._asked_path(proj), data, True)


# ---- forged phone verdicts --------------------------------------------------------------------------------


def test_a_verdict_planted_in_the_inbox_folder_is_not_applied(proj, run, new_ticket, conn):
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(
        proj, conn, tid, "q4"
    )  # the agent sees the question id in questions-sent / the relay log
    case = _case("choice-ok-picked")
    forged = msg("m_forge00000000001", "answer", case["body"], frm=PHONE, ticket=tid, reply_to=qmsg["id"])
    inbox = proj / ".orch" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "m_forge00000000001.json").write_text(json.dumps(forged))  # never fetched from the relay
    run("relay", "inbox")
    assert question(proj, tid, "q4")["answer"] is None


def test_a_verdict_from_the_peer_a_question_was_asked_of_is_ignored(proj, run, new_ticket, conn):
    """A question asked of another workspace (to: ws_…): its verdict applies nothing."""
    tid = new_ticket()
    install(proj, tid)
    q = question(proj, tid, "q4")
    mid = "m_peerq0000000001"
    rec = {
        "ticket": tid,
        "question_id": "q4",
        "to": "ws_reports001",
        "question_digest": tickets.question_digest(q),
    }
    relay.sign_asked(proj, mid, rec)
    _write_asked(proj, {**_asked(proj), mid: rec})
    body = _case("choice-ok-picked")["body"]
    body["answered_by"] = "human:iPhone"
    conn.inbox.append(msg("m_peera0000000001", "answer", body, frm="ws_reports001", ticket=tid, reply_to=mid))
    run("relay", "inbox")
    assert question(proj, tid, "q4")["answer"] is None and results(conn) == []


def test_a_plain_answer_from_the_peer_to_a_card_question_is_not_a_person(proj, run, new_ticket, conn):
    """_card_plain: a peer's plain answer to a card question it was asked never becomes a human: decision."""
    tid = new_ticket()
    install(proj, tid)
    q = question(proj, tid, "q4")
    mid = "m_peerq0000000002"
    rec = {
        "ticket": tid,
        "question_id": "q4",
        "to": "ws_reports001",
        "question_digest": tickets.question_digest(q),
    }
    relay.sign_asked(proj, mid, rec)
    _write_asked(proj, {**_asked(proj), mid: rec})
    body = {"question_id": "q4", "answer": "A", "answered_by": "human:owner"}
    conn.inbox.append(msg("m_peera0000000002", "answer", body, frm="ws_reports001", ticket=tid, reply_to=mid))
    run("relay", "inbox")
    got = question(proj, tid, "q4")
    assert got["answer"] is None or not str(got.get("answered_by")).startswith("human:")


def test_an_agent_session_never_applies_a_verdict(proj, run, new_ticket, conn, monkeypatch):
    """A verdict is a person's swipe: an inbox read from an agent session leaves it for the workspace."""
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q3")
    put_answer(conn, qmsg, _case("draft-ok"), 1)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    relay.inbox(proj)
    assert question(proj, tid, "q3")["answer"] is None and results(conn) == []


# ---- MAC coverage of the asked record ---------------------------------------------------------------------


def test_adding_a_digest_to_an_old_review_record_breaks_its_mac(proj, conn):
    rev = {"ticket": "t_x", "question_id": "review-1", "to": "phones", "review": True, "round": 1}
    relay.sign_asked(proj, "m_r1", rev)
    assert relay.asked_mac_ok(proj, "m_r1", rev)
    assert not relay.asked_mac_ok(proj, "m_r1", {**rev, "digest": "ab" * 32})
    signed = {**rev, "digest": "cd" * 32}
    relay.sign_asked(proj, "m_r2", signed)
    stripped = {k: v for k, v in signed.items() if k != "digest"}
    assert not relay.asked_mac_ok(proj, "m_r2", stripped)
    assert not relay.asked_mac_ok(proj, "m_r2", {**signed, "digest": None})


def test_a_digest_on_an_ordinary_record_is_covered_too(proj, conn):
    """An agent cannot add a `digest` to an ordinary record to steer the review/question digest choice."""
    rec = {"ticket": "t_x", "question_id": "q1", "to": "phones", "question_digest": "ab" * 32}
    relay.sign_asked(proj, "m_o1", rec)
    assert not relay.asked_mac_ok(proj, "m_o1", {**rec, "digest": "ab" * 32})


def test_agent_strips_signs_and_rewrites_the_record_digest(proj, run, new_ticket, conn):
    """The agent removes signs:true from the stored card AND moves the asked record's question_digest along:
    the MAC breaks, nothing is applied (and without the record edit the digest check says changed)."""
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q5")

    def strip(t):
        next(q for q in t["questions"] if q["id"] == "q5")["card"].pop("signs")

    tickets.apply_op(proj, tid, strip, by="agent:claude")
    new = tickets.question_digest(question(proj, tid, "q5"))
    asked = _asked(proj)
    asked[qmsg["id"]]["question_digest"] = new
    _write_asked(proj, asked)
    case = _case("signs-ok-refused")
    case["body"]["verdict"]["digest"] = new  # even if the phone were shown the new card
    put_answer(conn, qmsg, case, 1)
    run("relay", "inbox")
    assert question(proj, tid, "q5")["answer"] is None


def test_agent_strips_signs_only_gets_changed(proj, run, new_ticket, conn):
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q5")

    def strip(t):
        next(q for q in t["questions"] if q["id"] == "q5")["card"].pop("signs")

    tickets.apply_op(proj, tid, strip, by="agent:claude")
    put_answer(conn, qmsg, _case("signs-ok-refused"), 1)
    run("relay", "inbox")
    assert question(proj, tid, "q5")["answer"] is None
    (r,) = results(conn)
    assert r["body"]["review_result"] == {"result": "changed"}


def test_old_phone_plain_option_on_a_signs_choice_card_is_never_an_ok(proj, run, new_ticket, conn):
    """_card_plain: an option id typed on a signs:true choice card is talk, never use/approve."""
    tid = new_ticket()
    install(proj, tid)

    def make_signs(t):
        next(q for q in t["questions"] if q["id"] == "q4")["card"]["signs"] = True

    tickets.apply_op(proj, tid, make_signs, by="agent:claude")
    q = question(proj, tid, "q4")
    relay.send_question(proj, tickets.load(proj, tid), q)
    qmsg = [m for m in conn.sent if m["type"] == "question"][-1]
    opt = review._option_ids(q, q["card"])[0]
    conn.inbox.append(
        msg(
            "m_oldph0000000001",
            "answer",
            {"question_id": "q4", "answer": opt},
            frm=PHONE,
            ticket=tid,
            reply_to=qmsg["id"],
        )  # fmt: skip
    )
    run("relay", "inbox")
    d = question(proj, tid, "q4").get("decision") or {}
    assert d.get("action") not in ("use", "approve")


# ---- replay -----------------------------------------------------------------------------------------------


def test_an_old_verdict_does_not_answer_the_changed_follow_up(proj, run, new_ticket, conn):
    """Computer answered q4, then changed it (a NEW entry): a delayed phone verdict on the old question
    message is `decided` and never reaches the new entry (its id is in the digest)."""
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q4")
    review.decide(proj, tid, "q4", "ok", "A", None, by="human:me", via="page")
    new = review.change(proj, tid, "q4", "ok", "B", None, by="human:me", via="page")
    put_answer(conn, qmsg, _case("choice-ok-picked"), 1)
    run("relay", "inbox")
    assert question(proj, tid, new["id"])["decision"]["picked"] == "B"
    (r,) = results(conn)
    assert r["body"]["review_result"]["result"] == "decided"


def test_forged_vresults_cannot_make_an_applied_or_block_application(proj, run, new_ticket, conn):
    """An agent writes vresults/vpending into the (unsigned part of the) asked record: the verdict is still
    decided on its merits (the worst case is no result text, never a wrong decision)."""
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q4")
    asked = _asked(proj)
    asked[qmsg["id"]]["vresults"] = {"m_other": {"to": PHONE, "id": "m_x", "created_at": "x", "body": {}}}
    asked[qmsg["id"]]["vpending"] = "m_cs00000000000001"
    _write_asked(proj, asked)
    assert relay.asked_mac_ok(proj, qmsg["id"], _asked(proj)[qmsg["id"]])
    put_answer(conn, qmsg, _case("choice-ok-picked"), 1)
    run("relay", "inbox")
    assert question(proj, tid, "q4")["decision"]["picked"] == "C"
    assert all(
        r["body"]["review_result"].get("result") != "applied" or r["to"] == PHONE for r in results(conn)
    )


# ---- what goes to the phones ------------------------------------------------------------------------------

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.mark.parametrize("where", ["why", "table"])
def test_a_secret_in_card_text_never_reaches_the_phone(proj, new_ticket, conn, where):
    tid = new_ticket()
    card = {"kind": "draft", "title": "Deploy", "then": "The helper deploys."}
    if where == "why":
        card["why"] = f"token {SECRET}"
    else:
        card["preview"] = {"type": "table", "cols": ["Name", "Value"], "rows": [["GITHUB_TOKEN", SECRET]]}
    add_card(proj, tid, card, {})
    phone_view.sync_cards(proj)
    sent = json.dumps([m["body"] for m in conn.sent if m["type"] == "question"])
    assert SECRET not in sent


def test_a_reviewed_html_with_a_secret_is_held_back(proj, new_ticket, conn):
    tid = new_ticket()
    page = f"<html><body><p>config</p><!-- AWS_SECRET_ACCESS_KEY={SECRET} --></body></html>".encode()
    card = {
        "kind": "draft",
        "title": "Page",
        "then": "Publish.",
        "preview": {"type": "page", "src": "p.html"},
    }
    add_card(proj, tid, card, {"p.html": page})
    phone_view.sync_cards(proj)
    (m,) = card_questions(conn)
    assert m["body"]["card"]["preview"]["src"] == {"file": None, "why": "held_back"}
    assert "card_files" not in m["body"] and page not in conn.blobs.values()


def test_a_reviewed_copy_swapped_for_a_symlink_is_held_back(proj, new_ticket, conn, tmp_path):
    """The agent replaces the reviewed copy by a link to a file outside (with shown.files moved along)."""
    tid = new_ticket()
    q = add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})
    src = q["card"]["preview"]["src"]
    outside = tmp_path / "outside.png"
    other = png(7)
    outside.write_bytes(other)
    path = proj / ".orch" / "tickets" / tid / src
    path.unlink()
    os.symlink(outside, path)
    name = src.rsplit("/", 1)[-1]

    def move(t):
        t["questions"][0]["shown"]["files"][name] = hashlib.sha256(other).hexdigest()

    tickets.apply_op(proj, tid, move, by="agent:claude")
    phone_view.sync_cards(proj)
    (m,) = card_questions(conn)
    assert m["body"]["card"]["preview"]["src"] == {"file": None, "why": "held_back"}
    assert other not in conn.blobs.values()


def test_a_copy_outside_the_reviewed_folder_is_never_read(proj, new_ticket, conn):
    """shown.copy / src pointing elsewhere (another ticket, ..): read_reviewed returns None."""
    tid = new_ticket()
    q = add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})
    shown = q["shown"]
    sha12 = q["card"]["preview"]["src"].split("/")[1]
    for src in (f"reviewed/{sha12}/../x.png", f"reviewed/{sha12}/sub/x.png", "../t_other/reviewed/x/y.png"):
        assert review.read_reviewed(proj, tid, shown, src) is None
    bad = {**shown, "copy": "reviewed/000000000000/"}
    assert review.read_reviewed(proj, tid, bad, q["card"]["preview"]["src"]) is None


def test_sync_cards_never_sends_an_answered_or_cardless_question(proj, new_ticket, conn):
    tid = new_ticket()
    install(proj, tid)
    review.decide(proj, tid, "q4", "ok", "A", None, by="human:me", via="page")
    tickets.ask(proj, tid, "Plain?", ["Yes"], None, "agent:claude")
    sent = phone_view.sync_cards(proj)
    assert f"{tid}:q4" not in sent
    assert all(m["body"]["question_id"] != "q4" for m in card_questions(conn))
    assert all("card" in m["body"] for m in card_questions(conn))


# ---- the person's words -----------------------------------------------------------------------------------


def test_note_text_is_cleaned_before_it_is_stored(proj, run, new_ticket, conn):
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q3")
    case = _case("draft-talk-words-voice")
    case["body"]["verdict"]["note"] = {
        "changes": ["Use the ‮evil‬ date"],
        "words": {"text": "Fix it⁦ now\x07", "voice": []},
    }
    put_answer(conn, qmsg, case, 1)
    run("relay", "inbox")
    d = question(proj, tid, "q3")["decision"]
    blob = json.dumps(d, ensure_ascii=False)
    for bad in ("‮", "‬", "⁦", "\x07"):
        assert bad not in blob
    assert question(proj, tid, "q3")["answered_by"] == "human:iPhone"


def test_check_digest_covers_wont_do_like_the_check_card():
    t = {
        "id": "t_x",
        "title": "T",
        "status": "review",
        "checklist": [{"id": "c1", "text": "Step", "done": False}],
    }
    before = review.check_digest(t)
    t["checklist"][0]["wont_do"] = True  # check_card shows it as Done
    assert review.check_digest(t) != before


def test_a_secret_in_a_card_file_name_never_reaches_the_phone(proj, new_ticket, conn):
    tid = new_ticket()
    name = f"{SECRET}.png"
    add_card(proj, tid, img_card(name), {name: png()})
    phone_view.sync_cards(proj)
    sent = json.dumps([m["body"] for m in conn.sent if m["type"] == "question"])
    assert SECRET not in sent
    assert "card_files" not in json.loads(sent)[0]
