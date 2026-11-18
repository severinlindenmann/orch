"""How work is spread (ORCH-657): set by command and by page clicks, refused when it contradicts itself, read back
as one sentence with what each number counts, and every change in the Usage history."""

from __future__ import annotations

import json

import pytest
from conftest import jrun

from orch_usage import acts, share, store
from orch_usage.store import Refused

ME = "human:owner"


def _share_rows(ws):
    return [r for r in store.history(ws) if r.get("account") == share.ACCOUNT]


def test_no_share_reads_back_plainly(cli, no_switcher):
    code, d = jrun(cli, "share")
    assert code == 0 and d["share"] is None and d["changed"] is False
    assert d["sentence"].startswith("No share set")
    assert [p["id"] for p in d["presets"]] == ["save", "even", "sub"]


def test_preset_then_parts_by_command(cli, no_switcher, ws):
    code, d = jrun(cli, "share", "--preset", "even", "--by", ME)
    assert code == 0 and d["changed"] and d["preset"] == "even"
    assert d["sentence"] == (
        "Use the subscriptions first, up to 70 % of their week by Wednesday; run Reviews and Scripts on API credit "
        "and one in 4 Code tickets on Codex; when a subscription is ahead of that pace, send new starts to API credit "
        "for up to $10 a day."
    )
    code, d = jrun(
        cli, "share", "--week", "60%", "--day", "thu", "--api", "review, scripts and helpers",
        "--codex", "one in 3", "--dollars", "$20", "--by", ME,
    )
    assert code == 0 and d["preset"] is None
    assert d["share"] == {
        "week_pct": 60, "by_day": "thursday", "api_for": ["reviews", "scripts", "helpers"],
        "codex_one_in": 3, "when_ahead": "api", "day_dollars": 20,
    }
    saved = json.loads((ws / ".orch/addons/usage/share.json").read_text())
    assert saved["schema"] == share.SCHEMA and saved["share"] == d["share"]


def test_every_change_is_one_history_line_with_before_and_after(cli, no_switcher, ws):
    jrun(cli, "share", "--preset", "even", "--by", ME)
    jrun(cli, "share", "--codex", "all", "--by", ME)
    code, d = jrun(cli, "share", "--codex", "all", "--by", ME)  # already like that
    assert code == 0 and d["changed"] is False
    rows = _share_rows(ws)
    assert len(rows) == 2
    assert rows[0]["what"] == "all Code tickets on Codex (was one in 4 Code tickets on Codex)"
    assert rows[0]["before"]["codex_one_in"] == 4 and rows[0]["after"]["codex_one_in"] == 1
    assert rows[1]["what"].startswith("Even spread: Use the subscriptions first")
    assert all(r["who"] == ME and r["label"] == share.LABEL for r in rows)
    code, d = jrun(cli, "history", "--account", "share")
    assert code == 0 and len(d["history"]) == 2
    jrun(cli, "share", "--clear", "--by", ME)
    assert _share_rows(ws)[0]["after"] is None and share.load(ws) is None


@pytest.mark.parametrize(
    ("argv", "words"),
    [
        (["--api", "code", "--codex", "all"], "Pick one of the two"),
        (["--api", "lead,code,reviews,builds,scripts,helpers"], "nothing starts on the subscriptions"),
        (["--ahead", "api", "--dollars", "0"], "$0 a day"),
        (["--ahead", "codex", "--dollars", "10"], "Dollars a day only count"),
        (["--week", "100"], "never ahead of its pace"),
    ],
)
def test_a_share_that_contradicts_itself_is_refused(cli, no_switcher, ws, argv, words):
    jrun(cli, "share", "--preset", "even", "--by", ME)
    code, d = jrun(cli, "share", *argv, "--by", ME)
    assert code == 2 and words in d["error"]
    assert share.load(ws) == share.PRESETS["even"]["share"]  # nothing written
    assert len(_share_rows(ws)) == 1


def test_choosing_codex_or_none_drops_the_dollars_and_api_brings_them_back(cli, no_switcher, ws):
    jrun(cli, "share", "--preset", "even", "--by", ME)
    assert jrun(cli, "share", "--ahead", "codex", "--by", ME)[1]["share"]["day_dollars"] == 0
    d = jrun(cli, "share", "--ahead", "api", "--by", ME)[1]
    assert d["share"]["day_dollars"] == 10
    d = jrun(cli, "share", "--ahead", "none", "--week", "100", "--by", ME)[1]
    assert d["sentence"].endswith("new starts stay on the subscriptions even when one is ahead of that pace.")


@pytest.mark.parametrize(
    ("argv", "words"),
    [
        (["--week", "5"], "from 10 to 100"),
        (["--day", "someday"], "not a weekday"),
        (["--api", "dishes"], "not a kind of work"),
        (["--codex", "one in 40"], "not a share of Code tickets"),
        (["--ahead", "moon"], "not a choice"),
        (["--dollars", "lots"], "not an amount"),
        (["--preset", "best"], "no ready-made spread"),
        (["--clear", "--week", "70"], "does not go with other changes"),
    ],
)
def test_bad_words_are_refused_plainly(cli, no_switcher, argv, words):
    code, d = jrun(cli, "share", *argv, "--by", ME)
    assert code == 2 and words in d["error"]


def test_each_number_says_what_it_counts_and_when_it_starts_again():
    lines = share.counts(share.PRESETS["even"]["share"], {"Personal 1": "Wed 20:59"})
    assert "70 % counts how much of a subscription's week is used" in lines[0]
    assert "3 of the 7 days" in lines[0] and "Personal 1: Wed 20:59" in lines[0]
    assert "counts helper starts of Code tickets" in lines[1] and "midnight" in lines[1]
    assert "$10 a day counts dollars spent on API credit" in lines[2] and "midnight" in lines[2]


def test_sentence_names_accounts_in_order_and_warns_when_a_source_is_missing():
    accounts = [
        {"label": "Personal 1", "type": "subscription", "on": True},
        {"label": "Company", "type": "subscription", "on": True},
        {"label": "Old", "type": "subscription", "on": False},
        {"label": "Claude API key 1", "type": "api-key", "on": True},
        {"label": "OpenAI API", "type": "api-key", "on": True},
    ]
    s = share.PRESETS["even"]["share"]
    text = share.sentence(s, accounts)
    assert "subscriptions first (Personal 1, then Company)" in text and "Old" not in text
    assert "on API credit (Claude API key 1, then OpenAI API)" in text
    assert share.warnings(s, accounts) == [
        "Codex is not on in Usage yet. Until it is, work set for Codex stays on the subscriptions."
    ]
    assert share.warnings(s, accounts + [{"label": "Codex", "type": "helper-tool", "on": True}]) == []


def test_order_by_command_moves_accounts_and_is_in_the_history(cli, fake_switcher, ws):
    jrun(cli, "list")
    labels = [a["label"] for a in store.load(ws)["accounts"]]
    code, d = jrun(cli, "share", "--order", f"{labels[2]}, {labels[0]}", "--by", ME)
    assert code == 0 and d["changed"]
    assert d["order"][:2] == [labels[2], labels[0]]
    assert any(r["what"].startswith("order") for r in store.history(ws))
    assert jrun(cli, "share", "--order", f"{labels[0]},{labels[0]}", "--by", ME)[0] == 2


@pytest.mark.parametrize(
    ("target", "words"),
    [
        ("preset:sub", ["share", "--preset", "sub"]),
        ("week:70:wednesday", ["share", "--week", "70", "--day", "wednesday"]),
        ("api:reviews,scripts", ["share", "--api", "reviews,scripts"]),
        ("api:none", ["share", "--api", "none"]),
        ("codex:4", ["share", "--codex", "4"]),
        ("ahead:both:20", ["share", "--ahead", "both", "--dollars", "20"]),
        ("clear", ["share", "--clear"]),
    ],
)
def test_page_clicks_become_the_share_command(ws, target, words):
    assert acts.argv_for(ws, "share", target, "human:Some Person") == [*words, "--by", "human:Some_Person"]


@pytest.mark.parametrize("target", ["preset:all", "week:70:wed", "api:reviews;rm", "codex:", "ahead:api", "x"])
def test_page_clicks_of_another_shape_are_refused(ws, target):
    with pytest.raises(Refused):
        acts.argv_for(ws, "share", target, None)


def test_page_click_refusal_and_page_model(cli, no_switcher, ws):
    code, d = jrun(cli, "act", "share", "preset:even", "--by", "human:Some Person")
    assert code == 0 and d["preset"] == "even"
    code, d = jrun(cli, "act", "share", "ahead:api:0", "--by", "human:Some Person")
    assert code == 2 and "$0 a day" in d["error"]
    from orch_usage import cli as cli_mod
    from orch_usage import page

    m = page.build(cli_mod.gather(ws), ws)
    assert m["share"]["preset"] == "even" and m["share"]["sentence"].startswith("Use the subscriptions first")
    assert any(r["text"].startswith("How work is spread: Even spread") and r["who"] == "You" for r in m["history"])


def test_a_broken_share_file_is_reported_not_used(cli, no_switcher, ws):
    d = ws / ".orch/addons/usage"
    d.mkdir(parents=True)
    (d / "share.json").write_text('{"schema": "orch.usage-share/1", "share": {"week_pct": 7}}')
    code, v = jrun(cli, "share")
    assert code == 0 and v["share"] is None and "could not be read" in v["warnings"][0]
    assert jrun(cli, "share", "--preset", "sub", "--by", ME)[1]["share"] == share.PRESETS["sub"]["share"]


def test_a_refused_order_saves_nothing_else(cli, fake_switcher, ws):
    jrun(cli, "list")
    code, d = jrun(cli, "share", "--preset", "save", "--order", "nobody", "--by", ME)
    assert code == 2 and share.load(ws) is None and not _share_rows(ws)


def test_odd_kinds_in_the_file_do_not_crash(cli, no_switcher, ws):
    d = ws / ".orch/addons/usage"
    d.mkdir(parents=True)
    bad = dict(share.PRESETS["even"]["share"], api_for=[{}])
    (d / "share.json").write_text(json.dumps({"schema": share.SCHEMA, "share": bad}))
    code, v = jrun(cli, "share")
    assert code == 0 and v["share"] is None and "could not be read" in v["warnings"][0]


def test_a_newer_share_format_is_never_overwritten(cli, no_switcher, ws):
    d = ws / ".orch/addons/usage"
    d.mkdir(parents=True)
    (d / "share.json").write_text('{"schema": "orch.usage-share/2", "share": {"new": 1}}')
    code, v = jrun(cli, "share", "--preset", "even", "--by", ME)
    assert code == 2 and "newer orch" in v["error"]
    assert "orch.usage-share/2" in (d / "share.json").read_text()
