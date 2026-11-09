"""Run hook ordering, isolation and live delivery gate."""

import pytest

from orch import runhooks, runs, runs_live, tickets


@pytest.fixture(autouse=True)
def registry():
    runhooks.reset()
    yield
    runhooks.reset()


def broken(**info):
    raise RuntimeError("hook failed")


def test_defaults_and_order():
    for point in runhooks.POINTS:
        assert runhooks.fire(point) is None
        assert runhooks.gate(point) is True
    seen = []
    runhooks.register("run_start", lambda **info: seen.append((1, info)))
    runhooks.register("run_start", broken)
    runhooks.register("run_start", lambda **info: seen.append((2, info)))
    runhooks.fire("run_start", run="example")
    assert seen == [(1, {"run": "example"}), (2, {"run": "example"})]


def test_gate_and_unregister():
    seen = []
    hold = lambda **info: False  # noqa: E731
    runhooks.register("before_paste", hold)
    runhooks.register("before_paste", lambda **info: seen.append(info))
    assert runhooks.gate(run="example") is False
    assert seen == [{"run": "example"}]
    runhooks.unregister("before_paste", hold)
    runhooks.unregister("before_paste", hold)
    assert runhooks.gate() is True
    runhooks.register("before_paste", broken)
    assert runhooks.gate() is False
    runhooks.reset()
    assert runhooks.gate() is True


def test_unknown():
    for call in (runhooks.fire, runhooks.gate):
        with pytest.raises(ValueError):
            call("unknown")
    for call in (runhooks.register, runhooks.unregister):
        with pytest.raises(ValueError):
            call("unknown", broken)


def test_callbacks_can_change_registry():
    seen = []

    def first(**info):
        runhooks.reset()
        seen.append(1)

    runhooks.register("run_end", first)
    runhooks.register("run_end", lambda **info: seen.append(2))
    runhooks.fire("run_end")
    runhooks.fire("run_end")
    assert seen == [1, 2]


def test_lifecycle_and_held_delivery(proj, monkeypatch):
    seen = []
    for point in ("run_start", "run_state", "run_end", "event_line"):
        runhooks.register(point, lambda point=point, **info: seen.append((point, info)))
    tid = tickets.create(proj, "Hook integration", "human:test")["id"]
    rec = runs.claim(proj, tid, "human:test", "generic", "live")
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: True)
    monkeypatch.setattr(runs_live, "_hold_reason", lambda *a: None)
    typed = []
    monkeypatch.setattr(runs_live, "_type_line", lambda *a: typed.append(a) or True)
    item = runs.pending_add(proj, tid, "human:test", "message", "Queued input")
    hold = lambda **info: False  # noqa: E731
    runhooks.register("before_paste", hold)
    assert runs_live.event(proj, "idle", rec["run"], tid, None) == 0
    assert typed == []
    assert [i["id"] for i in runs.undelivered(proj, tid)] == [item["id"]]
    assert runs.read(proj, tid)["live"]["state"] == "idle"
    runhooks.unregister("before_paste", hold)
    assert runs_live.deliver(proj, tid) == 1
    assert len(typed) == 1
    assert runs.release(proj, tid, rec["run"])["released"]
    assert not runs.release(proj, tid, rec["run"])["released"]
    assert [point for point, _ in seen] == ["run_start", "run_state", "event_line", "run_end"]
    for _, info in seen:
        assert (info["root"], info["tid"], info["run"]) == (proj, tid, rec["run"])
    assert seen[1][1]["state"] == "idle"
    assert seen[2][1]["kind"] == "idle"
