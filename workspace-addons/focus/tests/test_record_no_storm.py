"""ORCH-266: Focus must never become a stream of `orch record tail` processes.

One followed command per running run, none for a run that ended (one plain read catches it up), and a followed
command that ends at once is started again later each time. Counted through the `_popen` hook over 10 seconds.
"""

import sys
import threading
import time

import pytest

from orch_focus import record
from orch_focus.record import RecordFeed

TICKET = "t_inv7c2"


def _script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\n{body}\n")
    p.chmod(0o755)
    return str(p)


@pytest.fixture
def started(monkeypatch):
    calls, procs = [], []
    real = record._popen

    def spy(argv, *a, **kw):
        calls.append(list(argv))
        p = real(argv, *a, **kw)
        procs.append(p)
        return p

    monkeypatch.setattr(record, "_popen", spy)
    yield calls
    for p in procs:
        if p.poll() is None:
            p.kill()
            p.wait()


def _drive(feeds, live, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        for f, on in zip(feeds, live, strict=True):
            f.poll(live=on)
        time.sleep(0.2)


def test_twenty_runs_over_ten_seconds_start_few_processes(tmp_path, started):
    """10 running runs whose command ends at once (no record yet) and 10 ended runs, polled 5 times a second.
    Before the fix: a restart every 2 s for each of the 20 runs (100+ processes). Now: 3 per running run
    (0 s, 2 s, 6 s) and one plain read per ended run."""
    quick = _script(tmp_path, "orch", "import sys\nsys.exit(2)")
    feeds = [RecordFeed(tmp_path, quick, f"r_storm{i:03d}", TICKET) for i in range(20)]
    live = [i < 10 for i in range(20)]
    try:
        _drive(feeds, live, 10.0)
    finally:
        for f in feeds:
            f.close()
    follows = [c for c in started if "--follow" in c]
    plain = [c for c in started if "--follow" not in c]
    assert len(plain) == 10, plain  # one catch-up read per ended run, never repeated
    assert all(c[c.index("--run") + 1] >= "r_storm000" for c in started)
    assert len(follows) <= 10 * 4, len(follows)
    assert len(started) <= 50
    assert not any(t.name == "focus-record" and t.is_alive() for t in threading.enumerate())


def test_a_running_run_keeps_one_long_lived_follower(tmp_path, started):
    sleeper = _script(tmp_path, "orch", "import time\ntime.sleep(60)")
    feeds = [RecordFeed(tmp_path, sleeper, f"r_live{i:03d}", TICKET) for i in range(20)]
    try:
        _drive(feeds, [True] * 20, 3.0)
    finally:
        for f in feeds:
            f.close()
    assert len(started) == 20 and all("--follow" in c for c in started)


def test_a_run_that_ends_stops_its_follower_and_reads_once(tmp_path, started):
    sleeper = _script(tmp_path, "orch", "import time\ntime.sleep(60)")
    f = RecordFeed(tmp_path, sleeper, "r_ends0001", TICKET)
    try:
        f.poll(live=True)
        time.sleep(0.5)
        assert f.proc is not None and f.proc.poll() is None
        first = f.proc
        f.poll(live=False)
        first.wait(timeout=5)  # the followed command ended with the run
        _drive([f], [False], 1.0)
        assert [("--follow" in c) for c in started] == [True, False]
        f.poll(live=True)  # it runs again: one new follower
        time.sleep(0.3)
        assert sum("--follow" in c for c in started) == 2
    finally:
        f.close()


def test_rest_ends_the_follower_of_a_run_nobody_looks_at(tmp_path, started):
    sleeper = _script(tmp_path, "orch", "import time\ntime.sleep(60)")
    f = RecordFeed(tmp_path, sleeper, "r_rest0001", TICKET)
    try:
        f.poll(live=True)
        time.sleep(0.5)
        p = f.proc
        f.rest()
        p.wait(timeout=5)
        assert not f.following
    finally:
        f.close()


def test_back_off_doubles_and_resets_after_a_long_follow(monkeypatch, tmp_path):
    f = RecordFeed(tmp_path, "orch", "r_back0001", TICKET)
    waits = []
    halt = threading.Event()
    clock = iter([0.0, 0.1, 1.0, 1.1, 2.0, 2.1, 3.0, 30.0, 31.0, 31.1])
    monkeypatch.setattr(record.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(f, "_once", lambda h, follow=True: None)

    class Halt:
        def is_set(self):
            return halt.is_set()

        def wait(self, secs):
            waits.append(secs)
            if len(waits) == 5:
                halt.set()
            return halt.is_set()

    f._loop(Halt(), True)
    assert waits == [2.0, 4.0, 8.0, 2.0, 2.0]
