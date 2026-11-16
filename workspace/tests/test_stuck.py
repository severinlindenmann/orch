"""Work that stopped short shows in `orch needs` (ORCH-26): a ticket in Review whose pull request passed its
checks with no helper on it, and a helper idle at its prompt. GitHub is asked only by the detached look."""

import json
import subprocess
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from orch import ghmerge, runs, runwatch, stuck, tickets

PR = "https://github.com/acme/app/pull/12"
HEAD = "a" * 40
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/needs.schema.json").read_text(encoding="utf-8")
)
OK = {"status": "COMPLETED", "conclusion": "SUCCESS"}


@pytest.fixture(autouse=True)
def no_real_look(monkeypatch):
    """Never a detached look at the real GitHub from a test; `spawned` counts the looks orch wanted."""
    spawned = []
    monkeypatch.setattr(stuck, "_spawn_look", lambda root: spawned.append(root))
    monkeypatch.setattr(stuck.shutil, "which", lambda name: "/fake/bin/gh")
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    return spawned


@pytest.fixture
def child():
    """A throwaway process standing for a run's wrapper (never the test process itself)."""
    p = subprocess.Popen(["sleep", "120"])
    yield p.pid
    p.kill()
    p.wait()


def _since(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _live(proj, tid, state, pid, idle_for=300):
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
            "started_at": _since(3000),
            "renewed_at": _since(3000),
            "live": {"state": state, "since": _since(idle_for)},
        },
    )


def _rows(run, kind):
    code, out, err = run("needs", "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert list(Draft202012Validator(SCHEMA).iter_errors(rows)) == []
    return [r for r in rows if r["kind"] == kind]


def _in_review(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ref", "add", tid, PR)[0] == 0
    tickets.apply_op(proj, tid, lambda t: t.update(status="review"), by="agent:x")
    return tid


def _seen(proj, green=True, state="OPEN", at=None):
    now = time.time() if at is None else at
    stuck._write(proj, {"pulls": {PR: {"state": state, "head": HEAD, "green": green, "at": now}}})


# ---------------------------------------------------------------- the checks of a pull request


@pytest.mark.parametrize(
    "rollup,want",
    [
        ([OK, {"status": "COMPLETED", "conclusion": "SKIPPED"}], True),
        ([OK, {"state": "SUCCESS"}], True),  # a commit status next to a check run
        ([], False),  # no checks is not passed
        ([{"status": "COMPLETED", "conclusion": "SKIPPED"}], False),  # nothing actually ran
        ([OK, {"status": "IN_PROGRESS", "conclusion": ""}], False),
        ([OK, {"status": "COMPLETED", "conclusion": "FAILURE"}], False),
        ([OK, {"state": "PENDING"}], False),
        (None, False),
    ],
)
def test_passed_needs_every_check_finished_and_none_failed(rollup, want):
    assert ghmerge.passed(rollup) is want


def test_only_the_newest_run_of_a_check_counts():
    """A workflow that ran twice on the commit (once while the pull request was a draft): the older run's
    failure does not count, a newer failure does."""
    old = {"name": "build", "workflowName": "ci", "status": "COMPLETED", "startedAt": "2026-11-16T11:28:36Z"}
    new = {**old, "startedAt": "2026-11-16T11:43:09Z"}
    assert ghmerge.passed([{**old, "conclusion": "FAILURE"}, {**new, "conclusion": "SUCCESS"}]) is True
    assert ghmerge.passed([{**new, "conclusion": "SUCCESS"}, {**old, "conclusion": "FAILURE"}]) is True
    assert ghmerge.passed([{**old, "conclusion": "SUCCESS"}, {**new, "conclusion": "FAILURE"}]) is False
    other = {**old, "workflowName": "mobile", "conclusion": "FAILURE"}  # the same name in another workflow
    assert ghmerge.passed([{**new, "conclusion": "SUCCESS"}, other]) is False


def _fake_view(monkeypatch, **fields):
    data = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "statusCheckRollup": [OK], **fields}
    calls = []

    def fake(argv, **kw):
        calls.append(argv[1:])
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: "/fake/bin/gh")
    monkeypatch.setattr(ghmerge.subprocess, "run", fake)
    return calls


def test_checks_reads_state_head_and_green(monkeypatch):
    calls = _fake_view(monkeypatch)
    assert ghmerge.checks(PR) == {"state": "OPEN", "head": HEAD, "green": True}
    assert calls == [["pr", "view", PR, "--json", ghmerge.JSON_CHECKS]]  # reading only
    _fake_view(monkeypatch, isDraft=True)
    assert ghmerge.checks(PR)["green"] is False  # a draft is never ready
    _fake_view(monkeypatch, state="MERGED")
    assert ghmerge.checks(PR) == {"state": "MERGED", "head": HEAD, "green": False}


def test_checks_without_gh_is_none(monkeypatch):
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: None)
    assert ghmerge.checks(PR) is None
    assert ghmerge.checks("https://example.com/x") is None


# ---------------------------------------------------------------- Review, checks passed, no helper


def test_review_with_a_green_pull_request_and_no_helper_is_a_row(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _seen(proj)
    (row,) = _rows(run, "helper:unmerged")
    assert row["id"] == f"core:unmerged:{tid}" and row["ticket"] == tid and row["tone"] == "needs-you"
    assert row["pull"] == {"url": PR, "head": HEAD} and row["helper"] == "none"
    assert "passed its checks but was not merged" in row["text"]
    assert row["cli"] == f"orch run start {tickets.load(proj, tid)['key']}"
    assert "not merged" in run("needs")[1]


def test_no_row_before_github_was_asked_and_one_detached_look_starts(proj, run, new_ticket, no_real_look):
    _in_review(proj, run, new_ticket)
    assert _rows(run, "helper:unmerged") == []
    assert no_real_look == [proj]
    assert _rows(run, "helper:unmerged") == []  # asked a moment ago: no second look
    assert no_real_look == [proj]


def test_no_look_without_gh(proj, run, new_ticket, no_real_look, monkeypatch):
    _in_review(proj, run, new_ticket)
    monkeypatch.setattr(stuck.shutil, "which", lambda name: None)
    assert _rows(run, "helper:unmerged") == [] and no_real_look == []


@pytest.mark.parametrize("seen", [{"green": False}, {"state": "MERGED", "green": False}])
def test_red_or_merged_pull_request_is_no_row(proj, run, new_ticket, seen):
    _in_review(proj, run, new_ticket)
    _seen(proj, **seen)
    assert _rows(run, "helper:unmerged") == []


def test_not_in_review_or_recorded_merged_is_no_row(proj, run, new_ticket):
    tid = new_ticket()  # Working, not Review
    run("ref", "add", tid, PR)
    _seen(proj)
    assert _rows(run, "helper:unmerged") == []
    tid = _in_review(proj, run, new_ticket)
    assert len(_rows(run, "helper:unmerged")) == 1
    assert run("ref", "set", tid, PR, "--status", "merged")[0] == 0
    assert _rows(run, "helper:unmerged") == []


def test_a_helper_at_work_is_no_row_an_idle_one_is(proj, run, new_ticket, child):
    tid = _in_review(proj, run, new_ticket)
    _seen(proj)
    _live(proj, tid, "working", child)
    assert _rows(run, "helper:unmerged") == []
    _live(proj, tid, "idle", child)
    (row,) = _rows(run, "helper:unmerged")
    assert row["helper"] == "idle"
    assert _rows(run, "helper:idle") == []  # a finished ticket's quiet session is not the idle case


def test_look_asks_github_once_per_pull_request_and_keeps_the_answer(proj, run, new_ticket, monkeypatch):
    _in_review(proj, run, new_ticket)
    asked = []
    monkeypatch.setattr(
        ghmerge, "checks", lambda url: asked.append(url) or {"state": "OPEN", "head": HEAD, "green": True}
    )
    assert run("needs", "--look-at-pulls")[0] == 0
    assert asked == [PR]
    assert run("needs", "--look-at-pulls")[0] == 0
    assert asked == [PR]  # fresh enough: GitHub is not asked again
    assert len(_rows(run, "helper:unmerged")) == 1
    old = time.time() - stuck.CHECK_EVERY - 5
    since = stuck._read(proj)["pulls"][PR]["green_since"]
    stuck._write(proj, {"pulls": {PR: {**stuck._read(proj)["pulls"][PR], "at": old}}})
    run("needs", "--look-at-pulls")
    assert asked == [PR, PR] and stuck._read(proj)["pulls"][PR]["green_since"] == since


def test_look_that_cannot_read_github_is_kept_as_unknown(proj, run, new_ticket, monkeypatch):
    _in_review(proj, run, new_ticket)
    monkeypatch.setattr(ghmerge, "checks", lambda url: None)
    run("needs", "--look-at-pulls")
    assert stuck._read(proj)["pulls"][PR]["state"] == "UNKNOWN"
    assert _rows(run, "helper:unmerged") == []


# ---------------------------------------------------------------- a helper idle at its prompt


def test_idle_helper_is_a_row_after_ten_minutes(proj, run, new_ticket, child):
    tid = new_ticket()
    _live(proj, tid, "idle", child, idle_for=stuck.IDLE_MINUTES * 60 - 60)
    assert _rows(run, "helper:idle") == []
    _live(proj, tid, "idle", child, idle_for=14 * 60)
    (row,) = _rows(run, "helper:idle")
    assert row["id"] == f"core:idle:{tid}" and row["tone"] == "warn" and row["ticket"] == tid
    assert row["text"] == "The helper has been idle for 14 min with nothing running."
    assert row["cli"].startswith(f"orch run send {tickets.load(proj, tid)['key']} ")


def test_idle_row_not_while_it_works_runs_a_command_or_waits_for_a_person(
    proj, run, new_ticket, child, monkeypatch
):
    tid = new_ticket()
    _live(proj, tid, "working", child, idle_for=3000)
    assert _rows(run, "helper:idle") == []
    _live(proj, tid, "idle", child, idle_for=3000)
    rec = runs.read(proj, tid)
    rec["agent_pid"] = 100
    runs._write(proj, rec)
    table = [(100, 1, 900, "claude"), (200, 100, 400, "/bin/zsh -c x"), (300, 200, 399, "bash pr-green.sh 1")]
    monkeypatch.setattr(runwatch, "_table", lambda: table)
    assert _rows(run, "helper:idle") == []  # it watches the checks: waiting, not stuck
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    assert len(_rows(run, "helper:idle")) == 1
    assert run("ask", tid, "Ship it?", "--option", "Yes", "--option", "No", "--by", "agent:x")[0] == 0
    assert _rows(run, "helper:idle") == []  # the open question is the row


def test_a_broken_run_record_never_breaks_needs(proj, run, new_ticket, monkeypatch):
    new_ticket()
    monkeypatch.setattr(stuck, "_helper", lambda root, t: 1 / 0)
    code, out, _ = run("needs", "--json")
    assert code == 0 and json.loads(out) == []


# ---------------------------------------------------------------- orch ref merge: a person's Merge


class FakeGh:
    def __init__(self):
        self.calls, self.state, self.review, self.rollup = [], "OPEN", "", [OK]

    def __call__(self, argv, env=None, **kw):
        args = argv[1:]
        self.calls.append(args)
        if args[:2] == ["api", "user"]:
            return subprocess.CompletedProcess(argv, 0, "pat-gh\n", "")
        if args[:2] == ["pr", "view"] and "--jq" not in args:  # the look at its checks
            data = {
                "state": self.state,
                "isDraft": False,
                "headRefOid": HEAD,
                "statusCheckRollup": self.rollup,
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, f"{self.state}\t{self.review}\t{HEAD}\n", "")
        if args[:2] == ["pr", "merge"]:
            self.state = "MERGED"
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(args)

    @property
    def merges(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: "/fake/bin/gh")
    monkeypatch.setattr(ghmerge.subprocess, "run", fake)
    return fake


def test_ref_merge_merges_the_shown_commit_and_marks_the_reference(proj, run, new_ticket, gh):
    tid = _in_review(proj, run, new_ticket)
    _seen(proj)
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat", "--json")
    assert code == 0, out + err
    assert json.loads(out) == {"merged": True, "already": False, "url": PR}
    assert ["pr", "merge", PR, "--merge", "--match-head-commit", HEAD] in gh.calls
    t = tickets.load(proj, tid)
    assert t["refs"][0]["status"] == "merged"
    assert _rows(run, "helper:unmerged") == []  # settled: the row is gone
    assert "Merged the pull request on GitHub as pat-gh" in run("ticket", "show", tid)[1]


def test_ref_merge_refuses_a_helper_and_a_changed_pull_request(proj, run, new_ticket, gh, monkeypatch):
    tid = _in_review(proj, run, new_ticket)
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "agent:x")
    assert code == 2 and "Only a person merges this" in out + err
    monkeypatch.setenv("CLAUDECODE", "1")  # a person's name does not help inside a helper's tool
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat")
    assert code == 2 and "Only a person merges this" in out + err
    monkeypatch.delenv("CLAUDECODE")
    code, out, err = run("ref", "merge", tid, "1", "--head", "b" * 40, "--by", "human:pat")
    assert code == 2 and "changed after it was shown" in out + err
    code, out, err = run("ref", "merge", tid, "https://github.com/acme/app/pull/99", "--head", HEAD)
    assert code == 2
    assert gh.merges == []
    assert tickets.load(proj, tid)["refs"][0].get("status") is None


def test_ref_merge_asks_github_again_and_never_trusts_the_kept_look(proj, run, new_ticket, gh):
    """The kept look is a file a helper can write: a row made from a faked "passed" merges nothing."""
    tid = _in_review(proj, run, new_ticket)
    _seen(proj)  # the file says passed
    gh.rollup = [OK, {"status": "COMPLETED", "conclusion": "FAILURE"}]  # GitHub says a check failed
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat")
    assert code == 2 and "checks have not all passed" in out + err and gh.merges == []
    gh.rollup, gh.state = [OK], "CLOSED"
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat")
    assert code == 2 and "not open on GitHub" in out + err and gh.merges == []
    gh.state = "OPEN"
    gh.rollup = [{"status": "IN_PROGRESS", "conclusion": ""}]
    assert run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat")[0] == 2 and gh.merges == []


def test_ref_merge_never_adds_the_persons_review(proj, run, new_ticket, gh):
    tid = _in_review(proj, run, new_ticket)
    gh.review = "REVIEW_REQUIRED"  # the Merge card adds a review here; one click on Home does not
    code, out, err = run("ref", "merge", tid, PR, "--head", HEAD, "--by", "human:pat")
    assert code == 0, out + err
    assert [c for c in gh.calls if c[:3] == ["api", "-X", "POST"]] == [] and len(gh.merges) == 1


# ---------------------------------------------------------------- the helper's finish step


def test_finishing_with_an_open_pull_request_prints_the_merge_step(proj, run, new_ticket):
    tid = new_ticket()
    run("ref", "add", tid, PR)
    run("check", "add", tid, "Build it")
    run("check", "done", tid, "c1", "--note", "built", "--summary", "Built.", "--by", "agent:x")
    code, out, err = run("ticket", "status", tid, "done", "--by", "agent:x")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["status"] == "review"  # a hint, never a block
    assert "Next: the pull request is still open" in out and "wait for them and merge it" in out
    assert "--status merged" in out


def test_finishing_with_a_merged_pull_request_prints_no_merge_step(proj, run, new_ticket):
    tid = new_ticket()
    run("ref", "add", tid, PR)
    run("ref", "set", tid, PR, "--status", "merged")
    run("check", "add", tid, "Build it")
    run("check", "done", tid, "c1", "--note", "built", "--summary", "Built.", "--by", "agent:x")
    code, out, _ = run("ticket", "status", tid, "done", "--by", "agent:x")
    assert code == 0 and "still open" not in out
