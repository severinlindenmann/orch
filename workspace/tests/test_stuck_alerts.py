"""ORCH-426: a stuck ticket (a helper waiting on a permission, a step that keeps failing, a ticket the
Reviewer left for the person) is a Needs you row, whether or not the ticket needs a person's review, and goes
to the phone once while the relay is on and a phone is paired."""

import json
import subprocess
import time
from datetime import UTC, datetime

import pytest

from orch import addons, needs, phone_stuck, phone_view, relay, reviewer, runs, stuck, tickets


def _since(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


@pytest.fixture
def child():
    p = subprocess.Popen(["sleep", "120"])
    yield p.pid
    p.kill()
    p.wait()


def _live(proj, tid, state, pid, since):
    runs._write(
        proj,
        {
            "schema": "orch.run/1",
            "ticket": tid,
            "run": "r_test1234",
            "by": "human:tester",
            "agent": "generic",
            "mode": "live",
            "pid": pid,
            "started_at": _since(1200),
            "renewed_at": _since(1200),
            "live": {"state": state, "since": since},
        },
    )


def _rows(proj, kind):
    return [r for r in needs.core_rows(proj) if r["kind"] == kind]


def _record(run, tid, cid, code):
    assert run("check", "record", tid, cid, "--cmd", "uv run pytest -q", "--exit", str(code))[0] == 0


def test_permission_prompt_waiting_too_long_is_stuck(proj, new_ticket, child):
    tid = new_ticket("Ship the page")
    _live(proj, tid, "attention", child, _since(30))
    assert _rows(proj, "helper:permission") == []  # a fresh prompt: the person may be answering it now
    _live(proj, tid, "attention", child, _since(stuck.PERMISSION_MINUTES * 60 + 60))
    (row,) = _rows(proj, "helper:permission")
    assert row["ticket"] == tid and row["tone"] == "needs-you" and "your OK on its screen" in row["text"]
    assert row["id"] == f"core:permission:{tid}"


def test_two_failed_checks_in_a_row_are_stuck_until_one_passes(proj, new_ticket, run):
    tid = new_ticket("Fix the export")
    assert run("check", "add", tid, "Make the export work")[0] == 0
    _record(run, tid, "c1", 1)
    assert _rows(proj, "helper:failing") == []
    _record(run, tid, "c1", 2)
    (row,) = _rows(proj, "helper:failing")
    assert row["tone"] == "bad"
    assert 'failed 2 times in a row on the step "Make the export work"' in row["text"]
    _record(run, tid, "c1", 0)
    assert _rows(proj, "helper:failing") == []


def test_reviewer_left_it_is_stuck_while_in_review(proj, new_ticket, run):
    tid = new_ticket("Write the campaign")
    assert run("ticket", "status", tid, "done", "--by", "agent:claude")[0] == 0
    assert tickets.load(proj, tid)["status"] == "review"
    mine = {}
    reviewer.remember_left(mine, "leave", "no pull request to check, so you look at it yourself.")
    reviewer._write_state(proj, {tid: mine})
    assert _rows(proj, "reviewer:unsure") == []  # ORCH-1741: the Check card says it, one card per ticket
    (row,) = [r for r in stuck.stuck_rows(proj, [tickets.load(proj, tid)]) if r["kind"] == "reviewer:unsure"]
    assert row["text"].startswith("The Reviewer was not sure and left it for you: no pull request")
    reviewer.remember_left(mine, "accept", "all good")
    assert "left" not in mine


def test_finished_tickets_are_never_stuck(proj, new_ticket, run, child):
    tid = new_ticket("Old work")
    assert run("check", "add", tid, "Run it")[0] == 0
    _record(run, tid, "c1", 1)
    _record(run, tid, "c1", 1)
    _live(proj, tid, "attention", child, _since(3600))
    reviewer._write_state(proj, {tid: {"left": "not sure"}})
    assert run("ticket", "status", tid, "dropped", "--by", "human:tester")[0] == 0
    assert stuck.stuck_rows(proj, tickets.list_all(proj)) == []


def test_failed_runs_counts_only_the_last_streak():
    ev = [{"type": "command", "exit": 1}, {"type": "command", "exit": 0}, {"type": "note"}]
    assert stuck.failed_runs({"evidence": ev}) == 0
    ev += [
        {"type": "command", "exit": 3},
        {"type": "command", "ref": "no exit"},
        {"type": "command", "exit": 1},
    ]
    assert stuck.failed_runs({"evidence": ev}) == 2


# ------------------------------------------------------------------ the phone


@pytest.fixture
def wired(proj, monkeypatch):
    box = {"relay_on": True, "phones": ["ph_iphone0001"], "sent": [], "logged": []}
    monkeypatch.setattr(addons, "active", lambda root: {"relay": {}} if box["relay_on"] else {})
    monkeypatch.setattr(phone_view, "_paired", lambda root: list(box["phones"]))

    def fake_message(root, to, type_, body, ticket=None, reply_to=None, mid=None, created_at=None):
        box["sent"].append({"to": to, "type": type_, "body": body, "ticket": ticket, "id": mid})
        return {"sent": True}

    monkeypatch.setattr(relay, "_message", fake_message)
    monkeypatch.setattr(relay, "log_send_failure", lambda root, what, why: box["logged"].append(what))
    return box


def _failing(proj, new_ticket, run, title="Fix the export"):
    tid = new_ticket(title)
    assert run("check", "add", tid, "Make the export work")[0] == 0
    _record(run, tid, "c1", 1)
    _record(run, tid, "c1", 1)
    return tid


def test_phone_hears_once_with_key_and_reason_never_the_title(proj, new_ticket, run, wired):
    tid = _failing(proj, new_ticket, run, "Secret launch plan")
    key = tickets.load(proj, tid)["key"]
    assert len(phone_stuck.sync(proj)) == 1
    (m,) = wired["sent"]
    assert m["to"] == "phones" and m["type"] == "text" and m["ticket"] == tid
    assert m["body"]["text"].startswith(f"{key} is stuck. The check failed 2 times")
    assert "Secret launch plan" not in json.dumps(m)
    assert phone_stuck.sync(proj) == []  # the same stuck row: no second push
    _record(run, tid, "c1", 0)
    phone_stuck.sync(proj)
    state = json.loads(phone_stuck._state_path(proj).read_text())
    assert state == {}  # no longer stuck: forgotten, so the next time it gets stuck the phone hears again


def test_nothing_sent_or_kept_without_relay_or_phone(proj, new_ticket, run, wired):
    _failing(proj, new_ticket, run)
    wired["relay_on"] = False
    assert phone_stuck.sync(proj) == []
    wired["relay_on"], wired["phones"] = True, []
    assert phone_stuck.sync(proj) == []
    assert wired["sent"] == [] and not phone_stuck._state_path(proj).exists()


def test_backlog_arrives_a_few_per_pull(proj, new_ticket, run, wired):
    for i in range(phone_stuck.PER_PASS + 2):
        _failing(proj, new_ticket, run, f"Ticket {i}")
    assert len(phone_stuck.sync(proj)) == phone_stuck.PER_PASS
    assert len(phone_stuck.sync(proj)) == 2


def test_relay_refusal_is_logged_not_raised(proj, new_ticket, run, wired, monkeypatch):
    _failing(proj, new_ticket, run)

    def refuse(*a, **k):
        raise relay.Refused("no")

    monkeypatch.setattr(relay, "_message", refuse)
    assert phone_stuck.sync(proj, now=datetime.now(UTC)) == []
    assert wired["logged"]


def test_inbox_pull_runs_it(tmp_path, monkeypatch):
    from orch import phone_alerts

    calls = []
    for name in ("sync_open", "sync", "sync_light", "sync_reviews", "sync_cards"):
        monkeypatch.setattr(phone_view, name, lambda root: [])
    monkeypatch.setattr(relay, "send_working", lambda root: None)
    monkeypatch.setattr(phone_alerts, "sync", lambda root: [])
    monkeypatch.setattr(phone_stuck, "sync", lambda root: calls.append(root) or [])
    relay.sync_phone_views(tmp_path)
    assert calls == [tmp_path]


def test_reviewer_note_is_not_sent_again_when_only_the_ticket_was_touched():
    row = {
        "id": "core:unsure:t_1",
        "kind": "reviewer:unsure",
        "text": "Not sure.",
        "since": "2026-11-22T05:00:00Z",
    }
    sent = {"core:unsure:t_1": {"since": "2026-11-22T04:00:00Z", "text": "Not sure."}}
    assert phone_stuck.due([row], sent) == []  # ticket touched: `since` moved, same words
    assert phone_stuck.due([{**row, "text": "No pull request."}], sent) != []  # other reason: once more
    other = {**row, "id": "core:failing:t_1", "kind": "helper:failing"}
    assert phone_stuck.due([other], {"core:failing:t_1": {"since": "x", "text": "Not sure."}}) != []
