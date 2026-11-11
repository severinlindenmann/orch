"""B13 prerequisites: special attributes must be inspected before any merge."""

import hashlib
import subprocess

import pytest
from test_worktrees_cleanup import git, make
from test_worktrees_cleanup import repo as repo_fixture

from orch import tickets, worktrees

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


def test_clean_merge(done_copy):
    root, tid, copy = done_copy
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    assert (root / "code.py").read_text() == "print(2)\n"
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert not copy.exists()
    assert not git(root, "branch", "--list", f"orch/{tid}")


def test_dirty_overlap_keeps_bytes(done_copy):
    root, tid, copy = done_copy
    (root / "code.py").write_bytes(b"person's uncommitted bytes\n")
    before = hashlib.sha256((root / "code.py").read_bytes()).hexdigest()
    tickets.set_status(root, tid, "done", "human:test", proven=True)
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
    tickets.set_status(root, tid, "done", "human:test", proven=True)
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
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    assert (root / "code.py").read_text() == "print(2)\n"
    monkeypatch.setattr(worktrees, "_bb_state", real)
    worktrees.on_run_ended(root, tid)
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


def test_journal_recovery(done_copy, monkeypatch):
    root, tid, copy = done_copy
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    real = worktrees._bb_merge

    def crash(top, args):
        if args == ["merge", "--abort"]:
            raise RuntimeError("killed before abort")
        return real(top, args)

    monkeypatch.setattr(worktrees, "_bb_merge", crash)
    before = project_hashes(root)
    tickets.set_status(root, tid, "done", "human:test", proven=True)
    assert (root / ".git/MERGE_HEAD").exists()
    monkeypatch.setattr(worktrees, "_bb_merge", real)
    assert worktrees.bring_back(root, tid)["state"] == "waiting"
    assert project_hashes(root) == before
    assert not (root / ".git/MERGE_HEAD").exists()
    assert copy.exists()


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
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
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
    (root / "code.py").write_text("conflicting main\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "main")
    with monkeypatch.context() as m:
        m.setattr(worktrees, "on_closed", lambda *a: None)
        tickets.set_status(root, tid, "done", "human:test", proven=True)
    before = project_hashes(root)
    # A fresh interpreter uses the same isolated fixture home and its test-only
    # pairing, with a different lock owner. Never fork a threaded pytest worker.
    script = """
import os, signal, sys
from pathlib import Path
from orch import addons, humanproof, worktrees
home = Path(os.environ["ORCH_HOME"])
addons.real_home = lambda: home.parent
humanproof.guarded_home = lambda root: home
real = worktrees._bb_merge
def killed(top, args):
    if args == ["merge", "--abort"]:
        os.kill(os.getpid(), signal.SIGKILL)
    return real(top, args)
worktrees._bb_merge = killed
worktrees.bring_back(Path(sys.argv[1]), sys.argv[2])
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(root), tid],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr
    assert (root / ".git/MERGE_HEAD").exists()
    result = worktrees.bring_back(root, tid)
    assert result["state"] == "waiting"
    assert "ask the agent" in result["reason"]
    assert project_hashes(root) == before
    assert not (root / ".git/MERGE_HEAD").exists()
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
    tickets.apply_op(root, tid, lambda t: t["work"].update(bring_back={"state": "merged"}))
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
    assert tickets.load(root, tid)["work"]["bring_back"]["state"] == "merged"
    assert (root / "code.py").read_text() == "print(2)\n"
    assert not copy.exists()
