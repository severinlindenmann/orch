"""The day's spread on the Usage page (ORCH-660): starts, percent, money, 7 days and skipped sources."""

import json
from datetime import UTC, datetime

from orch_usage import spread, store

AT = datetime(2026, 11, 18, 17, 0, tzinfo=UTC)


def _acc(id_, label, type_="subscription", on=True, bars=(), state="ready"):
    return {"id": id_, "label": label, "type": type_, "on": on, "state": state, "bars": list(bars)}


def _write(root, entries, schema=spread.SCHEMA):
    d = store.usage_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    starts = {f"s{i}": e for i, e in enumerate(entries)}
    (d / spread.STARTS).write_text(json.dumps({"schema": schema, "starts": starts}), encoding="utf-8")


def _e(source, day="2026-11-18", state="done", dollars=0.0, spent=None, kind="code", label=None):
    return {
        "source": source,
        "day": day,
        "state": state,
        "dollars": dollars,
        "spent": spent,
        "kind": kind,
        "label": label,
    }


ACCS = [
    _acc("a_sub1", "Personal 1"),
    _acc(
        "a_sub2",
        "Company",
        bars=[{"period": "week", "unit": "%", "used": 52.0, "limit": 50, "limit_unit": "%"}],
    ),
    _acc("a_cdx", "Codex"),
    _acc("a_key1", "Claude API key 1", "api-key"),
    _acc("a_oai", "OpenAI API", "api-key"),
    _acc(
        "a_key3",
        "Claude API key 3",
        "api-key",
        bars=[{"period": "until", "unit": "$", "used": 50.0, "limit": 50, "limit_unit": "$"}],
    ),
]


def test_today_counts_percent_and_money_per_source(tmp_path):
    entries = [_e("a_sub1") for _ in range(12)] + [_e("a_cdx") for _ in range(3)]
    entries += [
        _e("a_key1", dollars=3.70, spent=2.40),
        _e("a_oai", dollars=0.13, kind="reviews"),
        _e("a_oai", state="started", dollars=0.13, kind="reviews"),
    ]
    entries += [
        _e("a_sub2", day="2026-11-17"),
        _e("a_sub1", state="failed"),
        _e("a_oai", day="2026-11-10", dollars=9),
    ]
    _write(tmp_path, entries)
    m = spread.build(tmp_path, ACCS, AT)
    rows = {r["label"]: r for r in m["sources"]}
    assert (m["day"], m["starts"], m["dollars"]) == ("2026-11-18", 18, 2.66)
    assert [r["label"] for r in m["sources"]] == [a["label"] for a in ACCS]  # the page's order
    assert (rows["Personal 1"]["starts"], rows["Personal 1"]["pct"], rows["Personal 1"]["dollars"]) == (
        12,
        67,
        None,
    )
    assert (rows["Claude API key 1"]["dollars"], rows["OpenAI API"]["dollars"]) == (
        2.4,
        0.26,
    )  # real spend wins
    assert rows["OpenAI API"]["kinds"] == ["Reviews"]
    # a failed start does not count; a start older than 7 days is gone
    assert rows["Personal 1"]["week"] == [0, 0, 0, 0, 0, 0, 12]
    assert rows["Company"]["week"][-2:] == [1, 0] and rows["Company"]["week_starts"] == 1
    assert rows["OpenAI API"]["week_dollars"] == 0.26
    assert len(m["days"]) == 7 and m["days"][-1] == "2026-11-18" and m["days"][0] == "2026-11-12"


def test_skipped_sources_say_why_in_plain_words(tmp_path):
    accs = ACCS + [_acc("a_off", "Copilot", "helper-tool", on=False), _acc("a_gone", "Old", state="missing")]
    rows = {r["label"]: r for r in spread.build(tmp_path, accs, AT)["sources"]}
    assert rows["Company"]["skipped"] == "Its own limit is 50 % a week, so the next account takes its work"
    assert rows["Claude API key 3"]["skipped"] == "$0 left, so the next account takes its work"
    assert rows["Copilot"]["skipped"].startswith("It is turned off")
    assert rows["Old"]["skipped"].startswith("It is not found")
    assert rows["Personal 1"]["skipped"] is None
    full = _acc("a_full", "Full", bars=[{"period": "week", "unit": "%", "used": 100.0}])
    assert spread.skipped(full) == "It used all of its week, so the next account takes its work"


def test_no_starts_file_shows_zero_and_a_broken_one_is_ignored(tmp_path):
    m = spread.build(tmp_path, ACCS, AT)
    assert m["starts"] == 0 and all(r["starts"] == 0 and r["pct"] == 0 for r in m["sources"])
    _write(tmp_path, [_e("a_sub1")], schema="something-else/9")
    assert spread.build(tmp_path, ACCS, AT)["starts"] == 0
    (store.usage_dir(tmp_path) / spread.STARTS).write_text("{not json", encoding="utf-8")
    assert spread.build(tmp_path, ACCS, AT)["starts"] == 0


def test_money_only_for_api_keys_and_tools_with_a_dollar_limit(tmp_path):
    tool = _acc("a_cdx", "Codex", "helper-tool")
    capped = dict(
        _acc("a_cop", "Copilot", "helper-tool"), limits=[{"period": "month", "value": 20, "unit": "$"}]
    )
    _write(tmp_path, [_e("a_cdx", dollars=2.4), _e("a_cop", dollars=1.0)])
    rows = {r["label"]: r for r in spread.build(tmp_path, [tool, capped], AT)["sources"]}
    assert (rows["Codex"]["dollars"], rows["Codex"]["week_dollars"]) == (None, None)  # in the subscription
    assert rows["Copilot"]["dollars"] == 1.0


def test_starts_on_a_removed_account_still_count_today(tmp_path):
    _write(tmp_path, [_e("a_sub1"), _e("a_old", dollars=1.5, label="Old key")])
    m = spread.build(tmp_path, ACCS, AT)
    old = m["sources"][-1]
    assert (old["label"], old["starts"], old["pct"], old["dollars"]) == ("Old key", 1, 50, 1.5)
    assert m["dollars"] == 1.5
