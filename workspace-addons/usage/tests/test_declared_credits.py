"""ORCH-630: a credit a skill declares (ORCH-600 format, read by orch.apicredits) is listed by Usage by itself, with no
code per provider; its full name <skill>/<name> works for ask and spent; never a key value in a file Usage writes."""

from datetime import UTC, datetime, timedelta

from conftest import jrun

from orch_usage import asking, page, routing, store
from orch_usage import cli as usage_cli

KEY = "wx-live-" + "Q7f3" * 10  # the made-up key value; it must never land in a Usage file


def _decl(name="forecast", label="Weatherly forecast credit", provider="Weatherly", unit="$", **extra):
    return {
        "credit": f"weather-api-credit/{name}",
        "owner": "weather-api-credit",
        "source": "skill:weather-api-credit",
        "file": "/skills/weather-api-credit/api-credits.toml",
        "name": name,
        "label": label,
        "provider": provider,
        "key": "orch:weatherly-key",
        "unit": unit,
        "spend": "report",
        "balance": "",
        **extra,
    }


def _declare(monkeypatch, *credits):
    monkeypatch.setattr(usage_cli, "declared", lambda root: list(credits))


def _usage_files(ws):
    d = store.usage_dir(ws)
    return "".join(p.read_text() for p in d.rglob("*") if p.is_file())


def test_a_made_up_skill_shows_in_the_list_and_on_the_page(cli, ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl())
    code, d = jrun(cli, "list")
    assert code == 0
    a = next(x for x in d["accounts"] if x["label"] == "Weatherly forecast credit")
    assert a["type"] == "api-key" and a["provider"] == "weatherly" and a["on"]
    assert a["skill"] == "weather-api-credit"
    m = page.build(usage_cli.gather(ws), ws)
    row = next(x for x in m["accounts"] if x["label"] == "Weatherly forecast credit")
    assert row["provider_label"] == "Weatherly" and row["credit"]["skill"] == "weather-api-credit"
    hist = [r for r in store.history(ws) if r["what"] == "credit declared"]
    assert len(hist) == 1  # listed once; the next list adds nothing
    jrun(cli, "list")
    assert len([r for r in store.history(ws) if r["what"] == "credit declared"]) == 1


def test_the_full_name_works_for_left_spent_and_ask(cli, ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl())
    jrun(cli, "list")
    assert jrun(cli, "left", "Weatherly forecast credit", "10", "--by", "human:owner")[0] == 0
    assert jrun(cli, "spent", "weather-api-credit/forecast", "4")[0] == 0
    ans = asking.ask(ws, "scripts", name="weather-api-credit/forecast")
    assert ans["go"] and ans["name"] == "weather-api-credit/forecast" and ans["left"] == 6
    assert jrun(cli, "spent", "weather-api-credit/forecast", "6")[0] == 0
    ans = asking.ask(ws, "scripts", name="weather-api-credit/forecast")
    assert not ans["go"] and "nothing left" in ans["why"]


def test_ask_lists_a_declared_credit_before_anyone_opened_the_list(ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl())
    assert jrun_free(ws) == []
    ans = asking.ask(ws, "scripts", name="weather-api-credit/forecast")
    assert ans["go"] and ans["account"] == "Weatherly forecast credit"


def jrun_free(ws):
    return [a for a in store.load(ws)["accounts"] if a["type"] == "api-key"]


def test_a_credit_added_by_hand_is_linked_not_listed_twice(cli, ws, no_switcher, monkeypatch):
    code, _ = jrun(
        cli, "add", "Weatherly forecast credit", "--provider", "weatherly", "--name", "forecast",
        "--by", "human:owner", "--left", "50",
    )  # fmt: skip
    assert code == 0
    _declare(monkeypatch, _decl())
    code, d = jrun(cli, "list")
    rows = [x for x in d["accounts"] if x["label"] == "Weatherly forecast credit"]
    assert len(rows) == 1 and rows[0]["skill"] == "weather-api-credit"
    a = store.find(store.load(ws)["accounts"], "Weatherly forecast credit")
    assert a["source"]["name"] == "weather-api-credit/forecast" and a["left"]["value"] == 50


def test_a_removed_credit_stays_removed(cli, ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl())
    jrun(cli, "list")
    assert jrun(cli, "remove", "Weatherly forecast credit", "--by", "human:owner")[0] == 0
    jrun(cli, "list")
    accounts = store.load(ws)["accounts"]
    assert [a["removed"] for a in accounts if a["label"] == "Weatherly forecast credit"] == [True]


def test_credits_not_in_dollars_and_key_shaped_ones_are_not_listed(cli, ws, no_switcher, monkeypatch):
    _declare(
        monkeypatch,
        _decl(name="calls", label="Weatherly calls", unit="calls"),
        _decl(name="bad", label=KEY),
    )
    code, d = jrun(cli, "list")
    assert code == 0 and not [x for x in d["accounts"] if x["type"] == "api-key"]


def test_no_key_value_in_accounts_history_or_spend_log(cli, ws, no_switcher, monkeypatch, capsys):
    _declare(monkeypatch, _decl(key=KEY, balance=f"curl -H 'X-Key: {KEY}' https://example.invalid"))
    out = cli("list")[1]
    jrun(cli, "left", "Weatherly forecast credit", "10", "--by", "human:owner")
    jrun(cli, "spent", "weather-api-credit/forecast", "1")
    asking.ask(ws, "scripts", name="weather-api-credit/forecast")
    m = page.build(usage_cli.gather(ws), ws)
    blob = _usage_files(ws) + out + str(m)
    assert KEY not in blob and "orch:weatherly-key" not in blob and "example.invalid" not in blob


def test_a_spend_log_declaration_points_at_the_file_next_to_it(ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl(spend="log:spend.jsonl"))
    usage_cli.gather(ws)
    a = store.find(store.load(ws)["accounts"], "Weatherly forecast credit")
    assert a["source"]["reader"] == "spend-log"
    assert a["source"]["path"] == "/skills/weather-api-credit/spend.jsonl"


def test_closed_is_one_check_for_ask_and_helper_starts():
    at = datetime(2026, 11, 19, 12, tzinfo=UTC)
    a = {"label": "W", "on": True}
    assert store.closed(a, at) is None
    assert "switched off" in store.closed({**a, "on": False}, at)
    assert "removed" in store.closed({**a, "removed": True}, at)
    ended = store.utc_text(at - timedelta(minutes=1))
    assert "ended on" in store.closed({**a, "credit_ends": ended}, at)
    assert store.closed({**a, "credit_ends": store.utc_text(at + timedelta(hours=1))}, at) is None
    assert store.closed({**a, "credit_ends": "not a time"}, at) is None  # unreadable never blocks
    assert routing.store is store  # routing.decide filters with store.closed (no copy of the rule there)


def test_a_skill_asking_by_name_never_holds_the_whole_kind_of_work(cli, ws, no_switcher, monkeypatch):
    _declare(monkeypatch, _decl())
    jrun(cli, "list")
    assert jrun(cli, "off", "Weatherly forecast credit", "--by", "human:owner")[0] == 0
    ans = asking.ask(ws, "scripts", name="weather-api-credit/forecast")
    assert not ans["go"] and "switched off" in ans["why"]
    assert not routing.held(ws)  # only this credit is refused; helpers doing Scripts go on
    whats = [r["what"] for r in store.history(ws)]
    assert not [w for w in whats if "waits" in w or "room again" in w.lower()]
