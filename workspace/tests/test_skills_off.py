"""Turned-off skills (.orch/skills-off.json, the Skills page): orch does not link them, the files stay."""

import json
import sys

import pytest

from orch import adapters, skills, worktrees


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


def _skill(tmp_path, name):
    src = tmp_path / "src" / name
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text(f"---\nname: {name}\ndescription: The {name} skill for tests.\n---\n")
    return src


def _off(proj, names, schema="orch.skills-off/1"):
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "skills-off.json").write_text(json.dumps({"schema": schema, "skills": names}))


def _seen(proj, where, name):
    return (proj / where / name).is_symlink() or (proj / where / name / "SKILL.md").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
def test_an_off_skill_is_not_linked_and_comes_back(proj, tmp_path):
    for n in ("orch", "orch-hello"):
        skills.install_skill(proj, n, _skill(tmp_path, n))
    skills.apply_agent_files(proj)
    assert _seen(proj, ".agents/skills", "orch-hello") and _seen(proj, ".claude/skills", "orch-hello")

    _off(proj, ["orch-hello", "orch"])
    skills.apply_agent_files(proj)
    assert not _seen(proj, ".agents/skills", "orch-hello") and not _seen(proj, ".claude/skills", "orch-hello")
    assert (proj / ".orch/harness/skills/orch-hello/SKILL.md").is_file()  # the files stay
    assert _seen(proj, ".agents/skills", "orch")  # the core skill is always on
    assert skills.off_names(proj) == {"orch-hello"}

    _off(proj, [])
    skills.apply_agent_files(proj)
    assert _seen(proj, ".agents/skills", "orch-hello") and _seen(proj, ".claude/skills", "orch-hello")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
@pytest.mark.parametrize("prepared_before", [False, True])
def test_a_ticket_copy_honors_the_off_skills(proj, tmp_path, prepared_before):
    for n in ("orch", "orch-hello"):
        skills.install_skill(proj, n, _skill(tmp_path, n))
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / ".agents/skills/mine").mkdir(parents=True)  # the person's own skill in the copy
    (copy / ".agents/skills/mine/SKILL.md").write_text("mine")
    if prepared_before:  # an older copy, prepared while the skill was on
        skills.apply_agent_files(proj)
        assert worktrees._prepare_files(proj, {"path": str(copy)}) == []
        assert (copy / ".agents/skills/orch-hello/SKILL.md").is_file()

    _off(proj, ["orch-hello"])
    skills.apply_agent_files(proj)
    assert worktrees._prepare_files(proj, {"path": str(copy)}) == []
    assert not (proj / ".agents/skills/orch-hello/SKILL.md").exists()
    for where in (".agents/skills", ".claude/skills"):
        assert not _seen(copy, where, "orch-hello")
    assert _seen(copy, ".agents/skills", "orch")  # the core skill stays on
    assert (copy / ".agents/skills/mine/SKILL.md").read_text() == "mine"

    _off(proj, [])
    skills.apply_agent_files(proj)
    assert worktrees._prepare_files(proj, {"path": str(copy)}) == []
    assert (copy / ".agents/skills/orch-hello/SKILL.md").is_file()
    assert (copy / ".claude/skills/orch-hello/SKILL.md").is_file()
    assert (copy / ".agents/skills/mine/SKILL.md").read_text() == "mine"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
def test_a_team_link_of_the_same_name_stays(proj, tmp_path):
    skills.install_skill(proj, "orch-hello", _skill(tmp_path, "orch-hello"))
    own = tmp_path / "team" / "orch-hello"
    own.mkdir(parents=True)
    (proj / ".claude/skills").mkdir(parents=True)
    (proj / ".claude/skills/orch-hello").symlink_to(own)
    _off(proj, ["orch-hello"])
    skills.apply_agent_files(proj)
    assert (proj / ".claude/skills/orch-hello").is_symlink()  # not orch's link: left alone


@pytest.mark.parametrize(
    "text",
    ["{not json", json.dumps({"schema": "other/1", "skills": ["orch-hello"]}), json.dumps({"skills": "x"})],
)
def test_a_damaged_off_file_hides_nothing(proj, text):
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "skills-off.json").write_text(text)
    assert skills.off_names(proj) == frozenset()


def test_off_names_skip_unsafe_names(proj):
    _off(proj, ["../etc", "ok-name", 3, ""])
    assert skills.off_names(proj) == {"ok-name"}


def test_a_copy_that_holds_an_addon_file_stays(proj, tmp_path):
    from orch import harness

    skills.install_skill(proj, "orch-relay", _skill(tmp_path, "orch-relay"))
    copy = proj / ".agents/skills/orch-relay"
    copy.mkdir(parents=True)
    (copy / harness.COPY_MARK).write_text("")
    (copy / "workspaces.json").write_text("{}")
    _off(proj, ["orch-relay"])
    skills._unlink_ours(proj, ".agents/skills", "orch-relay", proj / ".orch/harness/skills/orch-relay")
    assert (copy / "workspaces.json").read_text() == "{}"
