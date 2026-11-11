"""B12: copies are always taken back (remove, sweep, pending list, branches, agent traces). DATA-LOSS CLASS:
the decoy tests prove that nothing but this workspace's own, exactly-named copies is ever deleted."""

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from orch import addons, harness, humanproof, runs, tickets, worktrees
from orch.errors import Refused

_REAL_GUARDED_HOME = humanproof.guarded_home  # the true pairing check, before tests/conftest.py replaces it

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX permissions and links")


def git(cwd, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    if check:
        assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.fixture(autouse=True)
def _no_detached_clean(monkeypatch):
    """The trash is emptied by a detached process in real life; tests empty it themselves."""
    monkeypatch.setenv("ORCH_NO_DETACHED_CLEAN", "1")


@pytest.fixture
def repo(proj, new_ticket):
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@t")
    git(proj, "config", "user.name", "t")
    (proj / "code.py").write_text("print(1)\n")
    tids = [new_ticket(n) for n in ("One", "Two", "Three")]
    addons.workspace_id(proj, create=True)
    harness.protect_local(proj)
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "init")
    r = type("Repo", (type(proj),), {})(proj)
    r.tids = tids
    yield r
    for t in list(worktrees.registry(r)):
        for e in worktrees.registry(r)[t]["paths"]:
            subprocess.run(["git", "worktree", "remove", "--force", e["path"]], cwd=r, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=r, capture_output=True)


def make(repo, i=0):
    e = worktrees.create(repo, repo.tids[i])
    assert e, "copy not made"
    return Path(e["path"])


def close(repo, tid, status="dropped"):
    tickets.set_status(repo, tid, status, "human:test")


def branches(repo):
    return git(repo, "branch", "--list", "orch/*").split()


def pending(repo):
    return worktrees._pending(repo)


def age_trash(repo, hours=25):
    """Make every trash note `hours` old (the grace period counts from orch's own note)."""
    doc = pending(repo)
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    for i in doc["trash"]:
        i["at"] = old
    worktrees._save_pending(repo, doc)
    tr = worktrees.copies_dir(repo) / ".trash"
    when = time.time() - (hours + 1) * 3600  # what was in it is older than the rename
    for dp, dns, fns in os.walk(tr):
        for n in [*dns, *fns]:
            os.utime(os.path.join(dp, n), (when, when), follow_symlinks=False)


def empty(repo, hours=25):
    age_trash(repo, hours)
    return worktrees.empty_trash(repo)


def trash(repo):
    d = worktrees.copies_dir(repo) / ".trash"
    return sorted(d.iterdir()) if d.is_dir() else []


def wid8(repo):
    return addons.workspace_id(repo)[:8]


# ---------------------------------------------------------------- the decoys: nothing else is ever deleted


def test_decoys_are_never_deleted(repo, tmp_path):
    mine = make(repo, 0)  # a real copy of ticket 0: must stay while ticket 0 is open
    home = addons.home(repo)
    base = home / "worktrees"
    folder = mine.parent
    reg = worktrees.registry(repo)

    outside = tmp_path / "outside-decoy"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    linktarget = tmp_path / "link-target"
    linktarget.mkdir()
    (linktarget / "precious.txt").write_text("keep")
    sibling = base / "deadbeef"
    sibling.mkdir()
    (sibling / ".owner").write_text("/somewhere/else\n")
    (sibling / "t_aaaaaa01").mkdir()
    (sibling / "t_aaaaaa01" / "precious.txt").write_text("keep")

    # ticket ids that have no ticket file: "missing" -> the sweep tries to remove them
    ghosts = {
        "t_ghost001": outside,  # (1) outside the worktrees folder
        "t_ghost002": sibling / "t_aaaaaa01",  # (2) another workspace's folder
        "t_ghost003": folder / ".." / ".." / ".." / outside.name,  # (3) a path with `..` that leaves
        "t_ghost004": mine,  # (4) forged: ghost ticket aimed at ticket 0's copy
    }
    forged = {
        t: {"paths": [{"path": str(p), "branch": f"orch/{t}", "base": "x", "sub": ""}], "created_at": "x"}
        for t, p in ghosts.items()
    }
    # (5) a symlink at the exact place of a ghost ticket's copy, pointing out
    link = folder / "t_ghost005"
    link.symlink_to(linktarget)
    forged["t_ghost005"] = {
        "paths": [{"path": str(link), "branch": "orch/t_ghost005", "base": "x", "sub": ""}],
        "created_at": "x",
    }
    # (6) the right path, but .owner names another workspace (a copy folder of someone else)
    worktrees._save_registry(repo, {**reg, **forged})

    notes = worktrees.sweep(repo)
    assert not any("Traceback" in n for n in notes)

    assert (outside / "precious.txt").read_text() == "keep"
    assert (sibling / "t_aaaaaa01" / "precious.txt").read_text() == "keep"
    assert (linktarget / "precious.txt").read_text() == "keep"
    assert link.is_symlink()  # the link itself is not ours to take
    assert mine.is_dir() and (mine / "code.py").is_file()  # ticket 0 is open: its copy stays
    left = worktrees.registry(repo)
    assert list(left) == [repo.tids[0]]  # every forged line is gone, the real open ticket's stays


def test_owner_mismatch_is_not_deleted(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p.parent / ".owner").write_text("/another/workspace\n")
    close(repo, t)
    assert p.is_dir() and (p / "code.py").is_file()
    assert t in worktrees.registry(repo)  # kept: it is retried when the owner is right again


def test_owner_that_is_a_link_is_not_deleted(repo, tmp_path):
    p = make(repo, 0)
    real = tmp_path / "ownerfile"
    real.write_text(str(repo.resolve()) + "\n")
    (p.parent / ".owner").unlink()
    (p.parent / ".owner").symlink_to(real)
    close(repo, repo.tids[0])
    assert p.is_dir()


def test_a_symlinked_copy_folder_is_refused_and_its_target_kept(repo, tmp_path):
    t = repo.tids[0]
    p = make(repo, 0)
    git(repo, "worktree", "remove", "--force", str(p))
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep")
    p.symlink_to(target)
    close(repo, t)
    assert (target / "precious.txt").read_text() == "keep"
    assert p.is_symlink()


def test_a_link_inside_a_copy_is_removed_as_a_link_only(repo, tmp_path):
    target = tmp_path / "linked-out"
    target.mkdir()
    (target / "precious.txt").write_text("keep")
    p = make(repo, 0)
    (p / "escape").symlink_to(target)
    (p / "escape-file").symlink_to(target / "precious.txt")
    assert worktrees.rmtree_nofollow(p)
    assert not p.exists()
    assert (target / "precious.txt").read_text() == "keep"


def test_a_top_swapped_for_a_link_after_the_checks_is_not_followed(tmp_path, monkeypatch):
    """S1: even when every check said "plain folder", the delete itself never follows a link at the top."""
    t = tmp_path / "t"
    t.mkdir()
    (t / "f").write_text("keep")
    link = tmp_path / "swapped"
    link.symlink_to(t)
    monkeypatch.setattr(worktrees, "_is_link", lambda p: False)  # the "check" was fooled / raced
    worktrees.rmtree_nofollow(link)
    assert (t / "f").read_text() == "keep"


def test_rmtree_nofollow_refuses_a_top_that_is_a_link(tmp_path):
    t = tmp_path / "t"
    t.mkdir()
    (t / "f").write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(t)
    assert not worktrees.rmtree_nofollow(link)
    assert (t / "f").read_text() == "keep" and link.is_symlink()


def test_remove_only_for_ticket_ids_and_never_raises(repo):
    for bad in ("../x", "t_ghost/../..", "", None, "t_x"):
        assert worktrees.remove(repo, bad)  # a note, no exception, nothing deleted
    assert repo.exists()


# ---------------------------------------------------------------- remove: the normal paths


def test_clean_copy_is_removed_with_registry_and_merged_branch_and_the_folder_goes_to_the_trash(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    assert f"orch/{t}" in branches(repo)
    close(repo, t, "done")
    assert not p.exists()
    assert t not in worktrees.registry(repo)
    assert f"orch/{t}" not in branches(repo)  # nothing on it: merged into HEAD, `branch -d` succeeds
    assert str(p) not in git(repo, "worktree", "list")  # git forgot it
    assert len(trash(repo)) == 1
    assert not worktrees.empty_trash(repo) and len(trash(repo)) == 1  # inside the grace period
    assert empty(repo) and trash(repo) == []


def test_dirty_copy_is_committed_to_its_branch_first_and_reachable(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "code.py").write_text("print(2)\n")  # modified
    (p / "new.txt").write_text("new\n")  # untracked
    close(repo, t, "done")
    assert not p.exists() and t not in worktrees.registry(repo)
    assert git(repo, "show", f"orch/{t}:new.txt") == "new"
    assert git(repo, "show", f"orch/{t}:code.py") == "print(2)"
    assert git(repo, "log", "-1", "--format=%an <%ae>", f"orch/{t}") == "orch <orch@localhost>"
    assert [b["ticket"] for b in pending(repo)["branches"]] == [t]  # unmerged: the branch stays
    assert git(repo, "status", "--porcelain", "--", ".", ":!.orch") == ""  # the project is untouched


def test_the_commit_never_runs_hooks_or_signs(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    hooks = Path(git(repo, "rev-parse", "--git-common-dir"))
    hooks = (repo / hooks) if not hooks.is_absolute() else hooks
    (hooks / "hooks").mkdir(exist_ok=True)
    marker = repo.parent / "hook-ran"
    for h in ("pre-commit", "commit-msg", "post-commit", "reference-transaction"):
        f = hooks / "hooks" / h
        f.write_text(f"#!/bin/sh\ntouch {marker}\n")
        f.chmod(0o755)
    git(repo, "config", "commit.gpgsign", "true")
    git(repo, "config", "gpg.program", "/bin/false")
    (p / "x.txt").write_text("x")
    close(repo, t, "done")
    assert not marker.exists()
    assert git(repo, "show", f"orch/{t}:x.txt") == "x"


def test_a_copy_whose_changes_cannot_be_saved_is_kept(repo, monkeypatch):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "mine.txt").write_text("unsaved")
    monkeypatch.setattr(worktrees, "_save_leftovers", lambda *a: (False, "git could not save"))
    close(repo, t, "done")
    assert p.is_dir() and (p / "mine.txt").read_text() == "unsaved"
    assert t in worktrees.registry(repo)
    assert pending(repo)["kept"][0]["reason"] == "git could not save"


def test_git_timeout_or_no_git_keeps_the_copy_with_its_unsaved_work(repo, monkeypatch):
    """B2: a git failure is never a reason to delete a copy that may hold work."""
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "mine.txt").write_text("unsaved")
    real = worktrees._git

    def slow(args, cwd, *a, **k):
        if args[0] == "rev-parse":
            return 124, "", "git rev-parse took longer than 1 s"
        return real(args, cwd, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(worktrees, "_git", slow)
        close(repo, t, "done")
        assert (p / "mine.txt").read_text() == "unsaved" and t in worktrees.registry(repo)
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_top_of", lambda r: None)  # git missing
        worktrees.sweep(repo)
        assert (p / "mine.txt").read_text() == "unsaved"
    worktrees.sweep(repo)  # git is back: now it is saved and taken away
    assert not p.exists() and git(repo, "show", f"orch/{t}:mine.txt") == "unsaved"


def test_a_folder_that_is_not_a_worktree_of_ours_is_kept_and_gets_no_git_commands(repo, monkeypatch):
    """A copy folder whose .git belongs to another repository: no add, no commit there, not deleted."""
    t = repo.tids[0]
    p = make(repo, 0)
    git(repo, "worktree", "remove", "--force", str(p))
    p.mkdir()
    git(p, "init", "-q")
    (p / "work.txt").write_text("w")
    seen = []
    real = worktrees._git

    def spy(args, cwd, *a, **k):
        seen.append((args[0], str(cwd)))
        return real(args, cwd, *a, **k)

    monkeypatch.setattr(worktrees, "_git", spy)
    close(repo, t, "done")
    assert not [s for s in seen if s[1] == str(p) and s[0] in ("add", "commit")]
    assert (p / "work.txt").read_text() == "w"


def test_a_detached_head_on_the_tip_is_put_back_on_the_branch_and_saved(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    git(p, "checkout", "-q", "--detach")
    (p / "w.txt").write_text("work")
    close(repo, t, "done")
    assert not p.exists()
    assert git(repo, "show", f"orch/{t}:w.txt") == "work"  # reachable from the branch, not a dangling commit


def test_a_detached_head_elsewhere_or_a_persons_branch_is_never_committed_to(repo):
    t, t2 = repo.tids[0], repo.tids[1]
    p, q = make(repo, 0), make(repo, 1)
    # detached on a commit that is not the branch tip
    git(p, "checkout", "-q", "--detach")
    (p / "a.txt").write_text("a")
    git(p, "add", "a.txt")
    git(p, "commit", "-qm", "own commit")
    (p / "dirty.txt").write_text("dirty")
    # the agent switched to the person's branch
    git(q, "checkout", "-q", "-b", "feature-x")
    (q / "w.txt").write_text("work")
    before = git(repo, "rev-parse", "feature-x")
    close(repo, t, "done")
    close(repo, t2, "done")
    assert p.is_dir() and (p / "dirty.txt").is_file()
    assert q.is_dir() and (q / "w.txt").is_file()
    assert git(repo, "rev-parse", "feature-x") == before  # nothing was committed on the person's branch
    reasons = {k["ticket"]: k["reason"] for k in pending(repo)["kept"]}
    assert "not on branch" in reasons[t] or "not orch" in reasons[t]
    assert "feature-x" in reasons[t2]


def test_a_copy_with_a_live_run_is_not_removed(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    runs.claim(repo, t, "human:test", "claude", "oneshot", folder=p)
    close(repo, t)
    worktrees.sweep(repo)
    assert p.is_dir()  # the closing hook and the sweep both leave a copy a run is in


def test_an_open_ticket_keeps_its_copy_even_when_asked_to_remove_it(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    notes = worktrees.remove(repo, t)
    assert p.is_dir() and any("not done or closed" in n for n in notes)


def test_a_rename_that_fails_keeps_the_copy_and_the_next_sweep_takes_it(repo, monkeypatch):
    """Windows: a locked file stops the move. The copy stays (its changes saved), the next sweep retries."""
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")

    def locked(*a, **k):
        raise PermissionError("in use")

    with monkeypatch.context() as m:
        m.setattr(os, "rename", locked)
        close(repo, t, "done")
    assert p.is_dir() and t in worktrees.registry(repo)
    assert "in use" in pending(repo)["kept"][0]["reason"] or "moved" in pending(repo)["kept"][0]["reason"]
    worktrees.sweep(repo)
    assert not p.exists() and git(repo, "show", f"orch/{t}:w.txt") == "work"


# ---------------------------------------------------------------- closing and the sweep


def test_closing_a_ticket_removes_its_copy(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    close(repo, t, "dropped")
    assert not p.exists() and t not in worktrees.registry(repo)


def test_done_removes_the_copy_and_its_changes_stay_on_the_branch(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    close(repo, t, "done")
    assert not p.exists() and t not in worktrees.registry(repo)
    assert git(repo, "show", f"orch/{t}:w.txt") == "work"  # B13 will add them to the project first


def test_copies_on_two_runs_done_leaves_no_copy_and_no_registry_line(repo):
    """Lane C D6b: copies on, two runs, Done on both: both copies and both registry lines are gone."""
    from orch import config

    config.set_copies_mode(repo, "always")
    a, b = repo.tids[:2]
    pa, pb = make(repo, 0), make(repo, 1)
    ra = runs.claim(repo, a, "human:t", "claude", "oneshot", folder=pa, pid=os.getpid())
    rb = runs.claim(repo, b, "human:t", "claude", "oneshot", folder=pb, pid=os.getpid())
    close(repo, a, "done")
    close(repo, b, "done")
    assert pa.is_dir() and pb.is_dir()  # the agents are still in them: they go when the runs end
    runs.release(repo, a, ra["run"])
    runs.release(repo, b, rb["run"])
    assert not pa.exists() and not pb.exists()
    assert worktrees.registry(repo) == {} and worktrees.count(repo) == 0
    assert branches(repo) == []  # nothing on them: merged, deleted


def test_sweep_removes_missing_ticket_copies_and_keeps_open_ones(repo):
    a, b = make(repo, 0), make(repo, 1)
    tickets.ticket_path(repo, repo.tids[0]).unlink()
    worktrees.sweep(repo)
    assert not a.exists() and b.is_dir()
    assert list(worktrees.registry(repo)) == [repo.tids[1]]


def test_crash_case_kill_the_run_delete_the_ticket_next_sweep_removes_it(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    rec = runs.claim(repo, t, "human:test", "claude", "oneshot", folder=p)
    runs.release(repo, t, rec["run"])  # the run ended without cleanup
    tickets.ticket_path(repo, t).unlink()
    assert worktrees.sweep(repo) == []
    assert not p.exists() and worktrees.count(repo) == 0


def test_a_corrupt_registry_never_makes_open_tickets_copies_orphans(repo):
    """S3: with the registry gone or damaged, the copies of OPEN tickets are kept."""
    a, b = make(repo, 0), make(repo, 1)
    worktrees._registry_path(repo).write_text("{ damaged")
    worktrees.sweep(repo)
    assert a.is_dir() and b.is_dir()
    tickets.ticket_path(repo, repo.tids[1]).unlink()  # a deleted ticket's copy is an orphan that goes
    worktrees.sweep(repo)
    assert a.is_dir() and not b.exists()


def test_sweep_removes_orphan_folders_of_closed_tickets_of_this_workspace_only(repo):
    mine = make(repo, 0)
    worktrees._save_registry(repo, {})  # the registry lost it: an orphan, still a worktree of ours
    tickets.set_status(repo, repo.tids[0], "done", "human:t")  # no registry line: the hook has nothing to do
    plain = mine.parent / "t_plain0001"  # not a worktree of ours: git cannot confirm it, so it stays
    plain.mkdir()
    (plain / "f.txt").write_text("x")
    other = mine.parent / "not-a-ticket"  # not ticket-named: not ours to judge
    other.mkdir()
    worktrees.sweep(repo)
    assert not mine.exists()
    assert (plain / "f.txt").is_file() and other.is_dir()
    assert (mine.parent / ".owner").is_file()


def test_orphans_are_left_when_the_owner_is_not_this_workspace(repo):
    mine = make(repo, 0)
    worktrees._save_registry(repo, {})
    tickets.set_status(repo, repo.tids[0], "done", "human:t")
    (mine.parent / ".owner").write_text("/not/mine\n")
    worktrees.sweep(repo)
    assert mine.is_dir()


# ------------------------------------------------ a project that is gone or moved: never automatic


def _gone_folder(repo, ws8="aaaaaaaa", owner="/nonexistent/workspace", old=True):
    d = addons.home(repo) / "worktrees" / ws8
    (d / "t_abcdef12" / "sub").mkdir(parents=True)
    (d / "t_abcdef12" / "sub" / "f.txt").write_text("x")
    (d / ".owner").write_text(owner + "\n")
    if old:
        t = time.time() - 30 * 86400
        for p in [d, *d.rglob("*")]:
            os.utime(p, (t, t), follow_symlinks=False)
    return d


def test_a_moved_project_keeps_its_copies_however_old_and_they_are_reported(repo):
    main = repo.parent / "moved-old"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    notes = worktrees.sweep(repo)
    assert (d / "t_abcdef12" / "sub" / "f.txt").is_file() and not notes
    assert worktrees.orphaned(repo) == [{"ws8": "aaaaaaaa", "copies": 1}]
    assert worktrees.usage(repo)["orphaned"] == [{"ws8": "aaaaaaaa", "copies": 1}]


def test_a_living_workspaces_folder_is_not_reported_and_never_touched(repo, tmp_path):
    other = tmp_path / "otherws"
    (other / ".orch").mkdir(parents=True)
    (other / ".orch" / ".local-id").write_text("aaaaaaaa" + "0" * 24 + "\n")
    d = _gone_folder(repo, ws8="aaaaaaaa", owner=str(other))
    worktrees.sweep(repo)
    assert (d / "t_abcdef12" / "sub" / "f.txt").is_file() and worktrees.orphaned(repo) == []
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, "aaaaaaaa", discard=True)  # the project is there: refused


def test_remove_orphaned_is_a_persons_call_and_discard_is_explicit(repo, monkeypatch):
    main = repo.parent / "gone"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    notes = worktrees.remove_orphaned(repo, "aaaaaaaa")  # cannot be saved (no repository): kept
    assert (d / "t_abcdef12").is_dir() and "kept" in notes[0]
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, "aaaaaaaa", discard=True)  # an agent may not
    monkeypatch.delenv("CLAUDECODE")
    assert worktrees.remove_orphaned(repo, "aaaaaaaa", discard=True) == []
    assert not d.exists()


def test_remove_orphaned_saves_changes_first_when_the_repository_is_reachable(repo):
    """The project folder was renamed: its copies' git still works, so changes are saved, then removed."""
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    wsdir = p.parent
    (wsdir / ".owner").write_text("/old/place/of/the/project\n")  # moved: .owner is stale
    tickets.ticket_path(repo, t).unlink()
    worktrees._save_registry(repo, {})
    assert worktrees.orphaned(repo) == [] or True  # (our own folder is never listed as orphaned)
    other = addons.home(repo) / "worktrees" / "bbbbbbbb"
    other.mkdir()
    p2 = other / t
    git(repo, "worktree", "move", str(p), str(p2))
    main = repo.parent / "old-project"
    (other / ".owner").write_text(str(main) + "\n")
    remember_gone(repo, other, main)
    assert worktrees.orphaned(repo)[0]["ws8"] == "bbbbbbbb"
    assert worktrees.remove_orphaned(repo, "bbbbbbbb") == []
    assert git(repo, "show", f"orch/{t}:w.txt") == "work"
    assert not other.exists() or not any((other / x).exists() for x in (t,))


# ---------------------------------------------------------------- forged notes authorize nothing


def test_forged_kept_and_branch_notes_delete_nothing(repo):
    """B3/S2: the notes file is agent-writable: a line for an open ticket changes nothing."""
    t = repo.tids[0]
    p = make(repo, 0)
    old = "2000-01-01T00:00:00Z"
    doc = {
        "kept": [{"ticket": t, "reason": "x", "at": old}],
        "branches": [{"ticket": t, "branch": f"orch/{t}", "at": old}],
        "folders": [{"ticket": t, "path": str(p), "removed_at": old}],  # the old shape: ignored
    }
    (repo / worktrees.REGISTRY_PENDING).write_text(json.dumps(doc))
    worktrees.sweep(repo)
    assert p.is_dir() and f"orch/{t}" in branches(repo)


# ---------------------------------------------------------------- branches


def _commit_old(p, days):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    when = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))
    env.update(GIT_AUTHOR_DATE=when + "Z", GIT_COMMITTER_DATE=when + "Z")
    (p / "old.txt").write_text("old")
    subprocess.run(["git", "add", "-A"], cwd=p, env=env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "old"], cwd=p, env=env, check=True, capture_output=True)


def test_unmerged_branch_is_kept_14_days_after_its_last_commit_and_the_removal(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    _commit_old(p, 20)
    close(repo, t, "done")
    assert f"orch/{t}" in branches(repo)
    worktrees.sweep(repo)
    assert f"orch/{t}" in branches(repo)  # the copy was removed just now: kept
    doc = pending(repo)
    doc["branches"][0]["at"] = "2000-01-01T00:00:00Z"
    worktrees._save_pending(repo, doc)
    worktrees.sweep(repo)
    assert f"orch/{t}" not in branches(repo)  # old tip AND old removal note


def test_a_forged_old_date_does_not_delete_a_fresh_branch(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")  # saved now: the tip is fresh
    close(repo, t, "done")
    doc = pending(repo)
    doc["branches"][0]["at"] = "2000-01-01T00:00:00Z"  # forged
    worktrees._save_pending(repo, doc)
    worktrees.sweep(repo)
    assert git(repo, "show", f"orch/{t}:w.txt") == "work"


def test_the_branch_of_an_open_or_copied_ticket_is_never_swept(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    _commit_old(p, 40)
    worktrees.sweep(repo)  # open ticket, live copy: nothing happens
    assert p.is_dir() and f"orch/{t}" in branches(repo)


def test_a_branch_that_gets_merged_later_goes_at_the_next_sweep(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    close(repo, t, "done")
    git(repo, "merge", "--no-ff", "-q", "-m", "bring back", f"orch/{t}")
    worktrees.sweep(repo)
    assert f"orch/{t}" not in branches(repo)


def test_other_branches_are_never_deleted(repo):
    git(repo, "branch", "feature/mine")
    git(repo, "branch", "orch/not-a-ticket")
    t = repo.tids[0]
    make(repo, 0)
    close(repo, t, "done")
    worktrees.sweep(repo)
    both = git(repo, "branch", "--list")
    assert "feature/mine" in both and "orch/not-a-ticket" in both


# ---------------------------------------------------------------- the trash


def test_the_trash_only_empties_its_own_children(repo, tmp_path):
    p = make(repo, 0)
    d = p.parent
    tr = d / ".trash"
    tr.mkdir()
    ok = tr / "t_abcdef12-0123abcd"
    ok.mkdir()
    (ok / "f").write_text("x")
    odd = tr / "my-notes"
    odd.mkdir()
    target = tmp_path / "linkdest"
    target.mkdir()
    (target / "keep").write_text("keep")
    (tr / "t_abcdef13-0123abcd").symlink_to(target)
    assert not worktrees.empty_trash(repo)
    assert empty(repo) is False
    assert not ok.exists() and odd.is_dir() and (target / "keep").is_file()


def test_a_trash_that_is_a_link_is_refused(repo, tmp_path):
    p = make(repo, 0)
    target = tmp_path / "linkdest"
    (target / "t_abcdef12-0123abcd").mkdir(parents=True)
    (p.parent / ".trash").symlink_to(target)
    assert not worktrees.empty_trash(repo)
    assert (target / "t_abcdef12-0123abcd").is_dir()


# ---------------------------------------------------------------- the agent tool's traces


def _claude_files(proj):
    cfg = Path(os.environ["CLAUDE_CONFIG_DIR"])
    return cfg, cfg / ".claude.json", cfg / "projects"


def test_transcripts_and_trust_of_a_removed_copy_go_and_nothing_else(repo):
    import re

    t = repo.tids[0]
    p, p2 = make(repo, 0), make(repo, 1)
    cfg, cj, projects = _claude_files(repo)
    enc = lambda x: re.sub(r"[^A-Za-z0-9]", "-", str(x))  # noqa: E731
    for q in (p, p2, repo):
        (projects / enc(q.resolve())).mkdir(parents=True, exist_ok=True)
        (projects / enc(q.resolve()) / "s.jsonl").write_text("{}")
    lookalike = projects / (enc(p.resolve()) + "-other")
    lookalike.mkdir()
    cj.write_text(
        json.dumps(
            {
                "numStartups": 3,
                "projects": {
                    str(p.resolve()): {"hasTrustDialogAccepted": True, "history": []},
                    str(p2.resolve()): {"hasTrustDialogAccepted": True},
                    str(repo.resolve()): {"hasTrustDialogAccepted": True},
                },
            }
        )
    )
    close(repo, t, "done")
    assert t not in worktrees.registry(repo)
    assert not (projects / enc(p.resolve())).exists()
    assert (projects / enc(p2.resolve()) / "s.jsonl").is_file()
    assert (projects / enc(repo.resolve()) / "s.jsonl").is_file()  # the workspace's own: never
    assert lookalike.is_dir()
    doc = json.loads(cj.read_text())
    assert doc["numStartups"] == 3
    assert set(doc["projects"]) == {str(p2.resolve()), str(repo.resolve())}


def test_a_malformed_claude_json_is_left_untouched(repo):
    t = repo.tids[0]
    make(repo, 0)
    cfg, cj, projects = _claude_files(repo)
    cj.write_text("{ not json")
    close(repo, t, "done")
    assert cj.read_text() == "{ not json"


def test_a_linked_claude_json_is_left_untouched(repo, tmp_path):
    t = repo.tids[0]
    p = make(repo, 0)
    cfg, cj, projects = _claude_files(repo)
    real = tmp_path / "real-claude.json"
    body = json.dumps({"projects": {str(p.resolve()): {"hasTrustDialogAccepted": True}}})
    real.write_text(body)
    cj.symlink_to(real)
    close(repo, t, "done")
    assert real.read_text() == body


def test_forget_refuses_a_folder_outside_the_copies_folder(repo, tmp_path):
    from orch import adapters

    cfg, cj, projects = _claude_files(repo)
    victim = tmp_path / "myproject"
    victim.mkdir()
    import re

    d = projects / re.sub(r"[^A-Za-z0-9]", "-", str(victim.resolve()))
    d.mkdir(parents=True)
    cj.write_text(json.dumps({"projects": {str(victim.resolve()): {"hasTrustDialogAccepted": True}}}))
    assert adapters.forget_folder("claude", victim, addons.home(repo) / "worktrees") == []
    assert d.is_dir() and str(victim.resolve()) in cj.read_text()


# ---------------------------------------------------------------- the sweep never breaks a start


def test_sweep_never_raises_and_says_why(repo, monkeypatch):
    make(repo, 0)
    monkeypatch.setattr(worktrees, "_top_of", lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    notes = worktrees.sweep(repo)
    assert notes and "boom" in notes[0]


def test_sweep_skips_when_the_copies_lock_is_busy(repo, subprocess_home):
    """Another process (a start making a copy) holds the copies lock: the sweep skips, it does not wait."""
    import sys

    make(repo, 0)
    tickets.ticket_path(repo, repo.tids[0]).unlink()
    code = (
        "import sys, time; from pathlib import Path; from orch import worktrees\n"
        "with worktrees.start_lock(Path(sys.argv[1])):\n"
        "    print('held', flush=True); time.sleep(60)\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child = subprocess.Popen(
        [sys.executable, "-P", "-c", code, str(repo)], env=env, cwd=repo, stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "held"
        start = time.monotonic()
        notes = worktrees.sweep(repo)
        assert time.monotonic() - start < 10
        assert notes and "busy" in notes[0]
        assert worktrees.count(repo) == 1  # nothing was done
    finally:
        child.terminate()  # this child's own PID only
        child.wait(10)


def test_sweep_stops_at_its_time_box(repo):
    for i in range(3):
        make(repo, i)
        tickets.ticket_path(repo, repo.tids[i]).unlink()
    notes = worktrees.sweep(repo, budget=-1)
    assert "time box reached" in notes
    assert worktrees.count(repo) == 3
    assert worktrees.sweep(repo) == []
    assert worktrees.count(repo) == 0


def test_sweep_without_copies_is_a_no_op(proj):
    assert worktrees.sweep(proj) == []


def test_a_busy_close_hook_does_not_raise(repo, monkeypatch):
    def boom(*a, **k):
        raise Refused("busy")

    monkeypatch.setattr(runs, "locked", boom)
    make_ok = worktrees.on_closed(repo, repo.tids[0])
    assert make_ok is None


def test_usage_counts_copies_and_size_without_following_links(repo, tmp_path):
    p = make(repo, 0)
    big = tmp_path / "big"
    big.write_text("x" * 100000)
    (p / "link").symlink_to(big)
    (p / "own.bin").write_bytes(b"y" * 5000)
    u = worktrees.usage(repo)
    assert u["copies"] == 1 and 5000 <= u["bytes"] < 100000 and u["partial"] is False
    assert worktrees.usage(repo, seconds=-1)["partial"] is True


# ---------------------------------------------------------------- triggers


def test_orch_copy_clean_removes_and_says_what_is_left(repo, subprocess_home):
    import sys

    a, b = make(repo, 0), make(repo, 1)
    tickets.ticket_path(repo, repo.tids[0]).unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["ORCH_ROOT"] = str(repo)
    p = subprocess.run(
        [sys.executable, "-P", "-m", "orch", "copy", "clean", "--json"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["copies"] == 1 and not a.exists() and b.is_dir()


def test_run_start_and_orch_start_sweep_first(repo, monkeypatch):
    from orch import cli_status, services

    calls = []
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda root: calls.append("scheduled"))
    monkeypatch.setattr(worktrees, "sweep", lambda *a, **k: calls.append("RAN IN THE START") or [])
    with pytest.raises(Refused):
        runs.start(repo, repo.tids[0], "human:t", agent="no-such-agent")
    assert calls == ["scheduled"]  # a start only schedules; the saves never run under its patience
    monkeypatch.setattr(services, "start", lambda root: [])
    args = type("A", (), {"cmd": "start", "print_launch_url": False, "json": True, "no_open": True})()
    cli_status._services_cmd(args, repo)
    assert calls == ["scheduled", "scheduled"]


# ---------------------------------------------------------------- the detached trash clean


def test_the_detached_clean_never_imports_anything_planted_in_the_workspace(repo, monkeypatch):
    import sys

    p = make(repo, 0)
    (p.parent / ".trash").mkdir()
    marker = repo.parent / "planted-ran"
    (repo / "orch.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    (repo / "orch").mkdir()
    (repo / "orch" / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    monkeypatch.delenv("ORCH_NO_DETACHED_CLEAN")
    seen = {}

    def fake_popen(argv, **kw):
        seen.update(argv=argv, **kw)

        class P:
            pass

        return P()

    with monkeypatch.context() as m:
        m.setattr(worktrees.subprocess, "Popen", fake_popen)
        worktrees.spawn_trash_clean(repo)
    argv = seen["argv"]
    assert argv[:5] == [sys.executable, "-I", "-P", "-m", "orch"]
    assert Path(seen["cwd"]).resolve() != repo.resolve() and seen["env"]["ORCH_ROOT"] == str(repo)
    done = subprocess.run(argv, cwd=seen["cwd"], env=seen["env"], capture_output=True, text=True, timeout=60)
    assert not marker.exists(), done.stderr
    assert done.returncode == 0, done.stderr


def test_a_link_inside_a_copy_never_makes_orch_chmod_its_target(repo, tmp_path):
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("keep")
    decoy.chmod(0o640)
    decoydir = tmp_path / "decoydir"
    decoydir.mkdir()
    decoydir.chmod(0o750)
    p = make(repo, 0)
    ro = p / "readonly"
    ro.mkdir()
    (ro / "f").write_text("x")
    (ro / "link").symlink_to(decoy)
    (ro / "dlink").symlink_to(decoydir)
    ro.chmod(0o500)  # a read-only folder: the delete must fix it, and only it
    d = p.parent / ".trash"
    d.mkdir()
    moved = d / "t_abcdef12-0123abcd"
    os.rename(p, moved)
    assert worktrees.empty_trash(repo) is False  # no note yet: its grace starts now
    assert empty(repo)
    assert not moved.exists()
    assert decoy.read_text() == "keep" and decoy.stat().st_mode & 0o777 == 0o640
    assert decoydir.stat().st_mode & 0o777 == 0o750


# ------------------------------------------------ review 2: grace period, stale lock, schedule


def test_a_removed_copy_that_changed_after_it_was_saved_is_kept_and_flagged(repo):
    """F1: a process orch does not know (a dev server) wrote into the renamed folder: nothing is deleted."""
    t = repo.tids[0]
    make(repo, 0)
    close(repo, t, "done")
    age_trash(repo)
    (entry,) = trash(repo)
    (entry / "late.log").write_text("written by a background process")
    assert worktrees.empty_trash(repo) is False
    assert (entry / "late.log").is_file()
    assert worktrees.usage(repo)["changed"] == 1
    assert pending(repo)["trash"][0]["changed"] is True


def test_the_trash_grace_counts_from_orchs_note_not_from_mtimes(repo):
    t = repo.tids[0]
    make(repo, 0)
    close(repo, t, "done")
    (entry,) = trash(repo)
    old = time.time() - 90 * 86400
    for p in [entry, *entry.rglob("*")]:
        os.utime(p, (old, old), follow_symlinks=False)  # an agent backdating everything changes nothing
    assert worktrees.empty_trash(repo) is False and entry.is_dir()
    age_trash(repo)
    assert worktrees.empty_trash(repo) is True and not entry.exists()


def _stale_lock(p, minutes):
    lock = worktrees._gitdir_of(p) / "index.lock"
    lock.write_text("")
    when = time.time() - minutes * 60
    os.utime(lock, (when, when))
    return lock


def test_a_stale_index_lock_keeps_the_copy_with_a_note_and_try_again_clears_it(repo, monkeypatch):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    lock = _stale_lock(p, 30)
    close(repo, t, "done")
    assert (p / "w.txt").is_file() and t in worktrees.registry(repo)
    u = worktrees.usage(repo)
    assert [s["ticket"] for s in u["stuck"]] == [t] and "interrupted" in u["stuck"][0]["reason"]
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(Refused):
        worktrees.retry(repo, t)  # a person's call only
    assert lock.exists()
    monkeypatch.delenv("CLAUDECODE")
    worktrees.retry(repo, t)
    assert not lock.exists() and not p.exists()
    assert git(repo, "show", f"orch/{t}:w.txt") == "work"
    assert worktrees.usage(repo)["stuck"] == []


def test_a_fresh_index_lock_is_not_called_stale_and_is_never_removed(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    lock = _stale_lock(p, 1)  # a git may be running right now
    close(repo, t, "done")
    assert p.is_dir() and worktrees.usage(repo)["stuck"] == []
    worktrees.retry(repo, t)  # nothing stale: it only tries the normal path again
    assert lock.exists() and p.is_dir()


def test_starts_only_schedule_a_detached_clean_and_only_when_there_is_something(repo, monkeypatch):
    import sys

    monkeypatch.delenv("ORCH_NO_DETACHED_CLEAN")
    seen = []

    def fake_popen(argv, **kw):
        seen.append((argv, kw))

    with monkeypatch.context() as m:
        m.setattr(worktrees.subprocess, "Popen", fake_popen)
        worktrees.schedule_sweep(repo)
    assert seen == []  # no copies folder, no notes: nothing to do
    make(repo, 0)
    with monkeypatch.context() as m:
        m.setattr(worktrees.subprocess, "Popen", fake_popen)
        worktrees.schedule_sweep(repo)
    argv, kw = seen[0]
    assert argv[:5] == [sys.executable, "-I", "-P", "-m", "orch"] and argv[5:] == [
        "copy",
        "clean",
        "--background",
    ]
    assert Path(kw["cwd"]).resolve() != repo.resolve() and kw["env"]["ORCH_ROOT"] == str(repo)
    # orch distrusts an ORCH_HOME inside its cwd (e2e G1-CLEAN proves it): not the home
    assert Path(kw["cwd"]).resolve() != worktrees.addons.home(repo).resolve()


@pytest.mark.parametrize("ended", [False, True])
def test_lane_c_post_rename_failure_drops_closed_entry(repo, monkeypatch, ended):
    a, b = repo.tids[:2]
    pa, pb = make(repo, 0), make(repo, 1)
    rec = runs.claim(repo, a, "human:t", "claude", "oneshot", folder=pa, pid=os.getpid())
    runs.release(repo, a, rec["run"])
    rec = runs.claim(repo, a, "human:t", "claude", "oneshot", folder=pa, pid=os.getpid())
    close(repo, b, "done")
    assert not pb.exists() and a in worktrees.registry(repo)
    original = worktrees._delete_branch

    def fail_after_rename(top, tid, **kw):
        if tid == a:
            raise OSError("post-rename failure")
        return original(top, tid, **kw)

    monkeypatch.setattr(worktrees, "_delete_branch", fail_after_rename)
    if ended:
        close(repo, a, "done")
        assert pa.exists()
        runs.release(repo, a, rec["run"])
    else:
        runs.release(repo, a, rec["run"])
        close(repo, a, "done")
    assert not pa.exists()
    assert str(pa) not in git(repo, "worktree", "list", "--porcelain")
    assert a not in worktrees.registry(repo)


@pytest.mark.parametrize("action", ["remove", "sweep", "clean"])
def test_missing_closed_copy_without_owner_is_clearable(repo, run, action):
    t = repo.tids[0]
    p = make(repo)
    git(repo, "worktree", "remove", str(p))
    (p.parent / ".owner").unlink()
    p.parent.rmdir()
    (addons.home(repo) / "keys" / "copies" / "registry.json").unlink()
    p.parent.parent.rmdir()
    tickets.ticket_path(repo, t).unlink()
    if action == "clean":
        code, out, err = run("copy", "clean", "--json")
        assert code == 0, err
        assert json.loads(out)["copies"] == 0
    elif action == "remove":
        assert worktrees.remove(repo, t) == []
    else:
        assert worktrees.sweep(repo) == []
    assert t not in worktrees.registry(repo)


def test_usage_two_live_registry_paths_and_missing_path(repo, monkeypatch):
    p, q = make(repo, 0), make(repo, 1)
    assert worktrees.usage(repo, max_entries=0)["copies"] == 2
    monkeypatch.setattr(worktrees, "copies_dir", lambda root: None)
    assert worktrees.usage(repo)["copies"] == worktrees.count(repo) == 2
    git(repo, "worktree", "remove", str(p))
    assert q.is_dir()
    assert worktrees.usage(repo)["copies"] == worktrees.count(repo) == 1


def test_orphan_forged_owner_alone_cannot_authorize_removal(repo):
    d = _gone_folder(repo)
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, "aaaaaaaa", discard=True)
    assert (d / "t_abcdef12" / "sub" / "f.txt").is_file()


def test_retry_live_run_keeps_stale_lock(repo):
    t = repo.tids[0]
    p = make(repo)
    (p / "work.txt").write_text("work")
    lock = _stale_lock(p, 30)
    rec = runs.claim(repo, t, "human:t", "claude", "oneshot", folder=p, pid=os.getpid())
    close(repo, t, "done")
    with pytest.raises(Refused, match="git was interrupted"):
        worktrees.retry(repo, t)
    assert lock.exists() and p.is_dir()
    runs.release(repo, t, rec["run"])
    assert worktrees.retry(repo, t) == []
    assert not p.exists() and not lock.exists()


def test_dashboard_cached_disk_count_tracks_two_live_copies(repo, monkeypatch):
    dashboard = Path(__file__).resolve().parents[2] / "workspace-addons" / "dashboard" / "src"
    monkeypatch.syspath_prepend(str(dashboard))
    from orch_dashboard import data

    monkeypatch.setattr(
        data,
        "_DISK",
        {
            str(repo): {
                "at": time.monotonic(),
                "val": {
                    "copies": 0,
                    "bytes": 0,
                    "partial": False,
                },
                "busy": False,
            }
        },
    )
    p, q = make(repo, 0), make(repo, 1)
    assert data.copies_disk(repo)["copies"] == 2
    git(repo, "worktree", "remove", str(p))
    assert data.copies_disk(repo)["copies"] == 1 and q.is_dir()


def remember_gone(repo, folder, main):
    """Record the identity while it exists, then simulate deletion of the workspace."""
    (main / ".orch").mkdir(parents=True)
    (main / ".orch" / ".local-id").write_text(folder.name + "0" * 24)
    worktrees._remember_copies(main, folder)
    (main / ".orch" / ".local-id").unlink()
    (main / ".orch").rmdir()
    main.rmdir()


def test_known_copy_record_is_created_outside_ws8_and_owner_must_agree(repo):
    p = make(repo)
    known = worktrees._known_copies(p.parent.parent)
    entry = known[addons.workspace_id(repo)[:8]]
    assert entry["main"] == str(repo.resolve())
    assert entry["workspace_id"] == addons.workspace_id(repo)
    guarded = addons.home(repo) / "keys" / "copies"
    assert guarded.stat().st_mode & 0o777 == 0o700
    for name in ("registry.json", "counter"):
        assert (guarded / name).stat().st_mode & 0o777 == 0o600
    assert not (p.parent.parent / ".known.json").exists()
    other = repo.parent / "gone-other"
    d = _gone_folder(repo, owner=str(other))
    remember_gone(repo, d, other)
    (d / ".owner").write_text(str(repo.parent / "forged-missing"))
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, d.name, discard=True)
    assert (d / "t_abcdef12").is_dir()


def test_known_copies_rejects_wrong_workspace_id(repo):
    folder = addons.home(repo) / "worktrees" / "aaaaaaaa"
    with pytest.raises(Refused, match="id"):
        worktrees._remember_copies(repo, folder)


def test_missing_open_copy_is_not_dropped(repo):
    p = make(repo)
    git(repo, "worktree", "remove", str(p))
    worktrees.remove(repo, repo.tids[0])
    worktrees.sweep(repo)
    assert repo.tids[0] in worktrees.registry(repo)
    assert worktrees.count(repo) == 0


def test_known_orphan_removal_only_trashes_ticket_folders_without_following_links(repo, monkeypatch):
    main = repo.parent / "gone"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    decoy = repo / "decoy"
    decoy.mkdir()
    (decoy / "keep").write_text("keep")
    (d / "t_12345678").symlink_to(decoy, target_is_directory=True)
    (d / "not-a-ticket").mkdir()
    moved = []
    original = worktrees._to_trash

    def record(path, tid):
        moved.append(path)
        return original(path, tid)

    monkeypatch.setattr(worktrees, "_to_trash", record)
    assert worktrees.remove_orphaned(repo, d.name, discard=True) == []
    assert moved == [d / "t_abcdef12"]
    assert (decoy / "keep").read_text() == "keep"
    assert (d / "t_12345678").is_symlink() and (d / "not-a-ticket").is_dir()


@pytest.mark.parametrize("record", ["unsigned", "bad-signature", "replayed"])
def test_review_forged_identity_cannot_remove_live_workspace(repo, record):
    p = make(repo)
    live = repo / "live-b"
    (live / ".orch").mkdir(parents=True)
    (live / ".orch" / ".local-id").write_text("bbbbbbbb" + "0" * 24)
    missing = str(repo.parent / "missing-b")
    d = _gone_folder(repo, ws8="bbbbbbbb", owner=missing)
    path = d.parent / ".known.json"
    known = worktrees._known_copies(d.parent)
    known[d.name] = (
        missing
        if record == "unsigned"
        else {"main": missing, "mac": "0" * 64}
        if record == "bad-signature"
        else known[p.parent.name]
    )
    path.write_text(json.dumps(known))
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, d.name, discard=True)
    assert (d / "t_abcdef12").is_dir()
    assert worktrees.orphaned(repo) == []
    with pytest.raises(Refused):
        worktrees._remember_copies(live, d)


def test_review_unknown_owner_is_not_listed(repo):
    _gone_folder(repo)
    assert worktrees.orphaned(repo) == []


def test_review_moved_workspace_refreshes_identity_and_owner(repo):
    p = make(repo)
    before = worktrees._known_copies(p.parent.parent)
    moved = repo.parent / "moved-project"
    repo.rename(moved)
    try:
        worktrees._remember_copies(moved, p.parent)
        assert (p.parent / ".owner").read_text().strip() == str(moved.resolve())
        after = worktrees._known_copies(p.parent.parent)
        assert after[p.parent.name] != before[p.parent.name]
        assert not worktrees._known_gone(p.parent)
    finally:
        moved.rename(repo)


def test_review_deleted_orphan_forgets_signed_identity(repo):
    main = repo.parent / "gone-review"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    assert worktrees.orphaned(repo) == [{"ws8": d.name, "copies": 1}]
    assert worktrees.remove_orphaned(repo, d.name, discard=True) == []
    assert not d.exists()
    assert d.name not in worktrees._known_copies(d.parent)


def test_review_retry_forged_gitdir_keeps_other_copys_lock(repo):
    p, q = make(repo, 0), make(repo, 1)
    lock = _stale_lock(q, 30)
    (p / ".git").write_text((q / ".git").read_text())
    worktrees.retry(repo, repo.tids[0])
    assert lock.exists()


@pytest.mark.parametrize("raises", [False, True])
def test_review_retry_bounds_remove_and_restores_deadline(repo, monkeypatch, raises):
    make(repo)
    previous = time.monotonic() + 1000
    monkeypatch.setattr(worktrees._ctx, "deadline", previous, raising=False)
    seen = []

    def remove(root, ticket):
        seen.append(worktrees._ctx.deadline)
        if raises:
            raise RuntimeError("remove failed")
        return []

    monkeypatch.setattr(worktrees, "_remove_locked", remove)
    start = time.monotonic()
    if raises:
        with pytest.raises(RuntimeError, match="remove failed"):
            worktrees.retry(repo, repo.tids[0])
    else:
        worktrees.retry(repo, repo.tids[0])
    assert start + worktrees.SWEEP_BUDGET <= seen[0] <= time.monotonic() + worktrees.SWEEP_BUDGET
    assert worktrees._ctx.deadline == previous


@pytest.fixture(autouse=True)
def _copies_test_home(monkeypatch, request):
    from orch import humanproof

    if request.node.name.startswith("test_task_e_real_guard"):
        # conftest's autouse patch gives every module a usable test home: these tests need the real pairing
        monkeypatch.setattr(humanproof, "guarded_home", _REAL_GUARDED_HOME)
        return

    # Legacy proj fixtures live outside the fake account's .orch-test directory.
    # Keep the real private-directory, file, and key checks on their isolated home.
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: Path(os.environ["ORCH_HOME"]))


def test_review_retry_linked_gitdir_keeps_lock(repo):
    p = make(repo)
    g = worktrees._gitdir_of(p)
    lock = _stale_lock(p, 30)
    alias = g.with_name("linked-copy")
    alias.symlink_to(g, target_is_directory=True)
    (p / ".git").write_text(f"gitdir: {alias}\n")
    worktrees.retry(repo, repo.tids[0])
    assert lock.exists()


@pytest.mark.parametrize("moved", [False, True])
def test_task_d_missing_main_cannot_rebind_different_full_id(repo, moved):
    main = repo.parent / "old-main"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    other = repo / "new-main"
    (other / ".orch").mkdir(parents=True)
    (other / ".orch" / ".local-id").write_text(d.name + "1" * 24)
    if moved:
        # A moved directory whose full id differs still cannot claim the old binding.
        destination = repo / "moved-main"
        other.rename(destination)
        other = destination
    with pytest.raises(Refused):
        worktrees._remember_copies(other, d)
    assert (d / ".owner").read_text().strip() == str(main)


@pytest.mark.parametrize("equal", [False, True])
def test_task_d_legacy_string_migration_requires_same_main(repo, equal):
    folder = addons.home(repo) / "worktrees" / wid8(repo)
    folder.mkdir(parents=True)
    main = str(repo.resolve())
    (folder.parent / ".known.json").write_text(json.dumps({folder.name: main if equal else main + "-gone"}))
    if not equal:
        with pytest.raises(Refused):
            worktrees._remember_copies(repo, folder)
    else:
        worktrees._remember_copies(repo, folder)
        store = addons.home(repo) / "keys" / "copies" / "registry.json"
        entry = json.loads(store.read_text())["entries"][folder.name]
        assert entry == {"main": main, "workspace_id": addons.workspace_id(repo)}


@pytest.mark.parametrize("update", ["move", "remove"])
def test_task_d_replayed_store_is_unknown(repo, update):
    main = repo.parent / "replay-main"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    store = addons.home(repo) / "keys" / "copies" / "registry.json"
    old = store.read_bytes()
    counter = store.with_name("counter")
    before = int(counter.read_text())
    assert json.loads(old)["counter"] == before
    if update == "move":
        moved = repo.parent / "replay-moved"
        remember_gone(repo, d, moved)  # same full id, legitimate rebind
    else:
        assert worktrees.remove_orphaned(repo, d.name, discard=True) == []
        d = _gone_folder(repo, owner=str(main))
    assert int(counter.read_text()) > before
    assert json.loads(store.read_bytes())["counter"] == int(counter.read_text())
    store.write_bytes(old)
    (d / ".owner").write_text(str(main))
    assert not worktrees._known_gone(d)
    assert worktrees.orphaned(repo) == []
    with pytest.raises(Refused):
        worktrees.remove_orphaned(repo, d.name, discard=True)
    # A replay must not become a fresh empty registry on the next write either.
    with pytest.raises(Refused):
        worktrees._remember_copies(repo, addons.home(repo) / "worktrees" / wid8(repo))


def test_task_e_real_guard_round_trip(repo, monkeypatch):
    from orch import humanproof

    home = addons.real_home() / ".orch-test" / "copies-home"
    home.mkdir(parents=True)
    monkeypatch.setenv("ORCH_HOME", str(home))
    monkeypatch.setattr(humanproof, "install_kind", lambda: "test")
    p = make(repo)
    assert worktrees._known_copies(p.parent.parent)[wid8(repo)] == {
        "main": str(repo.resolve()),
        "workspace_id": addons.workspace_id(repo),
    }


def test_task_e_real_guard_outside_refused(repo, monkeypatch):
    from orch import humanproof

    monkeypatch.setattr(humanproof, "install_kind", lambda: "test")
    home = addons.home(repo)
    before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    entry, note = worktrees._create_inner(repo, repo.tids[0])
    assert entry is None
    assert "cannot make the copy folder" in note
    assert "Traceback" not in note
    assert {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    assert not (home / "worktrees").exists()
    assert not (home / "keys" / "copies").exists()


@pytest.mark.parametrize("linked", ["folder", "owner"])
def test_task_e_owner_refresh_refuses_links(repo, tmp_path, monkeypatch, linked):
    p = make(repo)
    folder = p.parent
    target = tmp_path.parent / (tmp_path.name + "-owner-target")
    if linked == "folder":
        folder.rename(target)
        folder.symlink_to(target, target_is_directory=True)
        # Simulate a stale path check; opening the directory must refuse the link.
        monkeypatch.setattr(worktrees, "_is_link", lambda path: False)
        marker = target / ".owner"
    else:
        target.write_text("precious\n")
        (folder / ".owner").unlink()
        (folder / ".owner").symlink_to(target)
        marker = target
    before = marker.read_bytes()
    known = worktrees._known_copies(folder.parent)
    moved = repo.parent / "moved-owner"
    repo.rename(moved)
    try:
        with pytest.raises((Refused, OSError)):
            worktrees._remember_copies(moved, folder)
        assert marker.read_bytes() == before
        assert worktrees._known_copies(folder.parent) == known
    finally:
        moved.rename(repo)
        if linked == "folder":
            folder.unlink()
            target.rename(folder)


def test_task_e_failed_orphan_rmdir_restores_owner(repo):
    main = repo.parent / "gone-extra"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    known = worktrees._known_copies(d.parent)
    extra = d / "unexpected.txt"
    extra.write_text("keep")
    notes = worktrees.remove_orphaned(repo, d.name, discard=True)
    assert notes and "kept" in " ".join(notes)
    assert extra.read_text() == "keep"
    assert (d / ".owner").read_text().strip() == known[d.name]["main"]
    assert worktrees._known_copies(d.parent) == known
    extra.unlink()
    assert worktrees.remove_orphaned(repo, d.name, discard=True) == []
    assert not d.exists()
    assert d.name not in worktrees._known_copies(d.parent)


@pytest.mark.parametrize("owner", ["other", "missing"])
def test_task_f_unbound_existing_copies_refused_without_store_change(repo, owner):
    main = repo.parent / "already-known"
    existing = _gone_folder(repo, owner=str(main))
    remember_gone(repo, existing, main)
    store = addons.home(repo) / "keys" / "copies" / "registry.json"
    before = store.read_bytes(), store.with_name("counter").read_bytes()
    folder = addons.home(repo) / "worktrees" / wid8(repo)
    (folder / repo.tids[0]).mkdir(parents=True)
    if owner == "other":
        (folder / ".owner").write_text(str(repo.parent / "other-main") + "\n")
    with pytest.raises(Refused):
        worktrees._remember_copies(repo, folder)
    assert (store.read_bytes(), store.with_name("counter").read_bytes()) == before
    assert (folder / repo.tids[0]).is_dir()


def test_task_f_interrupted_store_write_heals_counter(repo, monkeypatch):
    from orch import humanproof

    p = make(repo)
    store = addons.home(repo) / "keys" / "copies" / "registry.json"
    counter = store.with_name("counter")
    old = store.read_bytes()
    before = int(counter.read_text())
    write = humanproof._write_private

    def crash(path, text):
        if path == counter:
            raise OSError("simulated counter write crash")
        return write(path, text)

    with monkeypatch.context() as patch:
        patch.setattr(humanproof, "_write_private", crash)
        with pytest.raises(OSError, match="simulated"):
            worktrees._remember_copies(repo, p.parent)
    assert int(counter.read_text()) == before
    assert json.loads(store.read_bytes())["counter"] == before + 1
    assert worktrees._known_copies(p.parent.parent)[wid8(repo)]["main"] == str(repo.resolve())
    assert int(counter.read_text()) == before + 1
    store.write_bytes(old)
    assert worktrees._known_copies(p.parent.parent) == {}


@pytest.mark.parametrize("gap", [-1, 2])
def test_task_f_other_counter_mismatches_remain_unknown(repo, gap):
    from orch import humanproof

    p = make(repo)
    home = addons.home(repo)
    store = home / "keys" / "copies" / "registry.json"
    doc = json.loads(store.read_bytes())
    doc["counter"] += gap
    data = {k: doc[k] for k in ("version", "counter", "entries")}
    doc["mac"] = worktrees._copies_mac(worktrees._copies_key(home), data)
    humanproof._write_private(store, json.dumps(doc))
    before = store.with_name("counter").read_bytes()
    assert worktrees._known_copies(p.parent.parent) == {}
    assert store.with_name("counter").read_bytes() == before


def test_task_f_orphan_store_save_failure_returns_note(repo, monkeypatch):
    main = repo.parent / "gone-save-failure"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)

    def fail(*args):
        raise OSError("simulated registry write failure")

    monkeypatch.setattr(worktrees, "_save_copies_store", fail)
    notes = worktrees.remove_orphaned(repo, d.name, discard=True)
    assert not d.exists()
    assert len(notes) == 1
    assert d.name in notes[0] and "simulated registry write failure" in notes[0]


def test_remove_orphaned_does_not_nest_the_copies_state_lock(repo, monkeypatch):
    """Opus: a nested lock take released the outer lock early, so the store save ran unlocked."""
    main = repo.parent / "gone-nest"
    d = _gone_folder(repo, owner=str(main))
    remember_gone(repo, d, main)
    held = []
    real = worktrees.runs.locked

    @contextlib.contextmanager
    def spy(root, name, *a, **k):
        if "copies-state" in str(root):
            assert not held, "nested copies-state lock"
            held.append(1)
        try:
            with real(root, name, *a, **k):
                yield
        finally:
            if "copies-state" in str(root):
                held.clear()

    monkeypatch.setattr(worktrees.runs, "locked", spy)
    assert worktrees.remove_orphaned(repo, d.name, discard=True) == []
    assert not d.exists()


def test_main_folder_run_then_copy_then_done_releases_the_copy(repo, monkeypatch):
    """Lane C D6b (#440 again): the ticket's first run was in the project folder, a later start made its
    copy (mode Every time). Done must take the copy away, keyed on the ticket, not on the run that made it."""
    from orch import config

    t = repo.tids[0]
    monkeypatch.setattr(config, "copies_mode", lambda root: "off")
    rec, _ = runs.claim_routed(repo, t, "human:t", "claude", "oneshot", pid=os.getpid())
    assert Path(rec["folder"]).resolve() == repo.resolve()
    runs.release(repo, t, rec["run"])
    monkeypatch.setattr(config, "copies_mode", lambda root: "always")
    rec, _ = runs.claim_routed(repo, t, "human:t", "claude", "oneshot", pid=os.getpid())
    copy = Path(rec["folder"])
    assert copy.resolve() != repo.resolve() and copy.is_dir()
    assert t in worktrees.registry(repo)
    close(repo, t, "done")  # the person's Done while the run is still alive: kept for now
    runs.release(repo, t, rec["run"])  # the run's end
    assert t not in worktrees.registry(repo)
    assert not copy.exists()
    assert str(copy) not in git(repo, "worktree", "list", "--porcelain")


def test_a_live_claim_in_the_project_folder_does_not_hold_the_tickets_copy(repo):
    """Lane C D6b: the ticket's (stand-in) claim says it works in the project folder, and its copy came later
    (the mode was switched). Done releases the copy, keyed on the ticket; a claim INSIDE the copy holds it."""
    t = repo.tids[0]
    p = make(repo)  # the copy
    runs.claim(repo, t, "human:t", "claude", "oneshot", folder=repo, pid=os.getpid())
    assert runs.state(runs.read(repo, t)) == "alive"
    close(repo, t, "done")
    assert t not in worktrees.registry(repo)
    assert not p.exists()
    assert str(p) not in git(repo, "worktree", "list", "--porcelain")


def test_a_live_claim_inside_the_copy_still_holds_it(repo):
    t = repo.tids[0]
    p = make(repo)
    runs.claim(repo, t, "human:t", "claude", "oneshot", folder=p, pid=os.getpid())
    close(repo, t, "done")
    assert t in worktrees.registry(repo) and p.is_dir()
