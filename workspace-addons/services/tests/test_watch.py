"""Health check, failing and the one question (`orch services check`), with the fake driver, a fake clock and a fake
orch CLI (no sleeping, no real ticket)."""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import jrun

from orch_services.watch import _lsof as REAL_LSOF
from orch_services.watch import listeners as REAL_LISTENERS  # the autouse fixture replaces it in every test

T0 = 1_800_000_000.0


@pytest.fixture
def clock(monkeypatch):
    from orch_services import watch

    now = {"t": T0}
    monkeypatch.setattr(watch, "clock", lambda: now["t"])
    return now


@pytest.fixture
def orch(ws, tmp_path, monkeypatch):
    """The fake orch CLI; DM1-12 is the ticket that made the service."""
    script = tmp_path / "orch"
    script.write_text(f"#!{sys.executable}\n" + Path(__file__).with_name("fake_orch.py").read_text())
    script.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(script))
    folder = ws / "fake-tickets"
    folder.mkdir()
    (folder / "t_abc123.json").write_text(
        json.dumps({"id": "t_abc123", "key": "DM1-12", "title": "Budget", "questions": [], "history": []})
    )

    class Fake:
        def ticket(self, ref="t_abc123"):
            for p in folder.glob("*.json"):
                t = json.loads(p.read_text())
                if ref in (t["id"], t["key"]):
                    return t
            raise KeyError(ref)

        def answer(self, ref, qid, text):
            t = self.ticket(ref)
            next(q for q in t["questions"] if q["id"] == qid)["answer"] = text
            (folder / f"{t['id']}.json").write_text(json.dumps(t))

        def calls(self):
            f = ws / "calls.jsonl"
            return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

        def asks(self):
            return [c for c in self.calls() if c["args"][0] == "ask" and "--take-back" not in c["args"]]

    return Fake()


def _add(cli, *extra, ticket=True):
    t = ("--ticket", "DM1-12") if ticket else ()
    code, out = jrun(
        cli, "add", "Budget guard", "--id", "budget", *t, *extra, "--start", "--", "python3", "-V"
    )
    assert code == 0, out


def _check(cli):
    code, out = jrun(cli, "check")
    assert code == 0, out
    return out["checked"][0]


def _crash(fake, sid="budget"):
    """The service died and the computer's service tool started it again by itself (launchd KeepAlive)."""
    fake.run_counts[sid] = fake.run_counts.get(sid, 1) + 1


def _state(ws, sid="budget"):
    return json.loads((ws / ".orch/addons/services/state" / f"{sid}.json").read_text(encoding="utf-8"))


def test_three_failures_in_ten_minutes_raise_exactly_one_question(cli, fake, ws, clock, orch):
    fake.run_counts["budget"] = 1
    _add(cli)
    assert fake.run_counts["budget"] == 1  # the start through orch is the baseline, not a failure
    for i in range(2):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        res = _check(cli)
        assert res["failing"] is False and not orch.asks()
    clock["t"] = T0 + 180
    _crash(fake)
    res = _check(cli)
    assert res["failing"] is True
    asks = orch.asks()
    assert len(asks) == 1 and asks[0]["by"] == "agent:services"
    # ORCH-614: an add-on kind keeps the answer with Services; a plain question would start a helper on the ticket
    assert asks[0]["args"][asks[0]["args"].index("--kind") + 1] == "services:health"
    q = orch.ticket()["questions"][0]
    assert (
        q["text"]
        == "Budget guard keeps stopping: it failed 3 times in the last 10 minutes. What it affects is not known."
        " Restart, Stop or Look into it?"
    )
    assert q["options"] == ["Restart", "Stop", "Look into it"] and q["recommended"] == "Restart"

    # a fourth failure: still one question
    clock["t"] = T0 + 240
    _crash(fake)
    _check(cli)
    assert len(orch.asks()) == 1 and len(orch.ticket()["questions"]) == 1

    # list --json shows it for the page
    _code, out = jrun(cli, "list")
    row = out["services"][0]
    assert row["state"] == "failing" and row["failing"] is True
    assert row["question"] == {
        "ticket": "DM1-12",
        "id": "q1",
        "title": "Budget guard keeps stopping",
        "text": "What it affects is not known. It failed 4 times in the last 10 minutes. Suggested: Restart.",
        "suggested": "Restart",
    }
    assert row["depends"] == [] and row["stale"] is False and row["recovered"] is None
    assert row["health"] == {"ok": True, "how": "process alive", "text": "Process alive"}


def test_failures_spread_over_more_than_ten_minutes_do_not_count(cli, fake, clock, orch):
    fake.run_counts["budget"] = 1
    _add(cli)
    for i in range(4):
        clock["t"] = T0 + 400 * (i + 1)  # one failure every 6 to 7 minutes: never 3 in 10 minutes
        _crash(fake)
        assert _check(cli)["failing"] is False
    assert not orch.asks()


def test_failed_health_checks_count_and_the_health_line_says_it(cli, fake, ws, clock, orch, monkeypatch):
    from orch_services import watch

    monkeypatch.setattr(watch, "port_answers", lambda port: False)
    _add(cli, "--port", "5173")
    for i in range(3):
        clock["t"] = T0 + 60 * (i + 1)
        res = _check(cli)
    assert res["health"] == {
        "ok": False,
        "how": "answers on its address",
        "text": "Alive, but does not answer on its address",
    }
    assert res["failing"] is True and len(orch.asks()) == 1
    _code, out = jrun(cli, "list")
    assert out["services"][0]["health"]["text"] == (
        "Alive, but does not answer on its address: it failed 3 times in the last 10 minutes"
    )


def test_healthy_ten_minutes_takes_the_question_back(cli, fake, clock, orch):
    fake.run_counts["budget"] = 1
    _add(cli)
    for i in range(3):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        _check(cli)
    assert len(orch.asks()) == 1
    clock["t"] = T0 + 240
    _check(cli)  # healthy from here
    clock["t"] = T0 + 240 + 599
    assert _check(cli)["failing"] is True
    clock["t"] = T0 + 240 + 600
    res = _check(cli)
    assert res["failing"] is False
    back = [c for c in orch.calls() if "--take-back" in c["args"]]
    assert len(back) == 1 and back[0]["args"][:2] == ["ask", "DM1-12"] and "q1" in back[0]["args"]
    assert orch.ticket()["questions"][0]["taken_back"]
    _code, out = jrun(cli, "list")
    assert out["services"][0]["state"] == "running" and out["services"][0]["question"] is None
    _check(cli)
    assert len([c for c in orch.calls() if "--take-back" in c["args"]]) == 1


def _make_failing(cli, fake, clock):
    fake.run_counts["budget"] = 1
    _add(cli)
    for i in range(3):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        _check(cli)


def test_answer_restart_restarts_once(cli, fake, ws, clock, orch):
    _make_failing(cli, fake, clock)
    orch.answer("DM1-12", "q1", "Restart")
    before = [c for c in fake.calls if c[0] == "restart"]
    clock["t"] = T0 + 300
    res = _check(cli)
    assert "Restarted Budget guard" in res["did"]
    clock["t"] = T0 + 360
    _check(cli)
    _check(cli)
    assert len([c for c in fake.calls if c[0] == "restart"]) == len(before) + 1
    assert res["failing"] is False and len(orch.asks()) == 1


def test_answer_stop_stops_once_and_look_into_it_changes_nothing(cli, fake, ws, clock, orch):
    _make_failing(cli, fake, clock)
    orch.answer("DM1-12", "q1", "Stop")
    clock["t"] = T0 + 300
    res = _check(cli)
    assert "Stopped" in res["did"] and fake.entries["budget"]["running"] is False
    assert res["health"]["text"] == "Stopped, so not checked" and res["failing"] is False
    _check(cli)
    assert [c[0] for c in fake.calls].count("stop") == 1


def test_answer_look_into_it_only_notes_it_and_asks_no_second_question(cli, fake, clock, orch):
    _make_failing(cli, fake, clock)
    orch.answer("DM1-12", "q1", "Look into it")
    n = len(fake.calls)
    clock["t"] = T0 + 300
    _crash(fake)
    res = _check(cli)
    assert "look into" in res["did"]
    assert fake.calls[n:] == []  # nothing restarted or stopped
    notes = orch.ticket()["history"]
    assert len(notes) == 1 and "Look into it" in notes[0]["text"] and notes[0]["by"] == "agent:services"
    clock["t"] = T0 + 360
    _crash(fake)
    assert _check(cli)["failing"] is True
    assert len(orch.asks()) == 1


def test_a_service_without_a_ticket_gets_one_kept_ticket(cli, fake, ws, clock, orch):
    fake.run_counts["budget"] = 1
    _add(cli, ticket=False)
    for i in range(3):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        _check(cli)
    tickets = [json.loads(p.read_text()) for p in (ws / "fake-tickets").glob("*.json")]
    own = [t for t in tickets if t["title"] == "Services: Budget guard keeps stopping"]
    assert len(own) == 1 and len(own[0]["questions"]) == 1
    assert _state(ws)["watch"]["question"]["ticket"] == own[0]["id"]


def test_state_and_question_never_carry_log_text(cli, fake, ws, clock, orch):
    log = ws / ".orch/addons/services/logs/budget.log"
    _make_failing(cli, fake, clock)
    log.write_text("token loaded: sk-live-abcdef\ncould not read the budget file\n", encoding="utf-8")
    _check(cli)
    text = (ws / ".orch/addons/services/state/budget.json").read_text(encoding="utf-8")
    text += json.dumps(orch.ticket())
    assert "sk-live" not in text and "budget file" not in text
    assert _state(ws)["running"] is True  # the start / stop record is kept next to the watch numbers


def test_a_service_stopped_by_the_person_is_not_watched(cli, fake, clock, orch):
    _add(cli)
    jrun(cli, "stop", "budget")
    for i in range(4):
        clock["t"] = T0 + 60 * (i + 1)
        res = _check(cli)
    assert res["failing"] is False and res["health"]["ok"] is False and not orch.asks()


def test_port_answers_with_a_real_listener():
    from orch_services import watch

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert watch.port_answers(port) is True
    finally:
        srv.close()
    assert watch.port_answers(port) is False


def test_check_with_no_services_says_so(cli, orch):
    code, out = jrun(cli, "check")
    assert code == 0 and out["checked"] == []
    code, text, _ = cli("check")
    assert "No services yet." in text


def _spec():
    from orch_services.drivers import Spec

    return Spec(
        sid="budget",
        name="Budget guard",
        workspace_id="w" * 32,
        argv=["/bin/true"],
        cwd=Path("/"),
        log=Path("/tmp/x.log"),
        auto=False,
    )


def test_launchd_runs_reads_the_count_from_print(monkeypatch):
    import subprocess

    from orch_services.drivers.launchd import Launchd

    d = Launchd()
    out = "gui/501/ch.orch.svc.x = {\n\tstate = running\n\truns = 7\n\tpid = 42\n}\n"
    monkeypatch.setattr(d, "_print", lambda spec: subprocess.CompletedProcess([], 0, out, ""))
    assert d.runs(_spec()) == 7
    monkeypatch.setattr(d, "_print", lambda spec: subprocess.CompletedProcess([], 113, "", "Could not find"))
    assert d.runs(_spec()) is None


def test_systemd_runs_reads_nrestarts(monkeypatch):
    import subprocess

    from orch_services.drivers.systemd import Systemd

    d = Systemd()
    seen = []

    def run(*args):
        seen.append(args)
        return subprocess.CompletedProcess([], 0, "NRestarts=4\n", "")

    monkeypatch.setattr(d, "_run", run)
    assert d.runs(_spec()) == 4
    assert seen[0][1].startswith("orch-svc-") and seen[0][2] == "--property=NRestarts"
    monkeypatch.setattr(d, "_run", lambda *a: subprocess.CompletedProcess([], 0, "NRestarts=\n", ""))
    assert d.runs(_spec()) is None


def test_an_answer_that_cannot_be_carried_out_is_asked_again(cli, fake, ws, clock, orch, monkeypatch):
    # review ORCH-378: a refused Stop used the answer up and orch never asked again while the service kept failing
    from orch_services.store import Refused

    _make_failing(cli, fake, clock)
    orch.answer("DM1-12", "q1", "Stop")

    def refuse(spec):
        raise Refused("Could not stop it (busy). Run orch services list and try again.")

    monkeypatch.setattr(fake, "stop", refuse)
    clock["t"] = T0 + 300
    res = _check(cli)
    assert "Could not stop Budget guard" in res["did"] and fake.entries["budget"]["running"] is True
    logs = [c for c in orch.calls() if c["args"][0] == "log"]
    assert logs and "busy" not in json.dumps(logs)  # the tool's words stay off the ticket
    assert len(orch.asks()) == 2  # the same pass asks again, once
    q = _state(ws)["watch"]["question"]
    assert q["open"] is True and q["id"] != "q1"
    clock["t"] = T0 + 360
    _check(cli)
    assert len(orch.asks()) == 2


def test_one_bad_pass_counts_once_even_when_it_was_also_started_again(
    cli, fake, ws, clock, orch, monkeypatch
):
    # ORCH-371 bug 5: "not alive" and a restart by the computer in the same pass counted as two failures
    from orch_services import watch

    monkeypatch.setattr(watch, "port_answers", lambda port: False)
    _add(cli, "--port", "5173")
    for i in range(2):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        assert _check(cli)["failing"] is False and not orch.asks()
    clock["t"] = T0 + 180
    _crash(fake)
    assert _check(cli)["failing"] is True and len(orch.asks()) == 1
    assert "3 times" in orch.ticket()["questions"][0]["text"]


def test_many_failures_recommend_look_into_it_not_restart(cli, fake, ws, clock, orch):
    # ORCH-623: a job that failed 8 times in 10 minutes is not helped by one more restart
    fake.run_counts["budget"] = 1
    _add(cli)
    clock["t"] = T0 + 60
    for _ in range(8):
        _crash(fake)
    res = _check(cli)
    assert res["failing"] is True
    q = orch.ticket()["questions"][0]
    assert "failed 8 times" in q["text"] and q["recommended"] == "Look into it"
    _code, out = jrun(cli, "list")  # the page suggests the same answer as the ticket question (R2.5)
    assert out["services"][0]["question"]["suggested"] == "Look into it"
    assert out["services"][0]["question"]["text"].endswith("Suggested: Look into it.")


# ---------------------------------------------------------------- what it affects, fresh or out of date (ORCH-1854)


def _depends(ws, lines, sid="budget"):
    """The record's own `depends` lines, as a person or the ticket's helper writes them (a plain file, R1.3)."""
    p = ws / ".orch/addons/services/services" / f"{sid}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["depends"] = lines
    p.write_text(json.dumps(rec), encoding="utf-8")


def test_known_dependents_are_said_first_on_the_question_and_the_row(cli, fake, ws, clock, orch):
    fake.run_counts["budget"] = 1
    _add(cli)
    _depends(ws, ["Every helper run that has a budget", "  ", 7, "x" * 90])
    for i in range(3):
        clock["t"] = T0 + 60 * (i + 1)
        _crash(fake)
        _check(cli)
    q = orch.ticket()["questions"][0]
    assert "10 minutes. Affected: Every helper run that has a budget, " in q["text"]
    _code, out = jrun(cli, "list")
    row = out["services"][0]
    assert row["depends"] == ["Every helper run that has a budget", "x" * 79 + "…"]
    text = row["question"]["text"]
    assert text.startswith("Affected: Every helper run that has a budget, xxx") and len(text) <= 200
    assert text.endswith("It failed 3 times in the last 10 minutes. Suggested: Restart.")


def test_running_fine_again_is_said_for_an_hour_after_a_fresh_check(cli, fake, ws, clock, orch):
    _make_failing(cli, fake, clock)
    clock["t"] = T0 + 240
    _check(cli)  # healthy from here
    clock["t"] = T0 + 840
    assert _check(cli)["failing"] is False
    _code, out = jrun(cli, "list")
    row = out["services"][0]
    assert row["state"] == "running" and row["recovered"] == {"since": "2027-01-15T08:04:00Z"}
    clock["t"] = T0 + 840 + 3600
    _check(cli)
    _code, out = jrun(cli, "list")
    assert out["services"][0]["recovered"] == {"since": "2027-01-15T08:04:00Z"}
    clock["t"] = T0 + 840 + 3601
    _check(cli)
    _code, out = jrun(cli, "list")
    assert out["services"][0]["recovered"] is None


def test_a_check_that_is_out_of_date_is_never_recovery(cli, fake, ws, clock, orch):
    _make_failing(cli, fake, clock)
    clock["t"] = T0 + 180 + 301  # the regular check stopped; the process happens to be alive now
    _code, out = jrun(cli, "list")
    row = out["services"][0]
    assert row["state"] == "failing" and row["stale"] is True and row["recovered"] is None
    assert row["checked_at"] == "2027-01-15T08:03:00Z"
    assert row["question"]["text"] == (
        "What it affects is not known. It was failing at the last check and orch has not checked it since."
        " Suggested: Restart."
    )
    # ran fine again, then the check stopped: the page no longer says it runs fine
    clock["t"] = T0 + 240
    _check(cli)
    clock["t"] = T0 + 840
    _check(cli)
    clock["t"] = T0 + 840 + 301
    _code, out = jrun(cli, "list")
    assert out["services"][0]["stale"] is True and out["services"][0]["recovered"] is None


def test_failing_again_or_a_stop_forgets_running_fine_again(cli, fake, ws, clock, orch):
    _make_failing(cli, fake, clock)
    clock["t"] = T0 + 240
    _check(cli)
    clock["t"] = T0 + 840
    _check(cli)
    assert _state(ws)["watch"]["recovered"]["since"] == "2027-01-15T08:04:00Z"
    for i in range(3):
        clock["t"] = T0 + 900 + 60 * i
        _crash(fake)
        _check(cli)
    assert _state(ws)["watch"]["recovered"] is None
    clock["t"] = T0 + 1080
    _check(cli)
    clock["t"] = T0 + 1680
    _check(cli)
    assert _state(ws)["watch"]["recovered"] is not None
    code, _out = jrun(cli, "stop", "budget")
    assert code == 0
    _check(cli)
    assert _state(ws)["watch"]["recovered"] is None


# ---------------------------------------------------------------- who answers on the port (r-1119-1255-ws-6)


def test_another_program_on_the_port_is_not_healthy_and_check_says_so(
    cli, fake, ws, clock, orch, monkeypatch
):
    from orch_services import watch

    monkeypatch.setattr(watch, "port_answers", lambda port: True)
    monkeypatch.setattr(watch, "listeners", lambda port: {9999})
    monkeypatch.setattr(watch, "parents", lambda: {9999: 1, 4242: 1})
    _add(cli, "--port", "5173")
    clock["t"] = T0 + 60
    res = _check(cli)
    assert res["health"]["ok"] is False and res["unhealthy"] is True
    assert res["health"]["text"] == "Alive, but another program answers on its address"
    code, out, _ = cli("check")
    assert code == 0 and "all as expected" not in out and "another program answers" in out


def test_a_child_of_the_service_listening_is_its_own(cli, fake, ws, clock, orch, monkeypatch):
    from orch_services import watch

    monkeypatch.setattr(watch, "port_answers", lambda port: True)
    monkeypatch.setattr(watch, "listeners", lambda port: {5001})
    monkeypatch.setattr(watch, "parents", lambda: {5001: 5000, 5000: 4242, 4242: 1})  # uv run -> python
    _add(cli, "--port", "5173")
    clock["t"] = T0 + 60
    res = _check(cli)
    assert res["health"] == {"ok": True, "how": "answers on its address", "text": "Answers on its address"}
    code, out, _ = cli("check")
    assert code == 0 and "all as expected" in out


def test_no_listener_of_this_account_means_someone_else(monkeypatch):
    from orch_services import watch

    monkeypatch.setattr(watch, "listeners", lambda port: set())
    assert watch.owns_port(4242, 5173) is False
    monkeypatch.setattr(watch, "listeners", lambda port: None)  # cannot tell: the connect alone counts
    assert watch.owns_port(4242, 5173) is None


def test_lsof_is_found_outside_the_path(monkeypatch):
    from orch_services import watch

    monkeypatch.setenv("PATH", "/nonexistent")
    got = watch._lsof()
    assert got == "lsof" or Path(got).is_file()  # /usr/sbin/lsof on a Mac even when PATH lacks /usr/sbin


@pytest.mark.skipif(sys.platform == "win32" or not Path(REAL_LSOF()).is_file(), reason="lsof reads listeners")
def test_owns_port_with_a_real_listener(monkeypatch):
    import os
    import socket

    from orch_services import watch

    monkeypatch.setattr(watch, "listeners", REAL_LISTENERS)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert os.getpid() in watch.listeners(port)
        assert watch.owns_port(os.getpid(), port) is True
        other = subprocess.Popen(["sleep", "30"])  # a process that neither listens nor started this one
        try:
            assert watch.owns_port(other.pid, port) is False
        finally:
            other.kill()
            other.wait()


def test_only_a_listener_the_probe_reaches_counts():
    # Codex review: the service on ::1 and another program on 127.0.0.1 must not look healthy
    from orch_services import watch

    text = "p4242\nn[::1]:5173\np9999\nn127.0.0.1:5173\np7000\nn*:5173\np7001\nn192.168.1.5:5173\nn*:80\n"
    assert watch.parse_lsof(text, 5173) == {9999, 7000}
    assert watch.parse_lsof("p1\nn[::]:8000\n", 8000) == {1}
    assert watch.parse_lsof("", 8000) == set()


def test_a_silent_port_just_after_a_start_is_starting_not_a_failure(monkeypatch):
    """ORCH-639: Restart on a web preview showed 'does not answer' while it was only starting."""
    from orch_services import watch

    rec = {"id": "web", "port": 59999}
    st = watch.drivers.Status(running=True, pid=1)
    monkeypatch.setattr(watch, "port_answers", lambda port: False)
    h = watch.health(rec, st, True, starting=True)
    assert h["text"] == "Starting…" and h["starting"] is True and h["ok"] is False
    h = watch.health(rec, st, True, starting=False)
    assert h["text"] == "Alive, but does not answer on its address" and not h.get("starting")


def test_just_started_is_true_only_in_the_grace_after_a_start(ws, clock):
    from orch_services import store, watch

    store.mark(ws, "web", True)
    since = store.last_change(ws, "web")
    from datetime import UTC, datetime

    t = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    clock["t"] = t + 30
    assert watch.just_started(ws, "web") is True
    clock["t"] = t + watch.START_GRACE + 5
    assert watch.just_started(ws, "web") is False


def test_starting_is_not_counted_as_running_fine_again(monkeypatch):
    """A failing service restarted through orch reads Starting… for a while: that is no recovery yet (ORCH-1130)."""
    from types import SimpleNamespace

    from orch_services import watch

    q = {"id": "q1", "open": True}
    w = {"events": [1, 2, 3], "failing": True, "healthy_since": None, "runs": None, "question": q}
    monkeypatch.setattr(watch, "clock", lambda: 700)
    monkeypatch.setattr(watch, "read_state", lambda *a: {"running": True, "watch": w})
    monkeypatch.setattr(watch, "_act_on_answer", lambda *a: None)
    monkeypatch.setattr(watch, "just_started", lambda *a: True)
    monkeypatch.setattr(watch, "port_answers", lambda port: False)
    monkeypatch.setattr(watch, "_save_watch", lambda root, sid, state: w.update(state))
    monkeypatch.setattr(watch, "_ticket_for", lambda *a: "T-1")
    monkeypatch.setattr(watch, "orch", lambda *a, **k: {})
    drv = SimpleNamespace(status=lambda spec: watch.drivers.Status(running=True, pid=1))
    r = watch.check_one(None, drv, {"id": "web", "name": "Web", "port": 8000}, None)
    assert r["health"]["starting"] is True and r["failing"] is True and r["did"] is None
    assert w["healthy_since"] is None and w["question"] is q
