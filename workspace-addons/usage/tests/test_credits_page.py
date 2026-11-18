"""ORCH-628: the API credits section of the Usage page. Each credit shows what is left, spent today and this month,
its end; the page sets what is left with the click `left`; never a key name, path or key value on the page."""

import json

import pytest
from conftest import jrun

from orch_usage import acts, page, store
from orch_usage import cli as usage_cli

KEYISH = "sk-ant-api03-" + "x" * 40


def _add(cli, label="Claude API key 1", name="key-1", *extra):
    code, d = jrun(
        cli, "add", label, "--provider", "anthropic", "--name", name, "--by", "human:owner", *extra
    )
    assert code == 0, d
    return d["account"]


def _model(ws):
    return page.build(usage_cli.gather(ws), ws)


def _credit(m, label):
    return next(a for a in m["accounts"] if a["label"] == label)


def test_credit_shows_left_spent_and_its_skill(cli, ws, no_switcher):
    _add(cli, "Claude API key 1", "key-1", "--left", "100")
    assert jrun(cli, "spent", "key-1", "3.50")[0] == 0
    with store.change(ws) as (accounts, _rows):  # the declaring skill, as the credit reader records it
        store.find(accounts, "Claude API key 1")["source"]["skill"] = "claude-api-credit"
    a = _credit(_model(ws), "Claude API key 1")
    c = a["credit"]
    assert (c["set"], c["spent_since"], c["left"]) == (100, 3.5, 96.5)
    assert c["spent_today"] == 3.5 and c["spent_month"] == 3.5
    assert c["skill"] == "claude-api-credit" and a["provider_label"] == "Anthropic"
    assert c["ends"] is None and a["state"] in ("ready", "in-use")


def test_credit_not_set_yet_and_subscriptions_have_no_credit(cli, ws, fake_switcher):
    assert jrun(cli, "list")[0] == 0
    _add(cli, "OpenAI API", "main")
    m = _model(ws)
    c = _credit(m, "OpenAI API")["credit"]
    assert c["left"] is None and c["set"] is None
    assert all(a["credit"] is None for a in m["accounts"] if a["type"] == "subscription")


def test_end_shows_on_the_credit(cli, ws, no_switcher):
    a = _add(cli)
    assert jrun(cli, "act", "end", f"{a['id']}:2026-12-31", "--by", "human:owner")[0] == 0
    assert _credit(_model(ws), "Claude API key 1")["credit"]["ends"].startswith("2026-12-31")


def test_left_click_sets_the_amount_with_a_history_line(cli, ws, no_switcher):
    a = _add(cli)
    code, d = jrun(cli, "act", "left", f"{a['id']}:73.40", "--by", "human:Some Person")
    assert code == 0, d
    c = _credit(_model(ws), "Claude API key 1")["credit"]
    assert c["left"] == 73.4 and c["set_at"]
    assert any("left" in r["text"] and r["who"] == "You" for r in page.history_rows(ws))
    assert jrun(cli, "act", "left", f"{a['id']}:0", "--by", "human:o")[0] == 0  # 0: calls are refused
    assert _credit(_model(ws), "Claude API key 1")["credit"]["left"] == 0


@pytest.mark.parametrize("target", ["a_abcdef:-3", "a_abcdef:12%", "a_abcdef", "a_abcdef:74;rm", "x:74"])
def test_bad_left_clicks_are_refused(ws, target):
    with pytest.raises(store.Refused):
        acts.argv_for(ws, "left", target, None)


def test_left_click_is_the_cli_command(ws):
    assert acts.argv_for(ws, "left", "a_abcdef:$74", "human:o") == [
        "left",
        "a_abcdef",
        "$74",
        "--by",
        "human:o",
    ]


def test_no_key_name_path_or_key_on_the_page(cli, ws, no_switcher, tmp_path):
    _add(cli, "Claude API key 1", "key-1", "--left", "50")
    # whatever a reader keeps about where the key lives stays off the page
    with store.change(ws) as (accounts, _rows):
        src = store.find(accounts, "Claude API key 1")["source"]
        src.update(path=str(tmp_path / "spend.jsonl"), vault="pass://Agents/claude key 1", skill=KEYISH)
    text = json.dumps(_model(ws))
    assert KEYISH not in text and "pass://" not in text and "spend.jsonl" not in text
    assert '"source"' not in text and "key-1" not in text  # nor the name the skill finds its key by


def test_remove_then_bring_back_from_the_page(cli, ws, no_switcher):
    a = _add(cli, "Old Claude key", "key-9", "--left", "20")
    assert jrun(cli, "act", "remove", a["id"], "--by", "human:owner")[0] == 0
    m = _model(ws)
    assert "Old Claude key" not in [x["label"] for x in m["accounts"]]
    assert m["removed"] == [{"id": a["id"], "label": "Old Claude key", "type": "api-key"}]
    assert acts.argv_for(ws, "restore", a["id"], None) == ["restore", a["id"]]
    assert jrun(cli, "act", "restore", a["id"], "--by", "human:owner")[0] == 0
    m = _model(ws)
    assert (
        m["removed"] == [] and _credit(m, "Old Claude key")["credit"]["left"] == 20
    )  # comes back with its amount


def test_a_helper_tools_end_shows_on_its_card(cli, ws, no_switcher):
    code, d = jrun(
        cli,
        "add",
        "Codex",
        "--provider",
        "openai",
        "--type",
        "helper-tool",
        "--name",
        "codex",
        "--limit",
        "90",
        "--by",
        "human:owner",
    )
    assert code == 0, d
    assert jrun(cli, "act", "end", f"{d['account']['id']}:2026-12-31", "--by", "human:owner")[0] == 0
    assert _credit(_model(ws), "Codex")["ends"]
