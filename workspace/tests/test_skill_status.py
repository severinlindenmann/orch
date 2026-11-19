"""Skill format step 2 (ORCH-533): status and platforms decide what orch offers helpers at install."""

import pytest

from orch import adapters, harness, skills, skillstatus


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


def _src(tmp_path, name, meta="", desc="Does a thing. Use when x."):
    d = tmp_path / "src" / name
    d.mkdir(parents=True)
    head = f"---\nname: {name}\ndescription: {desc}\n"
    if meta:
        head += "metadata:\n" + "".join(f"  {ln}\n" for ln in meta.strip().splitlines())
    (d / "SKILL.md").write_text(head + "---\n# body\n", encoding="utf-8")
    return d


def _install(proj, tmp_path, name, meta="", desc="Does a thing. Use when x."):
    skills.install_skill(proj, name, _src(tmp_path, name, meta, desc))
    skills.set_block(proj, name, f"## {name}\nRead the skill.")
    skills.apply_agent_files(proj)


# ---------------------------------------------------------------- the reader


def test_header_reads_metadata_strings():
    h = skillstatus._parse_header(
        '---\nname: a\ndescription: "x"\nmetadata:\n  status: "retired"\n'
        "  platforms: macos, windows  # comment\n  nested:\n    deep: no\nlicense: MIT\n---\nbody"
    )
    assert h["name"] == "a" and h["description"] == "x" and h["license"] == "MIT"
    assert h["metadata"]["status"] == "retired"
    assert h["metadata"]["platforms"] == "macos, windows"
    assert skillstatus.platforms(h["metadata"]) == {"macos", "windows"}


def test_no_header_is_empty():
    assert skillstatus._parse_header("# just text") == {"metadata": {}}


# ---------------------------------------------------------------- retired


def test_retired_skill_is_not_offered_and_files_stay(proj, tmp_path):
    _install(proj, tmp_path, "old-tool")
    assert (proj / ".claude/skills/old-tool/SKILL.md").is_file()
    assert "## old-tool" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")

    _install(proj, tmp_path / "v2", "old-tool", meta="status: retired")
    for where in (".agents/skills", ".claude/skills"):
        assert not (proj / where / "old-tool").exists()
        assert not (proj / where / "old-tool").is_symlink()
    assert (proj / ".orch/harness/skills/old-tool/SKILL.md").is_file()  # the file stays
    assert "## old-tool" not in harness.combined(proj)
    skills.set_block(proj, "orch", "## orch\nRead it.")
    assert "## orch" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    assert "## old-tool" not in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    assert skills.hidden_skills(proj) == {"old-tool": "retired"}


def test_retired_shared_skill_is_not_linked_for_other_agents(proj, tmp_path):
    sh = proj / ".agents/skills/team-tool"
    sh.mkdir(parents=True)
    (sh / ".orch-shared").write_text("", encoding="utf-8")
    (sh / "SKILL.md").write_text("---\nname: team-tool\ndescription: x\n---\n", encoding="utf-8")
    skills.apply_agent_files(proj)
    assert (proj / ".claude/skills/team-tool").is_symlink()

    (sh / "SKILL.md").write_text(
        "---\nname: team-tool\ndescription: x\nmetadata:\n  status: retired\n---\n", encoding="utf-8"
    )
    skills.apply_agent_files(proj)
    assert not (proj / ".claude/skills/team-tool").exists()
    assert (sh / "SKILL.md").is_file()  # the relay's files are not touched


def test_hidden_shared_skill_never_removes_the_persons_folder(proj, tmp_path):
    sh = proj / ".agents/skills/team-tool"
    sh.mkdir(parents=True)
    (sh / ".orch-shared").write_text("", encoding="utf-8")
    (sh / "SKILL.md").write_text(
        "---\nname: team-tool\ndescription: x\nmetadata:\n  status: retired\n---\n", encoding="utf-8"
    )
    mine = proj / ".claude/skills/team-tool"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine", encoding="utf-8")
    skills.apply_agent_files(proj)
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "mine"


# ---------------------------------------------------------------- deprecated


def test_deprecated_skill_points_to_its_replacement(proj, tmp_path):
    _install(proj, tmp_path, "status-page", meta="status: deprecated\nreplaced-by: orch-dashboard")
    text = (proj / ".claude/skills/status-page/SKILL.md").read_text(encoding="utf-8")
    h = skillstatus._parse_header(text)
    assert h["description"] == "Old skill, use orch-dashboard instead. Does a thing. Use when x."
    assert "## status-page" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")


def test_deprecated_note_keeps_quotes_and_is_idempotent():
    text = (
        '---\nname: a\ndescription: "Does x."\nmetadata:\n  status: deprecated\n  replaced-by: b\n---\nbody\n'
    )
    once = skillstatus.mark_deprecated(text)
    assert 'description: "Old skill, use b instead. Does x."' in once
    assert skillstatus.mark_deprecated(once) == once
    assert once.endswith("---\nbody\n")


def test_deprecated_without_replacement_and_active_unchanged():
    dep = "---\nname: a\ndescription: Does x.\nmetadata:\n  status: deprecated\n---\n"
    assert "description: Old skill, no longer kept up. Does x." in skillstatus.mark_deprecated(dep)
    active = "---\nname: a\ndescription: Does x.\nmetadata:\n  status: active\n---\n"
    assert skillstatus.mark_deprecated(active) == active


def test_deprecated_replacement_cannot_break_the_header():
    text = (
        '---\nname: a\ndescription: "x"\nmetadata:\n  status: deprecated\n  replaced-by: \'b"\\n: c\'\n---\n'
    )
    out = skillstatus.mark_deprecated(text)
    assert skillstatus._parse_header(out)["description"].startswith("Old skill, use bn c instead.")


# ---------------------------------------------------------------- platforms


def test_wrong_platform_skill_is_not_linked(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(skillstatus, "this_platform", lambda: "linux")
    _install(proj, tmp_path, "win-tool", meta='platforms: "macos, windows"')
    _install(proj, tmp_path / "b", "any-tool", meta='platforms: "linux, macos"')
    _install(proj, tmp_path / "c", "all-tool")
    assert not (proj / ".claude/skills/win-tool").exists()
    assert not (proj / ".agents/skills/win-tool").exists()
    assert (proj / ".orch/harness/skills/win-tool/SKILL.md").is_file()
    assert (proj / ".claude/skills/any-tool/SKILL.md").is_file()
    assert (proj / ".claude/skills/all-tool/SKILL.md").is_file()
    assert skills.hidden_skills(proj) == {"win-tool": "not for linux"}

    monkeypatch.setattr(skillstatus, "this_platform", lambda: "windows")
    skills.apply_agent_files(proj)
    assert (proj / ".claude/skills/win-tool/SKILL.md").is_file()
    assert not (proj / ".claude/skills/any-tool").exists()


def test_platform_words_and_aliases(tmp_path):
    d = _src(tmp_path, "t", meta="platforms: Mac, WIN")
    assert skillstatus.hidden_reason(d, "macos") is None
    assert skillstatus.hidden_reason(d, "windows") is None
    assert skillstatus.hidden_reason(d, "linux") == "not for linux"
    unknown = _src(tmp_path / "u", "t", meta="platforms: beos")
    assert skillstatus.hidden_reason(unknown, "linux") is None  # no known word: every system


def test_copy_of_project_skips_hidden_skill(proj, tmp_path):
    _install(proj, tmp_path, "old-tool", meta="status: retired")
    _install(proj, tmp_path / "b", "new-tool")
    work = tmp_path / "work"
    work.mkdir()
    skills.apply_copy_files(proj, work)
    assert not (work / ".claude/skills/old-tool").exists()
    assert (work / ".claude/skills/new-tool/SKILL.md").is_file()
    assert harness._same(work / ".claude/skills/new-tool", proj / ".orch/harness/skills/new-tool")
