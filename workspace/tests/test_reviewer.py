"""The Reviewer (`orch review tend`, ORCH-77): accepts a small merged fix in Review for the owner with its
reasons in the history, leaves a visual change for the owner, sends missing work back once, and lists what it
accepted."""

import json

import pytest

from orch import brake, reviewer, runs, tickets

PR = "https://github.com/acme/app/pull/12"


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    calls = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: calls.append(tid) or {"run": "r_x"})
    return calls


@pytest.fixture
def facts(monkeypatch):
    """GitHub as the test says it: one merged, green, small fix unless changed."""
    box = {
        "facts": {
            "url": PR,
            "number": 12,
            "state": "MERGED",
            "green": True,
            "checks": 17,
            "failed": 0,
            "files": [
                {"path": "workspace/src/orch/runs.py", "additions": 20, "deletions": 4},
                {"path": "workspace/tests/test_runs.py", "additions": 80, "deletions": 0},
            ],
            "added": {"workspace/src/orch/runs.py": ["    if not rec:", "        return None"]},
        }
    }
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: box["facts"] if url == PR else None)
    return box


@pytest.fixture
def on(proj, run):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0


def _finished(proj, run, new_ticket, pr=PR, review=True):
    tid = new_ticket("Fix the stale run record")
    assert run("ticket", "tidy", tid, "Fix the stale run record", "--description", "d", "--done-when",
               "the stale record is fixed", "--by", "human:tester")[0] == 0  # fmt: skip
    assert run("check", "add", tid, "Fix the stale record", "--covers", "the stale record is fixed",
               "--by", "human:tester")[0] == 0  # fmt: skip
    ev = ["--pr", pr] if pr else ["--note", "looked at it"]
    assert run("check", "done", tid, "c1", *ev, "--by", "human:tester")[0] == 0
    if review:
        tickets.set_status(proj, tid, "review", "human:tester")
    return tid


def _lines(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def test_a_small_merged_fix_is_accepted_for_the_owner_with_its_reasons(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["accept"]
    t = tickets.load(proj, tid)
    assert t["status"] == "done"
    last = t["history"][-1]
    assert last["by"] == "agent:reviewer"
    assert last["text"] == (
        "Accepted for you by the Reviewer: pull request #12 merged, 17 checks green, 1 of 1 tasks with "
        "evidence, small fix (1 file, 24 lines)."
    )
    assert any(h["text"] == "Status review -> done" and h["by"] == "agent:reviewer" for h in t["history"])


def test_a_visual_change_is_left_for_the_owner_with_one_line(proj, run, new_ticket, facts, on):
    facts["facts"]["files"] = [
        {
            "path": "workspace-addons/dashboard/src/orch_dashboard/web/pages/home.css",
            "additions": 4,
            "deletions": 1,
        },
        {"path": "workspace-addons/dashboard/mockup/home.html", "additions": 4, "deletions": 1},
    ]
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    t = tickets.load(proj, tid)
    assert t["status"] == "review"
    assert t["history"][-1]["text"] == "Left for you by the Reviewer: changes how a page looks (2 files)."
    reviewer.run(proj)  # nothing changed: no second line
    assert _lines(proj, tid).count(t["history"][-1]["text"]) == 1


@pytest.mark.parametrize(
    "path,added,word",
    [
        ("workspace/src/orch/cli.py", ['    x.add_argument("--fast")'], "adds a command or a setting"),
        (
            "workspace/src/orch/runs.py",
            ['        raise Refused("That run is gone now.")'],
            "changes words people read",
        ),
        ("workspace/src/orch/builtin/orch/skills/orch/SKILL.md", None, "changes words people read"),
        (".github/workflows/ci.yml", None, "changes rules, checks, relay, publish"),
        ("relay/src/main.rs", None, "changes rules, checks, relay, publish"),
    ],
)
def test_words_commands_rules_and_relay_are_not_small(proj, run, new_ticket, facts, on, path, added, word):
    facts["facts"]["files"] = [{"path": path, "additions": 3, "deletions": 1}]
    facts["facts"]["added"] = {path: added} if added else None
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert word in _lines(proj, tid)[-1]


def test_a_big_change_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    facts["facts"]["files"] = [{"path": f"workspace/src/orch/m{i}.py", "additions": 10, "deletions": 0}
                               for i in range(11)]  # fmt: skip
    facts["facts"]["added"] = {}
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert "too big for a small fix (11 files, 110 lines" in _lines(proj, tid)[-1]


def test_an_open_pull_request_goes_back_to_the_helper_once(proj, run, new_ticket, facts, on, no_starts):
    facts["facts"]["state"] = "OPEN"
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    t = tickets.load(proj, tid)
    assert t["status"] == "ready" and no_starts == [tid]
    assert _lines(proj, tid)[-1].startswith("Sent back by the Reviewer: The Reviewer found work missing: "
                                            "pull request #12 is not merged yet")  # fmt: skip
    assert runs.undelivered(proj, tid)  # the helper reads why
    # the helper comes back without merging: left for the owner, no loop
    run("check", "done", tid, "c2", "--note", "tried", "--by", "human:tester")
    tickets.set_status(proj, tid, "review", "human:tester")
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1].startswith("Left for you by the Reviewer: sent back once already and still:")


def test_red_checks_on_the_merge_go_back(proj, run, new_ticket, facts, on):
    facts["facts"].update(green=False, failed=2)
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert "were not green when it was merged (2 of 17 failed)" in _lines(proj, tid)[-1]


def test_no_pull_request_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket, pr=None)
    reviewer.run(proj)
    assert (
        _lines(proj, tid)[-1]
        == "Left for you by the Reviewer: no pull request to check, so you look at it yourself."
    )


def test_github_unreadable_does_nothing_and_looks_again(proj, run, new_ticket, facts, on):
    facts["facts"] = None
    tid = _finished(proj, run, new_ticket)
    before = _lines(proj, tid)
    res = reviewer.run(proj)
    assert res["actions"][0]["verdict"] == "wait" and _lines(proj, tid) == before


def test_an_open_question_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    run("ask", tid, "Which name?", "--option", "A", "--option", "B", "--by", "human:tester")
    tickets.set_status(proj, tid, "review", "human:tester")
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"


def test_off_by_default_and_paused_does_nothing(proj, run, new_ticket, facts):
    tid = _finished(proj, run, new_ticket)
    assert reviewer.run(proj)["off"] is True
    assert tickets.load(proj, tid)["status"] == "review"
    run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")
    brake.pause(proj, "human:tester")
    assert reviewer.run(proj)["paused"] is True
    assert tickets.load(proj, tid)["status"] == "review"


def test_dry_run_changes_nothing(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    code, out, _ = run("review", "tend", "--dry-run")
    assert code == 0 and "would be accepted for you" in out
    assert tickets.load(proj, tid)["status"] == "review"


def test_accept_needs_the_switch_and_evidence(proj, run, new_ticket):
    tid = _finished(proj, run, new_ticket)
    with pytest.raises(tickets.Refused, match="off here"):
        tickets.accept_for_owner(proj, tid, "x")


def test_the_owner_sees_the_list_and_can_send_one_back(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    code, out, _ = run("review", "accepted", "--json")
    rows = json.loads(out)["accepted"]
    assert code == 0 and [r["ticket"] for r in rows] == [tid] and rows[0]["sent_back"] is False
    assert "small fix" in rows[0]["why"]
    code, out, _ = run("review", "accepted")
    assert out.startswith("Accepted for you today: 1 ticket")
    # the owner sends it back from Done (same path as from Review)
    assert run("ticket", "changes", tid, "Also cover the empty file", "--by", "human:tester")[0] == 0
    assert tickets.load(proj, tid)["status"] == "ready"
    rows = json.loads(run("review", "accepted", "--json")[1])["accepted"]
    assert rows[0]["sent_back"] is True


def test_a_done_ticket_a_person_accepted_cannot_be_sent_back_by_changes(proj, run, new_ticket):
    tid = _finished(proj, run, new_ticket)
    tickets.set_status(proj, tid, "done", "human:tester")
    assert run("ticket", "changes", tid, "more", "--by", "human:tester")[0] == 2


def test_morning_list_without_relay_says_not_sent(proj, run, new_ticket, facts, on):
    _finished(proj, run, new_ticket)
    reviewer.run(proj)
    code, out, _ = run("review", "accepted", "--phone", "--json")
    data = json.loads(out)
    assert code == 0 and data["sent"] is False and data.get("not_sent")


@pytest.mark.parametrize(
    "path,kind",
    [
        ("workspace/tests/test_x.py", "test"),
        ("e2e/shots.cjs", "test"),
        ("workspace/src/orch/runs.py", "code"),
        ("workspace-addons/dashboard/src/orch_dashboard/web/app.js", "look"),
        ("workspace/src/orch_ui/static/kit.css", "look"),
        ("docs/wording.md", "words"),
        ("contracts/history.md", "structure"),
        ("AGENTS.md", "structure"),
        ("workspace/src/orch/relay.py", "structure"),
    ],
)
def test_kind_of_a_file(path, kind):
    assert reviewer.kind_of(path) == kind


def test_docstrings_and_comments_are_not_words():
    files = [{"path": "workspace/src/orch/runs.py", "additions": 3, "deletions": 0}]
    added = {
        "workspace/src/orch/runs.py": [
            '    """One pass of the thing here."""',
            "    # a long comment here ok",
            "x = 1",
        ]
    }
    assert reviewer.size_reasons(files, added)[0] == []
