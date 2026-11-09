"""Keep the phone's tasks and results about the person's work."""

from pathlib import Path

import pytest

from orch import phone_view, runs, tickets

REVIEW_MESSAGE = (
    "When the ticket reaches Review, orch sends its summary and files to the person by itself: "
    "add no task for that and don't write that it was sent. "
    "Answering a person's message is still your job."
)


def test_fresh_prompt_plain_words(proj, new_ticket):
    tid = new_ticket()
    prompt = runs.fresh_prompt(tickets.load(proj, tid), [])
    assert ("one task per piece of the person's work, in plain words (no ids, paths or commands)") in prompt
    assert (f'orch ticket summary {tid} "<what was done and what is left>" in plain words.') in prompt
    assert REVIEW_MESSAGE.replace("`", "") in prompt
    assert len(prompt) <= 12000


@pytest.mark.parametrize("filename", ["SKILL.md", "AGENTS-block.md"])
def test_skill_and_agents_block_review_message(filename):
    text = (Path(__file__).resolve().parents[1] / "skills" / "orch" / filename).read_text()
    assert REVIEW_MESSAGE in text
    assert 'orch ticket summary <id> "<what was done and what is left>"' in text


@pytest.mark.parametrize("summary", ["", "Result sent to phone."])
@pytest.mark.parametrize("note", ["Please write the page.", "The result is sent to the phone."])
def test_shown_summary_falls_back_to_unchanged_note(summary, note):
    assert phone_view.shown_summary({"summary": summary, "note": note}) == note


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fish page done, checked. Result sent to phone.", "Fish page done, checked."),
        ("Result sent to phone. Fish page done.", "Fish page done."),
        ("Done. The results were delivered back to your phones via the relay. Checked.", "Done. Checked."),
        ("I sent the report to the phone vendor.", "I sent the report to the phone vendor."),
        ("Result sent to phone vendor.", "Result sent to phone vendor."),
        ("Result sent to phone and checked.", "Result sent to phone and checked."),
        ("We checked: result sent to phone.", "We checked: result sent to phone."),
    ],
)
def test_delivery_sentence_only(text, expected):
    assert phone_view._without_delivery(text) == expected


def test_phone_view_hides_delivery_task_and_counts(proj, new_ticket):
    ticket = tickets.load(proj, new_ticket("Fish page"))
    ticket.update(
        status="review",
        summary="Fish page done, checked. Result sent to phone.",
        checklist=[
            {"id": "c1", "text": "Write the page", "done": True},
            {"id": "c2", "text": "Send the result back to the phone via relay", "done": True},
            {"id": "c3", "text": "Check the page", "done": False},
        ],
    )
    view = phone_view.build(proj, ticket, [])
    assert view["checklist"] == [
        {"text": "Write the page", "done": True},
        {"text": "Check the page", "done": False},
    ]
    assert view["total"] == 2
    assert view["done"] == 1
    assert view["summary"] == "Fish page done, checked."
    assert phone_view.result_text(ticket) == "Ready for your review: Fish page\nFish page done, checked."
    assert len(ticket["checklist"]) == 3


def test_delivery_task_must_be_the_whole_task():
    text = "Send the result back to the phone via relay and check the page"
    assert phone_view._without_delivery(text, task=True) == text
