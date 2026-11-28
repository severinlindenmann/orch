"""ORCH-2411: the relay inbox lock (relay.locked, also the groups, report and limit-stop locks) and the phone
view state lock are taken over the way the core's ticket lock is since ORCH-2369: under a marker, judged again
there, removed in place. Before, the lock was renamed away and put back, and in that gap another writer could
make a lock of its own, so two were inside."""

import os
import threading
import time

import pytest

from orch import phone_view, procs, relay, tickets
from orch.errors import Refused

DEAD = "999999 -"  # a holder that is gone (no such process)


def _old(path, seconds):
    at = time.time() - seconds
    os.utime(path, (at, at))


def _relay_lock(proj):
    lock = proj / ".orch" / "relay.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    return lock


def _phone_lock(proj):
    lock = phone_view.net.secrets_dir(proj) / "phone-views.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    return lock


LOCKS = [
    pytest.param(_relay_lock, lambda root: relay.locked(root, wait=0.3), relay._break_stale, id="relay"),
    pytest.param(
        _phone_lock, lambda root: phone_view._state_locked(root, wait=0.3), phone_view._break_stale_lock,
        id="phone",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_a_lock_of_a_holder_that_died_is_free_at_once(proj, path, hold, take):
    lock = path(proj)
    lock.write_text(DEAD, encoding="utf-8")  # fresh, but nobody holds it any more
    with hold(proj):
        mine = lock.read_bytes()
        assert mine.decode().startswith(procs.own_token())  # the new holder is named in it
    assert not lock.exists() and not lock.with_name(lock.name + ".take").exists()


@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_an_old_lock_is_taken_over_whoever_is_named_and_a_fresh_one_is_kept(proj, path, hold, take):
    lock = path(proj)
    for left in ("", "not a holder", procs.own_token()):  # nameless, unreadable, a holder that hangs
        lock.write_text(left, encoding="utf-8")
        _old(lock, 3600)
        with hold(proj):
            pass
        assert not lock.exists()
    lock.write_text(procs.own_token(), encoding="utf-8")  # a live holder's fresh lock
    with pytest.raises(Refused, match="busy"), hold(proj):
        pass
    assert lock.read_text(encoding="utf-8") == procs.own_token()  # still that holder's


@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_what_a_late_waiter_finds_under_the_marker_is_left_alone(proj, path, hold, take):
    """The gap of the old way: a waiter saw the dead holder's lock, another took it over and made its own, and
    the late waiter then renamed that fresh lock away. Now it judges again under the marker and keeps it."""
    lock = path(proj)
    lock.write_text(
        procs.own_token(), encoding="utf-8"
    )  # the next holder's fresh lock, found by the late one
    assert take(lock) is False
    assert lock.read_text(encoding="utf-8") == procs.own_token()
    assert not lock.with_name(lock.name + ".take").exists()
    # another waiter is at the takeover right now (its marker is there): this one leaves everything alone
    lock.write_text(DEAD, encoding="utf-8")
    marker = lock.with_name(lock.name + ".take")
    marker.write_text(procs.own_token(), encoding="utf-8")
    assert take(lock) is False and lock.exists() and marker.exists()
    # a waiter killed while it held the marker: the marker is removed by the same rule, then the lock
    marker.write_text(DEAD, encoding="utf-8")
    assert take(lock) is True and not lock.exists() and not marker.exists()


@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_the_lock_is_never_renamed_away(proj, path, hold, take, monkeypatch):
    """Removed in place: the lock's name is never free for a moment while a takeover judges it."""
    lock = path(proj)
    lock.write_text(DEAD, encoding="utf-8")
    moved = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: moved.append((str(a), str(b))) or real(a, b))
    monkeypatch.setattr(os, "rename", lambda a, b: moved.append((str(a), str(b))) or real(a, b))
    with hold(proj):
        pass
    assert not [m for m in moved if lock.name in os.path.basename(m[0])]


@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_a_holder_removes_only_the_lock_it_made(proj, path, hold, take):
    lock = path(proj)
    with hold(proj):
        lock.write_text("someone else", encoding="utf-8")  # taken over meanwhile (this holder was too slow)
    assert lock.read_text(encoding="utf-8") == "someone else"


@pytest.mark.slow
@pytest.mark.parametrize(("path", "hold", "take"), LOCKS)
def test_many_writers_on_a_dead_holders_lock_are_never_two_inside(proj, path, hold, take):
    lock = path(proj)
    wide = (lambda root: relay.locked(root, wait=20)) if take is relay._break_stale else (
        lambda root: phone_view._state_locked(root, wait=20)
    )  # fmt: skip
    inside, most, errors = [0], [0], []
    guard = threading.Lock()

    def writer():
        try:
            for _ in range(15):
                with wide(proj):
                    with guard:
                        inside[0] += 1
                        most[0] = max(most[0], inside[0])
                    time.sleep(0.001)
                    with guard:
                        inside[0] -= 1
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    lock.write_text(DEAD, encoding="utf-8")
    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and most[0] == 1
    assert not list(lock.parent.glob(lock.name + "*"))


def test_two_threads_of_one_process_never_hold_the_same_token():
    a, b = procs.lock_token(), procs.lock_token()
    assert a != b and a.decode().startswith(procs.own_token()) and not procs.owner_dead(a.decode())


def test_the_first_look_is_cheap_and_asks_about_a_holder_only_now_and_then(proj, monkeypatch):
    lock = _relay_lock(proj)
    lock.write_text(procs.own_token(), encoding="utf-8")
    asked = []
    monkeypatch.setattr(procs, "owner_dead", lambda text: asked.append(text) or False)
    looked: dict = {}
    assert [tickets._left_behind(lock, 30, looked) for _ in range(50)] == [False] * 50
    assert len(asked) == 1  # a wait loop turns every 20 ms
    assert tickets._left_behind(lock.with_name("gone.lock"), 30, looked) is False
