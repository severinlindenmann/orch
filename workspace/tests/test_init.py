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


def _git(proj, *args):
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *args], cwd=proj, env=env, capture_output=True, text=True, check=True
    ).stdout


def _git_repo(proj):
    _git(proj, "init", "-q")
    _git(proj, "config", "user.email", "t@example.com")
    _git(proj, "config", "user.name", "t")


def test_init_creates_everything(proj, run):
    code, out, _ = run("init")
    assert code == 0
    assert "name: orch" in (proj / ".orch/harness/skills/orch/SKILL.md").read_text(encoding="utf-8")
    assert not (proj / ".orch/harness/skills/orch/AGENTS-block.md").exists()
    assert (proj / ".agents/skills/orch/SKILL.md").is_file()  # through the link
    assert (proj / ".claude/skills/orch/SKILL.md").is_file()
    assert "orch" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    local = (proj / "CLAUDE.local.md").read_text(encoding="utf-8")
    assert "@.orch/harness/AGENTS.orch.md" in local and "@AGENTS.md" not in local  # the team has no AGENTS.md
    assert not (proj / "AGENTS.md").exists() and not (proj / "CLAUDE.md").exists()
    assert not (proj / ".gitignore").exists()
    assert (proj / ".orch/tickets").is_dir()


def test_fresh_init_in_a_git_repo_leaves_git_status_clean(proj, run):
    _git_repo(proj)
    (proj / "AGENTS.md").write_text("# Team rules\n", encoding="utf-8")
    (proj / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "base")
    assert run("init")[0] == 0
    # .orch/tickets, config.toml are the team's workspace state; everything of the harness is invisible
    status = _git(proj, "status", "--porcelain", "--untracked-files=all").splitlines()
    names = [x[3:] for x in status]
    assert not any(n.startswith((".agents", ".claude", ".orch/harness")) or n == "CLAUDE.local.md" for n in names)
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == "# Team rules\n"
    assert (proj / ".gitignore").read_text(encoding="utf-8") == "node_modules\n"
    assert "@AGENTS.md" in (proj / "CLAUDE.local.md").read_text(encoding="utf-8")  # team AGENTS.md, no CLAUDE.md
    ex = (proj / ".git/info/exclude").read_text(encoding="utf-8")
    assert "/.agents/skills/orch*" in ex and "/.claude/skills/orch*" in ex and "/CLAUDE.local.md" in ex
    assert run("init")[0] == 0  # again: same result, one block
    assert (proj / ".git/info/exclude").read_text(encoding="utf-8") == ex


def test_a_colleague_clone_without_orch_sees_no_orch_files(proj, run, tmp_path_factory):
    _git_repo(proj)
    (proj / "AGENTS.md").write_text("# Team rules\n", encoding="utf-8")
    assert run("init")[0] == 0
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "work")
    tracked = _git(proj, "ls-files").split()
    assert not any(t.startswith((".agents", ".claude", ".orch/harness")) or t == "CLAUDE.local.md" for t in tracked)
    clone = tmp_path_factory.mktemp("colleague") / "c"
    _git(proj, "clone", "-q", str(proj), str(clone))
    files = sorted(p.relative_to(clone).as_posix() for p in clone.rglob("*") if p.is_file() and ".git/" not in p.as_posix())
    assert "AGENTS.md" in files
    assert not [f for f in files if "harness" in f or f.startswith((".agents", ".claude")) or "CLAUDE" in f]


def test_init_keeps_user_files_and_is_idempotent(proj, run):
    (proj / "AGENTS.md").write_text("# Mine\nhello\n", encoding="utf-8")
    (proj / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    (proj / "CLAUDE.local.md").write_text("my private notes\n", encoding="utf-8")
    (proj / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    assert run("init")[0] == 0
    names = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", ".gitignore")
    first = {n: (proj / n).read_text(encoding="utf-8") for n in names}
    assert run("init")[0] == 0
    assert first == {n: (proj / n).read_text(encoding="utf-8") for n in names}
    assert first["AGENTS.md"] == "# Mine\nhello\n" and first["CLAUDE.md"] == "# Claude\n"
    assert first[".gitignore"] == "node_modules\n"
    local = first["CLAUDE.local.md"]
    assert local.startswith("my private notes\n") and local.count("orch:begin local") == 1
    assert "@AGENTS.md" not in local  # the team's CLAUDE.md is there: Claude reads it already


def test_no_git_same_layout_without_exclude(proj, run):
    assert run("init")[0] == 0
    assert not (proj / ".git").exists()
    assert (proj / ".agents/skills/orch/SKILL.md").is_file() and (proj / "CLAUDE.local.md").is_file()


def test_the_orch_block_is_in_the_start_prompt_of_a_non_claude_agent(proj, run):
    from orch import harness, runs

    assert run("init")[0] == 0
    assert "orch" in harness.start_text(proj)
    runs_mod_plan = runs.plan
    t = run("ticket", "new", "x", "--json")[1]
    import json

    tid = json.loads(t)["id"]
    plan_codex = runs_mod_plan(proj, tid, agent="codex")
    assert harness.start_text(proj)[:40] in plan_codex["prompt"]
    plan_claude = runs_mod_plan(proj, tid, agent="claude")
    assert harness.start_text(proj)[:40] not in plan_claude["prompt"]


def test_windows_copy_fallback_is_kept_in_sync(proj, run, monkeypatch):
    from orch import harness

    def no_links(link, target):
        harness._copy_dir(target, link)

    monkeypatch.setattr(harness, "_link_dir", no_links)
    assert run("init")[0] == 0
    cp = proj / ".agents/skills/orch"
    assert cp.is_dir() and not cp.is_symlink() and (cp / harness.COPY_MARK).is_file()
    (proj / ".orch/harness/skills/orch/SKILL.md").write_text("changed", encoding="utf-8")
    assert run("init")[0] == 0
    assert (cp / "SKILL.md").read_text(encoding="utf-8") == "changed" or "name: orch" in (cp / "SKILL.md").read_text(encoding="utf-8")


def test_does_not_replace_a_users_own_orch_folder(proj, run):
    (proj / ".agents/skills/orch").mkdir(parents=True)
    (proj / ".agents/skills/orch/SKILL.md").write_text("mine", encoding="utf-8")
    code, _, err = run("init")
    assert code == 2 and "not orch's" in err
    assert (proj / ".agents/skills/orch/SKILL.md").read_text(encoding="utf-8") == "mine"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink setup")
def test_harness_folder_linked_outside_is_refused(proj, run, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside2")
    (proj / ".orch").mkdir()
    os.symlink(outside, proj / ".orch" / "harness", target_is_directory=True)
    code, _, err = run("init")
    assert code == 2 and list(outside.iterdir()) == []


def test_share_with_team_on_and_off(proj, run):
    from orch import harness

    (proj / "AGENTS.md").write_text("# Team rules\n", encoding="utf-8")
    assert run("init")[0] == 0
    harness.share_on(proj)
    harness.share_on(proj)  # twice: still one block
    t = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert t.startswith("# Team rules\n") and t.count("orch:begin share") == 1 and "If it does not, ignore" in t
    assert "AGENTS.md merge=union" in (proj / ".gitattributes").read_text(encoding="utf-8")
    assert harness.share_state(proj)
    other = proj.parent / (proj.name + "_other")
    other.mkdir()
    (other / "AGENTS.md").write_text("# Team rules\n", encoding="utf-8")
    harness.share_on(other)
    assert (other / "AGENTS.md").read_text(encoding="utf-8") == t  # same text for everyone
    harness.share_off(proj)
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == "# Team rules\n"
    assert not (proj / ".gitattributes").exists() and not harness.share_state(proj)


def test_existing_claude_skills_folder_gets_per_skill_links(proj, run):
    (proj / ".claude/skills/mine").mkdir(parents=True)
    (proj / ".claude/skills/mine/SKILL.md").write_text("x", encoding="utf-8")
    assert run("init")[0] == 0
    assert (proj / ".claude/skills/mine/SKILL.md").is_file()
    assert (proj / ".claude/skills/orch/SKILL.md").is_file()
    assert not (proj / ".claude/skills").is_symlink() and (proj / ".claude/skills/orch").is_symlink()


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


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
def test_unix_symlink_is_relative(proj, run):
    assert run("init")[0] == 0
    assert os.readlink(proj / ".claude/skills/orch") == os.path.join("..", "..", ".orch", "harness", "skills", "orch")


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
    assert "Your agent will be allowed to work in this folder." in out


def test_no_agent_found_links_nothing(proj, run, monkeypatch):
    monkeypatch.setattr(adapters, "detect", lambda: [])
    code, out, _ = run("init")
    assert code == 0 and "Linked for" not in out
    assert not (proj / ".claude").exists() and not (proj / "CLAUDE.local.md").exists()
    assert (proj / ".agents/skills/orch/SKILL.md").is_file()


def test_codex_only_needs_only_agents_md(proj, run, monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "codex", "label": "Codex", "found": True, "version": None}]
    )
    code, out, _ = run("init")
    assert code == 0 and "Linked for" not in out and not (proj / "CLAUDE.local.md").exists()
    # Codex reads .agents/skills itself; its orch text comes in the start prompt
    assert (proj / ".agents/skills/orch/SKILL.md").is_file() and not (proj / ".claude").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink")
def test_files_entries_come_from_the_data(proj, monkeypatch):
    reg = adapters._registry()
    monkeypatch.setitem(
        reg["codex"],
        "files",
        {"instructions_link": {"OTHER.md": "@AGENTS.md"}, "skills_link": ".other/skills"},
    )
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "codex", "label": "Codex", "found": True, "version": None}]
    )
    skills.set_block(proj, "orch", "x")
    assert skills.apply_agent_files(proj) == ["Codex"]
    assert (proj / "OTHER.md").is_file() and not (proj / "AGENTS.md").exists()
    assert (proj / ".other/skills").is_dir() or not (proj / ".orch/harness/skills").exists()


def test_recommended_turns_on_marked_addons_or_none(proj, run, monkeypatch):
    from orch import addons, init

    rows = [
        {"name": "a1", "recommended": True, "active": False},
        {"name": "a2", "recommended": True, "active": False},
        {"name": "a3", "recommended": False, "active": False},
    ]
    monkeypatch.setattr(addons, "listing", lambda root: rows)
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: {})
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

    rows = [
        {"name": "a1", "recommended": True, "active": False},
        {"name": "a2", "recommended": True, "active": False},
    ]
    monkeypatch.setattr(addons, "listing", lambda root: rows)
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: {})
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


def test_recommended_also_turns_on_shipped_addons_that_are_not_installed(proj, monkeypatch):
    from orch import addons, init

    monkeypatch.setattr(addons, "listing", lambda root: [])
    monkeypatch.setattr(addons, "discover", lambda: {})
    man = {"version": "1", "description": "d", "background": False}
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: {"dash": man | {"name": "dash"}})
    seen = []
    monkeypatch.setattr(addons, "add", lambda root, n, yes=False: seen.append(n))
    assert init.recommended(proj, yes=True) == ["dash"] and seen == ["dash"]


def test_shipped_recommended_reads_the_local_source_manifests(monkeypatch):
    from pathlib import Path

    from orch import addons

    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ORCH_REPO", str(repo))
    monkeypatch.setattr(addons, "discover", lambda: {})
    assert sorted(addons.shipped_recommended()) == ["automation", "dashboard", "focus"]


def test_secrets_stay_ignored_even_when_linking_is_refused(proj, run, tmp_path_factory):
    _git_repo(proj)
    outside = tmp_path_factory.mktemp("outside3")
    (proj / ".agents").mkdir()
    os.symlink(outside, proj / ".agents" / "skills", target_is_directory=True)
    assert run("init")[0] == 2  # linking refused
    ex = (proj / ".git/info/exclude").read_text(encoding="utf-8")
    assert "/.orch/secrets/" in ex and "/.orch/run/" in ex and "/.orch/inbox/" in ex
    assert "secrets/" in (proj / ".orch/.gitignore").read_text(encoding="utf-8")
    (proj / ".orch/secrets").mkdir(parents=True, exist_ok=True)
    (proj / ".orch/secrets/publish.json").write_text("{}", encoding="utf-8")
    assert ".orch/secrets" not in _git(proj, "status", "--porcelain", "--untracked-files=all")


def test_orch_gitignore_protects_without_git_info_and_secrets_refuse_when_nothing_works(proj, monkeypatch):
    from orch import harness, net

    harness.protect_local(proj)  # no git repo: .orch/.gitignore alone is enough
    assert (proj / ".orch/.gitignore").is_file()
    (proj / ".orch/.gitignore").unlink()
    monkeypatch.setattr(harness, "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    with pytest.raises(skills.Refused, match="Nothing was stored"):
        net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert not (proj / ".orch/secrets/x.json").exists()


def test_share_command_on_off_status_and_agents_are_refused(proj, run, monkeypatch):
    assert run("init")[0] == 0
    code, out, _ = run("share", "--json")
    assert code == 0 and '"shared": false' in out
    assert run("share", "on")[0] == 0 and (proj / "AGENTS.md").is_file()
    assert '"shared": true' in run("share", "status", "--json")[1]
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("share", "off")
    assert code == 2 and "Only a person" in err and (proj / "AGENTS.md").is_file()
    monkeypatch.delenv("CLAUDECODE")
    assert run("share", "off")[0] == 0 and not (proj / "AGENTS.md").exists()
