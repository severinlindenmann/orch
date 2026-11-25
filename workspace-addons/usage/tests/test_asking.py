"""Stage 2: credit skills and helpers' own subagents ask Usage before they spend (`orch usage ask`)."""

import io
import json
from datetime import UTC, datetime

import pytest
from conftest import jrun

from orch_usage import asking, page, routing, store
from orch_usage import cli as usage_cli
from orch_usage.readers import spend_log

RESET = "2026-11-17T00:00:00Z"
AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def openai_known(log, limit=100):
    return [
        {
            "name": "openai",
            "label": "OpenAI credit",
            "log": log,
            "limit": limit,
            "since": RESET,
            "for": ["reviews"],
            "first": True,
            "unnamed": True,
        }
    ]


def claude_known(log):
    return [
        {"name": "main", "label": "Claude API credit (main)", "log": log, "limit": 180, "for": ["reviews"]},
        {
            "name": "second",
            "label": "Claude API credit (second)",
            "log": log,
            "limit": 100,
            "for": ["reviews"],
        },
    ]


def _ask(cli, monkeypatch, *argv, stdin=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin)))
    code, out, _ = cli("ask", *argv, "--json")
    return code, json.loads(out)


def test_nothing_set_means_do_as_today(cli, ws, monkeypatch, no_switcher):
    code, ans = _ask(cli, monkeypatch, "reviews", "--provider", "openai")
    assert code == 0 and ans == {"go": True}
    code, ans = _ask(cli, monkeypatch, "reviews")
    assert code == 0 and ans == {"go": True}


def test_a_skill_lists_its_credit_once_with_its_starting_rule(cli, ws, tmp_path, monkeypatch, no_switcher):
    log = _log(tmp_path / "openai.jsonl", [])
    code, ans = _ask(
        cli, monkeypatch, "reviews", "--provider", "openai", "--known", "-", stdin=openai_known(log)
    )
    assert code == 0 and ans["go"] and ans["account"] == "OpenAI credit" and ans["name"] == "openai"
    accounts = store.load(ws)["accounts"]
    a = accounts[0]
    assert a["type"] == "api-key" and a["provider"] == "openai" and a["order"] == 1
    assert a["rule"]["limits"] == [{"value": 100, "unit": "$", "period": "month", "since": RESET}]
    assert a["rule"]["for"] == ["reviews"] and a["source"]["unnamed"] is True
    assert [r["what"] for r in store.history(ws)] == ["account found"]
    # the person changes it; asking again with the skill's list never puts the skill's rule back
    assert cli("limit", "OpenAI", "$50", "--period", "month", "--by", "human:owner")[0] == 0
    _ask(cli, monkeypatch, "reviews", "--provider", "openai", "--known", "-", stdin=openai_known(log))
    a = store.load(ws)["accounts"][0]
    assert a["rule"]["limits"][0]["value"] == 50 and len(store.load(ws)["accounts"]) == 1
    assert a["rule"]["limits"][0]["since"] == RESET  # a new number keeps the reset day


def test_openai_goes_first_even_when_claude_was_listed_before(cli, ws, tmp_path, monkeypatch, no_switcher):
    log = _log(tmp_path / "claude.jsonl", [])
    _ask(cli, monkeypatch, "reviews", "--provider", "anthropic", "--known", "-", stdin=claude_known(log))
    _ask(cli, monkeypatch, "reviews", "--provider", "openai", "--known", "-", stdin=openai_known(log))
    labels = [a["label"] for a in store.load(ws)["accounts"]]
    assert labels == ["OpenAI credit", "Claude API credit (main)", "Claude API credit (second)"]
    # a Claude API skill is answered with a Claude API credit and the name it already uses
    _, ans = _ask(cli, monkeypatch, "reviews", "--provider", "anthropic")
    assert (
        ans["account"] == "Claude API credit (main)"
        and ans["name"] == "main"
        and ans["provider"] == "anthropic"
    )
    # a subagent asking for Reviews without a provider is pointed at the first credit: OpenAI
    _, ans = _ask(cli, monkeypatch, "reviews")
    assert ans["name"] == "openai"


def test_spend_counts_from_the_reset_day_and_refuses_at_the_limit(ws, tmp_path):
    log = _log(
        tmp_path / "openai.jsonl",
        [
            {"t": "2026-11-15 13:00:00", "usd": 60},  # before the reset: does not count
            {"t": "2026-11-18 10:00:00", "usd": 30.5},
        ],
    )
    known = [store.check_known(k) for k in openai_known(log)]
    ans = asking.ask(ws, "reviews", "openai", known=known, at=AT)
    assert ans == {
        "go": True,
        "account": "OpenAI credit",
        "provider": "openai",
        "name": "openai",
        "left": 69.5,
    }
    _log(tmp_path / "openai.jsonl", [{"t": "2026-11-18 10:00:00", "usd": 100.2}])
    ans = asking.ask(ws, "reviews", "openai", at=AT)
    assert ans["go"] is False and "OpenAI credit reached $100 (month)" in ans["why"]
    # it starts again a month after the reset, at the reset's day and hour on this computer's clock (#2723: the
    # 17th 00:00 UTC is the 16th in zones west of UTC)
    nxt, reset = store.to_time(ans["until"]).astimezone(), store.to_time(RESET).astimezone()
    assert (nxt.month, nxt.day, nxt.hour) == (reset.month + 1, reset.day, reset.hour)
    assert set(ans) == {"go", "why", "until"} and len(ans["why"]) <= 200


def test_a_refusal_through_the_cli_is_exit_3_with_plain_words(cli, ws, tmp_path, monkeypatch, no_switcher):
    log = _log(tmp_path / "openai.jsonl", [{"t": datetime.now(UTC).isoformat(), "usd": 9}])
    known = openai_known(log, limit=5)
    known[0]["since"] = None
    code, ans = _ask(cli, monkeypatch, "Reviews", "--provider", "openai", "--known", "-", stdin=known)
    assert code == 3 and ans["go"] is False and ans["why"].startswith("No room for Reviews")
    code, out, _ = cli("ask", "reviews", "--provider", "openai")
    assert code == 3 and out.startswith("No room for Reviews")


def test_the_named_credit_is_checked_and_another_is_never_picked_for_it(ws, tmp_path):
    log = _log(tmp_path / "claude.jsonl", [{"t": "2026-11-18T10:00:00Z", "account": "second", "usd": 100}])
    known = [store.check_known(k) for k in claude_known(log)]
    asking.ask(ws, "reviews", "anthropic", known=known, at=AT)
    assert asking.ask(ws, "reviews", "anthropic", name="main", at=AT)["name"] == "main"
    ans = asking.ask(ws, "reviews", "anthropic", name="second", at=AT)
    assert ans["go"] is False and "second" in ans["why"]


def test_off_or_other_kinds_are_not_answers(ws, tmp_path, no_switcher):
    log = _log(tmp_path / "openai.jsonl", [])
    known = [store.check_known(k) for k in openai_known(log)]
    asking.ask(ws, "reviews", "openai", known=known, at=AT)
    assert asking.ask(ws, "code", "openai", at=AT) == {"go": True}  # not allowed for Code: nothing set for it
    with store.change(ws) as (accounts, rows):
        store.set_on(accounts[0], rows, "human:owner", False)
    # a subagent asking for Reviews skips the off credit (nothing else set: do as today) ...
    assert asking.ask(ws, "reviews", at=AT) == {"go": True}
    # ... but the credit skill that would spend on it is refused (ORCH-627)
    ans = asking.ask(ws, "reviews", "openai", at=AT)
    assert ans == {"go": False, "why": "OpenAI credit is switched off. Turn it on on the Usage page."}


def test_a_whole_kind_without_room_waits_on_home_and_clears(ws, tmp_path, monkeypatch, no_switcher):
    monkeypatch.setenv("ORCH_TICKET", "t_cccccc")
    path = tmp_path / "openai.jsonl"
    log = _log(path, [{"t": "2026-11-18T10:00:00Z", "usd": 100}])
    known = [store.check_known(k) for k in openai_known(log)]
    asking.ask(
        ws, "reviews", "openai", known=known, at=AT
    )  # a skill's refusal: only that provider, no Home row
    assert routing.needs_rows(ws) == []
    ans = asking.ask(ws, "reviews", at=AT)  # a subagent for Reviews: nothing allowed for Reviews has room
    assert ans["go"] is False
    rows = routing.needs_rows(ws)
    assert [r["id"] for r in rows] == ["usage:no-room-reviews"] and "1 ticket waits" in rows[0]["text"]
    assert any(r["what"] == "warning: work for Reviews waits" for r in store.history(ws))
    _log(path, [])
    assert asking.ask(ws, "reviews", at=AT)["go"] is True
    assert routing.needs_rows(ws) == []
    assert store.history(ws)[0]["what"] == "room again for Reviews"


def test_a_subagent_on_the_subscription_is_answered_without_switching(cli, ws, monkeypatch, fake_switcher):
    jrun(cli, "list")  # Usage finds the three subscriptions; the first is in use (97% of 5 hours)
    code, ans = _ask(cli, monkeypatch, "helpers")
    assert code == 0 and ans["go"] and "account" in ans and "provider" not in ans
    assert fake_switcher.calls() and all(c == "list --json" for c in fake_switcher.calls())


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "main", "label": "me@example.test", "log": "x"},
        {"name": "main", "label": "sk-abc", "log": "x"},
        {"name": "main", "label": "A" * 40, "log": "x"},
        {"name": "bad name", "label": "ok", "log": "x"},
        {"name": "sk-short", "label": "ok", "log": "x"},
        {"name": "main", "label": "ok"},
        {"name": "main", "label": "ok", "log": "x", "limit": -1},
        {"name": "main", "label": "ok", "log": "x", "for": ["everything"]},
    ],
)
def test_known_credits_that_look_wrong_are_refused(cli, ws, monkeypatch, bad):
    code, ans = _ask(cli, monkeypatch, "reviews", "--provider", "openai", "--known", "-", stdin=[bad])
    assert code == 2 and "error" in ans and not (store.usage_dir(ws) / "accounts.json").exists()


def test_ask_refuses_unknown_kinds_and_providers(cli, ws, monkeypatch):
    code, ans = _ask(cli, monkeypatch, "everything")
    assert code == 2 and "kind of work" in ans["error"]
    code, ans = _ask(cli, monkeypatch, "reviews", "--provider", "gemini")
    assert code == 2 and "Anthropic" in ans["error"]


def test_monthly_reset_day_through_the_limit_command(cli, ws, tmp_path, monkeypatch, no_switcher):
    log = _log(tmp_path / "openai.jsonl", [])
    known = openai_known(log)
    known[0]["since"] = None
    _ask(cli, monkeypatch, "reviews", "--provider", "openai", "--known", "-", stdin=known)
    code, d = jrun(
        cli, "limit", "OpenAI", "$100", "--period", "month", "--resets", "2026-11-17", "--by", "human:owner"
    )
    assert code == 0 and store.to_time(d["account"]["rule"]["limits"][0]["since"]).astimezone().day == 17
    assert store.history(ws)[0]["what"] == "month starts again on day 17"
    m = page.build(usage_cli.gather(ws), ws)
    bar = m["accounts"][0]["bars"][0]
    assert (
        bar["unit"] == "$" and bar["limit"] == 100 and store.to_time(bar["resets_at"]).astimezone().day == 17
    )
    assert m["accounts"][0]["for"] == ["reviews"]


def test_month_window_runs_from_the_reset_day():
    lim = {"since": "2026-11-16T23:00:00Z"}
    start, nxt = store.month_window(lim, datetime(2026, 12, 20, tzinfo=UTC))
    assert start.astimezone(UTC) <= datetime(2026, 12, 20, tzinfo=UTC) < nxt.astimezone(UTC)
    assert (nxt - start).days in (28, 29, 30, 31)
    early, _ = store.month_window(lim, datetime(2026, 11, 1, tzinfo=UTC))  # before the reset: nothing counts
    assert early.astimezone(UTC) == datetime(2026, 11, 16, 23, tzinfo=UTC)


def test_spend_log_counts_unnamed_lines_and_local_times(tmp_path):
    log = _log(
        tmp_path / "s.jsonl",
        [
            {"t": "2026-11-18 10:00:00", "usd": 1},
            {"t": "2026-11-18 10:00:00", "account": "main", "usd": 2},
            {"t": "2026-11-18 10:00:00", "account": "second", "usd": 4},
        ],
    )
    assert spend_log.read({"path": log, "name": "main"}, None).spent == 2
    assert spend_log.read({"path": log, "name": "main", "unnamed": True}, None).spent == 3
    local = datetime(2026, 11, 18, 10, 0).astimezone().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert spend_log.read({"path": log, "name": "main"}, None).as_of == local


def test_month_window_keeps_the_local_reset_hour_over_summer_time(monkeypatch):
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        lim = {"since": "2026-01-17T05:00:00Z"}  # 17 Jan 00:00 in New York (winter)
        start, nxt = store.month_window(lim, datetime(2026, 7, 20, tzinfo=UTC))
        assert (start.month, start.day, start.hour) == (7, 17, 0) and (nxt.month, nxt.day, nxt.hour) == (
            8,
            17,
            0,
        )
    finally:
        monkeypatch.undo()
        time.tzset()


# ORCH-627: a credit at 0, switched off, past its end or removed is refused before the call; one with money left is
# answered as before. Every case runs on the fixed clock AT.


def _one_credit(ws, tmp_path, rows=(), **fields):
    """The OpenAI credit listed by its skill, then `fields` set on the account as the person would."""
    log = _log(tmp_path / "openai.jsonl", list(rows))
    known = [store.check_known(k) for k in openai_known(log)]
    asking.ask(ws, "reviews", "openai", known=known, at=AT)
    with store.change(ws) as (accounts, _):
        accounts[0].update(fields)
    return log


def test_a_credit_with_money_left_is_answered_as_today(ws, tmp_path):
    _one_credit(ws, tmp_path, [{"t": "2026-11-18 10:00:00", "usd": 30.5}])
    before = asking.ask(ws, "reviews", "openai", at=AT)
    assert before == {
        "go": True,
        "account": "OpenAI credit",
        "provider": "openai",
        "name": "openai",
        "left": 69.5,
    }
    # the person set what is left after that spend: the answer is the same, left counted down from their figure
    with store.change(ws) as (accounts, _):
        accounts[0]["left"] = {"value": 91.2, "at": "2026-11-19T00:00:00Z"}
        accounts[0]["credit_ends"] = "2026-11-30T23:59:00Z"  # an end still ahead does not stop it
    ans = asking.ask(ws, "reviews", "openai", at=AT)
    assert ans == {**before, "left": 69.5}  # the tighter of $100 a month and 91.20 left
    with store.change(ws) as (accounts, _):
        accounts[0]["left"] = {"value": 12.0, "at": "2026-11-19T00:00:00Z"}
    assert asking.ask(ws, "reviews", "openai", at=AT) == {**before, "left": 12.0}


def test_a_credit_at_zero_is_refused(ws, tmp_path):
    _one_credit(ws, tmp_path, left={"value": 0, "at": "2026-11-18T18:00:00Z"})
    ans = asking.ask(ws, "reviews", "openai", at=AT)
    assert ans == {"go": False, "why": "OpenAI credit has nothing left. Set what is left on the Usage page."}
    assert asking.ask(ws, "reviews", "openai", name="openai", at=AT)["go"] is False
    # a kind ask is refused too: no credit for Reviews has money
    assert asking.ask(ws, "reviews", at=AT)["go"] is False


def test_a_credit_counted_down_to_zero_is_refused(ws, tmp_path):
    rows = [
        # UTC times: a local '2026-11-19 10:00' is still the 18th in UTC east of +10 (#2723)
        {
            "t": "2026-11-18T09:00:00Z",
            "usd": 50,
        },  # before the person set what is left: already in their figure
        {"t": "2026-11-19T10:00:00Z", "usd": 4.0},
        {"t": "2026-11-20T11:00:00Z", "usd": 1.0},
    ]
    _one_credit(ws, tmp_path, rows, left={"value": 5, "at": "2026-11-19T00:00:00Z"})
    assert (
        asking.left_now(ws, store.load(ws)["accounts"][0], AT) == 0.0
    )  # 5 - 4 - 1; the $50 before does not count
    assert asking.ask(ws, "reviews", "openai", at=AT)["go"] is False


def test_a_credit_past_its_end_is_refused_with_a_fixed_clock(ws, tmp_path):
    _one_credit(ws, tmp_path, credit_ends="2026-11-20T12:00:00Z")
    a = store.load(ws)["accounts"][0]
    assert asking.stopped(ws, a, datetime(2026, 11, 20, 11, 59, tzinfo=UTC)) is None  # a minute before: goes
    ans = asking.ask(ws, "reviews", "openai", at=AT)  # AT is the end itself
    assert ans["go"] is False and ans["why"].startswith("OpenAI credit ended on ")
    later = datetime(2026, 12, 1, tzinfo=UTC)
    assert asking.ask(ws, "reviews", "openai", at=later)["go"] is False


def test_a_removed_credit_is_refused(ws, tmp_path):
    _one_credit(ws, tmp_path, removed=True)
    ans = asking.ask(ws, "reviews", "openai", at=AT)
    assert ans == {"go": False, "why": "OpenAI credit was removed. Bring it back on the Usage page."}


def test_a_stopped_credit_hands_over_to_the_next_with_room(ws, tmp_path):
    log = _log(tmp_path / "claude.jsonl", [])
    known = [store.check_known(k) for k in claude_known(log)]
    asking.ask(ws, "reviews", "anthropic", known=known, at=AT)
    with store.change(ws) as (accounts, _):
        accounts[0]["left"] = {"value": 0, "at": "2026-11-18T18:00:00Z"}  # main: nothing left
    ans = asking.ask(ws, "reviews", "anthropic", at=AT)
    assert ans["go"] is True and ans["name"] == "second"
    # the person names the stopped one: it is refused, the other is never picked for it
    ans = asking.ask(ws, "reviews", "anthropic", name="main", at=AT)
    assert ans["go"] is False and "nothing left" in ans["why"]
    with store.change(ws) as (accounts, rows):
        store.set_on(accounts[1], rows, "human:owner", False)
    ans = asking.ask(ws, "reviews", "anthropic", at=AT)
    assert ans == {
        "go": False,
        "why": "Claude API credit (main) has nothing left. Set what is left on the Usage page.",
    }


def test_a_stopped_credit_through_the_cli_is_exit_3(cli, ws, tmp_path, monkeypatch, no_switcher):
    _one_credit(ws, tmp_path, left={"value": 0, "at": "2026-11-18T18:00:00Z"})
    code, ans = _ask(cli, monkeypatch, "reviews", "--provider", "openai")
    assert code == 3 and ans["go"] is False and "nothing left" in ans["why"]


def test_the_real_setters_refuse_and_bring_back(ws, tmp_path):
    """With ORCH-626's commands: reported spend counts down to 0, an end stops it, remove refuses and the skill's
    own list never brings it back; restore does."""
    from orch_usage import left

    log = _one_credit(ws, tmp_path)
    with store.change(ws) as (accounts, rows):
        store.set_left(accounts[0], rows, "human:owner", 2.0, at="2026-11-19T00:00:00Z")
    a = store.load(ws)["accounts"][0]
    left.record(ws, a, 1.5, "agent:skill", at="2026-11-19T10:00:00Z")
    assert asking.ask(ws, "reviews", "openai", at=AT)["left"] == 0.5
    left.record(ws, a, 0.5, "agent:skill", at="2026-11-19T11:00:00Z")
    assert "nothing left" in asking.ask(ws, "reviews", "openai", at=AT)["why"]
    with store.change(ws) as (accounts, rows):
        store.set_left(accounts[0], rows, "human:owner", 50.0, at="2026-11-20T00:00:00Z")
        store.set_credit_end(accounts[0], rows, "human:owner", "2026-11-20T06:00:00Z")
    assert asking.ask(ws, "reviews", "openai", at=AT)["why"].startswith("OpenAI credit ended on ")
    with store.change(ws) as (accounts, rows):
        store.set_credit_end(accounts[0], rows, "human:owner", None)
        store.remove_account(accounts, accounts[0], rows, "human:owner")
    known = [store.check_known(k) for k in openai_known(log)]
    ans = asking.ask(ws, "reviews", "openai", known=known, at=AT)
    assert ans["go"] is False and "was removed" in ans["why"]
    with store.change(ws) as (accounts, rows):
        store.restore_account(accounts[0], rows, "human:owner")
    assert asking.ask(ws, "reviews", "openai", at=AT)["go"] is True


@pytest.fixture
def west_computer_tokyo_workspace(ws, monkeypatch):
    """The computer in Los Angeles, the workspace set to Tokyo (`[workspace] tz`)."""
    import time

    (ws / ".orch" / "config.toml").write_text('[workspace]\ntz = "Asia/Tokyo"\n', encoding="utf-8")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield ws
    monkeypatch.undo()
    time.tzset()


def test_times_in_words_are_on_the_workspace_clock(west_computer_tokyo_workspace, tmp_path, cli, no_switcher):
    """#2692: 'ended on', the credit end and 'set on' in `usage list`, and the history line of a rule that ended
    during a helper start used the computer's zone, not the workspace's."""
    ws = west_computer_tokyo_workspace
    _one_credit(
        ws,
        tmp_path,
        credit_ends="2026-11-19T16:30:00Z",  # 20 Nov 01:30 in Tokyo, 19 Nov 08:30 in Los Angeles
        left={"value": 5, "at": "2026-11-19T20:00:00Z"},  # 20 Nov in Tokyo, 19 Nov in Los Angeles
    )
    assert asking.ask(ws, "reviews", "openai", at=AT)["why"] == "OpenAI credit ended on Fri 20 Nov 01:30."
    out = cli("list")[1]
    assert "ended 2026-11-20 01:30 JST" in out and "set on 2026-11-20" in out
    with store.change(ws) as (accounts, _):
        accounts[0]["rule"]["ends"] = "2026-11-20T03:00:00Z"  # 12:00 in Tokyo
    routing.decide(ws, {"ticket": "t_aaaaaa", "agent": "x", "agents": ["x"]}, at=AT)
    assert any(r["what"] == "rule ended 20 Nov 2026, 12:00 JST" for r in store.history(ws))
