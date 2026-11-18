"""Early switching with a faked account switcher and a fake clock. No test may reach the real switcher: every test
names a fake (or a missing one) through ORCH_USAGE_SWITCHER."""

import json
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import jrun, switcher_data

from orch_usage import service, store, switching
from orch_usage.readers import SubscriptionUse

T0 = datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def never_the_real_switcher(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_USAGE_SWITCHER", str(tmp_path / "no-switcher-here"))


@pytest.fixture
def switcher(tmp_path, monkeypatch):
    """A fake `cswap` that lists from a file and really moves `active` on `switch N` (and logs every call)."""
    d = tmp_path / "bin"
    d.mkdir()
    answer = tmp_path / "switcher.json"
    calls = tmp_path / "switcher-calls.txt"
    fail = tmp_path / "switcher-fails"
    answer.write_text(json.dumps(switcher_data()), encoding="utf-8")
    exe = d / "cswap"
    exe.write_text(
        textwrap.dedent(f"""\
            #!{sys.executable}
            import json, os, sys
            a = sys.argv[1:]
            open({str(calls)!r}, "a").write(" ".join(a) + "\\n")
            if a == ["list", "--json"]:
                sys.stdout.write(open({str(answer)!r}).read()); sys.exit(0)
            if len(a) == 2 and a[0] in ("enable", "switch"):
                if os.path.exists({str(fail)!r}):
                    sys.exit(1)
                if a[0] == "switch":
                    d = json.load(open({str(answer)!r}))
                    n = int(a[1])
                    d["activeAccountNumber"] = n
                    for x in d["accounts"]:
                        x["active"] = x["number"] == n
                    json.dump(d, open({str(answer)!r}, "w"))
                sys.exit(0)
            sys.exit(3)
            """),
        encoding="utf-8",
    )
    exe.chmod(0o755)
    monkeypatch.setenv("ORCH_USAGE_SWITCHER", str(exe))

    class Fake:
        @staticmethod
        def use(active=None, **acc):
            """Set use per account: first=(5h, week), second=..., third=...; keeps the active one unless given."""
            cur = json.loads(answer.read_text())
            act = active if active is not None else cur["activeAccountNumber"]
            data = switcher_data(active=act, **acc)
            answer.write_text(json.dumps(data), encoding="utf-8")

        @staticmethod
        def reset_5h(n, at="2026-11-16T23:00:00+00:00"):
            cur = json.loads(answer.read_text())
            for x in cur["accounts"]:
                if x["number"] == n:
                    x["usage"]["fiveHour"]["resetsAt"] = at
            answer.write_text(json.dumps(cur), encoding="utf-8")

        @staticmethod
        def active():
            return json.loads(answer.read_text())["activeAccountNumber"]

        @staticmethod
        def calls():
            return calls.read_text().splitlines() if calls.exists() else []

        @staticmethod
        def changes():
            return [c for c in Fake.calls() if not c.startswith("list")]

        @staticmethod
        def failing(on=True):
            fail.write_text("x") if on else fail.unlink(missing_ok=True)

    return Fake


def seed(cli):
    """The owner's rules by label: first 95 % / 5 h and 100 % / week, then TEAMCO 92 / 70, then second 92 / 100."""
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


def usage_rows(ws, since=None):
    return [h for h in store.history(ws)[::-1] if h["who"] == "usage" and h["what"] != "account found"]


def at(seconds):
    return T0 + timedelta(seconds=seconds)


# ---------------------------------------------------------------- show only


def test_switching_is_off_until_turned_on_and_only_says_what_it_would_do(cli, switcher, ws):
    seed(cli)  # first is active with 5 hours at 97 %: over its 95 % limit
    r = switching.look(ws, at(0))
    assert r["did"] == "would switch" and (r["active"], r["target"]) == ("first", "TEAMCO")
    switching.look(ws, at(30))  # the same choice is written once, not every 30 seconds
    assert switcher.changes() == [] and switcher.active() == 1
    rows = usage_rows(ws)
    assert [(h["what"], h["before"], h["after"]) for h in rows] == [
        ("would switch to TEAMCO", "first", "TEAMCO")
    ]
    assert "5 hours 97% of 95%" in rows[0]["why"]


def test_without_the_switcher_it_shows_and_warns_only(cli, ws):
    code, d = jrun(cli, "run", "--once")
    assert code == 0 and d["switcher"] is False and d["did"] == "nothing"
    code, out, _ = cli("run", "--once")
    assert "does not switch" in out
    code, d = jrun(cli, "switching", "on", "--by", "human:owner")
    assert code == 0 and d["switching"] is True and "does not switch" in d["next"]
    code, d = jrun(cli, "status")
    assert code == 1 and d["switcher"] is False and d["running"] is False


def test_switching_on_and_off_is_in_the_history(cli, ws):
    assert jrun(cli, "switching", "on", "--by", "human:owner")[1]["changed"] is True
    assert jrun(cli, "switching", "on", "--by", "human:owner")[1]["changed"] is False
    assert jrun(cli, "switching", "off", "--by", "human:owner")[1]["changed"] is True
    rows = store.history(ws)
    assert [(h["what"], h["who"]) for h in rows] == [
        ("switching turned off", "human:owner"),
        ("switching turned on", "human:owner"),
    ]
    code, out, _ = cli("history")
    assert code == 0 and "Usage: switching turned on" in out


# ---------------------------------------------------------------- switching


def test_moves_to_the_first_account_under_its_limits(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    r = switching.look(ws, at(0))
    assert r["did"] == "switched" and switcher.active() == 3  # TEAMCO is slot 3, second in the owner's order
    assert switcher.changes() == ["enable 3", "switch 3"]
    h = usage_rows(ws)[-1]
    assert (h["what"], h["before"], h["after"], h["label"]) == (
        "switched to TEAMCO",
        "first",
        "TEAMCO",
        "TEAMCO",
    )
    assert switching.look(ws, at(30))["did"] == "stay"
    assert switcher.changes() == ["enable 3", "switch 3"]


def test_switches_early_when_the_limit_would_come_within_ten_minutes(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(80.0, 50.0))
    assert switching.look(ws, at(0))["did"] == "stay"  # one sample: no pace yet, 80 % is under 95 %
    switcher.use(first=(81.0, 50.0))
    assert switching.look(ws, at(150))["did"] == "stay"  # under five minutes apart: still no pace
    switcher.use(first=(90.0, 50.0))
    r = switching.look(ws, at(300))  # 2 % a minute: 90 + 20 reaches 95 within 10 minutes
    assert r["did"] == "switched" and r["pace"]["5h"] == pytest.approx(2.0)
    assert switcher.active() == 3
    assert "reached in under 10 min" in usage_rows(ws)[-1]["why"]


def test_one_refresh_jump_is_not_read_as_a_burst(cli, switcher, ws):
    """The switcher refreshes now and then: a jump seen over a short look must not switch (ORCH-93 finding 8)."""
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(60.0, 50.0))
    switching.look(ws, at(0))
    switcher.use(first=(75.0, 50.0))  # one refresh: 15 % appears at once
    for s in (30, 60, 120, 240):
        assert switching.look(ws, at(s))["did"] == "stay"
    assert switcher.changes() == []


def test_the_reason_names_the_account_that_was_left(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(97.0, 50.0))
    assert switching.look(ws, at(0))["did"] == "switched"
    row = usage_rows(ws)[-1]
    assert row["after"] == "TEAMCO" and row["why"].startswith("first: 5 hours 97%")


def test_slow_pace_stays(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    for i, pct in enumerate((80.0, 80.5, 81.0)):  # 1 % a minute: 81 + 10 stays under 95
        switcher.use(first=(pct, 50.0))
        assert switching.look(ws, at(30 * i))["did"] == "stay"
    assert switcher.changes() == []


def test_an_account_left_early_is_not_taken_back_until_its_use_drops(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(80.0, 50.0))
    switching.look(ws, at(0))
    switcher.use(first=(90.0, 50.0))
    assert switching.look(ws, at(300))["did"] == "switched"  # 2 % a minute
    for s in (
        330,
        360,
        450,
        600,
    ):  # on TEAMCO: its use looks flat for a few minutes (the switcher reads now and
        assert (
            switching.look(ws, at(s))["did"] == "stay"
        )  # then), first still 84 %: the remembered pace counts
    assert switcher.active() == 3
    switcher.use(first=(0.0, 51.0))  # first's 5 hours started again
    switcher.reset_5h(1)
    r = switching.look(ws, at(630))
    assert r["did"] == "switched" and switcher.active() == 1
    assert [h["after"] for h in usage_rows(ws)] == ["TEAMCO", "first"]


def test_when_the_work_slows_down_the_first_account_is_taken_back(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(80.0, 50.0))
    switching.look(ws, at(0))
    switcher.use(first=(90.0, 50.0))
    assert switching.look(ws, at(300))["did"] == "switched"
    for s in range(330, 630, 30):  # TEAMCO's use stays flat for five minutes: the work slowed down
        switching.look(ws, at(s))
    assert switcher.active() == 3
    assert switching.look(ws, at(630))["did"] == "switched" and switcher.active() == 1


def test_weekly_limit_counts_too_and_an_account_turned_off_is_skipped(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    jrun(cli, "off", "second", "--by", "human:owner")
    switcher.use(first=(97.0, 80.0), third=(10.0, 70.0))  # first over 5 hours, TEAMCO at its 70 % week
    r = switching.look(ws, at(0))
    assert r["all_at_limit"] is True and switcher.changes() == []  # second is off: nowhere to go


def test_every_account_at_its_limit_warns_once_and_stays(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(97.0, 80.0), second=(93.0, 40.0), third=(95.0, 50.0))
    r = switching.look(ws, at(0))
    assert r["all_at_limit"] is True and r["did"] == "stay" and switcher.changes() == []
    switching.look(ws, at(30))
    warn = [h for h in usage_rows(ws) if h["what"].startswith("warning")]
    assert len(warn) == 1 and "first: 5 hours 97%" in warn[0]["after"] and "@" not in json.dumps(warn)
    switcher.use(first=(97.0, 80.0), second=(10.0, 40.0), third=(95.0, 50.0))  # second has room again
    assert switching.look(ws, at(60))["did"] == "switched" and switcher.active() == 2
    switcher.use(first=(97.0, 80.0), second=(99.0, 40.0), third=(95.0, 50.0))
    switching.look(ws, at(90))  # all at a limit again: a second warning
    assert len([h for h in usage_rows(ws) if h["what"].startswith("warning")]) == 2


def _warn_ids(ws, t):
    return [r["id"] for r in switching.needs_rows(ws, at(t)) if r["kind"].startswith("usage:all-at-limit")]


def test_every_account_at_its_limit_reaches_the_person_once_as_one_row(cli, switcher, ws):
    """ORCH-644: one row in `orch usage needs` with a stable id while it lasts, not one per look."""
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(97.0, 80.0), second=(93.0, 40.0), third=(95.0, 50.0))
    switching.look(ws, at(0))
    first = _warn_ids(ws, 0)
    assert first == [f"usage:all-at-limit:{switching._iso(at(0))}"]
    for n in range(1, 6):  # five more looks: the same one row
        switching.look(ws, at(30 * n))
        assert _warn_ids(ws, 30 * n) == first
    (row,) = [r for r in switching.needs_rows(ws, at(150)) if r["id"] == first[0]]
    assert row["source"] == "usage" and row["ticket"] is None and row["tone"] == "bad"
    assert (
        row["actions"][0]["verb"] == "seen" and row["actions"][0]["target"] == f"all-at-limit:{row['since']}"
    )
    # a look that stopped long ago is not shown: it may be out of date (the command reads the clock: T0 is old)
    assert _warn_ids(ws, 150 + 60 * switching.FRESH_MINUTES) == []


def test_a_warning_comes_back_only_after_it_cleared_and_started_again(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    full = {"first": (97.0, 80.0), "second": (93.0, 40.0), "third": (95.0, 50.0)}
    room = {"first": (97.0, 80.0), "second": (10.0, 40.0), "third": (95.0, 50.0)}
    switcher.use(**full)
    switching.look(ws, at(0))
    first = _warn_ids(ws, 0)
    switcher.use(active=switcher.active(), **room)  # a flicker: room for one look, then full again
    switching.look(ws, at(30))
    assert _warn_ids(ws, 30) == []  # gone while it is gone
    switcher.use(active=switcher.active(), **full)
    switching.look(ws, at(60))
    assert _warn_ids(ws, 60) == first  # back within 10 minutes: the same warning, not a new card
    switcher.use(active=switcher.active(), **room)
    switching.look(ws, at(90))
    switching.look(ws, at(90 + 60 * switching.CLEAR_MINUTES))  # gone for 10 minutes: cleared
    switcher.use(active=switcher.active(), **full)
    t = 120 + 60 * switching.CLEAR_MINUTES
    switching.look(ws, at(t))
    again = _warn_ids(ws, t)
    assert again and again != first  # it came back: a new row the person is told about once more


def test_got_it_hides_a_warning_until_it_comes_back(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(97.0, 80.0), second=(93.0, 40.0), third=(95.0, 50.0))
    switching.look(ws, at(0))
    (row,) = [r for r in switching.needs_rows(ws, at(0)) if r["kind"] == "usage:all-at-limit"]
    assert jrun(cli, "act", "seen", "all-at-limit:2020-01-01T00:00:00Z", "--by", "human:owner")[0] != 0
    code, out = jrun(cli, "act", "seen", row["actions"][0]["target"], "--by", "human:owner")
    assert code == 0 and out["changed"] is True, out
    switching.look(ws, at(30))
    assert _warn_ids(ws, 30) == []
    assert any(h["what"].startswith("warning seen") for h in store.history(ws))
    assert jrun(cli, "act", "seen", "bogus:x", "--by", "human:owner")[0] != 0


def test_a_failed_switch_reaches_the_person_once_and_clears_after_a_switch(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.failing()
    switching.look(ws, at(0))
    switching.look(ws, at(30))
    rows = [r for r in switching.needs_rows(ws, at(30)) if r["kind"] == "usage:switch-failed"]
    assert len(rows) == 1 and "TEAMCO" in rows[0]["title"] and rows[0]["tone"] == "warn"
    assert rows[0]["id"] == f"usage:switch-failed:{switching._iso(at(0))}"
    switching.look(ws, at(601))  # tried again, failed again: still the same one row
    assert [r["id"] for r in switching.needs_rows(ws, at(601)) if r["kind"] == "usage:switch-failed"] == [
        rows[0]["id"]
    ]
    switcher.failing(False)
    switching.look(ws, at(1300))
    assert [r for r in switching.needs_rows(ws, at(1300)) if r["kind"] == "usage:switch-failed"] == []


def test_near_every_limit_it_still_leaves_an_account_that_is_over(cli, switcher, ws):
    """No account is safe for 10 minutes, but the active one is over its limit and another still has room."""
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.use(first=(90.0, 50.0), second=(91.0, 40.0), third=(91.0, 50.0))
    switching.look(ws, at(0))
    switcher.use(first=(96.0, 50.0), second=(91.0, 40.0), third=(91.0, 50.0))
    r = switching.look(ws, at(300))  # 1.2 % a minute: nobody lasts 10 minutes; first is over 95 %
    assert r["all_at_limit"] is True and r["did"] == "switched" and switcher.active() == 3


def test_a_failed_switch_is_written_and_tried_again_after_ten_minutes(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switcher.failing()
    assert switching.look(ws, at(0))["did"] == "switch failed"
    assert switching.look(ws, at(30))["did"] == "waiting to try again"
    assert [h["what"] for h in usage_rows(ws)] == ["could not switch to TEAMCO"]
    switcher.failing(False)
    assert switching.look(ws, at(601))["did"] == "switched"


def test_a_second_switcher_is_noted_tried_once_more_then_usage_stops_and_asks(cli, switcher, ws):
    """ORCH-591 / ORCH-612: another program switched back after every Usage switch (12 switches in 20 minutes).
    Usage writes the outside switch, switches away once more, then stops and asks once which rule should win."""
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    assert switching.look(ws, at(0))["did"] == "switched"
    assert switching.needs_rows(ws) == []
    switcher.use(active=1)  # the other program switches back to the first account
    assert switching.look(ws, at(120))["did"] == "switched"  # the one more try
    switcher.use(active=1)  # and again
    for n in range(2, 10):  # every later look stays: no fight
        assert switching.look(ws, at(120 * n))["did"] == "held"
    assert switcher.active() == 1
    assert [c for c in switcher.changes() if c.startswith("switch")] == ["switch 3", "switch 3"]
    assert [h["what"] for h in usage_rows(ws)] == [
        "switched to TEAMCO",
        "another program switched to first",
        "switched to TEAMCO",
        "stopped switching: another program keeps switching back to first",
    ]
    rows = switching.needs_rows(ws)
    assert len(rows) == 1  # asked once, not once per look
    r = rows[0]
    assert r["source"] == "usage" and r["tone"] == "needs-you" and "Which rule should win?" in r["text"]
    assert [(x["verb"], x["target"]) for x in r["actions"]] == [("switching", "on"), ("switching", "off")]
    code, out = jrun(cli, "needs")
    assert code == 0 and out == rows


def test_answer_usage_wins_switches_again_and_asks_again_only_after_a_new_fight(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switching.look(ws, at(0))
    for n in (1, 2):
        switcher.use(active=1)
        switching.look(ws, at(120 * n))
    assert switching.held(ws)
    code, out = jrun(cli, "act", "switching", "on", "--by", "human:owner")  # the button "Usage's limits win"
    assert code == 0 and out["changed"] is True
    assert switching.needs_rows(ws) == []
    assert switching.look(ws, at(400))["did"] == "switched"
    assert "switching again: Usage's limits win" in [h["what"] for h in store.history(ws)]
    switcher.use(active=1)  # the other program still runs: one more try, then ask again
    assert switching.look(ws, at(500))["did"] == "switched"
    switcher.use(active=1)
    assert switching.look(ws, at(600))["did"] == "held"
    assert len(switching.needs_rows(ws)) == 1


def test_answer_the_other_program_wins_turns_switching_off(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switching.look(ws, at(0))
    for n in (1, 2):
        switcher.use(active=1)
        switching.look(ws, at(120 * n))
    code, _ = jrun(cli, "act", "switching", "off", "--by", "human:owner")
    assert code == 0
    assert switching.needs_rows(ws) == []
    assert switching.look(ws, at(400))["did"] == "would switch"
    assert switcher.active() == 1


def test_a_held_account_is_let_go_when_there_is_nothing_to_fight_about(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switching.look(ws, at(0))
    for n in (1, 2):
        switcher.use(active=1)
        switching.look(ws, at(120 * n))
    assert switching.held(ws)
    switcher.use(active=1, first=(10, 10))  # first's use dropped (a reset): staying is right
    assert switching.look(ws, at(400))["did"] == "stay"
    assert switching.needs_rows(ws) == []


def test_without_a_second_switcher_nothing_is_noted(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    assert switching.look(ws, at(0))["did"] == "switched"
    for n in range(1, 5):
        assert switching.look(ws, at(60 * n))["did"] == "stay"
    assert [h["what"] for h in usage_rows(ws)] == ["switched to TEAMCO"]


def test_a_switch_that_did_not_change_the_account_in_use_is_not_written_as_done(
    cli, switcher, ws, monkeypatch
):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    monkeypatch.setattr(switching, "_stuck", lambda key, read=None: False)
    assert switching.look(ws, at(0))["did"] == "switch failed"
    assert [h["what"] for h in usage_rows(ws)] == ["could not switch to TEAMCO"]


def test_a_rule_that_ended_falls_back_before_choosing(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    jrun(cli, "limit", "first", "99%", "--period", "5h", "--end", "2099-01-01", "--by", "human:owner")
    assert switching.look(ws, at(0))["did"] == "stay"  # 97 % is under the temporary 99 %
    assert switching.look(ws, datetime(2099, 1, 2, tzinfo=UTC))["did"] == "switched"  # back to 95 %


def test_nothing_secret_is_written(cli, switcher, ws):
    seed(cli)
    jrun(cli, "switching", "on", "--by", "human:owner")
    switching.look(ws, at(0))
    d = ws / ".orch/addons/usage"
    text = "".join(p.read_text() for p in d.iterdir() if p.is_file())
    assert "@" not in text and "example.test" not in text


# ---------------------------------------------------------------- the loop


def test_loop_looks_every_30_seconds_and_stops_when_usage_is_turned_off(cli, switcher, ws):
    seed(cli)
    clock = iter(at(30 * i) for i in range(100))
    slept, on = [], iter([True, True, True, False])
    switching.run_forever(
        ws, clock=lambda: next(clock), sleep=slept.append, log=lambda m: None, active=lambda r: next(on)
    )
    assert slept == [30, 30, 30]
    assert (
        json.loads((ws / ".orch/addons/usage/switching.json").read_text())["last"]["at"]
        == "2026-11-16T18:01:00Z"
    )


def test_loop_reads_its_pace_from_config_and_survives_a_bad_look(cli, ws, monkeypatch):
    (ws / ".orch/config.toml").write_text("[usage]\nevery_seconds = 45\nahead_minutes = 20\n")
    assert switching.config(ws) == {"every_seconds": 45, "ahead_minutes": 20}

    def boom(root, at):
        raise OSError("disk")

    monkeypatch.setattr(switching, "look", boom)
    logs, slept, on = [], [], iter([True, True, False])
    switching.run_forever(
        ws, clock=lambda: T0, sleep=slept.append, log=logs.append, active=lambda r: next(on)
    )
    assert slept == [45, 45] and logs[0] == "skipped: OSError: disk"


def test_start_status_stop(ws, cli):
    pid = service.start(ws)
    try:
        assert service.running_pid(ws) == pid
        assert service.start(ws) == pid  # no second one
        code, d = jrun(cli, "status")
        assert code == 0 and d["running"] is True and d["pid"] == pid
    finally:
        assert service.stop(ws) == "stopped"
    for _ in range(30):
        if service.running_pid(ws) is None:
            break
        time.sleep(0.1)
    assert jrun(cli, "status")[0] == 1
    assert service.stop(ws) == "not running"


def _acc(label, order, h5=92, week=100):
    return {
        "id": f"a_{label}",
        "label": label,
        "type": "subscription",
        "on": True,
        "order": order,
        "source": {"reader": "cswap", "key": f"k_{label}"},
        "rule": {
            "limits": [
                {"value": h5, "unit": "%", "period": "5h"},
                {"value": week, "unit": "%", "period": "week"},
            ],
            "for": [],
            "ends": None,
        },
    }


def test_a_window_the_switcher_does_not_report_is_not_a_reached_limit():
    """Real switcher after a reset (ORCH-93 finding 9): no fiveHour block at all, week read fine."""
    from orch_usage.readers import Window

    use = SubscriptionUse(key="k_main", label="main", slot=2, active=True, windows={"week": Window(13.0)})
    c = switching.judge(_acc("main", 1), use, {}, 30)
    assert c.under and c.good, c.why
    ch = switching.choose([_acc("main", 1)], [use], {}, 30)
    assert ch.target is not None and ch.target.account["label"] == "main"
    assert not ch.all_at_limit


def test_a_window_reported_without_a_number_still_counts_as_reached():
    from orch_usage.readers import Window

    use = SubscriptionUse(
        key="k_main", label="main", slot=2, windows={"5h": Window(None), "week": Window(13.0)}
    )
    c = switching.judge(_acc("main", 1), use, {}, 30)
    assert not c.under and c.why == "5 hours use unknown"


def test_an_account_turned_off_in_the_switcher_is_never_a_target():
    from orch_usage.readers import Window

    off = SubscriptionUse(
        key="k_off", label="off", slot=3, disabled=True, windows={"5h": Window(0.0), "week": Window(10.0)}
    )
    main = SubscriptionUse(
        key="k_main", label="main", slot=2, active=True, windows={"5h": Window(96.0), "week": Window(50.0)}
    )
    ch = switching.choose([_acc("off", 1), _acc("main", 2)], [off, main], {}, 30)
    assert ch.target is None or ch.target.account["label"] != "off"
    assert switching.judge(_acc("off", 1), off, {}, 30).why == "turned off in the account switcher"


def test_reader_keeps_the_switchers_disabled_flag():
    from conftest import switcher_data

    from orch_usage.readers import cswap

    data = switcher_data()
    data["accounts"][1]["disabled"] = True
    assert [r.disabled for r in cswap.parse(data)] == [False, True, False]
