"""Usage picks tool, account and model per helper start, holds the money first, and counts a start once (ORCH-658)."""

import threading
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from orch_usage import picker, store

TUE = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)  # a Tuesday


def sources(**over):
    rows = [
        {
            "id": "a_sub001",
            "label": "Claude main",
            "tool": "claude",
            "type": "subscription",
            "on": True,
            "week_used": 10.0,
            "resets": "2026-11-17T15:00:00Z",
        },
        {
            "id": "a_sub002",
            "label": "Claude second",
            "tool": "claude",
            "type": "subscription",
            "on": True,
            "week_used": 10.0,
            "resets": "2026-11-17T16:00:00Z",
        },
        {
            "id": "a_key001",
            "label": "OpenAI credit",
            "tool": "codex",
            "type": "api-key",
            "on": True,
            "left": 100.0,
            "day_limit": 10.0,
            "spent_today": 0.0,
            "models": {"opus": "gpt-big", "sonnet": "gpt-small"},
        },
        {
            "id": "a_cdx001",
            "label": "Codex subscription",
            "tool": "codex",
            "type": "subscription",
            "on": True,
            "week_used": 10.0,
            "model": "gpt-big",
        },
    ]
    for r in rows:
        r.update(over.get(r["id"], {}))
    return rows


SHARE = {
    "order": ["a_sub001", "a_sub002", "a_key001", "a_cdx001"],
    "credit_kinds": ["reviews"],
    "codex_one_in": 4,
}


def req(n, kind="code", model="sonnet"):
    return {"start": f"s{n}", "ticket": f"ORCH-{n}", "kind": kind, "model": model}


def test_twenty_starts_follow_the_share(tmp_path):
    src = sources(a_sub001={"at_limit": True})  # the first subscription is full: skipped
    kinds = ["code"] * 12 + ["reviews"] * 4 + ["helpers"] * 4
    order = [kinds[i] for i in (0, 12, 1, 16, 2, 3, 13, 4, 17, 5, 6, 14, 7, 18, 8, 9, 15, 10, 19, 11)]
    picks = [
        picker.pick(tmp_path, req(i, k), SHARE, src, TUE + timedelta(minutes=i)) for i, k in enumerate(order)
    ]
    got = Counter(p.source for p in picks)
    assert got == {"a_sub002": 13, "a_key001": 4, "a_cdx001": 3}
    assert all(p.why.startswith("runs on ") and not p.wait for p in picks)
    assert all("Claude main at its limit" in p.why for p in picks if p.source == "a_sub002")
    reviews = [p for p, k in zip(picks, order) if k == "reviews"]
    assert {p.tool for p in reviews} == {"codex"} and {p.model for p in reviews} == {"gpt-small"}
    assert all("review work goes to API credit" in p.why for p in reviews)
    codex = [p for p in picks if p.source == "a_cdx001"]
    assert all("one in 4 code starts goes to Codex" in p.why and p.model == "gpt-big" for p in codex)
    assert {p.model for p in picks if p.source == "a_sub002"} == {"sonnet"}
    day = picker.spread(tmp_path, "2026-11-17")
    assert {k: v["starts"] for k, v in day.items()} == {"a_sub002": 13, "a_key001": 4, "a_cdx001": 3}
    assert day["a_key001"]["dollars"] == pytest.approx(4 * 1.05)
    assert day["a_sub002"]["dollars"] == 0  # a subscription holds no money


def test_starts_at_the_same_time_cannot_overspend_the_day(tmp_path):
    src = sources(a_key001={"day_limit": 5.0})  # room for 4 holds of 1.05, not 5
    out, gate = [], threading.Barrier(8)

    def go(i):
        gate.wait()
        out.append(picker.pick(tmp_path, req(i, "reviews"), SHARE, src, TUE))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    on_key = [p for p in out if p.source == "a_key001"]
    assert len(out) == 8 and len(on_key) == 4
    assert all(
        p.source == "a_sub001" and "OpenAI credit at its day limit" in p.why for p in out if p not in on_key
    )
    assert picker.spread(tmp_path, "2026-11-17")["a_key001"]["dollars"] <= 5.0


def test_held_money_counts_against_what_is_left(tmp_path):
    src = sources(a_key001={"left": 2.0, "day_limit": None})
    a = picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)
    b = picker.pick(tmp_path, req(2, "reviews"), SHARE, src, TUE)
    assert a.source == "a_key001" and b.source == "a_sub001"
    assert "OpenAI credit only $0.95 left" in b.why


def test_all_sources_empty_waits_with_a_reason(tmp_path):
    src = sources(
        a_sub001={"at_limit": True},
        a_sub002={"on": False},
        a_key001={"left": 0.0},
        a_cdx001={"at_limit": True, "resets": "2026-11-17T12:30:00Z"},
    )
    p = picker.pick(tmp_path, req(1), SHARE, src, TUE)
    assert p.wait and p.source is None
    assert p.why == (
        "waits: no account has room (Claude main at its limit, Claude second off, OpenAI credit empty, "
        "Codex subscription at its limit)"
    )
    assert p.until == "2026-11-17T12:30:00Z"  # the earliest reset of a source that is on
    assert picker.spread(tmp_path, "2026-11-17") == {}  # a wait holds nothing
    assert picker.pick(tmp_path, req(2), {}, [], TUE).why == "waits: no account has room (none is set up)"


def test_a_day_limit_wait_wakes_at_midnight(tmp_path):
    src = [sources()[2] | {"day_limit": 1.0}]
    p = picker.pick(tmp_path, req(1), {}, src, TUE)
    assert p.wait and p.until == "2026-11-18T00:00:00Z"


def test_a_retried_start_counts_once(tmp_path):
    src = sources()
    a = picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)
    b = picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE + timedelta(minutes=1))
    assert not a.repeat and b.repeat and (b.source, b.model, b.why) == (a.source, a.model, a.why)
    assert picker.started(tmp_path, "s1")
    c = picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE + timedelta(minutes=2))
    assert c.repeat and c.source == a.source
    assert picker.spread(tmp_path, "2026-11-17") == {
        "a_key001": {"label": "OpenAI credit", "starts": 1, "dollars": 1.05}
    }


def test_a_failed_start_gives_the_money_back_and_its_retry_counts_once(tmp_path):
    src = sources(a_key001={"day_limit": 1.5})
    assert picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE).source == "a_key001"
    assert (
        picker.pick(tmp_path, req(2, "reviews"), SHARE, src, TUE).source == "a_sub001"
    )  # 1.05 held, 1.5 a day
    assert picker.failed(tmp_path, "s1")
    assert not picker.failed(tmp_path, "s1")  # already given back
    assert (
        picker.pick(tmp_path, req(3, "reviews"), SHARE, src, TUE).source == "a_key001"
    )  # the money is free again
    again = picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)  # s1 tried again: picks anew
    assert not again.repeat and again.source == "a_sub001"
    day = picker.spread(tmp_path, "2026-11-17")
    assert day["a_key001"]["starts"] == 1 and day["a_sub001"]["starts"] == 2  # s1 once, s2
    assert picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE).repeat


def test_a_failed_start_does_not_count_for_one_in_n(tmp_path):
    src, share = sources(), {**SHARE, "codex_one_in": 2}
    assert picker.pick(tmp_path, req(1), share, src, TUE).source == "a_sub001"
    picker.failed(tmp_path, "s1")
    assert picker.pick(tmp_path, req(2), share, src, TUE).source == "a_sub001"  # still the first code start
    assert picker.pick(tmp_path, req(3), share, src, TUE).source == "a_cdx001"


def test_a_hold_that_never_started_goes_back(tmp_path):
    src = sources(a_key001={"day_limit": 1.5})
    assert picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE).source == "a_key001"
    late = TUE + timedelta(hours=picker.HOLD_HOURS, minutes=1)
    assert picker.pick(tmp_path, req(2, "reviews"), SHARE, src, late).source == "a_key001"


def test_finished_uses_the_real_spend(tmp_path):
    src = sources(a_key001={"day_limit": 2.0, "spent_today": None})
    picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)
    picker.started(tmp_path, "s1")
    assert picker.finished(tmp_path, "s1", 0.12)
    assert picker.spread(tmp_path, "2026-11-17")["a_key001"]["dollars"] == 0.12
    p = picker.pick(tmp_path, req(2, "reviews"), SHARE, src, TUE)
    assert p.source == "a_key001" and "$1.17 of $2 today" in p.why


def test_a_share_change_applies_to_the_next_start_and_keeps_the_holds(tmp_path):
    src = sources(a_key001={"day_limit": 2.0})
    assert picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE).source == "a_key001"
    new = {"order": ["a_key001", "a_sub001"], "codex_one_in": 0}
    p = picker.pick(tmp_path, req(2, "helpers"), new, src, TUE)
    assert (
        p.source == "a_sub001" and "OpenAI credit at its day limit" in p.why
    )  # 1.05 held under the old share
    assert picker.pick(tmp_path, req(1, "reviews"), new, src, TUE).repeat  # an old start keeps its pick
    picker.failed(tmp_path, "s1")
    assert picker.pick(tmp_path, req(3, "helpers"), new, src, TUE).source == "a_key001"


def test_the_day_turning_over_frees_the_day_limit(tmp_path):
    src = sources(a_key001={"day_limit": 1.5})
    late = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)
    picker.pick(tmp_path, req(1, "reviews"), SHARE, src, late)
    picker.started(tmp_path, "s1")
    assert picker.pick(tmp_path, req(2, "reviews"), SHARE, src, late).source == "a_sub001"
    next_day = late + timedelta(hours=1, minutes=30)
    assert picker.pick(tmp_path, req(3, "reviews"), SHARE, src, next_day).source == "a_key001"
    assert set(picker.spread(tmp_path, "2026-11-18")) == {"a_key001"}


def test_old_days_are_dropped(tmp_path):
    picker.pick(tmp_path, req(1), {}, sources(), TUE)
    picker.pick(tmp_path, req(2), {}, sources(), TUE + timedelta(days=picker.KEEP_DAYS + 1))
    assert picker.spread(tmp_path, "2026-11-17") == {}


def test_the_week_line():
    week = {"wed": 70}
    assert picker.week_line(week, datetime(2026, 11, 16, 0, 0, tzinfo=UTC)) == 0  # Monday start
    assert picker.week_line(week, datetime(2026, 11, 19, 0, 0, tzinfo=UTC)) == 70  # end of Wednesday
    assert picker.week_line(week, datetime(2026, 11, 22, 23, 59, tzinfo=UTC)) == pytest.approx(100, abs=0.1)
    assert picker.week_line(week, datetime(2026, 11, 17, 12, 0, tzinfo=UTC)) == pytest.approx(
        70 * 36 / 72, abs=0.1
    )
    assert picker.week_line(None, TUE) is None and picker.week_line({"xyz": 5}, TUE) is None


def test_ahead_of_the_week_moves_starts_to_credit_up_to_the_day_budget_and_the_week_turning_over(tmp_path):
    share = {**SHARE, "week": {"wed": 70}, "ahead_dollars_day": 2.0, "codex_one_in": 0}
    ahead = sources(a_sub001={"week_used": 60.0}, a_sub002={"week_used": 55.0}, a_cdx001={"on": False})
    p1 = picker.pick(tmp_path, req(1, "helpers"), share, ahead, TUE)  # Tuesday 10:00: line about 33 %
    assert (
        p1.source == "a_key001" and "subscriptions are ahead of the week (55% used, 33.1% planned" in p1.why
    )
    assert (
        picker.pick(tmp_path, req(2, "helpers"), share, ahead, TUE).source == "a_sub001"
    )  # 2 dollars a day spent
    behind = sources(a_sub001={"week_used": 20.0}, a_cdx001={"on": False})
    assert picker.pick(tmp_path, req(3, "helpers"), share, behind, TUE).source == "a_sub001"
    monday = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)  # the week turned: the readers say little is used
    fresh = sources(a_sub001={"week_used": 0.5}, a_sub002={"week_used": 0.5}, a_cdx001={"on": False})
    assert picker.pick(tmp_path, req(4, "helpers"), share, fresh, monday).source == "a_sub001"
    still = sources(a_sub001={"week_used": 30.0}, a_sub002={"week_used": 30.0}, a_cdx001={"on": False})
    assert (
        picker.pick(tmp_path, req(5, "helpers"), share, still, monday).source == "a_key001"
    )  # new day, new budget


def test_start_id_is_required_and_bad_rows_are_ignored(tmp_path):
    with pytest.raises(store.Refused):
        picker.pick(tmp_path, {"kind": "code"}, SHARE, sources(), TUE)
    p = picker.pick(tmp_path, req(1), {"order": [5, None]}, [None, {"label": "no id"}, *sources()], TUE)
    assert p.source == "a_sub001"
    f = store.usage_dir(tmp_path) / picker.STARTS
    f.write_text("not json")
    with pytest.raises(store.Refused, match="damaged"):
        picker.pick(tmp_path, req(2), SHARE, sources(), TUE)
    assert f.read_text() == "not json"  # kept for a person to look at, never overwritten


def test_never_writes_a_key(tmp_path):
    picker.pick(tmp_path, req(1, "reviews"), SHARE, sources(), TUE)
    entry = picker._load(tmp_path)["s1"]
    assert set(entry) == {
        "state",
        "at",
        "day",
        "ticket",
        "kind",
        "source",
        "label",
        "tool",
        "type",
        "model",
        "dollars",
        "ahead",
        "why",
        "tries",
    }  # labels, numbers and times only


def test_a_finished_start_still_counts_while_the_reader_lags(tmp_path):
    src = sources(
        a_key001={"left": 2.0, "left_at": "2026-11-17T09:00:00Z", "day_limit": 1.5, "spent_today": 0.0}
    )
    picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)
    picker.started(tmp_path, "s1")
    picker.finished(tmp_path, "s1", 1.0, TUE)
    p = picker.pick(tmp_path, req(2, "reviews"), SHARE, src, TUE)
    assert p.source == "a_sub001" and "OpenAI credit only $1 left" in p.why
    # the readers caught up (the credit topped up to 5): the finished dollar is not counted twice
    later = sources(
        a_key001={"left": 5.0, "left_at": "2026-11-17T11:00:00Z", "day_limit": 5.0, "spent_today": 1.0}
    )
    p = picker.pick(tmp_path, req(3, "reviews"), SHARE, later, TUE)
    assert p.source == "a_key001" and "$2.05 of $5 today" in p.why


def test_failed_and_finished_are_final(tmp_path):
    src = sources()
    picker.pick(tmp_path, req(1, "reviews"), SHARE, src, TUE)
    picker.failed(tmp_path, "s1")
    assert not picker.finished(tmp_path, "s1", 1.0)
    assert picker.spread(tmp_path, "2026-11-17") == {}
    picker.pick(tmp_path, req(2, "reviews"), SHARE, src, TUE)
    assert picker.finished(tmp_path, "s2", 0.3)
    assert not picker.finished(tmp_path, "s2") and not picker.failed(tmp_path, "s2")
    assert picker._load(tmp_path)["s2"]["spent"] == 0.3


def test_the_midnight_wake_is_utc(tmp_path):
    from datetime import timezone

    local = datetime(2026, 11, 18, 1, 0, tzinfo=timezone(timedelta(hours=2)))  # 17 Nov 23:00 UTC
    p = picker.pick(tmp_path, req(1), {}, [sources()[2] | {"day_limit": 1.0}], local)
    assert p.wait and p.until == "2026-11-18T00:00:00Z"
