"""A Start must show progress: the tool may run orch, one-shot output streams, a live tool stuck on a
first screen (trust this folder) is explained instead of "working", a never-pasted prompt is never nested,
attach explains a one-shot run."""

import json
import os
import shutil
import subprocess
import time

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import adapters, config, runs, runs_live, tickets

TRUST_SCREEN = """ Accessing workspace:
 Quick safety check: Is this a project you created or one you trust?
 ❯ No, exit
   Yes, I trust this folder
 Enter to confirm · Esc to cancel"""


def _ticket(run, title="A presentation about giraffes"):
    return json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]


def _no_tmux(monkeypatch):
    real = shutil.which
    monkeypatch.setattr(
        runs_live.shutil, "which", lambda n, *a, **k: None if n == "tmux" else real(n, *a, **k)
    )


def _valid_run(rec):
    schema = json.loads((CONTRACTS / "run.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(rec)


# ---------------------------------------------------------------- what the agent is told and allowed


def test_the_start_prompt_asks_for_tasks_and_a_summary(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    p = runs.plan(proj, tid)
    assert f"orch check add {tid}" in p["prompt"] and f"orch ticket summary {tid}" in p["prompt"]
    assert f"orch check done {tid}" in p["prompt"]


def test_a_one_shot_claude_streams_and_may_run_orch(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    argv = runs.plan(proj, tid, mode="oneshot")["argv"]
    head = argv[: argv.index("--")]
    assert head[head.index("--output-format") + 1] == "stream-json"
    rules = head[head.index("--allowedTools") + 1].split(",")
    assert "Bash(orch check:*)" in rules and "Bash(orch ticket summary:*)" in rules
    assert not [
        r for r in rules if r.startswith(("Bash(orch config", "Bash(orch addon", "Bash(orch run start"))
    ]


def test_a_tool_without_a_stream_gets_no_stream_args(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "codex")
    assert "--output-format" not in runs.plan(proj, tid, mode="oneshot")["argv"]


# ---------------------------------------------------------------- folder trust (adapter data only)


def _cfg(proj):
    return proj.parent / f"{proj.name}_home" / ".claude.json"


def test_trust_only_for_a_folder_set_up_with_orch_init(proj, tmp_path):
    f = _cfg(proj)
    f.write_text(json.dumps({"theme": "dark"}))
    other = tmp_path / "not-a-workspace"
    other.mkdir()
    assert adapters.trust_folder("claude", other) == "skipped"
    assert json.loads(f.read_text()) == {"theme": "dark"}


def test_trust_sets_only_the_one_key_and_keeps_the_rest(proj, run):
    run("init", "--yes")
    f = _cfg(proj)
    f.write_text(json.dumps({"theme": "dark", "projects": {"/other": {"x": 1}}}))
    f.chmod(0o600)
    assert adapters.trust_folder("claude", proj) == "set"
    doc = json.loads(f.read_text())
    assert doc["theme"] == "dark" and doc["projects"]["/other"] == {"x": 1}
    assert doc["projects"][str(proj.resolve())] == {"hasTrustDialogAccepted": True}
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert adapters.trust_folder("claude", proj) == "already"
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]


def test_trust_never_touches_a_missing_or_unreadable_file(proj, run):
    run("init", "--yes")
    f = _cfg(proj)
    assert adapters.trust_folder("claude", proj) == "skipped" and not f.exists()
    f.write_text("{not json")
    assert adapters.trust_folder("claude", proj) == "skipped" and f.read_text() == "{not json"


def test_trust_never_clobbers_a_write_by_the_tool(proj, run, monkeypatch):
    run("init", "--yes")
    f = _cfg(proj)
    f.write_text(json.dumps({"n": 0}))
    real_dump = json.dump
    n = {"i": 0}

    def tool_writes_meanwhile(doc, out, **kw):
        n["i"] += 1
        f.write_text(json.dumps({"n": n["i"]}))  # the tool saves its file while orch prepares its copy
        return real_dump(doc, out, **kw)

    monkeypatch.setattr(adapters.json, "dump", tool_writes_meanwhile)
    assert adapters.trust_folder("claude", proj) == "skipped"
    assert json.loads(f.read_text()) == {"n": 3}  # the tool's last write stands


def test_a_tool_without_trust_data_is_left_alone(proj):
    assert adapters.trust_folder("codex", proj) == "none"


# ---------------------------------------------------------------- a live tool that is not up yet


def _starting(proj, run, monkeypatch, pane_text, age):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "starting", "since": runs._iso(time.time() - age)}
    runs._write(proj, rec)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(
        runs_live, "tmux", lambda root, *a, **k: subprocess.CompletedProcess(a, 0, pane_text, "")
    )
    return tid


def test_a_trust_question_is_shown_instead_of_working(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, TRUST_SCREEN, age=5)
    runs_live.cleanup(proj)
    rec = runs.read(proj, tid)
    _valid_run(rec)
    assert rec["live"]["state"] == "attention"
    assert rec["live"]["why"].startswith("Claude asks whether to trust this folder")
    assert f"orch run attach {tid}" in rec["live"]["why"]
    out = run("run", "status", tid)[1]
    assert "trust this folder" in out and "working" not in out
    # the tool's own hook, once it is up, takes over again
    run("run", "event", "--run", rec["run"], "--kind", "idle")
    assert "why" not in runs.read(proj, tid)["live"]


def test_a_live_tool_not_up_after_a_minute_asks_for_a_look(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, "some screen orch does not know", age=61)
    runs_live.cleanup(proj)
    live = runs.read(proj, tid)["live"]
    assert live["state"] == "attention" and "has not started up after a minute" in live["why"]


def test_a_quiet_start_is_left_alone_for_a_minute(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, "loading", age=10)
    runs_live.cleanup(proj)
    assert runs.read(proj, tid)["live"]["state"] == "starting"


# ---------------------------------------------------------------- a never-pasted prompt


def _start_prompt(proj, tid):
    with runs.locked(proj, tid):
        text = f"Work on orch ticket {tid}: old"
        runs._pending_add_locked(proj, tid, "human:t", "text", text, "start", None)


def test_a_prompt_never_pasted_is_dropped_when_its_run_ends(proj, run):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live")
    _start_prompt(proj, tid)
    runs.pending_add(proj, tid, "human:anna", "message", "Use CHF")
    runs.release(proj, tid, rec["run"])
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Use CHF"]  # real input stays


def test_a_prompt_of_a_dead_run_is_not_nested_into_the_next(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    rec = runs.claim(proj, tid, "human:t", "claude", "live")
    rec["pid"], rec["pid_started"] = 999_999, None  # its process is gone
    runs._write(proj, rec)
    _start_prompt(proj, tid)
    runs.claim(proj, tid, "human:t", "claude", "oneshot")
    p = runs.plan(proj, tid, mode="oneshot")
    assert p["prompt"].count("Work on orch ticket") == 1 and p["item_ids"] == []
    out = run("run", "status", tid)[1]
    assert "Queued" not in out


# ---------------------------------------------------------------- attach and the start note


def test_attach_on_a_one_shot_run_points_to_focus_and_the_log(proj, run):
    tid = _ticket(run)
    runs.claim(proj, tid, "human:t", "claude", "oneshot", pid=os.getpid())
    rec = runs.read(proj, tid)
    rec["log"] = f".orch/run/logs/{tid}-{rec['run']}.log"
    runs._write(proj, rec)
    code, _, err = run("run", "attach", tid, "--watch")
    assert code == 2 and "one step at a time" in err and f"orch focus open {tid}" in err
    assert f"tail -f {rec['log']}" in err and "Start one" not in err


def test_attach_without_tmux_says_so(proj, run, monkeypatch):
    tid = _ticket(run)
    _no_tmux(monkeypatch)
    code, _, err = run("run", "attach", tid)
    assert code == 2 and "need tmux, which is not installed" in err


@pytest.mark.skipif(os.name == "nt", reason="tmux note is for Mac and Linux")
def test_start_without_tmux_says_how_to_get_a_live_session(proj, run, monkeypatch, tmp_path):
    d = tmp_path / "clbin"
    d.mkdir()
    (d / "claude").write_text("#!/bin/sh\nexit 0\n")
    (d / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    _no_tmux(monkeypatch)
    config.set_key(proj, "workspace", "agent", "claude")
    tid = _ticket(run)
    code, out, err = run("run", "start", tid, "--json")
    assert code == 0 and json.loads(out)["mode"] == "oneshot"
    assert "brew install tmux" in err and "Focus" in err
    deadline = time.monotonic() + 15
    while runs.read(proj, tid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert tickets.load(proj, tid)["id"] == tid
