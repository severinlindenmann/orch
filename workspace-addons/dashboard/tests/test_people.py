"""The "You: <name>" person switch: a name only, per workspace, used as the actor of dashboard actions."""

import pytest

from orch_dashboard import actions, data, people


def test_no_person_chosen_keeps_the_computer_user(tmp_path):
    assert people.load(tmp_path) == {"me": None, "people": []}
    assert actions.actor(tmp_path) == actions.actor()


def test_add_person_chooses_them_and_becomes_the_actor(tmp_path):
    out = actions.run_op(tmp_path, "/x/orch", "person.add", {"name": "Anna"}, mint=lambda *a: "p")
    assert out[0] == 200 and out[2]["people"] == {"me": "Anna", "people": ["Anna"]}
    assert actions.actor(tmp_path) == "human:Anna"
    assert actions.build_argv("log", {"ticket": "t_abc123", "text": "x"}, tmp_path)[-3:-1] == [
        "--by",
        "human:Anna",
    ] or "human:Anna" in actions.build_argv("log", {"ticket": "t_abc123", "text": "x"}, tmp_path)
    actions.run_op(tmp_path, "/x/orch", "person.add", {"name": "Ben"}, mint=lambda *a: "p")
    actions.run_op(tmp_path, "/x/orch", "person.set", {"name": "Anna"}, mint=lambda *a: "p")
    assert people.load(tmp_path) == {"me": "Anna", "people": ["Anna", "Ben"]}
    other = tmp_path / "other"
    other.mkdir()
    assert people.current(other) is None  # per workspace


def test_set_only_picks_a_known_person_and_names_are_clean(tmp_path):
    with pytest.raises(actions.BadRequest):
        actions.run_op(tmp_path, "/x/orch", "person.set", {"name": "Nobody"}, mint=lambda *a: "p")
    with pytest.raises(actions.BadRequest):
        actions.run_op(tmp_path, "/x/orch", "person.add", {"name": "   "}, mint=lambda *a: "p")
    out = actions.run_op(tmp_path, "/x/orch", "person.add", {"name": "Eve; rm -rf /\n"}, mint=lambda *a: "p")
    assert out[2]["people"]["me"] == "Eve rm -rf"


def test_watch_only_page_cannot_switch_person(tmp_path):
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(tmp_path, "/x/orch", "person.add", {"name": "Anna"}, mint=None)
    assert people.current(tmp_path) is None


def test_state_carries_people_and_who(tmp_path, monkeypatch):
    people.choose(tmp_path, "Anna", add=True)
    assert data._me(tmp_path) == "human:Anna"
