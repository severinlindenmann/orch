"""A merge card: `orch ask ... --link T --open <PR> --merge`. The person's Merge click (CLI, dashboard or a
paired phone, all through review.decide) merges the pull request with the person's own GitHub login: helper
token variables are dropped, and only a person's click merges. A refused merge saves no answer."""

import json
import os
import subprocess

import pytest

from orch import ghmerge, review, tickets

PR = "https://github.com/acme/app/pull/12"
HEAD = "a" * 40
ME = "human:pat"


class FakeGh:
    """Stands in for the gh command line: records every call and the token variables it was given."""

    def __init__(self, state="OPEN", merge_rc=0, merge_err="", login="pat-gh", user_rc=0):
        self.calls, self.envs, self.review, self.head = [], [], "", HEAD
        self.state, self.merge_rc, self.merge_err = state, merge_rc, merge_err
        self.login, self.user_rc = login, user_rc
        self.summary = (
            None  # what `gh pr view --json title,...` answers when the card is made (None: refused)
        )

    def __call__(self, argv, env=None, **kw):
        args = argv[1:]
        self.calls.append(args)
        env = os.environ if env is None else env  # no env= given: the process environment
        self.envs.append({k: env[k] for k in ghmerge.TOKEN_VARS if k in env})
        if args[:2] == ["api", "user"]:
            return subprocess.CompletedProcess(argv, self.user_rc, self.login + "\n", "")
        if args[:2] == ["pr", "view"] and "title,baseRefName,commits,statusCheckRollup" in args:
            if self.summary is None:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.summary), "")
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, f"{self.state}\t{self.review}\t{self.head}\n", "")
        if args[:3] == ["api", "-X", "POST"]:
            self.review = "APPROVED"
            return subprocess.CompletedProcess(argv, 0, "{}", "")
        if args[:2] == ["pr", "merge"]:
            if self.merge_rc == 0:
                self.state = "MERGED"
            return subprocess.CompletedProcess(argv, self.merge_rc, "", self.merge_err)
        raise AssertionError(args)

    @property
    def merges(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: "/fake/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(ghmerge.subprocess, "run", fake)
    monkeypatch.setenv("GH_TOKEN", "helper-token-value")
    monkeypatch.setenv("GITHUB_TOKEN", "helper-token-value")
    FakeGh.current = fake
    return fake


@pytest.fixture
def tk(proj, run, gh):
    code, out, _ = run("ticket", "new", "Release 27", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _ask(run, tid, *extra):
    got = _ask_only(run, tid, *extra)
    FakeGh.current.calls.clear()  # reading the pull request when the card is made is not the merge
    FakeGh.current.envs.clear()
    return got


def _ask_only(run, tid, *extra):
    return run(
        "ask", tid, "Merge release 27 into main?", "--link", "Release 27", "--open", PR, "--merge",
        "--then", "Release 27 goes to main.", *extra, "--json", "--by", "agent:x",
    )  # fmt: skip


def _q(root, tid, qid="q1"):
    return next(x for x in tickets.load(root, tid)["questions"] if x["id"] == qid)


def test_ask_makes_a_link_card_with_merge(tk, run, validate):
    root, tid = tk
    code, out, err = _ask(run, tid)
    assert code == 0, out + err
    q = _q(root, tid)
    assert q["card"]["kind"] == "link" and q["card"]["ok_label"] == "Merge"
    assert q["card"]["open"] == PR and "own GitHub login" in q["card"]["why"]
    assert q["action"] == {"merge": PR, "head": HEAD} and review.merge_url(q) == PR
    assert q.get("kind") in (None, "plain")  # stays on the person's Review stack
    validate(tickets.load(root, tid))
    code, out, _ = run("review", "list", "--json")
    assert [c["key"] for c in json.loads(out)["cards"] if c["ticket"] == tid] == ["q1"]


@pytest.mark.parametrize(
    "argv",
    [
        ["--link", "T", "--open", "https://example.com/x", "--merge"],  # not a pull request
        ["--link", "T", "--open", "https://github.com/acme/app/issues/3", "--merge"],
        ["--draft", "T", "--merge"],  # only a link card merges
        ["--merge"],  # no card at all
    ],
)
def test_merge_needs_a_link_card_on_a_pull_request(tk, run, argv):
    root, tid = tk
    code, out, err = run("ask", tid, "Merge?", *argv, "--then", "x", "--by", "agent:x")
    assert code == 2 and "--merge goes with" in out + err
    assert tickets.load(root, tid)["questions"] == []


def test_person_click_merges_with_own_login_and_saves_the_answer(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    d = tickets.question_digest(_q(root, tid))
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--digest", d, "--by", ME)
    assert code == 0, out + err
    assert gh.merges == [["pr", "merge", PR, "--merge", "--match-head-commit", HEAD]]
    assert all(e == {} for e in gh.envs)  # the helper's tokens never reach gh: its own sign-in merges
    q = _q(root, tid)
    assert q["answer"] == "Merge" and q["answered_by"] == ME
    hist = [h["text"] for h in tickets.load(root, tid)["history"]]
    assert f"Merged the pull request on GitHub as pat-gh: {PR}" in hist


def test_not_now_merges_nothing(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    code, *_ = run("review", "answer", tid, "q1", "--verdict", "no", "--by", ME)
    assert code == 0 and gh.calls == []
    assert _q(root, tid)["decision"]["action"] == "dont"


def test_refused_merge_saves_no_answer_and_can_be_clicked_again(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.merge_rc, gh.merge_err = 1, "X Pull request acme/app#12 is not mergeable: checks are failing.\n"
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2
    assert "GitHub did not merge it: Pull request acme/app#12 is not mergeable" in out + err
    assert "Open the pull request and merge it there." in out + err
    assert _q(root, tid)["answer"] is None
    gh.merge_rc = 0
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    assert len(gh.merges) == 2 and _q(root, tid)["answer"] is not None


def test_already_merged_is_not_merged_twice(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.state = "MERGED"
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    assert gh.merges == []
    hist = [h["text"] for h in tickets.load(root, tid)["history"]]
    assert f"The pull request was merged already on GitHub (pat-gh): {PR}" in hist


def test_closed_pull_request_and_no_gh_say_what_to_do(tk, run, gh, monkeypatch):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.state = "CLOSED"
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2 and "closed on GitHub" in out + err and gh.merges == []
    gh.state, gh.user_rc = "OPEN", 1  # gh not signed in
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2 and "signed in with your own account" in out + err
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: None)
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2 and "(gh)" in out + err
    assert _q(root, tid)["answer"] is None and gh.merges == []


def test_an_agent_never_merges(tk, run, gh, monkeypatch):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    q = _q(root, tid)
    with pytest.raises(tickets.Refused, match="Only a person merges this"):
        review.decide(root, tid, "q1", "ok", by="agent:x", via="cli")
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")  # a human: label inside an agent's run
    with pytest.raises(tickets.Refused, match="Only a person merges this"):
        review.decide(root, tid, "q1", "ok", by=ME, via="cli")
    # plain `orch answer` never records a merge answer without the merge
    with pytest.raises(tickets.Refused, match="answer it on the card"):
        tickets.answer(
            root, tid, "q1", "Merge", ME, "cli", expected_question_digest=tickets.question_digest(q)
        )
    assert gh.calls == [] and _q(root, tid)["answer"] is None


def test_a_paired_phone_answer_merges_even_when_a_helper_reads_the_inbox(tk, run, gh, monkeypatch):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    out = review.decide(root, tid, "q1", "ok", by="human:Pat iPhone", via="phone")
    assert out["answer"] == "Merge" and gh.merges == [
        ["pr", "merge", PR, "--merge", "--match-head-commit", HEAD]
    ]
    assert all(e == {} for e in gh.envs)


def test_changed_card_is_refused_before_any_merge(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--digest", "0" * 64, "--by", ME)
    assert code == 2 and gh.calls == []


def test_change_after_not_now_merges_and_a_merge_cannot_be_taken_back(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    assert run("review", "answer", tid, "q1", "--verdict", "no", "--by", ME)[0] == 0
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    assert len(gh.merges) == 1
    newest = tickets.load(root, tid)["questions"][-1]
    assert newest["decision"]["action"] == "approve" and newest["decision"]["replaces"] == "q1"
    code, out, err = run("review", "answer", tid, newest["id"], "--verdict", "no", "--by", ME)
    assert code == 2 and "cannot be taken back" in out + err


def test_a_required_review_is_the_persons_own_before_the_merge(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.review = "REVIEW_REQUIRED"
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    acts = [c[:2] for c in gh.calls]
    assert acts == [["api", "user"], ["pr", "view"], ["api", "-X"], ["pr", "merge"]]
    assert gh.calls[2][:4] == ["api", "-X", "POST", "repos/acme/app/pulls/12/reviews"]
    assert f"commit_id={HEAD}" in gh.calls[2] and "event=APPROVE" in gh.calls[2]
    assert all(e == {} for e in gh.envs)


def test_no_review_when_none_is_required(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.review = "APPROVED"
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    assert ["api", "-X"] not in [c[:2] for c in gh.calls]


def test_a_hand_made_merge_action_never_merges(tk, run, gh):
    root, tid = tk
    code, out, err = run("ask", tid, "Ok?", "--action", json.dumps({"merge": PR}), "--by", "agent:x")
    assert code == 2 and "A merge goes with a link card" in out + err
    # a card whose shown address differs from the merged one is no merge card
    assert _ask(run, tid)[0] == 0
    q = _q(root, tid)
    assert (
        review.merge_url({**q, "card": {**q["card"], "open": "https://github.com/acme/app/pull/99"}}) is None
    )
    assert review.merge_url({**q, "card": {**q["card"], "ok_label": "Looks good"}}) is None
    assert review.merge_url({**q, "card": {**q["card"], "kind": "draft"}}) is None
    assert review.merge_url({**q, "card": None}) is None and review.merge_url(q) == PR


def test_merge_button_always_says_merge(tk, run):
    root, tid = tk
    assert _ask(run, tid, "--ok", "Ship it")[0] == 0
    q = _q(root, tid)
    assert q["card"]["ok_label"] == "Merge" and review.merge_url(q) == PR


def test_card_shows_and_pins_the_newest_commit(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    q = _q(root, tid)
    assert q["action"] == {"merge": PR, "head": HEAD}
    assert q["card"]["preview"]["paras"] == [f"Merges commit {HEAD[:7]} exactly."]
    assert PR not in json.dumps(q["card"]["preview"]), "the address is the Open link, not the content"
    assert q["card"]["open"] == PR


def test_a_release_card_shows_what_goes_out_and_the_checks(tk, run, gh):
    """ORCH-183, owner 17 Nov: a Merge card shows what the person decides on, not the address."""
    root, tid = tk
    code, out, _ = run("ticket", "new", "Review on desktop", "--json", "--by", "agent:x")
    other = json.loads(out)["id"]
    assert run("ref", "add", other, "https://github.com/acme/app/pull/7", "--by", "agent:x")[0] == 0
    ok = {
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "workflowName": "ci",
        "name": "gate",
        "startedAt": "1",
    }
    gh.summary = {
        "title": "Release 32",
        "baseRefName": "main",
        "commits": [
            {"messageHeadline": "Merge pull request #7 from acme/feat/x", "messageBody": "Bigger pictures"},
            {"messageHeadline": "Fix a typo", "messageBody": ""},
            {
                "messageHeadline": "Merge pull request #9 from acme/fix/y",
                "messageBody": "Send back asks for words\n\nmore",
            },
        ],
        "statusCheckRollup": [ok, {**ok, "name": "lint"}],
    }
    assert _ask(run, tid)[0] == 0
    pv = _q(root, tid)["card"]["preview"]
    assert pv["heading"] == "What goes to main"
    assert pv["steps"] == [
        f"{tickets.load(root, other)['key']} Review on desktop (#7)",
        "Send back asks for words (#9)",
    ]
    assert pv["paras"][0].startswith("Checks at ") and pv["paras"][0].endswith(": all 2 passed.")
    assert pv["paras"][1] == f"Merges commit {HEAD[:7]} exactly."
    review.check_wire_card(review.wire_card(_q(root, tid)["card"], {}), 0)  # still a valid phone card


def test_checks_in_plain_words():
    run_ = {"status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "ci", "startedAt": "1"}
    assert ghmerge.checks_words([]) == "no checks ran"
    assert ghmerge.checks_words([{**run_, "name": "a"}, {**run_, "name": "b"}]) == "all 2 passed"
    assert (
        ghmerge.checks_words([{**run_, "name": "a"}, {"status": "IN_PROGRESS", "name": "b"}])
        == "1 of 2 still running"
    )
    assert ghmerge.checks_words([{**run_, "name": "a", "conclusion": "FAILURE"}]) == "1 failed: a"


def test_a_push_after_the_card_is_never_merged(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.head, gh.review = "b" * 40, "REVIEW_REQUIRED"
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2 and "changed after the card was made" in out + err
    assert gh.merges == [] and ["api", "-X"] not in [c[:2] for c in gh.calls]
    assert _q(root, tid)["answer"] is None


def test_card_only_for_an_open_pull_request(tk, run, gh):
    root, tid = tk
    gh.state = "MERGED"
    code, out, err = _ask_only(run, tid)
    assert code == 2 and "not open on GitHub" in out + err
    assert tickets.load(root, tid)["questions"] == []
