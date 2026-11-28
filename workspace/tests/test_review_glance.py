"""Glance formats of a card (ORCH-329): a Check card leads with one sentence, a bar and chips; the long text
sits in details; the new doc fields are checked and reach the phone as plain text."""

import pytest

from orch import review
from orch.tickets import Refused


def _ticket(summary="Works on Mac. Linux only tested with a stand-in. More words follow."):
    return {
        "id": "t_1",
        "title": "Services",
        "summary": summary,
        "checklist": [
            {"text": "Write it", "done": True, "evidence": [{"type": "command", "ref": "pytest", "exit": 0}]},
            {"text": "Ship it", "done": False},
            {"text": "Skip it", "wont_do": True},
        ],
    }


def test_check_card_leads_with_a_sentence_a_bar_and_chips():
    pv = review.check_card(_ticket())["preview"]
    assert pv["headline"] == "Works on Mac."
    assert pv["progress"] == {"done": 1, "total": 2}
    assert {"text": "1 check ran fine", "tone": "ok"} in pv["chips"]
    assert pv["steps"][0] == "Done: Write it — Ran: pytest"
    assert (
        pv["details"][0] == "Linux only tested with a stand-in. More words follow."
    )  # the rest, not the headline again


def test_check_card_says_each_step_and_the_summary_once():
    """ORCH-1686: no "Done:" when the bar says all are done, the evidence on the step's line, no repeat."""
    t = {
        "id": "t_3",
        "title": "Survey",
        "summary": "Most customers like our staff.",
        "checklist": [
            {
                "text": "Write the one-page summary",
                "done": True,
                "evidence": [{"type": "note", "ref": "x", "summary": "A one-page summary."}],
            }
        ],
    }
    pv = review.check_card(t)["preview"]
    assert pv["headline"] == "Most customers like our staff."
    assert pv["steps"] == ["Write the one-page summary — A one-page summary. · x"]
    assert "details" not in pv


def test_check_card_without_text_has_no_preview():
    assert "preview" not in review.check_card({"id": "t_2", "title": "x", "checklist": []})


def test_glance_fields_are_checked():
    ok = {
        "type": "doc",
        "headline": "Faster",
        "progress": {"done": 2, "total": 3},
        "chips": [{"text": "ok", "tone": "ok"}],
        "flow": ["a", "b"],
        "chart": {"unit": "s", "bars": [{"label": "before", "value": 4.2}, {"label": "after", "value": 1.8}]},
        "diff": [{"op": "+", "text": "Looks good"}, {"op": "-", "text": "Approve"}],
        "details": ["long text"],
    }
    review._walk_preview(dict(ok), "preview", [])
    bad = [
        {"progress": {"done": 4, "total": 3}},
        {"chips": [{"text": "x", "tone": "pink"}]},
        {"flow": list("abcdefg")},
        {"chart": {"bars": [{"label": "a", "value": "big"}]}},
        {"diff": [{"op": "*", "text": "x"}]},
    ]
    for extra in bad:
        with pytest.raises(Refused):
            review._walk_preview({"type": "doc", **extra}, "preview", [])


def test_phone_gets_the_glance_as_plain_text():
    p = review._plain_doc(
        {
            "type": "doc",
            "headline": "Faster",
            "progress": {"done": 2, "total": 3},
            "chips": [{"text": "ok", "tone": "ok"}],
            "flow": ["a", "b"],
            "chart": {"unit": "s", "bars": [{"label": "now", "value": 1.8}]},
            "details": ["long"],
        }
    )
    assert set(q for q in p) <= {"type", "heading", "paras", "steps"}
    assert p["paras"][:4] == ["Faster", "2 of 3 steps done", "ok", "a → b"] and "now: 1.8s" in p["steps"]


def test_ask_file_json_makes_a_glance_card(tmp_path):
    from orch import cli_review

    (tmp_path / "card.json").write_text('{"headline": "Done.", "chips": [{"text": "ok", "tone": "ok"}]}')
    pv = cli_review._file_preview(tmp_path, "card.json", "file")
    assert pv == {"type": "doc", "headline": "Done.", "chips": [{"text": "ok", "tone": "ok"}]}
    (tmp_path / "bad.json").write_text("[1]")
    with pytest.raises(Refused):
        cli_review._file_preview(tmp_path, "bad.json", "file")


def test_check_card_keeps_more_than_six_result_files():
    # ORCH-421: eight pictures on one step were cut to six without a word; the card now gets them all
    # (the page shows five tiles and a "+N more" tile)
    head = ".orch/tickets/t_9/evidence/"
    ev = [{"type": "file", "ref": f"{head}photo-{i}.png"} for i in range(8)]
    step = {"id": "c1", "text": "Photos", "done": True, "evidence": ev}
    t = {"id": "t_9", "title": "Shop photos", "checklist": [step]}
    files = review.check_card(t)["files"]
    assert [f["name"] for f in files] == [f"photo-{i}.png" for i in range(8)]


def test_result_card_says_everything_is_done_and_tested():
    """ORCH-2316 (R6 A, owner 25 Nov): every part done with its evidence, no failed check: one plain line."""
    t = _ticket()
    t["checklist"] = t["checklist"][:1]
    card = review.check_card(t)
    assert card["why"] == "Everything you asked for is done and tested."
    assert "open_parts" not in card


def test_result_card_names_the_open_part_as_asked_for_and_got():
    """ORCH-2316 (R6 A): an open part sits on top as You asked for / You got; the rest is done and tested."""
    t = _ticket()
    t["checklist"][1]["evidence"] = [{"type": "note", "ref": "only two widths"}]
    card = review.check_card(t)
    assert card["why"] == "Everything else you asked for is done and tested."
    assert card["open_parts"] == [{"asked": "Ship it", "got": "only two widths"}]
    assert card["blocked"]  # Looks good stays off (ORCH-548)


def test_result_card_keeps_the_plain_line_when_a_check_failed_or_a_step_has_no_evidence():
    t = _ticket()
    failed = [{"type": "command", "ref": "pytest", "exit": 1}]
    t["checklist"] = [{"text": "Write it", "done": True, "evidence": failed}]
    assert review.check_card(t)["why"] == "The helper says this is ready for your check."
    t["checklist"] = [{"text": "Write it", "done": True}]
    assert review.check_card(t)["why"] == "The helper says this is ready for your check."
