"""Jobs waiting for a machine on GitHub (ORCH-454): the count, the shared answer, the day's peak and the hold.
A fake GitHub API: no network."""

from __future__ import annotations

import json

import pytest

from orch import cibusy

REPO = "acme/app"


class Api:
    def __init__(self, queued=(), running=(), jobs=None, fail=False):
        self.queued, self.running, self.jobs, self.fail = list(queued), list(running), jobs or {}, fail
        self.calls: list[str] = []

    def __call__(self, path):
        self.calls.append(path)
        if self.fail:
            return None
        if "status=queued" in path:
            return {"workflow_runs": [{"id": i} for i in self.queued]}
        if "status=in_progress" in path:
            return {"workflow_runs": [{"id": i} for i in self.running]}
        rid = int(path.split("/runs/")[1].split("/")[0])
        return {"jobs": [{"status": s} for s in self.jobs.get(rid, [])]}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    from orch import addons

    monkeypatch.setattr(addons, "home", lambda root=None: tmp_path)
    return tmp_path


def test_counts_queued_and_waiting_jobs_of_queued_and_running_runs():
    api = Api(queued=[1], running=[2, 3], jobs={1: ["queued", "queued"], 2: ["in_progress", "queued"],
                                                 3: ["completed", "in_progress"]})  # fmt: skip
    assert cibusy.count(REPO, api) == 3


def test_an_unreadable_github_gives_none_and_never_blocks():
    assert cibusy.count(REPO, Api(fail=True)) is None
    assert cibusy.room(REPO, api=Api(fail=True), clock=lambda: 1000.0) == (True, None)
    assert cibusy.count("not a repo; rm", Api()) is None


def test_the_answer_is_shared_for_two_minutes_and_the_days_peak_is_kept():
    busy = Api(queued=[1], jobs={1: ["queued"] * 25})
    assert cibusy.room(REPO, api=busy, clock=lambda: 1_763_400_000.0) == (False, 25)
    calls = len(busy.calls)
    calm = Api()
    assert cibusy.waiting(REPO, api=calm, clock=lambda: 1_763_400_060.0) == 25  # shared answer, no read
    assert calm.calls == [] and len(busy.calls) == calls
    assert cibusy.waiting(REPO, api=calm, clock=lambda: 1_763_400_000.0 + cibusy.CACHE_SECS + 1) == 0
    day = next(iter(cibusy.peaks(REPO)))
    assert cibusy.peaks(REPO)[day]["n"] == 25  # a lower count later never lowers the peak
    assert cibusy.peaks("ACME/app")[day]["n"] == 25  # one repository whatever its case


def test_wait_room_waits_until_there_is_room_and_says_so_once(monkeypatch):
    counts = iter([30, 30, 5])
    said, slept, t = [], [], iter(range(0, 10_000, 60))
    monkeypatch.setattr(cibusy, "room", lambda repo, **kw: ((c := next(counts)) < cibusy.LIMIT, c))
    ok, n = cibusy.wait_room(REPO, say=said.append, sleep=slept.append, clock=lambda: next(t))
    assert (ok, n) == (True, 5) and len(slept) == 2 and len(said) == 1 and "30 jobs wait" in said[0]


def test_wait_room_gives_up_after_its_time(monkeypatch):
    t = iter(range(0, 100_000, 600))
    monkeypatch.setattr(cibusy, "room", lambda repo, **kw: (False, 40))
    ok, n = cibusy.wait_room(REPO, max_wait=1800, sleep=lambda s: None, clock=lambda: next(t))
    assert (ok, n) == (False, 40)


def test_cli_says_the_count_and_refuses_while_busy(proj, run, monkeypatch):
    monkeypatch.setattr(cibusy, "count", lambda repo, api=None: 4)
    code, out, _ = run("github", "ci-waiting", "--repo", REPO)
    assert code == 0 and "4 jobs of acme/app wait for a machine (limit 20)" in out
    monkeypatch.setattr(cibusy, "count", lambda repo, api=None: 25)
    code, out, err = run("github", "ci-waiting", "--repo", REPO, "--json")
    assert code == 2 and json.JSONDecoder().raw_decode(out)[0]["waiting"] == 25
    assert "start no runs now" in out + err
    code, out, err = run("github", "ci-waiting")
    assert code == 2 and "--repo owner/name" in out + err
