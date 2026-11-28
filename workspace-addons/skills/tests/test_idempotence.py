"""Skills add-on: every turn, remove, restore, delete and new is safe to repeat (a second click, a retry, a helper
that runs the command twice) and leaves the files as the first one did."""

import json

import pytest

from orch_skills import bin as skill_bin
from orch_skills import cli, model, switches


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _offer(ws, **offered):
    d = ws / ".orch/secrets"
    d.mkdir(parents=True, exist_ok=True)
    (d / "shared.json").write_text(json.dumps({"version": 5, "skills": list(offered), "offered": offered}))


def test_turning_a_workspace_skill_off_and_on_twice_changes_once(ws):
    t = "skill:workspace:release-walk"
    assert model.turn(ws, t, on=True)["changed"] is False  # already on: nothing written
    assert not (ws / ".claude/settings.local.json").exists()
    assert model.turn(ws, t, on=False)["changed"] is True
    off = _tree(ws / ".claude")
    assert model.turn(ws, t, on=False)["changed"] is False
    assert _tree(ws / ".claude") == off
    assert model.turn(ws, t, on=True)["changed"] is True
    assert model.turn(ws, t, on=True)["changed"] is False
    assert json.loads((ws / ".claude/settings.local.json").read_text()) == {}


def test_turning_a_linked_skill_on_when_it_never_was_off_writes_no_list(ws):
    assert model.turn(ws, "skill:orch:orch-hello", on=True)["changed"] is False
    assert (ws / ".agents/skills/orch-hello").exists()


def test_removing_a_shared_skill_twice_is_refused_and_keeps_the_list(ws):
    from orch_skills import shared

    _offer(ws, github=2)
    model.act(ws, "remove", "skill:admin:github")
    listed = (ws / ".orch/skills-removed.json").read_bytes()
    assert shared.remove(ws, "github") is False
    with pytest.raises(switches.Refused, match="not possible here"):
        model.act(ws, "remove", "skill:admin:github")
    assert (ws / ".orch/skills-removed.json").read_bytes() == listed


def test_getting_a_removed_skill_back_twice_changes_nothing_the_second_time(ws):
    from orch_skills import shared

    _offer(ws, github=2)
    model.act(ws, "remove", "skill:admin:github")
    assert "comes back" in shared.restore(ws, "github")
    assert shared.restore(ws, "github") == "github was not removed here. Nothing changed."
    assert json.loads((ws / ".orch/skills-removed.json").read_text())["skills"] == {}


def test_the_bin_takes_a_skill_once_and_gives_it_back_once(ws):
    folder = ws / ".agents/skills/release-walk"
    before = _tree(folder)
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    with pytest.raises(switches.Refused):
        model.delete(ws, "skill:workspace:release-walk", "human:Anna")
    assert len(model.build(ws)["bin"]) == 1
    model.restore(ws, row["id"], "human:Anna")
    with pytest.raises(switches.Refused, match="not in the bin"):
        model.restore(ws, row["id"], "human:Anna")
    assert _tree(folder) == before and model.build(ws)["bin"] == []


def test_a_second_new_skill_of_the_same_name_is_refused_and_keeps_the_first(ws):
    first = model.new_skill(ws, "weekly-report", "human:Anna")
    path = ws / ".agents/skills/weekly-report/SKILL.md"
    text = path.read_text()
    assert first
    with pytest.raises(switches.Refused, match="already here"):
        model.new_skill(ws, "weekly-report", "human:Bo")
    assert path.read_text() == text


def test_a_deleted_skills_name_can_be_made_new_again_and_restore_never_replaces_it(ws):
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    model.new_skill(ws, "release-walk", "human:Anna")
    mine = (ws / ".agents/skills/release-walk/SKILL.md").read_text()
    with pytest.raises(switches.Refused):
        model.restore(ws, row["id"], "human:Anna")
    assert (ws / ".agents/skills/release-walk/SKILL.md").read_text() == mine
    assert [r["id"] for r in model.build(ws)["bin"]] == [row["id"]]
    assert skill_bin.rows(ws)


def test_the_cli_repeats_turn_off_and_on_with_the_same_exit_code(ws, capsys):
    for verb, changed in (("off", [True, False]), ("on", [True, False])):
        for want in changed:
            assert (
                cli.main(["--dir", str(ws), verb, "--by", "human:Anna", "--json", "--", "skill:workspace:release-walk"])
                == 0
            )
            assert json.loads(capsys.readouterr().out)["changed"] is want
