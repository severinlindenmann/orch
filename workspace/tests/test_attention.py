"""Attention groups on Review (ORCH-2184, Focused review C): Quick look / Short decision / Take your time.
Plain rules on what orch knows; unknown risk is never a Quick look; groups never change what passes by
itself (the Reviewer and Away mode do not read them). Plus `orch ask --due` and the weekly measure."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import attention, autoreview, review, reviewer, tickets


def _item(kind, text="Move the old files to the archive folder?", **kw):
    return {"text": text, "card": kw.pop("card", {}), "card_kind": {"kind": kind}, **kw}


def test_rules_quick_only_with_a_clear_hint():
    g = attention.group_of
    assert g(_item("question", one_tap=True))["group"] == "quick"
    assert g(_item("document", proposal={"verdict": "accept", "why": "small"}))["group"] == "quick"
    passed = {"preview": {"type": "doc", "status": {"text": "All 12 tests passed", "tone": "done"}}}
    assert g(_item("check_result", text="", card=passed)) == {
        "group": "quick",
        "name": "Quick look",
        "why": "small and tested",
    }
    # no hint that it is small: a Short decision, never a guess
    assert g(_item("question"))["group"] == "short"
    assert g(_item("pictures", text=""))["group"] == "short"
    failed = {"preview": {"type": "doc", "status": {"text": "2 failed", "tone": "failed"}}}
    assert g(_item("check_result", text="", card=failed))["group"] == "short"
    assert g(_item("stuck", one_tap=True))["group"] == "short"


def test_unknown_risk_is_never_a_quick_look():
    g = attention.group_of
    # words orch cannot read plainly, a vague go-ahead, or a card too deep to read: not quick
    assert (
        g(_item("question", text="Alte Dateien ins Archiv verschieben, später?", one_tap=True))["group"]
        == "short"
    )
    assert g(_item("question", text="Ready to go ahead as planned?", one_tap=True))["group"] == "short"
    deep: dict = {"a": "x"}
    for _ in range(8):
        deep = {"a": deep}
    assert g(_item("question", card={"preview": deep}, one_tap=True))["group"] == "short"
    assert g({})["group"] == "short"
    assert g(None)["group"] == "short"


def test_take_your_time_for_live_risky_or_long():
    g = attention.group_of
    assert g(_item("put_live", text="Merge it"))["why"] == "it puts something live"
    assert g(_item("try_yourself"))["group"] == "time"
    risky = g(_item("question", text="Buy the 50 seat plan for 400 EUR?", one_tap=True))
    assert risky["group"] == "time" and risky["why"] == "costs money"
    # the Reviewer's accept does not make a risky card quick
    assert (
        g(_item("document", text="Delete the old table", proposal={"verdict": "accept"}))["group"] == "time"
    )
    long_doc = {"preview": {"type": "doc", "paras": ["line " * 301]}}
    assert g(_item("document", text="", card=long_doc))["why"] == "long to read"
    short_doc = {"preview": {"type": "doc", "paras": ["line " * 40]}}
    assert g(_item("document", text="", card=short_doc))["group"] == "short"


def test_review_list_carries_the_group_and_filters_by_it(proj, run, new_ticket):
    quick = new_ticket("Files")
    risky = new_ticket("Plan")
    assert (
        run(
            "ask",
            quick,
            "Move the old files to the archive folder?",
            "--option",
            "Move",
            "--option",
            "Leave",
            "--by",
            "agent:helper",
        )[0]
        == 0
    )
    assert (
        run(
            "ask",
            risky,
            "Buy the bigger plan for the team?",
            "--option",
            "Buy",
            "--option",
            "Wait",
            "--by",
            "agent:helper",
        )[0]
        == 0
    )
    groups = {c["ticket"]: c["attention"] for c in review.stack(proj)}
    assert groups[risky]["group"] == "time"
    assert groups[quick]["group"] in ("quick", "short")
    code, out, err = run("review", "list", "--group", "time", "--json")
    assert code == 0, out + err
    cards = json.loads(out)["cards"]
    assert [c["ticket"] for c in cards] == [risky]
    code, out, _ = run("review", "list", "--group", "time")
    assert "1 thing waits on you in Take your time." in out


def test_groups_never_change_what_passes_by_itself():
    # neither the Reviewer nor Away mode reads the groups: what passes by itself stays their own setting
    src = Path(attention.__file__).parent
    for mod in (reviewer, autoreview):
        assert "attention" not in Path(mod.__file__).read_text(encoding="utf-8")
    assert "tickets.apply_op" not in (src / "attention.py").read_text(encoding="utf-8")


def test_due_is_kept_in_utc_shown_and_in_the_digest(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = run(
        "ask",
        tid,
        "Keep the old file name?",
        "--option",
        "Keep",
        "--option",
        "Rename",
        "--due",
        "2026-12-01T09:00:00+01:00",
        "--by",
        "agent:helper",
    )
    assert code == 0, out + err
    q = tickets.load(proj, tid)["questions"][0]
    assert q["due"] == "2026-12-01T08:00:00Z"
    assert tickets.question_digest(q) != tickets.question_digest({k: v for k, v in q.items() if k != "due"})
    assert review.stack(proj)[0]["due"] == "2026-12-01T08:00:00Z"
    code, out, err = run(
        "ask",
        tid,
        "Another one?",
        "--option",
        "A",
        "--option",
        "B",
        "--due",
        "Friday",
        "--by",
        "agent:helper",
    )
    assert code == 2 and "is not a time" in out + err


def _put(proj, tid, fn):
    tickets.apply_op(proj, tid, fn, by="human:owner")


def test_week_counts_undos_send_backs_and_missed_deadlines(proj, run, new_ticket):
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    tid = new_ticket("Files")

    def op(t):
        t["history"] += [
            {"at": iso(now - timedelta(days=1)), "by": "human:owner", "text": autoreview.UNDONE_LINE + "x"},
            {"at": iso(now - timedelta(days=9)), "by": "human:owner", "text": autoreview.UNDONE_LINE + "old"},
            {"at": iso(now - timedelta(days=2)), "by": "human:owner", "text": "Status done -> open"},
            {"at": iso(now - timedelta(days=2)), "by": "human:owner", "text": "Status review -> done"},
        ]
        base = {"options": ["A", "B"], "recommended": None, "answered_by": None, "via": None}
        t["questions"] += [
            {**base, "id": "q1", "text": "a", "answer": None, "due": iso(now - timedelta(days=1))},
            {
                **base,
                "id": "q2",
                "text": "b",
                "answer": "A",
                "at": iso(now - timedelta(days=3)),
                "due": iso(now - timedelta(days=2)),
            },
            {
                **base,
                "id": "q3",
                "text": "c",
                "answer": "A",
                "at": iso(now - timedelta(days=1)),
                "due": iso(now - timedelta(days=2)),
            },
            {**base, "id": "q4", "text": "d", "answer": None, "due": iso(now + timedelta(days=1))},
        ]

    _put(proj, tid, op)
    w = attention.week(proj, now=now)
    assert (w["undos"], w["sent_back_later"], w["missed_deadlines"]) == (1, 1, 2)
    code, out, err = run("review", "list", "--week")
    assert code == 0, out + err
    assert "Last 7 days:" in out and "Next:" in out
