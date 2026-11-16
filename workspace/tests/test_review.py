"""Review stack data: cards on questions, reviewed copies, the stack, answers kept on the ticket."""

import json

import pytest
from conftest import ensure_keys

from orch import history, review, tickets
from orch.errors import Refused

ME = "human:severin"


def _raw(root, tid):
    return json.loads(tickets.ticket_path(root, tid).read_text(encoding="utf-8"))


@pytest.fixture
def tk(proj):
    ensure_keys(proj)
    t = tickets.create(proj, "Home layout", ME)
    return proj, t["id"]


CHOICE = {
    "kind": "choice",
    "title": "Home: which layout?",
    "then": "The helper builds the one you pick.",
    "preview": {
        "type": "options",
        "options": [
            {"id": "A", "title": "As today"},
            {"id": "B", "title": "Recent first"},
            {"id": "C", "title": "Questions first"},
        ],
    },
}
DRAFT = {"kind": "draft", "title": "New block", "then": "The helper builds it.", "ok_label": "Build it"}


def _ask(root, tid, card, text="Which one?", options=()):
    card, shown = review.prepare_card(root, tid, card)
    _, q = tickets.ask(root, tid, text, list(options), None, "agent:claude", card=card, shown=shown)
    return q


# 1. old questions keep their fingerprints
def test_old_question_digest_and_answer_mark_are_unchanged(proj):
    q = {"id": "q1", "text": "Send it now?", "options": ["Yes", "No"], "recommended": "Yes",
         "answer": None, "answered_by": None, "via": None}  # fmt: skip
    assert tickets.question_digest(q) == "58f5c6f88646d37f8fd3cb11cd9c4eebfc037d9f6d8d29eecdc2c45ca050d875"
    a = {"id": "q2", "text": "Ok?", "options": [], "recommended": None, "answer": "Yes",
         "answered_by": "human:me", "via": "cli", "at": "2026-11-15T10:00:00Z"}  # fmt: skip
    assert history._digest("answers", a) == "7119b7e14911468501fcbc9f60a408ec08bfdcf3b6e4b3b7624c414a5324260f"
    # present only when set: a card changes the digest, replaced_by never does
    assert tickets.question_digest({**q, "card": {"kind": "draft"}}) != tickets.question_digest(q)
    d = {"action": "approve", "replaced_by": None}
    assert history._digest("answers", {**a, "decision": d}) != history._digest("answers", a)
    assert history._digest("answers", {**a, "decision": d}) == history._digest(
        "answers", {**a, "decision": {**d, "replaced_by": "q9"}}
    )
    assert history._digest("answers", {**a, "decision": {"replaced_by": "q9"}}) == history._digest(
        "answers", a
    )


# 2. answers on cards are bound under sync
def test_card_answer_is_bound_under_sync(tk):
    root, tid = tk
    history.enable_sync(root, adopt=True)
    q = _ask(root, tid, DRAFT)
    review.decide(root, tid, q["id"], "ok", by=ME, via="cli", digest=tickets.question_digest(q))
    shown = history.shown_ticket(root, _raw(root, tid))
    got = shown["questions"][0]
    assert got["answered_by"] == ME and got["decision"]["action"] == "approve"
    assert got["answer"] == "Build it"

    def plant(d):  # rewrite what was decided: no longer the answer core recorded
        d["questions"][0]["decision"]["action"] = "dont"

    t = _raw(root, tid)
    plant(t)
    tickets.ticket_path(root, tid).write_text(json.dumps(t), encoding="utf-8")
    assert history.shown_ticket(root, _raw(root, tid))["questions"][0]["answered_by"] == history.SYNC_BY


# 3. a changed answer appends, never overwrites
def test_change_appends_entry_and_marks_old(tk):
    root, tid = tk
    q = _ask(root, tid, CHOICE, options=["A", "B", "C"])
    first = review.decide(root, tid, q["id"], "ok", "B", by=ME, via="phone")
    assert first["answer"] == "Use B" and first["decision"]["picked"] == "B"
    new = review.change(
        root, tid, q["id"], "talk", "C", {"changes": ["Put the questions on top."]}, by=ME, via="dashboard"
    )
    t = tickets.load(root, tid)
    old, cur = t["questions"][0], t["questions"][1]
    assert cur["id"] == new["id"] == "q2"
    assert cur["decision"]["replaces"] == "q1" and old["decision"]["replaced_by"] == "q2"
    assert old["answer"] == "Use B" and old["decision"]["action"] == "use"  # nothing overwritten
    assert cur["card"] == old["card"] and cur["shown"] == old["shown"]
    assert cur["answer"] == "Use C with 1 change: Put the questions on top."
    assert t["history"][-1]["text"] == "Answered q2: " + cur["answer"]
    with pytest.raises(Refused):  # the first answer is already replaced
        review.change(root, tid, q["id"], "no", by=ME, via="cli")


def test_answered_twice_and_agents_are_refused(tk):
    root, tid = tk
    q = _ask(root, tid, DRAFT)
    with pytest.raises(Refused):
        review.decide(root, tid, q["id"], "ok", by="human:x", via="Not A Word")
    with pytest.raises(Refused):
        review.decide(root, tid, q["id"], "talk", by=ME, via="cli")  # words alone never approve, no text
    review.decide(root, tid, q["id"], "no", by=ME, via="cli")
    assert tickets.load(root, tid)["questions"][0]["answer"] == "Don't do"
    with pytest.raises(Refused):
        review.decide(root, tid, q["id"], "ok", by=ME, via="cli")


def test_stale_digest_is_refused(tk):
    root, tid = tk
    q = _ask(root, tid, DRAFT)
    with pytest.raises(Refused):
        review.decide(root, tid, q["id"], "ok", by=ME, via="cli", digest="0" * 64)
    assert tickets.load(root, tid)["questions"][0]["answer"] is None


# 4. check cards
def _in_review(root, tid):
    tickets.check_add(root, tid, "Write it", "agent:claude")
    tickets.set_status(root, tid, "review", "agent:claude")


def test_check_approve_makes_ticket_done(tk):
    root, tid = tk
    _in_review(root, tid)
    (item,) = [c for c in review.stack(root) if c["kind"] == "check"]
    assert item["id"] == f"core:review:{tid}"
    e = review.decide(root, tid, "review", "ok", by=ME, via="dashboard", digest=item["digest"])
    t = tickets.load(root, tid)
    assert t["status"] == "done" and "verdicts" not in t
    assert (
        e["card"]["kind"] == "check" and e["decision"]["action"] == "approve" and e["answer"] == "Looks good"
    )
    assert t["questions"][-1]["answered_by"] == ME


def test_check_verdict_needs_a_person(tk):
    root, tid = tk
    _in_review(root, tid)
    with pytest.raises(Refused):
        review.decide(root, tid, "review", "ok", by="agent:x", via="cli")
    assert tickets.load(root, tid)["status"] == "review"
    review.decide(root, tid, "review", "ok", by=ME, via="cli")
    assert tickets.load(root, tid)["status"] == "done"


def test_check_send_back_asks_for_changes(tk):
    root, tid = tk
    _in_review(root, tid)
    with pytest.raises(Refused):
        review.decide(root, tid, "review", "no", by=ME, via="cli")  # a note is needed
    note = {"changes": ["Shorter."]}
    e = review.decide(root, tid, "review", "no", note=note, by=ME, via="cli")
    t = tickets.load(root, tid)
    assert t["status"] != "review" and t["status"] != "done"
    assert any(c.get("origin") == "change_request" and c["text"] == "Shorter." for c in t["checklist"])
    assert e["decision"]["action"] == "send_back" and e["answer"] == "Send back for changes: Shorter."


def test_check_with_old_digest_is_refused(tk):
    root, tid = tk
    _in_review(root, tid)
    with pytest.raises(Refused):
        review.decide(root, tid, "review", "ok", by=ME, via="cli", digest="f" * 64)
    assert tickets.load(root, tid)["status"] == "review"


# 5. reviewed copies
def test_copy_is_content_addressed_and_detects_change(tk):
    root, tid = tk
    (root / "shot.png").write_bytes(b"png-bytes")
    (root / "page.html").write_text("<p>hi</p>")
    a = review.copy_reviewed(root, tid, ["shot.png", "page.html"])
    b = review.copy_reviewed(root, tid, ["page.html", "shot.png"])
    assert a == b and a["copy"].startswith("reviewed/") and set(a["files"]) == {"shot.png", "page.html"}
    folder = root / ".orch" / "tickets" / tid / a["copy"]
    assert (folder / "shot.png").read_bytes() == b"png-bytes"
    assert review.changed_files(root, tid, a) == []
    (folder / "shot.png").write_bytes(b"evil")
    assert review.changed_files(root, tid, a) == ["shot.png"]
    (root / "shot.png").write_bytes(b"other")  # other bytes: another folder
    assert review.copy_reviewed(root, tid, ["shot.png"])["copy"] != a["copy"]
    assert review.changed_files(root, tid, {**a, "files": {"x.png": "0" * 64}}) == ["x.png"]


def test_copy_refuses_links_oversize_and_unknown_types(tk, monkeypatch):
    root, tid = tk
    (root / "a.png").write_bytes(b"x")
    (root / "run.exe").write_bytes(b"x")
    (root / "link.png").symlink_to(root / "a.png")
    for bad in (
        "run.exe",
        "link.png",
        "missing.png",
        "../a.png",
        ".orch/state.json",
        "https://x.example/a.png",
    ):
        with pytest.raises(Refused):
            review.copy_reviewed(root, tid, [bad])
    monkeypatch.setattr(review, "MAX_FILE", 4)
    (root / "big.png").write_bytes(b"123456")
    with pytest.raises(Refused, match="MB"):
        review.copy_reviewed(root, tid, ["big.png"])
    monkeypatch.setattr(review, "MAX_FILE", 100)
    monkeypatch.setattr(review, "MAX_TOTAL", 4)
    (root / "b.png").write_bytes(b"yyyy")
    with pytest.raises(Refused):
        review.copy_reviewed(root, tid, ["a.png", "b.png"])


def test_validate_card_and_prepare_rewrites_refs(tk):
    root, tid = tk
    (root / "d.html").write_text("<p>d</p>")
    card, shown = review.prepare_card(
        root, tid, {"kind": "draft", "title": "T", "then": "x", "preview": {"type": "page", "src": "d.html"}}
    )
    assert card["preview"]["src"] == shown["copy"] + "d.html" and review.changed_files(root, tid, shown) == []
    for bad in (
        {"kind": "nope", "title": "T", "then": "x"},
        {"title": "T", "then": "x"},
        {"kind": "draft", "title": "T"},
        {"kind": "draft", "title": "T", "then": "x", "open": "javascript:alert(1)"},
        {"kind": "draft", "title": "T", "then": "x", "preview": {"type": "video", "src": "a.mp4"}},
        {
            "kind": "draft",
            "title": "T",
            "then": "x",
            "preview": {"type": "page", "src": "http://evil/x.html"},
        },
        {
            "kind": "draft",
            "title": "T",
            "then": "x",
            "preview": {"type": "img", "src": "data:image/png;base64,AA"},
        },
        {"kind": "choice", "title": "T", "then": "x"},
        {"kind": "draft", "title": "T" * 300, "then": "x"},
        {"kind": "draft", "title": "T", "then": "x", "preview": {"type": "doc", "paras": ["p"] * 60}},
    ):
        with pytest.raises(Refused):
            review.validate_card(bad)


# 6. the stack, summaries, the helper block
def test_stack_lists_cards_checks_and_plain_questions(tk):
    root, tid = tk
    other = tickets.create(root, "Other", ME)["id"]
    _ask(root, tid, CHOICE, options=["A", "B", "C"])
    tickets.ask(root, other, "Send it now?", ["Yes", "No"], "Yes", "agent:claude")
    t3 = tickets.create(root, "Survey", ME)["id"]
    _in_review(root, t3)
    items = review.stack(root)
    ids = {i["id"] for i in items}
    assert ids == {f"core:q:{tid}:q1", f"core:q:{other}:q1", f"core:review:{t3}"}
    by_id = {i["id"]: i for i in items}
    card_item = by_id[f"core:q:{tid}:q1"]
    assert card_item["kind"] == "choice" and card_item["card"]["preview"]["options"][2]["id"] == "C"
    assert card_item["digest"] == tickets.question_digest(tickets.load(root, tid)["questions"][0])
    plain = by_id[f"core:q:{other}:q1"]
    assert (
        plain["options"] == ["Yes", "No"] and plain["card"]["kind"] == "choice" and len(plain["digest"]) == 64
    )
    assert by_id[f"core:review:{t3}"]["kind"] == "check"
    # a plain question answered the old way keeps its plain answer text
    q = review.decide(root, other, "q1", "ok", "Yes", by=ME, via="cli", digest=plain["digest"])
    assert q["answer"] == "Yes" and q["decision"]["picked"] == "Yes"
    assert {i["id"] for i in review.stack(root)} == ids - {f"core:q:{other}:q1"}


def test_stack_groups_by_ticket_then_task_and_says_about(tk, monkeypatch):
    root, tid = tk  # "Home layout"
    other = tickets.create(root, "Round two", ME)["id"]
    stamps = iter(f"2026-11-15T10:{i:02d}:00Z" for i in range(60))
    monkeypatch.setattr(tickets, "now", lambda: next(stamps))
    ids = {}

    def ask(ticket, text, check=None):
        _, q = tickets.ask(root, ticket, text, ["Yes", "No"], "Yes", "agent:claude", check=check)
        ids[text] = f"core:q:{ticket}:{q['id']}"

    _, c1 = tickets.check_add(root, tid, "Pick the " + "very long title " * 12, "agent:claude")
    _, c2 = tickets.check_add(root, tid, "Header\ncolour", "agent:claude")
    _, d1 = tickets.check_add(root, other, "Footer", "agent:claude")
    ask(tid, "plain-1")  # oldest, no task
    ask(other, "other-footer", d1["id"])  # the other ticket's first card is newer than plain-1
    ask(tid, "t2-first", c2["id"])
    ask(tid, "t1-late", c1["id"])
    ask(tid, "plain-2")
    ask(other, "other-plain")
    items = review.stack(root)
    assert [i["id"] for i in items] == [
        ids[k] for k in ("t1-late", "t2-first", "plain-1", "plain-2", "other-footer", "other-plain")
    ]
    by_id = {i["id"]: i for i in items}
    long = by_id[ids["t1-late"]]["about"]
    assert len(long) <= review.ABOUT_MAX and long.endswith("\u2026") and long.startswith("Pick the very long")
    assert by_id[ids["t2-first"]]["about"] == "Header colour"  # one line
    assert "about" not in by_id[ids["plain-1"]] and "about" not in by_id[ids["other-plain"]]
    assert by_id[ids["other-footer"]]["about"] == "Footer"
    # about is not on the wire card and does not change the digest
    assert "about" not in by_id[ids["t2-first"]]["card"]


def test_summary_and_applies_now_block(tk):
    root, tid = tk
    assert (
        review.summary(
            {
                "action": "use_with_changes",
                "picked": "C",
                "changes": ["Questions on top.", "Month in the heading."],
            }
        )
        == "Use C with 2 changes: Questions on top; Month in the heading."
    )
    assert review.summary({"action": "approve"}, {"ok_label": "Build it"}) == "Build it"
    assert review.summary({"action": "none_of_these"}) == "None of these"
    q = _ask(root, tid, CHOICE, text="Home: which layout?", options=["A", "B", "C"])
    review.decide(root, tid, q["id"], "ok", "B", by=ME, via="phone")
    review.change(
        root, tid, q["id"], "talk", "C",
        {"changes": ["Put the questions on top of the list.", "Show the month in the heading."]},
        by=ME, via="dashboard",
    )  # fmt: skip
    block = review.applies_now_block(tickets.load(root, tid), root)
    key = tickets.load(root, tid)["key"]
    assert block.startswith(f"What applies now ({key})\nUse option C (Questions first) WITH 2 CHANGES.")
    assert "  1. Put the questions on top of the list.\n  2. Show the month in the heading." in block
    assert "Not allowed by this answer: publishing, sending, anything outside " + key in block
    assert review.applies_now_block(tickets.load(root, tickets.create(root, "Empty", ME)["id"])) == ""


def test_card_question_keeps_agent_blocking(tk):
    root, tid = tk
    _ask(root, tid, DRAFT)
    q = tickets.load(root, tid)["questions"][0]
    assert q.get("kind") is None and tickets._open_questions(tickets.load(root, tid)) == ["q1"]
    assert q["card"]["kind"] == "draft" and q["shown"]["digest"]
