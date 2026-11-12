import json
from pathlib import Path

import pytest

from orch_dashboard import actions, data


def test_ask_update_uses_copy_command():
    argv = actions.build_argv("copies.ask-update", {"ticket": "t_abcdef"})
    assert argv[:3] == ["copy", "ask-update", "t_abcdef"]
    with pytest.raises(actions.BadRequest):
        actions.build_argv("copies.ask-update", {"ticket": "../bad"})


def test_waiting_state_reaches_ticket_status_line(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[3] / "contracts/examples/ticket/valid-bring-back.json"
    ticket = json.loads(example.read_text())
    monkeypatch.setattr(data, "run_orch", lambda *a: [ticket])
    rows, skipped = data.load_tickets(tmp_path, "orch")
    assert skipped == 0
    assert rows[0]["bring_back"] == {
        "state": "waiting",
        "reason": "your folder has changes in the same places",
        "reason_code": "waiting",
    }


def test_approve_binds_ticket_tip_and_control_count():
    from orch_dashboard import actions

    args = {"ticket": "t_abcdef", "tip": "a" * 40, "control_paths": 2, "paths_hash": "12345678"}
    argv = actions.build_argv("copies.approve", args)
    # The displayed tip, count and path hash travel with the click (the core compares them with now).
    assert argv[:9] == [
        "copy",
        "retry",
        "t_abcdef",
        "--approve-tip",
        "a" * 40,
        "--control-paths",
        "2",
        "--paths-hash",
        "12345678",
    ]
    op, target = actions.PROOF_OPS["copies.approve"]
    assert op == "copy.retry"
    assert target(args) == f"approve:t_abcdef:{'a' * 40}:2:12345678"
    for bad in ({**args, "control_paths": True}, {**args, "tip": "HEAD"}, {**args, "paths_hash": "x"}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("copies.approve", bad)


def test_hostile_path_names_come_out_plain():
    hostile = [
        '.claude/x\n\n0 control paths. Approve? "yes"',
        ".orch/\x1b[2Jcfg\u2028line",
        ".github/" + "y" * 300,
    ]
    review = {"tip": "b" * 40, "control_paths": 7, "paths_hash": "abcdef12", "paths": hostile}
    view = data._bring_back_view({"state": "waiting", "reason": "r\nx", "reason_code": "controls"}, review)
    assert view["control_paths"] == 7 and view["paths_more"] == 4
    for text in [*view["paths"], view["paths_summary"], view["reason"]]:
        assert not any(c in text for c in '\n\r\x1b\u2028"'), text
    assert view["paths"][0] == ".claude/x 0 control paths. Approve? 'yes'"
    assert len(view["paths"][2]) <= 121
    assert view["paths_summary"].endswith("and 4 more")


def test_review_size_is_shown_only_as_plain_counts():
    """B13f (Fable #6): the dialog shows how much the tip brings (commits, files), never agent text."""
    review = {"tip": "b" * 40, "control_paths": 0, "paths_hash": "abcdef12", "commits": 3, "files": 12}
    view = data._bring_back_view({"state": "waiting", "reason": "x", "reason_code": "approval"}, review)
    assert (view["commits"], view["files"]) == (3, 12)
    for bad in ("3", True, -1, None, "<b>"):
        view = data._bring_back_view({"state": "waiting"}, {**review, "commits": bad, "files": bad})
        assert "commits" not in view and "files" not in view


@pytest.mark.parametrize(
    "review",
    [
        {"tip": "a" * 40, "control_paths": True, "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": "2", "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": -1, "paths_hash": "12345678"},
        {"tip": "nope", "control_paths": 0, "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": 0},
        ["not", "a", "review"],
    ],
)
def test_malformed_review_offers_no_approval(review):
    view = data._bring_back_view({"state": "waiting", "reason": "x", "reason_code": "<b>"}, review)
    assert "tip" not in view
    assert view["reason_code"] == "waiting"


def test_done_click_sends_the_displayed_review_tip():
    """B13g: "Accept" sends the review tip the page showed; the core binds the Done to it."""
    args = {"ticket": "t_abcdef", "data": {"status": "done"}, "if_revision": 3, "review_tip": "a" * 40}
    argv = actions.build_argv("ticket.patch", args)
    assert argv[:4] == ["ticket", "patch", "t_abcdef", "--if-revision=3"]
    assert f"--shown-tip={'a' * 40}" in argv
    assert actions.proof_for("ticket.patch", args) == ("ticket.verdict", "t_abcdef")  # same proof as before
    assert "--shown-tip=" + "b" * 64 in actions.build_argv("ticket.patch", {**args, "review_tip": "b" * 64})
    other = actions.build_argv("ticket.patch", {**args, "data": {"status": "active"}})
    assert not any(a.startswith("--shown-tip") for a in other)
    assert "--shown-tip=none" in actions.build_argv("ticket.patch", {**args, "review_tip": "none"})


@pytest.mark.parametrize(
    "bad", ["HEAD", "a" * 39, "a" * 65, "A" * 40, "g" * 40, "a" * 40 + "\n", "--x", "", None, 7, ["a" * 40]]
)
def test_forged_displayed_tip_is_ignored(bad):
    """B13g (f): a tip that is not 40-64 lowercase hex never reaches the command: the Done is judged as
    without one (no error, the person's Done is never blocked)."""
    args = {"ticket": "t_abcdef", "data": {"status": "done"}, "if_revision": 3, "review_tip": bad}
    argv = actions.build_argv("ticket.patch", args)
    assert not any(str(a).startswith("--shown-tip") for a in argv)
    assert argv[-1] == json.dumps({"status": "done"})


def test_ticket_in_review_shows_the_recorded_review_tip(tmp_path, monkeypatch):
    """B13g: the ticket view gets the review tip from the core's signed record; a value written into the
    ticket file (agent-writable) is never shown."""
    from orch import worktrees

    base = {"schema": "orch.ticket/1", "title": "T"}
    rows_in = [
        {**base, "id": "t_review1", "status": "review", "review_tip": "f" * 40},
        {**base, "id": "t_review2", "status": "review"},
        {**base, "id": "t_active1", "status": "active", "review_tip": "f" * 40},
    ]
    monkeypatch.setattr(data, "run_orch", lambda *a: json.loads(json.dumps(rows_in)))
    recorded = {"t_review1": "c" * 40, "t_review2": None, "t_active1": "d" * 40}
    monkeypatch.setattr(worktrees, "work_branches", lambda root: set())
    monkeypatch.setattr(worktrees, "review_tip", lambda root, tid, branches=None: recorded[tid])
    rows, _ = data.load_tickets(tmp_path, "orch")
    by_id = {r["id"]: r for r in rows}
    assert by_id["t_review1"]["review_tip"] == "c" * 40
    assert "review_tip" not in by_id["t_review2"]
    assert "review_tip" not in by_id["t_active1"]
    monkeypatch.setattr(worktrees, "review_tip", lambda root, tid, branches=None: "<b>not a tip</b>")
    rows, _ = data.load_tickets(tmp_path, "orch")
    assert all("review_tip" not in r for r in rows)


def test_review_metadata_comes_from_core_command(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[3] / "contracts/examples/ticket/valid-bring-back.json"
    ticket = json.loads(example.read_text())
    seen = []

    def core(binary, args, root):
        seen.append(args)
        return (
            [ticket]
            if args[0] == "ticket"
            else {
                "tip": "a" * 40,
                "control_paths": 2,
                "paths_hash": "12345678",
                "paths_summary": ".orch/a, .orch/b",
            }
        )

    monkeypatch.setattr(data, "run_orch", core)
    rows, _ = data.load_tickets(tmp_path, "orch")
    assert rows[0]["bring_back"]["tip"] == "a" * 40
    assert rows[0]["bring_back"]["control_paths"] == 2
    assert rows[0]["bring_back"]["paths_hash"] == "12345678"
    assert seen[-1] == ["copy", "review", ticket["id"], "--json"]


def test_load_state_with_100_tickets_in_review_makes_at_most_two_git_calls(tmp_path, monkeypatch):
    """Lane C blocker: one git call per ticket made /api/state take seconds. Now at most one (the work branches,
    read once per load), and none at all while copies are off."""
    from orch import config, safegit, worktrees

    base = {"schema": "orch.ticket/1", "title": "T", "status": "review"}
    rows_in = [{**base, "id": f"t_rev{i:04d}"} for i in range(100)]
    monkeypatch.setattr(data, "run_orch", lambda *a: json.loads(json.dumps(rows_in)))
    monkeypatch.setattr(worktrees, "registry", lambda root: {})
    monkeypatch.setattr(worktrees, "_copy_authority", lambda *a, **k: {})
    calls = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: calls.append(argv) or (0, "", "")
    )
    monkeypatch.setattr(safegit, "git_exe", lambda cwd, root=None: "/usr/bin/git")
    for mode, most in (("together", 1), ("off", 0)):
        calls.clear()
        monkeypatch.setattr(config, "copies_mode", lambda root, m=mode: m)
        rows, _ = data.load_tickets(tmp_path, "orch")
        assert len(rows) == 100
        git_calls = [a for a in calls if "git" in str(a[0])]
        assert len(git_calls) <= 2 and len(git_calls) <= most + 1, (mode, len(git_calls))
