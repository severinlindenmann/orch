"""Opus delta review of #287 (F6): concurrent sync passes send a finished ticket's result once, and a
remember() racing a sync is not lost. Copy into workspace/tests/."""

import threading
import time

import pytest
from test_ticket_view import conn  # noqa: F401  (fixture)

from orch import mobile_mode, phone_view, tickets


@pytest.fixture
def mm(monkeypatch):
    monkeypatch.setattr(mobile_mode, "routes_to_phone", lambda root: True)


def _par(n, fn):
    ts = [threading.Thread(target=fn) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def test_parallel_syncs_push_one_result(proj, run, new_ticket, conn, mm):  # noqa: F811
    tid = new_ticket("Finish me")
    phone_view.sync(proj)
    tickets.set_status(proj, tid, "review", "human:t")
    n = len(conn.sent)
    _par(6, lambda: phone_view.sync(proj))
    res = [
        m for m in conn.sent[n:] if m["body"].get("update", {}).get("kind") == "result" and m["ticket"] == tid
    ]
    assert len(res) == 1, len(res)


def test_parallel_remember_calls_are_all_kept(proj, run, new_ticket, conn):  # noqa: F811
    ids = [new_ticket(f"T{i}") for i in range(8)]
    it = iter(ids)
    lock = threading.Lock()

    def one():
        with lock:
            tid = next(it)
        phone_view.remember(proj, tid, "ph_x")

    _par(8, one)
    st = phone_view.load_state(proj)
    assert set(ids) <= set(st["tickets"]) and set(ids) <= set(st["synced"]["ph_x"])


def test_lock_is_released_after_a_failing_update(proj):
    with pytest.raises(ZeroDivisionError):
        phone_view.update_state(proj, lambda st: 1 / 0)
    t = time.monotonic()
    phone_view.update_state(proj, lambda st: None)
    assert time.monotonic() - t < 1
