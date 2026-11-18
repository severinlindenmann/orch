"""ORCH-342: the five owner rules the stage 2 test found not acting yet (owner-rules-test-report.md).

1. One money limit over several accounts ("API cap $100" = every key of the provider together).
2. Model per kind of work (the account's rule narrows orch's pick, never widens it; a person's choice wins).
3. Order is part of a temporary rule (the account goes back to its place when the rule ends).
4. Add and remove an API credit or helper tool with one command and one click (a name, never the key).
5. A start whose helper tool runs on a subscription waits while every subscription is at its limit.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import jrun, switcher_data
from test_routing import CREW, _answer_ok, _owner_rules, req

from orch_usage import acts, asking, routing, store
from orch_usage.cli import gather


def _spend(path, rows):
    path.write_text("".join(json.dumps({"t": store.now(), "account": n, "usd": u}) + "\n" for n, u in rows))
    return str(path)


def _two_keys(ws, log, *, tool=None):
    """Two Anthropic API keys, $100 a month each, for Reviews; both log to one spend log."""
    p = ws / ".orch/addons/usage/accounts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text()) if p.exists() else {"schema": store.SCHEMA, "accounts": []}
    for i, name in enumerate(("main", "second")):
        data["accounts"].append(
            {
                "id": f"a_key00{i}",
                "label": f"Key {name}",
                "type": "api-key",
                "provider": "anthropic",
                **({"tool": tool} if tool else {}),
                "source": {"reader": "spend-log", "path": log, "name": name},
                "on": True,
                "order": 0,
                "rule": {
                    "limits": [{"value": 100, "unit": "$", "period": "month"}],
                    "for": ["reviews"],
                    "ends": None,
                },
                "prev": None,
            }
        )
    p.write_text(json.dumps(data))


# ---------------------------------------------------------------- 1. one limit over several accounts


def test_140_over_two_keys_is_refused_at_a_100_limit_over_both(cli, ws, tmp_path, no_switcher):
    log = _spend(tmp_path / "spend.jsonl", [("main", 70), ("second", 70)])
    _two_keys(ws, log)
    ans = asking.ask(ws, "reviews", provider="anthropic")
    assert ans["go"] is True and ans["name"] == "main"  # each key alone is under its own $100
    code, d = jrun(cli, "together", "anthropic", "$100", "--by", "human:owner")
    assert code == 0 and d["changed"] and d["together"][0]["limit"]["value"] == 100
    ans = asking.ask(ws, "reviews", provider="anthropic")
    assert ans["go"] is False
    assert ans["why"].startswith("No room for Reviews: All Anthropic accounts together reached $100 (month).")
    assert ans["until"]
    # the history says who set it
    row = store.history(ws)[0]
    assert row["label"] == "All Anthropic accounts together" and row["who"] == "human:owner"
    assert row["what"] == "limit $100 (month)"


def test_a_limit_over_both_leaves_less_and_counts_an_off_account(cli, ws, tmp_path, no_switcher):
    log = _spend(tmp_path / "spend.jsonl", [("main", 20), ("second", 50)])
    _two_keys(ws, log)
    jrun(cli, "off", "Key second")  # spending on it still counts
    jrun(cli, "together", "anthropic", "100")
    ans = asking.ask(ws, "reviews", provider="anthropic")
    assert ans["go"] is True and ans["left"] == 30  # $80 left on its own limit, $30 over both
    m = gather(ws)
    (t,) = m["together"]
    assert t["spent"] == 70 and t["accounts"] == ["Key main", "Key second"] and t["resets_at"]


def test_helper_starts_on_a_tool_respect_the_limit_over_both(cli, ws, tmp_path, no_switcher):
    log = _spend(tmp_path / "spend.jsonl", [("main", 60), ("second", 45)])
    _two_keys(ws, log, tool="tool-x")
    here = ("main-tool", "tool-x")
    assert routing.decide(ws, req(CREW("reviewer"), agents=here))["account"] == "Key main"
    jrun(cli, "together", "anthropic", "$100")
    ans = routing.decide(ws, req(CREW("reviewer"), agents=here))
    assert ans["go"] is False and "All Anthropic accounts together reached $100" in ans["why"]
    assert _answer_ok(ans)


def test_together_set_change_remove_and_refusals(cli, ws, tmp_path, no_switcher):
    code, d = jrun(cli, "together", "anthropic", "$100")
    assert code == 2 and "Add one first" in d["error"]
    _two_keys(ws, _spend(tmp_path / "s.jsonl", []))
    code, d = jrun(cli, "together", "anthropic", "50%")
    assert code == 2 and "dollars" in d["error"]
    jrun(cli, "together", "anthropic", "$100", "--resets", "2026-11-17")
    code, d = jrun(cli, "together", "anthropic", "$120")
    assert d["together"][0]["limit"]["since"]  # a new number keeps the reset day
    code, d = jrun(cli, "together", "anthropic", "$120")
    assert code == 0 and d["changed"] is False
    code, d = jrun(cli, "together", "anthropic", "none")
    assert code == 0 and d["together"] == []
    assert "together" not in json.loads((ws / ".orch/addons/usage/accounts.json").read_text())
    # a hand-broken row is counted, never used
    p = ws / ".orch/addons/usage/accounts.json"
    data = json.loads(p.read_text())
    data["together"] = [{"provider": "anthropic", "limit": {"value": 5, "unit": "%", "period": "month"}}]
    p.write_text(json.dumps(data))
    d = store.load(ws)
    assert d["together"] == [] and d["unreadable"] == 1


def test_together_page_click(cli, ws, tmp_path, no_switcher):
    _two_keys(ws, _spend(tmp_path / "s.jsonl", []))
    assert acts.argv_for(ws, "together", "anthropic:$100", "human:o") == [
        "together",
        "anthropic",
        "$100",
        "--by",
        "human:o",
    ]
    for bad in ("anthropic:90%", "Anthropic:$1", "anthropic", "a;b:$1"):
        with pytest.raises(store.Refused):
            acts.argv_for(ws, "together", bad, None)
    code, _out, _ = cli("act", "together", "anthropic:100", "--by", "human:o")
    assert code == 0 and store.load(ws)["together"][0]["limit"]["value"] == 100


# ---------------------------------------------------------------- 2. model per kind of work


def test_small_model_only_narrows_the_pick(cli, fake_switcher, ws):
    _owner_rules(cli)
    code, d = jrun(cli, "model", "first", "small", "--by", "human:owner")
    assert code == 0 and d["account"]["rule"]["model"] == "small"
    assert store.history(ws)[0]["what"] == "small model only"
    ans = routing.decide(ws, req())
    assert ans == {"go": True, "account": "first", "model": "sonnet"} and _answer_ok(ans)
    # orch's pick moved up does not widen "small only"
    assert routing.decide(ws, req(model="opus", model_up=True))["model"] == "sonnet"
    # a model a person set on the ticket wins
    ans = routing.decide(ws, req(model="opus", chosen={"agent": False, "model": True}))
    assert "model" not in ans
    # already smaller: nothing to narrow
    assert "model" not in routing.decide(ws, req(model="haiku"))


def test_small_first_allows_the_big_one_once_moved_up(cli, fake_switcher, ws):
    _owner_rules(cli)
    jrun(cli, "model", "first", "first")
    assert routing.decide(ws, req(model="opus"))["model"] == "sonnet"  # orch's first pick: small
    assert "model" not in routing.decide(ws, req(model="opus", model_up=True))
    _code, d = jrun(cli, "model", "first", "any")
    assert "model" not in d["account"]["rule"] and "model" not in routing.decide(ws, req())


def test_model_part_ends_with_a_temporary_rule_and_has_a_click(cli, fake_switcher, ws):
    _owner_rules(cli)
    end = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    jrun(cli, "model", "first", "small", "--end", end)
    a = store.load(ws)["accounts"][0]
    later = datetime.now(UTC) + timedelta(days=4)
    with store.change(ws) as (accounts, rows):
        store.expire(accounts, rows, later)
    assert "model" not in store.find(store.load(ws)["accounts"], "first")["rule"]
    assert acts.argv_for(ws, "model", f"{a['id']}:first", None) == ["model", a["id"], "first"]
    with pytest.raises(store.Refused):
        acts.argv_for(ws, "model", f"{a['id']}:opus", None)
    code, _d = jrun(cli, "model", "first", "opus")
    assert code == 2


# ---------------------------------------------------------------- 3. order in a temporary rule


def test_a_temporary_first_place_goes_back_when_the_rule_ends(cli, fake_switcher, ws):
    jrun(cli, "list")
    end = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    code, d = jrun(cli, "order", "TEAMCO", "1", "--end", end, "--by", "human:owner")
    assert code == 0 and d["account"]["order"] == 1 and d["account"]["rule"]["ends"]
    assert "falls back" in d["next"]
    assert [a["label"] for a in store.load(ws)["accounts"]] == ["TEAMCO", "first", "second"]
    assert store.history(ws)[0]["what"].startswith("order 3 to 1 until ")
    later = datetime.now(UTC) + timedelta(days=4)
    with store.change(ws) as (accounts, rows):
        store.expire(accounts, rows, later)
    assert [a["label"] for a in store.load(ws)["accounts"]] == ["first", "second", "TEAMCO"]
    row = store.history(ws)[0]
    assert row["what"] == "rule ended, back to place 3 (was 1)" and row["who"] == "usage"
    t = store.find(store.load(ws)["accounts"], "TEAMCO")
    assert "order" not in t["rule"] and t["prev"] is None


def test_order_changed_while_a_rule_is_temporary_is_part_of_it(cli, fake_switcher, ws):
    """'Third key first for Scripts until a date': for + end first, then the order on the page."""
    jrun(cli, "list")
    end = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%d")
    jrun(cli, "for", "TEAMCO", "scripts", "--end", end)
    jrun(cli, "order", "TEAMCO", "1")
    jrun(cli, "limit", "TEAMCO", "50%", "--period", "5h")  # a later change keeps the place in the rule
    assert store.find(store.load(ws)["accounts"], "TEAMCO")["rule"]["order"] == 1
    with store.change(ws) as (accounts, rows):
        store.expire(accounts, rows, datetime.now(UTC) + timedelta(days=4))
    t = store.find(store.load(ws)["accounts"], "TEAMCO")
    assert t["order"] == 3 and t["rule"]["for"] == [] and t["rule"]["limits"] == []


def test_a_plain_order_change_stays(cli, fake_switcher, ws):
    jrun(cli, "list")
    jrun(cli, "order", "TEAMCO", "1")
    t = store.find(store.load(ws)["accounts"], "TEAMCO")
    assert t["order"] == 1 and "order" not in t["rule"] and t["prev"] is None


# ---------------------------------------------------------------- 4. add and remove an account


def test_add_the_owners_openai_credit_with_one_command(cli, ws, tmp_path, no_switcher):
    code, d = jrun(
        cli,
        "add",
        "Codex / OpenAI credit",
        "--provider",
        "openai",
        "--name",
        "openai",
        "--for",
        "reviews",
        "--limit",
        "$100",
        "--resets",
        "2026-11-17",
        "--first",
        "--by",
        "human:owner",
    )
    assert code == 0 and d["changed"]
    a = store.load(ws)["accounts"][0]
    assert a["label"] == "Codex / OpenAI credit" and a["type"] == "api-key" and a["provider"] == "openai"
    assert a["rule"]["for"] == ["reviews"] and a["rule"]["limits"][0]["value"] == 100
    assert a["rule"]["limits"][0]["since"] and a["source"] == {"reader": "none", "name": "openai"}
    assert store.history(ws)[0]["what"] == "account added"
    # the skill asks: Usage answers with the name it already uses, and learns where it logs spend
    ans = asking.ask(ws, "reviews", provider="openai")
    assert ans == {"go": True, "account": "Codex / OpenAI credit", "provider": "openai", "name": "openai"}
    log = _spend(tmp_path / "oa.jsonl", [("openai", 100.5)])
    known = [store.check_known({"name": "openai", "label": "OpenAI credit", "log": log, "limit": 50})]
    ans = asking.ask(ws, "reviews", provider="openai", known=known)
    assert ans["go"] is False and "Codex / OpenAI credit reached $100 (month)" in ans["why"]
    a = store.load(ws)["accounts"][0]
    assert (
        a["source"]["reader"] == "spend-log" and a["rule"]["limits"][0]["value"] == 100
    )  # the person's rule


def test_add_refuses_keys_logins_and_doubles(cli, ws, no_switcher):
    base = ["--provider", "openai", "--name", "main"]
    assert jrun(cli, "add", "sk-abc123", *base)[0] == 2
    assert jrun(cli, "add", "me@example.test", *base)[0] == 2
    code, d = jrun(cli, "add", "OpenAI", "--provider", "openai", "--name", "sk-" + "x" * 40)
    assert code == 2 and "Never the key" in d["error"]
    assert jrun(cli, "add", "OpenAI", *base, "--limit", "90%")[0] == 2
    assert jrun(cli, "add", "OpenAI", *base)[0] == 0
    assert jrun(cli, "add", "OpenAI", *base)[0] == 2  # same label
    assert jrun(cli, "add", "Other", *base)[0] == 2  # same provider and name
    text = (ws / ".orch/addons/usage/accounts.json").read_text()
    assert "sk-" not in text and "@" not in text


def test_add_and_remove_by_page_click(cli, ws, no_switcher):
    target = "openai:api-key:openai:reviews:$100:2026-11-17:Codex / OpenAI credit"
    words = acts.argv_for(ws, "add", target, "human:o")
    assert words[:2] == ["add", "Codex / OpenAI credit"] and "--resets" in words and "--first" not in words
    for bad in (
        "openai:subscription:x:any:none:-:Label",
        "openai:api-key:x:any:none:-:-rf",
        "openai:api-key:x:any:90%:-:Label",
        "openai:api-key:x:any:none:-:a\nb",
        "openai:api-key:x:any:none:-:" + "L" * 65,
    ):
        with pytest.raises(store.Refused):
            acts.argv_for(ws, "add", bad, None)
    code, _out, _ = cli("act", "add", target, "--by", "human:o")
    assert code == 0
    a = store.load(ws)["accounts"][0]
    assert a["label"] == "Codex / OpenAI credit" and a["rule"]["limits"][0]["since"]
    code, _out, _ = cli("act", "add", "anthropic:helper-tool:main:code:none:-:Tool on key", "--by", "human:o")
    assert code == 0 and store.find(store.load(ws)["accounts"], "Tool on key")["type"] == "helper-tool"
    code, _out, _ = cli("act", "remove", a["id"], "--by", "human:o")
    assert code == 0 and [x["label"] for x in store.load(ws)["accounts"] if not x.get("removed")] == [
        "Tool on key"
    ]
    assert store.history(ws)[0]["what"] == "account removed"


def test_a_subscription_cannot_be_removed(cli, fake_switcher, ws):
    jrun(cli, "list")
    code, d = jrun(cli, "remove", "first")
    assert code == 2 and "Turn it off instead" in d["error"]


# ---------------------------------------------------------------- 5. every subscription at its limit


def _full(fake_switcher, cli):
    """17 Nov: lindenmann ('first') the only subscription, up to 100 % weekly, for Lead and Helpers; at 100 %."""
    fake_switcher.answer(switcher_data(first=(50.0, 100.0), second=(0.0, 10.0), third=(0.0, 10.0)))
    _owner_rules(cli)


SUB = {"main-tool": "anthropic", "tool-x": "openai"}


@pytest.mark.parametrize("role", ["reviewer", "builder", "release"])
def test_every_kind_on_the_subscription_waits_when_it_is_full(cli, fake_switcher, ws, role):
    _full(fake_switcher, cli)
    ans = routing.decide(ws, req(CREW(role), providers=SUB))
    assert ans["go"] is False and _answer_ok(ans)
    word = store.KIND_WORDS[routing.kind_of(req(CREW(role)))]
    assert ans["why"].startswith(f"No room for {word}: every subscription is at its limit (first: week 100%")
    assert ans["until"] == "2026-11-18T19:59:59Z"
    assert [h["what"] for h in store.history(ws) if h["what"].startswith("warning")] == [
        f"warning: work for {word} waits"
    ]


def test_full_subscription_holds_once_and_goes_when_there_is_room(cli, fake_switcher, ws):
    _full(fake_switcher, cli)
    routing.decide(ws, req(CREW("reviewer"), providers=SUB, ticket="t_aaaaaa"))
    routing.decide(ws, req(CREW("reviewer"), providers=SUB, ticket="t_cccccc"))
    assert len([h for h in store.history(ws) if h["what"] == "warning: work for Reviews waits"]) == 1
    (row,) = [r for r in routing.needs_rows(ws) if r["id"] == "usage:no-room-reviews"]
    assert "2 tickets wait." in row["text"]
    fake_switcher.answer(switcher_data(first=(50.0, 60.0)))
    assert routing.decide(ws, req(CREW("reviewer"), providers=SUB)) == {"go": True}
    assert store.history(ws)[0]["what"] == "room again for Reviews"


def test_a_start_not_on_the_subscription_still_goes(cli, fake_switcher, ws, tmp_path):
    _full(fake_switcher, cli)
    # the tool runs on its own credit (the owner's OpenAI credit once its helpers ship)
    from test_routing import _credit

    _credit(ws, tool="tool-x")
    ans = routing.decide(ws, req(CREW("builder"), agents=("main-tool", "tool-x"), providers=SUB))
    assert ans == {"go": True, "account": "Codex / OpenAI credit", "agent": "tool-x"}
    # a tool whose provider has no subscription listed, or an older core without `providers`: as before
    assert routing.decide(ws, req(CREW("release"), agent="tool-x", agents=("tool-x",), providers=SUB)) == {
        "go": True
    }
    assert routing.decide(ws, req(CREW("reviewer"))) == {"go": True}


def test_a_subscription_turned_off_does_not_count(cli, fake_switcher, ws):
    _full(fake_switcher, cli)
    jrun(cli, "on", "second")  # 10 % used: room
    assert routing.decide(ws, req(CREW("reviewer"), providers=SUB))["go"] is True
