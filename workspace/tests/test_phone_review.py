"""fb8: a ticket in Review asks the phones "Is this done?" (review-<n>); a phone's answer accepts it or asks
for changes, once, only while the ticket is in Review (contracts/vectors/review-question-v1.json)."""

import json
from pathlib import Path

import jsonschema
import pytest
from fakes import WS
from test_relay_client import msg

from orch import phone_view, relay, review, runs, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"


@pytest.fixture
def conn(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [
        {"id": PHONE, "name": "iPhone", "online": True, "last_seen": None}
    ]
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
    digest = q["body"].pop("digest")  # new: what the phone echoes in a verdict
    card = q["body"].pop("card")  # new: the Check card (kind check)
    assert digest == review.check_digest(tickets.load(proj, tid)) and card["kind"] == "check"
    assert q["body"] == {
        "question_id": "review-1",
        "title": "Make the html",
        "text": "Is this done?",
        "options": ["accept", "changes"],
        "recommended": None,
        "review": True,
    }
    q["body"].update(digest=digest, card=card)
    schema = json.loads((CONTRACTS / "message.schema.json").read_text(encoding="utf-8"))
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
    assert t["checklist"][-1]["text"] == "Please also rename Y"
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
    vec = json.loads((CONTRACTS / "vectors" / "review-question-v1.json").read_text(encoding="utf-8"))
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
                {
                    "question_id": q["body"]["question_id"],
                    "answer": case["answer"],
                    "answered_by": "human:iPhone",
                },
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
        msg(
            "m_ans0000000000099",
            "answer",
            {"question_id": "review-1", "answer": "accept", "answered_by": "human:x"},
            frm=PHONE,
            ticket=tid,
            reply_to="m_other00000000001",
        )
    )
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"


def test_an_unpaired_phone_and_group_messages_are_refused(proj, run, new_ticket, conn):
    tid = new_ticket()
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    (q,) = review_questions(conn)
    answer(conn, q, "accept", frm="ph_stranger01")
    answer(conn, q, "accept", n=2)
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


def _file_says(proj, tid, status):
    """What an agent's direct file edit does: no core code runs, no verdict."""
    p = tickets.ticket_path(proj, tid)
    t = json.loads(p.read_text())
    t["status"] = status
    p.write_text(json.dumps(t, indent=2))


def test_a_review_in_the_file_asks_the_phones_once(proj, run, new_ticket, conn):
    tid = new_ticket()
    _file_says(proj, tid, "done")  # a raw done is Done (no verdict needed): nothing to ask
    assert tickets.load(proj, tid)["status"] == "done"
    assert phone_view.sync_reviews(proj) == [] and not review_questions(conn)
    _file_says(proj, tid, "review")
    assert phone_view.sync_reviews(proj) == [tid]
    (q,) = review_questions(conn)
    assert q["body"]["question_id"] == "review-1" and q["body"]["options"] == ["accept", "changes"]
    assert phone_view.sync_reviews(proj) == [] and len(review_questions(conn)) == 1  # not duplicated
    _file_says(proj, tid, "ready")  # leaves review: round closes
    assert phone_view.sync_reviews(proj) == []
    _file_says(proj, tid, "review")  # enters again: a new round
    assert phone_view.sync_reviews(proj) == [tid]
    assert review_questions(conn)[-1]["body"]["question_id"] == "review-2"


def test_a_signed_done_sends_no_review_question(proj, run, new_ticket, conn):
    from conftest import sign_done

    tid = new_ticket()
    sign_done(proj, tid)
    assert tickets.load(proj, tid)["status"] == "done"
    assert phone_view.sync_reviews(proj) == [] and not review_questions(conn)


def test_verdict_cases(proj, run, new_ticket, conn):
    """Every verdict case of contracts/vectors/review-question-v1.json (a swipe on the Check card)."""
    vec = json.loads((CONTRACTS / "vectors" / "review-question-v1.json").read_text(encoding="utf-8"))
    asked_round = int(vec["question"]["body"]["question_id"].split("-")[1])
    for i, case in enumerate(vec["verdict_cases"]):
        tid = new_ticket(case["name"])
        qs = {}
        for r in range(1, case["state"]["round"] + 1):
            to_review(proj, tid)
            phone_view.sync_reviews(proj)
            qs[r] = review_questions(conn)[-1]
            if r < case["state"]["round"]:
                tickets.set_status(proj, tid, "ready", "human:dash")
                phone_view.sync_reviews(proj)
        q = qs[asked_round]
        if case["state"].get("checklist_changed"):
            _bump_checklist(proj, tid)
        if case["state"]["status"] != "review":
            tickets.set_status(proj, tid, case["state"]["status"], "human:dash")
        before = len([m for m in conn.sent if "review_result" in m["body"]])
        body = {
            "question_id": q["body"]["question_id"],
            "answer": case["answer"],
            "answered_by": "human:iPhone",
        }
        verdict = json.loads(json.dumps(case["verdict"]))
        verdict["digest"] = q["body"]["digest"]  # the vector's digest is of ITS ticket; ours is this one
        body["verdict"] = verdict
        if case.get("group"):
            body["group"] = {"id": "grp_x", "host": "ws_reports001"}
        conn.inbox.append(
            msg(f"m_vq{i:014d}", "answer", body, frm=case["from"], ticket=tid, reply_to=q["id"])
        )
        run("relay", "inbox")
        t = status(run, tid)
        want = {"accept": "done", "changes": "ready"}.get(case["do"])
        label = case["name"]
        if want:
            assert t["status"] == want, label
            if case["do"] == "changes":
                assert t["checklist"][-1]["text"] == case["note"], label
            assert t["history"][-1]["by"] == "human:iPhone" or any(
                h["by"] == "human:iPhone" for h in t["history"]
            ), label
        else:
            assert t["status"] == case["state"]["status"], label
        got = [m for m in conn.sent if "review_result" in m["body"]][before:]
        if case["result"] is None:
            assert got == [], label
        else:
            (r,) = got
            assert r["body"]["review_result"] == case["result"], label
            assert r["to"] == PHONE and r["reply_to"] == q["id"], label


def _bump_checklist(proj, tid):
    def op(t):
        t["checklist"].append({"id": "c_new", "text": "Added after it was shown", "done": False})

    tickets.apply_op(proj, tid, op, by="human:dash")


# ---- ORCH-444: voice notes, pictures and files added to a Send back on the phone ----------------------

VOICE_B, PHOTO_B, PDF_B = "b_v0icenote000001a", "b_ph0to00000000001", "b_pdf0000000000001"
PHOTO = {"blob_id": PHOTO_B, "kind": "image", "name": "screen.jpg", "size": 8, "mime": "image/jpeg"}


def _send_back(conn, proj, new_ticket, note, n=1):
    tid = new_ticket(f"files {n}")
    to_review(proj, tid)
    phone_view.sync_reviews(proj)
    q = review_questions(conn)[-1]
    body = {
        "question_id": q["body"]["question_id"],
        "answer": "Send back for changes",
        "answered_by": "human:iPhone",
        "verdict": {"verdict": "talk", "digest": q["body"]["digest"], "note": note},
    }
    conn.inbox.append(msg(f"m_fb{n:014d}", "answer", body, frm=PHONE, ticket=tid, reply_to=q["id"]))
    return tid


def _files(proj, tid):
    d = proj / ".orch" / "tickets" / tid / "files"
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def _blobs(conn):
    conn.blobs[VOICE_B] = b"\x00\x00\x00\x18ftypM4A voice"
    conn.blobs[PHOTO_B] = b"\xff\xd8\xff\xe0jpeg"
    conn.blobs[PDF_B] = b"%PDF-1.7 offer"


def test_send_back_with_a_voice_note_a_picture_and_a_file_lands_on_the_ticket(proj, run, new_ticket, conn):
    _blobs(conn)
    note = {
        "words": {
            "text": "Make the logo bigger",
            "voice": [{"blob_id": VOICE_B, "transcript": "Logo bigger", "lang": "en", "duration": 2.5}],
        },
        "files": [
            PHOTO,
            {"blob_id": PDF_B, "kind": "file", "name": "../../offer.pdf", "size": 14, "mime": "app/pdf"},
        ],
    }
    tid = _send_back(conn, proj, new_ticket, note)
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "ready"
    assert _files(proj, tid) == ["offer.pdf", "screen.jpg", "voice-1.m4a"]  # the phone's name is cleaned
    step = t["checklist"][-1]["text"]
    assert step.startswith("Make the logo bigger\n\nI added 3 files to this ticket from the phone: ")
    base = f".orch/tickets/{tid}/files/"
    for line in (f"Voice recording: {base}voice-1.m4a", f"Photo: {base}screen.jpg", f"File: {base}offer.pdf"):
        assert line in step
    assert step.endswith("Read them first.")
    (item,) = runs._pending_read(proj, tid)
    assert "screen.jpg" in item["text"] and item["by"] == "human:iPhone"
    assert (proj / base / "offer.pdf").read_bytes() == b"%PDF-1.7 offer"


def test_files_alone_are_enough_to_send_back(proj, run, new_ticket, conn):
    _blobs(conn)
    note = {"files": [PHOTO]}
    tid = _send_back(conn, proj, new_ticket, note)
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "ready"
    assert t["checklist"][-1]["text"] == (
        "I added a file to this ticket from the phone: "
        f"Photo: .orch/tickets/{tid}/files/screen.jpg. Read it first."
    )


def test_a_file_the_relay_cannot_serve_yet_keeps_the_answer_for_the_next_pull(
    proj, run, new_ticket, conn, monkeypatch
):
    from test_phone_v3 import _flaky_blob

    _blobs(conn)
    calls = _flaky_blob(monkeypatch, 1)
    note = {
        "words": {"text": "See the picture"},
        "files": [PHOTO],
    }
    tid = _send_back(conn, proj, new_ticket, note)
    run("relay", "inbox")
    assert status(run, tid)["status"] == "review"  # the round stays open: nothing decided without the file
    assert not [m for m in conn.sent if "review_result" in m["body"]]
    run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "ready" and calls["n"] == 2
    assert "Photo: " in t["checklist"][-1]["text"] and _files(proj, tid) == ["screen.jpg"]
    (r,) = [m for m in conn.sent if "review_result" in m["body"]]
    assert r["body"]["review_result"]["result"] == "applied"


def test_a_file_that_never_comes_is_named_and_the_answer_still_counts(
    proj, run, new_ticket, conn, monkeypatch
):
    from test_phone_v3 import _flaky_blob

    from orch import relay

    _blobs(conn)
    _flaky_blob(monkeypatch, 99)
    monkeypatch.setattr(relay, "PHONE_RETRY_SECONDS", 0)
    note = {
        "words": {"text": "See the picture"},
        "files": [PHOTO],
    }
    tid = _send_back(conn, proj, new_ticket, note)
    for _ in range(relay.PHONE_TRIES + 1):
        run("relay", "inbox")
    t = status(run, tid)
    assert t["status"] == "ready"
    assert "Photo screen.jpg: could not be downloaded." in t["checklist"][-1]["text"]


def test_the_file_line_never_cuts_the_persons_words():
    """Codex review: a 2,000-character note lost its end to the file line; now the short line is used."""
    saved = ["Photo: .orch/tickets/t_x/files/screen.jpg", "File: .orch/tickets/t_x/files/offer.pdf"]
    own = "x" * 1900 + " Do not publish."
    out = relay._note_with_files({"words": {"text": own}}, saved)
    text = out["words"]["text"]
    assert text.startswith(own) and len(text) <= relay.NOTE_WORDS_MAX
    assert text.endswith("I added 2 files from the phone to this ticket's files. Read them first.")
    short = relay._note_with_files({"words": {"text": "Bigger logo"}}, saved)["words"]["text"]
    assert "screen.jpg" in short and "offer.pdf" in short  # names when they fit


def test_the_file_line_reaches_the_helper_with_twenty_changes():
    """Codex review: at 20 changes the line was only in words, which the helper's task does not read."""
    changes = [f"change {i}" for i in range(relay.NOTE_CHANGES_MAX)]
    out = relay._note_with_files({"changes": changes}, ["Photo: .orch/tickets/t_x/files/screen.jpg"])
    assert len(out["changes"]) == relay.NOTE_CHANGES_MAX
    assert out["changes"][:-1] == changes[:-1]
    assert out["changes"][-1].startswith("change 19 I added a file to this ticket from the phone: ")
    assert all(len(c) <= relay.NOTE_CHANGE_MAX for c in out["changes"])
    few = relay._note_with_files({"changes": ["a"]}, ["Photo: p.jpg"])["changes"]
    assert few == ["a", "I added a file to this ticket from the phone: Photo: p.jpg. Read it first."]
