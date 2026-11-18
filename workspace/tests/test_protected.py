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
        "Host orch-dev\n  HostName 179.237.125.155\n  User deploy\n\n"
        "Host orch-dev-root\n  HostName 179.237.125.155\n  User root\n\nHost other\n  HostName 10.0.0.5\n"
    )
    return tmp_path


def test_list_is_parsed_and_stored(proj):
    assert config.protected_machines(proj) == []
    config.set_protected_machines(proj, "Orch-Dev, 179.237.125.155")
    assert config.protected_machines(proj) == ["orch-dev", "179.237.125.155"]
    config.set_protected_machines(proj, "")
    assert config.protected_machines(proj) == []
    with pytest.raises(Refused):
        config.set_protected_machines(proj, "bad name!;rm")


@pytest.mark.parametrize(
    "cmd",
    [
        "ssh orch-dev 'pytest tests/'",
        "ssh deploy@orch-dev ls",
        "ssh -i key -p 22 root@179.237.125.155 uptime",
        "scp file deploy@orch-dev:/tmp/",
        "rsync -av ./out/ orch-dev-root:/srv/",
        "cd x && /usr/bin/ssh orch-dev true",
        "bash -c \"echo hi; ssh orch-dev 'pytest'\"",
        "ssh ssh://deploy@orch-dev/",
    ],
)
def test_connections_to_a_listed_machine_are_found(cmd, home):
    assert protected.find_target(cmd, ["orch-dev"], home) in {"orch-dev", "179.237.125.155", "orch-dev-root"}


@pytest.mark.parametrize(
    "cmd",
    [
        "ssh other uptime",
        "ssh other uptime; echo orch-dev",
        "grep orch-dev notes.md",
        "git push",
        "ssh-add key",
        "ls",
    ],
)
def test_other_commands_pass(cmd, home):
    assert protected.find_target(cmd, ["orch-dev"], home) is None


def test_no_list_means_no_refusal(home):
    assert protected.find_target("ssh orch-dev ls", [], home) is None


def test_deploy_step_may_connect(proj, home):
    config.set_protected_machines(proj, "orch-dev")
    t = tickets.create(proj, "Ship it", "human:t")
    tickets.check_add(proj, t["id"], "Run the tests", "agent:x")
    tickets.check_add(proj, t["id"], "Deploy the relay", "agent:x")
    tickets.check_start(proj, t["id"], "c1", "agent:x")
    why = protected.verdict(proj, "ssh orch-dev ls", t["id"], home)
    assert why and "orch-dev" in why and "protected machine" in why
    tickets.check_start(proj, t["id"], "c2", "agent:x")
    assert protected.verdict(proj, "ssh orch-dev ls", t["id"], home) is None
    assert protected.verdict(proj, "ssh other ls", t["id"], home) is None


def run_hook(monkeypatch, capsys, payload, root, ticket):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setenv("ORCH_ROOT", str(root))
    monkeypatch.setenv("ORCH_TICKET", ticket)
    assert protected.hook_main(["protected-check", "--hook", "claude"]) == 0
    return capsys.readouterr().out


def test_hook_answers_with_a_refusal(proj, monkeypatch, capsys):
    config.set_protected_machines(proj, "orch-dev")
    t = tickets.create(proj, "Try", "human:t")
    bash = {"tool_name": "Bash", "tool_input": {"command": "ssh orch-dev pytest"}, "cwd": str(proj)}
    out = json.loads(run_hook(monkeypatch, capsys, bash, proj, t["id"]))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "protected machine" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ok = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(proj)}
    assert run_hook(monkeypatch, capsys, ok, proj, t["id"]) == ""
    read = {"tool_name": "Read", "tool_input": {"file_path": "orch-dev"}}
    assert run_hook(monkeypatch, capsys, read, proj, t["id"]) == ""


def test_hook_is_wired_before_bash_only():
    doc = adapters.reminder_doc("claude")
    if doc is None:
        pytest.skip("hooks not importable here")
    groups = doc["hooks"]["PreToolUse"]
    guards = [g for g in groups if "protected-check" in g["hooks"][0]["command"]]
    assert len(guards) == 1 and guards[0]["matcher"] == "Bash"


def test_a_question_never_offers_a_protected_machine_for_tests(proj, home, monkeypatch):
    monkeypatch.setattr(protected, "_ssh_aliases", lambda h=None: _aliases(home))
    config.set_protected_machines(proj, "orch-dev")
    t = tickets.create(proj, "Linux", "human:t")
    with pytest.raises(Refused, match="protected machine"):
        tickets.ask(
            proj,
            t["id"],
            "Which machine may it use?",
            ["orch-dev", "A throwaway server"],
            "orch-dev",
            "agent:x",
        )
    with pytest.raises(Refused, match="protected machine"):
        tickets.ask(proj, t["id"], "Run the tests on orch-dev?", ["yes", "no"], None, "agent:x")
    # an unrelated question, and a machine that is not listed, pass
    tickets.ask(proj, t["id"], "Which machine may it use?", ["other-box", "CI"], "CI", "agent:x")
    tickets.ask(proj, t["id"], "Ship release 4 to orch-dev?", ["yes", "no"], "yes", "agent:x")


def _aliases(home):
    return {"orch-dev": "179.237.125.155"}


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
