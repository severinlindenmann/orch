"""A rule's end can be a day with a time (ORCH-599): typed or clicked, in the workspace's time zone, to the minute,
and the rule ends at that minute (fixed clock)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import jrun, switcher_data

from orch_usage import cli as usage_cli
from orch_usage import page, store, switching, when
from orch_usage.store import Refused

ZURICH = ZoneInfo("Europe/Zurich")
NOW = datetime(2026, 11, 18, 17, 30, tzinfo=UTC)  # 18:30 in Zurich


@pytest.mark.parametrize(
    ("text", "stored"),
    [
        ("tomorrow 08:00", "2026-11-19T07:00:00Z"),
        ("Tomorrow  8:00", "2026-11-19T07:00:00Z"),
        ("2026-11-19 07:59", "2026-11-19T06:59:00Z"),
        ("2026-11-19T07:59", "2026-11-19T06:59:00Z"),
        ("today 23:15", "2026-11-18T22:15:00Z"),
        ("tomorrow", "2026-11-19T23:00:00Z"),  # a day only: to the end of that day
        ("2026-11-19", "2026-11-19T23:00:00Z"),
        ("2026-11-19T07:59:00Z", "2026-11-19T07:59:00Z"),  # a full time keeps its own zone
        ("2027-07-01 08:00", "2027-07-01T06:00:00Z"),  # summer time
    ],
)
def test_end_words_in_the_workspace_zone_to_the_minute(text, stored):
    assert when.parse_end(text, NOW, ZURICH) == stored


@pytest.mark.parametrize(
    "text", ["today 18:00", "2026-11-17", "tomorrow 25:00", "tomorrow 08:61", "soon", "8:00"]
)
def test_bad_or_past_ends_are_refused(text):
    with pytest.raises(Refused):
        when.parse_end(text, NOW, ZURICH)


def test_reset_needs_a_known_reset():
    assert when.parse_end("reset", NOW, ZURICH, reset="2026-11-19T06:59:00Z") == "2026-11-19T06:59:00Z"
    with pytest.raises(Refused, match="does not know when altyca resets"):
        when.parse_end("at its next reset", NOW, ZURICH, label="altyca")


def test_next_reset_week_then_5h_then_the_first_of_the_month():
    row = {
        "use": {
            "5h": {"resets_at": "2026-11-18T19:29:59.99+00:00"},
            "week": {"resets_at": "2026-11-19T06:59:59.99+00:00"},
        }
    }
    assert when.next_reset(row, NOW, ZURICH) == "2026-11-19T06:59:00Z"  # the week's, to the minute
    row["use"]["week"]["resets_at"] = "2026-11-18T10:00:00Z"  # already passed: the 5 hours'
    assert when.next_reset(row, NOW, ZURICH) == "2026-11-18T19:29:00Z"
    credit = {"use": {}, "rule": {"limits": [{"period": "month", "value": 100, "unit": "$"}]}}
    assert when.next_reset(credit, NOW, ZURICH) == "2026-11-30T23:00:00Z"  # 1 Dec 00:00 in Zurich
    assert when.next_reset({"use": {}, "rule": {"limits": []}}, NOW, ZURICH) is None


def test_local_and_words():
    assert when.local("2026-11-19T07:00:00Z", ZURICH) == "2026-11-19T08:00"
    assert (
        when.local("2026-11-19T23:00:00Z", ZURICH) == "2026-11-19"
    )  # midnight after it: the end of that day
    assert when.words("2026-11-19T07:00:00Z", ZURICH) == "19 Nov 2026, 08:00 CET"
    assert when.words("2026-11-19T23:00:00Z", ZURICH) == "at the end of 19 Nov 2026"


# ---------------------------------------------------------------- command, page and the minute it acts


@pytest.fixture
def zurich(ws, monkeypatch):
    (ws / ".orch" / "config.toml").write_text('[workspace]\ntz = "Europe/Zurich"\n', encoding="utf-8")
    monkeypatch.setattr(usage_cli, "_now", lambda: NOW)
    return ws


def _with_resets(fake_switcher):
    data = switcher_data()
    for a in data["accounts"]:
        a["usage"]["fiveHour"]["resetsAt"] = "2026-11-18T19:29:59.99+00:00"
        a["usage"]["sevenDay"]["resetsAt"] = "2026-11-19T06:59:59.99+00:00"  # altyca-like: tomorrow 07:59
    fake_switcher.answer(data)


def _seed(cli):
    assert jrun(cli, "list")[0] == 0
    assert jrun(cli, "limit", "TEAMCO", "70", "--period", "week", "--by", "human:owner")[0] == 0
    assert jrun(cli, "limit", "TEAMCO", "90", "--period", "week", "--by", "human:owner")[0] == 0


def test_command_sets_an_end_with_a_time_and_the_history_names_it(cli, fake_switcher, zurich):
    _seed(cli)
    code, out, _ = cli("end", "TEAMCO", "tomorrow 08:00", "--by", "human:owner")
    assert code == 0 and "(ends 19 Nov 2026, 08:00 CET)" in out
    a = store.find(store.load(zurich)["accounts"], "TEAMCO")
    assert a["rule"]["ends"] == "2026-11-19T07:00:00Z"
    assert store.history(zurich)[0]["what"] == "rule ends 19 Nov 2026, 08:00 CET"


def test_command_end_at_its_next_reset(cli, fake_switcher, zurich):
    _with_resets(fake_switcher)
    _seed(cli)
    code, d = jrun(cli, "end", "TEAMCO", "reset", "--by", "human:owner")
    assert code == 0 and d["account"]["rule"]["ends"] == "2026-11-19T06:59:00Z"
    assert store.history(zurich)[0]["what"] == "rule ends 19 Nov 2026, 07:59 CET"


def test_a_click_with_a_time_and_at_reset(cli, fake_switcher, zurich):
    _with_resets(fake_switcher)
    _seed(cli)
    acc = store.find(store.load(zurich)["accounts"], "TEAMCO")["id"]
    code, d = jrun(cli, "act", "end", f"{acc}:2026-11-19T08:00", "--by", "human:Some Person")
    assert code == 0 and d["account"]["rule"]["ends"] == "2026-11-19T07:00:00Z"
    code, d = jrun(cli, "act", "end", f"{acc}:reset", "--by", "human:Some Person")
    assert code == 0 and d["account"]["rule"]["ends"] == "2026-11-19T06:59:00Z"
    for bad in (
        f"{acc}:2026-11-19T08:00:00",
        f"{acc}:2026-11-19 08:00",
        f"{acc}:tomorrow 08:00",
        f"{acc}:resets",
    ):
        assert jrun(cli, "act", "end", bad)[0] == 2


def test_the_card_shows_the_end_and_the_next_reset_in_the_workspace_zone(
    cli, fake_switcher, zurich, monkeypatch
):
    _with_resets(fake_switcher)
    _seed(cli)
    jrun(cli, "end", "TEAMCO", "tomorrow 08:00")
    monkeypatch.setattr(page, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    m = page.build(usage_cli.gather(zurich), zurich)
    teamco = next(a for a in m["accounts"] if a["label"] == "TEAMCO")
    assert teamco["ends_local"] == "2026-11-19T08:00"  # the page writes it 'Ends tomorrow 08:00' (UI.stamp)
    assert teamco["next_reset_local"] == "2026-11-19T07:59"
    jrun(cli, "end", "TEAMCO", "tomorrow")
    m = page.build(usage_cli.gather(zurich), zurich)
    assert (
        next(a for a in m["accounts"] if a["label"] == "TEAMCO")["ends_local"] == "2026-11-19"
    )  # 'Ends tomorrow'


def test_the_rule_ends_at_that_minute(cli, fake_switcher, zurich):
    """Fixed clock: at 07:58:59 the end of 07:59 has not acted; at 07:59:00 the rule falls back, and the history
    says so at that minute."""
    _seed(cli)
    jrun(cli, "end", "TEAMCO", "2026-11-19 07:59", "--by", "human:owner")
    switching.look(zurich, datetime(2026, 11, 19, 6, 58, 59, tzinfo=UTC))
    a = store.find(store.load(zurich)["accounts"], "TEAMCO")
    assert a["rule"]["limits"][0]["value"] == 90 and a["rule"]["ends"]
    switching.look(zurich, datetime(2026, 11, 19, 6, 59, 0, tzinfo=UTC))
    a = store.find(store.load(zurich)["accounts"], "TEAMCO")
    assert a["rule"]["limits"][0]["value"] == 70 and a["rule"]["ends"] is None
    line = store.history(zurich)[0]
    assert (line["who"], line["what"], line["at"]) == (
        "usage",
        "rule ended 19 Nov 2026, 07:59 CET",
        "2026-11-19T06:59:00Z",
    )
    assert page.history_rows(zurich, datetime(2026, 11, 19, 7, tzinfo=UTC))[0]["text"] == (
        "TEAMCO: rule ended 19 Nov 2026, 07:59 CET"
    )
