"""The core skill = SKILL.md + topics/*.md; with no topic files it is exactly SKILL.md."""

import shutil

import pytest

from orch import skills


def _copy_without_topics(tmp_path):
    """The packaged core skill, minus any topic files lanes added meanwhile."""
    own = skills.packaged_skills_dir() / "orch"
    src = tmp_path / "skill"
    shutil.copytree(own, src, ignore=shutil.ignore_patterns("topics"))
    (src / "topics").mkdir()
    return own, src


def test_without_topic_files_the_text_is_SKILL_md(tmp_path):
    own, src = _copy_without_topics(tmp_path)
    assert skills.skill_text(src).encode("utf-8") == (own / "SKILL.md").read_bytes()


def test_install_without_topics_is_SKILL_md_and_keeps_extra_files(tmp_path, proj):
    own, src = _copy_without_topics(tmp_path)
    skills.install_skill(proj, "orch", src)
    dest = skills.harness_skill(proj, "orch")
    assert (dest / "SKILL.md").read_bytes() == (own / "SKILL.md").read_bytes()
    assert not (dest / "topics").exists()
    (dest / "SKILL.md").write_text("stale")
    (dest / "extra.txt").write_text("kept")
    skills.install_skill(proj, "orch", src)
    assert (dest / "SKILL.md").read_bytes() == (own / "SKILL.md").read_bytes()
    assert (dest / "extra.txt").read_text() == "kept"


def test_topics_are_appended_in_sorted_order_and_installed(tmp_path, proj):
    src = tmp_path / "skill"
    (src / "topics").mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"head\r\n")
    for name, data in [("50-b.md", b"b\n"), ("40-a.md", b"a\r\n"), ("note.txt", b"x")]:
        (src / "topics" / name).write_bytes(data)
    assert skills.skill_text(src) == "head\r\na\r\nb\n"
    skills.install_skill(proj, "orch-x", src)
    dest = skills.harness_skill(proj, "orch-x")
    assert (dest / "SKILL.md").read_bytes() == b"head\r\na\r\nb\n" and not (dest / "topics").exists()


def test_packaged_skill_ships_the_topics_folder():
    assert (skills.packaged_skills_dir() / "orch" / "topics").is_dir()


@pytest.mark.parametrize("name", ["SKILL.md"])
def test_core_skill_file_exists(name):
    assert (skills.packaged_skills_dir() / "orch" / name).is_file()
