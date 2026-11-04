from conftest import T

from orch_scheduler.cron import is_due, next_after, valid


def test_valid():
    assert valid("0 7 * * 1") and not valid("0 7 * *") and not valid("nope") and not valid("0 7 * * * *")


def test_due_inside_window():
    assert is_due("0 7 * * *", T(6, 59), T(7, 1))
    assert not is_due("0 7 * * *", T(7, 0), T(7, 1))  # already ran at 07:00
    assert not is_due("0 7 * * *", T(6, 0), T(6, 59))


def test_missed_runs_collapse_to_one():
    # off for 3 days: still just "due" once; after that run (since=now) nothing is due
    assert is_due("0 7 * * *", T(8, 0, d=1), T(8, 0, d=4))
    assert not is_due("0 7 * * *", T(8, 0, d=4), T(8, 5, d=4))


def test_utc_weekday():
    # 2026-11-02 is a Monday
    assert is_due("0 7 * * 1", T(0, 0, d=1), T(7, 30, d=2))
    assert next_after("0 7 * * 1", T(7, 30, d=2)).day == 9
