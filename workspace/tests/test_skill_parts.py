"""The core skill = SKILL.md + topics/*.md; with no topic files it is byte-identical to the frozen text."""

from pathlib import Path

from orch import skills

GOLDEN = Path(__file__).with_name("fixtures") / "orch-skill.golden.md"


def test_golden():
    assert skills.skill_text(skills.packaged_skills_dir() / "orch").encode("utf-8") == GOLDEN.read_bytes()


def test_install(proj):
    source = skills.packaged_skills_dir() / "orch"
    skills.install_skill(proj, "orch", source)
    dest = skills.harness_skill(proj, "orch")
    assert (dest / "SKILL.md").read_bytes() == GOLDEN.read_bytes()
    assert not (dest / "topics").exists()
    (dest / "SKILL.md").write_text("stale")
    (dest / "extra.txt").write_text("kept")
    skills.install_skill(proj, "orch", source)
    assert (dest / "SKILL.md").read_bytes() == GOLDEN.read_bytes()
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
