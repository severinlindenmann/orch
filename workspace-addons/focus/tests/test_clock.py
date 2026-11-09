from orch_focus import events as ev
from orch_focus.adapters.claude import ClaudeMapper
from orch_focus.board import Board
from orch_focus.clock import WorkClock

TID = "t_inv7c2"


def test_clock_counts_only_worked_time_and_freezes_while_paused(tmp_path):
    c = WorkClock(tmp_path)
    assert c.tick(TID, None, now=1000)["worked"] == 0  # not started
    c.tick(TID, "worked", first="2026-11-09T10:00:00Z", now=1010)
    assert c.tick(TID, "worked", now=1070)["worked"] == 60
    r = c.tick(TID, "paused", now=1100)  # stopped between two looks: at most 30 s counted
    assert r["worked"] == 90 and r["first"] == "2026-11-09T10:00:00Z"
    assert c.tick(TID, "paused", now=1110)["worked"] == 90  # frozen
    assert c.tick(TID, "paused", now=1120)["paused"] == 20
    assert c.tick(TID, "worked", now=100000)["worked"] == 90  # a day closed: not counted as work
    assert c.tick(TID, "worked", now=100030)["worked"] == 120  # a new claim keeps counting, no reset


def test_clock_survives_a_restart_and_ignores_bad_ids(tmp_path):
    (tmp_path / ".orch").mkdir()
    c = WorkClock(tmp_path)
    c.tick(TID, "worked", now=10)
    c.tick(TID, "worked", now=40)
    again = WorkClock(tmp_path)
    assert again.tick(TID, "worked", now=45)["worked"] == 35
    assert c.tick("../x", "worked")["worked"] == 0


def test_context_percent_from_cached_input():
    m = ClaudeMapper("r_8k2m9z4q", TID)
    for i, (read, new) in enumerate([(0, 1000), (900, 100)]):
        m.feed({"type": "assistant", "message": {"id": f"m{i}", "content": [], "usage": {
            "input_tokens": new // 2, "cache_creation_input_tokens": new - new // 2, "cache_read_input_tokens": read}}})
    m.feed({"type": "assistant", "message": {"id": "m1", "content": [], "usage": {"input_tokens": 50, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 900}}})  # same id twice: counted once
    out = m.feed({"type": "result", "timestamp": "2026-11-09T10:00:00Z"})
    state = next(e for e in out if e["kind"] == "run.state")
    assert state["data"]["reused"] == 45  # 900 of 2000
    snap = Board.from_events(out).snapshot()
    assert snap["context"]["reused"] == 45
    assert ev.make("r_8k2m9z4q", TID, "main", "run.state", "x", "adapter", state="idle")  # without the figure: fine
    assert Board.from_events([]).snapshot()["context"] is None


def test_no_figure_when_nothing_was_counted():
    m = ClaudeMapper("r_8k2m9z4q", TID)
    state = next(e for e in m.feed({"type": "result"}) if e["kind"] == "run.state")
    assert "reused" not in state["data"]
