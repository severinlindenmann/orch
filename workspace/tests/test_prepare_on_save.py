"""ORCH-738: Save without starting runs a prepare-only helper. It fills the ticket, the ticket stays in
Backlog marked Prepared, the conversation is kept for Start; when it cannot run, the ticket stays as saved
with "Not prepared yet" and Start still works."""

import json
import os
import shlex
import sys
import time

import pytest
import test_run_wrap

from orch import adapters, cli, config, runs, runs_live, tickets

pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")

SID = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"

# A helper that only prepares: it logs what it was told and fills the ticket with `orch ticket tidy`.
PREPARER = r"""
import os, shlex, subprocess, sys
args = sys.argv[1:]
how = args.pop(0)
with open(os.environ["PREP_LOG"], "a", encoding="utf-8") as f:
    f.write("prompt: " + " ".join(args).replace("\n", " | ") + "\n")
orch = shlex.split(os.environ["ORCH_CMD"])
tid = os.environ["ORCH_TICKET"]
if how == "fail":
    sys.exit(3)
if how == "tidy" and "Prepare orch ticket" in " ".join(args):  # a later turn is the work: nothing here
    subprocess.run(orch + ["ticket", "tidy", tid, "Monthly sales report", "--description",
        "Make the monthly sales report for the team.", "--done-when", "The report is in the shared folder",
        "--estimate-minutes", "30", "--estimate-cost", "2"], check=True, capture_output=True)
    subprocess.run(orch + ["check", "add", tid, "Collect the numbers"], check=True, capture_output=True)
"""


@pytest.fixture
def helper(proj, monkeypatch, subprocess_home):
    """The folder's agent is the preparer above; how: tidy (fills the ticket), nothing, fail."""
    script = proj.parent / f"{proj.name}-preparer.py"
    script.write_text(PREPARER, encoding="utf-8")
    log = proj.parent / f"{proj.name}-preparer.log"
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("PREP_LOG", str(log))
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)  # no tmux: one step at a time
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)  # a busy test machine

    def _set(how="tidy"):
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {how} {{prompt}}"
        config.add_agent(proj, "fake", cmd, approve=True)
        config.set_key(proj, "workspace", "agent", "fake")
        return log

    return _set


def _new(run, title="sales report for november pls"):
    code, out, err = run("ticket", "new", title, "--json", "--by", "human:t")
    assert code == 0, err
    return json.loads(out)["id"]


def _prepare_soon(proj, tid, want, timeout=25.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        p = tickets.load(proj, tid).get("prepare") or {}
        if p.get("state") == want and not runs.running(proj, tid):
            return p
        time.sleep(0.05)
    raise AssertionError(f"prepare did not reach {want}: {tickets.load(proj, tid).get('prepare')}")


def _texts(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def test_save_without_starting_prepares_and_the_ticket_stays_in_backlog_marked_prepared(
    proj, run, helper, validate
):
    log = helper("tidy")
    tid = _new(run)
    code, out, err = run("run", "start", tid, "--prepare", "--by", "human:t", "--json")
    assert code == 0, err
    r = json.loads(out)
    assert r["prepare"] is True and r["mode"] == "oneshot" and r["resumed"] is False
    assert tickets.load(proj, tid)["status"] == "open"  # never Working, not even while it prepares
    _prepare_soon(proj, tid, "prepared")
    t = tickets.load(proj, tid)
    assert t["status"] == "open" and not t.get("started")  # Backlog; the work has not started
    assert t["title"] == "Monthly sales report" and t["done_when"] and t["estimate"]["minutes"] == 30
    assert [c["text"] for c in t["checklist"]] == ["Collect the numbers"] and not t["checklist"][0]["done"]
    assert tickets.PREPARED_LINE in _texts(proj, tid)
    assert not any("started" in x and x.endswith("started") for x in _texts(proj, tid))
    validate(t)
    prompt = log.read_text(encoding="utf-8")
    assert f"Prepare orch ticket {tid}" in prompt and "Do NOT do the work" in prompt
    assert "sales report for november pls" in prompt  # the person's own words go in
    code, out, _ = run("ticket", "show", tid)
    assert code == 0 and "\nPrepared\n" in out and "Status: Backlog" in out


def test_a_helper_that_fills_nothing_leaves_not_prepared_yet_and_start_still_works(proj, run, helper):
    helper("nothing")
    tid = _new(run)
    assert run("run", "start", tid, "--prepare", "--by", "human:t")[0] == 0
    p = _prepare_soon(proj, tid, "not_prepared")
    assert "before the ticket was filled" in p["why"]
    t = tickets.load(proj, tid)
    assert t["status"] == "open" and any(x.startswith(tickets.NOT_PREPARED) for x in _texts(proj, tid))
    assert "Not prepared yet: the helper stopped before" in run("ticket", "show", tid)[1]
    code, out, err = run("run", "start", tid, "--by", "human:t", "--json")  # Start still works
    assert code == 0, err
    assert json.loads(out)["run"]
    test_run_wrap._wait(proj, tid)
    assert "started" in " ".join(_texts(proj, tid))


def test_a_helper_that_fails_leaves_the_ticket_as_saved(proj, run, helper):
    helper("fail")
    tid = _new(run)
    title = tickets.load(proj, tid)["title"]
    assert run("run", "start", tid, "--prepare", "--by", "human:t")[0] == 0
    p = _prepare_soon(proj, tid, "not_prepared")
    assert "error" in p["why"]
    t = tickets.load(proj, tid)
    assert t["status"] == "open" and t["title"] == title and t.get("waiting_on") is None


def test_prepare_refuses_a_started_ticket_or_one_out_of_backlog(proj, run, helper):
    helper("tidy")
    tid = _new(run)
    tickets.set_status(proj, tid, "ready", "human:t")
    code, _, err = run("run", "start", tid, "--prepare", "--by", "human:t")
    assert code == 2 and "Backlog" in err
    assert "prepare" not in tickets.load(proj, tid)
    for extra in (["--session", SID], ["--priority", "high"], ["--mode", "live"], ["--text", "x"]):
        code, _, err = run("run", "start", _new(run), "--prepare", *extra, "--by", "human:t")
        assert code == 2 and "--prepare" in err


def test_a_paused_orch_leaves_not_prepared_yet(proj, run, helper, monkeypatch):
    helper("tidy")
    tid = _new(run)
    from orch import brake

    monkeypatch.setattr(brake, "paused", lambda root: {"by": "human:t"})
    monkeypatch.setattr(brake, "paused_words", lambda rec: "orch is paused")
    code, _, err = run("run", "start", tid, "--prepare", "--by", "human:t")
    assert code == 2 and "paused" in err
    t = tickets.load(proj, tid)
    assert (
        t["status"] == "open" and t["prepare"]["state"] == "not_prepared" and "paused" in t["prepare"]["why"]
    )


def test_with_every_helper_place_taken_it_waits_low_in_line_and_starts_as_prepare(
    proj, run, helper, monkeypatch
):
    helper("tidy")
    busy, tid = _new(run, "Busy one"), _new(run)
    runs_live._queue_for_slot(proj, busy, "human:t", "human:t asked for more work.", "normal")
    monkeypatch.setattr(runs_live, "_full", lambda root: 2)
    code, _, err = run("run", "start", tid, "--prepare", "--by", "human:t")
    assert code == 2 and "prepared when a helper is free" in err
    assert tickets.load(proj, tid)["prepare"]["state"] == "waiting"
    assert runs_live.waiting_line(proj) == [(busy, "normal"), (tid, "low")]  # behind work a person started
    assert tickets.prepare_state(proj, tickets.load(proj, tid))["words"] == "Waits in line to be prepared"
    calls = []
    monkeypatch.setattr(runs_live, "_full", lambda root: None)
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)
    monkeypatch.setattr(runs, "start", lambda root, t, by, **kw: calls.append((t, kw)))
    runs_live.start_waiting(proj)
    assert calls == [(busy, {"mode": "live"}), (tid, {"prepare": True})]


def test_a_start_while_prepare_waits_in_line_makes_the_place_one_for_the_work(proj, run, helper, monkeypatch):
    helper("tidy")
    tid = _new(run)
    runs_live._queue_for_slot(proj, tid, "human:t", "saved", "low", prepare=True)
    runs_live._queue_for_slot(proj, tid, "human:t", "human:t asked for more work.", "normal")
    items = [i for i in runs.undelivered(proj, tid) if i.get("via") == "slots"]
    assert len(items) == 1 and "prepare" not in items[0] and items[0]["priority"] == "normal"


def test_a_prepare_run_that_died_reads_not_prepared_yet(proj, run, helper):
    helper("tidy")
    tid = _new(run)
    tickets.set_prepare(proj, tid, "preparing", "human:t", run="r_gone")
    st = tickets.prepare_state(proj, tickets.load(proj, tid))
    assert st["state"] == "not_prepared" and st["words"] == tickets.NOT_PREPARED
    tickets.set_status(proj, tid, "ready", "human:t")  # a person moved on: nothing about Prepare to show
    assert tickets.prepare_state(proj, tickets.load(proj, tid)) is None


def test_an_old_run_never_overwrites_a_newer_prepare(proj, new_ticket):
    tid = new_ticket()
    tickets.set_prepare(proj, tid, "preparing", "orch", run="r_new")
    assert tickets.set_prepare(proj, tid, "prepared", "orch", run="r_old") is False
    assert tickets.load(proj, tid)["prepare"]["state"] == "preparing"
    tickets.set_status(proj, tid, "active", "human:t")
    assert tickets.set_prepare(proj, tid, "prepared", "orch", run="r_new") is False  # left Backlog: kept


@pytest.fixture
def transcript(monkeypatch):
    monkeypatch.setattr(adapters, "transcript_exists", lambda *a, **k: True)
    monkeypatch.setattr(adapters, "transcript_path", lambda *a, **k: None)


def test_the_prepare_conversation_is_kept_and_start_continues_it(proj, new_ticket, transcript):
    tid = new_ticket()
    tickets.record_session(proj, tid, "claude", SID, runs.host())  # an earlier session: prepare starts fresh
    p = runs.plan(proj, tid, agent="claude", prepare=True)
    assert p["resumed"] is False and p["session"] != SID and p["model"] == runs.PREPARE_MODEL
    assert "ONLY to prepare" in p["prompt"]
    tickets.record_session(proj, tid, "claude", p["session"], runs.host())  # what the wrapper records
    tickets.set_prepare(proj, tid, "prepared", "agent:claude")
    tickets.set_status(proj, tid, "active", "human:t")  # the person pressed Start
    s = runs.plan(proj, tid, agent="claude")
    assert s["resumed"] is True and s["session"] == p["session"]  # the same conversation goes on
    assert "preparing is over" in s["prompt"]


def test_prepare_keeps_a_model_the_person_chose(proj, new_ticket):
    tid = new_ticket()
    assert cli.main(["ticket", "model", tid, "opus", "--by", "human:t"]) == 0
    assert runs.plan(proj, tid, agent="claude", prepare=True)["model"] == "opus"


def test_start_after_a_prepare_that_did_not_finish_also_says_the_work_begins(proj, new_ticket, transcript):
    tid = new_ticket()
    p = runs.plan(proj, tid, agent="claude", prepare=True)
    tickets.record_session(proj, tid, "claude", p["session"], runs.host())
    tickets.set_prepare(proj, tid, "not_prepared", "orch", why="the helper stopped with an error")
    tickets.set_status(proj, tid, "active", "human:t")
    s = runs.plan(proj, tid, agent="claude")
    assert s["resumed"] is True and "preparing is over" in s["prompt"]


def test_a_ticket_with_done_when_only_is_not_prepared_by_a_helper_that_does_nothing(proj, run, helper):
    helper("nothing")
    tid = _new(run)
    assert run("ticket", "edit", tid, "--done-when", "The report is sent", "--by", "human:t")[0] == 0
    assert run("run", "start", tid, "--prepare", "--by", "human:t")[0] == 0
    assert _prepare_soon(proj, tid, "not_prepared")["why"]


def test_a_ticket_moved_out_of_backlog_before_the_claim_is_not_prepared(proj, new_ticket):
    tid = new_ticket()
    tickets.set_status(proj, tid, "ready", "human:t")
    with pytest.raises(Exception, match="Backlog"):
        runs.claim(proj, tid, "human:t", "fake", "oneshot", prepare=True)
    assert runs.read(proj, tid) is None


def test_a_start_while_prepare_runs_goes_on_into_the_work_in_the_same_run(proj, run, helper, monkeypatch):
    log = helper("tidy")
    tid = _new(run)
    real = runs._prepare_end

    def slow_end(root, t, r, rc, by):  # the person presses Start just before the prepare run ends
        code, out, _ = run("run", "start", t, "--mode", "oneshot", "--by", "human:t", "--json")
        assert code == 2 and json.loads(out)["pending"] is True
        real(root, t, r, rc, by)

    monkeypatch.setattr(runs, "_prepare_end", slow_end)
    rec = runs.claim(proj, tid, "human:t", "fake", "oneshot", prepare=True)
    p = runs.plan(proj, tid, mode="oneshot", agent="fake", prepare=True)
    assert runs.wrap(proj, rec["run"], tid, "fake", p["argv"], stdin=p["stdin"]) == 0
    t = tickets.load(proj, tid)
    assert t["prepare"]["state"] == "prepared" and t["started"] is True
    prompts = [x for x in log.read_text(encoding="utf-8").splitlines() if x.startswith("prompt:")]
    assert (
        len(prompts) == 2 and "Prepare orch ticket" in prompts[0] and "Prepare orch ticket" not in prompts[1]
    )
    assert any(x.endswith("started") for x in _texts(proj, tid))
