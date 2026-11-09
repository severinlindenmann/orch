import threading
import time
from datetime import datetime

from orch_focus import events as ev, runfiles
from orch_focus.adapters.claude import ClaudeMapper
from orch_focus.board import Board
from orch_focus.clock import WorkClock

TID = "t_inv7c2"


def test_clock_counts_only_worked_time_and_freezes_while_paused(tmp_path):
    (tmp_path / ".orch").mkdir()
    c = WorkClock(tmp_path)
    assert c.tick(TID, None, now=1000)["worked"] == 0  # not started
    c.tick(TID, "worked", first="2026-11-09T10:00:00Z", now=1010)
    assert c.tick(TID, "worked", now=1070)["worked"] == 60
    r = c.tick(TID, "paused", now=1100)  # stopped between two looks: at most STOP_GAP counted
    assert r["worked"] == 75 and r["first"] == "2026-11-09T10:00:00Z"
    assert c.tick(TID, "paused", now=1110)["worked"] == 75  # frozen
    assert c.tick(TID, "paused", now=1120)["paused"] == 20
    r = c.tick(TID, "worked", now=1200)  # the pause (1100..1200) is added when work resumes
    assert r["worked"] == 75 and r["paused"] == 100
    assert c.tick(TID, "worked", now=1230)["worked"] == 105  # a new claim keeps counting, no reset


def test_a_long_gap_counts_as_nothing(tmp_path):
    (tmp_path / ".orch").mkdir()
    c = WorkClock(tmp_path)
    c.tick(TID, "worked", now=1000)
    assert c.tick(TID, "worked", now=1000 + 3 * 3600)["worked"] == 0  # sleep / downtime
    assert c.tick(TID, "worked", now=1000 + 3 * 3600 + 10)["worked"] == 10
    assert c.tick(TID, "paused", now=1000 + 10 * 3600)["worked"] == 10  # stop after a long gap: nothing added


def test_unwatched_work_is_counted_by_the_ticker_and_by_the_claim_age(tmp_path):
    (tmp_path / ".orch").mkdir()
    c = WorkClock(tmp_path)
    first = "2026-11-09T10:00:00Z"
    t0 = datetime.fromisoformat("2026-11-09T10:10:00+00:00").timestamp()
    assert c.tick(TID, "worked", first=first, now=t0)["worked"] == 600  # first seen already running: its age
    assert c.active() == [TID]
    assert c.tick(TID, "worked", now=t0 + 10)["worked"] == 610  # the server's ticker looks without a page
    c.tick(TID, "paused", now=t0 + 20)
    assert c.active() == []
    c.tick(TID, None, now=t0 + 30)  # done: dropped from memory, still on disk
    assert TID not in c.recs
    assert c.tick(TID, None, now=t0 + 40)["worked"] == 620


def test_corrupt_clock_file_is_ignored_and_ticks_are_safe_in_threads(tmp_path):
    (tmp_path / ".orch").mkdir()
    c = WorkClock(tmp_path)
    runfiles.write_json(c._file(TID), {"worked": float("inf"), "paused": True, "mode": "worked", "seen": float("nan")})
    r = c.tick(TID, "worked", now=500)
    assert r["worked"] == 0 and r["paused"] == 0
    start = time.time()
    c.tick(TID, "worked", now=start)
    threads = [threading.Thread(target=lambda: [c.tick(TID, "worked") for _ in range(300)]) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert c.tick(TID, "worked")["worked"] <= time.time() - start + 1  # never counted twice


def test_saving_the_clock_does_not_look_like_a_workspace_change(tmp_path):
    from orch_focus.revisions import Revisions

    (tmp_path / ".orch").mkdir()
    (tmp_path / ".orch" / "tickets").mkdir()
    (tmp_path / ".orch" / "run").mkdir()
    before = Revisions(tmp_path).signature()
    c = WorkClock(tmp_path)
    c.tick(TID, "worked", now=100)
    c.tick(TID, "paused", now=130)
    assert (tmp_path / ".orch" / "addons" / "focus" / "runs" / f"clock-{TID}.state").exists()
    assert Revisions(tmp_path).signature() == before  # the page would reload on every save otherwise
