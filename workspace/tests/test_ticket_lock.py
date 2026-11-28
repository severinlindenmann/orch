"""The per-ticket write lock when a dead writer's lock is taken over (ORCH-2369, R8.2)."""

import os
import threading
import time

import pytest

from orch import tickets


def _three_writers_on_a_dead_lock(proj, tid, monkeypatch):
    """Writers A, B and C wait on a dead writer's lock. B judges the dead writer's lock and is then held back
    until A has taken the ticket; whenever B looks at a holder again it gives C time to get in. Returns the
    most writers that were inside the lock at once."""
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text("999999 -", encoding="utf-8")  # named, and gone
    a_inside, c_inside = threading.Event(), threading.Event()
    real, b_looks = tickets.procs.owner_dead, []
    state = {"inside": 0, "most": 0}
    mutex = threading.Lock()

    def owner_dead(text):
        if threading.current_thread().name != "B":
            return real(text)
        b_looks.append(text)
        if len(b_looks) == 1:
            dead = real(text)
            a_inside.wait(5)  # B judged the dead writer's lock; A takes the ticket before B acts on it
            return dead
        c_inside.wait(0.5)  # the old gap: the lock B took away was A's fresh one, and C made its own
        return real(text)

    monkeypatch.setattr(tickets.procs, "owner_dead", owner_dead)

    def writer():
        me = threading.current_thread().name
        with tickets._locked(proj, tid):
            with mutex:
                state["inside"] += 1
                state["most"] = max(state["most"], state["inside"])
            {"A": a_inside, "C": c_inside}.get(me, threading.Event()).set()
            time.sleep(1.5 if me == "A" else 0.05)
            with mutex:
                state["inside"] -= 1

    threads = {n: threading.Thread(target=writer, name=n) for n in "BAC"}
    threads["B"].start()
    for _ in range(500):
        if b_looks:
            break
        time.sleep(0.01)
    threads["A"].start()
    assert a_inside.wait(5)
    threads["C"].start()
    for t in threads.values():
        t.join(15)
    assert not any(t.is_alive() for t in threads.values()) and len(b_looks) >= 2
    return state["most"]


@pytest.mark.slow
def test_three_writers_on_a_dead_writers_lock_are_never_two_inside(proj, new_ticket, monkeypatch):
    """A waiter that judged a dead writer's lock a moment too early used to rename away the fresh lock of the
    writer that took over, and a third writer made its own lock before it was put back."""
    tid = new_ticket()
    assert _three_writers_on_a_dead_lock(proj, tid, monkeypatch) == 1
    assert not list((proj / ".orch" / "tickets").glob(".lock-*"))  # every lock and marker is gone again


def test_a_takeover_killed_halfway_does_not_block_the_ticket(proj, run, new_ticket):
    """The waiter that removes a dead writer's lock holds a marker while it does. Killed right then, it leaves
    the marker behind (named, or still empty); the next writer removes both."""
    tid = new_ticket()
    d = proj / ".orch" / "tickets"
    lock, marker = d / f".lock-{tid}", d / f".lock-{tid}.take"
    for left in ("999998 -", ""):
        lock.write_text("999999 -", encoding="utf-8")
        marker.write_text(left, encoding="utf-8")
        old = time.time() - 3 * 86400
        os.utime(marker, (old, old))
        assert run("log", tid, "x")[0] == 0 and not list(d.glob(".lock-*"))
    lock.write_text("999999 -", encoding="utf-8")
    marker.write_text(tickets.procs.own_token(), encoding="utf-8")  # a live waiter is at it: left alone
    assert tickets._break_stale(lock) is False and lock.exists() and marker.exists()


def test_a_fresh_lock_is_never_taken_for_the_dead_one(proj, new_ticket):
    """What a late waiter finds under the marker is the next writer's lock: it stays."""
    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text(tickets.procs.own_token(), encoding="utf-8")
    assert tickets._break_stale(lock) is False
    assert lock.read_text(encoding="utf-8") == tickets.procs.own_token()
    assert not lock.with_name(lock.name + ".take").exists()


def test_a_writer_unlocks_only_its_own_lock(proj, new_ticket):
    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    with tickets._locked(proj, tid):
        lock.write_text("424242 -", encoding="utf-8")  # another writer's lock sits there now
    assert lock.read_text(encoding="utf-8") == "424242 -"
