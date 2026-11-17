"""state.review: the cards that wait and the decisions made, from `orch review list [--answered] --json`."""

import sys

from orch_dashboard.data import load_review, load_state

CARD = {
    "id": "core:q:t_abcdef:q1",
    "ticket": "t_abcdef",
    "key": "q1",
    "digest": "a" * 64,
    "card": {"kind": "draft"},
}
DONE = {"id": "core:q:t_abcdef:q2", "ticket": "t_abcdef", "decision": {"action": "approve"}}


ACC = {"ticket": "t_abcdef", "key": "ORCH-7", "title": "Fix", "why": "merged.", "sent_back": False}


def fake(tmp_path, cards, answered, fail=False, accepted=None):
    script = tmp_path / "orch"
    script.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
if a[:2] == ["review", "list"] and {fail!r}:
    sys.exit(2)
if a == ["review", "list", "--json"]:
    print(json.dumps({cards!r}))
elif a == ["review", "list", "--answered", "--json"]:
    print(json.dumps({answered!r}))
elif a == ["review", "accepted", "--json"] and {accepted!r} is not None:
    print(json.dumps({{"since": "today", "accepted": {accepted!r}}}))
else:
    sys.exit(2)
""")
    script.chmod(0o755)
    return str(script)


def test_review_cards_and_answered_come_from_orch(ws, tmp_path):
    orch = fake(tmp_path, {"workspace": "w", "cards": [CARD]}, [DONE, "junk"])
    assert load_review(ws, orch) == {"cards": [CARD], "answered": [DONE], "accepted": []}
    assert load_state(ws, orch_bin=orch, with_settings=True)["review"] == {
        "cards": [CARD],
        "answered": [DONE],
        "accepted": [],
    }


def test_review_is_empty_when_orch_cannot_say(ws, tmp_path):
    orch = fake(tmp_path, [], [], fail=True)
    assert load_review(ws, orch) == {"cards": [], "answered": [], "accepted": []}
    assert load_review(ws, None) == {"cards": [], "answered": [], "accepted": []}


def test_a_snapshot_carries_no_review(ws, tmp_path):
    orch = fake(tmp_path, [CARD], [DONE])
    assert load_state(ws, orch_bin=orch)["review"] == {"cards": [], "answered": [], "accepted": []}


def test_review_carries_what_the_reviewer_accepted(ws, tmp_path):
    orch = fake(tmp_path, {"workspace": "w", "cards": []}, [], accepted=[ACC, "junk"])
    assert load_review(ws, orch)["accepted"] == [ACC]
