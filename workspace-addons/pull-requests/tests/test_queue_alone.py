"""ORCH-450: every merge is checked in a queue group; a change to CI or to the queue itself runs alone, and one a
person merges is only checked (proof run), then marked for the person's Merge card."""

from __future__ import annotations

import pytest
from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import runner, settings, store
from orch_pull_requests.github import MARK, GitHub
from orch_pull_requests.store import Refused


def add(ws, *nums, ticket=None):
    for n in nums:
        store.add(ws, url(n), ticket, "agent:t", login="bot")


def members(gh, calls):
    return [gh.groups[c] for c in calls]


def test_a_ci_change_waits_for_a_group_of_its_own_and_the_others_go_on(ws):
    add(ws, 1, 2, 3)
    gh = FakeGitHub({1: {}, 2: {"files": [".github/actions/setup/action.yml"]}, 3: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1, 3], [2]] and set(states(ws).values()) == {"merged"}


def test_a_queue_change_first_in_line_runs_alone_before_the_others(ws):
    add(ws, 1, 2, 3)
    gh = FakeGitHub({1: {"files": ["workspace-addons/pull-requests/src/x.py"]}, 2: {}, 3: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1], [2, 3]] and set(states(ws).values()) == {"merged"}


def test_a_red_ci_change_alone_leaves_and_blames_nobody_else(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {"files": ["workspace/src/orch/prwait.py"]}, 2: {}})
    r, calls = make(ws, gh, FakeGit(), red_on_base={1})
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert "queue group was red" in store.find(store.read(ws), url(1))["why"]


def test_too_many_files_to_see_all_runs_alone_and_a_person_merges_it(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {"files": [f"src/f{i}.py" for i in range(100)]}, 2: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert gh.prs[1].get("state", "OPEN") == "OPEN"  # a workflow could hide among the files GitHub left out


def test_the_alone_paths_can_be_set(ws):
    assert ".github/" in settings.alone_paths(ws)
    (ws / ".orch" / "config.toml").write_text(
        '[pull_requests]\nalone_paths = ["/infra/"]\n', encoding="utf-8"
    )
    assert settings.alone_paths(ws) == ["infra/"]


def test_a_workflow_change_is_proved_alone_never_merged_and_gets_the_owners_card(ws):
    add(ws, 1, 2, ticket="t_abc123")
    asked = []
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}, 2: {}})
    r, calls = make(ws, gh, FakeGit(), ask=lambda root, tid, u: asked.append((tid, u)) or "ORCH-9")
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert gh.prs[1].get("state", "OPEN") == "OPEN"  # the queue never merges what the owner merges
    assert asked == [("t_abc123", url(1))]
    assert (f"{1:040d}", "Checked green in a queue group on top of develop") in gh.marks  # its head is marked
    row = store.find(store.read(ws), url(1))
    assert "checked green in its own queue group" in row["why"] and "Merge card on ORCH-9" in row["why"]
    assert gh.closed == [calls[0]]  # the proof group itself is closed, its branch deleted
    assert calls[0].rsplit("/", 1)[0] and gh.deleted


def test_a_red_proof_run_leaves_without_a_mark_or_a_card(ws):
    add(ws, 1, ticket="t_abc123")
    asked = []
    gh = FakeGitHub({1: {"files": [".github/CODEOWNERS"]}})
    r, _ = make(ws, gh, FakeGit(), red_on_base={1}, ask=lambda *a: asked.append(a) or "X")
    r.run()
    assert states(ws) == {1: "out"} and not asked
    assert all(sha == "c" * 40 for sha, _ in gh.marks)  # only the group commit, never the pull request head


def test_a_proved_pull_request_without_a_ticket_says_a_person_merges_it_on_github(ws):
    add(ws, 1)
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}})
    r, _ = make(ws, gh, FakeGit())
    r.run()
    assert "a person merges it on GitHub" in store.find(store.read(ws), url(1))["why"]


def test_no_mark_on_the_group_commit_means_no_group_run(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {}, 2: {}})
    gh.set_status = lambda *a, **k: False
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert calls == [] and states(ws) == {1: "out", 2: "out"}
    assert "mark was not set" in store.find(store.read(ws), url(1))["why"]


def test_owner_change_reads_workflows_and_code_owners():
    assert runner.owner_change({"files": [{"path": ".github/workflows/ci.yml"}]})
    assert runner.owner_change({"files": [{"path": ".github/CODEOWNERS"}]})
    assert runner.owner_change({"files": [{"path": "docs/CODEOWNERS"}]})
    assert runner.owner_change({"files": [{"path": ".github/workflows/README.md"}]})
    assert not runner.owner_change({"files": [{"path": ".github/actions/a.yml"}]})
    assert runner.owner_change({})  # GitHub listed no files: a person merges it (fails closed)


def test_github_sets_and_reads_the_mark(monkeypatch):
    gh = GitHub.__new__(GitHub)
    ran = []

    class Got:
        returncode = 0
        stdout = '{"statuses": [{"context": "orch/merge-queue", "state": "success"}]}'

    monkeypatch.setattr(gh, "_run", lambda *a, **k: ran.append(a) or Got())
    assert gh.set_status("acme/app", "a" * 40, "Built by the orch merge queue", "https://x/pull/5")
    args = ran[0]
    assert "repos/acme/app/statuses/" + "a" * 40 in args and f"context={MARK}" in args
    assert "state=success" in args and "target_url=https://x/pull/5" in args
    assert gh.has_mark("acme/app", "a" * 40) is True


def test_a_proved_pull_request_of_a_done_ticket_still_gets_its_merge_card(ws, monkeypatch):
    """ORCH-1377 (#1491, #1941 on 21 Nov): the ticket was Done, the card was refused silently and the line said
    'a person merges it on GitHub'; the pull request had to be queued again. Now the ticket opens (Waiting)."""
    from orch import tickets

    made = []  # the card itself is the core's (test_merge_card.py); here: that it is asked on the open ticket
    monkeypatch.setattr(
        runner, "_make_card",
        lambda root, tid, key, u: made.append((tickets.load(root, tid)["status"], key, u)),
    )  # fmt: skip
    t = tickets.create(ws, "CI change", by="human:p")
    tickets.ref_add(ws, t["id"], url(1), "human:p")
    tickets.set_status(ws, t["id"], "done", "human:p")
    add(ws, 1, ticket=t["id"])
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}})
    r, _ = make(ws, gh, FakeGit(), ask=runner._ask_merge)
    r.run()
    after = tickets.load(ws, t["id"])
    key = str(after.get("key") or after["id"])
    assert after["status"] == "waiting" and made == [("waiting", key, url(1))]
    assert f"Merge card on {key}" in store.find(store.read(ws), url(1))["why"]
    assert any("Status done -> waiting" in h["text"] for h in after["history"])


def test_a_merge_card_that_cannot_be_made_says_why(ws):
    add(ws, 1, ticket="t_abc123")
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}})

    def ask(root, tid, u):
        raise RuntimeError("the ticket file is locked")

    lines = []
    r, _ = make(ws, gh, FakeGit(), ask=ask, log=lines.append)
    r.run()
    why = store.find(store.read(ws), url(1))["why"]
    assert "a person merges it on GitHub (no Merge card: the ticket file is locked)." in why
    assert any("Merge card for" in x for x in lines)


def test_an_older_loaded_core_still_gets_the_merge_card_through_the_installed_orch(ws, monkeypatch):
    """Issue 2576: a long running queue had an older orch.tickets loaded (no PRIORITIES): no Merge card."""
    from orch import tickets

    monkeypatch.delattr(tickets, "PRIORITIES")
    ran = []
    monkeypatch.setattr(runner, "_ask_installed", lambda root, argv: ran.append(argv))
    runner._make_card(ws, "t_abc123", "QE-1", url(1))
    assert ran and ran[0][:2] == ["ask", "t_abc123"] and "--merge" in ran[0] and url(1) in ran[0]


def test_the_installed_orch_ask_refusing_says_what_to_do(ws, monkeypatch):
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "No ticket t_x.\n")
    )
    with pytest.raises(Refused, match=r"orch ask said: No ticket t_x; make the Merge card by hand"):
        runner._ask_installed(ws, ["ask", "t_x"])


CI = {"files": [".github/workflows/ci.yml"]}


def test_a_lone_pull_request_takes_at_most_one_round_in_three_while_groups_wait(ws):
    """ORCH-1377: a lone one (CI change or Merge card) no longer stops every group behind it for its own run."""
    add(ws, 1, 2, 3, 4, 5, 6, 7)
    (ws / ".orch" / "config.toml").write_text(
        "[pull_requests]\nmax_group = 2\noverlap = false\n", encoding="utf-8"
    )
    gh = FakeGitHub({1: CI, 3: CI, 2: {}, 4: {}, 5: {}, 6: {}, 7: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    rounds = [gh.groups[c] for c in calls]
    assert rounds == [[1], [2, 4], [5, 6], [3], [7]]  # #1 due at the start, #3 waits two rounds for its turn
    assert all(len(g) == 1 for g in rounds if 1 in g or 3 in g)  # still checked alone on top of develop


def test_a_lone_pull_request_not_due_says_so_and_runs_when_nothing_else_waits(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: CI, 2: CI})
    r, _ = make(ws, gh, FakeGit())
    r._since_lone = 0  # one ran just now
    batch = r.next_batch()
    assert [e["number"] for e in batch] == [1]  # nothing else can run: no empty round for a turn
    store.back_to_front(ws, [url(1)], "x")
    add(ws, 3)
    gh.prs[3] = {}
    assert [e["number"] for e in r.next_batch()] == [3]
    assert "waits for its turn" in store.find(store.read(ws), url(1))["why"]


def test_a_lone_fix_goes_first_whatever_the_turn(ws):
    add(ws, 2)
    store.add(ws, url(1), None, "agent:t", login="bot", first=True)
    gh = FakeGitHub({1: CI, 2: {}})
    r, _ = make(ws, gh, FakeGit())
    r._since_lone = 0
    assert [e["number"] for e in r.next_batch()] == [1]


def test_a_done_ticket_that_does_not_link_the_pull_request_is_not_opened(ws, monkeypatch):
    """Only the ticket the pull request belongs to opens again; a wrong --ticket never reopens someone's work."""
    from orch import tickets

    monkeypatch.setattr(runner, "_make_card", lambda *a: None)
    t = tickets.create(ws, "Other work", by="human:p")
    tickets.set_status(ws, t["id"], "done", "human:p")
    add(ws, 1, ticket=t["id"])
    r, _ = make(ws, FakeGitHub({1: CI}), FakeGit(), ask=runner._ask_merge)
    r.run()
    assert tickets.load(ws, t["id"])["status"] == "done"
    assert "is Done and does not link" in store.find(store.read(ws), url(1))["why"]


def _said_merge(ws, n, head, answer="Merge", action="approve", by="human:severin"):
    """A ticket with the Merge card of pull request n, answered as given at commit head (ORCH-1118)."""
    from orch import tickets

    t = tickets.create(ws, "CI change", by="human:p")
    t = tickets.load(ws, t["id"])
    t["questions"] = [{
        "id": "q9", "text": "Merge the CI change?", "answer": answer, "answered_by": by,
        "decision": {"action": action}, "action": {"merge": url(n), "head": head},
        "card": {"kind": "link", "open": url(n), "ok_label": "Merge"},
    }]  # fmt: skip
    tickets.save(ws, t)
    return t["id"], str(t.get("key") or t["id"])


class SaidGitHub(FakeGitHub):
    """Also takes the queue's review and its merge of the pull request itself."""

    def __init__(self, prs, review_err="", merge_err=""):
        super().__init__(prs)
        self.review_err, self.merge_err, self.reviews, self.merged = review_err, merge_err, [], []

    def approve(self, u, head, body):
        self.reviews.append((u, head, body))
        return self.review_err

    def merge_pr(self, u, head):
        if self.merge_err:
            return self.merge_err
        self.merged.append((u, head))
        self.prs[int(u.rsplit("/", 1)[1])]["state"] = "MERGED"
        return ""


def test_the_persons_merge_on_their_own_workflow_change_is_approved_and_merged_by_the_queue(ws):
    """ORCH-1118 (#2829 q9): the owner wrote the pull request, so GitHub refused his own review and nobody could
    land it. Their Merge on the card at this commit lets the queue approve it with its login and merge it."""
    tid, key = _said_merge(ws, 1, f"{1:040d}")
    add(ws, 1, ticket=tid)
    asked = []
    gh = SaidGitHub({1: {"files": [".github/workflows/ci.yml"]}})
    r, calls = make(ws, gh, FakeGit(), ask=lambda *a: asked.append(a) or "X")
    r.run()
    assert members(gh, calls) == [[1]] and states(ws) == {1: "merged"} and not asked
    assert gh.merged == [(url(1), f"{1:040d}")]
    assert gh.reviews[0][:2] == (url(1), f"{1:040d}") and f"Merge card {key} q9" in gh.reviews[0][2]
    assert f"as the Merge on {key} q9 said" in store.find(store.read(ws), url(1))["why"]


def test_a_review_github_does_not_count_says_what_the_owner_changes(ws):
    tid, _ = _said_merge(ws, 1, f"{1:040d}")
    add(ws, 1, ticket=tid)
    gh = SaidGitHub(
        {1: {"files": [".github/workflows/ci.yml"]}}, merge_err="the base branch policy prohibits the merge"
    )
    r, _ = make(ws, gh, FakeGit())
    r.run()
    why = store.find(store.read(ws), url(1))["why"]
    assert states(ws) == {1: "out"} and gh.prs[1].get("state", "OPEN") == "OPEN"
    assert "base branch policy prohibits" in why and "code owner of these files in .github/CODEOWNERS" in why


@pytest.mark.parametrize(
    "head, action, by",
    [
        ("f" * 40, "approve", "human:severin"),
        (f"{1:040d}", "send_back", "human:severin"),
        (f"{1:040d}", "approve", "agent:x"),
    ],
)
def test_only_a_persons_merge_on_this_very_commit_lets_the_queue_merge_it(ws, head, action, by):
    tid, _ = _said_merge(ws, 1, head, action=action, by=by)
    add(ws, 1, ticket=tid)
    asked = []
    gh = SaidGitHub({1: {"files": [".github/workflows/ci.yml"]}})
    r, _ = make(ws, gh, FakeGit(), ask=lambda root, t, u: asked.append(u) or "ORCH-9")
    r.run()
    assert not gh.reviews and not gh.merged and asked == [url(1)]  # a new card for the person, as before
