"""ORCH-818: the Manager, Empty and Chat helper start in a chosen permission mode, within what the workspace
allows, remembered per kind; raising it needs the signed-in person."""

import os

import pytest

from orch import adapters, config, manager, ownerpick, runs, runs_live, sessionmode, sessions, tickets
from orch.errors import Refused


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(adapters, "chosen", lambda root: "claude")


@pytest.fixture
def fake_start(monkeypatch, claude):
    started, stopped, modes = [], [], {}

    def start(root, tid, by, fresh=False, mode=None, **kw):
        started.append(tid)
        modes[tid] = sessionmode.for_ticket(root, tickets.load(root, tid))
        return {"run": "r_x", "notes": []}

    def stop(root, tid, hold=False):
        stopped.append(tid)
        started.remove(tid)
        return True

    monkeypatch.setattr(runs, "start", start)
    monkeypatch.setattr(runs_live, "stop", stop)
    monkeypatch.setattr(runs, "running", lambda root, tid: tid in started)
    monkeypatch.setattr(
        runs, "read", lambda root, tid: {"permissions": modes.get(tid)} if tid in modes else None
    )
    monkeypatch.setattr(
        manager,
        "start",
        lambda root, by, fresh=False, **kw: {
            **start(root, tickets.ensure_manager(root, by), by),
            "started": True,
        },
    )
    return {"started": started, "stopped": stopped, "modes": modes}


def test_the_ladder_and_the_workspace_cap(proj, claude):
    assert config.permissions(proj) == "auto"
    assert sessionmode.current(proj, "manager") == "auto"  # nothing remembered: the workspace setting
    assert [sessionmode.allowed(proj, m) for m in sessionmode.MODES] == [True, True, True, False]
    off = sessionmode.offer(proj, "manager")
    assert [(c["label"], c["allowed"]) for c in off["choices"]] == [
        ("Default", True),
        ("Accept edits", True),
        ("Auto", True),
        ("Bypass permissions", False),
    ]
    assert off["current"] == "auto" and off["label"] == "Auto" and off["full_warned"] is False


def test_bypass_is_refused_when_the_workspace_does_not_allow_it(proj, fake_start):
    with pytest.raises(Refused, match="Bypass permissions is not allowed in this workspace"):
        sessions.new(proj, "manager", "human:t", mode="full", person=True)
    assert fake_start["started"] == [] and sessionmode.remembered(proj, "manager") is None


def test_the_manager_starts_in_auto_and_in_bypass_when_allowed(proj, fake_start):
    d = sessions.new(proj, "manager", "human:t", mode="auto", person=True)
    mid = tickets.manager_id(proj)
    assert d["started"] and fake_start["modes"][mid] == "auto"
    assert d["permissions"]["running_label"] == "Auto"
    config.set_permissions(proj, "full")
    d = sessions.new(proj, "manager", "human:t", mode="full", person=True)
    # on in auto: ends and goes on in bypass, the same conversation (a resume, not --fresh)
    assert fake_start["stopped"] == [mid] and fake_start["modes"][mid] == "full"
    assert d["permissions"]["running_label"] == "Bypass permissions"
    assert any("goes on in Bypass permissions" in n for n in d["notes"])
    assert sessionmode.remembered(proj, "manager") == "full" and sessionmode.full_warned(proj)


def test_the_choice_is_remembered_per_kind_and_used_by_every_later_start(proj, fake_start):
    sessions.new(proj, "empty", "human:t", mode="ask")
    assert sessionmode.remembered(proj, "empty") == "ask" and sessionmode.remembered(proj, "chat") is None
    eid = tickets.session_id(proj, "empty")
    assert sessionmode.for_ticket(proj, tickets.load(proj, eid)) == "ask"
    gid = tickets.ensure_general(proj, "human:t")
    assert sessionmode.for_ticket(proj, tickets.load(proj, gid)) == "auto"
    work = tickets.create(proj, "A piece of work", "human:t")["id"]
    assert sessionmode.for_ticket(proj, tickets.load(proj, work)) is None  # the workspace setting, as before


def test_raising_needs_the_signed_in_person(proj, fake_start):
    sessions.new(proj, "manager", "agent:claude", mode="ask")  # lowering: anyone
    with pytest.raises(Refused, match="Only the signed-in person can raise the Manager to Auto"):
        sessions.new(proj, "manager", "agent:claude", mode="auto")
    with pytest.raises(Refused, match="Only the signed-in person"):
        sessions.new(proj, "manager", "human:owner", mode="edits")  # a terminal or phone without the grant
    assert sessionmode.remembered(proj, "manager") == "ask"
    sessions.new(proj, "manager", "human:owner", mode="auto", person=True)
    assert sessionmode.remembered(proj, "manager") == "auto"
    sessions.new(proj, "manager", "agent:claude", mode="auto")  # keeping it: fine


def test_a_lowered_workspace_caps_a_remembered_mode(proj, fake_start):
    config.set_permissions(proj, "full")
    sessions.new(proj, "manager", "human:t", mode="full", person=True)
    config.set_permissions(proj, "ask")
    assert sessionmode.current(proj, "manager") == "ask"
    mid = tickets.manager_id(proj)
    assert sessionmode.for_ticket(proj, tickets.load(proj, mid)) == "ask"


def test_the_plain_terminal_has_no_mode(proj, fake_start):
    with pytest.raises(Refused, match="no permission mode"):
        sessions.new(proj, "terminal", "human:t", mode="ask")
    assert "permissions" not in sessions.new(proj, "terminal", "human:t")


def test_the_remembered_modes_live_in_the_orch_home_not_the_workspace(proj, fake_start):
    sessions.new(proj, "chat", "human:t", mode="edits")
    f = sessionmode._file()
    assert f.is_file() and proj.resolve() not in f.resolve().parents
    if os.name != "nt":
        assert (f.stat().st_mode & 0o777) == 0o600


def test_codex_gets_its_own_levels(proj, monkeypatch):
    monkeypatch.setattr(adapters, "chosen", lambda root: "codex")
    off = sessionmode.offer(proj, "empty", "codex")
    assert [c["label"] for c in off["choices"]] == ["This folder only", "Full access"]
    assert off["current"] == "ask" and off["label"] == "This folder only"  # auto: the workspace level
    assert (
        sessionmode.tool_mode("codex", "edits") == "ask" and sessionmode.tool_mode("codex", "full") == "full"
    )


def test_claude_accept_edits_flags(proj):
    argv = adapters.render(
        "claude", "fresh", "live", {"new_session": "s", "orch_hooks_file": "h", "permissions": "edits"}, proj
    )
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits" and "--dangerously-skip-permissions" not in argv
    assert "Bash(orch private:*)" in argv[argv.index("--disallowedTools") + 1]


def test_the_cli_takes_no_grant_from_a_helper_shell(proj, fake_start, run, monkeypatch):
    sessions.new(proj, "empty", "human:t", mode="ask")
    monkeypatch.setattr(ownerpick, "person_granted", lambda root, by: False)
    code, _out, err = run("session", "new", "empty", "--permission-mode", "auto")
    assert code == 2 and "Only the signed-in person" in err
    assert sessionmode.remembered(proj, "empty") == "ask"


def test_a_tool_whose_choices_are_all_higher_never_gets_more(proj, monkeypatch):
    real = adapters.load

    def only_full(name, root=None):
        a = real(name, root)
        a["permission_choices"] = [{"mode": "full", "label": "Full access"}]
        return a

    monkeypatch.setattr(adapters, "load", only_full)
    assert sessionmode.tool_mode("codex", "ask") == "ask"
