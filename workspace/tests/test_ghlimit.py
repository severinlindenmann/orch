"""The GitHub add-on's hourly write limit (orch.ghlimit, `orch github`, the github.*_per_hour settings)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from orch import ghlimit, prwait


class Clock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t
        self.naps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.naps.append(secs)
        self.t += secs


def _take(clock: Clock, kind: str = "merge", wait: float = ghlimit.WAIT_SECS) -> bool:
    return ghlimit.take(kind, "o/r#1", wait=wait, sleep=clock.sleep, clock=clock)


def test_defaults_match_the_old_budget():
    assert ghlimit.limits() == {"merge": 12, "pr": 12, "comment": 20, "other": 30}


def test_first_write_goes_at_once_and_is_counted():
    c = Clock()
    assert _take(c) and c.naps == []
    merge = next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")
    assert merge["used"] == 1 and merge["per_hour"] == 12 and merge["last_secs_ago"] == 0


def test_second_write_of_a_kind_waits_for_the_pause():
    c = Clock()
    assert _take(c)
    assert _take(c)
    assert sum(c.naps) >= ghlimit.PAUSE_SECS["merge"]


def test_kinds_are_counted_apart():
    c = Clock()
    assert _take(c, "merge") and _take(c, "comment") and _take(c, "pr")
    assert c.naps == []


def test_a_full_hour_waits_until_the_oldest_write_is_an_hour_old():
    c = Clock()
    ghlimit.set_limit("merge", 2)
    assert _take(c)
    c.t += 600
    assert _take(c)
    c.t += 600
    start = c.t
    assert _take(c)  # waits until the first write is an hour old
    assert c.t >= start + (ghlimit.HOUR - 1200) - 1


def test_no_room_in_time_is_false_and_counts_nothing():
    c = Clock()
    ghlimit.set_limit("merge", 1)
    assert _take(c)
    assert not _take(c, wait=300)
    assert next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")["used"] == 1


def test_count_never_waits_but_uses_up_the_hour():
    c = Clock()
    ghlimit.set_limit("merge", 1)
    ghlimit.count("merge", "o/r#2", clock=c)
    assert not _take(c, wait=60)


def test_writes_older_than_an_hour_drop_out():
    c = Clock()
    ghlimit.set_limit("merge", 1)
    assert _take(c)
    c.t += ghlimit.HOUR + 1
    assert _take(c, wait=0)


def test_the_limit_is_shared_by_every_process_on_the_computer(subprocess_home):
    c = Clock(time.time())  # the other process reads the real clock
    ghlimit.set_limit("pr", 1)
    assert _take(c, "pr")
    log = ghlimit._log_file()
    assert log.parent == ghlimit._home() and log.exists()  # the machine-wide orch folder, not a workspace
    other = subprocess.run(
        [sys.executable, "-c", "from orch import ghlimit; print(ghlimit.take('pr', 'x', wait=0))"],
        capture_output=True, text=True, env=os.environ.copy(), timeout=60,
    )  # fmt: skip
    assert other.stdout.strip() == "False", other.stderr


def test_a_stale_lock_is_cleared():
    c = Clock()
    d = ghlimit._lock_dir()
    d.parent.mkdir(parents=True, exist_ok=True)
    d.mkdir()
    os.utime(d, (c.t - 600, c.t - 600))
    assert _take(c, wait=60)


def test_a_broken_log_line_is_skipped():
    c = Clock()
    log = ghlimit._log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("not json\n" + json.dumps({"t": c.t, "kind": "merge"}) + "\n", encoding="utf-8")
    assert next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")["used"] == 1


@pytest.mark.parametrize("bad", ["0", "201", "-1", "ten", "1.5"])
def test_set_limit_refuses_bad_numbers(bad):
    with pytest.raises(ghlimit.Refused):
        ghlimit.set_limit("merge", bad)


def test_a_higher_limit_shortens_the_pause():
    assert ghlimit.pause_secs("merge", 12) == 120
    assert ghlimit.pause_secs("merge", 200) == ghlimit.HOUR // 200


def test_settings_through_orch_config(proj, run):
    code, out, err = run("config", "set", "github.merge_per_hour", "5")
    assert code == 0, err
    assert "at most 5 merges per hour" in out
    assert run("config", "get", "github.merge_per_hour")[1].splitlines()[0] == "5"
    assert ghlimit.limits()["merge"] == 5
    assert run("config", "set", "github.merge_per_hour", "500")[0] == 2


def test_orch_github_wait_and_writes(proj, run):
    code, out, _ = run("github", "wait", "comment", "--for", "o/r#3")
    assert code == 0 and "write it now" in out
    run("config", "set", "github.comment_per_hour", "1")
    code, _, err = run("github", "wait", "comment", "--max-wait", "0")
    assert code == 2 and "Do not write to GitHub now" in err
    code, out, _ = run("github", "writes", "--json")
    rows = {r["kind"]: r for r in json.loads(out)["writes"]}
    assert rows["comment"]["used"] == 1 and rows["comment"]["per_hour"] == 1


class _Pull(prwait.Replay):
    def __init__(self, room: bool):
        super().__init__(
            {"polls": [[{"name": "test", "state": "SUCCESS", "bucket": "pass"}]], "required": []}
        )
        self.url, self.gh, self.room, self.taken = "https://github.com/o/r/pull/1", "/fake/gh", room, []

    def view(self):
        return {"state": "OPEN", "isDraft": False, "baseRefName": "develop", "headRefOid": "a" * 40}

    def landed(self, head, base):
        return []

    def changed_files(self):
        return ["x.py"]

    def take(self, kind, what):
        self.taken.append(kind)
        return self.room


def test_orch_merge_waits_for_room_and_does_not_merge_without(monkeypatch):
    merges = []
    monkeypatch.setattr(
        prwait, "_run", lambda argv, t=30: merges.append(argv) or subprocess.CompletedProcess(argv, 0)
    )
    full = _Pull(room=False)
    o = prwait.run_one(full.url, True, src=full)
    assert not o.ok and merges == [] and full.taken == ["merge"] and "no room" in o.line
    free = _Pull(room=True)
    o = prwait.run_one(free.url, True, src=free)
    assert o.ok and o.status == "merged" and len(merges) == 1


def test_live_pull_takes_from_the_shared_limit(monkeypatch):
    got = []
    monkeypatch.setattr(ghlimit, "take", lambda kind, what: got.append((kind, what)) or True)
    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")
    live = prwait.Live("https://github.com/o/r/pull/1")
    assert live.take("merge", "u") and got == [("merge", "u")]


def test_waiting_for_room_counts_nothing_and_a_merge_that_did_not_happen_gives_its_place_back():
    c = Clock()
    for _ in range(3):  # many waits for room: nothing is used
        assert ghlimit.wait_room("merge", sleep=c.sleep, clock=c)
    assert next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")["used"] == 0
    assert _take(c)
    assert next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")["used"] == 1
    assert ghlimit.give_back("merge", "o/r#1", clock=c)
    assert next(r for r in ghlimit.status(clock=c) if r["kind"] == "merge")["used"] == 0
    assert not ghlimit.give_back("merge", "o/r#1", clock=c)


def test_wait_room_waits_when_the_hour_is_full():
    c = Clock()
    ghlimit.set_limit("merge", 1)
    assert _take(c)
    assert ghlimit.wait_room("merge", wait=10, sleep=c.sleep, clock=c) is False


def test_a_merge_github_refused_gives_its_place_back(monkeypatch):
    pull = _Pull(room=True)
    pull.take = lambda kind, what: ghlimit.take(kind, what)
    monkeypatch.setattr(
        prwait, "_run", lambda argv, t=30: subprocess.CompletedProcess(argv, 1, "", "not mergeable")
    )
    used = lambda: next(r for r in ghlimit.status() if r["kind"] == "merge")["used"]  # noqa: E731
    o = prwait.run_one(pull.url, True, src=pull)
    assert not o.ok and used() == 0
    monkeypatch.setattr(prwait, "_run", lambda argv, t=30: subprocess.CompletedProcess(argv, 0, "", ""))
    assert prwait.run_one(pull.url, True, src=pull).ok and used() == 1
