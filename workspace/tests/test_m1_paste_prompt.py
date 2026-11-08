import pytest

from orch import runs


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("note,checklist,wants_plan", [
    ("Details " * 80, [], True),
    ("Short note", [], False),
    ("Details " * 80, [{"id": "c1", "text": "Do it", "done": False}], False),
    ("Details " * 80, [{"id": "c1", "text": "Done", "done": True}], False),
])
def test_long_description_without_tasks_gets_split_instruction(resume, note, checklist, wants_plan):
    ticket = {"id": "t_paste001", "title": "Pasted", "note": note, "checklist": checklist}
    prompt = runs.resume_prompt(ticket, [], None, "agent") if resume else runs.fresh_prompt(ticket, [])
    instruction = "Read the description, write a plan, split it into tasks with orch check add, then start"
    assert (instruction in prompt) is wants_plan
