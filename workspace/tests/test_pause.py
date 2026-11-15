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
