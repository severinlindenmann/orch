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
            "merged_at": "2999-01-01T00:00:00Z",  # after the ticket was made
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


def _finished(proj, run, new_ticket, pr=PR, review=True, title="Fix the stale run record"):
    tid = new_ticket(title)
    assert run("ticket", "tidy", tid, title, "--description", "d", "--done-when",
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
    assert last["text"].startswith("Accepted for you by the Reviewer: ")
    assert "Pull request #12 merged with all checks green" in last["text"]
    assert "(2 files, 104 lines changed)" in last["text"]
    for jargon in ("small fix", "second look", "points shown", "Could not match"):
        assert jargon not in last["text"]
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


def test_an_open_release_into_main_waits_for_the_owner(proj, run, new_ticket, facts, on, no_starts):
    # ORCH-1835: a release walk links the release pull request into main; only the owner merges it
    facts["facts"].update(state="OPEN", release=True, merged_at=None)
    tid = _finished(proj, run, new_ticket)
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave" and res.get("owner") is True
    assert tickets.load(proj, tid)["status"] == "review" and no_starts == []
    assert _lines(proj, tid)[-1] == (
        "Left for you by the Reviewer: release pull request #12 waits for your merge into main; "
        "the work itself is finished."
    )
    assert reviewer.plain_left(res["why"]) == "Release pull request #12 waits for your merge into main."


def test_a_merged_release_is_not_sized_and_the_kind_reason_says_who_acts(proj, run, new_ticket, facts, on):
    facts["facts"].update(release=True)  # merged, green: still never this ticket's change
    tid = _finished(proj, run, new_ticket)
    assert run("ticket", "kind", tid, "other", "--by", "human:tester")[0] == 0
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave"
    assert res["why"] == (
        "you accept other work yourself here; "
        "the Reviewer only accepts bug and small bug work by itself (Settings)."
    )
    assert reviewer.plain_left(res["why"]) == "You accept other work yourself here."


HEAD = "f30ff39449b1aa00"


def _walk(proj, run, new_ticket, facts, verdict="pass", commit=HEAD[:12], state="OPEN", keeper=False):
    """ORCH-1835: a finished release 47 walk ticket linking the open release pull request into main, with the
    result its helper recorded (verdict None: nothing recorded); keeper: the open release names it."""
    facts["facts"].update(
        state=state, release=True, merged_at=None if state == "OPEN" else "2999-01-01T00:00:00Z"
    )
    if verdict:
        res = {
            "47": {
                "clickthrough": {
                    "verdict": verdict,
                    "line": "11 of 16 steps pass, 0 blockers",
                    "commit": commit,
                    "by": "agent:claude",
                    "at": "2026-11-24T02:22:10+00:00",
                }
            }
        }
        d = runs.run_dir(proj)
        d.mkdir(parents=True, exist_ok=True)
        (d / "release-walks.json").write_text(json.dumps(res), encoding="utf-8")
    tid = _finished(proj, run, new_ticket, title="Release 47: clickthrough walk")
    if keeper:
        rel = {"release": {"n": 47, "sha": HEAD, "walks": {"clickthrough": {"ticket": tid}}}}
        (runs.run_dir(proj) / "release-keeper.json").write_text(json.dumps(rel), encoding="utf-8")
    return tid


def test_a_passed_walk_waits_for_the_owners_merge_into_main(proj, run, new_ticket, facts, on, no_starts):
    tid = _walk(proj, run, new_ticket, facts)
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave" and res.get("owner") is True and no_starts == []
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1] == (
        "Left for you by the Reviewer: walk recorded as passed, release pull request #12 waits for your "
        "merge into main."
    )
    assert reviewer.plain_left(res["why"]) == (
        "Walk recorded as passed, release pull request #12 waits for your merge into main."
    )


@pytest.mark.parametrize(
    "verdict,commit,keeper,sha",
    [
        (None, None, False, "<sha>"),
        (None, None, True, "f30ff39449b1"),
        ("pass", "0123456789ab", True, "f30ff39449b1"),
    ],
)
def test_a_walk_with_no_result_for_its_commit_goes_back(
    proj, run, new_ticket, facts, on, verdict, commit, keeper, sha
):
    # the keeper's open release knows its commit: a result for another cut of the same number is no result
    tid = _walk(proj, run, new_ticket, facts, verdict=verdict, commit=commit, keeper=keeper)
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "back"
    why = res["why"]
    assert why.startswith("work is missing: the clickthrough walk of release 47 has no result recorded")
    assert "orch github release-walk 47 clickthrough pass|fail" in why and f"--commit {sha})" in why
    assert "not merged yet" not in res["why"] and tickets.load(proj, tid)["status"] != "done"


def test_a_failed_walk_is_left_for_the_owner_not_finished(proj, run, new_ticket, facts, on, no_starts):
    tid = _walk(proj, run, new_ticket, facts, verdict="fail")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave" and res.get("owner") is True and no_starts == []
    assert res["why"] == (
        "the clickthrough walk of release 47 failed: 11 of 16 steps pass, 0 blockers; "
        "release pull request #12 is yours to decide."
    )
    assert "finished" not in res["why"] and tickets.load(proj, tid)["status"] == "review"


def test_a_passed_walk_with_the_release_merged_is_accepted(proj, run, new_ticket, facts, on):
    tid = _walk(proj, run, new_ticket, facts, state="MERGED")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "accept", res
    assert res["why"] == (
        "The clickthrough walk of release 47 is recorded as passed and release pull request #12 is merged."
    )
    assert tickets.load(proj, tid)["status"] == "done"


def test_a_passed_walk_with_the_release_closed_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    _walk(proj, run, new_ticket, facts, state="CLOSED")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave" and res["why"] == "release pull request #12 was closed without merging."


def test_walk_of_reads_the_keepers_open_release_first(proj):
    from orch import releasekeeper

    d = runs.run_dir(proj)
    d.mkdir(parents=True, exist_ok=True)
    keeper = {"release": {"n": 48, "sha": "abc1234ff", "walks": {"install": {"ticket": "t_abc"}}}}
    (d / "release-keeper.json").write_text(json.dumps(keeper), encoding="utf-8")
    walks = {"48": {"install": {"verdict": "pass", "commit": "abc1234"}}}
    (d / "release-walks.json").write_text(json.dumps(walks), encoding="utf-8")
    got = releasekeeper.walk_of(proj, {"id": "t_abc", "title": "Walk the install again"})
    assert got == {
        "n": 48,
        "name": "install",
        "commit": "abc1234ff",
        "result": {"verdict": "pass", "commit": "abc1234"},
    }
    assert releasekeeper.walk_of(proj, {"id": "t_zzz", "title": "Fix the stale run record"}) is None
    assert releasekeeper.walk_of(proj, {"id": "t_zzz", "title": "Release 9: services walk"})["result"] is None
    # a walk ticket known by its title of the open release's number: still checked against its commit
    (d / "release-walks.json").write_text(
        json.dumps({"48": {"install": {"verdict": "pass", "commit": "9999999"}}})
    )
    assert releasekeeper.walk_of(proj, {"id": "t_new", "title": "Release 48: install walk"})["result"] is None


def test_pr_facts_marks_a_release_into_main(monkeypatch):
    from types import SimpleNamespace

    from orch import ghmerge

    seen = []

    def gh(_gh, args, _t):
        seen.append(args)
        body = {"number": 7, "state": "MERGED", "statusCheckRollup": [], "mergedAt": "2026-01-01T00:00:00Z",
                "files": [{"path": "workspace/src/orch/runs.py"}], "baseRefName": "main",
                "headRefName": "release/part7"}  # fmt: skip
        return SimpleNamespace(returncode=0, stdout=json.dumps(body))

    monkeypatch.setattr(reviewer.shutil, "which", lambda _n: "/bin/gh")
    monkeypatch.setattr(ghmerge, "_gh_plain", gh)
    f = reviewer.pr_facts("https://github.com/acme/app/pull/7")
    assert f["release"] is True and f["added"] is None
    assert len(seen) == 1  # no diff read for a release: it is never sized


def test_a_pull_request_merged_before_the_ticket_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    facts["facts"]["merged_at"] = "2020-01-01T00:00:00Z"
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1].endswith("was merged before this ticket was made.")


def test_code_that_is_not_python_is_left_for_the_owner():
    files = [{"path": "scripts/tidy.sh", "additions": 2, "deletions": 0}]
    assert "cannot read" in reviewer.size_reasons(files, {})[0][0]


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
    assert "the change is small" in rows[0]["why"]
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
        ("contracts/history.md", "security"),
        ("workspace/src/orch/secretscan.py", "security"),
        ("workspace/src/orch/phone_view.py", "security"),
        ("workspace/src/orch/pagesession.py", "security"),
        ("workspace/src/orch/syncgate.py", "security"),
        ("workspace-addons/sync/src/orch_sync/push.py", "security"),
        ("workspace/tests/test_runs.py", "test"),
        ("workspace/src/orch/test_helpers.py", "code"),
        ("contracts/tests/case.md", "security"),
        ("AGENTS.md", "structure"),
        ("workspace/src/orch/relay.py", "structure"),
        ("workspace/src/orch/fixtures/evil.py", "code"),
        ("workspace/src/orch/tests_helper.py", "code"),
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


def test_what_may_leave_the_machine_stays_for_the_owner(proj, run, new_ticket, facts, on):
    facts["facts"]["files"] = [{"path": "workspace/src/orch/secretscan.py", "additions": 2, "deletions": 1}]
    facts["facts"]["added"] = {"workspace/src/orch/secretscan.py": ["    x = 1"]}
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1] == "Left for you by the Reviewer: security: needs a second look (1 file)."


# ---- ORCH-128: evidence decides, not the wording of the Done when sentence

REAL = {  # ORCH-112 / ORCH-113 as the Reviewer saw them: no task carries `covers`, the work is in other words
    "orch112": (
        "With 20 queued tickets and no limit set, helpers start in steps and stop on high load, disk or "
        "subscription limits.",
        [
            (
                "Find the cause in the report and the code",
                "Cause found: with no limit set the start line let all 20 queued tickets go",
            ),
            (
                "Give start line a default ceiling: one new helper per pass, none while load or disk is high",
                "Always-on ceiling: no start while load is high",
            ),
            (
                "Add a test: 20 queued tickets, no limit set, they start in steps",
                "3 new tests, helpers start in steps",
            ),
        ],
    ),
    "orch113": (
        "A Choose card with text options (labels with spaces) can be answered from the page, and a refused "
        "click says why in plain words.",
        [
            (
                "Find the cause of the refused Choose click",
                "Cause: the servers only accept short ids, text options were refused",
            ),
            (
                "Fix it, show a plain message when a click is refused, add a test",
                "Regex relaxed, tests added, card options answered from the page",
            ),
        ],
    ),
    "unbuilt": (
        "The weekly export is sent to the owner by email.",
        [("Fix the stale record", "stale record fixed")],
    ),
}


def _real(proj, run, new_ticket, name, proves=None):
    done_when, tasks = REAL[name]
    tid = new_ticket("Fix " + name)
    assert run("ticket", "tidy", tid, "Fix " + name, "--description", "d", "--done-when", done_when,
               "--by", "human:tester")[0] == 0  # fmt: skip
    for i, (text, said) in enumerate(tasks, 1):
        assert run("check", "add", tid, text, "--by", "human:tester")[0] == 0
        extra = ["--proves", proves] if proves and i == 1 else []
        args = ["--pr", PR, "--summary", said, *extra, "--by", "human:tester"]
        assert run("check", "done", tid, f"c{i}", *args)[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    return tid


@pytest.mark.parametrize("name", ["orch112", "orch113"])
def test_work_in_other_words_is_accepted_with_a_could_not_match_note(proj, run, new_ticket, facts, on, name):
    tid = _real(proj, run, new_ticket, name)
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "accept", res
    assert "Could not match" not in res["why"] and "merged with all checks green" in res["why"]
    assert tickets.load(proj, tid)["status"] == "done"


def test_a_part_with_no_task_is_left_for_the_owner_no_helper(proj, run, new_ticket, facts, on, no_starts):
    """ORCH-220: a Done when part no task covers is a question for the owner, not work for a helper."""
    tid = _real(proj, run, new_ticket, "unbuilt")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave", res
    t = tickets.load(proj, tid)
    assert t["status"] == "review" and no_starts == []
    assert not runs.undelivered(proj, tid)  # no message for a helper
    assert [c["text"] for c in t["checklist"]] == ["Fix the stale record"]  # no new task added
    assert _lines(proj, tid)[-1] == (
        "Left for you by the Reviewer: Done when part 'The weekly export is sent to the owner by email.' has "
        "no task (looked for: weekly, export, sent, owner, email); send it back if that work is missing."
    )


def test_a_part_with_no_task_is_decided_once(proj, run, new_ticket, facts, on, no_starts):
    tid = _real(proj, run, new_ticket, "unbuilt")
    reviewer.run(proj)
    before = len(_lines(proj, tid))
    assert reviewer.run(proj)["actions"] == []  # quiet ticket: no second line, still no helper
    assert len(_lines(proj, tid)) == before and no_starts == []


def test_an_open_pull_request_in_the_queue_starts_no_helper(
    proj, run, new_ticket, facts, on, no_starts, queue_on
):
    """ORCH-815: the queue merges it or wakes the helper with its reason; sending it back only woke a helper
    that could do nothing but wait."""
    facts["facts"]["state"] = "OPEN"
    tid = _finished(proj, run, new_ticket)
    url = PR
    qfile = proj / ".orch" / "addons" / "pull-requests" / "queue.json"
    qfile.parent.mkdir(parents=True, exist_ok=True)
    qfile.write_text(json.dumps({"entries": [{"url": url, "state": "running", "ticket": tid}]}))
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review" and no_starts == []
    qfile.write_text(json.dumps({"entries": [{"url": url, "state": "out", "ticket": tid}]}))
    reviewer.run(proj)  # out of the queue and still open: back to the helper as before
    assert tickets.load(proj, tid)["status"] == "ready" and no_starts == [tid]


def test_missing_work_goes_back_even_with_a_part_with_no_task(proj, run, new_ticket, facts, on, no_starts):
    facts["facts"]["state"] = "OPEN"
    tid = _real(proj, run, new_ticket, "unbuilt")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "back" and no_starts == [tid]
    assert "pull request #12 is not merged yet" in res["why"] and "Done when part" not in res["why"]


def test_two_parts_with_no_task_are_counted_in_one_line(proj, run, new_ticket, facts, on):
    tid = new_ticket("Two parts")
    assert run("ticket", "tidy", tid, "Two parts", "--description", "d", "--done-when",
               "The weekly export is sent by email. The invoices are archived yearly.",
               "--by", "human:tester")[0] == 0  # fmt: skip
    assert run("check", "add", tid, "Fix the stale record", "--by", "human:tester")[0] == 0
    assert run("check", "done", tid, "c1", "--pr", PR, "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    res = reviewer.run(proj)["actions"][0]
    assert res["verdict"] == "leave", res
    assert "(and 1 more); send it back if that work is missing." in res["why"]


def test_proves_links_a_part_to_a_finished_task_and_no_note_is_left(proj, run, new_ticket, facts, on):
    tid = _real(proj, run, new_ticket, "orch113", proves=REAL["orch113"][0])
    assert tickets.proof_state(tickets.load(proj, tid))["uncovered"] == []
    assert reviewer.run(proj)["actions"][0]["verdict"] == "accept"


def test_proves_counts_only_with_a_finished_task(proj, run, new_ticket):
    tid = new_ticket("Open one")
    run(
        "ticket",
        "tidy",
        tid,
        "Open one",
        "--description",
        "d",
        "--done-when",
        "It works.",
        "--by",
        "human:tester",
    )
    run("check", "add", tid, "Do it", "--by", "human:tester")
    assert tickets.proof_state(tickets.load(proj, tid))["uncovered"] == ["It works."]
    run("check", "done", tid, "c1", "--note", "ok", "--proves", "It works.", "--by", "human:tester")
    assert tickets.proof_state(tickets.load(proj, tid))["uncovered"] == []


def test_plain_verdict_one_sentence_without_stutter_or_chained_colons():
    f = reviewer.plain_verdict
    tail = " Finish it and send the ticket to Review again."
    said = "The Reviewer found work missing: work is missing: the check on 'X' failed."
    assert f(said + tail) == "The check on 'X' failed."
    said = (
        "The Auto Reviewer found work missing (screen work): pictures at 1280, 1920 and 390 px wide: "
        "(no picture says 1920, 390 px)."
    )
    assert f(said + tail) == "Pictures at 1920 and 390 px are missing."
    assert f("data work, all 9 points shown.") == "All 9 points of this data work are shown."
    assert f("task 'Do it': (not done)") == "Task 'Do it' is not done."
    assert f("") == ""


def test_only_the_newest_verdict_of_a_ticket_counts_older_ones_are_earlier(proj, run, new_ticket):
    tid = new_ticket("Two verdicts")

    def op(t):
        accepted = tickets.ACCEPTED_LINE + "code work, all 2 points shown."
        back = tickets.SENT_BACK_LINE + "The Reviewer found work missing: work is missing: x. Finish it"
        tickets.add_history(t, reviewer.BY, accepted, at="2026-11-20T10:00:00Z")
        tickets.add_history(t, reviewer.BY, back, at="2026-11-21T10:00:00Z")

    tickets.apply_op(proj, tid, op, by=reviewer.BY)
    rows = [r for r in reviewer.accepted(proj, "2000-01-01T00:00:00Z") if r["ticket"] == tid]
    assert [bool(r.get("back")) for r in rows] == [True, False]
    assert rows[0]["why"] == "X." and not rows[0].get("earlier")
    assert rows[1].get("earlier") is True and rows[1]["undo"] is None and rows[1]["sent_back"] is False
    assert rows[1]["why"] == "All 2 points of this code work are shown."
