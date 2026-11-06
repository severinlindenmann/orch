import os
import sys
from pathlib import Path

import pytest

from orch import adapters, skills


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    """Claude is on this machine (the files entry of a found agent is applied; CI has none)."""
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


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


def test_init_says_what_it_linked_and_what_is_next(proj, run):
    code, out, _ = run("init")
    assert code == 0 and "Linked for: Claude" in out and "Your agent can now use tickets." in out


def test_no_agent_found_links_nothing(proj, run, monkeypatch):
    monkeypatch.setattr(adapters, "detect", lambda: [])
    code, out, _ = run("init")
    assert code == 0 and "Linked for" not in out
    assert not (proj / ".claude").exists() and not (proj / "CLAUDE.md").exists()
    assert (proj / "AGENTS.md").is_file()


def test_codex_only_needs_only_agents_md(proj, run, monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "codex", "label": "Codex", "found": True, "version": None}]
    )
    code, out, _ = run("init")
    assert code == 0 and "Linked for" not in out and not (proj / "CLAUDE.md").exists()


def test_files_entries_come_from_the_data(proj, monkeypatch):
    reg = adapters._registry()
    monkeypatch.setitem(
        reg["codex"], "files", {"instructions_link": {"OTHER.md": "@AGENTS.md"}, "skills_link": ".other/skills"}
    )
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "codex", "label": "Codex", "found": True, "version": None}]
    )
    assert skills.apply_agent_files(proj) == ["Codex"]
    assert (proj / "OTHER.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert (proj / ".other/skills").is_symlink()


def test_recommended_turns_on_marked_addons_or_none(proj, run, monkeypatch):
    from orch import addons, init

    rows = [
        {"name": "a1", "recommended": True, "active": False},
        {"name": "a2", "recommended": True, "active": False},
        {"name": "a3", "recommended": False, "active": False},
    ]
    monkeypatch.setattr(addons, "listing", lambda root: rows)
    man = {"name": "x", "version": "1", "description": "d", "background": False}
    monkeypatch.setattr(addons, "discover", lambda: {r["name"]: man | {"name": r["name"]} for r in rows})
    seen = []
    monkeypatch.setattr(addons, "add", lambda root, n, yes=False: seen.append(n))
    assert init.recommended(proj, yes=True) == ["a1", "a2"] and seen == ["a1", "a2"]
    seen.clear()
    with pytest.raises(skills.Refused):  # not asked and no --yes: nothing happens
        init.recommended(proj, yes=False, interactive=False)
    assert seen == []


def test_recommended_failure_turns_none_on(proj, monkeypatch):
    from orch import addons, init

    rows = [{"name": "a1", "recommended": True, "active": False}, {"name": "a2", "recommended": True, "active": False}]
    monkeypatch.setattr(addons, "listing", lambda root: rows)
    man = {"version": "1", "description": "d", "background": False}
    monkeypatch.setattr(addons, "discover", lambda: {r["name"]: man | {"name": r["name"]} for r in rows})
    on, off = [], []

    def add(root, n, yes=False):
        if n == "a2":
            raise skills.Refused("boom")
        on.append(n)

    monkeypatch.setattr(addons, "add", add)
    monkeypatch.setattr(addons, "remove", lambda root, n, purge=False: off.append(n))
    with pytest.raises(skills.Refused, match="Nothing was changed"):
        init.recommended(proj, yes=True)
    assert on == ["a1"] and off == ["a1"]
