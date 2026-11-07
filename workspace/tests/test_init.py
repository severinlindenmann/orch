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
    assert not any(
        n.startswith((".agents", ".claude", ".orch/harness")) or n == "CLAUDE.local.md" for n in names
    )
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == "# Team rules\n"
    assert (proj / ".gitignore").read_text(encoding="utf-8") == "node_modules\n"
    assert "@AGENTS.md" in (proj / "CLAUDE.local.md").read_text(
        encoding="utf-8"
    )  # team AGENTS.md, no CLAUDE.md
    ex = (proj / ".git/info/exclude").read_text(encoding="utf-8")
    assert "/.agents/skills/orch\n" in ex and "/.claude/skills/orch\n" in ex and "/CLAUDE.local.md" in ex
    assert run("init")[0] == 0  # again: same result, one block
    assert (proj / ".git/info/exclude").read_text(encoding="utf-8") == ex


def test_a_colleague_clone_without_orch_sees_no_orch_files(proj, run, tmp_path_factory):
    _git_repo(proj)
    (proj / "AGENTS.md").write_text("# Team rules\n", encoding="utf-8")
    assert run("init")[0] == 0
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "work")
    tracked = _git(proj, "ls-files").split()
    assert not any(
        t.startswith((".agents", ".claude", ".orch/harness")) or t == "CLAUDE.local.md" for t in tracked
    )
    clone = tmp_path_factory.mktemp("colleague") / "c"
    _git(proj, "clone", "-q", str(proj), str(clone))
    files = sorted(
        p.relative_to(clone).as_posix()
        for p in clone.rglob("*")
        if p.is_file() and ".git/" not in p.as_posix()
    )
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
    assert (cp / "SKILL.md").read_text(encoding="utf-8") == "changed" or "name: orch" in (
        cp / "SKILL.md"
    ).read_text(encoding="utf-8")


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
    assert (
        t.startswith("# Team rules\n") and t.count("orch:begin share") == 1 and "If it does not, ignore" in t
    )
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
    link = proj / ".claude/skills/orch"  # a symlink; on Windows a junction (no privileges needed)
    is_link = link.is_symlink() or getattr(link, "is_junction", lambda: False)()
    assert not (proj / ".claude/skills").is_symlink() and is_link


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
    assert os.readlink(proj / ".claude/skills/orch") == os.path.join(
        "..", "..", ".orch", "harness", "skills", "orch"
    )


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


def test_recommended_without_a_terminal_asks_and_is_not_an_error(proj, run, monkeypatch):
    """No terminal to ask in: orch says what it would turn on and how to confirm. A question, not an error."""
    from orch import addons

    rows = [{"name": "a1", "recommended": True, "active": False}]
    monkeypatch.setattr(addons, "listing", lambda root: rows)
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: {})
    man = {"name": "a1", "version": "1", "description": "Shows things.", "background": False}
    monkeypatch.setattr(addons, "discover", lambda: {"a1": man})
    added = []
    monkeypatch.setattr(addons, "add", lambda root, n, yes=False: added.append(n))
    code, _, err = run("init", "--recommended")
    assert code == 2 and not err.startswith("Refused") and "Refused:" not in err
    assert "Shows things." in err and "To turn these on, run it again with --yes." in err and added == []


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


def test_review_fixes_user_folder_kept_share_off_exact_and_eol(proj, run):
    from orch import harness

    # a user's own folder at a link place is never emptied or removed
    (proj / ".claude/skills/orch").mkdir(parents=True)
    (proj / ".claude/skills/orch/README.md").write_text("mine", encoding="utf-8")
    code, _, err = run("init")
    assert code == 2 and (proj / ".claude/skills/orch/README.md").read_text(encoding="utf-8") == "mine"
    # a user's own skill named like ours (orchestrator) is not hidden by the exclude block
    _git_repo(proj)
    (proj / ".claude/skills/orch/README.md").unlink()
    (proj / ".claude/skills/orch").rmdir()
    run("init")
    assert "orch*" not in (proj / ".git/info/exclude").read_text(encoding="utf-8")
    # share off: a .gitattributes line the team wrote itself stays; CRLF files keep CRLF
    (proj / ".gitattributes").write_bytes(b"AGENTS.md merge=union\r\n*.png binary\r\n")
    (proj / "AGENTS.md").write_bytes(b"# Team\r\n")
    harness.share_on(proj)
    assert b"\r\n" in (proj / "AGENTS.md").read_bytes() and b"\n" not in (
        proj / "AGENTS.md"
    ).read_bytes().replace(b"\r\n", b"")
    harness.share_off(proj)
    assert (proj / "AGENTS.md").read_bytes() == b"# Team\r\n"
    assert (proj / ".gitattributes").read_bytes() == b"AGENTS.md merge=union\r\n*.png binary\r\n"


def test_share_off_removes_an_agents_md_only_when_orch_made_it(proj, run):
    from orch import harness

    (proj / "AGENTS.md").write_text("", encoding="utf-8")  # the team's own (empty) file
    assert run("init")[0] == 0
    harness.share_on(proj)
    harness.share_off(proj)
    assert (proj / "AGENTS.md").is_file()
    (proj / "AGENTS.md").unlink()
    harness.share_on(proj)
    harness.share_off(proj)
    assert not (proj / "AGENTS.md").exists()


def test_a_long_orch_block_never_cuts_the_ticket_out_of_the_prompt(proj, run):
    import json

    from orch import harness, runs

    assert run("init")[0] == 0
    harness.set_block(proj, "big", "x" * 30000, addon=True)
    tid = json.loads(run("ticket", "new", "Find me", "--json")[1])["id"]
    assert "Find me" in runs.plan(proj, tid, agent="codex")["prompt"]


def test_addon_ignore_lines_that_hide_everything_are_refused(proj):
    from orch import addons

    for bad in (
        "*",
        "**",
        ".orch",
        ".orch/",
        ".orc?",
        ".ORCH",
        ".Orch/tickets/",
        ".orch/Tickets",
        ".orch/*",
        ".orch/tick*",
        "*/tickets",
        ".orch ",
        " .orch",
        "[.]orch",
        "./",
        "?",
        "*.tmp",
        ".orch/./tickets",
        ".orch/config.toml",
    ):
        with pytest.raises(skills.Refused):
            addons._set_gitignore(proj, "evil", [bad])


def test_addon_ignore_lines_that_name_a_place_are_accepted(proj):
    import subprocess

    from orch import addons

    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    addons._set_gitignore(proj, "ok", ["received/", ".orch/outbox/", "notes/*.tmp", ".orch/relay.lock*"])
    ex = (proj / ".git/info/exclude").read_text(encoding="utf-8")
    assert "/received/" in ex and "/.orch/outbox/" in ex and "/notes/*.tmp" in ex


@pytest.mark.skipif(sys.platform == "win32", reason="symlink setup")
def test_linked_dot_folder_outside_the_project_is_not_written_into(proj, run, tmp_path_factory):
    outside = tmp_path_factory.mktemp("dotfiles")
    os.symlink(outside, proj / ".claude", target_is_directory=True)  # `skills` does not exist there yet
    code, _, err = run("init")
    assert code == 2 and "outside" in err and list(outside.iterdir()) == []


# ---- review findings of PR #215 (harness local-only)


def _tracked_orch_gitignore(proj, extra_root=None, orch_text=None):
    _git_repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch/.gitignore").write_text(orch_text or "# team\n", encoding="utf-8")
    if extra_root is not None:
        (proj / ".gitignore").write_text(extra_root, encoding="utf-8")
    _git(proj, "add", "-f", ".")
    _git(proj, "commit", "-qm", "team")


@pytest.mark.parametrize(
    "root_ignore,orch_ignore",
    [
        ("!/.orch/secrets/\n", None),
        ("*\n!.orch/\n!.orch/**\n", None),
        (None, "!secrets/\n"),
    ],
)
def test_private_write_refuses_when_a_team_ignore_file_unignores_secrets(proj, root_ignore, orch_ignore):
    from orch import harness, net

    _tracked_orch_gitignore(proj, root_ignore, orch_ignore)
    with pytest.raises(skills.Refused):
        net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert not (proj / ".orch/secrets/x.json").exists()
    assert harness  # imported for clarity


def test_private_write_still_works_with_a_plain_tracked_orch_gitignore(proj):
    from orch import net

    _tracked_orch_gitignore(proj)
    net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert (proj / ".orch/secrets/x.json").is_file()


@pytest.mark.parametrize("bad", ["a\nb", "*", "x y", "..", ".", "a" * 65, "!x", "a[b]"])
def test_odd_skill_folder_names_are_skipped_and_never_reach_the_exclude_block(proj, bad, capsys):
    from orch import harness

    if "/" in bad or bad in {".", ".."}:
        pytest.skip("not creatable as a folder name")
    if sys.platform == "win32" and any(c in bad for c in '\n*?<>|"'):
        pytest.skip(
            "Windows cannot hold this folder name (name check: test_safe_skill_name_refuses_odd_names)"
        )
    base = proj / ".agents/skills"
    (base / bad).mkdir(parents=True)
    (base / bad / ".orch-shared").write_text("", encoding="utf-8")
    (base / "good-1.0_x").mkdir()
    (base / "good-1.0_x/.orch-shared").write_text("", encoding="utf-8")
    assert [p.name for p in skills._shared_skills(proj)] == ["good-1.0_x"]
    assert bad not in "\n".join(skills._exclude_lines(proj)).splitlines()
    assert "skipped" in capsys.readouterr().err.lower()
    del harness


@pytest.mark.parametrize(
    "bad", ["a\nb", "*", "new\nline", "star*", "x y", "..", ".", "a" * 65, "!x", "a[b]", "a:b"]
)
def test_safe_skill_name_refuses_odd_names(bad):
    from orch import harness

    assert not harness.safe_skill_name(bad)
    assert harness.safe_skill_name("good-1.0_x")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot hold these folder names (see test_safe_skill_name_refuses_odd_names)",
)
def test_odd_harness_skill_names_are_not_excluded(proj):
    sk = proj / ".orch/harness/skills"
    (sk / "ok").mkdir(parents=True)
    (sk / "new\nline").mkdir()
    (sk / "star*").mkdir()
    lines = skills._exclude_lines(proj)
    assert not any("\n" in ln or "*" in ln for ln in lines)
    assert ".agents/skills/ok" in lines


def test_glob_characters_are_escaped_in_exclude_lines():
    from orch import harness

    assert harness.glob_escape("a*b[c]?!") == "a\\*b\\[c\\]\\?\\!"


def _copy_setup(proj, harness):
    src = proj / ".orch/harness/skills/s1"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("x", encoding="utf-8")
    dest = proj / ".agents/skills/s1"
    harness._copy_dir(src, dest)
    return src, dest


def test_a_copy_marker_alone_does_not_delete_a_tracked_folder(proj, capsys):
    from orch import harness

    _git_repo(proj)
    dest = proj / ".agents/skills/s1"
    dest.mkdir(parents=True)
    (dest / "mine.md").write_text("user", encoding="utf-8")
    (dest / harness.COPY_MARK).write_text("x", encoding="utf-8")
    _git(proj, "add", "-f", ".agents")
    (proj / ".orch/harness/skills/s1").mkdir(parents=True)
    with pytest.raises(skills.Refused):
        harness.link_skill(proj, ".agents/skills", "s1")
    harness.sync_copies(proj, [".agents/skills"])
    harness.unlink_skill(proj, ".agents/skills", "s1")
    assert (dest / "mine.md").read_text(encoding="utf-8") == "user"


def test_a_copy_with_a_file_newer_than_the_marker_is_kept(proj):
    from orch import harness

    src, dest = _copy_setup(proj, harness)
    mark = dest / harness.COPY_MARK
    os.utime(mark, (1000, 1000))
    (dest / "user.txt").write_text("mine", encoding="utf-8")
    harness.sync_copies(proj, [".agents/skills"])
    harness.unlink_skill(proj, ".agents/skills", "s1")
    assert (dest / "user.txt").read_text(encoding="utf-8") == "mine"


def test_an_untouched_copy_is_still_synced_and_removed(proj):
    from orch import harness

    src, dest = _copy_setup(proj, harness)
    os.utime(dest / harness.COPY_MARK, (time_future(), time_future()))
    (src / "SKILL.md").write_text("new", encoding="utf-8")
    harness.sync_copies(proj, [".agents/skills"])
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "new"
    harness.unlink_skill(proj, ".agents/skills", "s1")
    assert not dest.exists()


def time_future():
    import time

    return time.time() + 5


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_copy_dir_does_not_follow_directory_links(proj, tmp_path_factory):
    from orch import harness

    outside = tmp_path_factory.mktemp("outside_copy")
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    src = proj / "srcdir"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    os.symlink(outside, src / "lnk", target_is_directory=True)
    dst = proj / "dstdir"
    harness._copy_dir(src, dst)
    assert (dst / "a.txt").is_file()
    assert not (dst / "lnk").exists() and not any(dst.rglob("secret.txt"))


_REINC = "!/.orch/secrets/\n/.orch/secrets/*\n"


@pytest.mark.parametrize(
    "root_ignore",
    [_REINC + "!/.orch/secrets/token.json\n", _REINC + "!*.json\n", _REINC + "!/.orch/secrets/tok*\n"],
)
def test_private_write_refuses_a_name_that_a_gitignore_unignores(proj, root_ignore):
    from orch import net

    _tracked_orch_gitignore(proj, root_ignore)
    with pytest.raises(skills.Refused):
        net.write_json(proj / ".orch/secrets/token.json", {"t": 1}, True)
    assert not (proj / ".orch/secrets/token.json").exists()


def test_private_write_refuses_a_tracked_file(proj):
    from orch import net

    _tracked_orch_gitignore(proj)
    (proj / ".orch/secrets").mkdir()
    (proj / ".orch/secrets/token.json").write_text("{}", encoding="utf-8")
    _git(proj, "add", "-f", ".orch/secrets/token.json")
    with pytest.raises(skills.Refused):
        net.write_json(proj / ".orch/secrets/token.json", {"t": 1}, True)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_private_write_refuses_a_linked_secrets_folder_in_a_repo(proj, tmp_path_factory):
    from orch import net

    _tracked_orch_gitignore(proj)
    outside = tmp_path_factory.mktemp("outside_sec")
    os.symlink(outside, proj / ".orch/secrets", target_is_directory=True)
    with pytest.raises(skills.Refused):
        net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert not (outside / "x.json").exists()


def test_a_git_failure_inside_a_repo_refuses_and_no_repo_is_fine(proj, monkeypatch):
    import subprocess

    from orch import harness, net

    _tracked_orch_gitignore(proj)
    real = subprocess.run

    def broken(cmd, *a, **k):
        if cmd[:2] == ["git", "check-ignore"]:
            return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: detected dubious ownership")
        return real(cmd, *a, **k)

    monkeypatch.setattr(harness.subprocess, "run", broken)
    with pytest.raises(skills.Refused):
        net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    monkeypatch.undo()
    assert not (proj / ".orch/secrets/x.json").exists()


def test_rev_parse_failure_that_is_not_no_repo_refuses(proj, monkeypatch):
    import subprocess

    from orch import harness

    def broken(cmd, *a, **k):
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: detected dubious ownership")

    monkeypatch.setattr(harness.subprocess, "run", broken)
    with pytest.raises(skills.Refused):
        harness._in_git_repo(proj)


def test_not_a_repo_still_stores_private_files(proj):
    from orch import net

    net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert (proj / ".orch/secrets/x.json").is_file()


def test_no_git_program_in_a_repo_refuses_and_in_a_plain_folder_is_fine(proj, monkeypatch):
    import subprocess

    from orch import harness

    def nogit(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(harness.subprocess, "run", nogit)
    assert harness._in_git_repo(proj) is False  # plain folder (the test folder has no .git above it)
    (proj / ".git").mkdir()
    with pytest.raises(skills.Refused):
        harness._in_git_repo(proj)
    del subprocess


def test_tracked_returns_true_when_git_cannot_be_run(proj, monkeypatch):
    from orch import harness

    def boom(*a, **k):
        raise OSError("x")

    monkeypatch.setattr(harness.subprocess, "run", boom)
    assert harness._tracked(proj, "a") is True


def test_a_copy_with_an_older_file_orch_did_not_copy_is_kept(proj):
    from orch import harness

    src, dest = _copy_setup(proj, harness)
    extra = dest / "user-old.txt"
    extra.write_text("mine", encoding="utf-8")
    os.utime(extra, (1000, 1000))  # older than the marker: mtime alone would not catch it
    os.utime(dest / harness.COPY_MARK, (time_future(), time_future()))
    harness.sync_copies(proj, [".agents/skills"])
    harness.unlink_skill(proj, ".agents/skills", "s1")
    assert extra.read_text(encoding="utf-8") == "mine"


def test_private_path_rejects_dotdot_and_other_case_orch(proj):
    from orch import harness

    with pytest.raises(skills.Refused):
        harness.check_private_path(proj, proj / ".orch" / "secrets" / ".." / ".." / "x.json")
    with pytest.raises(skills.Refused):
        harness.check_private_path(proj, proj / ".ORCH" / "secrets" / "x.json")


@pytest.mark.parametrize(
    "rel",
    [
        (".Orch", "secrets", "x.json"),  # another case of .orch: the same folder on Windows and macOS
        ("ORCH~1", "secrets", "x.json"),  # Windows 8.3 short name of .orch
        (".orch", "SECRE~1", "x.json"),  # a short name inside .orch
        (".orch", "secrets ", "x.json"),  # Windows drops a trailing space: lands in secrets
        (".orch", "secrets.", "x.json"),  # ... and a trailing dot
        (".orch", "secrets", "x.json."),
    ],
)
def test_private_path_refuses_names_windows_would_alias(proj, rel):
    from orch import harness

    with pytest.raises(skills.Refused):
        harness.check_private_path(proj, proj.joinpath(*rel))


def test_outbox_probe_is_checked_at_protect_time(proj):
    from orch import harness

    _tracked_orch_gitignore(proj, "!/.orch/outbox/\n/.orch/outbox/*\n!/.orch/outbox/probe\n")
    assert harness._probes_ignored(proj) is False


def test_without_git_in_a_plain_folder_private_writes_work(proj, monkeypatch, tmp_path_factory):
    from orch import net

    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("emptybin")))
    net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert (proj / ".orch/secrets/x.json").is_file()


def test_without_git_a_fresh_copy_is_ours(proj, monkeypatch, tmp_path_factory):
    from orch import harness

    src, dest = _copy_setup(proj, harness)
    os.utime(dest / harness.COPY_MARK, (time_future(), time_future()))
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("emptybin2")))
    assert harness._is_ours_copy(dest, proj) is True
    (proj / ".git").mkdir()  # a repo that cannot be checked: never ours
    assert harness._is_ours_copy(dest, proj) is False
