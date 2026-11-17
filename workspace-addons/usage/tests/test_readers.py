import json

import pytest
from conftest import switcher_data

from orch_usage.readers import credit, cswap, spend_log


def test_switcher_answer_becomes_labels_numbers_and_keys_without_addresses(fake_switcher):
    rows = cswap.read()
    assert [r.label for r in rows] == ["first", "second", "TEAMCO"]
    assert [r.active for r in rows] == [True, False, False]
    assert rows[0].windows["5h"].pct == 97.0 and rows[0].windows["week"].pct == 80.0
    assert rows[0].windows["week"].lasts_to_reset is False
    text = json.dumps([r.__dict__ for r in rows], default=lambda o: o.__dict__)
    assert "@" not in text and "example.test" not in text  # the address is never kept
    assert rows[0].key == cswap.key_of("FIRST@example.test")  # stable, case does not matter
    assert fake_switcher.calls() == ["list --json"]


def test_missing_switcher_reads_none(no_switcher):
    assert cswap.read() is None


@pytest.mark.parametrize(
    "answer", ["not json", json.dumps({"schemaVersion": 2, "accounts": []}), json.dumps([1, 2])]
)
def test_unknown_switcher_answer_is_refused_in_plain_words(fake_switcher, answer):
    fake_switcher.answer(answer)
    with pytest.raises(cswap.ReaderError, match="account switcher"):
        cswap.read()


def test_rows_without_an_address_or_number_are_skipped():
    data = switcher_data()
    data["accounts"][1].pop("email")
    data["accounts"][2]["number"] = "3"
    assert [r.label for r in cswap.parse(data)] == ["first"]


def test_spend_log_sums_one_account_since_a_time(tmp_path):
    log = tmp_path / "spend.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"t": "2026-11-01T10:00:00Z", "account": "main", "usd": 1.5}),
                json.dumps({"t": "2026-11-05T10:00:00Z", "account": "main", "usd": 0.25}),
                json.dumps({"t": "2026-11-06T10:00:00Z", "account": "second", "usd": 9}),
                "broken line",
                json.dumps({"t": "2026-11-07T10:00:00+01:00", "account": "main", "usd": 2}),
            ]
        ),
        encoding="utf-8",
    )
    use = spend_log.read({"reader": "spend-log", "path": str(log), "name": "main"}, "2026-11-03T00:00:00Z")
    assert use.spent == 2.25 and use.estimated and use.as_of == "2026-11-07T09:00:00Z"
    assert spend_log.read({"path": str(log), "name": "main"}, None).spent == 3.75


def test_credit_readers_never_raise_for_a_missing_source(tmp_path):
    assert spend_log.read({"path": str(tmp_path / "nope.jsonl")}, None).spent is None
    assert credit.READERS["none"]({}, None).note
