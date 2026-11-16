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


# --- ORCH-102: a click answers at once, a cold page load shows content within 1 s -------------------------------

CLICK_LIMIT = (
    1.0  # "its result within 1 s": the click's answer holds the change (the busy state is the page's own)
)
CLICK_BUILD = 1.5  # one full build here: a click that waited for it could not pass CLICK_LIMIT
LOAD_LIMIT = 1.0  # a cold page load: the page, every file it names and the state

FAKE = """#!{py}
import json, pathlib, sys
a = sys.argv[1:]
root = pathlib.Path.cwd()
if a[:2] == ["check", "add"]:  # the click: a task added to the ticket file
    f = root / ".orch" / "tickets" / (a[2] + ".json")
    t = json.loads(f.read_text())
    t["checklist"].append({{"id": "c%d" % (len(t["checklist"]) + 1), "text": a[-1], "done": False}})
    t["revision"] = t.get("revision", 0) + 1
    f.write_text(json.dumps(t))
    print(json.dumps({{"ok": True}})); sys.exit(0)
if a[:2] == ["ticket", "show"]:
    print((root / ".orch" / "tickets" / (a[2] + ".json")).read_text()); sys.exit(0)
if a[:2] == ["review", "list"]:
    print("[]" if "--answered" in a else json.dumps({{"cards": []}})); sys.exit(0)
if a[:2] == ["run", "status"]:
    print(json.dumps({{"runs": {{}}}})); sys.exit(0)
sys.exit(2)  # everything else: as if orch could not say (tickets come from the files)
"""


@pytest.fixture
def click_server(ws, tmp_path, monkeypatch):
    import sys

    from orch_dashboard import server as server_mod
    from orch_dashboard.server import make_server

    fake = tmp_path / "clickorch" / "orch"
    fake.parent.mkdir()
    fake.write_text(FAKE.format(py=sys.executable))
    fake.chmod(0o755)
    builds = []
    real = state_cache.load_state

    def slow(*a, **kw):  # every full build, in the background or in a request, takes CLICK_BUILD
        builds.append(time.monotonic())
        time.sleep(CLICK_BUILD)
        return real(*a, **kw)

    monkeypatch.setattr(state_cache, "load_state", slow)
    monkeypatch.setattr(server_mod, "load_state", slow)
    srv = make_server(ws, 0, orch_bin=str(fake))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}", builds
    srv.revisions.leave()
    srv.shutdown()
    srv.server_close()


def _click(base, text):
    from .test_act import post

    t = time.monotonic()
    code, body, _ = post(base, {"op": "check.add", "args": {"ticket": "t_other003x", "text": text}})
    return code, json.loads(body) if code == 200 else body, time.monotonic() - t


def _tasks(state):
    t = next(x for x in state["tickets"] if x["id"] == "t_other003x")
    return [c["text"] for c in t["checklist"]]


def test_a_click_answers_at_once_with_its_change_while_helpers_work(ws, click_server):
    srv, base, _builds = click_server
    urllib.request.urlopen(base + "/api/state", timeout=30).read()  # the first build (a warm server)
    assert srv.revisions.join()  # an open page's event stream
    stop = threading.Event()
    helpers = _helpers(ws, 5, stop)
    try:
        time.sleep(0.5)  # the helpers' changes keep a background build running
        times = []
        for n in range(3):
            code, state, took = _click(base, f"Step {n}")
            assert code == 200, state
            assert f"Step {n}" in _tasks(state), "the answer holds the click's change"
            times.append(took)
        assert max(times) < CLICK_LIMIT, (
            f"clicks took {[round(x, 2) for x in times]} s (a build takes {CLICK_BUILD} s)"
        )
        # the full build follows in the background and keeps the change; the page is told when it is stored
        rev = srv.revisions.rev
        end = time.monotonic() + 3 * CLICK_BUILD + 2
        while srv.revisions.rev == rev and time.monotonic() < end:
            time.sleep(0.05)
        assert srv.revisions.rev != rev, "the background build was published"
        served = json.loads(urllib.request.urlopen(base + "/api/state", timeout=30).read())
        assert {"Step 0", "Step 1", "Step 2"} <= set(_tasks(served))
    finally:
        stop.set()
        for t in helpers:
            t.join()


def _assets(html):
    import re

    return re.findall(r'(?:src|href)="([^"#:]+)"', html)


def test_a_cold_page_load_shows_content_within_a_second_while_helpers_work(ws, click_server):
    """A browser opens at most 6 connections to the server. The other tabs share one event stream (app.js
    sharedEvents), so 5 are left for the page, its files and the state, while builds are slow and helpers write."""
    from concurrent.futures import ThreadPoolExecutor

    _srv, base, _ = click_server
    urllib.request.urlopen(base + "/api/state", timeout=30).read()  # the server is warm; the browser is cold
    stream = urllib.request.urlopen(base + "/api/events", timeout=30)  # the other tabs' one stream
    stop = threading.Event()
    helpers = _helpers(ws, 5, stop)
    try:
        time.sleep(0.5)
        t = time.monotonic()
        html = urllib.request.urlopen(base + "/", timeout=30).read().decode()
        urls = [*_assets(html), "/api/state", "/api/update-status"]
        assert len(urls) > 30, "the page names its files"

        def get(u):
            with urllib.request.urlopen(base + "/" + u.lstrip("/"), timeout=30) as r:
                r.read()
                return r.status

        with ThreadPoolExecutor(max_workers=5) as pool:
            codes = list(pool.map(get, urls))
        took = time.monotonic() - t
        assert all(c == 200 for c in codes), dict(zip(urls, codes, strict=True))
        assert took < LOAD_LIMIT, f"cold load of {len(urls) + 1} requests took {took:.2f} s"
    finally:
        stop.set()
        for th in helpers:
            th.join()
        stream.close()
