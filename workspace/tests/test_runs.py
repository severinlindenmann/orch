"""Run claim: one agent per ticket, stale rules, pending input, argv (resume or fresh), the footer."""

import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import config, runs, tickets
from orch.errors import Refused

NEW = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"


def _schema(name):
    s = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(s, format_checker=jsonschema.FormatChecker())


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _ago(minutes):
    return (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _edit(proj, tid, **fields):
    p = runs.record_path(proj, tid)
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec.update(fields)
    p.write_text(json.dumps(rec), encoding="utf-8")


def test_claim_writes_a_valid_record_and_release_removes_it(proj, new_ticket):
    tid = new_ticket()
    rec = runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    assert not list(_schema("run.schema.json").iter_errors(rec))
    assert rec["pid_started"] and rec["by"] == "agent:scheduler" and rec["seen_revision"] >= 1
    assert runs.release(proj, tid, rec["run"]) == {"released": True, "pending": False}
    assert runs.read(proj, tid) is None
    assert not (proj / ".orch/run/tickets" / f"{tid}.lock").exists()


def test_busy_ticket_exits_2_queues_the_event_once(proj, new_ticket, run):
    tid = new_ticket()
    runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    code, out, err = run(
        "run", "claim", tid, "--by", "focus", "--agent", "claude", "--text", "Also add October", "--json"
    )
    j = json.loads(out)
    assert (
        code == 2
        and j["pending"] is True
        and j["claimed"] is False
        and j["holder"]["by"] == "agent:scheduler"
    )
    assert "already working on this ticket" in err
    items = runs.undelivered(proj, tid)
    assert [i["text"] for i in items] == ["Also add October"] and items[0]["by"] == "focus"
    assert not list(_schema("run-pending.schema.json").iter_errors(items[0]))
    assert runs.read(proj, tid)["pending"] is True
    # the same input id twice is one line
    runs.pending_add(proj, tid, "phone", "message", "hello", pid="p_abc123def")
    runs.pending_add(proj, tid, "phone", "message", "hello", pid="p_abc123def")
    assert len(runs.undelivered(proj, tid)) == 2


def test_dead_pid_is_stale_and_taken_over_without_asking(proj, new_ticket):
    tid = new_ticket()
    runs.claim(proj, tid, "a", "claude", pid=os.getpid())
    _edit(proj, tid, pid=_dead_pid())
    assert runs.state(runs.read(proj, tid)) == "dead"
    new = runs.claim(proj, tid, "b", "claude")
    assert new["by"] == "b"


def test_alive_pid_with_another_start_time_is_a_reused_pid(proj, new_ticket):
    tid = new_ticket()
    runs.claim(proj, tid, "a", "claude", pid=os.getpid())
    assert runs.state(runs.read(proj, tid)) == "alive"
    _edit(proj, tid, pid_started="2001-01-01T00:00:00Z")
    assert runs.state(runs.read(proj, tid)) == "dead"


def test_a_quiet_live_agent_keeps_its_claim(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setenv("ORCH_RUN_LEASE_SECONDS", "0.01")
    runs.claim(proj, tid, "a", "claude", pid=os.getpid())
    _edit(proj, tid, renewed_at=_ago(600))  # silent for ten hours, but the process lives
    time.sleep(0.05)
    with pytest.raises(runs.Busy):
        runs.claim(proj, tid, "b", "claude")
    with pytest.raises(runs.Busy):
        runs.claim(proj, tid, "b", "claude", take_over=True)  # not even on request: it is running


def test_pidless_claim_is_maybe_stale_after_30_min_and_needs_take_over(proj, new_ticket, run):
    tid = new_ticket()
    runs.claim(proj, tid, "agent:hand", "claude")
    _edit(proj, tid, renewed_at=_ago(10))
    with pytest.raises(runs.Busy):
        runs.claim(proj, tid, "b", "claude", take_over=True)  # only 10 min: still fine
    _edit(proj, tid, renewed_at=_ago(31))
    code, out, _ = run("run", "status", tid)
    assert "may be stuck" in out and f"orch run start {tid} --take-over" in out
    with pytest.raises(runs.Busy):
        runs.claim(proj, tid, "b", "claude")  # never automatically
    assert runs.read(proj, tid)["by"] == "agent:hand"
    assert runs.claim(proj, tid, "b", "claude", take_over=True)["by"] == "b"


def _taker(root, tid, who, barrier, q):
    barrier.wait()
    try:
        runs.claim(root, tid, who, "claude", take_over=True)
        q.put((who, "won"))
    except runs.Busy:
        q.put((who, "busy"))


def test_two_concurrent_takeovers_of_a_stale_claim_have_one_winner(proj, new_ticket):
    ctx = mp.get_context("spawn")
    for round_ in range(4):
        tid = new_ticket(f"r{round_}")
        runs.claim(proj, tid, "old", "claude")
        _edit(proj, tid, renewed_at=_ago(60))
        barrier, q = ctx.Barrier(2), ctx.Queue()
        ps = [ctx.Process(target=_taker, args=(proj, tid, w, barrier, q)) for w in ("x", "y")]
        for p in ps:
            p.start()
        res = dict(q.get(timeout=30) for _ in ps)
        for p in ps:
            p.join(30)
        assert sorted(res.values()) == ["busy", "won"], res
        assert runs.read(proj, tid)["by"] in ("x", "y")


def test_status_without_a_run_says_none_is_active(proj, new_ticket, run):
    tid = new_ticket()
    code, out, _ = run("run", "status", tid)
    assert code == 0 and out.strip() == f"No run is active for this ticket. Start one: orch run start {tid}"


def test_status_with_queued_input_and_no_runner_says_queued(proj, new_ticket, run):
    tid = new_ticket()
    runs.pending_add(proj, tid, "phone", "message", "hello")
    code, out, _ = run("run", "status", tid)
    assert code == 0 and out.strip() == (
        f"Queued. Nothing will start it: no background add-on is running here. Start it: orch run start {tid}"
    )


# ---------------------------------------------------------------- argv


def _choose(proj, name):
    config.set_key(proj, "workspace", "agent", name)


def test_argv_resumes_only_this_agent_on_this_host(proj, new_ticket, run):
    tid = new_ticket("Q3 summary")
    _choose(proj, "claude")
    j = json.loads(run("run", "argv", tid, "--json")[1])
    assert (
        j["resumed"] is False
        and j["session"]
        and j["argv"][:4] == ["claude", "-p", "--session-id", j["session"]]
    )
    assert "Q3 summary" in j["argv"][-1] and j["argv"][-2] == "--" and j["tmux"] is None
    tickets.record_session(proj, tid, "claude", "f88ec2ca-0930-42dd-9d5e-00fbbd59067d", runs.host())
    tickets.record_session(proj, tid, "codex", "01a1ac76-7c05-70d2-824d-4854e0c9c3f8", runs.host())
    j = json.loads(run("run", "argv", tid, "--json")[1])
    assert j["resumed"] is True and j["session"] == "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    assert j["argv"][:4] == ["claude", "-p", "--resume", j["session"]]
    assert json.loads(run("run", "argv", tid, "--fresh", "--json")[1])["resumed"] is False
    assert run("run", "session", tid)[1].strip() == "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    assert run("run", "session", tid, "--agent", "generic")[1].strip() == ""
    # a session of another machine is not resumed
    tickets.record_session(proj, tid, "claude", "0a0a0a0a-0000-4000-8000-000000000000", "other-mac")
    t = tickets.load(proj, tid)
    assert tickets.sessions_for(t, "claude", runs.host()) == "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    _choose(proj, "codex")
    j = json.loads(run("run", "argv", tid, "--json")[1])
    assert j["argv"][:5] == ["codex", "exec", "resume", "--json", "01a1ac76-7c05-70d2-824d-4854e0c9c3f8"]


def test_argv_on_another_host_starts_fresh(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    _choose(proj, "claude")
    tickets.record_session(proj, tid, "claude", "f88ec2ca-0930-42dd-9d5e-00fbbd59067d", runs.host())
    monkeypatch.setattr(runs, "host", lambda: "vps-pilot")
    assert json.loads(run("run", "argv", tid, "--json")[1])["resumed"] is False


def test_generic_agent_argv_has_no_session(proj, new_ticket, run):
    tid = new_ticket("Do it")
    config.add_agent(proj, "my-agent", "my-agent --prompt {prompt}")
    _choose(proj, "my-agent")
    j = json.loads(run("run", "argv", tid, "--json")[1])
    assert j["agent"] == "my-agent" and j["adapter"] == "generic" and j["session"] is None
    assert j["resumed"] is False and j["argv"][:2] == ["my-agent", "--prompt"] and "Do it" in j["argv"][2]


def test_prompt_file_and_allow(proj, new_ticket, run):
    tid = new_ticket()
    _choose(proj, "claude")
    (proj / "p.txt").write_text("Say hi", encoding="utf-8")
    j = json.loads(
        run("run", "argv", tid, "--prompt-file", "p.txt", "--allow", "Bash(git push:*)", "--json")[1]
    )
    assert j["argv"][-1] == "Say hi" and "Bash(git push:*)" in j["argv"]
    assert j["argv"].index("--allowedTools") < j["argv"].index("--")
    config.add_agent(proj, "gen", "gen {prompt}")
    _choose(proj, "gen")
    j = json.loads(run("run", "argv", tid, "--allow", "Edit", "--json")[1])
    assert "Edit" not in j["argv"]  # the generic adapter ignores it


def test_fresh_prompt_has_title_summary_and_what_changed(proj, new_ticket, run):
    tid = new_ticket("Invoice export")
    tickets.set_summary(proj, tid, "Half done", "human:me")
    tickets.log(proj, tid, "Anna sent the numbers", "human:anna")
    config.add_agent(proj, "gen", "gen {prompt}")
    _choose(proj, "gen")
    prompt = json.loads(run("run", "argv", tid, "--json")[1])["argv"][-1]
    assert "Invoice export" in prompt and "Half done" in prompt and "Anna sent the numbers" in prompt


def test_fresh_prompt_carries_the_persons_note(proj):
    t = tickets.create(proj, "Write hello.txt", "human:me", fields={"note": "Ask me first: Hello or Hi?"})
    prompt = runs.fresh_prompt(t, [])
    assert "The person's note on this ticket: Ask me first: Hello or Hi?" in prompt
    assert prompt.index("note on this ticket") < prompt.index("SKILL.md")  # read before anything else


# ---------------------------------------------------------------- the footer


def _inside(monkeypatch, proj, tid, agent="claude"):
    rec = runs.claim(proj, tid, "scheduler", agent, pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", tid)
    return rec


def test_footer_goes_to_stderr_only_and_once(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    run("check", "add", tid, "Step one", "--by", "human:me")
    _inside(monkeypatch, proj, tid)
    tickets.log(proj, tid, "q2 answered Yes", "human:marco")  # something happens while the agent works
    code, out, err = run("check", "done", tid, "c1", "--note", "ok", "--json", "--by", "agent:claude")
    assert code == 0
    json.loads(out)  # stdout is exactly the JSON
    assert f"New on {tid} since you looked: Claude started (scheduler); q2 answered Yes (human:marco)" in err
    code, out, err = run("log", tid, "second", "--by", "agent:claude")
    assert "New on" not in err  # once per new revision
    tickets.log(proj, tid, "another thing", "human:marco")
    assert "another thing" in run("log", tid, "third", "--by", "agent:claude")[2]


def test_no_footer_outside_a_run(proj, new_ticket, run):
    tid = new_ticket()
    tickets.log(proj, tid, "x", "human:marco")
    assert "New on" not in run("log", tid, "y")[2]


def test_orch_writes_renew_the_lease(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    rec = runs.claim(proj, tid, "agent:hand", "claude")
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", tid)
    _edit(proj, tid, renewed_at=_ago(40))
    run("log", tid, "alive", "--by", "agent:claude")
    assert runs.state(runs.read(proj, tid)) == "alive"


def test_claim_by_hand_records_the_session(proj, new_ticket, run):
    tid = new_ticket()
    code, out, _ = run("run", "claim", tid, "--by", "agent:claude", "--agent", "claude",
                       "--session", "f88ec2ca-0930-42dd-9d5e-00fbbd59067d", "--json")  # fmt: skip
    assert code == 0 and json.loads(out)["claimed"] is True
    assert (
        tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host())
        == "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    )
    assert run("run", "release", tid)[0] == 0 and runs.read(proj, tid) is None


def test_bad_input_is_refused(proj, new_ticket):
    tid = new_ticket()
    with pytest.raises(Refused):
        runs.pending_add(proj, tid, "x", "bogus", "t")
    with pytest.raises(Refused):
        runs.pending_add(proj, tid, "x", "text", "")


def test_release_needs_the_run_when_a_process_holds_the_claim(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    rec = runs.claim(proj, tid, "a", "claude", pid=os.getpid())
    code, _, err = run("run", "release", tid)
    assert code == 2 and rec["run"] in err and runs.read(proj, tid)
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    assert run("run", "release", tid)[0] == 0 and runs.read(proj, tid) is None
    monkeypatch.delenv("ORCH_RUN")
    runs.claim(proj, tid, "agent:hand", "claude")  # a hand-started claim has no pid
    assert run("run", "release", tid)[0] == 0 and runs.read(proj, tid) is None


def test_orch_writes_of_a_hand_started_agent_renew_its_claim(proj, new_ticket, run):
    tid = new_ticket()
    runs.claim(proj, tid, "agent:hand", "claude")
    _edit(proj, tid, renewed_at=_ago(40))
    run("log", tid, "other agent", "--by", "agent:other")
    assert runs.state(runs.read(proj, tid)) == "maybe-stale"
    run("log", tid, "mine", "--by", "agent:hand")
    assert runs.state(runs.read(proj, tid)) == "alive"


def test_a_reader_holding_the_record_open_does_not_break_a_write_or_delete(proj, new_ticket, monkeypatch):
    """Windows refuses os.replace/unlink on a file another process has open for a moment: wait it out."""
    from orch import procs

    monkeypatch.setattr(procs, "_FILE_BUSY", True)
    tid = new_ticket()
    rec = runs.claim(proj, tid, "agent:a", "fake", "oneshot")
    real_replace, real_unlink = os.replace, runs.Path.unlink
    busy = {"replace": 2, "unlink": 2}

    def replace(a, b):
        if busy["replace"]:
            busy["replace"] -= 1
            raise PermissionError(13, "in use")
        return real_replace(a, b)

    def unlink(self, *a, **k):
        if busy["unlink"] and self.name.endswith(".json"):
            busy["unlink"] -= 1
            raise PermissionError(13, "in use")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(procs.os, "replace", replace)
    monkeypatch.setattr(procs.Path, "unlink", unlink)
    assert runs.set_process(proj, tid, rec["run"], os.getpid())
    assert runs.release(proj, tid, rec["run"])["released"]
    assert runs.read(proj, tid) is None and busy == {"replace": 0, "unlink": 0}


def test_permission_errors_are_not_retried_off_windows(monkeypatch):
    from orch import procs

    monkeypatch.setattr(procs, "_FILE_BUSY", False)
    calls = []

    def op():
        calls.append(1)
        raise PermissionError(13, "no")

    with pytest.raises(PermissionError):
        procs._wait_free(op)
    assert calls == [1]


def test_a_lock_that_refuses_with_permission_error_is_waited_for_then_taken(proj, new_ticket, monkeypatch):
    """Windows 'delete pending': creating a lock being removed raises PermissionError."""
    tid = new_ticket()
    real, left = os.open, [2]

    def fake_open(path, flags, *a, **k):
        if str(path).endswith(".lock") and left[0]:
            left[0] -= 1
            raise PermissionError(13, "delete pending")
        return real(path, flags, *a, **k)

    real_link = os.link

    def fake_link(src, dst, *a, **k):  # the lock is linked into place (never empty): same refusal there
        if str(dst).endswith(".lock") and left[0]:
            left[0] -= 1
            raise PermissionError(13, "delete pending")
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(runs.os, "open", fake_open)
    monkeypatch.setattr(runs.os, "link", fake_link)
    with runs.locked(proj, tid):
        pass
    assert left[0] == 0


def test_the_wrapper_errors_go_to_the_run_log_not_nowhere(proj, new_ticket, run, monkeypatch):
    tid = new_ticket()
    config.add_agent(proj, "x", f"{sys.executable} -c pass {{prompt}}")
    config.set_key(proj, "workspace", "agent", "x")
    seen = {}

    class P:
        pid = os.getpid()

    def popen(cmd, **kw):
        if "_wrap" in cmd:
            seen.update(kw)
        return P()

    monkeypatch.setattr(runs.subprocess, "Popen", popen)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    assert seen["stderr"] not in (subprocess.DEVNULL, subprocess.STDOUT, None)
    assert seen["stderr"].mode == "ab" and list((proj / ".orch" / "run" / "logs").glob(f"{tid}-*.log"))


def test_claim_started_survives_stop_and_second_claim(proj, new_ticket, run):
    tid = new_ticket()
    first = runs.claim(proj, tid, "agent:test", "claude", pid=os.getpid())
    assert tickets.load(proj, tid)["started"] is True
    code, out, err = run("ticket", "show", tid, "--json")
    assert code == 0, err
    assert json.loads(out)["started"] is True
    runs.release(proj, tid, first["run"])
    tickets.agent_stopped(proj, tid, "agent:test")
    assert tickets.load(proj, tid)["started"] is True
    second = runs.claim(proj, tid, "agent:test", "claude", pid=os.getpid())
    assert tickets.load(proj, tid)["started"] is True
    runs.release(proj, tid, second["run"])


# ---- B4: "X is also changing this folder" (a hint computed from the run records, never a lock)


def _two_runs(proj, new_ticket):
    a, b = new_ticket("Update footer links"), new_ticket("Fix login form")
    runs.claim(proj, a, "agent:x", "claude", pid=os.getpid())
    runs.claim(proj, b, "agent:y", "codex", pid=os.getpid())
    return a, b


def test_shared_folder_two_alive_runs_see_each_other(proj, new_ticket):
    from orch import sharedfolder

    a, b = _two_runs(proj, new_ticket)
    assert sharedfolder.others_in_folder(proj, a) == [
        {"ticket": b, "title": "Fix login form", "agent": "codex"}
    ]
    assert sharedfolder.others_in_folder(proj, b)[0]["ticket"] == a
    assert sharedfolder.line(sharedfolder.others_in_folder(proj, a)) == (
        '"Fix login form" is also changing this folder.'
    )


def test_shared_folder_dead_run_or_no_run_says_nothing(proj, new_ticket):
    from orch import sharedfolder

    a, b = _two_runs(proj, new_ticket)
    _edit(proj, b, pid=_dead_pid(), pid_started=None)
    assert sharedfolder.others_in_folder(proj, a) == []
    assert sharedfolder.others_in_folder(proj, b) == []  # this ticket's own run is gone
    assert sharedfolder.line([]) is None


def test_shared_folder_different_folder_says_nothing(proj, new_ticket, tmp_path):
    from orch import sharedfolder

    a, b = _two_runs(proj, new_ticket)
    other = tmp_path / "copy"
    other.mkdir()
    _edit(proj, b, folder=str(other))
    assert sharedfolder.others_in_folder(proj, a) == []


def test_shared_folder_resolved_and_symlinked_paths_are_equal(proj, new_ticket, tmp_path):
    from orch import sharedfolder

    a, b = _two_runs(proj, new_ticket)
    link = tmp_path / "link"
    link.symlink_to(proj)
    _edit(proj, b, folder=str(link))
    assert len(sharedfolder.others_in_folder(proj, a)) == 1
    rec = json.loads(runs.record_path(proj, b).read_text(encoding="utf-8"))
    del rec["folder"]  # an older record: started in the root
    runs.record_path(proj, b).write_text(json.dumps(rec), encoding="utf-8")
    assert len(sharedfolder.others_in_folder(proj, a)) == 1


def test_shared_folder_several_others_are_counted(proj, new_ticket):
    from orch import sharedfolder

    a, _ = _two_runs(proj, new_ticket)
    runs.claim(proj, new_ticket("Third"), "agent:z", "claude", pid=os.getpid())
    assert sharedfolder.line(sharedfolder.others_in_folder(proj, a)) == (
        "2 other agents are also changing this folder."
    )


def test_shared_folder_in_show_and_run_status(proj, new_ticket, run):
    a, _ = _two_runs(proj, new_ticket)
    code, out, _ = run("ticket", "show", a)
    assert code == 0 and '"Fix login form" is also changing this folder.' in out
    code, out, _ = run("run", "status", a, "--json")
    assert json.loads(out)["shared_folder"]["line"].endswith("is also changing this folder.")
    c = new_ticket("Alone")
    assert "also changing" not in run("ticket", "show", c)[1]
