"""Review stack on the phone, the workspace side (relay-api.md 'Review cards on the phone'): cards go to the
paired phones once with their reviewed files, a phone verdict becomes review.decide, one review_result goes
back. Replays every `workspace` case of contracts/vectors/review-card-v1.json and the `verdict_cases` of
review-question-v1.json."""

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from conftest import ensure_signing
from fakes import WS
from test_relay_client import msg

from orch import phone_view, relay, review, tickets
from orch.errors import Refused

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"
VEC = json.loads((CONTRACTS / "vectors" / "review-card-v1.json").read_text())
RQ = json.loads((CONTRACTS / "vectors" / "review-question-v1.json").read_text())
SCHEMA = json.loads((CONTRACTS / "message.schema.json").read_text())
MSG_V = jsonschema.Draft202012Validator(SCHEMA)


@pytest.fixture
def conn(proj, run, rel):
    ensure_signing(proj)
    rel.snapshot["workspaces"]["phones"] = [
        {"id": PHONE, "name": "iPhone", "online": True, "last_seen": None}
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def card_questions(rel):
    return [m for m in rel.sent if m["type"] == "question" and "card" in m["body"]]


def results(rel):
    return [m for m in rel.sent if m["type"] == "text" and "review_result" in m["body"]]


def install(proj, tid):
    """The stored questions of the vector, as the workspace keeps them (digests are the contract's)."""
    for sq in VEC["stored_questions"]:
        q = {"answered_by": None, "via": None, **copy.deepcopy(sq)}

        def op(t, q=q):
            t["questions"].append(q)
            t["status"] = "waiting"
            t["waiting_on"] = {"kind": "question", "ref": q["id"]}

        tickets.apply_op(proj, tid, op, by="agent:claude")
    t = tickets.load(proj, tid)
    for q in t["questions"]:
        assert tickets.question_digest(q) == VEC["digests"][q["id"]], q["id"]
    return t


def send_card(proj, rel, tid, qid):
    t = tickets.load(proj, tid)
    q = next(x for x in t["questions"] if x["id"] == qid)
    refs = {src: i for i, src in enumerate(review.card_files_of(q["card"]))}
    wire = review.wire_card(q["card"], refs)
    relay.send_question(proj, t, q, card=wire, digest=tickets.question_digest(q))
    return card_questions(rel)[-1]


def put_answer(rel, qmsg, case, n):
    mid = f"m_cs{n:014d}"
    rel.inbox.append(
        msg(
            mid,
            "answer",
            copy.deepcopy(case["body"]),
            frm=case["from"],
            ticket=qmsg["ticket"],
            reply_to=qmsg["id"],
        )
    )
    return mid


def question(proj, tid, qid):
    return next(x for x in tickets.load(proj, tid)["questions"] if x["id"] == qid)


def test_workspace_vector_cases(proj, run, new_ticket, conn):
    for i, case in enumerate(VEC["workspace"]):
        tid = new_ticket(case["name"])
        install(proj, tid)
        qmsg = send_card(proj, conn, tid, case["question"])
        st = case.get("state", {})
        if st.get("stored_question_changed"):

            def edit(t, qid=case["question"]):
                next(q for q in t["questions"] if q["id"] == qid)["card"]["title"] = "Other"

            tickets.apply_op(proj, tid, edit, by="agent:claude")
        if st.get("answered"):
            review.decide(proj, tid, case["question"], "ok", "B", None, by=st["answered"]["by"], via="page")
            assert question(proj, tid, case["question"])["decision"]["summary"] == st["answered"]["summary"]
        before = len(results(conn))
        put_answer(conn, qmsg, case, i)
        run("relay", "inbox")
        q = question(proj, tid, case["question"])
        want = case["expect"]
        label = case["name"]
        if want["do"] == "decide":
            assert q["answered_by"] == want["by"] and q["via"] == want["via"], label
            d = q["decision"]
            for k, v in want["decision"].items():
                assert d[k] == v, (label, k)
            if "answer" in want:
                assert q["answer"] == want["answer"], label
            if "words" in want:
                assert d["words"] == want["words"], label
        elif st.get("answered"):
            assert q["answered_by"] == st["answered"]["by"] and q["via"] == "page", label
            assert q["decision"]["action"] == "use" and q["decision"]["picked"] == "B", label
        else:
            assert q["answer"] is None, label
        got = results(conn)[before:]
        wr = want["review_result"]
        if wr is None:
            assert got == [], label
        else:
            (r,) = got
            assert r["body"]["review_result"] == wr, label
            assert r["to"] == PHONE and r["reply_to"] == qmsg["id"] and r["ticket"] == tid, label
            assert r["body"]["text"] == relay._review_result_text(wr), label
            assert sorted(r["body"]) == ["review_result", "text"], label
            MSG_V.validate({**r, "schema": "orch.msg/1"})
        if "history" in want:
            assert any(want["history"] in h["text"] for h in tickets.load(proj, tid)["history"]), label


def test_no_change_from_the_phone_after_a_computer_answer(proj, run, new_ticket, conn, monkeypatch):
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q4")
    calls = []
    monkeypatch.setattr(review, "change", lambda *a, **k: calls.append(1))
    review.decide(proj, tid, "q4", "ok", "A", None, by="human:me", via="page")
    case = next(c for c in VEC["workspace"] if c["name"] == "choice-ok-picked")
    put_answer(conn, qmsg, case, 1)
    run("relay", "inbox")
    assert not calls and question(proj, tid, "q4")["decision"]["picked"] == "A"
    (r,) = results(conn)
    assert r["body"]["review_result"] == {"result": "decided", "summary": "Use A"}


def test_ticket_and_question_come_from_the_record_not_the_answer(proj, run, new_ticket, conn):
    tid, other = new_ticket("one"), new_ticket("two")
    install(proj, tid)
    install(proj, other)
    qmsg = send_card(proj, conn, tid, "q4")
    case = copy.deepcopy(next(c for c in VEC["workspace"] if c["name"] == "choice-ok-picked"))
    case["body"]["ticket"] = other  # extra keys in the answer are never used
    case["body"]["verdict"]["ticket"] = other
    put_answer(conn, qmsg, case, 1)
    conn.inbox[-1]["ticket"] = other
    run("relay", "inbox")
    assert question(proj, tid, "q4")["answer"] == "Use C"
    assert question(proj, other, "q4")["answer"] is None


def test_a_retried_answer_resends_the_same_result_once(proj, run, new_ticket, conn):
    tid = new_ticket()
    install(proj, tid)
    qmsg = send_card(proj, conn, tid, "q4")
    case = next(c for c in VEC["workspace"] if c["name"] == "choice-ok-picked")
    mid = put_answer(conn, qmsg, case, 1)
    run("relay", "inbox")
    (first,) = results(conn)
    # the answer is handled again (a crash before "seen"): same result id, nothing applied twice
    seen = proj / ".orch/inbox-seen.json"
    data = json.loads(seen.read_text())
    seen.write_text(json.dumps([x for x in data if x != mid] if isinstance(data, list) else data))
    run("relay", "inbox")
    again = results(conn)
    assert {m["id"] for m in again} == {first["id"]}
    assert question(proj, tid, "q4")["decision"]["picked"] == "C"
    # a second answer of the same question gets no second result
    case2 = next(c for c in VEC["workspace"] if c["name"] == "choice-no")
    put_answer(conn, qmsg, case2, 2)
    run("relay", "inbox")
    assert {m["id"] for m in results(conn)} == {first["id"]}


def test_old_phone_without_a_verdict_keeps_working_on_plain_questions(proj, run, new_ticket, conn):
    tid = new_ticket()
    t, q = tickets.ask(proj, tid, "Send it?", ["Yes", "No"], None, "agent:claude")
    relay.send_question(proj, tickets.load(proj, tid), q)
    qmsg = next(m for m in conn.sent if m["type"] == "question")
    conn.inbox.append(
        msg(
            "m_plain00000000001",
            "answer",
            {"question_id": q["id"], "answer": "Yes", "answered_by": "human:iPhone"},
            frm=PHONE,
            ticket=tid,
            reply_to=qmsg["id"],
        )
    )
    run("relay", "inbox")
    got = question(proj, tid, q["id"])
    assert got["answer"] == "Yes" and "decision" not in got and results(conn) == []


# ---- RULE A: asked records and bodies of old questions stay as they were --------------------------------


def test_asked_records_carry_no_mac(proj, conn):
    assert not hasattr(relay, "asked_mac_ok") and not hasattr(relay, "QUESTION_MAC_KIND")  # MAC gone


def test_question_without_card_fields_is_byte_identical(proj, new_ticket, conn):
    tid = new_ticket()
    t, q = tickets.ask(proj, tid, "Ok?", ["Yes"], None, "agent:claude")
    m = relay.send_question(proj, tickets.load(proj, tid), q)
    assert set(m["body"]) == {"question_id", "title", "text", "options", "recommended"}


# ---- sync_cards -----------------------------------------------------------------------------------------


def _chunk(kind: bytes, body: bytes) -> bytes:
    import zlib

    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def png(n=1):
    """A well-formed PNG (the secret gate reads anything else as unknown); n varies the bytes."""
    ihdr = _chunk(b"IHDR", (n).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0]))
    return b"\x89PNG\r\n\x1a\n" + ihdr + _chunk(b"IEND", b"")


def add_card(proj, tid, card, files):
    for name, data in files.items():
        (proj / name).write_bytes(data)
    card, shown = review.prepare_card(proj, tid, card)
    _, q = tickets.ask(proj, tid, card["title"], [], None, "agent:claude", card=card, shown=shown)
    return q


def img_card(name):
    return {"kind": "draft", "title": "Send the invoice", "then": "The helper sends it.",
            "preview": {"type": "img", "src": name, "alt": "Invoice"}}  # fmt: skip


def test_sync_cards_sends_once_with_files_and_digest(proj, new_ticket, conn):
    tid = new_ticket()
    data = png()
    q = add_card(proj, tid, img_card("invoice.png"), {"invoice.png": data})
    assert phone_view.sync_cards(proj) == [f"{tid}:{q['id']}"]
    (m,) = card_questions(conn)
    b = m["body"]
    assert b["digest"] == tickets.question_digest(tickets.load(proj, tid)["questions"][0])
    assert b["card"]["preview"]["src"] == {"file": 0}
    assert b["card_files"] == [
        {
            "blob_id": b["card_files"][0]["blob_id"],
            "name": "invoice.png",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "mime": "image/png",
        }
    ]
    assert conn.blobs[b["card_files"][0]["blob_id"]] == data
    MSG_V.validate({**m, "schema": "orch.msg/1"})
    assert phone_view.sync_cards(proj) == [] and len(card_questions(conn)) == 1  # idempotent
    rec = relay.net.read_json(relay._asked_path(proj), {})[m["id"]]
    assert rec["question_digest"] == b["digest"] and "question_mac" not in rec


def test_sync_cards_needs_a_phone(proj, run, new_ticket, rel):
    ensure_signing(proj)
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    tid = new_ticket()
    add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})
    assert phone_view.sync_cards(proj) == [] and not card_questions(rel)  # no phone paired


def test_sync_cards_skips_a_question_already_asked_of_the_phones(proj, new_ticket, conn):
    tid = new_ticket()
    q = add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})
    relay.send_question(proj, tickets.load(proj, tid), q)  # e.g. `orch ask` sent it plain
    assert phone_view.sync_cards(proj) == [] and not card_questions(conn)


def test_gate_refusal_holds_the_file_back(proj, new_ticket, conn):
    tid = new_ticket()
    secret = b"password = hunter2hunter2hunter2\nAKIAIOSFODNN7EXAMPLE\n-----BEGIN PRIVATE KEY-----\nabc\n"
    q = add_card(
        proj,
        tid,
        {"kind": "draft", "title": "Look", "then": "Then.", "preview": {"type": "page", "src": "notes.html"}},
        {"notes.html": b"<p>" + secret + b"</p>"},
    )
    assert phone_view.sync_cards(proj) == [f"{tid}:{q['id']}"]
    (m,) = card_questions(conn)
    assert m["body"]["card"]["preview"]["src"] == {"file": None, "why": "held_back"}
    assert "card_files" not in m["body"] and conn.blobs == {}
    MSG_V.validate({**m, "schema": "orch.msg/1"})


def test_over_the_card_budget_is_too_large(proj, new_ticket, conn, monkeypatch):
    tid = new_ticket()
    big, small = png(1), png(2)
    monkeypatch.setattr(review, "MAX_PHONE_CARD", len(small) + 5)  # room for one file only
    card = {
        "kind": "choice", "title": "Pick", "then": "Then.",
        "preview": {"type": "options", "options": [
            {"id": "A", "title": "A", "preview": {"type": "img", "src": "a.png"}},
            {"id": "B", "title": "B", "preview": {"type": "img", "src": "b.png"}},
        ]},
    }  # fmt: skip
    (proj / "a.png").write_bytes(small)
    (proj / "b.png").write_bytes(big)
    c, shown = review.prepare_card(proj, tid, card)
    tickets.ask(proj, tid, "Pick", ["A", "B"], None, "agent:claude", card=c, shown=shown)
    phone_view.sync_cards(proj)
    (m,) = card_questions(conn)
    opts = m["body"]["card"]["preview"]["options"]
    assert opts[0]["preview"]["src"] == {"file": 0}
    assert opts[1]["preview"]["src"] == {"file": None, "why": "too_large"}
    assert len(m["body"]["card_files"]) == 1


def test_a_changed_reviewed_copy_is_held_back(proj, new_ticket, conn):
    tid = new_ticket()
    add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})
    copy_file = next((proj / ".orch" / "tickets" / tid / "reviewed").rglob("invoice.png"))
    copy_file.write_bytes(png(9))  # the agent swapped the reviewed bytes
    phone_view.sync_cards(proj)
    (m,) = card_questions(conn)
    assert m["body"]["card"]["preview"]["src"] == {"file": None, "why": "held_back"}


def test_a_card_that_fails_the_wire_check_goes_without_card(proj, new_ticket, conn, monkeypatch):
    tid = new_ticket()
    add_card(proj, tid, img_card("invoice.png"), {"invoice.png": png()})

    def boom(card, refs):
        raise Refused("nope")

    monkeypatch.setattr(review, "wire_card", boom)
    assert len(phone_view.sync_cards(proj)) == 1
    m = next(x for x in conn.sent if x["type"] == "question")
    assert "card" not in m["body"] and "card_files" not in m["body"] and "digest" not in m["body"]


def test_review_question_carries_the_digest(proj, new_ticket, conn):
    tid = new_ticket()
    tickets.set_status(proj, tid, "review", "human:t")
    assert phone_view.sync_reviews(proj) == [tid]
    (m,) = [x for x in conn.sent if x["type"] == "question" and x["body"].get("review")]
    assert m["body"]["digest"] == review.check_digest(tickets.load(proj, tid))
    MSG_V.validate({**m, "schema": "orch.msg/1"})
    rec = relay.net.read_json(relay._asked_path(proj), {})[m["id"]]
    assert rec["digest"] == m["body"]["digest"] and "question_mac" not in rec


# ---- review.py: the wire card ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", VEC["question_shapes"], ids=lambda s: s["name"])
def test_wire_card_matches_the_schema_vectors(shape):
    card = shape["message"].get("body", {}).get("card")
    if card is None:
        return
    errs = list(MSG_V.iter_errors({**shape["message"], "schema": "orch.msg/1"}))
    n = len(shape["message"]["body"].get("card_files") or [])
    if shape["schema"] is True:
        assert not errs
        review.check_wire_card(card, n)  # the hand-written check agrees with the schema
    else:
        try:
            review.check_wire_card(card, n)
        except Refused:
            return
        # the schema refuses for a reason outside the card (question or files): nothing to say about the card
        assert errs


def test_wire_card_from_the_vector_questions():
    for sq in VEC["stored_questions"]:
        refs = {src: i for i, src in enumerate(review.card_files_of(sq["card"]))}
        wire = review.wire_card(sq["card"], refs)
        name = {"q3": "card-draft", "q4": "card-choice", "q5": "card-no-files"}[sq["id"]]
        want = next(m["message"]["body"]["card"] for m in VEC["question_shapes"] if m["name"] == name)
        assert wire == want


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "img", "src": "a.png", "extra": 1},
        {"type": "img", "src": "a.png", "": "x"},
        {"type": "table", "cols": ["A"], "rows": [["x\x07"]]},
        {"type": "table", "cols": ["A"], "rows": [["x\x7f"]]},
        {"type": "table", "cols": ["A"], "rows": [["a‮b"]]},
        {"type": "doc", "heading": "a⁦b"},
        {"type": "doc", "paras": ["a‪b"]},
        {
            "type": "compare",
            "before": {"type": "img", "src": "a.png", "x": 1},
            "after": {"type": "img", "src": "a.png"},
        },
        {"type": "options", "options": [{"id": "A", "title": "a", "z": 1}, {"id": "B", "title": "b"}]},
    ],
)
def test_validate_card_refuses_what_the_wire_refuses(bad):
    with pytest.raises(Refused):
        review.validate_card({"kind": "draft", "title": "T", "then": "x", "preview": bad})


@pytest.mark.parametrize(
    "field,value",
    [("title", "a‮b"), ("why", "a\x7fb"), ("then", "a⁩b"), ("need", "a\x00b")],
)
def test_validate_card_texts_refuse_bidi_del_and_controls(field, value):
    card = {"kind": "draft", "title": "T", "then": "x", field: value}
    with pytest.raises(Refused):
        review.validate_card(card)


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://example.com/a?b=1", True),
        ("http://host:8080/x", True),
        ("https://user@evil.example/", False),
        ("https://evil.example\\@good.example/", False),
        ("https://exa%6dple.com/", False),
        ("https://example.com/a b", False),
        ("ftp://example.com/", False),
        ("https://", False),
    ],
)
def test_open_is_a_plain_host(url, ok):
    card = {
        "kind": "link",
        "title": "T",
        "then": "x",
        "open": url,
        "preview": {"type": "doc", "paras": ["p"]},
    }
    if ok:
        assert review.validate_card(card)["open"] == url
    else:
        with pytest.raises(Refused):
            review.validate_card(card)


def test_card_json_is_at_most_64_kb_compact():
    paras = ["x" * 1000] * 50
    ok = {"kind": "draft", "title": "T", "then": "x", "preview": {"type": "doc", "paras": paras}}
    assert len(json.dumps(ok, separators=(",", ":"))) < review.MAX_CARD_JSON
    review.validate_card(ok)
    big = {"kind": "draft", "title": "T", "then": "x", "preview": {"type": "table", "cols": ["A"],
           "rows": [["y" * 500]] * 200}}  # fmt: skip
    assert len(json.dumps(big, separators=(",", ":"))) > review.MAX_CARD_JSON
    with pytest.raises(Refused):
        review.validate_card(big)


def test_wire_card_without_a_file_leaves_why(proj):
    card = review.validate_card(img_card("a.png") | {"preview": {"type": "img", "src": "a.png"}})
    w = review.wire_card(card, {"a.png": "too_large"})
    assert w["preview"]["src"] == {"file": None, "why": "too_large"}
    with pytest.raises(Refused):
        review.check_wire_card({**w, "kind": "check", "extra": 1}, 0)
    with pytest.raises(Refused):
        review.check_wire_card({**w, "preview": {"type": "img", "src": {"file": 3}}}, 1)


SPOOF = ["invoice‮gnp.exe", "a‎.png", "a‏.png", "a؜.png", "a⁦.png", "a⁩.png"]


@pytest.mark.parametrize("name", SPOOF)
def test_file_names_with_bidi_or_marks_are_refused_at_prepare(proj, new_ticket, name):
    tid = new_ticket()
    (proj / name).write_bytes(png())
    with pytest.raises(Refused):
        review.prepare_card(proj, tid, img_card(name))
    with pytest.raises(Refused):
        review.copy_reviewed(proj, tid, [name])


@pytest.mark.parametrize("name", SPOOF)
def test_card_name_pattern_holds_back_spoofed_names(name):
    assert phone_view._CARD_NAME.fullmatch(name) is None
    assert phone_view._CARD_NAME.fullmatch("invoice.png")
