"""Separate copies for a workspace folder that holds several git projects (issue 960): one copy folder per
ticket with a copy of each project inside, handed over by pull request (orch never merges it back), removed
only when nothing in it would be lost."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from orch import addons, config, runs, tickets, worktrees

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX links")


@pytest.fixture(autouse=True)
def _no_detached_clean(monkeypatch):
    monkeypatch.setenv("ORCH_NO_DETACHED_CLEAN", "1")


def git(cwd, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    if check:
        assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def _project(d: Path, text: str) -> None:
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@t")
    git(d, "config", "user.name", "t")
    (d / "code.txt").write_text(text)
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")


@pytest.fixture
def ws(proj, new_ticket):
    """A workspace folder that is no git project, with two projects side by side and its own instructions."""
    _project(proj / "app", "app\n")
    _project(proj / "kit", "kit\n")
    (proj / "AGENTS.md").write_text("workspace rules\n")
    (proj / "CLAUDE.md").write_text("@AGENTS.md\n")
    (proj / "notes").mkdir()
    (proj / "notes" / "n.txt").write_text("n\n")
    addons.workspace_id(proj, create=True)
    config.set_copies_mode(proj, "always")
    w = type("Ws", (type(proj),), {})(proj)
    w.tids = (new_ticket("One"), new_ticket("Two"))
    yield w
    for t in list(worktrees.registry(w)):
        for e in worktrees.registry(w)[t]["paths"]:
            top = w / e.get("project", "")
            subprocess.run(["git", "worktree", "remove", "--force", e["path"]], cwd=top, capture_output=True)
    for name in ("app", "kit"):
        subprocess.run(["git", "worktree", "prune"], cwd=w / name, capture_output=True)


def _route(root, ticket):
    folder, notes, after = worktrees.route(root, ticket)
    for step in after:
        notes = notes + step()
    return folder, notes


def test_each_project_gets_its_copy_in_one_folder_and_the_agent_starts_there(ws):
    t = ws.tids[0]
    folder, notes = _route(ws, t)
    want = worktrees.path_for(addons.workspace_id(ws), t)
    assert folder == want and notes == []
    for name, text in (("app", "app\n"), ("kit", "kit\n")):
        copy = folder / name
        assert (copy / "code.txt").read_text() == text
        assert git(copy, "rev-parse", "--abbrev-ref", "HEAD") == f"orch/{t}"
        assert git(copy, "status", "--porcelain") == ""
        assert git(ws / name, "status", "--porcelain") == ""  # the project itself is untouched
    paths = worktrees.registry(ws)[t]["paths"]
    assert [e["project"] for e in paths] == ["app", "kit"]
    assert worktrees.count(ws) == 1  # one copy folder, however many projects
    assert worktrees.is_orch_copy(folder) and worktrees.is_orch_copy(folder / "app")
    # the workspace's own files are there as links (its rule files as files); the store and projects are not
    assert (folder / "AGENTS.md").read_text() == "workspace rules\n"
    assert not (folder / "AGENTS.md").is_symlink()
    assert os.readlink(folder / "notes") == str(ws / "notes")
    assert not os.path.lexists(folder / ".orch")
    assert not (folder / "app").is_symlink()
    # the ticket records each project's copy for people (never the local path)
    rec = tickets.load(ws, t)["work"]["folders"]
    assert sorted(r["project"] for r in rec) == ["app", "kit"] and all("path" not in r for r in rec)
    # a second start finds the same folder, nothing is made twice
    assert _route(ws, t)[0] == folder and worktrees.count(ws) == 1


def test_the_copy_reads_the_workspace_instructions_and_says_where_the_projects_are(ws, monkeypatch):
    from orch import skills

    monkeypatch.setattr(skills, "detected_agents", lambda root: ["claude"])
    h = ws / ".orch" / "harness"
    (h / "skills" / "orch").mkdir(parents=True)
    (h / "skills" / "orch" / "SKILL.md").write_text("# orch\n")
    (h / "blocks").mkdir(parents=True, exist_ok=True)
    (h / "blocks" / "core.md").write_text("## orch workspace\nthe orch block\n")
    (h / "AGENTS.orch.md").write_text("## orch workspace\nthe orch block\n")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text("{}\n")
    skills.apply_agent_files(ws)
    assert (ws / "CLAUDE.local.md").is_file()
    t = ws.tids[0]
    folder, notes = _route(ws, t)
    assert notes == []
    # the agent tools' settings and skills are the workspace's own (links), never written through
    assert os.readlink(folder / ".claude") == str(ws / ".claude")
    assert (folder / ".agents" / "skills" / "orch" / "SKILL.md").read_text() == "# orch\n"
    # orch's own local instruction file: not the workspace's (that one imports the workspace's harness)
    local = folder / "CLAUDE.local.md"
    assert local.is_file() and not local.is_symlink()
    assert ".orch-harness/AGENTS.orch.md" in local.read_text()
    own = (folder / ".orch-harness" / "AGENTS.orch.md").read_text()
    assert "the orch block" in own and "app, kit" in own and "pull request" in own
    _route(ws, t)  # refreshed at each start: the note is there exactly once
    assert (folder / ".orch-harness" / "AGENTS.orch.md").read_text().count("## This separate copy") == 1
    # closed with nothing to lose: the whole copy folder goes; the workspace's linked files stay
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert not os.path.lexists(folder)
    trash = folder.parent / worktrees.TRASH
    assert any(trash.iterdir())
    worktrees._empty_trash_in(ws, folder.parent, time.monotonic() + 60, grace=False)
    assert not any(trash.iterdir())  # emptied, without following a link into the workspace
    assert (ws / ".claude" / "settings.json").is_file() and (ws / "AGENTS.md").is_file()
    assert (ws / "notes" / "n.txt").is_file() and (ws / "CLAUDE.local.md").is_file()
    assert (ws / ".orch" / "harness" / "skills" / "orch" / "SKILL.md").is_file()


def test_the_rule_files_are_plain_files_so_no_import_leaves_the_copy(ws):
    """A copy folder of several projects linked the workspace's CLAUDE.md and AGENTS.md: CLAUDE.md's
    `@AGENTS.md` then resolved outside the folder, so Claude Code asked "Allow external CLAUDE.md file
    imports?" (a live helper hung there) and an unattended run started without the workspace rules. They are
    plain files of the copy now, with the top-level files they import, written again at each start."""
    import re

    (ws / "CLAUDE.md").write_text("@AGENTS.md\n@RULES.md\n@notes/n.txt\n@../outside.md\n")
    (ws / "RULES.md").write_text("more rules\n")
    t = ws.tids[0]
    folder, notes = _route(ws, t)
    assert notes == []
    for name in ("CLAUDE.md", "AGENTS.md", "RULES.md"):
        f = folder / name
        assert f.is_file() and not f.is_symlink(), name
        assert f.read_text() == (ws / name).read_text(), name
    assert not os.path.lexists(folder / "outside.md")
    for imp in re.findall(r"^@(\S+)", (folder / "CLAUDE.md").read_text(), re.M)[:2]:
        assert (folder / imp).resolve().is_relative_to(folder.resolve()), imp
    # the workspace's text wins at the next start
    (ws / "AGENTS.md").write_text("workspace rules v2\n")
    _route(ws, t)
    assert (folder / "AGENTS.md").read_text() == "workspace rules v2\n"
    # a copy made before (a link orch made) becomes a file; the workspace's file is never written through
    (folder / "AGENTS.md").unlink()
    os.symlink(ws / "AGENTS.md", folder / "AGENTS.md")
    _route(ws, t)
    assert not (folder / "AGENTS.md").is_symlink()
    assert (folder / "AGENTS.md").read_text() == "workspace rules v2\n"
    assert (ws / "AGENTS.md").read_text() == "workspace rules v2\n" and not (ws / "AGENTS.md").is_symlink()
    # a link orch did not make stays as it is, with a note
    other = folder.parent / "elsewhere.md"
    other.write_text("not ours\n")
    (folder / "RULES.md").unlink()
    os.symlink(other, folder / "RULES.md")
    _, notes = _route(ws, t)
    assert os.readlink(folder / "RULES.md") == str(other) and other.read_text() == "not ours\n"
    assert any("RULES.md" in n for n in notes)
    (folder / "RULES.md").unlink()
    other.unlink()
    # closed with nothing to lose: the rule files never keep the copy folder
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert not os.path.lexists(folder)
    assert (ws / "CLAUDE.md").is_file() and (ws / "RULES.md").read_text() == "more rules\n"


def test_a_linked_rule_file_in_the_workspace_stays_a_link(ws, tmp_path):
    real = tmp_path / "shared-rules.md"
    real.write_text("shared\n")
    (ws / "AGENTS.md").unlink()
    os.symlink(real, ws / "AGENTS.md")
    folder, _ = _route(ws, ws.tids[0])
    assert os.readlink(folder / "AGENTS.md") == str(ws / "AGENTS.md")  # linked as before, never copied
    assert (folder / "CLAUDE.md").is_file() and not (folder / "CLAUDE.md").is_symlink()


def test_a_folder_without_projects_still_gets_no_copy(proj, new_ticket):
    t = new_ticket("No git")
    (proj / "plain").mkdir()
    assert worktrees.create(proj, t) is None
    assert worktrees.count(proj) == 0


def test_a_linked_or_hidden_folder_is_not_a_project(ws, tmp_path):
    other = tmp_path.parent / f"{tmp_path.name}_other"
    _project(other, "x\n")
    os.symlink(other, ws / "linked")
    _project(ws / ".hidden", "h\n")
    names = [n for n, _, _ in worktrees._projects(ws)[0]]
    assert names == ["app", "kit"]


def test_a_failed_project_takes_back_the_whole_copy(ws, monkeypatch):
    t = ws.tids[0]
    real = worktrees._add_copy

    def fail_on_kit(root, ticket, top, rel, head, dest, bring_back):
        if dest.name == "kit":
            return None, "boom"
        return real(root, ticket, top, rel, head, dest, bring_back)

    monkeypatch.setattr(worktrees, "_add_copy", fail_on_kit)
    assert worktrees.create(ws, t) is None
    assert not os.path.lexists(worktrees.path_for(addons.workspace_id(ws), t))
    assert git(ws / "app", "branch", "--list", f"orch/{t}") == ""
    assert t not in worktrees.registry(ws)


def test_done_never_brings_work_back_and_a_saved_copy_goes(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    app = folder / "app"
    (app / "code.txt").write_text("changed\n")
    git(app, "commit", "-qam", "work")
    git(app, "branch", "pushed")  # the work is on another branch too (as after a push)
    tickets.set_status(ws, t, "done", "human:test")
    worktrees.sweep(ws)
    assert (ws / "app" / "code.txt").read_text() == "app\n"  # never merged into the project
    assert not (tickets.load(ws, t).get("work") or {}).get("bring_back")
    assert not os.path.lexists(folder)  # moved to the trash
    assert t not in worktrees.registry(ws)
    assert git(ws / "app", "branch", "--list", f"orch/{t}") == ""
    assert git(ws / "kit", "branch", "--list", f"orch/{t}") == ""  # held nothing new


def test_uncommitted_work_keeps_that_projects_copy(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    (folder / "kit" / "new.txt").write_text("not committed\n")
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert (folder / "kit" / "new.txt").is_file()
    assert not os.path.lexists(folder / "app")  # the clean one went
    assert [e["project"] for e in worktrees.registry(ws)[t]["paths"]] == ["kit"]


def test_commits_on_no_other_branch_keep_the_branch(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    app = folder / "app"
    (app / "code.txt").write_text("only here\n")
    git(app, "commit", "-qam", "unsaved work")
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert not os.path.lexists(app)  # the folder goes: everything in it is committed
    assert git(ws / "app", "branch", "--list", f"orch/{t}").strip().endswith(f"orch/{t}")  # the work stays


def test_a_detached_commit_on_no_branch_keeps_the_copy(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    app = folder / "app"
    git(app, "checkout", "-q", "--detach")
    (app / "code.txt").write_text("detached\n")
    git(app, "commit", "-qam", "detached work")
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert (app / "code.txt").read_text() == "detached\n"


def test_an_open_ticket_or_a_live_run_keeps_the_copies(ws):
    a, b = ws.tids
    fa, _ = _route(ws, a)
    worktrees.sweep(ws)
    assert fa.is_dir()  # open ticket
    fb, _ = _route(ws, b)
    runs.claim(ws, b, "agent:x", "claude", pid=os.getpid())
    tickets.set_status(ws, b, "dropped", "human:test")
    worktrees.sweep(ws)
    assert fb.is_dir()  # an agent is still in it


def test_other_files_in_the_copy_folder_keep_it(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    (folder / "draft.md").write_text("an agent's own file\n")
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert (folder / "draft.md").is_file()
    assert not os.path.lexists(folder / "app")
    assert (ws / "AGENTS.md").read_text() == "workspace rules\n"  # a link is never followed


def test_a_forged_line_never_touches_another_folder(ws, tmp_path):
    t = ws.tids[0]
    _route(ws, t)
    decoy = tmp_path.parent / f"{tmp_path.name}_decoy"
    decoy.mkdir()
    (decoy / "keep.txt").write_text("k\n")
    reg = worktrees.registry(ws)
    reg[t]["paths"][0]["path"] = str(decoy)
    worktrees._save_registry(ws, reg)
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert (decoy / "keep.txt").is_file()


@pytest.mark.parametrize("name", ["..", "../x", ".hidden/..", "a/b"])
def test_a_registry_project_name_that_leaves_the_folder_is_refused(ws, name):
    t = ws.tids[0]
    _route(ws, t)
    reg = worktrees.registry(ws)
    reg[t]["paths"][0]["project"] = name
    worktrees._save_registry(ws, reg)
    assert [e["project"] for e in worktrees.registry(ws)[t]["paths"]] == ["kit"]


def test_a_faked_start_commit_never_deletes_unsaved_work(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    app = folder / "app"
    (app / "code.txt").write_text("only here\n")
    git(app, "commit", "-qam", "unsaved work")
    tip = git(app, "rev-parse", "HEAD")
    reg = worktrees.registry(ws)
    reg[t]["paths"][0]["base"] = tip  # an agent can write the registry
    worktrees._save_registry(ws, reg)
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert git(ws / "app", "rev-parse", f"refs/heads/orch/{t}") == tip


def test_files_git_ignores_wait_in_the_trash(ws):
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    app = folder / "app"
    (app / ".gitignore").write_text(".env\n")
    git(app, "add", ".gitignore")
    git(app, "commit", "-qm", "ignore")
    git(app, "branch", "pushed")
    (app / ".env").write_text("local only\n")
    tickets.set_status(ws, t, "dropped", "human:test")
    worktrees.sweep(ws)
    assert not os.path.lexists(app)
    kept = list((folder.parent / worktrees.TRASH).glob("*/.env"))
    assert kept and kept[0].read_text() == "local only\n"


def test_a_project_left_out_is_never_linked_in(ws):
    (ws / "sub").mkdir()
    (ws / "sub" / ".git").write_text("gitdir: /nowhere\n")  # a submodule or another worktree
    t = ws.tids[0]
    folder, _ = _route(ws, t)
    assert [e["project"] for e in worktrees.registry(ws)[t]["paths"]] == ["app", "kit"]
    assert not os.path.lexists(folder / "sub")


def test_a_workspace_that_is_a_git_project_never_gets_project_copies(proj, new_ticket):
    t = new_ticket("Fresh repo")
    git(proj, "init", "-q")  # a git project without a commit: no copy at all, not one of its sub folders
    _project(proj / "inner", "i\n")
    assert worktrees.create(proj, t) is None
    assert worktrees.count(proj) == 0
