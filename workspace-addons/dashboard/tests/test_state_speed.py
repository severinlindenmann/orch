"""Timing: /api/state stays fast while helpers change files, however many helpers there are.

Report r-1116-1940-ws (16 Nov, 4 to 8 helpers): every helper step changed a ticket or run file, every page request
then built the whole state before it answered (a dozen `orch` processes), 160 of 160 answers were built in their
request and took 3 to 20 s. Here a build is made slow on purpose (as on a busy machine) and helpers are simulated by
threads that rewrite ticket and run files several times a second."""

import json
import threading
import time
import urllib.request

import pytest

from orch_dashboard import state_cache

SLOW_BUILD = 0.6  # seconds one state build takes here (on the busy machine of the report: 3 to 7 s)
ANSWER_LIMIT = 0.5  # every answer, generous for a loaded CI runner; the copy is served from memory


def _get(url):
    t = time.monotonic()
    with urllib.request.urlopen(url, timeout=30) as r:
        json.loads(r.read())
        return time.monotonic() - t, int(r.headers["X-State-Age-Ms"])


@pytest.fixture
def slow_builds(monkeypatch):
    builds = []
    real = state_cache.load_state

    def slow(*a, **kw):
        builds.append(time.monotonic())
        time.sleep(SLOW_BUILD)
        return real(*a, **kw)

    monkeypatch.setattr(state_cache, "load_state", slow)
    return builds


def _helpers(ws, n, stop):
    """n helpers: each rewrites its own ticket file and run heartbeat about 5 times a second."""
    run = ws / ".orch" / "run" / "tickets"
    run.mkdir(parents=True, exist_ok=True)

    def work(i):
        k = 0
        while not stop.is_set():
            k += 1
            (ws / ".orch" / "tickets" / f"t_helper{i:02d}.json").write_text(
                json.dumps({"id": f"t_helper{i:02d}", "k": k})
            )
            (run / f"t_helper{i:02d}.json").write_text(json.dumps({"heartbeat": k}))
            time.sleep(0.2)

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    return threads


def _measure(ws, helpers, seconds=3.0, tabs=3):
    from orch_dashboard.server import make_server

    srv = make_server(ws, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/state"
    stop = threading.Event()
    times, errors = [], []
    try:
        _get(base)  # the first build: the only one a request may wait for
        assert srv.revisions.join()  # an open page's event stream: the watcher runs
        threads = _helpers(ws, helpers, stop)

        def tab():
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    times.append(_get(base)[0])
                except Exception as e:  # noqa: BLE001 - counted, the test fails on it below
                    errors.append(e)
                time.sleep(0.1)

        tabs_ = [threading.Thread(target=tab) for _ in range(tabs)]
        for t in tabs_:
            t.start()
        for t in tabs_:
            t.join()
        stop.set()
        for t in threads:
            t.join()
    finally:
        stop.set()
        srv.revisions.leave()
        srv.shutdown()
        srv.server_close()
    assert not errors, errors
    return sorted(times)


@pytest.mark.parametrize("helpers", [1, 6])
def test_state_answers_stay_fast_while_helpers_work(ws, slow_builds, helpers):
    times = _measure(ws, helpers)
    builds_during = len(slow_builds) - 1
    assert len(times) >= 30, "the tabs asked often"
    assert times[-1] < ANSWER_LIMIT, (
        f"{helpers} helpers: slowest answer {times[-1]:.2f}s (builds take {SLOW_BUILD}s)"
    )
    # builds are bounded by time (one at a time, a rest between them), never by the number of requests
    most = int(3.0 / (SLOW_BUILD + state_cache.MIN_GAP)) + 2
    assert builds_during <= most, f"{builds_during} builds for {len(times)} requests in 3 s"
    assert builds_during >= 1, "the changes reached the copy"


def test_more_helpers_do_not_make_answers_slower(ws, slow_builds):
    few = _measure(ws, 1)
    many = _measure(ws, 8)
    p90 = lambda xs: xs[int(len(xs) * 0.9)]
    assert p90(many) < ANSWER_LIMIT, f"8 helpers: p90 {p90(many):.3f}s"
    assert p90(many) < max(0.25, 3 * p90(few)), f"p90 1 helper {p90(few):.3f}s, 8 helpers {p90(many):.3f}s"
