"""B12: copies are always taken back (remove, sweep, pending list, branches, agent traces). DATA-LOSS CLASS:
the decoy tests prove that nothing but this workspace's own, exactly-named copies is ever deleted."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from orch import addons, harness, runs, tickets, worktrees
from orch.errors import Refused

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX permissions and links")


def git(cwd, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    if check:
        assert p.returncode == 0, p.stderr
    return p.stdout.strip()


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
    worktrees.remove(repo, t)
    assert p.is_dir() and (p / "code.py").is_file()
    assert t in worktrees.registry(repo)  # kept: it is retried when the owner is right again


def test_owner_that_is_a_link_is_not_deleted(repo, tmp_path):
    p = make(repo, 0)
    real = tmp_path / "ownerfile"
    real.write_text(str(repo.resolve()) + "\n")
    (p.parent / ".owner").unlink()
    (p.parent / ".owner").symlink_to(real)
    worktrees.remove(repo, repo.tids[0])
    assert p.is_dir()


def test_a_symlinked_copy_folder_is_refused_and_its_target_kept(repo, tmp_path):
    t = repo.tids[0]
    p = make(repo, 0)
    git(repo, "worktree", "remove", "--force", str(p))
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep")
    p.symlink_to(target)
    worktrees.remove(repo, t)
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


def test_clean_copy_is_removed_with_folder_registry_and_merged_branch(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    assert f"orch/{t}" in branches(repo)
    assert worktrees.remove(repo, t) == []
    assert not p.exists()
    assert t not in worktrees.registry(repo)
    assert f"orch/{t}" not in branches(repo)  # nothing on it: merged into HEAD, `branch -d` succeeds
    assert "worktree" not in git(repo, "worktree", "list").replace(str(repo), "")  # git forgot it


def test_dirty_copy_is_committed_to_its_branch_first(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "code.py").write_text("print(2)\n")  # modified
    (p / "new.txt").write_text("new\n")  # untracked
    assert worktrees.remove(repo, t) == []
    assert not p.exists()
    assert t not in worktrees.registry(repo)
    assert git(repo, "show", f"orch/{t}:new.txt") == "new"
    assert git(repo, "show", f"orch/{t}:code.py") == "print(2)"
    assert git(repo, "log", "-1", "--format=%an <%ae>", f"orch/{t}") == "orch <orch@localhost>"
    # unmerged: the branch stays, on the pending list, with the day it started
    assert [b["ticket"] for b in pending(repo)["branches"]] == [t]
    assert git(repo, "status", "--porcelain") == ""  # the project itself is untouched


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
    assert worktrees.remove(repo, t) == []
    assert not marker.exists()
    assert git(repo, "show", f"orch/{t}:x.txt") == "x"


def test_a_copy_whose_changes_cannot_be_saved_is_kept(repo, monkeypatch):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "mine.txt").write_text("unsaved")
    monkeypatch.setattr(worktrees, "_save_leftovers", lambda *a: False)
    notes = worktrees.remove(repo, t)
    assert p.is_dir() and (p / "mine.txt").read_text() == "unsaved"
    assert t in worktrees.registry(repo)
    assert any("could not be saved" in n for n in notes)


def test_a_copy_with_a_live_run_is_not_removed(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    runs.claim(repo, t, "human:test", "claude", "oneshot", folder=p)
    notes = worktrees.remove(repo, t)
    assert p.is_dir() and notes and "still working" in notes[0]
    worktrees.sweep(repo)
    close(repo, t)
    assert p.is_dir()  # the closing hook and the sweep both leave a copy a run is in


def test_a_folder_that_is_not_a_worktree_of_ours_gets_no_git_commands(repo, monkeypatch):
    """A copy folder whose .git belongs to another repository: no status, no add, no commit there."""
    t = repo.tids[0]
    p = make(repo, 0)
    git(repo, "worktree", "remove", "--force", str(p))
    p.mkdir()
    other = p
    git(other, "init", "-q")
    (other / "work.txt").write_text("w")
    seen = []
    real = worktrees._git

    def spy(args, cwd, *a, **k):
        seen.append((args[0], str(cwd)))
        return real(args, cwd, *a, **k)

    monkeypatch.setattr(worktrees, "_git", spy)
    worktrees.remove(repo, t)
    assert not [s for s in seen if s[1] == str(p) and s[0] in ("add", "commit")]
    assert not p.exists()  # plain folder, passes both checks: deleted as a plain folder


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


def test_sweep_removes_orphan_folders_of_this_workspace_only(repo):
    mine = make(repo, 0)
    worktrees._save_registry(repo, {})  # the registry lost it: an orphan, still a worktree of ours
    plain = mine.parent / "t_plain0001"  # an orphan that is just a folder
    plain.mkdir()
    (plain / "f.txt").write_text("x")
    other = mine.parent / "not-a-ticket"  # not ticket-named: not ours to judge
    other.mkdir()
    worktrees.sweep(repo)
    assert not mine.exists() and not plain.exists()
    assert other.is_dir()
    assert (mine.parent / ".owner").is_file()


def test_orphans_are_left_when_the_owner_is_not_this_workspace(repo):
    mine = make(repo, 0)
    worktrees._save_registry(repo, {})
    (mine.parent / ".owner").write_text("/not/mine\n")
    worktrees.sweep(repo)
    assert mine.is_dir()


def _old(path, days):
    t = time.time() - days * 86400
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t), follow_symlinks=False)


def _gone_folder(repo, ws8="aaaaaaaa", owner="/nonexistent/workspace", old=True):
    d = addons.home(repo) / "worktrees" / ws8
    (d / "t_abcdef12" / "sub").mkdir(parents=True)
    (d / "t_abcdef12" / "sub" / "f.txt").write_text("x")
    (d / ".owner").write_text(owner + "\n")
    if old:
        _old(d, 30)
    return d


def test_a_gone_workspaces_folder_is_removed_after_it_was_idle(repo):
    d = _gone_folder(repo)
    worktrees.sweep(repo)
    assert not d.exists()


def test_a_gone_workspace_that_was_just_active_is_kept(repo):
    d = _gone_folder(repo, old=False)
    worktrees.sweep(repo)
    assert (d / "t_abcdef12" / "sub" / "f.txt").is_file()


def test_an_id_mismatch_counts_as_gone(repo, tmp_path):
    other = tmp_path / "otherws"
    (other / ".orch").mkdir(parents=True)
    (other / ".orch" / ".local-id").write_text("f" * 32 + "\n")
    d = _gone_folder(repo, ws8="aaaaaaaa", owner=str(other))
    worktrees.sweep(repo)
    assert not d.exists()


def test_a_living_workspaces_folder_is_never_touched(repo, tmp_path):
    other = tmp_path / "otherws"
    (other / ".orch").mkdir(parents=True)
    (other / ".orch" / ".local-id").write_text("aaaaaaaa" + "0" * 24 + "\n")
    d = _gone_folder(repo, ws8="aaaaaaaa", owner=str(other))
    worktrees.sweep(repo)
    assert (d / "t_abcdef12" / "sub" / "f.txt").is_file()


def test_gone_folders_without_owner_or_with_strangers_are_left(repo):
    d = _gone_folder(repo, ws8="bbbbbbbb")
    (d / ".owner").unlink()
    e = _gone_folder(repo, ws8="cccccccc")
    (e / "notes.txt").write_text("a person's file")
    f = addons.home(repo) / "worktrees" / "not-hex"
    f.mkdir()
    (f / ".owner").write_text("/nonexistent\n")
    worktrees.sweep(repo)
    assert d.is_dir() and (e / "notes.txt").is_file() and f.is_dir()


# ---------------------------------------------------------------- locked leftovers: pending, then delete


def test_a_leftover_folder_goes_on_the_pending_list_and_is_deleted_next_sweep(repo, monkeypatch):
    t = repo.tids[0]
    p = make(repo, 0)
    real = worktrees._git

    def lock_it(args, cwd, *a, **k):
        if args[:2] == ["worktree", "remove"]:  # Windows: unregistered, folder stays (a locked file)
            real(["worktree", "prune"], cwd, filters=False) if False else None
            return 0, "", ""
        return real(args, cwd, *a, **k)

    monkeypatch.setattr(worktrees, "_git", lock_it)
    real_rm = worktrees.rmtree_nofollow
    monkeypatch.setattr(worktrees, "rmtree_nofollow", lambda top: False)
    notes = worktrees.remove(repo, t)
    assert p.is_dir() and any("try again" in n for n in notes)
    assert t not in worktrees.registry(repo)
    assert [i["path"] for i in pending(repo)["folders"]] == [str(p)]
    monkeypatch.setattr(worktrees, "rmtree_nofollow", real_rm)
    monkeypatch.setattr(worktrees, "_git", real)
    worktrees.sweep(repo)
    assert not p.exists()
    assert pending(repo)["folders"] == []


def test_a_pending_path_that_fails_the_checks_is_dropped_untouched(repo, tmp_path):
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "keep.txt").write_text("keep")
    worktrees._save_pending(
        repo,
        {
            "folders": [{"ticket": repo.tids[0], "path": str(decoy), "removed_at": tickets.now()}],
            "branches": [],
        },
    )
    worktrees.sweep(repo)
    assert (decoy / "keep.txt").read_text() == "keep"
    assert pending(repo)["folders"] == []


# ---------------------------------------------------------------- branches


def test_unmerged_branch_is_kept_until_14_days_then_deleted_by_the_sweep(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    worktrees.remove(repo, t)
    assert f"orch/{t}" in branches(repo)
    worktrees.sweep(repo)
    assert f"orch/{t}" in branches(repo)  # fresh: kept
    doc = pending(repo)
    doc["branches"][0]["removed_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 15 * 86400)
    )
    worktrees._save_pending(repo, doc)
    worktrees.sweep(repo)
    assert f"orch/{t}" not in branches(repo)
    assert pending(repo)["branches"] == []


def test_a_branch_that_gets_merged_later_goes_at_the_next_sweep(repo):
    t = repo.tids[0]
    p = make(repo, 0)
    (p / "w.txt").write_text("work")
    worktrees.remove(repo, t)
    git(repo, "merge", "--no-ff", "-q", "-m", "bring back", f"orch/{t}")
    worktrees.sweep(repo)
    assert f"orch/{t}" not in branches(repo)


def test_other_branches_are_never_deleted(repo):
    git(repo, "branch", "feature/mine")
    git(repo, "branch", "orch/not-a-ticket")
    t = repo.tids[0]
    make(repo, 0)
    worktrees.remove(repo, t)
    worktrees.sweep(repo)
    assert "feature/mine" in git(repo, "branch", "--list") and "orch/not-a-ticket" in git(
        repo, "branch", "--list"
    )


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
    assert worktrees.remove(repo, t) == []
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
    worktrees.remove(repo, t)
    assert cj.read_text() == "{ not json"


def test_a_linked_claude_json_is_left_untouched(repo, tmp_path):
    t = repo.tids[0]
    p = make(repo, 0)
    cfg, cj, projects = _claude_files(repo)
    real = tmp_path / "real-claude.json"
    body = json.dumps({"projects": {str(p.resolve()): {"hasTrustDialogAccepted": True}}})
    real.write_text(body)
    cj.symlink_to(real)
    worktrees.remove(repo, t)
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
    monkeypatch.undo()


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
    monkeypatch.setattr(worktrees, "sweep", lambda root, budget=0: calls.append(("sweep", budget)) or [])
    with pytest.raises(Refused):
        runs.start(repo, repo.tids[0], "human:t", agent="no-such-agent")
    assert calls == [("sweep", worktrees.START_SWEEP_BUDGET)]
    monkeypatch.setattr(services, "start", lambda root: [])
    args = type("A", (), {"cmd": "start", "print_launch_url": False, "json": True, "no_open": True})()
    cli_status._services_cmd(args, repo)
    assert len(calls) == 2
