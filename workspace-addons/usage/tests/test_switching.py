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
