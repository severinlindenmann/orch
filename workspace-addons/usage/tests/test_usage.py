import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import jrun, switcher_data

from orch_usage import store


def _seed(cli):
    """The owner's rules (16 Nov evening), by account label: first up to 100 % weekly and 95 % per 5 hours, then
    TEAMCO up to 70 %, then second up to 100 %; 5-hour limit 92 % on the others."""
    assert jrun(cli, "list")[0] == 0
    for args in (
        ("limit", "first", "95%", "--period", "5h"),
        ("limit", "first", "100%", "--period", "week"),
        ("limit", "TEAMCO", "92", "--period", "5h"),
        ("limit", "TEAMCO", "70", "--period", "week"),
        ("limit", "second", "92%", "--period", "5h"),
        ("limit", "second", "100%", "--period", "week"),
        ("order", "TEAMCO", "2"),
    ):
        code, out = jrun(cli, *args, "--by", "human:owner")
        assert code == 0, out


def test_list_finds_the_switcher_accounts_once_with_use(cli, fake_switcher, ws):
    code, d = jrun(cli, "list")
    assert code == 0 and d["switcher"] is True and d["warnings"] == []
    assert [(a["label"], a["order"], a["on"], a["active"]) for a in d["accounts"]] == [
        ("first", 1, True, True),
        ("second", 2, True, False),
        ("TEAMCO", 3, True, False),
    ]
    assert d["accounts"][0]["use"]["5h"]["pct"] == 97.0
    jrun(cli, "list")  # a second look adds nothing
    assert len(store.load(ws)["accounts"]) == 3
    hist = store.history(ws)
    assert [h["what"] for h in hist] == ["account found"] * 3 and {h["who"] for h in hist} == {"usage"}
    files = (ws / ".orch/addons/usage/accounts.json").read_text() + (
        ws / ".orch/addons/usage/history.jsonl"
    ).read_text()
    assert "@" not in files and "example.test" not in files
    assert fake_switcher.calls() == ["list --json", "list --json"]  # read only: never a switch or enable


def test_owner_rules_and_order_with_history(cli, fake_switcher, ws):
    _seed(cli)
    accts = store.load(ws)["accounts"]
    assert [a["label"] for a in accts] == ["first", "TEAMCO", "second"]
    assert accts[1]["rule"]["limits"] == [
        {"value": 92, "unit": "%", "period": "5h"},
        {"value": 70, "unit": "%", "period": "week"},
    ]
    _code, out, _ = cli("list")
    assert "2. TEAMCO (on): 92% per 5 hours, 70% per week" in out
    assert "1. first (on, in use)" in out and "5 hours 97% used" in out
    h = store.history(ws)[0]
    assert h["who"] == "human:owner" and h["what"] == "order 3 to 2" and (h["before"], h["after"]) == (3, 2)
    h = next(x for x in store.history(ws) if x["what"] == "limit 70% (week)")
    assert h["before"]["limits"] == [{"value": 92, "unit": "%", "period": "5h"}]
    assert h["after"]["limits"][1]["value"] == 70


@pytest.mark.parametrize("value", ["37.5%", "1", "99.9", "100%"])
def test_any_number_is_a_limit(cli, fake_switcher, ws, value):
    jrun(cli, "list")
    code, d = jrun(cli, "limit", "second", value)
    assert code == 0 and d["account"]["rule"]["limits"][0]["value"] == float(value.rstrip("%"))


@pytest.mark.parametrize(
    "args, words",
    [
        (("limit", "second", "0"), "above 0"),
        (("limit", "second", "abc"), "not a number"),
        (("limit", "second", "101%"), "at most 100%"),
        (("limit", "second", "$100"), "percent"),
        (("limit", "second", "50", "--period", "month"), "5 hours or week"),
        (("limit", "nobody", "50"), "No account called 'nobody'"),
        (("limit", "second", "50", "--period", "fortnight"), "not a period"),
        (("limit", "second", "50", "--end", "2020-01-01"), "already passed"),
        (("limit", "second", "none"), "no week limit"),
        (("period", "second", "week"), "no limit yet"),
        (("order", "second", "x"), None),
    ],
)
def test_bad_input_is_refused_and_changes_nothing(cli, fake_switcher, ws, args, words):
    jrun(cli, "list")
    before = (ws / ".orch/addons/usage/accounts.json").read_text()
    if words is None:
        with pytest.raises(SystemExit):
            cli(*args)
        return
    code, d = jrun(cli, *args)
    assert code == 2 and words in d["error"], d
    assert (ws / ".orch/addons/usage/accounts.json").read_text() == before


def test_two_limits_need_a_period_and_a_third_is_refused(cli, fake_switcher, ws):
    _seed(cli)
    code, d = jrun(cli, "limit", "first", "90")
    assert code == 2 and "--period 5h or --period week" in d["error"]
    code, d = jrun(cli, "limit", "first", "none", "--period", "5h")
    assert code == 0 and [x["period"] for x in d["account"]["rule"]["limits"]] == ["week"]
    code, d = jrun(cli, "limit", "first", "90")  # one limit left: that one
    assert code == 0 and d["account"]["rule"]["limits"] == [{"value": 90, "unit": "%", "period": "week"}]


def test_period_on_and_off_and_nothing_changed(cli, fake_switcher, ws):
    _seed(cli)
    code, d = jrun(cli, "period", "first", "5h")
    assert code == 2 and "--of" in d["error"]
    code, d = jrun(cli, "period", "first", "5h", "--of", "week")
    assert code == 2 and "already has a 5 hours limit" in d["error"]
    code, d = jrun(cli, "off", "second")
    assert code == 0 and d["changed"] and d["account"]["on"] is False
    code, d = jrun(cli, "off", "second")
    assert code == 0 and not d["changed"] and "Nothing changed" in d["next"]
    assert [h["what"] for h in store.history(ws)][:1] == ["turned off"]
    jrun(cli, "on", "second")
    assert store.load(ws)["accounts"][2]["on"] is True


def test_temporary_rule_falls_back_to_the_rule_before(cli, fake_switcher, ws):
    _seed(cli)
    code, d = jrun(cli, "limit", "second", "20%", "--period", "week", "--end", "2099-01-01")
    assert code == 0 and d["account"]["rule"]["ends"] and "falls back" in d["next"]
    jrun(cli, "limit", "second", "15%", "--period", "week")  # still temporary, same fallback
    a = store.find(store.load(ws)["accounts"], "second")
    assert a["rule"]["ends"] and a["prev"]["limits"][1]["value"] == 100
    # time passes: the end is reached
    accts, rows = store.load(ws)["accounts"], []
    store.expire(accts, rows, at=datetime(2099, 1, 2, tzinfo=UTC))
    a = store.find(accts, "second")
    assert a["rule"]["limits"][1]["value"] == 100 and a["rule"]["ends"] is None and a["prev"] is None
    assert rows[0]["who"] == "usage" and rows[0]["what"] == "rule ended"


def test_end_on_the_current_rule_and_no_end(cli, fake_switcher, ws):
    _seed(cli)
    jrun(cli, "limit", "TEAMCO", "50", "--period", "week")
    code, d = jrun(cli, "end", "TEAMCO", "2099-01-01T10:00")
    assert code == 0 and d["account"]["rule"]["ends"]
    a = store.find(store.load(ws)["accounts"], "TEAMCO")
    assert a["prev"]["limits"][1]["value"] == 70  # falls back to the rule before the 50 % change
    code, d = jrun(cli, "end", "TEAMCO", "none")
    assert code == 0 and d["account"]["rule"]["ends"] is None
    assert store.history(ws)[0]["what"] == "rule kept, no end"


def test_an_ended_rule_falls_back_on_the_next_command(cli, fake_switcher, ws):
    _seed(cli)
    p = ws / ".orch/addons/usage/accounts.json"
    data = json.loads(p.read_text())
    a = next(x for x in data["accounts"] if x["label"] == "second")
    a["prev"] = a["rule"]
    a["rule"] = {
        "limits": [{"value": 10, "unit": "%", "period": "week"}],
        "for": [],
        "ends": (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    p.write_text(json.dumps(data))
    _code, d = jrun(cli, "list")
    second = next(x for x in d["accounts"] if x["label"] == "second")
    assert second["rule"]["limits"][1]["value"] == 100 and second["rule"]["ends"] is None


def test_credit_account_by_hand_reads_its_spend(cli, fake_switcher, ws, tmp_path):
    jrun(cli, "list")
    log = tmp_path / "spend.jsonl"
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.write_text(json.dumps({"t": now, "account": "main", "usd": 3.5}) + "\n")
    p = ws / ".orch/addons/usage/accounts.json"
    data = json.loads(p.read_text())
    data["accounts"].append(
        {
            "id": "a_api001",
            "label": "API key 1",
            "type": "api-key",
            "provider": "anthropic-api",
            "source": {"reader": "spend-log", "path": str(log), "name": "main"},
            "on": True,
            "order": 4,
            "rule": {"limits": [], "for": [], "ends": None},
            "prev": None,
        }
    )
    p.write_text(json.dumps(data))
    code, d = jrun(cli, "limit", "API key 1", "$200")
    assert code == 0 and d["account"]["rule"]["limits"] == [{"value": 200, "unit": "$", "period": "month"}]
    code, d = jrun(cli, "list")
    api = next(x for x in d["accounts"] if x["label"] == "API key 1")
    assert api["use"]["month"]["spent"] == 3.5 and api["use"]["month"]["estimated"] is True
    assert "path" not in json.dumps(api)  # the source stays in the file, not in the answer
    code, out, _ = cli("list")
    assert "month $3.5 spent (estimated)" in out


def test_without_the_switcher_show_and_warn_only(cli, no_switcher, ws):
    code, d = jrun(cli, "list")
    assert code == 0 and d["switcher"] is False and d["accounts"] == []
    assert "does not switch" in d["warnings"][0]
    code, out, _ = cli("list")
    assert "No accounts yet." in out and "Warning:" in out


def test_history_command_and_unreadable_file(cli, fake_switcher, ws):
    _seed(cli)
    code, d = jrun(cli, "history", "--account", "TEAMCO")
    assert code == 0 and d["history"][0]["what"] == "order 3 to 2" and len(d["history"]) == 4
    code, out, _ = cli("history")
    assert "TEAMCO: order 3 to 2  (by owner)" in out
    (ws / ".orch/addons/usage/accounts.json").write_text("{broken")
    code, d = jrun(cli, "limit", "first", "50", "--period", "week")
    assert code == 2 and "could not be read" in d["error"]
    assert (ws / ".orch/addons/usage/accounts.json").read_text() == "{broken"  # never rewritten


def test_actor_comes_from_the_run(cli, fake_switcher, ws, monkeypatch):
    jrun(cli, "list")
    monkeypatch.setenv("ORCH_AGENT", "helper1")
    jrun(cli, "limit", "first", "90")
    assert store.history(ws)[0]["who"] == "agent:helper1"
    code, d = jrun(cli, "limit", "first", "80", "--by", "usage")
    assert code == 2 and "not a valid name" in d["error"]


def test_no_workspace_is_refused(tmp_path, monkeypatch, capsys):
    from orch_usage.cli import main

    monkeypatch.setenv("ORCH_ROOT", str(tmp_path))
    assert main(["list", "--json"]) == 2
    assert "No orch workspace" in json.loads(capsys.readouterr().out)["error"]


def test_order_moves_and_keeps_places_whole(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "order", "TEAMCO", "1")
    jrun(cli, "order", "first", "99")  # past the end: last
    assert [(a["label"], a["order"]) for a in store.load(ws)["accounts"]] == [
        ("TEAMCO", 1),
        ("second", 2),
        ("first", 3),
    ]


def test_switcher_numbers_may_change_the_accounts_stay(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "limit", "TEAMCO", "70")
    data = switcher_data(active=3)
    for row, n in zip(data["accounts"], (3, 1, 2), strict=True):
        row["number"] = n
    fake_switcher.answer(data)
    _code, d = jrun(cli, "list")
    assert len(d["accounts"]) == 3
    assert next(x for x in d["accounts"] if x["label"] == "TEAMCO")["rule"]["limits"][0]["value"] == 70


def test_a_limit_works_before_the_accounts_were_listed(cli, fake_switcher, ws):
    """A fresh workspace: the limit command finds the accounts itself (ORCH-93 finding 2)."""
    code, out = jrun(cli, "limit", "first", "95%", "--period", "5h", "--by", "human:owner")
    assert code == 0, out
    assert out["account"]["label"] == "first"


def test_plain_history_shows_local_time(cli, fake_switcher, ws):
    """ORCH-93 finding 3: plain history times are this computer's local time (the reason shows when there is one)."""
    _seed(cli)
    code, text, _ = cli("history")
    assert code == 0
    row = store.history(ws)[-1]
    local = store.to_time(row["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
    assert local in text
