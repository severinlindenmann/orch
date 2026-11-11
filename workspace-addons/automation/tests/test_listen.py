import json
import threading

from conftest import T, add_ticket, calls

from orch_automation import listen, needs
from orch_automation.cli import main
from orch_automation.listen import Listener
from orch_automation.loop import Scheduler
from orch_automation.runner import update_state


def relay_on(ws):
    (ws / ".orch/secrets").mkdir(parents=True, exist_ok=True)
    (ws / ".orch/secrets/relay.json").write_text("{}")


def test_not_listening_when_relay_is_not_set_up(ws):
    ev = threading.Event()
    assert Listener(ws, ev).step() == listen.PAUSE_OFF  # sleeps 60 s
    st = listen.read(ws)
    assert st["listening"] is False and st["note"] == "Not listening: the relay is not set up here"
    assert not ev.is_set() and not any(c["args"][:2] == ["relay", "inbox"] for c in calls(ws))


def test_long_poll_keeps_cursor_and_wakes_on_new_item(ws):
    relay_on(ws)
    ev = threading.Event()
    lst = Listener(ws, ev)
    (ws / "since.json").write_text(json.dumps({"next": 4, "items": [{"seq": 4, "id": "m_1", "seen": True}]}))
    assert lst.step() == 0 and not ev.is_set()
    assert listen.read(ws)["cursor"] == 4 and listen.read(ws)["listening"] is True
    (ws / "since.json").write_text(json.dumps({"next": 5, "items": [{"seq": 5, "id": "m_2", "seen": False}]}))
    lst.step()
    assert ev.is_set()
    polls = [c["args"] for c in calls(ws) if "--since" in c["args"]]
    assert polls[0][2:4] == ["--since", "0"] and polls[1][2:4] == ["--since", "4"] and "--wait" in polls[1]


def test_wake_forces_an_inbox_pass_between_intervals(ws):
    relay_on(ws)
    (ws / "inbox.json").write_text("[]")
    s = Scheduler(ws)
    s.tick(T(8, 0))
    s.tick(T(8, 0).replace(second=5))
    assert sum(c["args"][:2] == ["relay", "inbox"] for c in calls(ws)) == 1
    s.wake.set()
    s.tick(T(8, 0).replace(second=10))
    assert sum(c["args"][:2] == ["relay", "inbox"] for c in calls(ws)) == 2


def test_status_says_listening_or_not(ws, capsys, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=True: 123)
    listen._write(ws, listening=False, note=listen.NOT_LISTENING)
    assert main(["--dir", str(ws), "status"]) == 0
    assert "Not listening: the relay is not set up here" in capsys.readouterr().out
    listen._write(ws, listening=True, note="")
    main(["--dir", str(ws), "status", "--json"])
    assert json.loads(capsys.readouterr().out)["listening"] is True


def test_needs_ten_runs_today_warns_and_a_person_resets_it(ws):
    add_ticket(ws, "t_loop0001", title="Loopy", history=[])
    update_state(ws, "t_loop0001", starts=[f"2026-11-05T0{h}:00:00Z" for h in range(10)])
    (r,) = needs.rows(ws, T(12, 0, d=5))
    assert r["text"] == "Ran 10× today without you" and r["tone"] == "warn" and r["ticket"] == "t_loop0001"
    t = json.loads((ws / ".orch/tickets/t_loop0001.json").read_text())
    t["history"] = [{"at": "2026-11-05T05:30:00Z", "by": "human:s", "text": "hi"}]
    (ws / ".orch/tickets/t_loop0001.json").write_text(json.dumps(t))
    assert needs.rows(ws, T(12, 0, d=5)) == []  # only 4 runs since the person; nothing is blocked either way


def test_nine_runs_do_not_warn(ws):
    add_ticket(ws, "t_loop0002")
    update_state(ws, "t_loop0002", starts=[f"2026-11-05T0{h}:00:00Z" for h in range(9)])
    assert needs.rows(ws, T(12, 0, d=5)) == []


def test_needs_failed_run_without_question(ws):
    add_ticket(ws, "t_nf000001", title="X")
    add_ticket(
        ws, "t_nf000002", title="Y", questions=[{"id": "q1", "kind": "automation:failure", "answer": None}]
    )
    d = ws / ".orch/addons/automation"
    (d / "runs.jsonl").write_text(
        "".join(
            json.dumps({"ticket": t, "at": "2026-11-05T07:00:00Z", "took": 1, "exit": 1}) + "\n"
            for t in ("t_nf000001", "t_nf000002")
        )
    )
    (r,) = needs.rows(ws, T(8, 0, d=5))
    assert r["ticket"] == "t_nf000001" and r["tone"] == "bad" and r["kind"] == "automation:failed-run"


def test_needs_cli_json_validates(ws, capsys):
    import re

    add_ticket(ws, "t_loop0003")
    update_state(ws, "t_loop0003", starts=[f"2026-11-0{5}T0{h}:00:00Z" for h in range(10)])
    from datetime import UTC, datetime
    from unittest import mock

    with mock.patch("orch_automation.needs.datetime") as dt:
        dt.now.return_value = datetime(2026, 11, 5, 12, tzinfo=UTC)
        assert main(["--dir", str(ws), "needs", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and re.fullmatch(r"[a-z][a-z0-9-]{1,31}:[A-Za-z0-9_.:-]{1,200}", rows[0]["id"])


def test_unreachable_relay_pauses_instead_of_spinning(ws):
    relay_on(ws)
    (ws / "since.json").write_text(json.dumps({"next": 3, "items": [], "warning": "No connection"}))
    ev = threading.Event()
    assert Listener(ws, ev).step() >= 10  # a pause, not an instant retry
    assert listen.read(ws)["listening"] is False and not ev.is_set()


def phone_ticket(ws, tid, **kw):
    return add_ticket(
        ws,
        tid,
        created_at="2026-11-04T07:50:00Z",
        ext={"relay": {"origin": "phone", "from": "ph_abc", "message": "m_1"}},
        **kw,
    )


def test_phone_text_ticket_starts_one_run_only(ws):
    from conftest import runs_started

    phone_ticket(ws, "t_ph000001")
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_ph000001"]
    assert s.tick(T(8, 1)) == [] and Scheduler(ws).tick(T(8, 2)) == []  # also not after a restart
    assert runs_started(ws) == ["t_ph000001"]
    assert (
        json.loads((ws / ".orch/tickets/t_ph000001.json").read_text())["ext"]["automation"]["phone_started"]
        is True
    )


def test_old_or_closed_phone_tickets_are_left_alone(ws):
    from conftest import runs_started

    add_ticket(ws, "t_ph000002", created_at="2026-10-01T00:00:00Z", ext={"relay": {"origin": "phone"}})
    phone_ticket(ws, "t_ph000003", status="done")
    assert Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []


def test_follow_up_text_on_a_running_ticket_starts_nothing(ws):
    from conftest import runs_started

    add_ticket(ws, "t_ph000004", status="active")
    relay_on(ws)
    (ws / "inbox.json").write_text(
        json.dumps(
            [
                {
                    "id": "m_5",
                    "type": "text",
                    "from": "ph_abc",
                    "ticket": "t_ph000004",
                    "applied": True,
                    "note": "added to t_ph000004",
                    "body": {"text": "and also"},
                }
            ]
        )
    )
    assert (
        Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []
    )  # the run is going: the relay queued the text


def test_follow_up_text_on_an_idle_ticket_starts_a_run(ws):
    from conftest import runs_started

    add_ticket(ws, "t_ph000005", status="open")
    (ws / "ended-t_ph000005").write_text("")
    relay_on(ws)
    (ws / "inbox.json").write_text(
        json.dumps(
            [
                {
                    "id": "m_6",
                    "type": "text",
                    "from": "ph_abc",
                    "ticket": "t_ph000005",
                    "applied": True,
                    "note": "added to t_ph000005",
                    "body": {"text": "more"},
                }
            ]
        )
    )
    assert Scheduler(ws).tick(T(8)) == ["t_ph000005"] and runs_started(ws) == ["t_ph000005"]


def test_a_phone_ticket_made_by_the_inbox_pass_starts_in_the_same_pass(ws, monkeypatch):
    """fb6: the inbox pass makes the ticket of a new phone text; its run starts in that pass, not one
    interval (60 s) later on the next pass."""
    from conftest import runs_started

    def inbox(self, now):
        phone_ticket(ws, "t_ph000010")  # what `orch relay inbox` does for a new phone text
        return []

    monkeypatch.setattr(Scheduler, "inbox", inbox)
    relay_on(ws)
    s = Scheduler(ws)
    s.wake.set()  # the listener saw the text arrive
    assert s.tick(T(8)) == ["t_ph000010"] and runs_started(ws) == ["t_ph000010"]


def test_runs_for_the_phone_are_not_forced_to_one_step(ws):
    """fb4: a run the phone asked for may open a live session (core decides), so it stays up for an hour
    and can be opened with `orch run attach`; a scheduled (cron) run stays one step at a time."""
    from conftest import calls

    phone_ticket(ws, "t_ph000011")
    Scheduler(ws).tick(T(8))
    start = next(c["args"] for c in calls(ws) if c["args"][:2] == ["run", "start"])
    assert "--mode" not in start


def test_a_general_text_starts_the_agent_on_the_general_ticket(ws):
    """fb1B: a phone text in General was queued on the hidden General ticket and nothing ever answered it."""
    from conftest import calls, runs_started

    add_ticket(ws, "t_general1", status="open")
    (ws / "ended-t_general1").write_text("")
    relay_on(ws)
    (ws / "inbox.json").write_text(
        json.dumps(
            [
                {
                    "id": "m_7",
                    "type": "text",
                    "from": "ph_abc",
                    "ticket": "t_general1",
                    "applied": True,
                    "note": "General conversation",
                    "body": {"text": "hello", "general": True},
                }
            ]
        )
    )
    assert Scheduler(ws).tick(T(8)) == ["t_general1"] and runs_started(ws) == ["t_general1"]
    start = next(c["args"] for c in calls(ws) if c["args"][:2] == ["run", "start"])
    assert "--mode" not in start  # a person is waiting on the phone: a live session when the machine can
    told = json.loads((ws / ".orch/tickets/t_general1.json").read_text())["history"][0]["text"]
    assert "orch relay send ph_abc" in told and "--ticket t_general1" in told


def test_a_general_text_while_the_agent_runs_starts_nothing(ws):
    from conftest import runs_started

    add_ticket(ws, "t_general2", status="active")
    relay_on(ws)
    (ws / "inbox.json").write_text(
        json.dumps(
            [
                {
                    "id": "m_8",
                    "type": "text",
                    "from": "ph_abc",
                    "ticket": "t_general2",
                    "applied": True,
                    "note": "General conversation",
                    "body": {"text": "hello", "general": True},
                }
            ]
        )
    )
    assert Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []


def test_started_line_never_has_an_empty_id(ws):
    add_ticket(ws, "t_general3", status="open")
    (ws / "ended-t_general3").write_text("")
    relay_on(ws)
    (ws / "inbox.json").write_text(
        json.dumps(
            [
                {
                    "id": "",
                    "type": "text",
                    "from": "ph_abc",
                    "ticket": "t_general3",
                    "applied": True,
                    "note": "General conversation",
                    "body": {"text": "hello", "general": True},
                }
            ]
        )
    )
    Scheduler(ws).tick(T(8))
    texts = [h["text"] for h in json.loads((ws / ".orch/tickets/t_general3.json").read_text())["history"]]
    assert not any("()" in t or "(phone text )" in t for t in texts)


def test_answer_to_one_of_several_questions_resumes_a_stopped_phone_ticket_once(ws):
    from conftest import runs_started

    # q1 answered on the dashboard, q2 is still open: the ticket keeps waiting, no run holds it
    add_ticket(
        ws,
        "t_ph000009",
        status="waiting",
        waiting_on={"kind": "question", "ref": "q2"},
        ext={"relay": {"origin": "phone"}, "automation": {"phone_started": True}},
    )
    (ws / "ended-t_ph000009").write_text("")
    (ws / "pending-t_ph000009").write_text(json.dumps(["p_1"]))
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_ph000009"]
    assert s.tick(T(8, 1)) == [] and Scheduler(ws).tick(T(8, 2)) == []
    assert runs_started(ws) == ["t_ph000009"]


def test_one_run_when_both_ready_and_waiting_rules_could_apply(ws):
    from conftest import runs_started

    add_ticket(ws, "t_ph000010", status="ready")
    add_ticket(ws, "t_ph000011", status="waiting", waiting_on={"kind": "question", "ref": "q2"})
    add_ticket(
        ws, "t_ph000012", status="waiting", waiting_on={"kind": "time", "until": "2026-12-01T00:00:00Z"}
    )
    for tid in ("t_ph000010", "t_ph000011", "t_ph000012"):
        (ws / f"ended-{tid}").write_text("")
        (ws / f"pending-{tid}").write_text(json.dumps(["p_1"]))
    s = Scheduler(ws)
    assert sorted(s.tick(T(8))) == ["t_ph000010", "t_ph000011"]  # a time wait is not an answer: left alone
    assert s.tick(T(8, 1)) == [] and sorted(runs_started(ws)) == ["t_ph000010", "t_ph000011"]
