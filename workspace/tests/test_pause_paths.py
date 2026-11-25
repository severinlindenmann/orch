"""R8.6: every path that starts a helper goes through runs.start: none starts while paused, all are capped."""

import pytest

from orch import brake, runs, runs_live, tickets
from orch.errors import Refused


def _new(proj, title="Make the report"):
    return tickets.create(proj, title, "human:t")["id"]


START_PATHS = [
    runs_live.AUTOMATION_BY,  # automation add-on, renew, autoreview, reviewer
    "agent:factory",  # factory add-on (orders, crews, ideas)
    "agent:dispatcher",  # the dispatcher's starts
    "agent:helper-watcher",  # tend
    "agent:dev-expert",
    "agent:release-keeper",  # release keeper and its security review
    "agent:triage",
    tickets.REVIEWER,  # reviewer, look review
    "orch",  # renew
]


@pytest.fixture
def no_helper(monkeypatch):
    """Any real start would reach start_live or the one-step spawn: this records it and starts nothing."""
    began = []
    monkeypatch.setattr(runs_live, "start_live", lambda *a, **k: began.append(a) or {"run": 1})
    monkeypatch.setattr(runs_live, "available", lambda adapter: True)
    return began


@pytest.mark.parametrize("by", START_PATHS)
def test_no_start_path_runs_while_paused(proj, no_helper, by):
    tid = _new(proj)
    brake.pause(proj, "human:t")
    for mode in ("live", None):
        with pytest.raises(Refused, match="orch resume"):
            runs.start(proj, tid, by, mode=mode)
    assert no_helper == [] and runs.read(proj, tid) is None


def test_the_cli_start_is_refused_while_paused(proj, run, no_helper):
    tid = _new(proj)
    brake.pause(proj, "human:t")
    code, out, err = run("run", "start", tid, "--by", runs_live.AUTOMATION_BY)
    assert code != 0 and "orch resume" in out + err
    assert no_helper == []


def test_a_waiting_start_is_not_taken_while_paused(proj, no_helper):
    tid = _new(proj)
    runs.pending_add(proj, tid, runs_live.AUTOMATION_BY, "message", "go on", via="slots")
    brake.pause(proj, "human:t")
    assert runs_live.start_waiting(proj) == [] and no_helper == []


@pytest.mark.parametrize("by", START_PATHS)
def test_the_cap_applies_to_every_start_path_by_default(proj, no_helper, by):
    tid = _new(proj)
    for _ in range(brake.CAP_PER_DAY):
        runs.start(proj, tid, by, mode="live")
    assert len(no_helper) == brake.CAP_PER_DAY
    with pytest.raises(Refused, match="ran 20 times on its own today"):
        runs.start(proj, tid, by, mode="live")
    assert len(no_helper) == brake.CAP_PER_DAY
