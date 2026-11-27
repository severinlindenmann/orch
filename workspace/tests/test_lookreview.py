"""The Reviewer's second look (ORCH-175): bigger work the small Reviewer leaves waits in line, one helper on
the small model starts only when there is work, and its verdict accepts for the owner, sends back once or
leaves it; look work without pictures goes back by itself; security and questions stay with the owner."""

import json
from datetime import datetime

import pytest

from orch import lookreview, reviewer, runs, tickets, worktrees

PR = "https://github.com/acme/app/pull/12"
CSS = "workspace-addons/dashboard/src/orch_dashboard/web/pages/home.css"


@pytest.fixture(autouse=True)
def starts(monkeypatch):
    calls = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: calls.append(tid) or {"run": "r_x"})
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    return calls


@pytest.fixture
def facts(monkeypatch):
    """A merged, green pull request that changes how a page looks."""
    box = {
        "facts": {
            "url": PR,
            "number": 12,
            "state": "MERGED",
            "green": True,
            "checks": 17,
            "failed": 0,
            "merged_at": "2999-01-01T00:00:00Z",
            "files": [{"path": CSS, "additions": 4, "deletions": 1}],
            "added": None,
        }
    }
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: box["facts"] if url == PR else None)
    return box


@pytest.fixture
def on(proj, run):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0
    assert run("config", "set", "workflow.reviewer_look", "on", "--by", "human:tester")[0] == 0


def _finished(proj, run, new_ticket, picture=True, title="Top bar on one row"):
    tid = new_ticket(title)
    assert run("ticket", "tidy", tid, title, "--description", "d", "--done-when", "the top bar fits one row",
               "--by", "human:tester")[0] == 0  # fmt: skip
    assert run("check", "add", tid, "Put the top bar on one row", "--covers", "the top bar fits one row",
               "--by", "human:tester")[0] == 0  # fmt: skip
    ev = ["--pr", PR]
    if picture:
        pic = proj / "files" / f"{tid}-bar-1280.png"
        pic.parent.mkdir(exist_ok=True)
        pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
        ev += ["--file", str(pic.relative_to(proj))]
    assert run("check", "done", tid, "c1", *ev, "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    return tid


def _lines(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def test_a_look_change_with_pictures_waits_for_a_second_look_and_one_helper_starts(
    proj, run, new_ticket, facts, on, starts
):
    tid = _finished(proj, run, new_ticket)
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["queue"]
    assert tickets.load(proj, tid)["status"] == "review"
    assert (
        _lines(proj, tid)[-1] == "Waits for a second look by the Reviewer: changes how a page looks (1 file)."
    )
    st = lookreview.read_state(proj)
    helper = st["open"]["ticket"]
    assert starts == [helper] and st["open"]["items"] == [tid]
    h = tickets.load(proj, helper)
    assert h["title"].startswith("Reviewer second look") and h.get("parent") is None
    assert any(x.startswith("Look at ") and "changes how a page looks" in x for x in _lines(proj, helper))
    assert h["checklist"][0]["text"] == "Give every listed ticket a verdict"
    assert "Second look: opened second look" in reviewer.text(res)
    reviewer.run(proj)  # nothing changed: no second line, no second helper
    assert _lines(proj, tid).count(_lines(proj, tid)[-1]) == 1
    assert starts == [helper]


def test_the_helper_starts_on_the_small_model(proj, run, new_ticket, facts, on):
    from orch import modelpick

    _finished(proj, run, new_ticket, title="Design the security login page")  # hard words stay in the history
    reviewer.run(proj)
    helper = tickets.load(proj, lookreview.read_state(proj)["open"]["ticket"])
    assert modelpick.pick(helper)[0] == "sonnet"


def test_a_look_change_without_pictures_goes_back_once(proj, run, new_ticket, facts, on, starts):
    tid = _finished(proj, run, new_ticket, picture=False)
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["back"]
    t = tickets.load(proj, tid)
    assert t["status"] == "ready"
    assert lookreview.NO_PICTURES in _lines(proj, tid)[-1]
    tickets.set_status(proj, tid, "review", "human:tester")  # back again, still no pictures: the owner's
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1].startswith("Left for you by the Reviewer: ")
    assert lookreview.read_state(proj)["open"] is None


@pytest.mark.parametrize("what", ["security", "question", "closed"])
def test_security_questions_and_closed_requests_stay_with_the_owner(proj, run, new_ticket, facts, on, what):
    if what == "security":
        facts["facts"]["files"].append({"path": "workspace/src/orch/secretscan.py", "additions": 2})
    if what == "closed":
        facts["facts"]["state"] = "CLOSED"
    tid = _finished(proj, run, new_ticket)
    if what == "question":
        assert (
            run(
                "ask",
                tid,
                "Which colour?",
                "--option",
                "a",
                "--option",
                "b",
                "--recommend",
                "a",
                "--by",
                "agent:x",
            )[0]
            == 0
        )
    reviewer.run(proj)
    if what == "question":  # asking moved it out of Review: nothing for either Reviewer to do
        assert tickets.load(proj, tid)["status"] != "review"
    else:
        assert _lines(proj, tid)[-1].startswith("Left for you by the Reviewer: ")
    assert lookreview.read_state(proj)["line"] == {}


def test_off_the_small_reviewer_leaves_it_as_before(proj, run, new_ticket, facts, starts):
    run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert _lines(proj, tid)[-1] == "Left for you by the Reviewer: changes how a page looks (1 file)."
    assert starts == []


def test_only_a_person_turns_it_on(proj, run):
    code, _, err = run("config", "set", "workflow.reviewer_look", "on", "--by", "agent:x")
    assert code == 2 and "Only the owner" in err
    assert run("config", "set", "workflow.reviewer_look", "on", "--by", "human:pat")[0] == 0
    code, out, _ = run("config", "get", "workflow.reviewer_look", "--json")
    assert json.loads(out)["workflow.reviewer_look"] is True
    assert run("config", "set", "workflow.reviewer_look", "off", "--by", "agent:x")[0] == 0


def test_accept_marks_done_for_the_owner_with_the_points(proj, run, new_ticket, facts, on, monkeypatch):
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    helper = lookreview.read_state(proj)["open"]["ticket"]
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda root: helper)  # the helper's live run
    code, out, _ = run("review", "verdict", tid, "accept", "top bar fits at 1280, 1920 and 390",
                       "--point", "the top bar fits one row: shown")  # fmt: skip
    assert code == 0 and "accepted for you" in out
    t = tickets.load(proj, tid)
    assert t["status"] == "done"
    assert _lines(proj, tid)[-3] == "Second look, point by point: the top bar fits one row: shown"
    assert _lines(proj, tid)[-1] == "Accepted for you by the Reviewer: top bar fits at 1280, 1920 and 390"
    rows = reviewer.accepted(proj, "2000-01-01T00:00:00+00:00")
    assert [r["ticket"] for r in rows] == [tid]
    assert lookreview.read_state(proj)["line"] == {}
    assert reviewer.run(proj)["second_look"] == []  # its one ticket has a verdict: the helper ticket is free
    assert "Next: nothing else waits for a second look" in out  # issue 1920: no placeholder
    code, out, _ = run("review", "accepted", "--since", "yesterday")
    assert code == 0 and "Accepted for you since yesterday: 1 ticket" in out  # not "yesterday"
    code, out, _ = run("review", "accepted")
    assert code == 0 and "Accepted for you today: 1 ticket" in out


def test_the_verdict_names_the_next_ticket_waiting_for_a_second_look(proj, run, new_ticket, facts, on):
    """Issue 1920: the Next hint after a verdict was a placeholder; it names the next ticket in line."""
    a, b = (_finished(proj, run, new_ticket, title=f"Look change {i}") for i in range(2))
    for tid in (a, b):
        lookreview.queue(proj, tid, "changes how a page looks")
    lookreview.tend(proj)
    assert lookreview.read_state(proj)["open"]["items"] == [a, b]
    code, out, _ = run("review", "verdict", a, "leave", "a new colour")
    key_b = tickets.load(proj, b)["key"]
    assert code == 0 and f"Next: orch ticket show {key_b}  (the next one waiting for a second look)" in out
    res = lookreview.verdict(proj, b, "leave", "x")
    assert res["next"] is None


def test_back_goes_to_the_helper_once_then_it_is_left(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    res = lookreview.verdict(proj, tid, "back", "the mockup was not redrawn", ["mockup redrawn: missing"])
    assert res["verdict"] == "back"
    t = tickets.load(proj, tid)
    assert t["status"] == "ready"
    assert "the mockup was not redrawn; mockup redrawn: missing" in t["checklist"][-1]["text"]
    assert run("check", "done", tid, "c2", "--note", "redrew it", "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    reviewer.run(proj)  # back in line (pictures are there)
    res = lookreview.verdict(proj, tid, "back", "still no mockup")
    assert res["verdict"] == "leave"
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1] == (
        "Left for you by the Reviewer: second look: sent back once already and still: still no mockup"
    )


def test_leave_keeps_it_in_review_with_the_line(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    lookreview.verdict(proj, tid, "leave", "a new colour no card of yours covers")
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1].endswith("a new colour no card of yours covers")
    reviewer.run(proj)  # decided: the small Reviewer adds no line
    assert _lines(proj, tid)[-1].endswith("a new colour no card of yours covers")


def test_verdict_refusals(proj, run, new_ticket, facts, on, monkeypatch):
    tid = _finished(proj, run, new_ticket)
    other = new_ticket("Not in line")
    with pytest.raises(tickets.Refused, match="not waiting for a second look"):
        lookreview.verdict(proj, other, "accept", "x")
    reviewer.run(proj)
    with pytest.raises(tickets.Refused, match="Not every point is shown"):
        lookreview.verdict(proj, tid, "accept", "fine", ["the top bar fits one row: missing at 390"])
    with pytest.raises(tickets.Refused, match="one line"):
        lookreview.verdict(proj, tid, "accept", "  ")
    monkeypatch.setenv("ORCH_TICKET", lookreview.read_state(proj)["open"]["ticket"])
    with pytest.raises(tickets.Refused, match="Only the second-look helper"):  # forged: no live run
        lookreview.verdict(proj, tid, "accept", "x")
    monkeypatch.delenv("ORCH_TICKET")
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda root: tid)
    with pytest.raises(tickets.Refused, match="its own ticket"):
        lookreview.verdict(proj, tid, "accept", "x")
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda root: other)
    with pytest.raises(tickets.Refused, match="Only the second-look helper"):
        lookreview.verdict(proj, tid, "accept", "x")
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda root: None)
    run("config", "set", "workflow.reviewer_look", "off", "--by", "human:tester")
    with pytest.raises(tickets.Refused, match="off here"):
        lookreview.verdict(proj, tid, "accept", "x")


def test_one_helper_at_a_time_and_a_daily_limit_of_tickets(proj, run, new_ticket, facts, on, starts):
    a = _finished(proj, run, new_ticket, title="First look change")
    reviewer.run(proj)
    b = _finished(proj, run, new_ticket, title="Second look change")
    reviewer.run(proj)
    assert len(starts) == 1  # the first helper still has a ticket to decide
    lookreview.verdict(proj, a, "leave", "x")
    reviewer.run(proj)
    assert len(starts) == 2 and lookreview.read_state(proj)["open"]["items"] == [b]
    st = lookreview.read_state(proj)
    st["open"], st["looked"] = None, {lookreview._day(datetime.now().astimezone()): lookreview.PER_DAY}
    lookreview._write_state(proj, st)
    out = lookreview.tend(proj)
    assert out == [f"1 wait for a second look; {lookreview.PER_DAY} tickets looked at today already"]
    assert len(starts) == 2
    full = lookreview.FULL_LINE.format(n=lookreview.PER_DAY)
    assert _lines(proj, b)[-1] == full  # the ticket says no look comes today
    lookreview.tend(proj)
    assert _lines(proj, b).count(full) == 1  # once a day, not every pass


def _held(t: datetime):
    """A datetime whose now() stands still at `t` (ORCH-1183)."""

    class _Held(datetime):
        @classmethod
        def now(cls, tz=None):
            return t if tz is None else t.astimezone(tz)

    return _Held


@pytest.mark.parametrize("at", ["23:59:40", "23:59:59", "00:00:05"])
def test_tickets_one_per_pass_all_get_a_look_the_same_day(
    proj, run, new_ticket, facts, on, starts, monkeypatch, at
):
    """18 Nov: tickets came one per pass, each helper got one, and 4 helpers a day ran out by 06:00.
    One clock for the whole test (ORCH-1183): the daily cap counts per day on purpose, so six looks that
    straddle midnight rightly count on two days."""
    held = datetime.fromisoformat(f"2026-11-21T{at}").astimezone()
    monkeypatch.setattr(lookreview, "datetime", _held(held))
    for i in range(6):
        tid = _finished(proj, run, new_ticket, title=f"Look change {i}")
        reviewer.run(proj)
        assert lookreview.read_state(proj)["open"]["items"] == [tid]
        lookreview.verdict(proj, tid, "leave", "x")
    assert len(starts) == 6
    assert lookreview.read_state(proj)["looked"] == {"2026-11-21": 6}


def test_a_batch_never_goes_past_the_daily_limit(proj, run, new_ticket, facts, on, starts, monkeypatch):
    held = datetime.fromisoformat("2026-11-21T23:59:59").astimezone()
    monkeypatch.setattr(lookreview, "datetime", _held(held))  # one day for the whole test (ORCH-1183)
    ids = [_finished(proj, run, new_ticket, title=f"Look change {i}") for i in range(3)]
    for tid in ids:
        lookreview.queue(proj, tid, "changes how a page looks")
    st = lookreview.read_state(proj)
    st["looked"] = {lookreview._day(): lookreview.PER_DAY - 2}
    lookreview._write_state(proj, st)
    lookreview.tend(proj)
    st = lookreview.read_state(proj)
    assert len(st["open"]["items"]) == 2 and st["looked"] == {lookreview._day(): lookreview.PER_DAY}


def test_the_waiting_line_does_not_also_say_you_look_yourself():
    t = {"history": [], "checks": []}
    res = {"verdict": "leave", "why": "no pull request to check, so you look at it yourself."}
    assert lookreview.triage(t, [], res, 0) == {"verdict": "queue", "why": "no pull request to check"}


def test_dry_run_starts_nothing(proj, run, new_ticket, facts, on, starts):
    tid = _finished(proj, run, new_ticket)
    code, out, _ = run("review", "tend", "--dry-run")
    assert code == 0 and "would be in line for a second look" in out
    assert starts == [] and lookreview.read_state(proj)["line"] == {}
    assert tickets.load(proj, tid)["status"] == "review"


def test_its_own_second_look_ticket_is_never_queued(proj, run, new_ticket, facts, on, starts):
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    helper = lookreview.read_state(proj)["open"]["ticket"]
    lookreview.verdict(proj, tid, "leave", "x")
    assert run("check", "done", helper, "c1", "--note", "gave the verdict", "--by", "human:tester")[0] == 0
    tickets.set_status(proj, helper, "review", "human:tester")
    reviewer.run(proj)
    assert helper not in lookreview.read_state(proj)["line"]
    # ORCH-826: a finished second look is good news only: accepted for the owner, never queued or left
    assert _lines(proj, helper)[-1].startswith("Accepted for you by the Reviewer: The Reviewer's second look")
    assert len(starts) == 1
