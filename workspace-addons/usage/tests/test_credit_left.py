"""ORCH-626: what is left on an API credit. The person types the amount left now (orch keeps the time), a credit skill
reports each spend with `orch usage spent`, orch counts down; off, end, order and remove land in the history."""

import json
from datetime import datetime, timedelta

from conftest import jrun

from orch_usage import asking, left, store


def _local(y, mo, d, h=12, mi=0):
    return datetime(y, mo, d, h, mi).astimezone()  # this computer's time, like the person's day


def _add(cli, label="Claude API key 1", name="key-1", provider="anthropic", *extra):
    code, d = jrun(cli, "add", label, "--provider", provider, "--name", name, "--by", "human:owner", *extra)
    assert code == 0, d
    return d["account"]


def _acct(ws, label):
    return store.find(store.load(ws)["accounts"], label)


def test_set_left_then_count_down_by_reported_spend(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1", "anthropic", "--left", "$100")
    assert jrun(cli, "spent", "key-1", "3.50")[0] == 0  # by the name the skill uses
    code, d = jrun(cli, "spent", "Claude API key 1", "$1.25")  # or by its label
    assert code == 0 and d["credit"]["left"] == 95.25
    code, d = jrun(cli, "list")
    row = next(r for r in d["accounts"] if r["label"] == "Claude API key 1")
    c = row["credit"]
    assert (c["set"], c["spent_since"], c["left"]) == (100, 4.75, 95.25)
    assert c["spent_today"] == 4.75 and c["spent_month"] == 4.75
    code, out, _ = cli("list")
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert f"left: $95.25 (set on {day}, minus $4.75 spent since); spent today $4.75, this month $4.75" in out


def test_setting_again_starts_the_count_from_the_new_figure(cli, ws, no_switcher):
    _add(cli)
    a = _acct(ws, "Claude API key 1")
    left.record(
        ws, a, 10, "agent:claude", at="2026-11-01T10:00:00Z"
    )  # before the amount was set: not counted
    code, d = jrun(cli, "left", "Claude API key 1", "$74")
    assert code == 0 and d["credit"]["left"] == 74 and d["credit"]["spent_since"] == 0
    jrun(cli, "spent", "key-1", "4")
    assert left.view(ws, _acct(ws, "Claude API key 1"))["left"] == 70
    with store.change(ws) as (accounts, rows):  # the person reads the provider again, a minute later
        a = store.find(accounts, "Claude API key 1")
        later = store.utc_text(store.to_time(a["left"]["at"]) + timedelta(minutes=1))
        store.set_left(a, rows, "human:owner", 72, at=later)
    assert left.view(ws, _acct(ws, "Claude API key 1"))["left"] == 72


def test_today_this_month_and_since_with_a_fixed_clock(ws, cli, no_switcher):
    _add(cli)
    a = _acct(ws, "Claude API key 1")
    with store.change(ws) as (accounts, rows):
        store.set_left(
            store.find(accounts, a["id"]), rows, "human:owner", 50, at=store.utc_text(_local(2026, 11, 2))
        )
    for when, usd in ((_local(2026, 10, 30), 4), (_local(2026, 11, 3), 2), (_local(2026, 11, 18, 9), 1)):
        left.record(ws, a, usd, "agent:claude", at=store.utc_text(when))
    v = left.view(ws, _acct(ws, "Claude API key 1"), at=_local(2026, 11, 18, 12))
    assert v["spent_today"] == 1 and v["spent_month"] == 3
    assert v["set"] == 50 and v["spent_since"] == 3 and v["left"] == 47
    assert (
        left.text(v) == "left: $47 (set on 2026-11-02, minus $3 spent since); spent today $1, this month $3"
    )


def test_spent_past_what_was_left_shows_zero_and_over(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1", "anthropic", "--left", "1")
    _, d = jrun(cli, "spent", "key-1", "1.5")
    assert d["credit"]["left"] == 0 and d["credit"]["over"] == 0.5
    assert "left: $0 (set on" in left.text(d["credit"]) and "$0.50 over" in left.text(d["credit"])


def test_zero_and_none_and_the_history(cli, ws, no_switcher):
    _add(cli)
    assert jrun(cli, "left", "Claude API key 1", "0")[1]["credit"]["left"] == 0  # blocked: nothing left
    assert jrun(cli, "left", "Claude API key 1", "none")[1]["credit"]["left"] is None
    jrun(cli, "spent", "key-1", "0.42")
    whats = [r["what"] for r in store.history(ws)]
    assert "left set to $0" in whats and "amount left taken away" in whats
    assert not any("spent" in w for w in whats)  # spend goes to the spend log, not the history of changes
    row = json.loads((ws / ".orch/addons/usage/spent.jsonl").read_text().splitlines()[0])
    assert set(row) == {"t", "account", "usd", "who"} and row["usd"] == 0.42


def test_refusals(cli, ws, no_switcher):
    _add(cli)
    for bad in ("-1", "abc", "5%"):
        code, d = jrun(cli, "left", "Claude API key 1", bad)
        assert code == 2, bad
    for bad in ("0", "-2", "x", "none", "200000"):
        code, d = jrun(cli, "spent", "key-1", bad)
        assert code == 2, bad
    code, d = jrun(cli, "spent", "no-such-credit", "1")
    assert code == 2 and "No account called" in d["error"]
    assert not (ws / ".orch/addons/usage/spent.jsonl").exists()


def test_a_subscription_has_no_amount_left(cli, ws, no_switcher):
    p = ws / ".orch/addons/usage/accounts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    sub = {
        "id": "a_sub001",
        "label": "Main subscription",
        "type": "subscription",
        "source": {"reader": "cswap", "key": "k1"},
        "on": True,
        "order": 1,
        "rule": store.empty_rule(),
        "prev": None,
    }
    p.write_text(json.dumps({"schema": store.SCHEMA, "accounts": [sub]}))
    code, d = jrun(cli, "left", "Main subscription", "10")
    assert code == 2 and "subscription" in d["error"]
    code, d = jrun(cli, "spent", "Main subscription", "1")
    assert code == 2


def test_same_name_at_two_providers_needs_the_provider(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "main", "anthropic")
    _add(cli, "OpenAI credit", "main", "openai")
    code, d = jrun(cli, "spent", "main", "1")
    assert code == 2 and "--provider" in d["error"]
    code, d = jrun(cli, "spent", "main", "1", "--provider", "openai")
    assert code == 0 and d["account"] == "OpenAI credit"


def test_reported_spend_counts_for_the_dollar_limit(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1", "anthropic", "--for", "reviews", "--limit", "$10")
    assert asking.ask(ws, "reviews", provider="anthropic")["go"] is True
    jrun(cli, "spent", "key-1", "12")
    ans = asking.ask(ws, "reviews", provider="anthropic")
    assert ans["go"] is False and "Claude API key 1 reached $10" in ans["why"]


def test_off_end_order_and_remove_land_in_the_history(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1")
    _add(cli, "Claude API key 3", "key-3")
    assert jrun(cli, "off", "Claude API key 3", "--by", "human:owner")[0] == 0
    assert jrun(cli, "on", "Claude API key 3", "--by", "human:owner")[0] == 0
    assert jrun(cli, "end", "Claude API key 1", "2026-12-01", "--by", "human:owner")[0] == 0
    assert jrun(cli, "order", "Claude API key 3", "1", "--by", "human:owner")[0] == 0
    assert jrun(cli, "left", "Claude API key 3", "$74", "--by", "human:owner")[0] == 0
    assert jrun(cli, "remove", "Claude API key 1", "--by", "human:owner")[0] == 0
    rows = store.history(ws)
    whats = {r["what"] for r in rows}
    assert {"turned off", "turned on", "left set to $74", "account removed"} <= whats
    assert any(w.startswith("credit ends ") for w in whats)
    assert any(w.startswith("order 2 to 1") for w in whats)
    assert all(r["who"] == "human:owner" for r in rows)
    labels = [a["label"] for a in store.load(ws)["accounts"] if not a.get("removed")]
    assert labels == ["Claude API key 3"]
    text = (ws / ".orch/addons/usage/history.jsonl").read_text()
    assert (
        "pass:" not in text and "sk-" not in text
    )  # only labels, amounts and times; never where or what a key is


def test_a_credit_end_is_the_credit_s_own_time_not_a_rule_end(cli, ws, no_switcher):
    _add(cli)
    code, d = jrun(cli, "end", "Claude API key 1", "2026-12-01T08:00", "--by", "human:owner")
    a = d["account"]
    assert code == 0 and a["credit_ends"] == store.utc_text(datetime(2026, 12, 1, 8, 0).astimezone())
    assert a["rule"]["ends"] is None  # a rule end falls back; the credit's own end does not
    code, out, _ = cli("list")
    assert "Claude API key 1 (on, ends 2026-12-01 08:00)" in out
    row = next(r for r in jrun(cli, "list")[1]["accounts"] if r["label"] == "Claude API key 1")
    assert row["credit_ends"] == a["credit_ends"]
    code, d = jrun(cli, "end", "Claude API key 1", "none", "--by", "human:owner")
    assert code == 0 and "credit_ends" not in d["account"]
    assert store.history(ws)[0]["what"] == "credit end taken away"


def test_remove_keeps_the_credit_and_restore_brings_it_back(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1", "anthropic", "--left", "74")
    code, out, _ = cli("remove", "Claude API key 1", "--by", "human:owner")
    assert code == 0 and 'orch usage restore "Claude API key 1"' in out
    a = _acct(ws, "Claude API key 1")
    assert a["removed"] is True and a["left"]["value"] == 74  # kept with what it had
    code, out, _ = cli("list")
    assert "1. Claude API key 1" not in out and "Removed: Claude API key 1" in out
    assert jrun(cli, "list")[1]["accounts"][0]["removed"] is True  # the page can offer Bring back
    # a credit skill listing it again does not add it back on
    with store.change(ws) as (accounts, rows):
        store.sync_known(
            accounts,
            rows,
            "anthropic",
            [store.check_known({"name": "key-1", "label": "Key 1", "log": "spend.jsonl"})],
        )
    assert [x["label"] for x in store.load(ws)["accounts"]] == ["Claude API key 1"]
    code, d = jrun(cli, "add", "Claude API key 1", "--provider", "anthropic", "--name", "key-9")
    assert code == 2 and "orch usage restore" in d["error"]
    assert jrun(cli, "restore", "Claude API key 1", "--by", "human:owner")[0] == 0
    assert not _acct(ws, "Claude API key 1").get("removed")
    assert [r["what"] for r in store.history(ws)[:2]] == ["account brought back", "account removed"]


def test_a_removed_tool_is_not_picked_for_a_helper_start(cli, ws, no_switcher):
    from test_routing import CREW, req

    from orch_usage import routing

    _add(
        cli,
        "Tool on key",
        "main",
        "anthropic",
        "--type",
        "helper-tool",
        "--tool",
        "tool-x",
        "--for",
        "reviews",
    )
    here = ("main-tool", "tool-x")
    assert routing.decide(ws, req(CREW("reviewer"), agents=here)).get("account") == "Tool on key"
    with store.change(ws) as (accounts, rows):  # past its own end: not picked either
        store.set_credit_end(store.find(accounts, "Tool on key"), rows, "human:o", "2026-01-01T00:00:00Z")
    assert routing.decide(ws, req(CREW("reviewer"), agents=here)).get("account") != "Tool on key"
    with store.change(ws) as (accounts, rows):
        store.set_credit_end(store.find(accounts, "Tool on key"), rows, "human:o", None)
    jrun(cli, "remove", "Tool on key")
    assert routing.decide(ws, req(CREW("reviewer"), agents=here)).get("account") != "Tool on key"


def test_an_unreadable_spend_log_is_marked_not_empty(cli, ws, no_switcher, monkeypatch):
    _add(cli, "Claude API key 1", "key-1", "anthropic", "--left", "10")
    jrun(cli, "spent", "key-1", "4")
    real_open = open

    def broken(path, *a, **k):
        if str(path).endswith("spent.jsonl") and "r" in (a[0] if a else k.get("mode", "r")):
            raise PermissionError("no")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", broken)
    c = left.credit_use(ws, _acct(ws, "Claude API key 1"), None)
    assert c.estimated is True and "could not be read" in c.note
    v = left.view(ws, _acct(ws, "Claude API key 1"))
    assert v["measured"] is False and "may be less" in left.text(v)


def test_the_key_guard_takes_short_names_and_refuses_key_shapes(cli, ws, no_switcher):
    for ok in ("key-1", "key-12", "main"):
        assert store.check_known({"name": ok, "label": "A credit", "log": "spend.jsonl"})["name"] == ok
    for bad in ("key-abcd1234", "key-ab-cd-ef-gh", "sk-anything"):
        code, _ = jrun(cli, "add", "Some credit", "--provider", "openai", "--name", bad)
        assert code == 2, bad
