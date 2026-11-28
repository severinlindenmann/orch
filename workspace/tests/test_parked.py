"""ORCH-2431: a parked ticket (in Backlog, or waiting on a time, a ticket or something outside) gives no row
in `orch needs`, on Review or in the Needs you number; it comes back when the wait ends, a person brings it
back or it moves to To do; `orch needs --parked` lists what is parked, with the reason."""

import json

from orch import counts, history, parked, review, stuck, tickets

NOW = "2026-11-28T12:00:00Z"


def _t(tid, status="waiting", on=None, **kw):
    return {"id": tid, "status": status, "waiting_on": on, "questions": [], **kw}


def _new(run, title):
    return json.loads(run("ticket", "new", title, "--json")[1])["id"]


def _needs(run):
    code, out, err = run("needs", "--json")
    assert code == 0, err
    return json.loads(out)


def _number(proj, run):
    """THE number, the same from `orch counts` and from the rows a page draws (`orch needs`)."""
    n = json.loads(run("counts", "--json")[1])["needs_you"]["count"]
    shown = history.shown_json(proj, tickets.list_all(proj))
    assert n == counts.needs_you(shown, stopped=_needs(run))["count"]
    return n


def test_what_parks_a_ticket_and_what_does_not():
    assert parked.why(_t("t_backlg", "open"), NOW) == {"kind": "backlog"}
    w = {"kind": "time", "until": "2026-12-01T09:00:00Z", "ref": "the price list"}
    assert parked.why(_t("t_timeaa", on=w), NOW) == w
    assert parked.why(_t("t_extern", on={"kind": "external", "ref": "my own test"}), NOW) == {
        "kind": "external",
        "ref": "my own test",
    }
    assert parked.why(_t("t_ticket", on={"kind": "ticket", "ref": "DM-2"}), NOW)["kind"] == "ticket"
    # the wait ended: the time has come, or the ticket it waited on is finished
    assert parked.why(_t("t_pastaa", on={"kind": "time", "until": "2026-11-28T08:00:00Z"}), NOW) is None
    late = {"kind": "external", "ref": "Acme IT", "until": "2020-01-01T00:00:00Z"}
    assert parked.why(_t("t_pastex", on=late), NOW) is None
    other = parked.lookup([{"id": "t_otherr", "key": "DM-2", "status": "done"}])
    assert parked.why(_t("t_ticket", on={"kind": "ticket", "ref": "dm-2"}), NOW, other) is None
    # never parked: a question (that is the row), a failed start, a pull request, any other status
    assert parked.why(_t("t_questn", on={"kind": "question", "ref": "q1"}), NOW) is None
    assert parked.why(_t("t_startt", on={"kind": "external", "ref": "x", "start": True}), NOW) is None
    assert parked.why(_t("t_pullrq", on={"kind": "pr", "ref": "https://github.com/a/b/pull/1"})) is None
    for status in ("ready", "active", "review", "done", "dropped"):
        assert parked.why(_t("t_status", status), NOW) is None
    assert parked.why(_t("t_genera", "open", general=True), NOW) is None


def test_the_reason_is_plain_words():
    assert parked.reason({"kind": "backlog"}) == "In Backlog"
    assert parked.reason({"kind": "external", "ref": "my own test"}) == "Until you bring it back: my own test"
    assert parked.reason({"kind": "ticket", "ref": "DM-2"}) == "Until DM-2 is finished"
    assert parked.reason({"kind": "external", "ref": "Not now"}) == "Until you bring it back"
    assert ": " not in parked.reason({"kind": "time", "until": "2999-01-01T09:00:00Z", "ref": "Not now"})[9:]
    assert parked.reason({"kind": "time", "until": "2999-01-01T09:00:00Z"}).startswith("Until ")


def test_a_parked_ticket_is_not_in_the_needs_you_number():
    q = [{"id": "q1", "answer": None}]
    ts = [
        _t("t_backlg", "open", questions=q),
        _t("t_extern", on={"kind": "external", "ref": "x"}, questions=q),
        _t("t_future", on={"kind": "time", "until": "2999-01-01T00:00:00Z"}, questions=q),
        _t("t_onotha", on={"kind": "ticket", "ref": "t_extern"}, questions=q),
        _t("t_asking", on={"kind": "question", "ref": "q1"}, questions=q),
        _t("t_pastaa", on={"kind": "time", "until": "2020-01-01T00:00:00Z"}, questions=q),
        _t("t_doneaa", "done"),
        _t("t_ondone", on={"kind": "ticket", "ref": "t_doneaa"}, questions=q),
        _t("t_halted", "ready"),
    ]
    stopped = [
        {"id": "core:failing:t_extern", "source": "core", "kind": "helper:failing", "ticket": "t_extern"},
        {"id": "core:failing:t_asking", "source": "core", "kind": "helper:failing", "ticket": "t_asking"},
        {"id": "core:failing:t_halted", "source": "core", "kind": "helper:failing", "ticket": "t_halted"},
        {"id": "core:idle:t_halted", "source": "core", "kind": "helper:idle", "ticket": "t_halted"},
    ]
    n = counts.needs_you(ts, stopped=stopped)
    # one row per ticket: t_asking's question is its row, t_halted counts once
    assert n["tickets"] == ["t_asking", "t_pastaa", "t_ondone", "t_halted"]
    assert (n["count"], n["questions"], n["stopped"]) == (4, 3, 1)
    # a parked ticket is in progress (or not started) until it comes back, never lost from the lists
    s = counts.summary(ts)
    assert "t_backlg" in s["not_started"] and {"t_extern", "t_future", "t_onotha"} <= set(s["in_progress"])


def test_a_parked_ticket_gives_no_stuck_row(proj, run):
    assert run("init")[0] == 0
    failing = {"type": "command", "exit": 1, "at": "2026-11-28T10:00:00Z"}
    step = {"id": "c1", "text": "Wait for the release", "evidence": [failing] * stuck.FAILED_RUNS}
    ts = [
        _t("t_failaa", "ready", checklist=[step]),
        _t("t_parked", on={"kind": "external", "ref": "x"}, checklist=[step]),
        _t("t_backlg", "open", checklist=[step]),
    ]
    assert [r["ticket"] for r in stuck.rows(proj, ts)] == ["t_failaa"]
    assert [r["ticket"] for r in stuck.stuck_rows(proj, ts)] == ["t_failaa"]


def test_one_row_per_ticket_at_most(proj, run):
    """A step that keeps failing on a ticket whose wake time has passed: one row, not two (ORCH-1205)."""
    assert run("init")[0] == 0
    tid = _new(run, "Wait for the release")
    assert run("check", "add", tid, "Wait until it is released")[0] == 0
    for _ in range(stuck.FAILED_RUNS):
        assert run("check", "record", tid, "c1", "--cmd", "make", "--exit", "1")[0] == 0
    assert run("ticket", "wait", tid, "--until", "2999-01-01T00:00:00Z")[0] == 0
    assert _needs(run) == []  # parked until then
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["waiting_on"]["until"] = "2020-01-01T00:00:00Z"
    p.write_text(json.dumps(t), encoding="utf-8")
    assert [r["kind"] for r in _needs(run)] == ["helper:failing"]
    assert _number(proj, run) == 1
    # its own question is the row once it asks
    assert run("ask", tid, "Go on?", "--option", "Yes", "--option", "No")[0] == 0
    t = json.loads(p.read_text(encoding="utf-8"))
    t["waiting_on"] = {"kind": "time", "until": "2020-01-01T00:00:00Z"}
    p.write_text(json.dumps(t), encoding="utf-8")
    assert [r["kind"] for r in _needs(run)] == ["question"]
    assert _number(proj, run) == 1


def test_parking_takes_the_question_off_and_bringing_back_returns_it(proj, run):
    """Needs, the Needs you number and the Review cards, for both ways to park and both ways back."""
    assert run("init")[0] == 0
    tid = _new(run, "Try it on my notebook")
    assert run("ask", tid, "Did it work?", "--option", "Yes", "--option", "No")[0] == 0
    assert [r["id"] for r in _needs(run)] == [f"core:q:{tid}:q1"]
    assert _number(proj, run) == 1 and len(review.stack(proj)) == 1

    # "until I bring it back"
    assert run("ticket", "wait", tid, "--on", "external:my own test on the notebook")[0] == 0
    assert _needs(run) == [] and _number(proj, run) == 0 and review.stack(proj) == []
    code, out, _ = run("needs")
    assert out.startswith("Nothing needs you.") and "1 parked, not listed here: orch needs --parked" in out
    (row,) = json.loads(run("needs", "--parked", "--json")[1])
    assert (row["ticket"], row["kind"], row["questions"]) == (tid, "external", 1)
    assert row["reason"] == "Until you bring it back: my own test on the notebook"
    key = tickets.load(proj, tid).get("key") or tid
    assert row["cli"] == f"orch ticket wait {key} --clear"
    text = run("needs", "--parked")[1]
    assert text.startswith("Parked (1)") and "(1 open question)" in text and row["cli"] in text

    # brought back: the question is the row again, and the ticket waits on it as before
    assert run("ticket", "wait", tid, "--clear")[0] == 0
    t = tickets.load(proj, tid)
    assert (t["status"], t["waiting_on"]) == ("waiting", {"kind": "question", "ref": "q1"})
    assert [r["id"] for r in _needs(run)] == [f"core:q:{tid}:q1"]
    assert _number(proj, run) == 1 and len(review.stack(proj)) == 1
    assert run("needs", "--parked")[1].startswith("Nothing is parked.")

    # "until a date": off while the date is ahead, back once it has passed
    assert run("ticket", "wait", tid, "--until", "2999-01-01T00:00:00Z")[0] == 0
    assert _needs(run) == [] and _number(proj, run) == 0 and review.stack(proj) == []
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["waiting_on"]["until"] = "2020-01-01T00:00:00Z"
    p.write_text(json.dumps(t), encoding="utf-8")
    assert f"core:q:{tid}:q1" in [r["id"] for r in _needs(run)]
    assert _number(proj, run) == 1 and len(review.stack(proj)) == 1


def test_a_backlog_ticket_shows_nothing_until_it_moves_to_todo(proj, run):
    assert run("init")[0] == 0
    tid = _new(run, "Later idea")
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    assert run("ticket", "status", tid, "open")[0] == 0  # back to Backlog, its question still open
    assert tickets.load(proj, tid)["status"] == "open"
    assert _needs(run) == [] and _number(proj, run) == 0 and review.stack(proj) == []
    (row,) = json.loads(run("needs", "--parked", "--json")[1])
    assert (row["ticket"], row["reason"], row["questions"]) == (tid, "In Backlog", 1)
    assert row["cli"].startswith("orch ticket status ") and row["cli"].endswith(" ready")
    # a Backlog ticket that holds nothing back is not in the parked list: Backlog itself lists it
    _new(run, "Plain backlog ticket")
    assert len(json.loads(run("needs", "--parked", "--json")[1])) == 1

    assert run("ticket", "status", tid, "ready")[0] == 0  # To do
    assert [r["id"] for r in _needs(run)] == [f"core:q:{tid}:q1"]
    assert _number(proj, run) == 1 and len(review.stack(proj)) == 1


def test_a_wait_on_a_ticket_ends_when_that_ticket_is_finished(proj, run):
    assert run("init")[0] == 0
    first, then = _new(run, "First"), _new(run, "Then")
    assert run("ask", then, "Go on?", "--option", "Yes", "--option", "No")[0] == 0
    assert run("ticket", "wait", then, "--on", f"ticket:{first}")[0] == 0
    assert _needs(run) == [] and review.stack(proj) == []
    tickets.set_status(proj, first, "review", "agent:claude")
    assert f"core:q:{then}:q1" in [r["id"] for r in _needs(run)]
    assert then in [c["ticket"] for c in review.stack(proj)]
