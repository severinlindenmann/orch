import os
import sys
from pathlib import Path

import pytest

from orch import skills


def test_init_creates_everything(proj, run):
    code, out, _ = run("init")
    assert code == 0
    assert "name: orch" in (proj / ".agents/skills/orch/SKILL.md").read_text(encoding="utf-8")
    assert not (proj / ".agents/skills/orch/AGENTS-block.md").exists()
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- orch:begin orch -->" in agents and "<!-- orch:end orch -->" in agents
    assert (proj / "CLAUDE.md").read_text(encoding="utf-8").splitlines() == ["@AGENTS.md"]
    gi = (proj / ".gitignore").read_text(encoding="utf-8")
    assert ".orch/secrets/" in gi and ".orch/addons/" in gi and ".orch/.local-id" in gi
    assert (proj / ".claude/skills/orch/SKILL.md").is_file()  # through the link
    assert (proj / ".orch/tickets").is_dir()


def test_init_is_idempotent_and_keeps_user_text(proj, run):
    (proj / "AGENTS.md").write_text("# Mine\nhello\n", encoding="utf-8")
    (proj / "CLAUDE.md").write_text("# Claude\n@AGENTS.md\n", encoding="utf-8")
    (proj / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    assert run("init")[0] == 0
    first = {n: (proj / n).read_text(encoding="utf-8") for n in ("AGENTS.md", "CLAUDE.md", ".gitignore")}
    assert run("init")[0] == 0
    second = {n: (proj / n).read_text(encoding="utf-8") for n in first}
    assert first == second
    assert first["AGENTS.md"].startswith("# Mine\nhello\n")
    assert first["AGENTS.md"].count("orch:begin orch") == 1
    assert first["CLAUDE.md"].count("@AGENTS.md") == 1
    assert first["CLAUDE.md"].startswith("# Claude")
    assert (
        first[".gitignore"].startswith("node_modules\n") and first[".gitignore"].count(".orch/secrets/") == 1
    )


def test_block_replaced_whole_text_outside_untouched(proj):
    skills.set_block(proj, "orch", "old")
    p = proj / "AGENTS.md"
    p.write_text("before\n" + p.read_text(encoding="utf-8") + "after\n", encoding="utf-8")
    skills.set_block(proj, "orch", "new")
    t = p.read_text(encoding="utf-8")
    assert "new" in t and "old" not in t and t.startswith("before\n") and t.endswith("after\n")
    skills.remove_block(proj, "orch")
    assert p.read_text(encoding="utf-8") == "before\nafter\n"


def test_existing_claude_skills_folder_gets_per_skill_links(proj, run):
    (proj / ".claude/skills/mine").mkdir(parents=True)
    (proj / ".claude/skills/mine/SKILL.md").write_text("x", encoding="utf-8")
    assert run("init")[0] == 0
    assert (proj / ".claude/skills/mine/SKILL.md").is_file()
    assert (proj / ".claude/skills/orch/SKILL.md").is_file()
    assert not (proj / ".claude/skills").is_symlink()


def test_all_packaged_skills_have_front_matter():
    root = skills.packaged_skills_dir()
    assert sorted(p.name for p in root.iterdir() if p.is_dir()) == ["orch"]
    builtin = Path(skills.__file__).parent / "builtin"  # publish and relay: built-in add-ons
    dirs = {"orch": root / "orch"} | {
        f"orch-{n}": builtin / n / "skills" / f"orch-{n}" for n in ("publish", "relay")
    }
    for n, d in dirs.items():
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {n}\ndescription: ")
        assert (d / "AGENTS-block.md").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_windows_junction(proj, run):
    assert run("init")[0] == 0
    cl = proj / ".claude" / "skills"
    assert os.lstat(cl).st_file_attributes & 0x400  # reparse point = junction
    assert (cl / "orch" / "SKILL.md").is_file()
    assert Path(os.path.realpath(cl)) == (proj / ".agents" / "skills").resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
def test_unix_symlink_is_relative(proj, run):
    assert run("init")[0] == 0
    assert os.readlink(proj / ".claude/skills") == os.path.join("..", ".agents", "skills")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink setup")
def test_refuses_skills_dir_pointing_outside(proj, run, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (proj / ".agents").mkdir()
    os.symlink(outside, proj / ".agents" / "skills", target_is_directory=True)
    code, _, err = run("init")
    assert code == 2 and "outside" in err
    assert list(outside.iterdir()) == []
