"""ORCH-82: tokens per model from the saved Claude conversations, cached per file, and `orch usage`."""

import json

import pytest

from orch import cli, tickets, usage

SID = "11111111-1111-4111-8111-111111111111"
SID2 = "22222222-2222-4222-8222-222222222222"


def line(model, mid, i, o, cc=0, cr=0, kind="assistant"):
    u = {
        "input_tokens": i,
        "output_tokens": o,
        "cache_creation_input_tokens": cc,
        "cache_read_input_tokens": cr,
    }
    return json.dumps({"type": kind, "message": {"id": mid, "model": model, "usage": u}})


def write(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make(proj, title, sids, up=False, model=None):
    t = tickets.create(proj, title, "human:t")
    raw = tickets.load(proj, t["id"])
    raw["sessions"] = [{"agent": "claude", "id": s} for s in sids]
    if model:
        raw["model"] = {"name": model, "by": "orch"}
    if up:  # as tickets.move_up stores it
        raw["model"]["up"] = {"from": "sonnet", "at": tickets.now(), "by": "agent:claude"}
    tickets._write(proj, raw)
    return tickets.load(proj, t["id"])


@pytest.fixture
def env(proj):
    return {
        "HOME": str(proj.parent / f"{proj.name}_nohome"),
        "CLAUDE_CONFIG_DIR": str(proj.parent / f"{proj.name}_cfg"),
    }


def projects(env):
    return __import__("pathlib").Path(env["CLAUDE_CONFIG_DIR"]) / "projects"


def test_families_and_duplicates_and_subagents(proj, env):
    t = make(proj, "A", [SID])
    p = projects(env)
    write(
        p / "-x-copy" / f"{SID}.jsonl",
        line("claude-opus-5-5", "m1", 10, 1, cc=5, cr=5),
        line("claude-opus-5-5", "m1", 10, 7, cc=5, cr=5),  # same reply again: last usage, once
        line("claude-sonnet-5-5", "m2", 3, 2),
        "not json {{",
        line("claude-opus-5-5", "m3", 1, 1, kind="user"),
        line("weird-model", "m4", 1, 1),
    )
    write(p / "-x-copy" / SID / "subagents" / "a.jsonl", line("claude-haiku-5-5", "h1", 4, 4))
    got = usage.ticket_usage(proj, t, env)
    assert got == {
        "opus": {"in": 20, "out": 7},
        "sonnet": {"in": 3, "out": 2},
        "other": {"in": 1, "out": 1},
        "haiku": {"in": 4, "out": 4},
    }


def test_nothing_and_bad_session_id(proj, env):
    t = make(proj, "A", ["../evil"])
    write(projects(env) / "-p" / "evil.jsonl", line("claude-opus-5-5", "m", 1, 1))
    assert usage.ticket_usage(proj, t, env) == {}
    assert usage.workspace_usage(proj, 30, env)["tickets"] == []


def test_cache_used_until_file_changes(proj, env, monkeypatch):
    t = make(proj, "A", [SID])
    f = write(projects(env) / "-p" / f"{SID}.jsonl", line("claude-opus-5-5", "m1", 1, 1))
    assert usage.ticket_usage(proj, t, env)["opus"] == {"in": 1, "out": 1}
    assert (proj / ".orch" / "run" / usage.CACHE_NAME).is_file()
    calls = []
    real = usage._read_file
    monkeypatch.setattr(usage, "_read_file", lambda p: calls.append(p) or real(p))
    usage.ticket_usage(proj, t, env)
    assert calls == []  # same size and mtime: not read again
    write(f, line("claude-opus-5-5", "m1", 1, 1), line("claude-opus-5-5", "m2", 2, 2))
    assert usage.ticket_usage(proj, t, env)["opus"] == {"in": 3, "out": 3}
    assert len(calls) == 1


def test_workspace_usage(proj, env):
    a = make(proj, "Big", [SID], up=True, model="opus")
    b = make(proj, "Small", [SID2], model="sonnet")
    make(proj, "Quiet", [], model="sonnet")
    write(
        projects(env) / "-p" / f"{SID}.jsonl",
        line("claude-sonnet-5-5", "a", 100, 10),
        line("claude-opus-5-5", "b", 50, 5),
    )
    write(projects(env) / "-p" / f"{SID2}.jsonl", line("claude-sonnet-5-5", "c", 5, 5))
    w = usage.workspace_usage(proj, 30, env)
    assert w["schema"] == "orch.usage/1"
    assert [r["id"] for r in w["tickets"]] == [a["id"], b["id"]]
    assert w["tickets"][0]["moved_up"] is True and w["tickets"][1]["moved_up"] is False
    assert w["tickets"][0]["total"] == 165 and w["tickets"][0]["model"] == "opus"
    assert w["totals"]["sonnet"] == {"in": 105, "out": 15}
    assert w["moved_up"] == 1 and w["with_model"] == 3


def test_cli_json_and_text(proj, env, monkeypatch, capsys):
    make(proj, "Big", [SID], model="opus")
    write(projects(env) / "-p" / f"{SID}.jsonl", line("claude-opus-5-5", "a", 2000, 10))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
    assert cli.main(["usage", "--json"]) == 0
    data = json.loads(capsys.readouterr().out.split("\nNext:")[0])
    assert data["totals"]["opus"] == {"in": 2000, "out": 10}
    assert cli.main(["usage"]) == 0
    out = capsys.readouterr().out
    assert "opus: 2.0k in, 10 out" in out and "Big" in out


def test_empty_text(proj, env, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
    assert cli.main(["usage"]) == 0
    assert "No model use in the last 30 days." in capsys.readouterr().out
