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
    ("pr978-second-run", True, "all required checks SUCCESS"),
    ("late-second-workflow-fails", False, "banned-words FAILURE"),
    ("late-second-workflow-passes", True, "all required checks SUCCESS"),
    ("second-workflow-stuck", False, "unfinished workflow runs: rules"),
    ("draft", False, "draft"),
    ("no-checks", False, "no checks after"),
    ("required-check-missing", False, "required check(s) never reported"),
    ("other-repo-skipped", False, "b SKIPPED"),
    ("other-repo-green", True, "all 1 checks SUCCESS"),
    ("release-into-main", True, "the base branch has no required checks: the default branch's passed"),
    ("release-into-main-red", False, "FAILURE"),
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
    assert src.n == 2  # required check green at first, the queued rules run still waited for


def test_a_case_without_polls_is_refused():
    with pytest.raises(prwait.Refused):
        prwait.Replay({"repo": "acme/app", "polls": []})


def _one(state, required=None, repo="acme/app"):
    return {
        "repo": repo,
        "isDraft": False,
        "required": required,
        "polls": [[{"name": "build", "state": "SUCCESS", "bucket": "pass"},
                   {"name": "required", "state": "SUCCESS", "bucket": "pass"},
                   {"name": "lint", "state": state, "bucket": "fail" if state != "SKIPPED" else "skipping"}]],
    }  # fmt: skip


@pytest.mark.parametrize("state", ["FAILURE", "CANCELLED", "TIMED_OUT", "NEUTRAL", "ACTION_REQUIRED"])
@pytest.mark.parametrize("required", [None, ["required"]])
def test_no_unfinished_or_failed_state_is_ever_green(state, required):
    v = prwait.wait(prwait.Replay(_one(state, required)))
    assert not v.green and f"lint {state}" in v.why


def test_skipped_is_green_only_with_required_checks_all_success():
    assert prwait.wait(prwait.Replay(_one("SKIPPED", ["required"]))).green
    assert not prwait.wait(prwait.Replay(_one("SKIPPED", None))).green
    v = prwait.wait(prwait.Replay(_one("SKIPPED", ["required", "deploy"])))
    assert not v.green and "deploy" in v.why  # a required check never reported: waited for, then not green


def test_unexpanded_draft_matrix_leftovers_are_ignored():
    case = _one("SKIPPED", ["required"])
    case["polls"][0].append({"name": "test (${{ matrix.os }})", "state": "SKIPPED", "bucket": "skipping"})
    v = prwait.wait(prwait.Replay(case))
    assert v.green and all("${{" not in n for n, _ in v.checks)


def test_unreadable_rules_are_not_green():
    class NoRules(prwait.Replay):
        def required(self):
            raise prwait.Refused("could not read the rules of the base branch develop")

    v = prwait.wait(NoRules(_one("SUCCESS")))
    assert not v.green and "rules" in v.why


def test_not_green_without_an_answer_is_marked_unknown_and_a_failed_check_is_not():
    class NoRules(prwait.Replay):
        def required(self):
            raise prwait.Refused("could not read the rules of the base branch develop")

    assert prwait.wait(NoRules(_one("SUCCESS"))).unknown
    assert not prwait.wait(prwait.Replay(_one("FAILURE"))).unknown
    assert prwait.wait(prwait.Replay({"isDraft": None, "polls": [[]]})).unknown  # unreadable
    assert not prwait.wait(prwait.Replay({"isDraft": True, "polls": [[]]})).unknown  # a draft is an answer
    assert prwait.wait(prwait.Replay({"polls": [[]]})).unknown  # no checks in time
    pending = [{"name": "build", "state": "PENDING", "bucket": "pending"}]
    assert prwait.wait(prwait.Replay({"polls": [pending]}), timeout=600).unknown


class _Green(prwait.Replay):
    def __init__(self):
        super().__init__(
            {"polls": [[{"name": "test", "state": "SUCCESS", "bucket": "pass"}]], "required": []}
        )
        self.url, self.gh = "https://github.com/o/r/pull/1", "/fake/gh"

    def view(self):
        return {"state": "OPEN", "isDraft": False, "baseRefName": "develop", "headRefOid": "a" * 40}

    def landed(self, head, base):
        return []

    def changed_files(self):
        return ["x.py"]


def test_before_merge_is_asked_right_before_the_merge_and_can_stop_it(monkeypatch):
    merges, asked, order = [], [], []
    monkeypatch.setattr(_Green, "take", lambda self, kind, what: order.append("room") or True)
    monkeypatch.setattr(prwait.ghlimit, "give_back", lambda kind, what: order.append("back"))
    monkeypatch.setattr(
        prwait, "_run", lambda argv, t=30: merges.append(argv) or subprocess.CompletedProcess(argv, 0)
    )
    src = _Green()
    o = prwait.run_one(
        src.url, True, src=src, before_merge=lambda head: asked.append(head) or "it was closed"
    )
    assert not o.ok and o.status == "held" and "it was closed" in o.line and merges == []
    assert asked == ["a" * 40] and order == ["room", "back"]  # asked after the wait for room
    o = prwait.run_one(src.url, True, src=src, before_merge=lambda head: None)
    assert o.ok and o.status == "merged" and len(merges) == 1


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
    """One pull request: a recorded case for its checks plus what GitHub says about the branch: the files it
    changes, the files that landed on develop since it took develop in (one list per look), and whether
    GitHub can take develop in."""

    def __init__(self, url, case, state="OPEN", head_after=None, changed=None, landed=None, can_update=True):
        super().__init__(case)
        self.url, self.gh, self.state, self.head, self.head_after = url, "/fake/gh", state, HEAD, head_after
        self.changed = ["workspace/src/orch/prwait.py"] if changed is None else changed
        self.landings = list(landed or [[]])
        self.can_update, self.updates, self.views = can_update, [], 0

    def view(self):
        self.views += 1
        if self.head_after and self.views > 1:
            self.head = self.head_after
        return {"state": self.state, "isDraft": False, "baseRefName": "develop", "headRefOid": self.head}

    def landed(self, head, base):
        return self.landings.pop(0) if len(self.landings) > 1 else self.landings[0]

    def changed_files(self):
        return self.changed

    def update_branch(self, head):
        self.updates.append(head)
        if not self.can_update:
            return None
        self.head = f"{len(self.updates):x}" * 40
        self.n = 0  # the new commit's checks are waited for from the start
        return self.head


@pytest.fixture
def fake_gh(monkeypatch):
    pulls, merges = {}, []

    def run(argv, timeout=30):
        merges.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(prwait, "Live", lambda url: pulls[url])
    monkeypatch.setattr(prwait, "_run", run)
    from orch import ghmerge

    monkeypatch.setattr(ghmerge, "workflow_check", lambda url, head: None)  # never the real GitHub
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


def test_overlap_rule_by_file_and_by_test_module():
    mine = ["workspace/src/orch/prwait.py", "workspace/tests/test_cli.py"]
    assert prwait.overlap(mine, ["docs/x.md", "workspace/src/orch/review.py"]) == []
    assert prwait.overlap(mine, ["workspace/src/orch/prwait.py"]) == ["workspace/src/orch/prwait.py"]
    assert prwait.overlap(mine, ["workspace/tests/test_prwait.py"]) == ["workspace/tests/test_prwait.py"]
    assert prwait.overlap(mine, ["workspace/src/orch/cli.py"]) == [
        "workspace/src/orch/cli.py"
    ]  # its test changed
    assert prwait.overlap(["web/app.js"], ["web/tests/app.test.js"]) == ["web/tests/app.test.js"]
    assert prwait.overlap(["a/__init__.py"], ["b/__init__.py"]) == []  # same name, another module


def test_develop_moved_without_touching_it_merges_and_says_so(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(
        PR, _case("pr978-second-run"), landed=[["docs/notes.md", "workspace/src/orch/review.py"]]
    )
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 0, out
    assert pulls[PR].updates == [] and len(merges) == 1  # no second CI run
    assert "develop moved (2 files changed there), none of them touch this pull request" in out


def test_nothing_new_on_develop_merges_and_says_so(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 0 and len(merges) == 1 and "develop had nothing new" in out


def test_overlap_takes_develop_in_waits_again_then_merges_the_new_commit(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"), landed=[["workspace/tests/test_prwait.py"], []])
    code, out, err = run("ref", "wait", tk, "--merge")
    assert code == 0, out + err
    assert pulls[PR].updates == [HEAD]  # develop taken in once, on the checked commit
    assert "taking develop in and waiting for the checks once more" in err
    assert merges[0][-1] == "1" * 40  # the new commit, after its own green checks
    assert "develop taken in 1x first" in out


def test_overlap_with_red_checks_after_taking_develop_in_is_not_merged(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pull = FakePull(PR, _case("pr978-second-run"), landed=[["workspace/src/orch/prwait.py"]])
    red = _case("pr978-first-run")
    pull.update_branch = lambda head, _u=pull.update_branch: (setattr(pull, "polls", red["polls"]), _u(head))[
        1
    ]
    pulls[PR] = pull
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == [] and "after taking develop in: NOT green" in out


def test_queue_mode_never_takes_develop_in_it_says_behind(fake_gh):
    pulls, merges = fake_gh
    pull = FakePull(PR, _case("pr978-second-run"), landed=[["workspace/src/orch/prwait.py"]])
    o = prwait.run_one(PR, True, src=pull, queue=True)
    assert o.status == "behind" and not o.ok and pull.updates == [] and merges == []
    assert "develop changed files of" in o.line and "prwait.py" in o.line


def test_queue_mode_merges_without_waiting_for_the_hourly_merge_count_but_counts_it(fake_gh):
    pulls, merges = fake_gh
    pull = FakePull(PR, _case("pr978-second-run"))
    pull.take = lambda kind, what: False  # no room in the hour: ref wait --merge would stop here
    assert prwait.run_one(PR, True, src=pull).status == "checks passed" and merges == []
    pull = FakePull(PR, _case("pr978-second-run"))
    pull.take = lambda kind, what: False
    o = prwait.run_one(PR, True, src=pull, queue=True)
    assert o.ok and o.status == "merged" and len(merges) == 1
    assert pull.counted == [("merge", PR)]


def test_stop_ends_the_wait_without_a_verdict_and_never_merges(fake_gh):
    pulls, merges = fake_gh
    asked: list[int] = []

    def stop():
        asked.append(1)
        return "the group before it was not merged" if len(asked) > 1 else None

    pull = FakePull(PR, _case("pr978-second-run"))
    o = prwait.run_one(PR, True, src=pull, queue=True, stop=stop)
    assert o.status == "stopped" and not o.ok and merges == []
    assert o.verdict.unknown and "the group before it was not merged" in o.line
    pull = FakePull(PR, _case("pr978-second-run"))  # a stop that never says stop changes nothing
    assert prwait.run_one(PR, True, src=pull, queue=True, stop=lambda: None).status == "merged"


def test_overlap_that_github_cannot_take_in_is_left_to_the_helper(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(
        PR, _case("pr978-second-run"), landed=[["workspace/src/orch/prwait.py"]], can_update=False
    )
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == [] and "by hand" in out


def test_overlap_every_round_stops_after_two_rounds(proj, tk, run, fake_gh):
    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"), landed=[["workspace/src/orch/prwait.py"]])
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 1 and merges == [] and len(pulls[PR].updates) == 2 and "keeps changing" in out


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


def test_with_the_merge_queue_on_no_merge_into_its_base_goes_past_it(proj, tk, run, fake_gh, monkeypatch):
    """ORCH-450: every merge into develop is checked in a queue group, so ref wait --merge refuses it."""
    from orch import addons

    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    monkeypatch.setattr(addons, "active", lambda root: {"pull-requests": {}})
    code, _, err = run("ref", "wait", tk, "--merge")
    assert code == 2 and merges == [] and "go through the merge queue" in err
    assert f"orch pull-requests queue add {PR} --ticket" in err
    code, _, _ = run("ref", "wait", tk)  # only waiting for the checks stays allowed
    assert code == 0 and merges == []


def test_the_queue_refusal_counts_only_for_the_queues_base_branches(proj, tk, run, fake_gh, monkeypatch):
    from orch import addons

    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    monkeypatch.setattr(addons, "active", lambda root: {"pull-requests": {}})
    (proj / ".orch" / "config.toml").write_text('[pull_requests]\nbases = ["next"]\n', encoding="utf-8")
    code, out, _ = run("ref", "wait", tk, "--merge")
    assert code == 0, out
    assert merges == [["/fake/gh", "pr", "merge", PR, "--merge", "--match-head-commit", HEAD]]


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


def test_after_taking_develop_in_only_githubs_merge_commit_is_taken(monkeypatch):
    """Someone pushes while develop is taken in: that commit is never waited for and merged in its place."""
    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")
    monkeypatch.setattr(prwait.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        prwait, "_run", lambda argv, timeout=30: subprocess.CompletedProcess(argv, 0, "{}", "")
    )
    new, base_tip = "c" * 40, "d" * 40

    def live(parents, base_has_it=True):
        src = prwait.Live(PR)
        src.base = "develop"
        answers = {
            f"repos/acme/app/commits/{new}": {"parents": [{"sha": p} for p in parents]},
            f"repos/acme/app/compare/develop...{base_tip}": {"ahead_by": 0 if base_has_it else 3},
        }
        src.view = lambda: {"state": "OPEN", "isDraft": False, "baseRefName": "develop", "headRefOid": new}
        src.gh_json = lambda *args: answers.get(args[1])
        return src

    assert live([HEAD, base_tip]).update_branch(HEAD) == new
    assert live([HEAD]).update_branch(HEAD) is None  # a plain push on top
    assert live(["e" * 40, base_tip]).update_branch(HEAD) is None  # a merge, but not of the checked commit
    assert live([HEAD, base_tip], base_has_it=False).update_branch(HEAD) is None  # merged something else


def _rules(*names):
    return [{"type": "required_status_checks",
             "parameters": {"required_status_checks": [{"context": n} for n in names]}}]  # fmt: skip


def _live_with_rules(monkeypatch, base, rules: dict, default="develop"):
    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")
    src = prwait.Live(PR)
    src.base = base
    answers = {f"repos/acme/app/rules/branches/{b}": r for b, r in rules.items()}
    answers["repos/acme/app"] = {"default_branch": default}
    src.gh_json = lambda *args: answers.get(args[1])
    return src


def test_required_checks_are_those_of_the_branch_the_pull_request_goes_into(monkeypatch):
    rules = {"develop": _rules("ci", "words"), "main": [{"type": "deletion"}], "next": _rules("ci")}
    into_next = _live_with_rules(monkeypatch, "next", rules)
    assert into_next.required() == ["ci"] and into_next.fallback is False
    into_develop = _live_with_rules(monkeypatch, "develop", rules)
    assert into_develop.required() == ["ci", "words"] and into_develop.fallback is False


def test_a_pull_request_into_main_falls_back_to_the_default_branchs_checks(monkeypatch):
    src = _live_with_rules(
        monkeypatch, "main", {"develop": _rules("ci", "words"), "main": [{"type": "deletion"}]}
    )
    assert src.required() == ["ci", "words"] and src.fallback is True
    lone = _live_with_rules(monkeypatch, "main", {"main": []}, default="main")
    assert lone.required() == [] and lone.fallback is False  # no rules anywhere: every check must be SUCCESS


def test_into_main_a_skipped_required_check_passes_but_not_all_skipped():
    case = _case("release-into-main")
    for c in case["polls"][0]["checks"]:
        if c["name"] in case["required"]:
            c["state"], c["bucket"] = "SKIPPED", "skipping"
    v = prwait.wait(prwait.Replay(case))
    assert not v.green and "none of the required checks ran" in v.why


def test_into_main_a_missing_required_check_is_waited_for():
    case = _case("release-into-main")
    case["polls"][0]["checks"] = [c for c in case["polls"][0]["checks"] if c["name"] != case["required"][0]]
    v = prwait.wait(prwait.Replay(case))
    assert not v.green and v.unknown and "never reported: " + case["required"][0] in v.why


def test_a_pull_request_moved_to_another_base_while_waiting_is_not_merged(monkeypatch):
    merges = []
    monkeypatch.setattr(
        prwait, "_run", lambda argv, t=30: merges.append(argv) or subprocess.CompletedProcess(argv, 0)
    )
    src = _Green()
    seen = iter(["develop", "main"])
    monkeypatch.setattr(src, "view", lambda: {"state": "OPEN", "isDraft": False, "headRefOid": "a" * 40,
                                               "baseRefName": next(seen, "main")})  # fmt: skip
    o = prwait.run_one(src.url, True, src=src)
    assert not o.ok and o.status == "changed" and "another base branch" in o.line and merges == []


def test_a_before_merge_check_that_breaks_never_lets_the_merge_through(monkeypatch):
    merges, back = [], []
    monkeypatch.setattr(
        prwait, "_run", lambda argv, t=30: merges.append(argv) or subprocess.CompletedProcess(argv, 0)
    )
    monkeypatch.setattr(prwait.ghlimit, "give_back", lambda kind, what: back.append(kind))
    src = _Green()

    def broken(head):
        raise TimeoutError("lock")

    o = prwait.run_one(src.url, True, src=src, before_merge=broken)
    assert not o.ok and o.status == "held" and "TimeoutError" in o.line and merges == [] and back == ["merge"]


def test_a_green_workflow_change_goes_to_the_owners_merge_card_and_is_not_merged_here(
    proj, tk, run, fake_gh, monkeypatch
):
    """ORCH-305: GitHub holds it for the owner (CODEOWNERS): one Merge card, no merge, no hand push."""
    from orch import cli_review, ghmerge

    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"), changed=[".github/workflows/addons.yml"])
    seen = []
    monkeypatch.setattr(
        ghmerge, "workflow_check", lambda url, head: seen.append((url, head)) or {"files": []}
    )

    def card(args, root, tid, by):
        assert (
            args.merge and args.open == PR and args.link == "CI workflow change" and by.startswith("agent:")
        )
        return {}, {"id": "q4"}

    monkeypatch.setattr(cli_review, "ask_card", card)
    code, out, _ = run("ref", "wait", tk, "--merge", "--by", "agent:x")
    assert code == 1 and merges == [] and seen == [(PR, HEAD)]
    lines = out.strip().splitlines()
    assert "the owner merges it with the Merge card q4" in lines[-2]
    assert lines[-1].startswith("Next: GREEN; it changes a CI workflow, so the owner merges it")
    assert _ref_status(proj, tk, PR) == "owner merges"


def test_without_a_workflow_file_the_merge_goes_on(proj, tk, run, fake_gh, monkeypatch):
    from orch import ghmerge

    pulls, merges = fake_gh
    pulls[PR] = FakePull(PR, _case("pr978-second-run"))
    monkeypatch.setattr(ghmerge, "workflow_check", lambda url, head: None)
    code, _, _ = run("ref", "wait", tk, "--merge")
    assert code == 0 and len(merges) == 1


def _timed_out(retry_state):
    bad = {"name": "lint", "state": "TIMED_OUT", "bucket": "fail"}
    ok = {"name": "build", "state": "SUCCESS", "bucket": "pass"}
    again = {"name": "lint", "state": retry_state, "bucket": "pass" if retry_state == "SUCCESS" else "fail"}
    return {"repo": "acme/app", "isDraft": False, "required": [], "polls": [[ok, bad], [ok, again]]}


def test_a_timed_out_check_is_run_once_more_and_counted():
    src = prwait.Replay(_timed_out("SUCCESS"))
    v = prwait.wait(src)
    assert v.green and v.retried == ["lint"] and src.reran == ["lint"]
    from orch import checkretry

    s = checkretry.summary()
    assert s["total"] == 1 and s["checks"][0]["check"] == "lint" and s["checks"][0]["timeout"] == 1


def test_a_check_that_times_out_again_is_red_after_one_retry():
    src = prwait.Replay(_timed_out("TIMED_OUT"))
    v = prwait.wait(src)
    assert not v.green and "lint TIMED_OUT" in v.why and "once more" in v.why
    from orch import checkretry

    assert checkretry.summary()["total"] == 1  # one retry, never a second


def test_a_real_failure_is_never_retried():
    src = prwait.Replay(_timed_out("SUCCESS"))
    src.polls[0][1]["state"] = "FAILURE"
    v = prwait.wait(src)
    assert not v.green and not v.retried and not hasattr(src, "reran")


def test_a_network_failure_named_by_the_source_is_retried():
    case = _timed_out("SUCCESS")
    case["polls"][0][1]["state"] = "FAILURE"
    case["networkFailed"] = ["lint"]
    v = prwait.wait(prwait.Replay(case))
    assert v.green and v.retried == ["lint"]
    from orch import checkretry

    assert checkretry.summary()["checks"][0]["network"] == 1


def test_a_timeout_and_a_real_failure_together_are_not_retried():
    case = _timed_out("SUCCESS")
    case["polls"][0].append({"name": "unit", "state": "FAILURE", "bucket": "fail"})
    v = prwait.wait(prwait.Replay(case))
    assert not v.green and not v.retried


def test_retry_summary_keeps_only_the_window_and_orders_by_count():
    from orch import checkretry

    checkretry.record("a/b", "1", "old", "timeout", now=10_000_000.0 - 40 * 86400)
    for _ in range(2):
        checkretry.record("a/b", "2", "flaky", "network", now=10_000_000.0)
    checkretry.record("a/b", "3", "other", "timeout", now=10_000_000.0)
    s = checkretry.summary(30, now=10_000_100.0)
    assert [c["check"] for c in s["checks"]] == ["flaky", "other"] and s["total"] == 3


def test_the_wait_says_once_a_minute_what_it_waits_for():
    """17 Nov: orch ref wait --merge sat 50 minutes without a word (it waited for the hourly merge limit)."""
    running = [{"name": "build", "state": "PENDING", "bucket": "pending"},
               {"name": "lint", "state": "SUCCESS", "bucket": "pass"}]  # fmt: skip
    done = [{"name": "build", "state": "SUCCESS", "bucket": "pass"},
            {"name": "lint", "state": "SUCCESS", "bucket": "pass"},
            {"name": "needed", "state": "SUCCESS", "bucket": "pass"}]  # fmt: skip
    src = prwait.Replay({"required": ["needed"], "polls": [[], running, running, done]})
    src.url = PR
    assert prwait.wait(src).green
    lines = [text for _, text in src.said]
    assert len(lines) == 3  # one per minute of waiting, none after the verdict
    assert "to start (none reported yet)" in lines[0]
    assert "1 of 2 still running (build)" in lines[1] and "required not reported yet: needed" in lines[1]
    assert all(PR in x for x in lines)


def test_a_wait_for_room_in_the_merge_limit_is_said_at_most_once_a_minute(monkeypatch, capsys):
    from orch import ghlimit

    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")

    def take(kind, what, on_wait=None, **kw):
        for waited in (0, 20, 40, 60, 80, 100, 120):
            on_wait(900 - waited, waited)
        return True

    monkeypatch.setattr(ghlimit, "take", take)
    monkeypatch.setattr(ghlimit, "status", lambda: [{"kind": "merge", "used": 12, "per_hour": 12}])
    assert prwait.Live(PR).take("merge", PR)
    lines = [x for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert len(lines) == 3  # at 0, 60 and 120 seconds
    assert f"checks of {PR} passed" in lines[0] and "GitHub limit for merges (12 of 12 this hour" in lines[0]
    assert "next fits in about 15 min" in lines[0]


def test_a_required_check_that_never_comes_is_not_waited_for_an_hour():
    """18 Nov: a merge queue group's run was cancelled before its final check; nothing ran any more and the
    wait sat the whole hour for a check that could not come. Then: NOT green, unknown."""
    v = prwait.wait(prwait.Replay(_case("required-check-missing")))
    assert not v.green and v.unknown and "never reported" in v.why
    src = prwait.Replay(_case("required-check-missing"))
    prwait.wait(src)
    assert src.t < prwait.NO_CHECKS_SECS + 3 * prwait.POLL_SECS


def test_a_missing_required_check_is_waited_for_while_a_run_is_still_open():
    runs = {"checks": [{"name": "banned-words", "state": "SUCCESS", "bucket": "pass"}],
            "runs": [{"name": "ci", "status": "queued"}]}  # fmt: skip
    v = prwait.wait(prwait.Replay({"required": ["needed"], "polls": [runs]}), timeout=1800)
    assert not v.green and "still waiting" in v.why and "unfinished workflow runs: ci" in v.why


def test_overlap_while_ci_is_jammed_does_not_take_develop_in(fake_gh):
    """ORCH-454: taking develop in starts every check again; never while 20 or more jobs wait."""
    pulls, merges = fake_gh
    case = {**_case("pr978-second-run"), "ciWaiting": 37}
    pull = FakePull(PR, case, landed=[["workspace/src/orch/prwait.py"]])
    o = prwait.run_one(PR, True, src=pull)
    assert o.status == "behind" and not o.ok and pull.updates == [] and merges == []
    assert "37 jobs wait for a machine" in o.line and "Run it again later" in o.line


def test_an_empty_merge_commit_of_the_group_before_is_nothing_landed(monkeypatch):
    """ORCH-1118: a queue group built on top of another sees only that group's merge commit land on develop;
    GitHub's compare lists commits but no files. That is nothing landed, not unknown (six green groups were
    closed without merge on 20 Nov)."""
    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")
    src = prwait.Live(PR)
    answers = {
        "empty": {"ahead_by": 1, "files": []},
        "nolist": {"ahead_by": 2},
        "some": {"ahead_by": 1, "files": [{"filename": "a.py"}]},
    }
    for key, want in (("empty", []), ("nolist", None), ("some", ["a.py"])):
        src.gh_json = lambda *args, k=key: answers[k]
        assert src.landed(HEAD, "develop") == want


def _c(name, state):
    bucket = {"SUCCESS": "pass", "SKIPPED": "skipping", "PENDING": "pending", "CANCELLED": "cancel"}.get(
        state, "fail"
    )
    return {"name": name, "state": state, "bucket": bucket}


def _group(second):
    """A merge queue group: lint fails while build still runs; build and the final check get cancelled
    or red; the re-run first still shows the old results, then runs, then ends as `second` says."""
    polls = [
        [_c("build", "PENDING"), _c("lint", "FAILURE")],
        [_c("build", "CANCELLED"), _c("lint", "FAILURE"), _c("final", "FAILURE")],
        [_c("build", "CANCELLED"), _c("lint", "FAILURE"), _c("final", "FAILURE")],
        [_c("build", "PENDING"), _c("lint", "PENDING"), _c("final", "PENDING")],
        [
            _c("build", "SUCCESS"),
            _c("lint", second),
            _c("final", "SUCCESS" if second == "SUCCESS" else "FAILURE"),
        ],
    ]
    return {"repo": "acme/app", "isDraft": False, "required": [], "polls": polls}


def test_a_queue_group_stops_at_the_first_red_and_runs_the_failed_jobs_once_more():
    """ORCH-1118: a red job at minute 10 no longer waits for the rest; the run is cancelled, the failed and
    cancelled jobs run once more (a flaky test does not split a group of ten), green then is green."""
    src = prwait.Replay(_group("SUCCESS"))
    v = prwait.wait(src, queue=True)
    assert v.green and v.retried == ["lint"] and src.reran == ["lint"] and src.cancels == 1
    from orch import checkretry

    assert checkretry.summary()["checks"][0]["flaky"] == 1


def test_a_queue_group_red_again_after_the_one_re_run_is_red_and_cancelled_again():
    src = prwait.Replay(_group("FAILURE"))
    v = prwait.wait(src, queue=True)
    assert not v.green and not v.unknown and "lint FAILURE" in v.why and "once more" in v.why
    assert src.cancels == 2 and src.n == 5  # one re-run only, never a second


def test_outside_the_queue_a_red_check_still_waits_for_the_rest_and_is_not_re_run():
    src = prwait.Replay(_group("SUCCESS"))
    v = prwait.wait(src)
    assert not v.green and not hasattr(src, "reran") and not hasattr(src, "cancels")


def test_a_job_still_shown_cancelled_after_the_re_run_is_not_taken_for_its_new_result():
    """Codex review: build stays CANCELLED for a poll after the re-run while lint is green already; that is
    the old result, not a red one."""
    polls = [
        [_c("lint", "FAILURE"), _c("build", "PENDING")],
        [_c("lint", "FAILURE"), _c("build", "CANCELLED")],
        [_c("lint", "SUCCESS"), _c("build", "CANCELLED")],
        [_c("lint", "SUCCESS"), _c("build", "PENDING")],
        [_c("lint", "SUCCESS"), _c("build", "SUCCESS")],
    ]
    src = prwait.Replay({"repo": "acme/app", "isDraft": False, "required": [], "polls": polls})
    assert prwait.wait(src, queue=True).green


def test_a_red_group_whose_run_did_not_stop_is_red_without_a_re_run():
    src = prwait.Replay(_group("SUCCESS"))
    src.cancel_runs = lambda: False
    v = prwait.wait(src, queue=True)
    assert not v.green and not v.retried and not hasattr(src, "reran")


def test_counting_a_retry_never_breaks_the_wait_when_the_orch_folder_is_refused(monkeypatch):
    """ORCH-1118: a refused orch folder (Refused, not OSError) made the queue's one re-run break the wait."""
    from orch import addons, checkretry
    from orch.errors import Refused

    def refused():
        raise Refused("ORCH_HOME is not a trusted folder")

    monkeypatch.setattr(addons, "home", refused)
    checkretry.record("acme/app", "1", "test", "flaky")  # no exception


GLITCH = "https://github.com/acme/app/actions/runs/44987756687/job/137101952270"


def test_a_job_of_a_finished_run_counts_as_finished_with_its_own_conclusion():
    """22 Nov, group #2465: 'changes' stayed in_progress for 46 min although the job had conclusion success
    and its run was completed; the waiter now takes the job's conclusion."""
    checks = [
        {"name": "changes", "state": "IN_PROGRESS", "bucket": "pending", "link": GLITCH},
        {"name": "lint", "state": "SUCCESS", "bucket": "pass", "link": GLITCH.replace("137101952270", "1")},
    ]
    run = {"id": 44987756687, "status": "completed", "conclusion": "success", "run_attempt": 1}
    asked = []
    job = {"status": "in_progress", "conclusion": "success", "run_attempt": 1}
    got = prwait.settle(checks, [run], lambda j: asked.append(j) or job, "acme/app")
    assert got[0]["state"] == "SUCCESS" and got[0]["bucket"] == "pass" and asked == [137101952270]
    assert got[1] == checks[1]  # a finished check is not read again
    red = {**run, "conclusion": "failure"}
    same = {"status": "in_progress", "conclusion": None, "run_attempt": 1}
    assert prwait.settle(checks, [red], lambda j: same, "acme/app")[0]["bucket"] == "fail"  # the run's result
    assert prwait.settle(checks, [red], lambda j: None, "acme/app")[0] == checks[0]  # unreadable: next poll


def test_a_job_run_again_waits_while_github_still_shows_the_old_attempt_finished():
    """A job run again: no conclusion, newer attempt; the old attempt's success is not its result."""
    checks = [{"name": "changes", "state": "QUEUED", "bucket": "pending", "link": GLITCH}]
    run = {"id": 44987756687, "status": "completed", "conclusion": "success", "run_attempt": 1}
    new = {"status": "queued", "conclusion": None, "run_attempt": 2}
    assert prwait.settle(checks, [run], lambda j: new, "acme/app") == checks


def test_a_job_of_a_run_that_still_goes_keeps_waiting():
    checks = [{"name": "changes", "state": "IN_PROGRESS", "bucket": "pending", "link": GLITCH}]
    runs = [{"id": 44987756687, "status": "in_progress", "conclusion": None}]
    done = {"conclusion": "success"}
    assert prwait.settle(checks, runs, lambda job: done, "acme/app") == checks
    no_link = [{"name": "ext", "state": "PENDING", "bucket": "pending", "link": "https://example.com/x"}]
    assert prwait.settle(no_link, runs, lambda job: done, "acme/app") == no_link
    finished = [{**runs[0], "status": "completed", "conclusion": "success"}]
    assert prwait.settle(checks, finished, lambda job: done, "other/repo") == checks  # another repository


def test_live_look_ends_the_wait_once_the_run_finished(monkeypatch):
    monkeypatch.setattr(prwait.shutil, "which", lambda name: "/fake/gh")
    pending = [{"name": "changes", "state": "IN_PROGRESS", "bucket": "pending", "link": GLITCH}]
    monkeypatch.setattr(
        prwait, "_run", lambda argv, timeout=30: subprocess.CompletedProcess(argv, 8, json.dumps(pending), "")
    )
    src = prwait.Live(PR)
    answers = {
        "repos/acme/app/actions/runs?head_sha=" + HEAD + "&per_page=100": {"workflow_runs": [
            {"id": 44987756687, "name": "ci", "event": "pull_request", "status": "completed",
             "conclusion": "success"}]},
        "repos/acme/app/actions/jobs/137101952270": {"status": "in_progress", "conclusion": "success",
                                                     "run_attempt": 1},
    }  # fmt: skip
    src.view = lambda: {"state": "OPEN", "isDraft": False, "baseRefName": "develop", "headRefOid": HEAD}
    src.gh_json = lambda *args: answers.get(args[1])
    checks, open_runs = src.look()
    assert open_runs == "" and checks[0]["bucket"] == "pass" and src.last == checks
