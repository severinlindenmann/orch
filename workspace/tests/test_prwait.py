"""orch ref wait: wait for a pull request's checks without an AI call, say GREEN or NOT green, merge on green.

The recorded cases in fixtures/prwait/ come from the helpers' pr-green script (16 Nov, PR 978 and friends):
a red check must never read as green (ORCH-35). No GitHub, no waiting: a Replay plays each case.
"""

import json
import subprocess
from pathlib import Path

import pytest

from orch import prwait, tickets

CASES = Path(__file__).parent / "fixtures" / "prwait"
PR = "https://github.com/acme/app/pull/12"
PR2 = "https://github.com/acme/app/pull/13"
HEAD = "a" * 40


def _case(name: str) -> dict:
    return json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))


# (recorded case, green?, text the verdict line must hold) - the pr-green-test.sh table, case for case
REPLAYS = [
    ("pr978-first-run", False, "banned-words FAILURE"),
    ("pr978-second-run", True, "all required checks SUCCESS (gate)"),
    ("late-second-workflow-fails", False, "banned-words FAILURE"),
    ("late-second-workflow-passes", True, "all required checks SUCCESS (gate)"),
    ("second-workflow-stuck", False, "unfinished workflow runs: rules"),
    ("draft", False, "draft"),
    ("no-checks", False, "no checks after"),
    ("gate-missing", False, "still waiting"),
    ("other-repo-skipped", False, "b SKIPPED"),
    ("other-repo-green", True, "all 1 checks SUCCESS"),
]


@pytest.mark.parametrize(("name", "green", "text"), REPLAYS)
def test_recorded_cases(name, green, text):
    v = prwait.wait(prwait.Replay(_case(name)))
    assert v.green is green, v.line()
    assert text in v.line()
    assert v.line().startswith("GREEN: " if green else "NOT green: ")


def test_every_recorded_case_is_tested():
    assert {p.stem for p in CASES.glob("*.json")} == {n for n, _, _ in REPLAYS}


def test_a_late_second_workflow_is_waited_for():
    src = prwait.Replay(_case("late-second-workflow-fails"))
    prwait.wait(src)
    assert src.n == 2  # gate was green on the first look, but the queued rules run was waited for


def test_a_case_without_polls_is_refused():
    with pytest.raises(prwait.Refused):
        prwait.Replay({"repo": "acme/app", "polls": []})


def _one(state, required=None, repo="acme/app"):
    return {
        "repo": repo,
        "isDraft": False,
        "required": required,
        "polls": [[{"name": "build", "state": "SUCCESS", "bucket": "pass"},
                   {"name": "gate", "state": "SUCCESS", "bucket": "pass"},
                   {"name": "lint", "state": state, "bucket": "fail" if state != "SKIPPED" else "skipping"}]],
    }  # fmt: skip


@pytest.mark.parametrize("state", ["FAILURE", "CANCELLED", "TIMED_OUT", "NEUTRAL", "ACTION_REQUIRED"])
@pytest.mark.parametrize("required", [None, ["gate"]])
def test_no_unfinished_or_failed_state_is_ever_green(state, required):
    v = prwait.wait(prwait.Replay(_one(state, required)))
    assert not v.green and f"lint {state}" in v.why


def test_skipped_is_green_only_with_required_checks_all_success():
    assert prwait.wait(prwait.Replay(_one("SKIPPED", ["gate"]))).green
    assert not prwait.wait(prwait.Replay(_one("SKIPPED", None))).green
    v = prwait.wait(prwait.Replay(_one("SKIPPED", ["gate", "deploy"])))
    assert not v.green and "deploy" in v.why  # a required check never reported: waited for, then not green


def test_unexpanded_draft_matrix_leftovers_are_ignored():
    case = _one("SKIPPED", ["gate"])
    case["polls"][0].append({"name": "test (${{ matrix.os }})", "state": "SKIPPED", "bucket": "skipping"})
    v = prwait.wait(prwait.Replay(case))
    assert v.green and all("${{" not in n for n, _ in v.checks)


def test_unreadable_rules_are_not_green():
    class NoRules(prwait.Replay):
        def required(self):
            raise prwait.Refused("could not read the rules of the base branch develop")

    v = prwait.wait(NoRules(_one("SUCCESS")))
    assert not v.green and "rules" in v.why


def test_a_dropped_connection_is_retried_and_other_errors_are_not(monkeypatch):
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        if len(calls) < 3:
            return subprocess.CompletedProcess(argv, 1, "", "dial tcp: connect: connection refused")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(prwait.subprocess, "run", fake)
    monkeypatch.setattr(prwait.time, "sleep", lambda s: None)
    assert prwait._run(["gh", "pr", "merge"]).stdout == "ok" and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(
        prwait.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 1, "", "HTTP 405: no"),
    )  # fmt: skip
    assert prwait._run(["gh", "pr", "merge"]).returncode == 1 and len(calls) == 1


# ---- the command, with a fake GitHub ----


class FakePull(prwait.Replay):
    """One pull request: a recorded case for its checks plus what `gh pr view` and the compare say."""

    def __init__(self, url, case, state="OPEN", behind=0, head_after=None):
        super().__init__(case)
        self.url, self.gh, self.state = url, "/fake/gh", state
        self.behind_by, self.head_after = behind, head_after
        self.views = 0

    def view(self):
        self.views += 1
        head = self.head_after if (self.head_after and self.views > 1) else HEAD
        return {"state": self.state, "isDraft": False, "baseRefName": "develop", "headRefOid": head}

    def gh_json(self, *args):
        return {"behind_by": self.behind_by}


@pytest.fixture
def fake_gh(monkeypatch):
    pulls, merges = {}, []

    def run(argv, timeout=30):
        merges.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(prwait, "Live", lambda url: pulls[url])
    monkeypatch.setattr(prwait, "_run", run)
    return pulls, merges


@pytest.fixture
def tk(new_ticket, run):
    tid = new_ticket()
    assert run("ref", "add", tid, PR)[0] == 0
    return tid


def _ref_status(root, tid, url):
    return next(r.get("status") for r in tickets.load(root, tid)["refs"] if r.get("url") == url)


def test_green_waits_writes_the_verdict_and_merges_nothing_without_merge(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    code, out, _ = run("ref", "wait", tk)
    assert code == 0 and merges == []
    lines = out.strip().splitlines()
    assert lines[-2].startswith(f"Checks of {PR}: GREEN: ") and lines[-1].startswith("Next: GREEN")
    assert _ref_status(proj, tk, PR) == "checks passed"
    assert "GREEN" in json.dumps(tickets.load(proj, tk)["history"])


def test_red_is_exit_one_and_said_on_the_ticket(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-first-run"))
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == []
    *_, verdict, last = out.strip().splitlines()
    assert "NOT green" in verdict and "banned-words FAILURE" in verdict
    assert last.startswith(
        "Next: NOT green"
    )  # through a pipe only the text is left: the last line says it too
    assert _ref_status(proj, tk, PR) == "checks failed"


def test_merge_on_green_takes_only_the_checked_commit(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 0, out
    assert out.strip().splitlines()[-1] == "Next: GREEN and merged: finish the ticket"
    assert merges == [["/fake/gh", "pr", "merge", PR, "--merge", "--match-head-commit", HEAD]]
    assert _ref_status(proj, tk, PR) == "merged"


def test_behind_its_base_is_never_merged(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"), behind=2)
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == [] and "behind develop" in out


def test_a_new_commit_while_waiting_is_not_merged(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"), head_after="b" * 40)
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == [] and "new commit" in out


def test_several_in_order_stop_at_the_first_red(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    assert run("ref", "add", tk, PR2)[0] == 0
    pulls[PR] = FakePull(PR, _case("pr978-first-run"))
    pulls[PR2] = FakePull(PR2, _case("pr978-second-run"))
    code, out, _ = run("ref", "wait", tk, "--merge", "--json")
    assert code == 1 and merges == []
    got = json.loads(out)
    assert [g["url"] for g in got] == [PR] and got[0]["green"] is False


def test_several_in_order_all_merged(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    assert run("ref", "add", tk, PR2)[0] == 0
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    pulls[PR2] = FakePull(PR2, _case("other-repo-green"))
    code, _, _ = run("ref", "wait", tk, "2", "1", "--merge")
    assert code == 0
    assert [m[3] for m in merges] == [PR2, PR]  # the order given


def test_merged_and_closed_refs_are_skipped_by_default(proj, tk, run, fake_gh):
    pulls, _ = fake_gh
    assert run("ref", "set", tk, "1", "--status", "merged")[0] == 0
    code, _, err = run("ref", "wait", tk)
    assert code == 2 and "no open GitHub pull request" in err


def test_a_ticket_without_the_pull_request_is_refused(tk, run, fake_gh):
    code, _, err = run("ref", "wait", tk, "https://github.com/acme/app/pull/99")
    assert code == 2 and "orch ref add" in err


def test_a_persons_merge_card_is_never_merged_here(proj, tk, run, fake_gh, monkeypatch):
    pulls, merges = fake_gh

    t = tickets.load(proj, tk)
    t["questions"] = [
        {"id": "q9", "question": "Merge?", "answer": None, "action": {"merge": PR},
         "card": {"kind": "link", "open": PR, "ok_label": "Merge"}}
    ]  # fmt: skip
    monkeypatch.setattr(tickets, "load", lambda root, tid, *a, **k: t)
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    code, _, err = run("ref", "wait", tk, "--merge")
    assert code == 2 and merges == [] and "Merge card" in err
