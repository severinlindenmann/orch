"""A read-only ticket (`orch ticket new --read-only`): its run is held to the agent's read-only tool list."""

import json

from orch import adapters, runs, tickets


def new(run, *extra):
    code, out, err = run("ticket", "new", "Look around", "--read-only", *extra, "--json")
    assert code == 0, out + err
    return json.loads(out)["id"]


def test_ticket_new_read_only(proj, run):
    tid = new(run, "--allow-cmd", "insights propose")
    assert tickets.load(proj, tid)["read_only"] == {"allow": ["insights propose"]}
    code, out, _ = run("ticket", "new", "x", "--allow-cmd", "insights propose", "--json")
    assert code == 2
    code, out, _ = run("ticket", "new", "x", "--read-only", "--allow-cmd", "rm -rf /;", "--json")
    assert code == 2


def test_argv_is_held_to_the_read_only_list(proj, run):
    tid = new(run, "--allow-cmd", "insights propose")
    p = runs.plan(proj, tid, mode="live", agent="claude")
    argv = p["argv"]
    head = argv[: argv.index("--")]
    assert p["mode"] == "oneshot" and p["resumed"] is False
    allowed = head[head.index("--allowedTools") + 1]
    assert "Bash(orch insights propose:*)" in allowed and f"Bash(orch log {tid}:*)" in allowed
    assert "orch ticket new" not in allowed and "orch run done" not in allowed
    assert head.count("--allowedTools") == 1 and "--strict-mcp-config" in head
    assert head[head.index("--setting-sources") + 1] == ""
    assert head[head.index("--permission-mode") + 1] == "default"
    for t in ("WebFetch", "Edit", "Write"):
        assert t in head[head.index("--disallowedTools") + 1]


def test_drops_the_flags_that_switch_checks_off():
    argv = [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "auto",
        "--allowedTools",
        "x",
        "--",
        "p",
    ]
    out = adapters.readonly_argv("claude", argv, "t_abc123")
    assert "--dangerously-skip-permissions" not in out and out.count("--permission-mode") == 1
    assert out[-2:] == ["--", "p"]


def test_an_agent_without_a_read_only_list_runs_normally(proj, run):
    tid = new(run)
    assert adapters.readonly("codex") is None and adapters.readonly("generic") is None
    p = runs.plan(proj, tid, agent="codex")
    assert "--strict-mcp-config" not in p["argv"]
    assert runs.fence_cmds(proj, tickets.load(proj, tid), "codex") is None


def test_secret_refuses_in_a_read_only_run(proj, run, monkeypatch):
    tid = new(run)
    monkeypatch.setenv("ORCH_TICKET", tid)
    monkeypatch.setenv("ORCH_AGENT", "claude")
    code, out, err = run("secret", "list", "--json")
    assert code == 2 and "read-only" in (out + err)
    monkeypatch.setenv("ORCH_AGENT", "codex")  # no read-only list for this agent: nothing is fenced
    code, out, err = run("secret", "list", "--json")
    assert "read-only" not in (out + err)
