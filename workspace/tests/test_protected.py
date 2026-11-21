"""Protected machines: the list, the guard on a helper's ssh/scp/rsync, and the hook answer."""

import io
import json
import sys

import pytest

from orch import adapters, config, protected, tickets
from orch.errors import Refused


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text(
        "Host hostinger\n  HostName 2.24.146.133\n  User deploy\n\n"
        "Host hostinger-root\n  HostName 2.24.146.133\n  User root\n\nHost other\n  HostName 10.0.0.5\n"
    )
    return tmp_path


def test_list_is_parsed_and_stored(proj):
    assert config.protected_machines(proj) == []
    config.set_protected_machines(proj, "Hostinger, 2.24.146.133")
    assert config.protected_machines(proj) == ["hostinger", "2.24.146.133"]
    config.set_protected_machines(proj, "")
    assert config.protected_machines(proj) == []
    with pytest.raises(Refused):
        config.set_protected_machines(proj, "bad name!;rm")


@pytest.mark.parametrize(
    "cmd",
    [
        "ssh hostinger 'pytest tests/'",
        "ssh deploy@hostinger ls",
        "ssh -i key -p 22 root@2.24.146.133 uptime",
        "scp file deploy@hostinger:/tmp/",
        "rsync -av ./out/ hostinger-root:/srv/",
        "cd x && /usr/bin/ssh hostinger true",
        "bash -c \"echo hi; ssh hostinger 'pytest'\"",
        "ssh ssh://deploy@hostinger/",
    ],
)
def test_connections_to_a_listed_machine_are_found(cmd, home):
    assert protected.find_target(cmd, ["hostinger"], home) in {"hostinger", "2.24.146.133", "hostinger-root"}


@pytest.mark.parametrize(
    "cmd",
    [
        "ssh other uptime",
        "ssh other uptime; echo hostinger",
        "grep hostinger notes.md",
        "git push",
        "ssh-add key",
        "ls",
    ],
)
def test_other_commands_pass(cmd, home):
    assert protected.find_target(cmd, ["hostinger"], home) is None


def test_no_list_means_no_refusal(home):
    assert protected.find_target("ssh hostinger ls", [], home) is None


def test_deploy_step_may_connect(proj, home):
    config.set_protected_machines(proj, "hostinger")
    t = tickets.create(proj, "Ship it", "human:t")
    tickets.check_add(proj, t["id"], "Run the tests", "agent:x")
    tickets.check_add(proj, t["id"], "Deploy the relay", "agent:x")
    tickets.check_start(proj, t["id"], "c1", "agent:x")
    why = protected.verdict(proj, "ssh hostinger ls", t["id"], home)
    assert why and "hostinger" in why and "protected machine" in why
    tickets.check_start(proj, t["id"], "c2", "agent:x")
    assert protected.verdict(proj, "ssh hostinger ls", t["id"], home) is None
    assert protected.verdict(proj, "ssh other ls", t["id"], home) is None


def run_hook(monkeypatch, capsys, payload, root, ticket):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setenv("ORCH_ROOT", str(root))
    monkeypatch.setenv("ORCH_TICKET", ticket)
    assert protected.hook_main(["protected-check", "--hook", "claude"]) == 0
    return capsys.readouterr().out


def test_hook_answers_with_a_refusal(proj, monkeypatch, capsys):
    config.set_protected_machines(proj, "hostinger")
    t = tickets.create(proj, "Try", "human:t")
    bash = {"tool_name": "Bash", "tool_input": {"command": "ssh hostinger pytest"}, "cwd": str(proj)}
    out = json.loads(run_hook(monkeypatch, capsys, bash, proj, t["id"]))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "protected machine" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ok = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(proj)}
    assert run_hook(monkeypatch, capsys, ok, proj, t["id"]) == ""
    read = {"tool_name": "Read", "tool_input": {"file_path": "hostinger"}}
    assert run_hook(monkeypatch, capsys, read, proj, t["id"]) == ""


def test_hook_is_wired_before_bash_only(monkeypatch):
    """Where the record hook runs (POSIX) the guard is part of it (`orch record hook --with claude`, one
    process per tool event, ORCH-634; the guard itself answers only for Bash); without it (Windows) its own
    group, Bash only."""
    monkeypatch.setattr(adapters, "_is_windows", lambda: False)
    doc = adapters.reminder_doc("claude")
    if doc is None:
        pytest.skip("hooks not importable here")
    groups = doc["hooks"]["PreToolUse"]
    assert [g["hooks"][0]["command"].split(" -m orch ")[1] for g in groups] == ["record hook --with claude"]
    monkeypatch.setattr(adapters, "_is_windows", lambda: True)
    groups = adapters.reminder_doc("claude")["hooks"]["PreToolUse"]
    guards = [g for g in groups if "protected-check" in g["hooks"][0]["command"]]
    assert len(guards) == 1 and guards[0]["matcher"] == "Bash" and len(groups) == 1


def test_the_record_hook_with_the_tool_answers_the_guard_too(proj, monkeypatch, capsys):
    """`orch record hook --with claude` (ORCH-634): one process reads the payload once, records (here:
    nothing, not inside a run) and still refuses the command for a protected machine, exit 0 as every hook."""
    from orch import cli_record

    config.set_protected_machines(proj, "hostinger")
    t = tickets.create(proj, "Try", "human:t")
    monkeypatch.setenv("ORCH_ROOT", str(proj))
    monkeypatch.setenv("ORCH_TICKET", t["id"])

    def hook(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload) + "\n"))
        assert cli_record.hook_main(["record", "hook", "--with", "claude"]) == 0
        return capsys.readouterr().out

    bash = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(proj),
            "tool_input": {"command": "ssh hostinger pytest"}, "tool_use_id": "toolu_x1"}  # fmt: skip
    out = json.loads(hook(bash))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook({**bash, "tool_input": {"command": "ls"}}) == ""
    # a payload written over several lines is read whole: still refused
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(bash, indent=2) + "\n"))
    assert cli_record.hook_main(["record", "hook", "--with", "claude"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook({**bash, "hook_event_name": "PostToolUse", "tool_response": {"stdout": "x"}}) == ""
    assert (
        hook({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "hostinger"}})
        == ""
    )


def test_a_question_never_offers_a_protected_machine_for_tests(proj, home, monkeypatch):
    monkeypatch.setattr(protected, "_ssh_aliases", lambda h=None: _aliases(home))
    config.set_protected_machines(proj, "hostinger")
    t = tickets.create(proj, "Linux", "human:t")
    with pytest.raises(Refused, match="protected machine"):
        tickets.ask(
            proj,
            t["id"],
            "Which machine may it use?",
            ["hostinger", "A throwaway server"],
            "hostinger",
            "agent:x",
        )
    with pytest.raises(Refused, match="protected machine"):
        tickets.ask(proj, t["id"], "Run the tests on hostinger?", ["yes", "no"], None, "agent:x")
    # an unrelated question, and a machine that is not listed, pass
    tickets.ask(proj, t["id"], "Which machine may it use?", ["other-box", "CI"], "CI", "agent:x")
    tickets.ask(proj, t["id"], "Ship release 4 to hostinger?", ["yes", "no"], "yes", "agent:x")


def _aliases(home):
    return {"hostinger": "2.24.146.133"}


def test_a_skip_question_must_say_where_it_would_run(proj):
    t = tickets.create(proj, "Linux", "human:t")
    tickets.check_add(proj, t["id"], "Real Linux run", "agent:x")
    with pytest.raises(Refused, match="where it would run"):
        tickets.ask(proj, t["id"], "Mark step c1 as won't do?", ["yes", "no"], "yes", "agent:x", check="c1")
    tickets.ask(
        proj,
        t["id"],
        "Mark step c1 as won't do?",
        ["yes", "No, run it in CI"],
        "No, run it in CI",
        "agent:x",
        check="c1",
    )
