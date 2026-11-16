"""R8.6 runaway brake: `orch pause` stops automation, automatic starts have a daily cap per ticket."""

import json
import os
import time

import pytest
import test_run_wrap

from orch import brake, runs, runs_live, tickets
from orch.errors import Refused

gen = test_run_wrap.gen
_wait = test_run_wrap._wait

pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


@pytest.fixture
def one_step(monkeypatch):
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)


def _new(proj, title="Make the report"):
    return tickets.create(proj, title, "human:t")["id"]


def test_pause_writes_the_flag_and_is_idempotent(proj, run):
    _new(proj)
    code, out, err = run("pause", "--json", "--by", "human:t")
    assert code == 0, err
    assert json.loads(out)["paused"] is True
    flag = proj / ".orch" / "run" / "paused.json"
    first = json.loads(flag.read_text(encoding="utf-8"))
    assert first["by"] == "human:t" and first["at"]
    code, out, _ = run("pause")
    assert code == 0 and "orch resume" in out
    assert json.loads(flag.read_text(encoding="utf-8")) == first
    code, out, _ = run("status")
    assert "Automation is paused" in out


def test_resume_clears_the_flag(proj, run):
    _new(proj)
    run("pause")
    code, out, _ = run("resume", "--json")
    assert code == 0 and json.loads(out) == {"paused": False, "was_paused": True}
    assert brake.paused(proj) is None
    code, out, _ = run("resume")
    assert code == 0 and "not paused" in out
    assert "paused" not in run("status")[1]


@pytest.mark.parametrize("by", ["agent:automation", "agent:factory"])
def test_paused_refuses_automatic_starts(proj, by):
    tid = _new(proj)
    brake.pause(proj, "human:t")
    with pytest.raises(Refused, match="orch resume"):
        runs.start(proj, tid, by)
    assert runs.read(proj, tid) is None


def test_paused_still_lets_a_person_start(proj, gen, one_step):
    gen("--silent 0.2")
    tid = _new(proj)
    brake.pause(proj, "human:t")
    runs.start(proj, tid, "human:t")
    _wait(proj, tid)


def test_resume_lets_automation_start_again(proj, gen, one_step):
    gen("--silent 0.2")
    tid = _new(proj)
    brake.pause(proj, "human:t")
    brake.resume(proj)
    runs.start(proj, tid, "agent:automation")
    _wait(proj, tid)


def test_restart_after_give_up_does_not_start_while_paused(proj, monkeypatch):
    tid = _new(proj)
    calls = []
    monkeypatch.setattr(runs, "start", lambda *a, **k: calls.append(a))
    brake.pause(proj, "human:t")
    assert runs_live.restart_after_give_up(proj, tid, "fake") is None
    assert calls == []
    assert not any("started again" in h["text"] for h in tickets.load(proj, tid)["history"])


def test_cap_refuses_the_21st_automatic_start_with_one_history_line(proj):
    tid = _new(proj)
    for _ in range(brake.CAP_PER_DAY):
        brake.check_start(proj, tid, "agent:automation")
    for _ in range(3):
        with pytest.raises(Refused, match="ran 20 times on its own today"):
            brake.check_start(proj, tid, "agent:factory")
    lines = [h for h in tickets.load(proj, tid)["history"] if "ran 20 times" in h["text"]]
    assert len(lines) == 1


def test_person_starts_are_not_counted_or_capped(proj):
    tid = _new(proj)
    for _ in range(brake.CAP_PER_DAY + 5):
        brake.check_start(proj, tid, "human:t")
    assert not (proj / ".orch" / "run" / "starts.json").exists()
    brake.check_start(proj, tid, "agent:automation")  # the automation's own count starts at zero


def test_cap_is_per_ticket_and_rolls_over_after_24_hours(proj):
    a, b = _new(proj, "A"), _new(proj, "B")
    for _ in range(brake.CAP_PER_DAY):
        brake.check_start(proj, a, "agent:automation")
    brake.check_start(proj, b, "agent:automation")
    path = proj / ".orch" / "run" / "starts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["starts"][a] = [time.time() - brake.WINDOW - 5] * brake.CAP_PER_DAY
    path.write_text(json.dumps(data), encoding="utf-8")
    brake.check_start(proj, a, "agent:automation")


def test_pause_reason_is_kept_and_named_where_a_start_is_held_back(proj, run):
    """ORCH-75: the system keeper pauses on a full disk; whoever meets the pause sees why."""
    tid = _new(proj)
    why = "Disk almost full:\n 8 GB free"
    code, out, err = run("pause", "--json", "--by", "agent:system-keeper", "--reason", why)
    assert code == 0, err
    rec = json.loads(out)
    assert rec["paused"] is True and rec["reason"] == "Disk almost full: 8 GB free"
    held = r"paused in this workspace: Disk almost full: 8 GB free\. .*orch resume"
    with pytest.raises(Refused, match=held):
        runs.start(proj, tid, "agent:automation")
    assert "Disk almost full: 8 GB free" in run("status")[1]
    code, out, _ = run("pause", "--reason", "something else")  # pausing again keeps the first record
    assert "Disk almost full" in out
    assert brake.paused(proj)["reason"] == "Disk almost full: 8 GB free"


def test_pause_reason_is_one_short_line():
    assert brake.clean_reason("  a\n\tb  ") == "a b"
    assert brake.clean_reason("   ") is None
    assert len(brake.clean_reason("x" * 500)) == brake.REASON_MAX
    assert brake.paused_words({"by": "human:t"}) == brake.PAUSED_REFUSAL
