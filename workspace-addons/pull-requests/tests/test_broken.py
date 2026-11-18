"""A test broken for everyone, not one pull request (ORCH-455): spotted on 3 unrelated pull requests within an hour,
one issue, the helpers told it is not their change, set aside after a person's yes, back once the issue is closed.
Fake GitHub, fake write limit, fake wake: no network, no helper is started."""

from __future__ import annotations

import json

import pytest
from test_checks import REPO, Limit, Waker, history, job, ticket, url
from test_queue import FakeGit, make
from test_queue_red_base import RedGitHub, add, row

from orch_pull_requests import broken, checks

CLOCK_LOG = (
    "page-smoke\ttest\t2026-11-17T21:35:01.1Z ============ short test summary info ============\n"
    "page-smoke\ttest\t2026-11-17T21:35:01.2Z FAILED tests/test_clock.py::test_start_now - assert 21 == 22\n"
    "page-smoke\ttest\t2026-11-17T21:35:01.3Z ##[error]Process completed with exit code 1.\n"
)
SUM_LOG = "summary\tcheck\t2026-11-17T21:40:00Z bad: {'page_smoke': 'failure'}\n##[error]Process completed with exit code 1.\n"
OWN_LOG = "unit\ttest\t2026-11-17T21:35:01Z FAILED tests/test_mine.py::test_my_change - KeyError: 'x'\n"


class NightGitHub:
    """prs[n] = (head, {check: log}) of failed checks; every check listed failed, the rest passed."""

    def __init__(self):
        self.prs: dict[int, tuple[str, dict[str, str]]] = {}
        self.issues: list[tuple[str, str, str]] = []
        self.closed: set[str] = set()
        self.variables: list[tuple[str, str, str]] = []
        self.ids = {}

    def fail(self, n: int, head: str, **logs: str) -> None:
        self.prs[n] = (head, logs)

    def checks(self, u):
        n = int(u.rsplit("/", 1)[1])
        head, logs = self.prs.get(n, ("0" * 40, {}))  # not failed (yet): green
        rows = [job("lint", "SUCCESS", 1)]
        for name in logs:
            jid = self.ids.setdefault((n, head, name), 100 + len(self.ids))
            rows.append(job(name, "FAILURE", jid))
        return {"state": "OPEN", "isDraft": False, "isCrossRepository": False, "headRefOid": head,
                "statusCheckRollup": rows}  # fmt: skip

    def job_log(self, repo, j):
        for (n, head, name), jid in self.ids.items():
            if jid == j:
                return self.prs[n][1][name]
        return ""

    def rerun_job(self, repo, j):  # pragma: no cover - nothing here is cancelled
        raise AssertionError("no rerun expected")

    def create_issue(self, repo, title, body):
        self.issues.append((repo, title, body))
        return f"https://github.com/{REPO}/issues/{900 + len(self.issues)}"

    def issue_state(self, u):
        return "CLOSED" if u in self.closed else "OPEN"

    def set_variable(self, repo, name, value):
        self.variables.append((repo, name, value))
        return True


class AnyLimit(Limit):
    def __call__(self, kind, what="", wait=None):
        assert kind == "other" and wait == 0
        self.taken.append(what)
        return self.room


@pytest.fixture(autouse=True)
def no_stored_keys(monkeypatch):
    from orch import phone_results

    class NoKeys:
        def hide_text(self, text):
            return text

    monkeypatch.setattr(phone_results, "value_hider", lambda root: NoKeys())


@pytest.fixture
def on(ws):
    checks.set_on(ws, True)
    return ws


def tend(ws, gh, waker, at):
    return checks.tend(ws, gh, take=AnyLimit(), wake_fn=waker, clock=lambda: at, log=lambda s: None)


def fix_it(waker) -> int:
    return sum("Fix the cause" in text for _, text in waker.calls)


# -- the same way ----------------------------------------------------------------------------------------------
def test_the_same_way_is_every_failing_test_the_log_names():
    assert broken.failing_test(CLOCK_LOG) == "tests/test_clock.py::test_start_now"
    xdist = "[gw1] [ 50%] FAILED tests/a.py::test_b\n[gw0] [ 60%] FAILED tests/a.py::test_a\n"
    assert broken.failing_test(xdist) == "tests/a.py::test_a + tests/a.py::test_b"
    assert (
        broken.failing_test("ok 1 - fine\nnot ok 2 - clock shows midnight # time=12ms\n")
        == "clock shows midnight"
    )
    # no test named: the last error line without numbers, so two runs of one failure match
    one = broken.failing_test("Error: port 51234 refused after 3.2s at /tmp/abc/x\n")
    assert one == broken.failing_test("Error: port 40001 refused after 1.0s at /tmp/zz/y\n") != ""
    assert broken.failing_test(SUM_LOG) == ""  # a summing-up check says nothing of its own


# -- 3 unrelated pull requests -----------------------------------------------------------------------------
def test_three_unrelated_pull_requests_in_an_hour_make_one_issue_and_every_helper_is_told(on):
    gh, waker = NightGitHub(), Waker()
    tids = [ticket(on, n) for n in (1, 2, 3, 4)]
    for n in (1, 2):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    assert fix_it(waker) == 2 and not gh.issues  # two are not yet a pattern
    gh.fail(3, "3" * 40, page_smoke=CLOCK_LOG, summary=SUM_LOG)
    got = tend(on, gh, waker, 1600.0)
    assert len(got["broken"]) == 1 and len(gh.issues) == 1
    repo, title, body = gh.issues[0]
    assert (
        repo == REPO and "tests/test_clock.py::test_start_now" in title and url(1) in body and url(3) in body
    )
    told = [tid for tid, text in waker.calls if "not because of your change" in text]
    assert sorted(told) == sorted(tids[:3])  # the two told to fix it earlier, and the third
    assert fix_it(waker) == 2  # the third was never told to fix it (its summary check only sums up)
    assert "issues/901" in waker.calls[-1][1]
    # a fourth pull request later in the night: told at once, still one issue
    gh.fail(4, "4" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 9000.0)
    assert len(gh.issues) == 1 and waker.calls[-1][0] == tids[3] and fix_it(waker) == 2
    assert any("broken test, not its change" in h for h in history(on, tids[3]))


def test_a_person_is_asked_on_one_ticket_for_the_broken_test(on):
    from orch import tickets

    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    t = next(iter(broken.read(on)["tests"].values()))
    made = tickets.load(on, t["ticket"])
    assert made["title"].startswith("Broken test: tests/test_clock.py::test_start_now")
    assert any(r.get("url", "").endswith("/issues/901") for r in made.get("refs") or [])
    q = made["questions"][-1]
    assert q["kind"] == broken.KIND and q["options"] == [broken.ASIDE, broken.LEAVE] and q["answer"] is None
    tend(on, gh, waker, 1100.0)  # asked once
    assert len(tickets.load(on, t["ticket"])["questions"]) == 1


def test_two_pull_requests_of_one_ticket_are_related(on):
    gh, waker = NightGitHub(), Waker()
    ticket(on, 1, 2)
    ticket(on, 3)
    for n in (1, 2, 3):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    got = tend(on, gh, waker, 1000.0)
    assert not got["broken"] and not gh.issues and fix_it(waker) == 3


def test_failures_more_than_an_hour_apart_are_no_pattern(on):
    gh, waker = NightGitHub(), Waker()
    for i, n in enumerate((1, 2, 3)):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
        tend(on, gh, waker, 1000.0 + i * 2000)
    assert not gh.issues and fix_it(waker) == 3


def test_a_real_failure_next_to_the_broken_test_still_wakes_the_helper(on):
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3, 4):
        ticket(on, n)
    for n in (1, 2, 3):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    gh.fail(4, "4" * 40, page_smoke=CLOCK_LOG, unit=OWN_LOG)
    tend(on, gh, waker, 1200.0)
    text = waker.calls[-1][1]
    assert "Fix the cause" in text and "`ci / unit`: failed" in text
    assert "Not your change" in text and "test_clock.py::test_start_now` is broken" in text
    # the broken test AND a second failing test in one job is not the broken test's way: theirs to look at
    both = CLOCK_LOG + "FAILED tests/test_x.py::test_other - boom\n"
    gh.fail(4, "5" * 40, page_smoke=both)
    tend(on, gh, waker, 1300.0)
    assert "Fix the cause" in waker.calls[-1][1]


# -- set aside after a yes, back once fixed ----------------------------------------------------------------
def test_set_aside_after_a_yes_then_back_when_the_issue_is_closed(on, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(broken, "LOOK_SECS", 0)
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3, 4):
        ticket(on, n)
    for n in (1, 2, 3):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    t = next(iter(broken.read(on)["tests"].values()))
    assert not gh.variables  # nothing is set aside without a person
    tickets.answer(on, t["ticket"], t["question"], broken.ASIDE, "human:p", "cli")
    tend(on, gh, waker, 1100.0)
    assert gh.variables[-1][:2] == (REPO, "ORCH_ASIDE")
    listed = json.loads(gh.variables[-1][2])
    assert listed == [{"check": "ci / page_smoke", "test": "tests/test_clock.py::test_start_now",
                       "issue": f"https://github.com/{REPO}/issues/901"}]  # fmt: skip
    calls = len(waker.calls)
    gh.fail(4, "4" * 40, page_smoke=CLOCK_LOG)
    got = tend(on, gh, waker, 1200.0)
    assert len(waker.calls) == calls and not got["woke"]  # set aside: no helper is woken for it
    assert any("only in tests set aside" in h for h in history(on, ticket_of(on, 4)))
    gh.closed.add(f"https://github.com/{REPO}/issues/901")
    tend(on, gh, waker, 1300.0)
    assert json.loads(gh.variables[-1][2]) == []  # it counts again
    assert broken.set_aside(on, REPO) == {}
    assert any("is closed" in h for h in history(on, t["ticket"]))


def test_only_a_person_sets_a_test_aside(on):
    from orch import tickets

    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    t = next(iter(broken.read(on)["tests"].values()))
    tickets.answer(on, t["ticket"], t["question"], broken.ASIDE, "agent:reviewer", "cli")
    tend(on, gh, waker, 1100.0)
    assert not gh.variables and not next(iter(broken.read(on)["tests"].values()))["aside"]


def test_an_error_line_that_looks_like_a_secret_names_nothing():
    line = "Error: login refused for ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "\n"
    assert broken.failing_test(line) == ""


def test_leave_it_asks_never_again(on):
    from orch import tickets

    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    t = next(iter(broken.read(on)["tests"].values()))
    tickets.answer(on, t["ticket"], t["question"], broken.LEAVE, "human:p", "cli")
    tend(on, gh, waker, 1100.0)
    tend(on, gh, waker, 1200.0)
    assert not gh.variables and len(tickets.load(on, t["ticket"])["questions"]) == 1


def test_off_does_nothing(ws):
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(ws, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    got = tend(ws, gh, waker, 1000.0)
    assert not got["on"] and not gh.issues and not waker.calls


def ticket_of(ws, n):
    from orch import tickets

    return next(
        t["id"] for t in tickets.list_all(ws) if any(r.get("url") == url(n) for r in t.get("refs") or [])
    )


# -- the merge queue ---------------------------------------------------------------------------------------
class QueueGitHub(RedGitHub):
    """RedGitHub plus the checks and logs the queue reads for a set-aside test: logs[n] = {check: log}."""

    def __init__(self, prs, logs):
        super().__init__(prs, red=(frozenset(),))
        self.logs = logs

    def checks(self, u):
        n = int(u.rsplit("/", 1)[1])
        rows = [job(name, "FAILURE", n * 10 + i) for i, name in enumerate(self.logs.get(n, {}))]
        return {"state": "OPEN", "headRefOid": "a" * 40, "statusCheckRollup": rows}

    def job_log(self, repo, j):
        return list(self.logs[j // 10].values())[j % 10]


def aside(ws, check="ci / page-smoke", test="tests/test_clock.py::test_start_now"):
    data = broken.read(ws)
    for i, n in enumerate((11, 12, 13)):
        t = broken.note(data, REPO, f"{REPO}#{n}", f"t{n}", check, test, 1000.0 + i)
    t.update(aside=True, issue=f"https://github.com/{REPO}/issues/901")
    broken.write(ws, data)


def test_the_queue_does_not_blame_a_pull_request_for_a_test_set_aside(ws):
    aside(ws)
    for n in (1, 2, 3):
        add(ws, n)
    summing = "bad: {'page-smoke': 'failure'}\n"
    gh = QueueGitHub(
        {n: {"failed": True, "jobs": {"page-smoke", "summary"}} for n in (1, 2, 3)},
        {
            1: {"page-smoke": CLOCK_LOG, "summary": summing},  # only the set-aside test: not blamed
            2: {"page-smoke": CLOCK_LOG + "FAILED tests/test_x.py::test_new - boom\n", "summary": summing},
            3: {"page-smoke": CLOCK_LOG, "summary": "nothing said\n"},  # a red check that is not only the sum
        },
    )
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == []
    one = row(ws, 1)
    assert one["state"] == "waiting" and not one.get("tries") and "set aside" in one["why"]
    assert row(ws, 2)["state"] == "out"  # a new failing test next to it: its own
    assert row(ws, 3)["state"] == "out"


def test_the_queue_blames_as_before_while_nobody_set_the_test_aside(ws):
    data = broken.read(ws)
    for i, n in enumerate((11, 12, 13)):
        broken.note(
            data,
            REPO,
            f"{REPO}#{n}",
            f"t{n}",
            "ci / page-smoke",
            "tests/test_clock.py::test_start_now",
            1000.0 + i,
        )
    broken.write(ws, data)
    add(ws, 1)
    gh = QueueGitHub({1: {"failed": True, "jobs": {"page-smoke"}}}, {1: {"page-smoke": CLOCK_LOG}})
    r, _ = make(ws, gh, FakeGit())
    r.next_batch()
    assert row(ws, 1)["state"] == "out"


# -- what the review of 18 Nov found -----------------------------------------------------------------------
def test_a_helper_told_to_fix_two_failures_hears_only_that_one_is_not_theirs(on):
    gh, waker = NightGitHub(), Waker()
    t1 = ticket(on, 1)
    for n in (2, 3):
        ticket(on, n)
    gh.fail(1, "1" * 40, page_smoke=CLOCK_LOG, unit=OWN_LOG)
    tend(on, gh, waker, 1000.0)
    for n in (2, 3):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1100.0)
    later = [text for tid, text in waker.calls[1:] if tid == t1]
    assert len(later) == 1 and "one of the failures" in later[0] and "still yours to fix" in later[0]
    assert "Go on with your ticket" not in later[0]


def test_an_issue_github_already_holds_is_found_not_opened_twice(on):
    gh, waker = NightGitHub(), Waker()
    gh.find_issue = lambda repo, mark: f"https://github.com/{REPO}/issues/77"
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    assert not gh.issues and next(iter(broken.read(on)["tests"].values()))["issue"].endswith("/issues/77")


def test_the_issue_body_carries_the_marker(on):
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    k = next(iter(broken.read(on)["tests"]))
    assert f"{broken.MARK} {k}" in gh.issues[0][2]


def test_no_question_before_the_issue_is_open(on):
    from orch import tickets

    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    checks.tend(on, gh, take=AnyLimit(room=False), wake_fn=waker, clock=lambda: 1000.0, log=lambda s: None)
    t = next(iter(broken.read(on)["tests"].values()))
    assert not t["issue"] and not t["question"] and not t["ticket"]
    tend(on, gh, waker, 1100.0)  # room again: the issue, then the question
    t = next(iter(broken.read(on)["tests"].values()))
    assert t["issue"] and tickets.load(on, t["ticket"])["questions"][0]["kind"] == broken.KIND


def test_after_the_issue_is_closed_old_failures_never_make_a_new_broken_test(on, monkeypatch):
    monkeypatch.setattr(broken, "LOOK_SECS", 0)
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3, 4):
        ticket(on, n)
    for n in (1, 2, 3):
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    gh.closed.add(f"https://github.com/{REPO}/issues/901")
    tend(on, gh, waker, 1100.0)
    gh.fail(4, "4" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1200.0)
    assert len(gh.issues) == 1 and "Fix the cause" in waker.calls[-1][1]


def test_a_refused_variable_is_written_again_also_after_the_test_is_gone(on, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(broken, "LOOK_SECS", 0)
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
        gh.fail(n, f"{n}" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 1000.0)
    t = next(iter(broken.read(on)["tests"].values()))
    tickets.answer(on, t["ticket"], t["question"], broken.ASIDE, "human:p", "cli")
    tend(on, gh, waker, 1100.0)
    gh.closed.add(t["issue"])
    gh.set_variable = lambda repo, name, value: False  # GitHub refuses the removal
    tend(on, gh, waker, 1200.0)
    tend(on, gh, waker, 1300.0)  # the test record is gone now
    written = []
    gh.set_variable = lambda repo, name, value: written.append(value) or True
    tend(on, gh, waker, 1400.0)
    assert written == ["[]"] and broken.read(on)["publish"] == {}


def test_a_new_failure_of_the_same_pull_request_counts_from_its_new_time(on):
    gh, waker = NightGitHub(), Waker()
    for n in (1, 2, 3):
        ticket(on, n)
    gh.fail(1, "a" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 0.0)
    gh.fail(1, "b" * 40, page_smoke=CLOCK_LOG)  # a new commit, the same failure, 55 minutes later
    tend(on, gh, waker, 55 * 60.0)
    gh.fail(2, "2" * 40, page_smoke=CLOCK_LOG)
    tend(on, gh, waker, 56 * 60.0)
    gh.fail(3, "3" * 40, page_smoke=CLOCK_LOG)
    got = tend(on, gh, waker, 62 * 60.0)
    assert got["broken"] and len(gh.issues) == 1


def test_a_long_list_of_failing_tests_is_compared_whole():
    many = "".join(f"FAILED tests/test_p.py::test_{'x' * 150}[{i}]\n" for i in range(3))
    more = many + "FAILED tests/test_p.py::test_zzz\n"
    assert broken.failing_test(many) != broken.failing_test(more)
    assert broken.failing_test("".join(f"FAILED tests/t.py::test_{i}\n" for i in range(500))) == ""


# -- the night of 17/18 Nov ----------------------------------------------------------------------------------
def test_the_night_of_17_18_nov_drops_to_under_5_fix_it_messages(on):
    """About 90 failures from two broken tests on 26 branches (ORCH-446): each branch fails 3 to 4 times as its
    helper pushes; the first broken test from 21:00, the second from 00:00. Without the detection every one
    of them would tell a helper to fix it."""
    gh, waker = NightGitHub(), Waker()
    second = CLOCK_LOG.replace("test_clock.py::test_start_now", "test_services.py::test_midnight")
    for n in range(1, 27):
        ticket(on, n)
    failures, at = 0, 0.0
    for rnd in range(4):
        for n in range(1, 27):
            if rnd == 3 and n % 2:
                continue  # 13 branches failed a fourth time: 26 * 3 + 13 = 91
            log = CLOCK_LOG if n <= 13 else second
            start = 0.0 if n <= 13 else 3 * 3600.0
            at = start + rnd * 1800.0 + n * 60.0
            gh.fail(n, f"{rnd}{n:02d}".ljust(40, "0"), page_smoke=log, summary=SUM_LOG)
            tend(on, gh, waker, at)
            failures += 1
    assert failures == 91
    assert len(gh.issues) == 2
    print("fix-it messages:", fix_it(waker), "of", failures)
    assert fix_it(waker) < 5  # was about 90


def test_only_an_issue_this_login_opened_is_taken_as_ours():
    from orch_pull_requests.github import GitHub

    gh = GitHub.__new__(GitHub)
    gh.login = lambda: "severin-agent"
    mine = {
        "url": "https://github.com/acme/app/issues/5",
        "body": "x\norch-broken-test: k1",
        "author": {"login": "severin-agent"},
    }
    other = dict(mine, url="https://github.com/acme/app/issues/6", author={"login": "someone"})
    seen = []
    gh._json = lambda *a: seen.append(a) or [other, mine]
    assert gh.find_issue(REPO, "k1") == mine["url"]
    assert "--author" in seen[0] and "severin-agent" in seen[0]
    gh._json = lambda *a: [other]
    assert gh.find_issue(REPO, "k1") is None
    gh.login = lambda: None
    assert gh.find_issue(REPO, "k1") is None
