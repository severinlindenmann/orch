import json
import threading
import time
import urllib.request

import pytest

from orch_dashboard import data, state_cache
from orch_dashboard.data import load_state


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read()), r.headers


def _post(url, body):
    from .test_act import post

    code, text, _h = post(url, body)
    assert code == 200, text
    return json.loads(text)


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = state_cache.load_state

    def counting(*a, **kw):
        calls.append(time.monotonic())
        return real(*a, **kw)

    monkeypatch.setattr(state_cache, "load_state", counting)
    return calls


def test_two_quick_gets_build_once(server, counted):
    a, _h1 = _get(server + "/api/state")
    b, h2 = _get(server + "/api/state")
    assert len(counted) == 1
    assert a["rev"] == b["rev"] and int(h2["X-State-Age-Ms"]) >= 0


def test_state_shape_unchanged(server, ws):
    got, _h = _get(server + "/api/state")
    direct = load_state(ws, with_settings=True)
    assert got.keys() == direct.keys()
    # settings.copies_disk is measured in the background (it can arrive between two reads), so `rev` may differ
    assert got["settings"].keys() == direct["settings"].keys()
    for k in direct.keys() - {"now", "rev", "settings"}:
        assert got[k] == direct[k], k


def test_first_build_is_single_flight(ws, counted):
    cache = state_cache.StateCache(ws, None)
    threads = [threading.Thread(target=cache.get) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(counted) == 1


def test_ticket_change_triggers_rebuild(server, ws):
    first, _h = _get(server + "/api/state")
    f = ws / ".orch" / "tickets" / "t_7k3f9q.json"
    t = json.loads(f.read_text())
    t["title"] = "Changed on disk"
    f.write_text(json.dumps(t))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        s, _h = _get(server + "/api/state")
        if any(x["title"] == "Changed on disk" for x in s["tickets"]):
            assert s["rev"] != first["rev"]
            return
        time.sleep(0.1)
    pytest.fail("the ticket change never reached /api/state")


def test_failed_rebuild_keeps_old_copy(ws, monkeypatch):
    cache = state_cache.StateCache(ws, None)
    old, _age = cache.get()
    monkeypatch.setattr(state_cache, "load_state", lambda *a, **kw: 1 / 0)
    cache.at -= 10
    cache.get()
    deadline = time.monotonic() + 2
    while cache.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    s, age = cache.get()
    assert s["rev"] == old["rev"] and age >= 10


def test_post_act_replaces_the_copy(act_server, monkeypatch):
    _get(act_server + "/api/state")
    marker = {"n": 0}
    real = load_state

    def fresh(*a, **kw):
        s = real(*a, **kw)
        if kw.get("fresh"):
            marker["n"] += 1
            s["skipped"] = 100 + marker["n"]
        return s

    import orch_dashboard.server as server_mod

    monkeypatch.setattr(server_mod, "load_state", fresh)
    reply = _post(act_server, {"op": "log", "args": {"ticket": "t_7k3f9q", "text": "hi"}})
    after, _h = _get(act_server + "/api/state")
    assert after["skipped"] == reply["skipped"] == 101


def test_parallel_load_state_matches_serial(ws, monkeypatch):
    from concurrent.futures import Future

    class Serial:  # runs each job at submit time: the old, one-after-the-other order
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, *a, **kw):
            f = Future()
            try:
                f.set_result(fn(*a, **kw))
            except Exception as e:  # noqa: BLE001 - handed to the Future, as the pool does
                f.set_exception(e)
            return f

    monkeypatch.setattr(data, "copies_disk", lambda root: None)  # measured in the background: not stable
    parallel = load_state(ws, with_settings=True)
    monkeypatch.setattr(data, "ThreadPoolExecutor", Serial)
    serial = load_state(ws, with_settings=True)
    assert parallel["rev"] == serial["rev"]
    assert {k: v for k, v in parallel.items() if k != "now"} == {
        k: v for k, v in serial.items() if k != "now"
    }


def test_worker_exception_propagates(ws, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("chat broke")

    monkeypatch.setattr(data, "load_chat", boom)
    with pytest.raises(RuntimeError, match="chat broke"):
        load_state(ws, with_settings=True)


def test_changed_ticket_file_is_served_fresh_at_once(server, ws, counted):
    """The page is told about a change and fetches once: that answer must already hold the change."""
    _get(server + "/api/state")
    n = len(counted)
    from orch_dashboard import events

    tickets = ws / ".orch" / "tickets"
    tickets.mkdir(parents=True, exist_ok=True)
    (tickets / "t_zzzzzz.json").write_text("{}")
    got, _h = _get(server + "/api/state")
    assert len(counted) == n + 1, "a changed file rebuilds the state before answering"
    assert events.Revisions(ws).signature()  # sanity: the signature saw the file


def test_fresh_flag_always_rebuilds(server, counted):
    _get(server + "/api/state")
    n = len(counted)
    _get(server + "/api/state?fresh=1")
    assert len(counted) == n + 1
