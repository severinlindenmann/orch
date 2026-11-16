"""A merge card: `orch ask ... --link T --open <PR> --merge`. The person's Merge click (CLI, dashboard or a
paired phone, all through review.decide) merges the pull request with the person's own GitHub login: helper
token variables are dropped, and only a person's click merges. A refused merge saves no answer."""

import json
import subprocess

import pytest

from orch import ghmerge, review, tickets

PR = "https://github.com/acme/app/pull/12"
ME = "human:pat"


class FakeGh:
    """Stands in for the gh command line: records every call and the token variables it was given."""

    def __init__(self, state="OPEN", merge_rc=0, merge_err="", login="pat-gh", user_rc=0):
        self.calls, self.envs = [], []
        self.state, self.merge_rc, self.merge_err = state, merge_rc, merge_err
        self.login, self.user_rc = login, user_rc

    def __call__(self, argv, env=None, **kw):
        args = argv[1:]
        self.calls.append(args)
        self.envs.append({k: env[k] for k in ghmerge.TOKEN_VARS if k in env})
        if args[:2] == ["api", "user"]:
            return subprocess.CompletedProcess(argv, self.user_rc, self.login + "\n", "")
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, self.state + "\n", "")
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
    return fake


@pytest.fixture
def tk(proj, run):
    code, out, _ = run("ticket", "new", "Release 27", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _ask(run, tid, *extra):
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
    assert q["action"] == {"merge": PR} and review.merge_url(q) == PR
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
    assert gh.merges == [["pr", "merge", PR, "--merge"]]
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
    assert out["answer"] == "Merge" and gh.merges == [["pr", "merge", PR, "--merge"]]
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
