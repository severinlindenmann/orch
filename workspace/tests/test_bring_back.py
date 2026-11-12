"""B13 prerequisites: special attributes must be inspected before any merge."""

import hashlib
import subprocess

import pytest
from test_worktrees_cleanup import git, make
from test_worktrees_cleanup import repo as repo_fixture

from orch import humanproof, tickets, worktrees

_REAL_PERSON_BY = humanproof.person_by

repo = repo_fixture


def test_special_attributes_can_be_checked_without_running_filters(proj):
    subprocess.run(["git", "init", "-q", str(proj)], check=True, capture_output=True)
    attributes = proj / ".gitattributes"
    attributes.write_text("payload filter=lfs\n", encoding="utf-8")
    payload = proj / "payload"
    payload.write_bytes(b"local bytes must survive\n")
    paths = (attributes, payload)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    rc, out, reason = worktrees._git(
        ["check-attr", "-z", "filter", "eol", "working-tree-encoding", "--", "payload"],
        proj,
        read_only=True,
        filters=False,  # Inspect actual attributes, not safegit's empty attribute tree.
        strip=False,
    )

    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before
    assert rc == 0, reason
    assert "payload\0filter\0lfs\0" in out


@pytest.fixture
def done_copy(repo, monkeypatch):
    monkeypatch.setenv("ORCH_NO_DETACHED_CLEAN", "1")
    copy = make(repo)
    (copy / "code.py").write_text("print(2)\n")
    return repo, repo.tids[0], copy


def to_review(root, tid):
    """The agent commits its work in the copy (when it can: a copy in the middle of a git operation or on
    another branch stays as it is) and hands the ticket to Review with its run over. Entering Review records
    the tip the person looks at (B13f)."""
    copy = worktrees._want(root, tid)
    if copy is not None and copy.is_dir():
        worktrees._save_leftovers(copy, tid)
    tickets.set_status(root, tid, "review", "human:test")


def done_and_sweep(root, tid):
    """Review, a person's Done, then the detached sweep it schedules (run here in the test's own process)."""
    if tickets.load(root, tid)["status"] != "review":
        to_review(root, tid)
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    worktrees.sweep(root)


def test_clean_merge(done_copy):
    root, tid, copy = done_copy
    done_and_sweep(root, tid)
    assert (root / "code.py").read_text() == "print(2)\n"
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert not copy.exists()
    assert not git(root, "branch", "--list", f"orch/{tid}")


def test_dirty_overlap_keeps_bytes(done_copy):
    root, tid, copy = done_copy
    (root / "code.py").write_bytes(b"person's uncommitted bytes\n")
    before = hashlib.sha256((root / "code.py").read_bytes()).hexdigest()
    done_and_sweep(root, tid)
    assert hashlib.sha256((root / "code.py").read_bytes()).hexdigest() == before
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "waiting"
    assert copy.exists()


def project_hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
        and ".git" not in p.relative_to(root).parts
        and ".orch" not in p.relative_to(root).parts
    }


def finish(root, tid):
    done_and_sweep(root, tid)
    return tickets.load(root, tid)["work"]["bring_back"]


def assert_waiting_unchanged(root, tid, copy, before):
    assert finish(root, tid)["state"] == "waiting"
    assert project_hashes(root) == before
    assert copy.exists()
    assert git(root, "branch", "--list", f"orch/{tid}")


def test_none(repo):
    copy = make(repo)
    assert finish(repo, repo.tids[0])["state"] == "none"
    assert not copy.exists()


def test_unrelated_dirty(done_copy):
    root, tid, copy = done_copy
    (root / "personal").write_bytes(b"keep me")
    before = hashlib.sha256((root / "personal").read_bytes()).hexdigest()
    assert finish(root, tid)["state"] == "merged"
    assert hashlib.sha256((root / "personal").read_bytes()).hexdigest() == before


def test_conflict_aborts(done_copy):
    root, tid, copy = done_copy
    (root / "code.py").write_text("main changed\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    before = project_hashes(root)
    head = git(root, "rev-parse", "HEAD")
    assert_waiting_unchanged(root, tid, copy, before)
    assert git(root, "rev-parse", "HEAD") == head
    assert not (root / ".git/MERGE_HEAD").exists()


@pytest.mark.parametrize("mode", ["ignored", "untracked_directory", "case", "staged", "rename"])
def test_overlap_variants(done_copy, mode):
    root, tid, copy = done_copy
    if mode == "ignored":
        (root / ".git/info/exclude").write_text("private\n")
        (root / "private").write_bytes(b"precious ignored data")
        (copy / "private").write_text("incoming")
        git(copy, "add", "-f", "private")
    elif mode == "untracked_directory":
        (root / "dir").mkdir()
        (root / "dir/local").write_bytes(b"personal")
        (copy / "dir").write_text("file replacing directory")
    elif mode == "case":
        (root / "CODE.PY").write_text("personal")
    elif mode == "staged":
        (root / "code.py").write_text("staged")
        git(root, "add", "code.py")
    else:
        git(copy, "mv", "code.py", "renamed.py")
        (root / "renamed.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))


@pytest.mark.parametrize(
    "mode",
    [
        "detached",
        "another_branch",
        "merge",
        "wrong_copy_branch",
        "active_copy",
        "active_main",
        "special_attributes",
        "decoy",
    ],
)
def test_preconditions(done_copy, mode, monkeypatch):
    root, tid, copy = done_copy
    if mode == "detached":
        git(root, "checkout", "--detach")
    elif mode == "another_branch":
        git(root, "checkout", "--orphan", "other")
        git(root, "commit", "-qm", "unrelated history")
    elif mode == "merge":
        (root / ".git/MERGE_HEAD").write_text(git(root, "rev-parse", "HEAD") + "\n")
    elif mode == "wrong_copy_branch":
        git(copy, "checkout", "-b", "other")
    elif mode == "active_copy":
        monkeypatch.setattr(worktrees, "_alive_here", lambda *a: {"running": True})
    elif mode == "active_main":
        from orch import runs

        runs._atomic(runs.record_path(root, root.tids[1]), "{}")
        monkeypatch.setattr(runs, "read", lambda r, t: {"ticket": t} if t == root.tids[1] else None)
        monkeypatch.setattr(runs, "state", lambda r: "alive")
        monkeypatch.setattr(runs, "workdir_for", lambda *a: root)
    elif mode == "special_attributes":
        (root / ".gitattributes").write_text("code.py filter=lfs\n")
    else:
        git(root, "worktree", "remove", "--force", str(copy))
        copy.mkdir()
        (copy / "precious").write_text("not a worktree")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))


def test_crash_after_merge_before_record(done_copy, monkeypatch):
    root, tid, copy = done_copy
    real = worktrees._bb_state

    def crash(r, t, state, *a, **kw):
        if state == "merged":
            raise RuntimeError("simulated crash")
        return real(r, t, state, *a, **kw)

    monkeypatch.setattr(worktrees, "_bb_state", crash)
    done_and_sweep(root, tid)
    assert (root / "code.py").read_text() == "print(2)\n"
    monkeypatch.setattr(worktrees, "_bb_state", real)
    worktrees.on_run_ended(root, tid)
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert not copy.exists()


def test_branch_moved_uses_resolved_sha(done_copy, monkeypatch):
    root, tid, copy = done_copy
    real = worktrees._bb_merge
    attempted = []

    def move(top, args):
        if "--no-ff" in args:
            attempted.append(args[-1])
            git(copy, "commit", "--allow-empty", "-qm", "new work")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", move)
    finish(root, tid)
    assert git(root, "rev-parse", "HEAD^2") == attempted[0]
    assert copy.exists()  # new branch tip is not saved in main
    assert worktrees._unmerged_done_work(root, tid)


def test_main_changed_before_merge(done_copy, monkeypatch):
    root, tid, copy = done_copy
    real = worktrees._bb_snapshot
    n = 0
    before = project_hashes(root)

    def race(top):
        nonlocal n
        result = real(top)
        n += 1
        if n == 2:
            result["head"] = "0" * 40
        return result

    monkeypatch.setattr(worktrees, "_bb_snapshot", race)
    assert_waiting_unchanged(root, tid, copy, before)


def half_merge(root, args):
    """What a git killed between writing the files and committing leaves behind: orch's merge (same
    message, same tip) with MERGE_HEAD, ORIG_HEAD and the touched files written, no commit."""
    message = args[args.index("-m") + 1]
    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "-m", message, args[-1]],
        cwd=root,
        capture_output=True,
        check=True,
    )


def test_journal_recovery(done_copy, monkeypatch):
    root, tid, copy = done_copy
    real = worktrees._bb_merge

    def crash(top, args):
        if "--no-ff" in args:
            half_merge(top, args)
            raise RuntimeError("killed in the middle of the merge")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", crash)
    to_review(root, tid)
    before = project_hashes(root)
    head = git(root, "rev-parse", "HEAD")
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    worktrees._record_done_tip(root, tid)
    with pytest.raises(RuntimeError):
        worktrees.bring_back(root, tid)
    assert (root / ".git/MERGE_HEAD").exists()
    assert worktrees._copy_authority(root, tid)["journal"]["tip"] == git(root, "rev-parse", "MERGE_HEAD")
    monkeypatch.setattr(worktrees, "_bb_merge", real)
    # The signed journal proves the merge is orch's own: it is undone, then the bring-back runs again.
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "merged", result
    assert git(root, "rev-parse", "HEAD^1") == head
    assert (root / "code.py").read_text() == "print(2)\n"
    assert set(project_hashes(root)) == set(before)
    assert not worktrees._copy_authority(root, tid).get("journal")


def test_autostash_disabled(done_copy):
    root, tid, copy = done_copy
    git(root, "config", "merge.autoStash", "true")
    (root / "code.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    assert not git(root, "stash", "list")


def test_hostile_repo_never_executes_code(done_copy):
    root, tid, copy = done_copy
    sentinel = root.parent / "executed"
    hook = root / ".git/hooks/pre-merge-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
    hook.chmod(0o755)
    git(root, "config", "filter.evil.clean", f"touch '{sentinel}'")
    git(root, "config", "filter.evil.smudge", f"touch '{sentinel}'")
    git(root, "config", "merge.evil.driver", f"touch '{sentinel}'")
    assert finish(root, tid)["state"] == "merged"
    assert not sentinel.exists()


def test_vanished_copy_branch_retained_and_retried(done_copy, monkeypatch):
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    git(root, "worktree", "remove", "--force", str(copy))
    monkeypatch.setattr(worktrees, "_tip_age_days", lambda *a: 100)
    before = project_hashes(root)
    worktrees.sweep(root)
    assert project_hashes(root) == before
    assert worktrees.registry(root).get(tid)
    assert git(root, "branch", "--list", f"orch/{tid}")
    assert not worktrees._delete_branch(root, tid, force=True)
    (root / "code.py").write_text("print(1)\n")
    worktrees.sweep(root)
    assert (root / "code.py").read_text() == "print(2)\n"
    assert not git(root, "branch", "--list", f"orch/{tid}")


def test_dropped_waiting_retains_need(done_copy):
    from orch import needs

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    tickets.set_status(root, tid, "dropped", "human:test", proven=True)
    worktrees.sweep(root)
    assert copy.exists()
    assert not worktrees._delete_branch(root, tid, force=True)
    assert any(row["kind"] == "copies:bring-back" for row in needs.core_rows(root))


def test_dropped_does_not_merge(done_copy):
    root, tid, copy = done_copy
    before = project_hashes(root)
    tickets.set_status(root, tid, "dropped", "human:test", proven=True)
    assert project_hashes(root) == before
    assert not copy.exists()
    assert git(root, "branch", "--list", f"orch/{tid}")


def test_dropped_empty_removes(repo):
    copy = make(repo)
    tid = repo.tids[0]
    tickets.set_status(repo, tid, "dropped", "human:test", proven=True)
    assert not copy.exists()
    assert not git(repo, "branch", "--list", f"orch/{tid}")


def test_need_appears_and_clears(done_copy):
    from orch import needs

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    finish(root, tid)
    assert any(row["kind"] == "copies:bring-back" for row in needs.core_rows(root))
    (root / "code.py").write_text("print(1)\n")
    worktrees.on_run_ended(root, tid)
    worktrees.sweep(root)
    assert not any(row["kind"] == "copies:bring-back" for row in needs.core_rows(root))


def test_ask_update_and_copy_update(done_copy, monkeypatch):
    from orch import runs_live

    root, tid, copy = done_copy
    (root / "other").write_text("main addition")
    git(root, "add", "other")
    git(root, "commit", "-qm", "main advances")
    sent = []
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: True)
    monkeypatch.setattr(
        runs_live, "send", lambda r, t, by, text: sent.append(text) or {"delivered": 1, "state": "idle"}
    )
    worktrees.ask_update(root, tid)
    assert f"orch copy update {tid}" in sent[0]
    before = project_hashes(root)
    monkeypatch.chdir(copy)
    worktrees.update_copy(root, tid)
    assert project_hashes(root) == before
    assert (copy / "other").read_text() == "main addition"
    assert finish(root, tid)["state"] == "merged"


def test_no_session_plain_refusal(done_copy, monkeypatch):
    from orch import runs_live
    from orch.errors import Refused

    root, tid, copy = done_copy
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: False)
    before = project_hashes(root)
    with pytest.raises(Refused, match="start the agent again"):
        worktrees.ask_update(root, tid)
    assert project_hashes(root) == before


def test_small_sweep_budget_never_starts_merge(done_copy, monkeypatch):
    root, tid, copy = done_copy
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    before = project_hashes(root)
    worktrees.sweep(root, budget=20)
    assert project_hashes(root) == before
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "waiting"
    assert copy.exists()


def test_contract_example(validate):
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "contracts/examples/ticket/valid-bring-back.json"
    validate(json.loads(path.read_text()))


def test_branch_only_without_registry(done_copy, monkeypatch):
    root, tid, copy = done_copy
    entry = worktrees.registry(root)[tid]["paths"][0]
    worktrees._record_on_ticket(root, tid, entry)
    assert worktrees._save_leftovers(copy, tid)[0]
    git(root, "worktree", "remove", "--force", str(copy))
    worktrees._save_registry(root, {})
    to_review(root, tid)  # the branch alone is what the person reviews
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    worktrees._record_done_tip(root, tid)
    worktrees.sweep(root)
    assert (root / "code.py").read_text() == "print(2)\n"
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert not git(root, "branch", "--list", f"orch/{tid}")


def test_failure_after_successful_merge_keeps_copy(done_copy, monkeypatch):
    root, tid, copy = done_copy
    real = worktrees._bb_snapshot
    n = 0

    def raced(top):
        nonlocal n
        n += 1
        snap = real(top)
        if n == 3:
            snap["files"]["external-change"] = "different"
        return snap

    monkeypatch.setattr(worktrees, "_bb_snapshot", raced)
    assert finish(root, tid)["state"] == "waiting"
    assert copy.exists()
    assert git(root, "branch", "--list", f"orch/{tid}")


def test_journal_for_foreign_merge_never_aborts(done_copy):
    import json

    root, tid, copy = done_copy
    head = git(root, "rev-parse", "HEAD")
    (root / ".git/MERGE_HEAD").write_text(head + "\n")
    journal = root / ".orch/run/bringback" / f"{tid}.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"tip_sha": "0" * 40}))
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    assert (root / ".git/MERGE_HEAD").read_text() == head + "\n"


def test_deleted_waiting_ticket_keeps_branch_and_need(done_copy):
    from orch import needs

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    tickets.ticket_path(root, tid).unlink()
    before = project_hashes(root)
    worktrees.sweep(root)
    assert project_hashes(root) == before
    assert copy.exists()
    assert not worktrees._delete_branch(root, tid, force=True)
    assert any(r["ticket"] == tid and r["kind"] == "copies:bring-back" for r in needs.core_rows(root))


def test_unreadable_git_never_authorizes_force_delete(done_copy, monkeypatch):
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    finish(root, tid)
    before = project_hashes(root)
    monkeypatch.setattr(worktrees, "_git", lambda *a, **kw: (128, "", "unreadable"))
    assert worktrees._unmerged_done_work(root, tid)
    assert not worktrees._delete_branch(root, tid, force=True)
    assert project_hashes(root) == before


def test_merge_timeout_ignores_sweep_deadline(repo, monkeypatch):
    import time

    seen = []
    monkeypatch.setattr(
        worktrees.safegit, "run", lambda args, cwd, timeout, **kw: seen.append(timeout) or (0, "", "")
    )
    before = getattr(worktrees._ctx, "deadline", None)
    try:
        worktrees._ctx.deadline = time.monotonic() + 1
        worktrees._bb_merge(repo, ["merge", "--abort"])
        assert seen == [worktrees.BRING_BACK_TIMEOUT]
        assert worktrees.BRING_BACK_TIMEOUT is None  # never killed in the middle of a merge
    finally:
        worktrees._ctx.deadline = before


def test_update_leaves_conflicts_only_in_copy(done_copy, monkeypatch):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    (root / "code.py").write_text("different main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main changed")
    before = project_hashes(root)
    monkeypatch.chdir(copy)
    assert "Resolve the conflicts" in worktrees.update_copy(root, tid)
    assert project_hashes(root) == before
    assert "<<<<<<<" in (copy / "code.py").read_text()
    assert not (root / ".git/MERGE_HEAD").exists()


def test_cli_copy_commands_have_no_person_proof_gate(done_copy, run, monkeypatch):
    root, tid, copy = done_copy
    monkeypatch.setattr(worktrees, "update_copy", lambda r, t: "copy updated")
    monkeypatch.setattr(worktrees, "ask_update", lambda r, t: "sent input")
    for command, message in (("update", "copy updated"), ("ask-update", "sent input")):
        code, out, err = run("copy", command, tid, "--by", "agent:tester")
        assert code == 0, err
        assert message in out


def test_process_death_recovers_journal(done_copy, monkeypatch):
    import os
    import signal
    import sys

    if os.name == "nt":
        pytest.skip("process-death injection uses SIGKILL")
    root, tid, copy = done_copy
    to_review(root, tid)
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    before = project_hashes(root)
    head = git(root, "rev-parse", "HEAD")
    worktrees._record_done_tip(root, tid)
    # A fresh interpreter uses the same isolated fixture home and its test-only
    # pairing, with a different lock owner. Never fork a threaded pytest worker.
    script = """
import os, signal, subprocess, sys
from pathlib import Path
from orch import addons, humanproof, worktrees
home = Path(os.environ["ORCH_HOME"])
addons.real_home = lambda: home.parent
humanproof.guarded_home = lambda root: home
def killed(top, args):
    if "--no-ff" in args:
        msg = args[args.index("-m") + 1]
        subprocess.run(["git", "merge", "--no-ff", "--no-commit", "-m", msg, args[-1]], cwd=top, check=True,
                       capture_output=True)
        os.kill(os.getpid(), signal.SIGKILL)
    raise AssertionError(args)
worktrees._bb_merge = killed
worktrees.bring_back(Path(sys.argv[1]), sys.argv[2])
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(root), tid],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr
    assert (root / ".git/MERGE_HEAD").exists()
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "merged", result
    assert git(root, "rev-parse", "HEAD^1") == head
    assert set(project_hashes(root)) == set(before)
    assert not (root / ".git/MERGE_HEAD").exists()


def test_b13e_killed_before_merge_head_keeps_journal_and_says_so(done_copy, monkeypatch):
    """A kill while git writes files but before MERGE_HEAD exists: no undo is guessed, the signed journal
    stays (every later attempt says what happened) and nothing more is written to the folder."""
    root, tid, copy = done_copy
    to_review(root, tid)
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    worktrees._record_done_tip(root, tid)

    def killed(top, args):
        (top / "code.py").write_text("pri")  # half written
        raise RuntimeError("killed")

    monkeypatch.setattr(worktrees, "_bb_merge", killed)
    with pytest.raises(RuntimeError):
        worktrees.bring_back(root, tid)
    monkeypatch.setattr(worktrees, "_bb_merge", lambda *a: pytest.fail("merged again"))
    before = project_hashes(root)
    for _ in range(2):
        result = worktrees.bring_back(root, tid)
        assert result["reason"] == worktrees.INTERRUPTED_BB
        assert result["reason_code"] == "interrupted"
    assert project_hashes(root) == before
    assert worktrees._copy_authority(root, tid).get("journal")
    assert copy.exists()


def test_start_schedules_branch_only_retry(done_copy, monkeypatch):
    root, tid, copy = done_copy
    called = []
    monkeypatch.setattr(worktrees, "copies_dir", lambda r: None)
    monkeypatch.setattr(worktrees, "_spawn_clean", lambda r, flag: called.append(flag))
    worktrees.schedule_sweep(root)
    assert called == ["--background"]


def test_forged_merged_flag_cannot_authorize_removal(done_copy):
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    tickets.apply_op(root, tid, lambda t: t["work"].update(bring_back={"state": "merged"}), by=tickets.SYSTEM)
    before = project_hashes(root)
    worktrees.remove(root, tid)
    assert project_hashes(root) == before
    assert copy.exists()
    assert worktrees._unmerged_done_work(root, tid)


def test_hostile_filter_is_refused_without_running_it(done_copy):
    root, tid, copy = done_copy
    sentinel = root.parent / "evil-filter-ran"
    git(root, "config", "filter.evil.clean", f"touch '{sentinel}'")
    git(root, "config", "filter.evil.smudge", f"touch '{sentinel}'")
    (root / ".gitattributes").write_text("code.py filter=evil\n")
    assert_waiting_unchanged(root, tid, copy, project_hashes(root))
    assert not sentinel.exists()


def test_main_run_ending_retries_other_done_tickets(done_copy):
    import os

    from orch import runs

    root, tid, copy = done_copy
    other = root.tids[1]
    rec = runs.claim(root, other, "human:test", "claude", "oneshot", folder=root, pid=os.getpid())
    before = project_hashes(root)
    assert_waiting_unchanged(root, tid, copy, before)
    runs.release(root, other, rec["run"])
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert (root / "code.py").read_text() == "print(2)\n"
    assert not copy.exists()


@pytest.mark.parametrize(
    "mode", ["late_commit", "live_done", "forged_ticket", "forged_registry", "copy_update"]
)
def test_reviewed_tip_cannot_move(done_copy, monkeypatch, mode):
    root, tid, copy = done_copy
    (root / "code.py").write_text("person dirty\n")
    if mode == "live_done":
        with monkeypatch.context() as m:
            m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
            finish(root, tid)
    else:
        finish(root, tid)
    (root / "code.py").write_text("print(1)\n")
    if mode == "copy_update":
        (root / "other").write_text("new main\n")
        git(root, "add", "other")
        git(root, "commit", "-qm", "advance main")
        monkeypatch.chdir(copy)
        worktrees.update_copy(root, tid)
    else:
        (copy / "late").write_text("unreviewed\n")
        assert worktrees._save_leftovers(copy, tid)[0]
    if mode == "forged_ticket":
        tickets.apply_op(
            root,
            tid,
            lambda t: t["work"].update(
                bring_back={"reviewed_tip": git(copy, "rev-parse", "HEAD"), "state": "merged"}
            ),
            by=tickets.SYSTEM,
        )
    if mode == "forged_registry":
        reg = worktrees.registry(root)
        reg[tid]["reviewed_tip"] = git(copy, "rev-parse", "HEAD")
        worktrees._save_registry(root, reg)
    before = project_hashes(root)
    head = git(root, "rev-parse", "HEAD")
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "waiting"
    assert "need your approval" in result["reason"]
    assert project_hashes(root) == before
    assert git(root, "rev-parse", "HEAD") == head
    assert copy.exists()


@pytest.mark.parametrize(
    "name",
    [
        ".orch/tickets/x.json",
        ".ORCH/x",
        ".Orch/x",
        "sub/.gitattributes",
        ".gitmodules",
        ".githooks/pre-commit",
        "caf\u00e9/.codex/x",
        "cafe\u0301/.agents/x",
        "sub\\.claude\\x",
    ],
)
def test_control_paths_wait(done_copy, name):
    root, tid, copy = done_copy
    p = copy / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("hostile control\n")
    git(copy, "add", "-f", "--", name)
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert "control orch or git" in result["reason"]
    assert project_hashes(root) == before
    assert copy.exists()


def test_unresolved_copy_never_saved(done_copy, monkeypatch):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    monkeypatch.chdir(copy)
    assert "Resolve the conflicts" in worktrees.update_copy(root, tid)
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert result["reason"] == "The agent has not finished resolving a conflict"
    assert project_hashes(root) == before
    assert copy.exists()


def test_refused_journal_does_not_abort_person_merge(done_copy, monkeypatch):
    root, tid, copy = done_copy
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    real = worktrees._bb_snapshot
    calls = 0

    def race(top):
        nonlocal calls
        snap = real(top)
        calls += 1
        if calls == 2:
            snap["head"] = "0" * 40
        return snap

    monkeypatch.setattr(worktrees, "_bb_snapshot", race)
    assert finish(root, tid)["state"] == "waiting"
    monkeypatch.setattr(worktrees, "_bb_snapshot", real)
    subprocess.run(["git", "merge", f"orch/{tid}"], cwd=root, capture_output=True)
    (root / "code.py").write_text("PERSON RESOLUTION\n")
    git(root, "add", "code.py")
    before = git(root, "status", "--porcelain")
    worktrees.bring_back(root, tid)
    assert (root / "code.py").read_text() == "PERSON RESOLUTION\n"
    assert git(root, "status", "--porcelain") == before
    assert (root / ".git/MERGE_HEAD").exists()


@pytest.mark.parametrize("kind", ["symlink", "gitlink", "rename", "delete"])
def test_control_modes_and_old_paths(done_copy, kind):
    root, tid, copy = done_copy
    if kind == "symlink":
        (copy / "link").symlink_to("code.py")
    elif kind == "gitlink":
        git(copy, "update-index", "--add", "--cacheinfo", f"160000,{git(copy, 'rev-parse', 'HEAD')},module")
        (copy / "module").mkdir()
        git(copy, "commit", "-qm", "gitlink")
    else:
        (root / ".orch/control").write_text("base control")
        git(root, "add", "-f", ".orch/control")
        git(root, "commit", "-qm", "tracked control")
        git(copy, "merge", "--no-edit", git(root, "rev-parse", "HEAD"))
        if kind == "rename":
            git(copy, "mv", ".orch/control", "ordinary")
        else:
            git(copy, "rm", ".orch/control")
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert "control orch or git" in result["reason"]
    assert project_hashes(root) == before
    assert copy.exists()


def test_forged_signed_review_is_refused(done_copy):
    import json

    from orch import addons

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    finish(root, tid)
    (root / "code.py").write_text("print(1)\n")
    (copy / "late").write_text("unreviewed")
    assert worktrees._save_leftovers(copy, tid)[0]
    store = addons.home(root) / "keys/copies/registry.json"
    doc = json.loads(store.read_text())
    entry = next(iter(doc["entries"].values()))
    entry["tickets"][tid]["reviewed_tip"] = git(copy, "rev-parse", "HEAD")
    store.write_text(json.dumps(doc))
    before = project_hashes(root)
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "waiting"
    assert result["reason"] == worktrees.APPROVAL_NEEDED
    assert project_hashes(root) == before
    assert copy.exists()


def test_person_approves_exact_control_tip(done_copy, run, monkeypatch):
    monkeypatch.setattr(humanproof, "person_by", _REAL_PERSON_BY)
    import io

    root, tid, copy = done_copy
    (copy / ".gitignore").write_text("something\n")
    assert finish(root, tid)["state"] == "waiting"
    target, tip, count = worktrees.approval_target(root, tid)
    assert count == 1
    proof = humanproof.mint(
        humanproof.human_key(root), humanproof.new_payload("copy.retry", target, "human:pat")
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(proof + "\n"))
    code, out, err = run("copy", "approve", tid, "--proof-stdin", "--json")
    assert code == 0, out + err
    assert git(root, "rev-parse", "HEAD^2") == tip
    assert (root / ".gitignore").read_text() == "something\n"


def test_approval_race_refused(done_copy):
    from orch.errors import Refused

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    finish(root, tid)
    target, _, _ = worktrees.approval_target(root, tid)
    git(copy, "commit", "--allow-empty", "-qm", "late")
    before = project_hashes(root)
    with pytest.raises(Refused, match="changed after"):
        worktrees.approve_copy(root, tid, target)
    assert project_hashes(root) == before


@pytest.mark.parametrize("prefix", ["", "\0binary\n"])
def test_committed_conflict_markers_wait(done_copy, prefix):
    root, tid, copy = done_copy
    (copy / "code.py").write_text(prefix + "<<<<<<< ours\nours\n=======\ntheirs\n>>>>>>> theirs\n")
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert result["reason"] == worktrees.CONFLICT_PENDING
    assert project_hashes(root) == before


def test_verify_signatures_cannot_run_repo_program(done_copy):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    tree, parent = git(copy, "rev-parse", "HEAD^{tree}"), git(copy, "rev-parse", "HEAD")
    body = (
        f"tree {tree}\nparent {parent}\nauthor a <a@b> 1 +0000\ncommitter a <a@b> 1 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n x\n -----END PGP SIGNATURE-----\n\nsigned\n"
    )
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
        cwd=copy,
        input=body,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git(copy, "reset", "-q", "--soft", sha)
    mark = root.parent / (tid + "-gpg-ran")
    evil = root.parent / (tid + "-evil.sh")
    evil.write_text(f'#!/bin/sh\necho ran >> "{mark}"\nexit 0\n')
    evil.chmod(0o755)
    git(root, "config", "merge.verifySignatures", "true")
    git(root, "config", "gpg.program", str(evil))
    assert finish(root, tid)["state"] == "merged"
    assert not mark.exists()


def test_snapshot_does_not_read_large_ignored_file(done_copy, monkeypatch):
    from pathlib import Path

    root, tid, copy = done_copy
    large = root / "large"
    with large.open("wb") as f:
        f.truncate(3 * 1024**3)
    (root / ".git/info/exclude").write_text("large\n")
    real = Path.read_bytes

    def guarded(path):
        assert path != large
        return real(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert finish(root, tid)["state"] == "merged"


def test_forged_base_does_not_choose_main_branch(done_copy):
    root, tid, copy = done_copy
    reg = worktrees.registry(root)
    reg[tid]["paths"][0]["base"] = "0" * 40
    worktrees._save_registry(root, reg)
    assert finish(root, tid)["state"] == "merged"


def test_same_history_other_branch_waits(done_copy):
    root, tid, copy = done_copy
    git(root, "checkout", "-b", "other")
    before = project_hashes(root)
    assert finish(root, tid)["state"] == "waiting"
    assert project_hashes(root) == before


def test_run_end_only_schedules(done_copy, monkeypatch):
    root, tid, copy = done_copy
    scheduled = []
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda r: scheduled.append(r))
    monkeypatch.setattr(worktrees, "sweep", lambda *a: pytest.fail("synchronous sweep"))
    worktrees.on_run_ended(root, tid)
    assert scheduled == [root]


def test_approval_without_proof_has_bound_handoff(done_copy, run, monkeypatch):
    monkeypatch.setattr(humanproof, "person_by", _REAL_PERSON_BY)

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal")
    finish(root, tid)
    target, tip, count = worktrees.approval_target(root, tid)
    code, _, _ = run("copy", "approve", tid, "--by", "human:pat")
    assert code == 2
    handoff = next(h for h in humanproof.handoffs(root) if h["target"] == target)
    assert handoff["argv"] == [
        "copy",
        "retry",
        tid,
        "--approve-tip",
        tip,
        "--control-paths",
        str(count),
        "--paths-hash",
        target.rsplit(":", 1)[1],
    ]


@pytest.mark.parametrize("phase", ["before", "after"])
def test_snapshot_memory_error_keeps_main_safe(done_copy, monkeypatch, phase):
    root, tid, copy = done_copy
    real = worktrees._bb_snapshot
    calls = 0
    before = project_hashes(root)

    def snapshot(top):
        nonlocal calls
        calls += 1
        if calls == (1 if phase == "before" else 3):
            raise MemoryError
        return real(top)

    monkeypatch.setattr(worktrees, "_bb_snapshot", snapshot)
    result = finish(root, tid)
    if phase == "before":
        assert result["state"] == "waiting"
        assert project_hashes(root) == before
        assert copy.exists()
    else:
        assert result["state"] == "merged"
        assert (root / "code.py").read_text() == "print(2)\n"


def test_snapshot_never_reads_run_state(done_copy, monkeypatch):
    from pathlib import Path

    root, tid, copy = done_copy
    run = root / ".orch/run/ignored-state"
    run.parent.mkdir(parents=True, exist_ok=True)
    run.write_text("runtime")
    real = Path.read_bytes

    def guarded(path):
        assert path != run
        return real(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert finish(root, tid)["state"] == "merged"


@pytest.mark.parametrize("marker", ["rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"])
def test_copy_operation_in_progress_is_never_saved(done_copy, marker):
    root, tid, copy = done_copy
    path = worktrees._gitdir_of(copy) / marker
    if marker.startswith("rebase"):
        path.mkdir()
    else:
        path.write_text(git(copy, "rev-parse", "HEAD"))
    before = project_hashes(root)
    assert worktrees._save_leftovers(copy, tid) == (False, worktrees.CONFLICT_PENDING)
    assert finish(root, tid)["reason"] == worktrees.CONFLICT_PENDING
    assert project_hashes(root) == before


@pytest.mark.parametrize("invalid", ["expired", "head", "message", "none"])
def test_recovery_needs_fresh_matching_head_and_message(done_copy, invalid):
    """A journal file in the project (agent-writable) is never trusted, even when every field matches."""
    import json

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal dirty")
    finish(root, tid)
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    head, tip = git(root, "rev-parse", "HEAD"), git(copy, "rev-parse", "HEAD")
    subprocess.run(["git", "merge", "-m", f"orch: {tid} manual", tip], cwd=root, capture_output=True)
    (root / "code.py").write_text("PERSON RESOLUTION\n")
    git(root, "add", "code.py")
    if invalid == "message":
        (root / ".git/MERGE_MSG").write_text("My own merge\n")
    journal = root / ".orch/run/bringback" / f"{tid}.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {
                "pre_head": "0" * 40 if invalid == "head" else head,
                "tip_sha": tip,
                "started_at": "2000-01-01T00:00:00Z" if invalid == "expired" else tickets.now(),
            }
        )
    )
    before = project_hashes(root)
    staged = git(root, "diff", "--cached", "--name-only")
    assert worktrees.bring_back(root, tid)["state"] == "waiting"
    assert project_hashes(root) == before
    assert (root / ".git/MERGE_HEAD").exists()
    assert (root / "code.py").read_text() == "PERSON RESOLUTION\n"
    assert git(root, "diff", "--cached", "--name-only") == staged
    assert not worktrees._copy_authority(root, tid).get("journal")


def test_existing_base_marker_lines_are_allowed(repo):
    (repo / "example").write_text("=======\n")
    git(repo, "add", "example")
    git(repo, "commit", "-qm", "example marker")
    copy = make(repo)
    (copy / "example").write_text("text\n=======\n=======\n")
    assert finish(repo, repo.tids[0])["state"] == "merged"


def test_copy_update_uses_short_timeout(done_copy, monkeypatch):
    root, tid, copy = done_copy
    seen = []
    real = worktrees._git

    def capture(args, cwd, timeout=worktrees.GIT_TIMEOUT, *a, **kw):
        if args[0] == "merge":
            seen.append((args, timeout))
        return real(args, cwd, timeout, *a, **kw)

    monkeypatch.setattr(worktrees, "_git", capture)
    monkeypatch.chdir(copy)
    worktrees.update_copy(root, tid)
    assert seen and seen[0][1] == 30
    assert "--no-verify-signatures" in seen[0][0]


def test_review_command_is_read_only(done_copy, run):
    import json

    root, tid, copy = done_copy
    before = project_hashes(root)
    code, out, err = run("copy", "review", tid, "--json", "--by", "agent:x")
    assert code == 0, err
    assert json.loads(out)["tip"] == git(copy, "rev-parse", "HEAD")
    assert project_hashes(root) == before
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")


def test_done_without_copy_does_not_need_bring_back(repo):
    from orch import needs

    tid = repo.tids[0]
    tickets.set_status(repo, tid, "done", "human:test", proven=True)
    assert not tickets.load(repo, tid).get("work", {}).get("bring_back")
    assert not any(row["kind"] == "copies:bring-back" for row in needs.core_rows(repo))


@pytest.mark.parametrize(
    "name",
    [
        "ODD~1/config",
        "odd./x",
        "odd /x",
        "a:b",
        ".or\u200bch/x",
        "a\u200cx",
        "a\u200dx",
        "a\ufeffx",
        ".mcp.json",
        ".envrc",
        ".github/x",
        ".vscode/x",
        ".devcontainer/x",
        "AGENTS.md",
        "AGENTS.orch.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".cursor/x",
        ".windsurf/x",
        ".aider.conf",
    ],
)
def test_b13d_control_components(done_copy, name):
    root, tid, copy = done_copy
    p = copy / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("instructions\n")
    git(copy, "add", "-f", name)
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert project_hashes(root) == before
    assert name in worktrees._control_paths(root, git(copy, "rev-parse", "HEAD"))


def test_b13d_setext_is_not_conflict(done_copy):
    root, tid, copy = done_copy
    (copy / "README.md").write_text("Summary\n=======\n")
    assert finish(root, tid)["state"] == "merged"


def test_b13d_live_done_never_reviews(done_copy, monkeypatch):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
        finish(root, tid)
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert worktrees.bring_back(root, tid)["reason"] == worktrees.APPROVAL_NEEDED


def test_b13d_deleted_ticket_empty_pending_keeps_branch(done_copy):
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal\n")
    finish(root, tid)
    tickets.ticket_path(root, tid).unlink()
    (root / ".orch/run/worktrees-pending.json").write_text("{}")
    assert not worktrees._delete_branch(root, tid, force=True)
    assert git(root, "branch", "--list", f"orch/{tid}")


def test_b13d_pending_text_is_not_displayed():
    from orch import needs

    row = needs._bring_back_row(
        "t_abcdef",
        "title",
        {"reason": "forged", "at": "forged", "reason_code": "unknown"},
        "2026-11-11T00:00:00Z",
    )
    assert row["reason"] != "forged"
    assert row["since"] == "2026-11-11T00:00:00Z"


def test_b13d_approval_binds_paths(done_copy, monkeypatch):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    monkeypatch.setattr(worktrees, "_control_paths", lambda *a: [".orch/a"])
    first = worktrees.approval_target(root, tid)[0]
    monkeypatch.setattr(worktrees, "_control_paths", lambda *a: [".orch/b"])
    assert first != worktrees.approval_target(root, tid)[0]


def test_b13d_cross_ticket_ask_update_refused(done_copy, monkeypatch):
    from orch import runs_live
    from orch.errors import Refused

    root, tid, copy = done_copy
    monkeypatch.setenv("ORCH_TICKET", root.tids[1])
    monkeypatch.setenv("ORCH_AGENT", "test")
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: True)
    monkeypatch.setattr(runs_live, "send", lambda *a: pytest.fail("sent across tickets"))
    with pytest.raises(Refused):
        worktrees.ask_update(root, tid)


def test_b13d_criss_cross_refused(repo):
    copy = make(repo)
    tid = repo.tids[0]
    (copy / ".orch").mkdir(exist_ok=True)
    (copy / ".orch/cfg").write_text("old\n")
    git(copy, "add", "-f", ".orch/cfg")
    git(copy, "commit", "-qm", "X")
    x = git(copy, "rev-parse", "HEAD")
    (repo / "main-file").write_text("main\n")
    git(repo, "add", "main-file")
    git(repo, "commit", "-qm", "P0")
    p0 = git(repo, "rev-parse", "HEAD")
    git(repo, "merge", "--no-ff", "-m", "merge X", x)
    (repo / ".orch/cfg").write_text("new\n")
    git(repo, "add", "-f", ".orch/cfg")
    git(repo, "commit", "-qm", "new config")
    git(copy, "merge", "--no-ff", "-m", "merge P0", p0)
    (copy / "harmless").write_text("hi\n")
    git(copy, "add", "harmless")
    git(copy, "commit", "-qm", "tip")
    assert len(git(repo, "merge-base", "--all", "HEAD", f"orch/{tid}").splitlines()) == 2
    head = git(repo, "rev-parse", "HEAD")
    assert finish(repo, tid)["reason"] == "bring it back by hand"
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".orch/cfg").read_text() == "new\n"
    # The plain reason survives into the Need row (from the fixed code table, not free text).
    from orch import needs

    rows = [r for r in needs.core_rows(repo) if r.get("ticket") == tid]
    assert rows and rows[0]["reason"] == "bring it back by hand"
    # An approval cannot get past it either.
    with pytest.raises(worktrees.Refused, match="bring it back by hand"):
        worktrees.approval_target(repo, tid)
    assert git(repo, "rev-parse", "HEAD") == head


def test_b13d_agent_done_never_reviews(done_copy, monkeypatch):
    from orch import config

    root, tid, copy = done_copy
    monkeypatch.setattr(config, "agents_may_finish", lambda *a: True)
    tickets.set_status(root, tid, "done", "agent:test")
    assert tickets.load(root, tid)["status"] == "done"
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert worktrees.bring_back(root, tid)["reason"] == worktrees.APPROVAL_NEEDED


@pytest.mark.parametrize("kind", ["control", "overlap", "markers"])
def test_b13d_merge_result_is_checked(done_copy, monkeypatch, kind):
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    original = git(copy, "rev-parse", "HEAD")
    name = ".orch/cfg" if kind == "control" else "result-only"
    p = copy / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n" if kind == "markers" else "result\n")
    git(copy, "add", "-f", name)
    tree = git(copy, "write-tree")
    git(copy, "reset", "--mixed", original)
    p.unlink()
    real = worktrees._git

    def merge_result(args, *a, **kw):
        if args[0] == "merge-tree":
            return 0, tree, ""
        return real(args, *a, **kw)

    monkeypatch.setattr(worktrees, "_git", merge_result)
    if kind == "overlap":
        (root / name).write_text("personal bytes\n")
    head = git(root, "rev-parse", "HEAD")
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert git(root, "rev-parse", "HEAD") == head
    assert project_hashes(root) == before
    if kind == "control":
        assert name in worktrees._control_paths(root, original)
    if kind == "markers":
        assert result["reason"] == worktrees.CONFLICT_PENDING


def test_b13d_real_merge_tree(done_copy, monkeypatch):
    from orch import safegit

    root, tid, copy = done_copy
    # Exercise the driver allow-list addition without modifying safegit.py.
    monkeypatch.setattr(safegit, "ALLOWED", safegit.ALLOWED | {"merge-tree"})
    assert worktrees._save_leftovers(copy, tid)[0]
    ranges = worktrees._safety_ranges(root, git(copy, "rev-parse", "HEAD"))
    assert len(ranges) == 2
    assert finish(root, tid)["state"] == "merged"


def test_b13d_unsaved_done_never_reviews(done_copy, monkeypatch):
    """Something that had to be saved at Done (it was not there when the review began) is never reviewed,
    whether saving it works or not."""
    root, tid, copy = done_copy
    to_review(root, tid)
    (copy / "late").write_text("written after the review began\n")
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_save_leftovers", lambda *a: (False, "could not save"))
        finish(root, tid)
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert worktrees.bring_back(root, tid)["reason"] == worktrees.APPROVAL_NEEDED
    assert (copy / "late").exists()


def test_b13d_review_shows_first_five_paths(done_copy, run):
    import json

    root, tid, copy = done_copy
    for i in range(7):
        (copy / f".aider{i}").write_text("config\n")
    finish(root, tid)
    code, out, err = run("copy", "review", tid, "--json")
    assert code == 0, err
    review = json.loads(out)
    assert review["paths"] == [f".aider{i}" for i in range(5)]
    assert review["paths_summary"].endswith("and 2 more")
    assert review["target"].endswith(":" + review["paths_hash"])


# ---------------------------------------------------------------- B13e (Fable 5.2 review)


def test_b13e_done_only_records_and_schedules(done_copy, monkeypatch):
    """#7: marking Done records the tip reviewed when the review began; the bring-back runs in the detached
    sweep."""
    root, tid, copy = done_copy
    to_review(root, tid)
    scheduled = []
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda r: scheduled.append(r))
    monkeypatch.setattr(worktrees, "_bring_back_locked", lambda *a: pytest.fail("bring-back inside Done"))
    monkeypatch.setattr(worktrees, "_bb_snapshot", lambda *a: pytest.fail("snapshot inside Done"))
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    assert scheduled == [root]
    assert (root / "code.py").read_text() == "print(1)\n"
    assert worktrees._copy_authority(root, tid)["reviewed_tip"] == git(copy, "rev-parse", "HEAD")


def test_b13e_failed_merge_never_aborts(done_copy, monkeypatch):
    """#1: another process plants MERGE_HEAD=<tip> (and the person stages work) right before orch's merge:
    git refuses, and orch must NOT run `merge --abort` (it would wipe the staged work)."""
    root, tid, copy = done_copy
    real = worktrees._bb_merge

    def race(top, args):
        if "--no-ff" in args:
            (top / "notes.txt").write_text("person's staged work\n")
            git(top, "add", "notes.txt")
            (top / ".git/MERGE_HEAD").write_text(args[-1] + "\n")
        elif "--abort" in args:
            pytest.fail("aborted a merge orch cannot prove is its own")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", race)
    assert finish(root, tid)["state"] == "waiting"
    for _ in range(2):  # later attempts do not abort it either
        assert worktrees.bring_back(root, tid)["state"] == "waiting"
    assert "notes.txt" in git(root, "diff", "--cached", "--name-only").split()
    assert (root / "notes.txt").read_text() == "person's staged work\n"
    assert (root / ".git/MERGE_HEAD").exists()
    assert copy.exists()


def test_b13e_conflict_is_computed_before_any_merge(done_copy, monkeypatch):
    """#1: a conflict is found with merge-tree; the project folder never sees a conflicted merge."""
    root, tid, copy = done_copy
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    monkeypatch.setattr(worktrees, "_bb_merge", lambda *a: pytest.fail("merge started"))
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["reason"] == worktrees.UPDATE
    assert project_hashes(root) == before
    assert not (root / ".git/MERGE_HEAD").exists()


@pytest.mark.parametrize("how", ["detach", "branch"])
def test_b13e_looking_at_the_work_is_not_bringing_it_back(done_copy, monkeypatch, how):
    """#2: the person checks the work out to look at it; a sweep must not call that merged."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    own = git(root, "symbolic-ref", "--short", "HEAD")
    tip = git(copy, "rev-parse", "HEAD")
    if how == "detach":
        git(root, "checkout", "-q", "--detach", tip)
    else:
        git(root, "checkout", "-q", "-b", "look", tip)
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "waiting"
    assert worktrees._unmerged_done_work(root, tid)
    assert copy.exists()
    assert git(root, "branch", "--list", f"orch/{tid}")
    git(root, "checkout", "-q", own)
    assert git(root, "rev-parse", f"orch/{tid}") == tip


@pytest.mark.parametrize("agent_commit", [False, True])
def test_b13e_dropped_commit_never_comes_back(repo, agent_commit):
    """#3: the person drops a commit (a secret) after the copy was made; the branch's history still holds
    it. Nothing is merged, even with zero agent commits."""
    tid = repo.tids[0]
    (repo / "secret").write_text("api key\n")
    git(repo, "add", "secret")
    git(repo, "commit", "-qm", "oops")
    copy = make(repo)
    if agent_commit:
        (copy / "code.py").write_text("print(2)\n")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    head = git(repo, "rev-parse", "HEAD")
    result = finish(repo, tid)
    assert result["state"] == "waiting"
    assert result["reason"] == worktrees.BASE_CHANGED
    assert git(repo, "rev-parse", "HEAD") == head
    assert not (repo / "secret").exists()
    assert copy.exists()


@pytest.mark.parametrize("option", ["--squash", "--no-commit", "-s ours"])
def test_b13e_merge_options_cannot_fake_a_merge(done_copy, option):
    """branch.<b>.mergeOptions (agent-writable config) would make `git merge` squash, stop, or keep only
    main: never merged with the work missing."""
    root, tid, copy = done_copy
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    git(root, "config", f"branch.{branch}.mergeOptions", option)
    head = git(root, "rev-parse", "HEAD")
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["state"] == "waiting"
    assert git(root, "rev-parse", "HEAD") == head
    assert project_hashes(root) == before
    assert not git(root, "diff", "--cached", "--name-only")


def commit_paths(copy, names):
    """Commit files to the copy's branch through the index only (names a case-insensitive disk cannot
    hold side by side)."""
    for name in names:
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=copy,
            input=name + "\n",
            capture_output=True,
            text=True,
        ).stdout.strip()
        git(copy, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")
    git(copy, "commit", "-qm", "names")


@pytest.mark.parametrize("names", [["CODE.PY"], ["a.txt", "A.txt"], ["Docs/x", "docs/y"]])
def test_b13e_case_collisions_wait(done_copy, names):
    """#6: touched paths that fold to a tracked one or to each other (case, NFC) are never merged."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    commit_paths(copy, names)
    git(root, "worktree", "remove", "--force", str(copy))
    head = git(root, "rev-parse", "HEAD")
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["reason"] == worktrees.NAME_CLASH
    assert git(root, "rev-parse", "HEAD") == head
    assert project_hashes(root) == before


def test_b13e_nfc_collision_with_tracked_file(repo):
    (repo / "caf\u00e9.txt").write_text("tracked\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "nfc")
    assert worktrees._name_clash(["cafe\u0301.txt"], ["caf\u00e9.txt"])
    assert not worktrees._name_clash(["caf\u00e9.txt"], ["caf\u00e9.txt", "CAF\u00c9.txt"])


def test_b13e_untracked_nested_repo_and_fifo_do_not_block(done_copy):
    """#8c: a nested repository (or a FIFO) the merge does not touch is no reason to wait forever."""
    import os

    root, tid, copy = done_copy
    nested = root / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    (nested / "file").write_text("inner\n")
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "pipe")
    assert finish(root, tid)["state"] == "merged"
    assert (nested / "file").read_text() == "inner\n"


def test_b13e_nested_repo_in_the_way_waits(done_copy):
    root, tid, copy = done_copy
    (copy / "nested").write_text("a file where the person has a repository\n")
    (root / "nested").mkdir()
    git(root / "nested", "init", "-q")
    before = project_hashes(root)
    assert finish(root, tid)["reason"] == worktrees.OVERLAP
    assert project_hashes(root) == before


def test_b13e_missing_branch_is_not_unmerged(done_copy):
    """#8d: a registry line whose branch is gone (and no copy) is no Need and is cleaned up."""
    from orch import needs

    root, tid, copy = done_copy
    (root / "code.py").write_text("personal\n")
    assert finish(root, tid)["state"] == "waiting"
    git(root, "worktree", "remove", "--force", str(copy))
    git(root, "branch", "-D", f"orch/{tid}")
    assert not worktrees._unmerged_done_work(root, tid)
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "none"
    assert tid not in worktrees.registry(root)
    assert not any(r["ticket"] == tid for r in needs.core_rows(root) if r["kind"] == "copies:bring-back")


def test_b13e_check_attr_is_chunked(done_copy, monkeypatch):
    """#8e: many touched paths never become one over-long command line."""
    root, tid, copy = done_copy
    for i in range(30):
        (copy / f"file-{i:02d}-{'x' * 40}.txt").write_text("x\n")
    assert worktrees._save_leftovers(copy, tid)[0]
    real_chunks, real_read = worktrees._chunks, worktrees._bb_read
    monkeypatch.setattr(worktrees, "_chunks", lambda paths, limit=0: real_chunks(paths, 200))
    lengths = []

    def read(top, args, **kw):
        if args[0] == "check-attr":
            lengths.append(sum(len(a) + 1 for a in args))
        return real_read(top, args, **kw)

    monkeypatch.setattr(worktrees, "_bb_read", read)
    assert finish(root, tid)["state"] == "merged"
    assert len(lengths) > 3
    assert max(lengths) < 400


def test_b13e_root_spelled_through_a_link(done_copy, tmp_path):
    """#8f: the workspace root given through a link is matched to git's top folder; an unrelated one is a
    plain reason, never a raw ValueError."""
    from pathlib import Path

    from orch.errors import Refused

    root, tid, copy = done_copy
    alias = tmp_path.parent / (tmp_path.name + "-alias")
    alias.symlink_to(root, target_is_directory=True)
    top = Path(git(root, "rev-parse", "--show-toplevel"))
    assert worktrees._rel_posix(top, alias / ".orch/run") == ".orch/run"
    with pytest.raises(Refused, match="git could not read your folder"):
        worktrees._rel_posix(top, tmp_path.parent)


def test_b13e_legacy_copy_gets_branch_from_approval(done_copy):
    """#8a: a copy made before the branch was recorded waits once; the person's approval records it."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    worktrees._copy_authority(root, tid, lambda r: (r.pop("origin_branch"), r.pop("base")))
    result = finish(root, tid)
    assert result["reason_code"] == "origin"
    target, tip, _ = worktrees.approval_target(root, tid)
    assert worktrees.approve_copy(root, tid, target)["state"] == "merged"
    assert git(root, "rev-parse", "HEAD^2") == tip
    assert worktrees._copy_authority(root, tid)["origin_branch"] == git(root, "symbolic-ref", "HEAD")


def test_b13e_create_on_detached_head_is_a_plain_reason(repo):
    """#9: nothing is made (no folder, no branch) and nothing raises."""
    tid = repo.tids[0]
    git(repo, "checkout", "-q", "--detach")
    entry, why = worktrees._create(repo, tid)
    assert entry is None
    assert "not on a branch" in why
    assert not git(repo, "branch", "--list", f"orch/{tid}")
    assert not worktrees.path_for(
        worktrees.addons.workspace_id(repo), tid, worktrees.addons.home(repo)
    ).exists()


def test_b13e_save_leftovers_never_raises(done_copy, monkeypatch):
    """#10: one copy whose git breaks never stops a sweep."""
    from orch.errors import Refused

    root, tid, copy = done_copy

    def broken(*a):
        raise Refused("git could not read your folder")

    monkeypatch.setattr(worktrees, "_copy_conflict", broken)
    assert worktrees._save_leftovers(copy, tid) == (False, "git could not read your folder")


def test_b13e_state_and_notes_written_only_on_change(done_copy):
    """#11: the same answer again changes nothing (no new revision, "since" stays); a clear clears."""
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal\n")
    first = finish(root, tid)
    rev = tickets.load(root, tid)["revision"]
    again = worktrees._bb_state(root, tid, "waiting", first["reason"])
    assert tickets.load(root, tid)["revision"] == rev
    assert again["at"] == first["at"]
    worktrees._mark(root, "kept", tid)
    assert not [i for i in worktrees._pending(root)["kept"] if i["ticket"] == tid]


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_b13e_hidden_edit_in_index_is_kept(done_copy, flag):
    """Part 2 #5: an index flag (or forged stat data) that hides the person's edit from `git status`."""
    root, tid, copy = done_copy
    (root / "code.py").write_text("person's hidden edit\n")
    git(root, "update-index", flag, "code.py")
    assert not git(root, "status", "--porcelain", "--", "code.py")
    result = finish(root, tid)
    assert result["reason"] == worktrees.OVERLAP
    assert (root / "code.py").read_text() == "person's hidden edit\n"


def test_b13e_staged_change_waits(done_copy):
    root, tid, copy = done_copy
    (root / "notes.txt").write_text("staged\n")
    git(root, "add", "notes.txt")
    result = finish(root, tid)
    assert result["reason"] == worktrees.STAGED
    assert git(root, "diff", "--cached", "--name-only") == "notes.txt"


def test_b13e_cli_approve_compares_what_was_shown(done_copy, run):
    """#4: the click forwards the tip, count and path hash it showed; the CLI compares them with now."""
    root, tid, copy = done_copy
    (copy / ".gitignore").write_text("something\n")
    assert finish(root, tid)["state"] == "waiting"
    target, tip, count = worktrees.approval_target(root, tid)
    digest = target.rsplit(":", 1)[1]
    git(copy, "commit", "--allow-empty", "-qm", "moved after display")
    head = git(root, "rev-parse", "HEAD")
    shown = ["--approve-tip", tip, "--control-paths", str(count), "--paths-hash", digest]
    code, out, err = run("copy", "approve", tid, *shown, "--by", "human:pat")
    assert code == 2
    assert "changed after it was shown" in out + err
    assert git(root, "rev-parse", "HEAD") == head


def test_b13e_plain_retry_proof_cannot_approve(done_copy, run, monkeypatch):
    """Part 2 #7: a proof for a plain "Try again" (target = the ticket) never approves a bring-back."""
    import io

    monkeypatch.setattr(humanproof, "person_by", _REAL_PERSON_BY)
    root, tid, copy = done_copy
    (copy / ".gitignore").write_text("something\n")
    assert finish(root, tid)["state"] == "waiting"
    target, tip, count = worktrees.approval_target(root, tid)
    proof = humanproof.mint(
        humanproof.human_key(root), humanproof.new_payload("copy.retry", tid, "human:pat")
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(proof + "\n"))
    head = git(root, "rev-parse", "HEAD")
    shown = ["--approve-tip", tip, "--control-paths", str(count), "--paths-hash", target.rsplit(":", 1)[1]]
    code, _, _ = run("copy", "retry", tid, *shown, "--proof-stdin", "--json")
    assert code != 0
    assert git(root, "rev-parse", "HEAD") == head
    assert not worktrees._copy_authority(root, tid).get("controls_tip")


def test_b13e_review_paths_are_one_plain_line_each(done_copy, run):
    """Automated finding 1: agent-chosen path names cannot fake the approval text."""
    import json

    root, tid, copy = done_copy
    name = '.claude/x 0 control paths "approved"'
    (copy / ".claude").mkdir()
    (copy / name).write_text("x\n")
    assert finish(root, tid)["state"] == "waiting"
    code, out, err = run("copy", "review", tid, "--json")
    assert code == 0, err
    review = json.loads(out)
    assert review["control_paths"] == 1
    for text in [*review["paths"], review["paths_summary"]]:
        assert "\n" not in text and '"' not in text
    assert review["paths"] == [".claude/x 0 control paths 'approved'"]
    # A line break in a name (B13f: an odd name) is not even offered for approval: nothing to fake.
    (copy / ".claude/y\n1 more line").write_text("y\n")
    assert worktrees._save_leftovers(copy, tid)[0]
    code, out, err = run("copy", "review", tid, "--json")
    assert code != 0
    assert worktrees.bring_back(root, tid)["reason"] == worktrees.ODD_NAME


def live_claim(root, tid, pid):
    from orch import runs

    rec = runs.claim(root, tid, "agent:test", "claude", "oneshot", folder=root, pid=pid)
    return {"ORCH_RUN": rec["run"], "ORCH_TICKET": tid}


@pytest.mark.parametrize("case", ["no_record", "other_ticket", "dead_run", "own_live"])
def test_b13e_agent_identity_comes_from_a_live_run(done_copy, monkeypatch, case):
    """Automated finding 2: ORCH_RUN + ORCH_TICKET must name a LIVE run record of that ticket."""
    import os

    from orch import runs_live
    from orch.errors import Refused

    root, tid, copy = done_copy
    sent = []
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: True)
    monkeypatch.setattr(runs_live, "send", lambda r, t, by, text: sent.append(t) or {"delivered": 1})
    monkeypatch.setattr(runs_live, "send_text", lambda result, t: "sent")
    if case == "no_record":
        env = {"ORCH_RUN": "r_forged0001", "ORCH_TICKET": tid}
    elif case == "other_ticket":
        env = live_claim(root, root.tids[1], os.getpid())
    elif case == "dead_run":
        dead = subprocess.Popen(["true"])
        dead.wait()
        env = live_claim(root, tid, dead.pid)
    else:
        env = live_claim(root, tid, os.getpid())
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if case == "own_live":
        assert worktrees.ask_update(root, tid) == "sent"
        assert sent == [tid]
        with pytest.raises(Refused):
            worktrees.ask_update(root, root.tids[1])
    else:
        with pytest.raises(Refused):
            worktrees.ask_update(root, tid)
        assert not sent


# ---------------------------------------------------------------- B13f (final reviews: Fable 5.2, Opus 5.5)


def done_no_sweep(root, tid):
    """A person's Done; the scheduled sweep does not run (the test runs it, or calls bring_back)."""
    tickets.set_status(root, tid, "done", "human:test", proven=True)


def commit_on_side(root, name, text):
    """A commit with one more file on top of HEAD, made on a throwaway branch; the folder ends as before."""
    own = git(root, "symbolic-ref", "--short", "HEAD")
    git(root, "checkout", "-q", "-b", "side-tmp")
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-qm", "side")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", own)
    git(root, "branch", "-q", "-D", "side-tmp")
    return sha


@pytest.mark.parametrize("move", ["ref", "copy_file", "copy_commit"])
def test_b13f_change_after_review_needs_approval(done_copy, move):
    """Fable #1 / Opus #3: between the review and the person's Done another agent moves the branch, or a
    leftover process writes or commits into the copy: the Done approves only the tip the review showed."""
    root, tid, copy = done_copy
    to_review(root, tid)
    reviewed = git(copy, "rev-parse", "HEAD")
    assert worktrees._copy_authority(root, tid)["review_tip"] == reviewed
    if move == "ref":
        evil = commit_on_side(root, "evil.py", "evil\n")
        git(root, "update-ref", f"refs/heads/orch/{tid}", evil)
    elif move == "copy_file":
        (copy / "evil.py").write_text("evil\n")
    else:
        (copy / "evil.py").write_text("evil\n")
        git(copy, "add", "evil.py")
        git(copy, "commit", "-qm", "late")
    before = project_hashes(root)
    head = git(root, "rev-parse", "HEAD")
    result = finish(root, tid)
    assert result["state"] == "waiting" and result["reason"] == worktrees.APPROVAL_NEEDED
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert git(root, "rev-parse", "HEAD") == head and project_hashes(root) == before
    assert not (root / "evil.py").exists()


def test_b13f_review_tip_needs_a_committed_copy_and_no_run(done_copy, monkeypatch):
    """Main A: the tip is recorded only when nothing would have to be saved and no run holds the copy; a run
    that ends while the ticket is in Review records it then."""
    root, tid, copy = done_copy  # code.py is not committed in the copy
    tickets.set_status(root, tid, "review", "human:test")
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    tickets.set_status(root, tid, "ready", "human:test")
    assert worktrees._save_leftovers(copy, tid)[0]
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
        tickets.set_status(root, tid, "review", "human:test")
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    worktrees.on_run_ended(root, tid)
    assert worktrees._copy_authority(root, tid)["review_tip"] == git(copy, "rev-parse", "HEAD")
    assert finish(root, tid)["state"] == "merged"


def test_b13f_agent_done_after_review_is_no_approval(done_copy, monkeypatch):
    """Fable #2 scenario 1: the person reviewed (or asked for changes); the agent then finishes the ticket
    itself (agents may finish): its own Done is no person's approval of the tip."""
    from orch import config

    root, tid, copy = done_copy
    to_review(root, tid)
    monkeypatch.setattr(config, "agents_may_finish", lambda *a: True)
    tickets.set_status(root, tid, "done", "agent:test")
    worktrees.sweep(root)
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert tickets.load(root, tid)["work"]["bring_back"]["reason"] == worktrees.APPROVAL_NEEDED
    assert (root / "code.py").read_text() == "print(1)\n"


def test_b13f_person_done_must_be_this_rounds(done_copy):
    """Main A: only a current person verdict made at or after the review began counts."""
    root, tid, copy = done_copy
    to_review(root, tid)
    done_no_sweep(root, tid)
    t = tickets.load(root, tid)
    assert worktrees._person_done(root, t, "2000-01-01T00:00:00Z")
    assert not worktrees._person_done(root, t, "2999-01-01T00:00:00Z")
    forged = {**t, "verdicts": [{**t["verdicts"][0], "kind": "agent"}]}
    assert not worktrees._person_done(root, forged, "2000-01-01T00:00:00Z")


def test_b13f_reopened_round_forgets_the_old_review(done_copy):
    """Fable #2 scenario 2: a ticket reopened for more work drops the reviewed tip, the Done marker and the
    approvals of the round before; a later Done without a new review needs an approval."""
    root, tid, copy = done_copy
    (root / "code.py").write_text("person dirty\n")
    assert finish(root, tid)["reason"] == worktrees.OVERLAP
    assert worktrees._copy_authority(root, tid).get("reviewed_tip")
    tickets.set_status(root, tid, "ready", "human:test")
    known = worktrees._copy_authority(root, tid)
    assert not any(known.get(k) for k in worktrees.ROUND_KEYS)
    assert known.get("origin_branch") and known.get("base")
    (root / "code.py").write_text("print(1)\n")
    done_no_sweep(root, tid)
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["reason"] == worktrees.APPROVAL_NEEDED
    assert (root / "code.py").read_text() == "print(1)\n"
    assert copy.exists()


def test_b13f_busy_done_click_is_judged_by_the_sweep(done_copy, monkeypatch):
    """Fable #9 / Opus #7: the Done click waits at most SWEEP_WAIT for the copies lock; when it is busy, the
    sweep judges the Done before it saves anything."""
    from orch import runs

    root, tid, copy = done_copy
    to_review(root, tid)
    waits = []
    real = runs.locked

    def busy(r, name, wait=10.0):
        if name == worktrees.LOCK_ID:
            waits.append(wait)
            raise worktrees.Refused("busy")
        return real(r, name, wait)

    with monkeypatch.context() as m:
        m.setattr(runs, "locked", busy)
        done_no_sweep(root, tid)
    assert waits == [worktrees.SWEEP_WAIT]
    assert not worktrees._copy_authority(root, tid).get("done_seen")
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"


def test_b13f_orphan_copy_of_another_project_is_still_saved(repo, tmp_path):
    """Fable #3: the main-relative marker check is never run against the CURRENT workspace's repository for
    a copy of another project: its changes are saved and it is removed (no --discard needed)."""
    from test_worktrees_cleanup import remember_gone

    from orch import addons

    old = tmp_path / "old-project-repo"
    old.mkdir()
    git(old, "init", "-q")
    git(old, "config", "user.email", "t@t")
    git(old, "config", "user.name", "t")
    (old / "a.txt").write_text("a\n")
    git(old, "add", "a.txt")
    git(old, "commit", "-qm", "init")
    tid = "t_orphan01"
    folder = addons.home(repo) / "worktrees" / "bbbbbbbb"
    folder.mkdir(parents=True)
    copy = folder / tid
    git(old, "worktree", "add", "-q", "-b", f"orch/{tid}", str(copy))
    (copy / "w.txt").write_text("work\n")
    gone = tmp_path / "gone-project"
    (folder / ".owner").write_text(str(gone) + "\n")
    remember_gone(repo, folder, gone)
    assert worktrees.remove_orphaned(repo, "bbbbbbbb") == []
    assert git(old, "show", f"orch/{tid}:w.txt") == "work"
    assert not copy.exists()


def test_b13f_unreadable_branch_never_starts_a_new_round(done_copy, monkeypatch):
    """Fable #4: a timeout reading the branch is not "no branch": nothing is cleared, nothing deleted; a
    half-made copy deletes its branch only while it still points where it was made."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    tip = git(copy, "rev-parse", "HEAD")
    worktrees._copy_authority(root, tid, lambda r: r.update(done_seen=True, reviewed_tip=tip))
    git(root, "worktree", "remove", "--force", str(copy))
    real = worktrees._git

    def flaky(args, *a, **kw):
        if args[:2] == ["rev-parse", "--verify"] and args[-1] == f"refs/heads/orch/{tid}":
            return 124, "", "timed out"
        return real(args, *a, **kw)

    monkeypatch.setattr(worktrees, "_git", flaky)
    entry, why = worktrees._create(root, tid)
    monkeypatch.setattr(worktrees, "_git", real)
    assert entry is None and "try again" in why
    assert git(root, "rev-parse", f"orch/{tid}") == tip
    assert worktrees._copy_authority(root, tid)["reviewed_tip"] == tip
    worktrees._drop_partial(root, copy, f"orch/{tid}", True, git(root, "rev-parse", "HEAD"))
    assert git(root, "rev-parse", f"orch/{tid}") == tip


def test_b13f_agent_in_the_folder_spelled_through_a_link(done_copy, monkeypatch, tmp_path):
    """Fable #5: a run whose folder is the project spelled through a link still blocks the merge."""
    from orch import runs

    root, tid, copy = done_copy
    alias = tmp_path.parent / (tmp_path.name + "-link")
    alias.symlink_to(root, target_is_directory=True)
    runs._atomic(runs.record_path(root, root.tids[1]), "{}")
    monkeypatch.setattr(runs, "read", lambda r, t: {"ticket": t} if t == root.tids[1] else None)
    monkeypatch.setattr(runs, "state", lambda r: "alive")
    monkeypatch.setattr(runs, "workdir_for", lambda *a: alias)
    before = project_hashes(root)
    result = finish(root, tid)
    assert result["reason"] == "an agent is still working in your folder"
    assert project_hashes(root) == before


def test_b13f_run_state_is_never_approvable(done_copy):
    """Fable #7a: a branch that writes orch's own run state (registry, run records, locks) is refused; no
    approval lets it through."""
    root, tid, copy = done_copy
    p = copy / ".orch/run/worktrees-pending.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n")
    git(copy, "add", "-f", ".orch/run/worktrees-pending.json")
    head = git(root, "rev-parse", "HEAD")
    result = finish(root, tid)
    assert result["reason"] == worktrees.RUN_STATE
    with pytest.raises(worktrees.Refused):
        worktrees.approval_target(root, tid)
    assert git(root, "rev-parse", "HEAD") == head


@pytest.mark.parametrize(
    "name",
    ["SECRET~1.ENV", "notes.", ".clau\u200ede/settings.json", ".git\u202chub/workflows/x.yml", "a\u206ab"],
)
def test_b13f_odd_names_are_never_approvable(done_copy, name):
    """Fable #7b / #11, Opus #9: names a file system may write as another name (8.3, trailing dot, every
    ignorable format character HFS+ drops) wait for a person working by hand, never a one-click approval."""
    root, tid, copy = done_copy
    p = copy / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n")
    git(copy, "add", "-f", "--", name)
    head = git(root, "rev-parse", "HEAD")
    result = finish(root, tid)
    assert result["reason"] == worktrees.ODD_NAME
    with pytest.raises(worktrees.Refused):
        worktrees.approval_target(root, tid)
    assert git(root, "rev-parse", "HEAD") == head


@pytest.mark.parametrize(
    "name", [".cursorrules", ".npmrc", ".env.local", "GEMINI.md", ".pre-commit-config.yaml"]
)
def test_b13f_more_control_files(done_copy, name):
    """Fable #11: more files that tools read and act on need a person's look."""
    root, tid, copy = done_copy
    (copy / name).write_text("x\n")
    git(copy, "add", "-f", "--", name)
    result = finish(root, tid)
    assert "control orch or git" in result["reason"]
    assert not (root / name).exists()


def test_b13f_branch_moved_over_the_work_is_not_merged(done_copy):
    """Fable #8: somebody moves the project's branch over the tip (the files stay as they were): orch never
    certifies that as merged, keeps the copy and the branch."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    tip = git(copy, "rev-parse", "HEAD")
    done_no_sweep(root, tid)  # no review round: the tip was never approved
    git(root, "update-ref", git(root, "symbolic-ref", "HEAD"), tip)
    worktrees.sweep(root)
    back = tickets.load(root, tid)["work"]["bring_back"]
    assert back["state"] == "waiting" and back["reason_code"] == "outside"
    assert copy.exists() and git(root, "branch", "--list", f"orch/{tid}")
    assert (root / "code.py").read_text() == "print(1)\n"


def test_b13f_branch_reappearing_after_bring_back_is_not_one_click(done_copy):
    """Fable #6: a long-finished ticket's branch made again by an agent: no Need with a one-click approve."""
    root, tid, copy = done_copy
    assert finish(root, tid)["state"] == "merged"
    assert not git(root, "branch", "--list", f"orch/{tid}")
    git(root, "branch", f"orch/{tid}", commit_on_side(root, "evil.py", "evil\n"))
    head = git(root, "rev-parse", "HEAD")
    worktrees.sweep(root)
    back = tickets.load(root, tid)["work"]["bring_back"]
    assert back["state"] == "waiting" and back["reason_code"] == "foreign"
    with pytest.raises(worktrees.Refused):
        worktrees.approval_target(root, tid)
    assert git(root, "rev-parse", "HEAD") == head and not (root / "evil.py").exists()


def test_b13f_branch_not_grown_from_its_base_waits(repo):
    """Opus #4: the branch must grow from the recorded base (not from older or unrelated history)."""
    tid = repo.tids[0]
    (repo / "second").write_text("2\n")
    git(repo, "add", "second")
    git(repo, "commit", "-qm", "second")
    copy = make(repo)
    git(copy, "reset", "-q", "--soft", git(repo, "rev-parse", "HEAD~1"))
    (copy / "x.py").write_text("x\n")
    head = git(repo, "rev-parse", "HEAD")
    assert finish(repo, tid)["reason"] == worktrees.BASE_CHANGED
    assert git(repo, "rev-parse", "HEAD") == head


def crash_in_merge(monkeypatch, after):
    real = worktrees._bb_merge

    def crash(top, args):
        if "--no-ff" in args:
            half_merge(top, args)
            after(top)
            raise RuntimeError("killed in the middle of the merge")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", crash)
    return real


def reviewed_done(root, tid, monkeypatch):
    to_review(root, tid)
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        done_no_sweep(root, tid)
    worktrees._record_done_tip(root, tid)


@pytest.mark.parametrize("case", ["stale", "resolved"])
def test_b13f_stale_or_resolved_merge_is_never_aborted(done_copy, monkeypatch, case):
    """Fable #10 / Opus #2: a merge orch started is undone only soon after, and only while the index is
    what the merge wrote: a person's staged resolution (or anything later) is never thrown away."""
    root, tid, copy = done_copy
    real = crash_in_merge(monkeypatch, lambda top: None)
    reviewed_done(root, tid, monkeypatch)
    with pytest.raises(RuntimeError):
        worktrees.bring_back(root, tid)

    def no_abort(top, args):
        if "--abort" in args:
            pytest.fail("aborted")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", no_abort)
    if case == "stale":
        worktrees._copy_authority(root, tid, lambda r: r["journal"].update(started_at="2000-01-01T00:00:00Z"))
    else:
        (root / "code.py").write_text("PERSON RESOLUTION\n")
        git(root, "add", "code.py")
    before = project_hashes(root)
    staged = git(root, "diff", "--cached", "--name-only")
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "waiting" and result["reason"] == worktrees.MERGING
    assert (root / ".git/MERGE_HEAD").exists()
    assert project_hashes(root) == before
    assert git(root, "diff", "--cached", "--name-only") == staged


def test_b13f_killed_clean_merge_is_rolled_back(done_copy, monkeypatch):
    """Opus #10: a clean merge killed after writing index and files, before its commit (no MERGE_HEAD):
    the index is exactly the checked tree, so orch undoes it exactly and brings the work back."""
    root, tid, copy = done_copy

    def no_state(top):
        for name in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE"):
            (top / ".git" / name).unlink(missing_ok=True)

    real = crash_in_merge(monkeypatch, no_state)
    reviewed_done(root, tid, monkeypatch)
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError):
        worktrees.bring_back(root, tid)
    assert (root / "code.py").read_text() == "print(2)\n" and git(root, "rev-parse", "HEAD") == head
    monkeypatch.setattr(worktrees, "_bb_merge", real)
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "merged", result
    assert git(root, "rev-parse", "HEAD^1") == head
    assert (root / "code.py").read_text() == "print(2)\n"


def test_b13f_ignored_folder_is_one_entry_and_still_overlaps(done_copy):
    """Fable #9: an ignored folder is listed once (not file by file); a merge into it still waits."""
    root, tid, copy = done_copy
    with (root / ".git/info/exclude").open("a") as f:
        f.write("\nbuild/\n")
    for i in range(50):
        (root / "build" / "deep").mkdir(parents=True, exist_ok=True)
        (root / "build" / "deep" / f"f{i}").write_text("x\n")
    status = worktrees._bb_status(root)
    assert "build/deep/f1" not in status and "!! build/" in status
    (copy / "build").mkdir()
    (copy / "build" / "new").write_text("incoming\n")
    git(copy, "add", "-f", "build/new")
    assert finish(root, tid)["reason"] == worktrees.OVERLAP
    assert not (root / "build" / "new").exists()


def test_b13f_ref_moved_back_never_makes_reviewed_work_look_merged(done_copy):
    """Opus #11: the signed reviewed tip keeps the branch when its ref is pointed back at merged history."""
    root, tid, copy = done_copy
    (root / "code.py").write_text("personal\n")
    assert finish(root, tid)["state"] == "waiting"
    assert worktrees._copy_authority(root, tid).get("reviewed_tip")
    git(root, "worktree", "remove", "--force", str(copy))
    git(root, "update-ref", f"refs/heads/orch/{tid}", git(root, "rev-parse", "HEAD"))
    assert worktrees._unmerged_done_work(root, tid)
    assert not worktrees._delete_branch(root, tid, force=True)


def test_b13f_copy_update_merges_the_recorded_branch(done_copy, monkeypatch):
    """Opus #8: `orch copy update` merges the branch the work goes back to, not whatever the project folder
    has checked out (a private branch); a person cannot merge into a copy a live agent works in."""
    root, tid, copy = done_copy
    (root / "shared").write_text("main\n")
    git(root, "add", "shared")
    git(root, "commit", "-qm", "main advances")
    git(root, "checkout", "-q", "-b", "experiment")
    (root / "private-experiment").write_text("x\n")
    git(root, "add", "private-experiment")
    git(root, "commit", "-qm", "experiment")
    monkeypatch.chdir(copy)
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
        with pytest.raises(worktrees.Refused):
            worktrees.update_copy(root, tid)
    worktrees.update_copy(root, tid)
    assert (copy / "shared").exists() and not (copy / "private-experiment").exists()


def test_b13f_one_broken_ticket_never_stops_the_sweep(done_copy, monkeypatch):
    """Fable #13: one ticket that raises is kept (and said); the others are still brought back."""
    root, tid, copy = done_copy
    other = root.tids[1]
    copy2 = make(root, 1)
    (copy2 / "two.py").write_text("2\n")
    to_review(root, tid)
    to_review(root, other)
    real = worktrees._bring_back_locked

    def broken(r, t):
        if t == tid:
            raise RuntimeError("broken ticket")
        return real(r, t)

    monkeypatch.setattr(worktrees, "_bring_back_locked", broken)
    done_no_sweep(root, tid)
    done_no_sweep(root, other)
    notes = worktrees.sweep(root)
    assert tickets.load(root, other)["work"]["bring_back"]["state"] == "merged"
    assert (root / "two.py").exists() and copy.exists()
    assert any("broken ticket" in n for n in notes)


def test_b13f_saving_is_never_cut_by_the_sweep_budget(done_copy, monkeypatch):
    """Fable #14: add and commit start only with some budget left, and then run with their own timeout."""
    import time

    root, tid, copy = done_copy
    seen = []
    real = worktrees.safegit.run

    def run(args, cwd, timeout, **kw):
        if args and args[0] in ("add", "commit"):
            seen.append(timeout)
        return real(args, cwd, timeout, **kw)

    monkeypatch.setattr(worktrees.safegit, "run", run)
    before = getattr(worktrees._ctx, "deadline", None)
    try:
        worktrees._ctx.deadline = time.monotonic() + 2
        assert worktrees._save_leftovers(copy, tid) == (False, BRING_TIME)
        worktrees._ctx.deadline = time.monotonic() + 8
        assert worktrees._save_leftovers(copy, tid)[0]
    finally:
        worktrees._ctx.deadline = before
    assert seen == [worktrees.GIT_ADD_TIMEOUT, worktrees.GIT_ADD_TIMEOUT]


BRING_TIME = "saving needs more time; the next sweep will try again"


def test_b13f_title_cannot_add_commit_trailers(done_copy):
    """Fable #16: the ticket title goes into the merge message as one line."""
    root, tid, copy = done_copy
    tickets.apply_op(
        root, tid, lambda t: t.update(title="Fix\nCo-authored-by: Evil <e@x>"), by=tickets.SYSTEM
    )
    assert finish(root, tid)["state"] == "merged"
    message = git(root, "log", "-1", "--format=%B")
    assert "\n" not in message and message.startswith(f"orch: {tid} Fix")


@pytest.mark.parametrize(
    "setting",
    [("merge.renormalize", "true"), ("merge.directoryRenames", "true"), ("submodule.recurse", "true")],
)
def test_b13f_merge_settings_wait(done_copy, setting):
    """Opus #5: settings that make `git merge` write something else than merge-tree checked."""
    root, tid, copy = done_copy
    git(root, "config", *setting)
    head = git(root, "rev-parse", "HEAD")
    assert finish(root, tid)["reason"] == worktrees.SETTINGS
    assert git(root, "rev-parse", "HEAD") == head


def test_b13f_review_shows_commits_and_files(done_copy, run):
    """Fable #6: the review says how much the tip brings, not only its control paths."""
    import json

    root, tid, copy = done_copy
    (copy / ".gitignore").write_text("something\n")
    assert finish(root, tid)["state"] == "waiting"
    code, out, err = run("copy", "review", tid, "--json")
    assert code == 0, err
    review = json.loads(out)
    assert review["commits"] == 1 and review["files"] == 2


# ---------------------------------------------------------------- B13g (automated HIGH on B13f)


def agent_commits(copy, name="late.py"):
    """The agent's run goes on after the review began and commits one more file in the copy."""
    (copy / name).write_text("late\n")
    git(copy, "add", name)
    git(copy, "commit", "-qm", "late")
    return git(copy, "rev-parse", "HEAD")


def test_b13g_run_end_never_moves_a_recorded_review_tip(done_copy):
    """(a) The person looked at the recorded tip; the agent's run commits more and ends: the new tip is not
    "reviewed". The recorded tip is forgotten (a later run end records nothing either) and the Done waits for
    an explicit approval; nothing is merged."""
    root, tid, copy = done_copy
    to_review(root, tid)
    looked = git(copy, "rev-parse", "HEAD")
    assert worktrees._copy_authority(root, tid)["review_tip"] == looked
    agent_commits(copy)
    worktrees.on_run_ended(root, tid)
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    worktrees.on_run_ended(root, tid)  # one more run ending in this round: still nothing recorded
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    head, before = git(root, "rev-parse", "HEAD"), project_hashes(root)
    result = finish(root, tid)
    assert tickets.load(root, tid)["status"] == "done"
    assert result["state"] == "waiting" and result["reason"] == worktrees.APPROVAL_NEEDED
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert git(root, "rev-parse", "HEAD") == head and project_hashes(root) == before
    assert not (root / "late.py").exists()


def test_b13g_run_end_with_the_same_tip_keeps_it(done_copy):
    """(b) A run that ends without moving the branch keeps the recorded tip: the Done brings it back."""
    root, tid, copy = done_copy
    to_review(root, tid)
    looked = git(copy, "rev-parse", "HEAD")
    known = worktrees._copy_authority(root, tid)
    worktrees.on_run_ended(root, tid)
    after = worktrees._copy_authority(root, tid)
    assert (after["review_tip"], after["review_at"]) == (looked, known["review_at"])
    assert finish(root, tid)["state"] == "merged"
    assert (root / "code.py").read_text() == "print(2)\n"


def test_b13g_agent_done_while_alive_records_at_run_end(done_copy, monkeypatch):
    """(c) The agent's own move to Review while its run is alive records nothing; the tip at the end of
    that run is what the person is shown, and it is recorded then (also after more commits in that run)."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    with monkeypatch.context() as m:
        m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
        tickets.set_status(root, tid, "review", "human:test")
        assert not worktrees._copy_authority(root, tid).get("review_tip")
        last = agent_commits(copy)
    worktrees.on_run_ended(root, tid)
    assert worktrees._copy_authority(root, tid)["review_tip"] == last
    assert finish(root, tid)["state"] == "merged"
    assert (root / "late.py").read_text() == "late\n"


def test_b13g_entering_review_again_replaces_the_tip(done_copy):
    """(d) Only a new round (the ticket enters Review again after more work) replaces the recorded tip,
    also after a run end forgot it."""
    root, tid, copy = done_copy
    to_review(root, tid)
    agent_commits(copy, "one.py")
    worktrees.on_run_ended(root, tid)
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    tickets.set_status(root, tid, "active", "human:test")
    newest = agent_commits(copy, "two.py")
    to_review(root, tid)
    assert worktrees._copy_authority(root, tid)["review_tip"] == newest
    assert finish(root, tid)["state"] == "merged"
    assert (root / "two.py").read_text() == "late\n"


def cli_done(run, root, tid, how, *extra):
    if how == "status":
        return run("ticket", "status", tid, "done", *extra, "--by", "human:pat")
    rev = f"--if-revision={tickets.load(root, tid)['revision']}"
    return run("ticket", "patch", tid, '{"status": "done"}', rev, *extra, "--by", "human:pat")


@pytest.mark.parametrize("how", ["status", "patch"])
def test_b13g_done_on_a_stale_page_needs_approval(done_copy, run, how):
    """(e) The page showed the tip of an earlier round; more work came to Review since. The Done is recorded
    (never blocked), but it approves nothing: the bring-back waits, and the person is told in plain words."""
    root, tid, copy = done_copy
    to_review(root, tid)
    shown = git(copy, "rev-parse", "HEAD")
    tickets.set_status(root, tid, "active", "human:test")
    agent_commits(copy)
    to_review(root, tid)
    assert worktrees._copy_authority(root, tid)["review_tip"] != shown
    head = git(root, "rev-parse", "HEAD")
    code, out, err = cli_done(run, root, tid, how, f"--shown-tip={shown}")
    assert code == 0, err
    assert worktrees.NEW_CHANGES in out
    assert tickets.load(root, tid)["status"] == "done"
    worktrees.sweep(root)
    back = tickets.load(root, tid)["work"]["bring_back"]
    assert back["state"] == "waiting" and back["reason"] == worktrees.NEW_CHANGES
    assert not worktrees._copy_authority(root, tid).get("reviewed_tip")
    assert git(root, "rev-parse", "HEAD") == head and not (root / "late.py").exists()


@pytest.mark.parametrize("how", ["status", "patch"])
def test_b13g_done_on_the_shown_tip_merges(done_copy, run, how):
    """(e) The displayed tip is the recorded one and the branch is still there: the Done brings it back."""
    root, tid, copy = done_copy
    to_review(root, tid)
    shown = worktrees._copy_authority(root, tid)["review_tip"]
    code, out, err = cli_done(run, root, tid, how, f"--shown-tip={shown}")
    assert code == 0, err
    assert worktrees.NEW_CHANGES not in out
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert (root / "code.py").read_text() == "print(2)\n"


def test_b13g_moved_branch_after_display_needs_approval(done_copy, run):
    """(e) The branch moved after the page showed the recorded tip (the run is still going): the Done
    approves nothing, whatever the recorded tip says by the time the sweep looks."""
    root, tid, copy = done_copy
    to_review(root, tid)
    shown = worktrees._copy_authority(root, tid)["review_tip"]
    agent_commits(copy)
    code, out, err = cli_done(run, root, tid, "status", f"--shown-tip={shown}")
    assert code == 0, err
    assert worktrees.NEW_CHANGES in out
    assert not worktrees._copy_authority(root, tid).get("review_tip")
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["reason"] == worktrees.NEW_CHANGES
    assert not (root / "late.py").exists()


@pytest.mark.parametrize("how", ["status", "patch"])
def test_b13g_page_showed_no_tip_later_run_end_tip_is_not_approved(done_copy, run, how):
    """The page showed no review tip (none was recorded: the agent's run was alive); the run ends afterwards
    and records a tip the person never saw. Their Done (sent as --shown-tip=none) approves nothing."""
    root, tid, copy = done_copy
    assert worktrees._save_leftovers(copy, tid)[0]
    with pytest.MonkeyPatch.context() as m:
        m.setattr(worktrees, "_alive_here", lambda *a: {"live": True})
        tickets.set_status(root, tid, "review", "human:test")
        assert not worktrees._copy_authority(root, tid).get("review_tip")
    agent_commits(copy)
    worktrees.on_run_ended(root, tid)
    assert worktrees._copy_authority(root, tid).get("review_tip")
    head = git(root, "rev-parse", "HEAD")
    code, out, err = cli_done(run, root, tid, how, "--shown-tip=none")
    assert code == 0, err
    assert worktrees.NEW_CHANGES in out
    assert tickets.load(root, tid)["status"] == "done"
    worktrees.sweep(root)
    back = tickets.load(root, tid)["work"]["bring_back"]
    assert back["state"] == "waiting" and back["reason"] == worktrees.NEW_CHANGES
    assert git(root, "rev-parse", "HEAD") == head and not (root / "late.py").exists()


def test_b13g_none_with_no_recorded_tip_changes_nothing(done_copy, run):
    root, tid, copy = done_copy
    tickets.set_status(root, tid, "review", "human:test")
    worktrees._copy_authority(root, tid, lambda r: r.pop("review_tip", None))
    code, out, err = cli_done(run, root, tid, "status", "--shown-tip=none")
    assert code == 0, err
    assert worktrees.NEW_CHANGES not in out


@pytest.mark.parametrize(
    "bad", ["HEAD", "a" * 39, "a" * 65, "A" * 40, "g" * 40, " " + "a" * 40, "a" * 40 + "\n", "", "--x"]
)
def test_b13g_forged_displayed_tip_is_ignored(done_copy, run, bad):
    """(f) A displayed tip that is not 40-64 lowercase hex is ignored: the Done is judged as without one."""
    root, tid, copy = done_copy
    to_review(root, tid)
    assert worktrees.bind_shown(root, tid, bad) is True
    assert worktrees._copy_authority(root, tid).get("review_tip")
    code, out, err = cli_done(run, root, tid, "patch", f"--shown-tip={bad}")
    assert code == 0, err
    assert worktrees.NEW_CHANGES not in out
    worktrees.sweep(root)
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"


def test_b13g_displayed_tip_without_a_person_changes_nothing(done_copy, run):
    """Only a person's Done binds a displayed tip: anyone else naming one never forgets the review."""
    root, tid, copy = done_copy
    to_review(root, tid)
    rev = f"--if-revision={tickets.load(root, tid)['revision']}"
    tip = f"--shown-tip={'b' * 40}"
    code, out, err = run("ticket", "patch", tid, '{"status": "done"}', rev, tip, "--by", "agent:test")
    assert worktrees.NEW_CHANGES not in out + err
    assert tickets.load(root, tid)["status"] == "review"  # an agent's Done is no Done
    assert worktrees._copy_authority(root, tid).get("review_tip")


def test_b13h_reopened_while_the_merge_is_prepared_merges_nothing(done_copy, monkeypatch):
    """A reopen during the preparation withdraws the Done: nothing is merged and the next round starts clean."""
    root, tid, copy = done_copy
    to_review(root, tid)
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    head = git(root, "rev-parse", "HEAD")
    real = worktrees._bb_snapshot

    def reopen_then_snapshot(top):
        if tickets.load(root, tid)["status"] == "done":
            tickets.set_status(root, tid, "active", "human:test")
        return real(top)

    monkeypatch.setattr(worktrees, "_bb_snapshot", reopen_then_snapshot)
    worktrees.sweep(root)
    assert tickets.load(root, tid)["status"] == "active"
    assert git(root, "rev-parse", "HEAD") == head and not (root / "code.py").read_text() == "print(2)\n"
    assert not worktrees._copy_authority(root, tid).get("finished")
