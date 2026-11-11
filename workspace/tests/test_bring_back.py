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
    worktrees._record_done_tip(root, tid)
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
    assert handoff["argv"] == ["copy", "retry", tid, "--approve-tip", tip, "--control-paths", str(count)]


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


@pytest.mark.parametrize("invalid", ["expired", "head", "message"])
def test_recovery_needs_fresh_matching_head_and_message(done_copy, invalid):
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
    assert worktrees.bring_back(root, tid)["state"] == "waiting"
    assert project_hashes(root) == before
    assert (root / ".git/MERGE_HEAD").exists()
    assert not journal.exists()


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
