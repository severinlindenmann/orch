"""Focus reads live steps through `orch record tail --follow --json`, never from files (contracts/activity.md)."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from orch_focus import record
from orch_focus.board import Board
from orch_focus.record import RecordFeed, to_events

ROOT = Path(__file__).resolve().parents[3]
FAKE = ROOT / "workspace" / "tests" / "fakes" / "orch"
EX = ROOT / "contracts" / "examples" / "activity"
RUN, TICKET = "r_8k2m01", "t_inv7c2"


def example(name, **kw):
    e = json.loads((EX / name).read_text())
    e.update(kw)
    return e


def wait(feed, n=1, secs=15.0):
    got, end = [], time.time() + secs
    while len(got) < n and time.time() < end:
        got += feed.poll()
        time.sleep(0.05)
    return got


@pytest.fixture
def feed_for(monkeypatch, tmp_path):
    feeds = []
    monkeypatch.setenv("ORCH_FAKE_FOLLOW_PINGS", "0")

    def make(run=RUN, orch_bin=str(FAKE)):
        f = RecordFeed(tmp_path, orch_bin, run, TICKET)
        feeds.append(f)
        return f

    yield make
    for f in feeds:
        f.close()


def test_step_started_and_finished_become_board_steps():
    s = to_events(example("valid-step-started.json"), TICKET)
    assert [e["kind"] for e in s] == ["tool.start"] and s[0]["text"] == "Read report-2025-11.pdf"
    fin = example("valid-step-started.json", outcome={"ok": False, "error": "boom", "ms": 5})
    assert to_events(fin, TICKET)[0]["data"]["ok"] is False
    b = Board.from_events(s)
    assert b.snapshot()["step"] == "Read report-2025-11.pdf"


def test_other_kinds_and_bad_shapes_give_nothing_or_the_right_event():
    assert to_events({"kind": "task.start", "run": RUN}, TICKET) == []  # the ticket watcher makes these
    assert to_events({"kind": "key.use"}, TICKET) == []
    assert to_events({"nonsense": 1}, TICKET) == [] and to_events({"kind": "step"}, TICKET) == []
    st = to_events(example("valid-run-state-say.json"), TICKET)
    assert st and st[0]["kind"] == "run.state"


def test_text_is_hidden_again_before_it_reaches_the_page():
    e = example("valid-step-started.json", text="Run curl -H 'Authorization: Bearer abcdefghijklmnop1234'")
    assert "abcdefghijklmnop1234" not in json.dumps(to_events(e, TICKET))


def test_feed_follows_the_fake_orch_and_keeps_the_cursor(feed_for):
    f = feed_for()
    got = wait(f)
    assert got and all(e["run"] == RUN and e["ticket"] == TICKET for e in got)
    assert f.cursor and f.cursor.startswith("c")


def test_feed_refuses_a_run_id_that_is_not_one_and_a_missing_orch(feed_for):
    assert feed_for(run="../x").poll() == []
    assert feed_for(orch_bin=None).poll() == []


def test_a_broken_orch_gives_no_steps_and_no_crash(feed_for, tmp_path):
    bad = tmp_path / "nothing-here"
    f = feed_for(orch_bin=str(bad))
    assert f.poll() == []
    time.sleep(0.3)
    assert f.poll() == []


def test_garbled_lines_are_skipped_and_the_cursor_only_moves_on_good_lines(feed_for):
    f = feed_for(run="r_none0001")
    f._line(b"not json")
    f._line(b"[1]")
    f._line(
        json.dumps(
            {"type": "event", "cursor": "rc1.abc", "event": example("valid-step-started.json")}
        ).encode()
    )
    f._line(json.dumps({"type": "error", "error": "x", "cursor": "rc1.zzz"}).encode())
    assert f.cursor == "rc1.abc" and len(f.queue) == 1


def test_restart_passes_the_last_cursor(feed_for):
    f = feed_for()
    assert "--since" not in f._argv()
    f.cursor = "rc1.abc"
    assert f._argv()[-2:] == ["--since", "rc1.abc"] and "--follow" in f._argv()


def test_close_ends_the_followed_command(monkeypatch, tmp_path):
    started = []
    real = record._popen

    def spy(*a, **kw):
        p = real(*a, **kw)
        started.append(p)
        return p

    monkeypatch.setattr(record, "_popen", spy)
    sleeper = tmp_path / "orch"
    sleeper.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    sleeper.chmod(0o755)
    f = RecordFeed(tmp_path, str(sleeper), RUN, TICKET)
    f.poll()
    end = time.time() + 10
    while not started and time.time() < end:
        time.sleep(0.05)
    assert started
    f.close()
    assert started[0].poll() is not None
    assert not any(t.name == "focus-record" and t.is_alive() for t in threading.enumerate())


def test_the_view_shows_live_steps_from_the_record(server, ws, fake_orch, monkeypatch):
    """Through the real server: status says a run is on, the wrapper answers `record tail`, the board shows the step."""
    run = "r_start001"
    wrap = fake_orch.parent / "wrap"
    ev = example("valid-step-started.json", run=run, ticket="t_inv7c2ab", text="Read the March report")
    line = json.dumps({"type": "event", "cursor": "rc1.x", "event": ev})
    wrap.write_text(
        f"#!{sys.executable}\nimport os, sys, time\na = sys.argv[1:]\n"
        f"if a[:2] == ['record', 'tail']:\n    print({line!r}, flush=True)\n    time.sleep(30)\n"
        f"os.execv({str(fake_orch)!r}, [{str(fake_orch)!r}, *a])\n"
    )
    wrap.chmod(0o755)
    (fake_orch.parent / "status.json").write_text(
        json.dumps({"running": True, "claim": {"run": run, "agent": "claude", "mode": "oneshot"}})
    )
    server.tracker.orch_bin = str(wrap)
    from tests.test_server import req

    seen, end = None, time.time() + 15
    while time.time() < end:
        v = json.loads(req(server, "GET", "/api/t/t_inv7c2ab")[1])
        if v["board"]["step"]:
            seen = v["board"]["step"]
            break
        time.sleep(0.2)
    assert seen == "Read the March report"
