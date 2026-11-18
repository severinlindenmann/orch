"""Health check, failing and the one question (`orch services check`), with the fake driver, a fake clock and a fake
orch CLI (no sleeping, no real ticket)."""

import json
import socket
import sys
from pathlib import Path

import pytest
from conftest import jrun

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
    q = orch.ticket()["questions"][0]
    assert (
        q["text"]
        == "Budget guard keeps stopping: it failed 3 times in the last 10 minutes. Restart, Stop or Look into it?"
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
        "text": "It failed 4 times in the last 10 minutes. Restart, Stop or Look into it?",
    }
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
