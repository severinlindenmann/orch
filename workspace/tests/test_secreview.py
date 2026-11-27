"""The release keeper's security check (ORCH-317): pull requests that touch the servers, sign-in, secrets or
what leaves this computer get a security review by themselves, and no release is cut without every OK."""

import json

import pytest

from orch import releasekeeper as rk
from orch import secreview
from orch.errors import Refused

DEV, MAIN = "d" * 40, "m" * 40
UN = [
    {"sha": f"{i}" * 40, "at": "2026-11-17T00:00:00+00:00", "subject": f"Merge pull request #{i} from x/y"}
    for i in (1, 2)
]


def pr(n, files, head=None, draft=False):
    return {
        "number": n,
        "title": f"Change {n}",
        "url": f"https://github.com/x/y/pull/{n}",
        "headRefOid": head or f"h{n}",
        "isDraft": draft,
        "files": [{"path": f} for f in files],
    }


def change(n, files, head=None, pr_no=True):
    return {
        "sha": f"{n}" * 40,
        "files": files,
        "pr": n if pr_no else None,
        "head": (head or f"h{n}") if pr_no else None,
        "title": f"Merge pull request #{n} from x/y",
        "url": f"https://github.com/x/y/pull/{n}",
    }


SAFE = change(1, ["workspace/src/orch/cli.py", "docs/x.md"])
RELAY = change(2, ["relay/src/subs.rs", "workspace/src/orch/relay.py"])


def go(tmp_path, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN})
    sim.setdefault("last_release", 30)
    sim.setdefault("changes", [SAFE, RELAY])
    sim.setdefault(
        "pr_for_commit",
        {c["sha"]: {"pr": c["pr"], "head": c["head"], "url": c["url"]} for c in sim["changes"] if c["pr"]},
    )
    st = json.loads(json.dumps(sim.pop("state", {})))
    over = sim.pop("cfg", {})
    cfg = rk.Cfg(None, keeper="ORCH-79", repo="x/y", clone=str(tmp_path), run_dir=tmp_path, **over)
    w = rk.World(None, cfg, json.loads(json.dumps(sim)))
    lines = rk.pass_once(w, st, "ORCH-79", None)
    return json.loads(json.dumps({"state": st, "did": w.did, "lines": lines}, default=str))


def entry(n=2, sha="h2", **kw):
    return {"security": {"prs": {str(n): {"sha": sha, "tid": f"t_sec{n}", "key": f"SEC-{n}", **kw}}}}


# ---------------------------------------------------------------- matching


@pytest.mark.parametrize(
    "path",
    [
        "relay/src/subs.rs",
        "publish/src/main.rs",
        "contracts/relay-api.md",
        "workspace/src/orch/relay.py",
        "workspace/src/orch/secretscan.py",
        "workspace/src/orch/phone_view.py",
        "workspace-addons/dashboard/src/orch_dashboard/framepass.py",
        "workspace-addons/dashboard/src/orch_dashboard/server.py",
        "workspace-addons/dashboard/src/orch_dashboard/web/session.js",
        "workspace/src/orch/agents/login.json",
        "workspace/src/orch/renew.py",
        ".github/workflows/ci.yml",
    ],
)
def test_the_hand_reviewed_files_of_17_nov_need_a_review(path):
    assert secreview.matched([path], secreview.DEFAULT_PATHS) == [path]


@pytest.mark.parametrize(
    "path",
    [
        "workspace/src/orch/cli.py",
        "workspace/src/orch/session_history.py",
        "workspace/tests/test_relay.py",
        "relay/tests/review_card_adversarial.rs",
        "mobile/OrchMobileTests/TakenBackTests.swift",
        "workspace-addons/dashboard/web/app.test.js",
        "docs/relay.md",
    ],
)
def test_tests_docs_and_other_code_need_none(path):
    assert secreview.matched([path], secreview.DEFAULT_PATHS) == []


def test_own_paths_replace_the_defaults():
    pats = secreview.patterns("billing/*, *token*")
    assert secreview.matched(["billing/a.py", "relay/x.rs", "src/token_store.py"], pats) == [
        "billing/a.py",
        "src/token_store.py",
    ]
    assert secreview.patterns(None) == secreview.DEFAULT_PATHS


def test_the_paths_setting_refuses_nonsense():
    assert secreview.check_patterns(" relay/* , *secret* ") == "relay/*,*secret*"
    with pytest.raises(Refused):
        secreview.check_patterns("relay/*;rm -rf /")


# ---------------------------------------------------------------- the keeper's pass


def test_a_merged_relay_change_gets_a_review_and_holds_the_release(tmp_path):
    out = go(tmp_path)
    assert out["did"] == ["security-review:#2"]
    assert "#2: security review SEC-2 opened (2 file(s)); helper started" in out["lines"]
    assert out["lines"][-1] == "waits for every security OK: #2 (security review SEC-2 running)"
    assert out["state"]["security"]["prs"]["2"]["sha"] == "h2"
    assert out["state"].get("release") is None


def test_a_running_review_is_not_started_twice(tmp_path):
    out = go(tmp_path, state=entry(), open_reviews=["t_sec2"])
    assert out["did"] == []
    assert out["lines"] == ["waits for every security OK: #2 (security review SEC-2 running)"]


def test_every_ok_lets_the_release_go_on(tmp_path):
    out = go(tmp_path, state=entry(), security_verdicts={"2": {"sha": "h2", "verdict": "ok"}})
    assert not any("security" in x for x in out["lines"])
    assert out["did"] and out["did"][0].startswith("test-branch:")  # the normal cut path starts (ORCH-1475)
    assert out["did"][1].startswith("dispatch:")


def test_no_matched_pull_request_changes_nothing(tmp_path):
    out = go(tmp_path, changes=[SAFE, change(2, ["docs/a.md"])])
    assert not any("security" in x for x in out["lines"]) and out["state"]["security"]["prs"] == {}


def test_an_ok_for_an_older_head_does_not_count(tmp_path):
    st = entry(sha="old")
    st["security"]["prs"]["2"]["tid"] = "t_old"
    out = go(
        tmp_path,
        state=st,
        open_reviews=["t_old"],
        security_verdicts={"2": {"sha": "old", "verdict": "ok"}},
    )
    assert out["lines"][-1] == "waits for every security OK: #2 (security review SEC-2 running)"


def test_a_moved_pull_request_ends_its_open_older_review_and_starts_one_for_the_new_head(tmp_path):
    # #2403: the old review ticket stayed open, so the keeper waited on it forever while it could never
    # record a verdict for the new head
    st = entry(sha="old")
    st["security"]["prs"]["2"].update(tid="t_old", key="SEC-1")
    out = go(tmp_path, state=st, open_reviews=["t_old"])
    assert out["did"] == ["security-review:#2", "drop-review:#2 t_old"]
    assert out["state"]["security"]["prs"]["2"]["sha"] == "h2"
    assert "#2: the review of its older commit (t_old) ended, replaced by SEC-2" in out["lines"]
    again = go(tmp_path, state=out["state"], open_reviews=["t_sec2"])
    assert again["did"] == []  # the new review runs; nothing is dropped twice


def test_a_moved_review_is_dropped_as_superseded_on_the_real_ticket(tmp_path, monkeypatch):
    from orch import tickets

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(tickets, "log", lambda *a, **k: calls.append(("log", a[1])))
    monkeypatch.setattr(
        tickets, "set_status", lambda r, t, s, by, superseded_by=None: calls.append((s, t, superseded_by))
    )
    w = rk.World(
        root, rk.Cfg(None, keeper="ORCH-79", repo="x/y", clone=str(tmp_path), run_dir=tmp_path), None
    )
    lines = secreview._drop_stale(w, 2, "t_old", {"tid": "t_new", "key": "SEC-9", "sha": "h2"})
    assert calls == [("log", "t_old"), ("dropped", "t_old", "t_new")]
    assert lines == ["#2: the review of its older commit (t_old) ended, replaced by SEC-9"]


def test_a_finished_review_of_an_older_head_starts_a_new_one(tmp_path):
    out = go(tmp_path, state=entry(sha="old"), security_verdicts={"2": {"sha": "old", "verdict": "ok"}})
    assert out["did"] == ["security-review:#2"] and out["state"]["security"]["prs"]["2"]["sha"] == "h2"


def test_problems_ask_one_card_and_hold(tmp_path):
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "token in the log"}}
    out = go(tmp_path, state=entry(), security_verdicts=v)
    assert out["did"] == ["card:security #2"]
    assert out["lines"][-1] == "waits for every security OK: #2 (security review found problems)"
    assert out["state"]["security"]["prs"]["2"]["card_sha"] == "h2"
    again = go(tmp_path, state=out["state"], security_verdicts=v)
    assert again["did"] == []  # one card, never a second


def test_the_owners_release_anyway_counts_as_an_ok(tmp_path):
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "x"}}
    q = {"id": "q7", "text": "...", "answer": "Release anyway", "answered_by": "human:owner"}
    out = go(
        tmp_path,
        state=entry(card_sha="h2", qid="q7"),
        security_verdicts=v,
        ticket={"ORCH-79": {"questions": [q]}},
    )
    assert "#2: the owner said release anyway" in out["lines"]
    assert out["did"][0] == "note:Pull request #2: the owner said release anyway after the security review."
    assert any(d.startswith("dispatch:") for d in out["did"])


def test_an_agents_release_anyway_does_not_count(tmp_path):
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "x"}}
    q = {"id": "q7", "text": "...", "answer": "Release anyway", "answered_by": "agent:claude"}
    out = go(
        tmp_path,
        state=entry(card_sha="h2", qid="q7"),
        security_verdicts=v,
        ticket={"ORCH-79": {"questions": [q]}},
    )
    assert out["lines"][-1] == "waits for every security OK: #2 (security review found problems)"


def test_an_open_pull_request_gets_its_review_before_the_merge(tmp_path):
    out = go(
        tmp_path,
        heads={"develop": DEV, "main": MAIN, "unreleased": []},
        changes=[],
        open_prs=[pr(9, ["publish/src/a.rs"]), pr(10, ["relay/x.rs"], draft=True)],
    )
    assert out["did"] == ["security-review:#9"]  # a draft waits until it is ready
    assert out["lines"][-1] == "green develop has nothing main does not have"


def test_a_squash_merge_is_tied_to_its_pull_request_by_github(tmp_path):
    squash = change(2, ["relay/src/subs.rs"], pr_no=False)
    found = {"pr": 2, "head": "h2", "title": "Relay fix", "url": "https://github.com/x/y/pull/2"}
    out = go(tmp_path, changes=[SAFE, squash], pr_for_commit={squash["sha"]: found})
    assert out["did"] == ["security-review:#2"] and out["state"]["security"]["prs"]["2"]["sha"] == "h2"


def test_a_matched_change_with_no_pull_request_holds(tmp_path):
    out = go(tmp_path, changes=[SAFE, change(2, ["relay/src/subs.rs"], pr_no=False)])
    assert out["did"] == []
    assert out["lines"][-1] == (
        "waits for every security OK: 22222222 (changes relay/src/subs.rs but no pull request with its "
        "merged commit was found)"
    )


def test_a_merge_line_github_does_not_confirm_holds(tmp_path):
    out = go(tmp_path, pr_for_commit={RELAY["sha"]: {"pr": 2, "head": "other"}})
    assert out["did"] == []
    assert out["lines"][-1] == (
        "waits for every security OK: 22222222 (its merge line does not match pull request #2 on GitHub)"
    )
    none = go(tmp_path, pr_for_commit={})
    assert "no pull request with its merged commit was found" in none["lines"][-1]


def test_a_rename_out_of_a_matched_path_still_counts(tmp_path):
    # git's list without rename detection names both the old and the new path
    out = go(tmp_path, changes=[change(2, ["pkg/auth.py", "pkg/access.py"])])
    assert out["did"] == ["security-review:#2"]


def test_an_open_pull_request_with_a_cut_file_list_counts_as_matched(tmp_path):
    many = pr(9, [f"docs/p{i}.md" for i in range(secreview.TRUNCATED)])
    out = go(tmp_path, heads={"develop": DEV, "main": MAIN, "unreleased": []}, changes=[], open_prs=[many])
    assert out["did"] == ["security-review:#9"]


def test_ci_workflow_tests_are_never_left_out():
    assert secreview.matched([".github/workflows/tests/run.yml"], secreview.DEFAULT_PATHS) != []


def test_a_review_that_ended_twice_without_a_verdict_holds_and_says_so(tmp_path):
    out = go(tmp_path, state=entry(tries=2))
    assert out["did"] == []
    assert out["lines"][-1] == "waits for every security OK: #2 (security review ended without a verdict)"
    once = go(tmp_path, state=entry())
    assert once["did"] == ["security-review:#2"] and once["state"]["security"]["prs"]["2"]["tries"] == 2


W30 = "after-release-30"  # the window go() runs in (last_release 30)


def used_up(n=secreview.PER_DAY, **sec):
    return {"security": {"prs": {}, "starts": {W30: n}, **sec}}


def test_the_limit_holds_and_puts_one_card_instead_of_waiting_silently(tmp_path):
    out = go(tmp_path, state=used_up())
    assert out["did"] == ["card:security-limit #2"]
    assert "#2: waits for a security review (8 started for this release already)" in out["lines"]
    assert out["lines"][-1] == "waits for every security OK: #2 (security review not started yet)"
    card = out["state"]["security"]["limit_card"]
    assert card["window"] == W30 and card["prs"] == {"2": "h2"} and card["review"] == "Review these 1 now"
    again = go(tmp_path, state=out["state"])  # unanswered: no second card
    assert again["did"] == []
    assert again["lines"][-1] == "waits for every security OK: #2 (security review not started yet)"


LONG_FILES = [
    f"workspace-addons/dashboard/src/orch_dashboard/web/very/long/folder/name/session_{i}.js"
    for i in range(30)
]


@pytest.mark.parametrize("hits", [[], ["relay/src/subs.rs"], LONG_FILES[:12], LONG_FILES])
def test_the_review_note_always_fits_the_ticket_note_limit(hits):
    """ORCH-774: the brief with a full address and commit was 2004 to 2319 characters, every review was
    refused by the 2000-character note limit and release 35 waited a day."""
    from orch import tickets

    url, sha = "https://github.com/severinlindenmann/orch/pull/17286", "a2b2c2d" * 5 + "abcde"
    note = secreview.review_note(17286, url, sha, hits)
    assert len(note) <= secreview.NOTE_LIMIT
    assert tickets.clean_field("note", note) == note  # the ticket rule takes it as is
    assert note.count(url) == 1 and note.count(sha) == 1 and "orch review security 17286 ok" in note
    if hits:
        assert hits[0] in note and "need a review" in note
    if len(hits) > secreview.FILES_SHOWN:
        assert "more." in note


def test_a_refused_review_ticket_is_never_listed_as_done(tmp_path, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(tickets, "resolve", lambda root, ref: "t_role")

    def refuse(*a, **k):
        raise Refused("A note is at most 2000 characters; this one has 2025.")

    monkeypatch.setattr(tickets, "create", refuse)
    cfg = rk.Cfg(None, keeper="ORCH-79", repo="x/y", clone=str(tmp_path), run_dir=tmp_path)
    w = rk.World(tmp_path, cfg)
    sec = {"prs": {}, "starts": {W30: 3}}
    line = secreview._start(w, sec, "ORCH-79", pr(2, ["relay/src/subs.rs"]), ["relay/src/subs.rs"], W30)
    assert (
        line
        == "#2: could not open the security review: A note is at most 2000 characters; this one has 2025."
    )
    assert w.did == ["security-review:#2 failed"]
    assert sec == {"prs": {}, "starts": {W30: 3}}  # a failed try uses none of the limit


def test_a_closed_role_ticket_is_named_instead_of_a_refused_limit_card(tmp_path):
    closed = {"ORCH-79": {"key": "ORCH-79", "status": "done"}}
    out = go(tmp_path, state=used_up(), ticket=closed)
    assert out["did"] == []
    assert (
        "security limit: #2 wait; the role ticket ORCH-79 is closed, so the keeper cannot put its card "
        "there: set it back to Working" in out["lines"]
    )
    assert "limit_card" not in out["state"]["security"]  # asked again once the ticket is open
    assert out["lines"][-1] == "waits for every security OK: #2 (security review not started yet)"


def test_a_closed_role_ticket_is_named_instead_of_a_refused_problems_card(tmp_path):
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "token in the log"}}
    closed = {"ORCH-79": {"key": "ORCH-79", "status": "done"}}
    out = go(tmp_path, state=entry(), security_verdicts=v, ticket=closed)
    assert out["did"] == []
    assert any(
        "#2: security review found problems; the role ticket ORCH-79 is closed" in x for x in out["lines"]
    )
    assert "card_sha" not in out["state"]["security"]["prs"]["2"]
    assert out["lines"][-1] == "waits for every security OK: #2 (security review found problems)"


def test_the_limit_counts_per_release_not_per_day(tmp_path):
    old = {"security": {"prs": {}, "starts": {"after-release-29": 50, "2026-11-18": 8}}}
    out = go(tmp_path, state=old)
    assert out["did"] == ["security-review:#2"]
    assert out["state"]["security"]["starts"] == {W30: 1}


def test_the_limit_is_a_setting(tmp_path):
    out = go(tmp_path, state=used_up(), cfg={"security_limit": "30"})
    assert out["did"] == ["security-review:#2"]
    assert out["state"]["security"]["starts"] == {W30: 9}
    assert secreview.limit(None) == secreview.limit("x") == secreview.limit("0") == secreview.PER_DAY
    assert secreview.check_limit(" 30 ") == "30"
    for bad in ("0", "-3", "abc", "1.5", str(secreview.LIMIT_MAX + 1)):
        with pytest.raises(Refused):
            secreview.check_limit(bad)


def _limit_card_answered(tmp_path, answer, by="human:owner"):
    first = go(tmp_path, state=used_up())
    first["state"]["security"]["limit_card"]["qid"] = "q9"
    q = {"id": "q9", "text": "...", "answer": answer, "answered_by": by}
    return go(tmp_path, state=first["state"], ticket={"ORCH-79": {"questions": [q]}})


def test_review_them_now_starts_the_waiting_reviews(tmp_path):
    out = _limit_card_answered(tmp_path, "Review these 1 now")
    assert "security limit: the owner said review #2 now" in out["lines"]
    assert out["did"] == ["security-review:#2"]
    assert out["state"]["security"]["extra"] == {W30: 1}
    assert out["state"]["security"]["starts"] == {W30: 9}


def test_release_without_them_lets_the_release_go(tmp_path):
    out = _limit_card_answered(tmp_path, "Release without them")
    assert "security limit: the owner said release without a review of #2" in out["lines"]
    assert out["state"]["security"]["prs"]["2"]["owner_ok"] == "h2"
    assert any(d.startswith("dispatch:") for d in out["did"])  # the normal cut path starts
    assert not any(d.startswith("security-review:") for d in out["did"])


def test_release_without_them_never_overrides_a_review_started_since(tmp_path):
    first = go(tmp_path, state=used_up())
    st = first["state"]
    st["security"]["limit_card"]["qid"] = "q9"
    st["security"]["prs"]["2"] = {"sha": "h2", "tid": "t_sec2", "key": "SEC-2"}
    q = {"id": "q9", "text": "...", "answer": "Release without them", "answered_by": "human:owner"}
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "a way in without sign-in"}}
    out = go(tmp_path, state=st, ticket={"ORCH-79": {"questions": [q]}}, security_verdicts=v)
    assert "owner_ok" not in out["state"]["security"]["prs"]["2"]
    assert out["lines"][-1] == "waits for every security OK: #2 (security review found problems)"


def test_an_agents_answer_to_the_limit_card_does_not_count(tmp_path):
    out = _limit_card_answered(tmp_path, "Release without them", by="agent:claude")
    assert out["did"] == []
    assert out["lines"][-1] == "waits for every security OK: #2 (security review not started yet)"


def test_a_new_release_drops_the_old_limit_card(tmp_path):
    first = go(tmp_path, state=used_up())
    out = go(tmp_path, state=first["state"], last_release=31)
    assert out["state"]["security"]["limit_card"]["done"] == "a release went out"
    assert out["did"] == ["security-review:#2"]


def test_a_failed_github_read_holds_the_cut(tmp_path, monkeypatch):
    def boom(self):
        raise Refused("gh pr list: network down")

    monkeypatch.setattr(rk.World, "changes", boom)
    out = go(tmp_path)
    assert out["lines"][0] == "security check could not run: gh pr list: network down"
    assert out["lines"][-1] == "waits for every security OK: the security check could not run"
    assert not any(d.startswith("dispatch:") for d in out["did"])


def test_a_running_release_goes_on_while_a_review_runs(tmp_path):
    rel = {"n": 31, "sha": DEV, "phase": "card", "pr": 40}
    out = go(
        tmp_path,
        state={**entry(), "release": rel},
        open_reviews=["t_sec2"],
        prs={"40": {"state": "OPEN"}},
    )
    assert out["lines"][-1].startswith("release 31: waits for the Merge")


# ------------------------------------------------ a fix pull request ends a problems hold (ORCH-789)

FIX = change(3, ["relay/src/subs.rs"])


def _fix_state(**kw3):
    st = entry(card_sha="h2", qid="q7")
    st["security"]["prs"]["3"] = {"sha": "h3", "tid": "t_sec3", "key": "SEC-3", **kw3}
    return st


def test_a_merged_fix_with_a_security_ok_ends_the_problems_hold(tmp_path):
    v = {
        "2": {"sha": "h2", "verdict": "problems", "line": "race", "fixed_by": 3},
        "3": {"sha": "h3", "verdict": "ok", "line": "fine"},
    }
    out = go(tmp_path, changes=[SAFE, RELAY, FIX], state=_fix_state(), security_verdicts=v)
    assert not any("waits for every security OK" in x for x in out["lines"])
    assert any(d.startswith("dispatch:") for d in out["did"])  # the normal cut path starts


def test_a_fix_without_its_own_ok_still_holds_and_says_why(tmp_path):
    v = {
        "2": {"sha": "h2", "verdict": "problems", "line": "race", "fixed_by": 3},
        "3": {"sha": "h3", "verdict": "problems", "line": "still racy"},
    }
    out = go(tmp_path, changes=[SAFE, RELAY, FIX], state=_fix_state(card_sha="h3"), security_verdicts=v)
    assert "#2 (security review found problems; its fix #3 has no security OK yet)" in out["lines"][-1]


def test_a_fix_not_merged_in_this_release_still_holds(tmp_path):
    v = {"2": {"sha": "h2", "verdict": "problems", "line": "race", "fixed_by": 3}}
    out = go(tmp_path, state=entry(card_sha="h2", qid="q7"), security_verdicts=v)
    assert out["lines"][-1] == (
        "waits for every security OK: #2 (security review found problems; "
        "its fix #3 is not merged in this release with a security review)"
    )


def test_an_ok_for_an_older_head_of_the_fix_does_not_count(tmp_path):
    v = {
        "2": {"sha": "h2", "verdict": "problems", "line": "race", "fixed_by": 3},
        "3": {"sha": "old", "verdict": "ok", "line": "fine"},
    }
    st = _fix_state()
    st["security"]["prs"]["3"]["sha"] = "old"
    out = go(tmp_path, changes=[SAFE, RELAY, FIX], state=st, security_verdicts=v, open_reviews=["t_sec3"])
    assert "#2 (security review found problems; its fix #3 has no security OK yet)" in out["lines"][-1]


# #1568: a fix that changes no matched file (the fix of a server finding in a client file) was never reviewed,
# so its OK never came and the problems verdict could not be cleared
SAFE_FIX = change(3, ["workspace/src/orch/cli.py", "workspace/tests/test_cli.py"])
LINKED = {"2": {"sha": "h2", "verdict": "problems", "line": "race", "fixed_by": 3}}


def test_an_open_fix_that_touches_no_matched_file_gets_its_security_review(tmp_path):
    st = entry(card_sha="h2", qid="q7")
    out = go(tmp_path, state=st, security_verdicts=LINKED, open_prs=[pr(3, ["workspace/src/orch/cli.py"])])
    assert "security-review:#3" in out["did"]
    assert out["state"]["security"]["prs"]["3"]["files"] == ["workspace/src/orch/cli.py"]


def test_a_merged_fix_that_touches_no_matched_file_is_reviewed_and_its_ok_ends_the_hold(tmp_path):
    changes = [SAFE, RELAY, SAFE_FIX]
    out = go(tmp_path, changes=changes, state=entry(card_sha="h2", qid="q7"), security_verdicts=LINKED)
    assert "security-review:#3" in out["did"]
    assert out["state"]["security"]["prs"]["3"]["files"] == ["workspace/src/orch/cli.py"]  # tests left out
    v = {**LINKED, "3": {"sha": "h3", "verdict": "ok", "line": "fine"}}
    done = go(tmp_path, changes=changes, state=out["state"], security_verdicts=v)
    assert not any("waits for every security OK" in x for x in done["lines"])


def test_a_fix_merged_inside_a_queue_group_is_reviewed_as_its_member(tmp_path):
    grp = {**change(9, ["workspace/src/orch/cli.py"]), "title": "Merge pull request #9 from x/orch-queue/a1"}
    out = go(
        tmp_path,
        changes=[SAFE, RELAY, grp],
        state=entry(card_sha="h2", qid="q7"),
        security_verdicts=LINKED,
        groups={"9": [(3, "h3", [])]},
    )
    assert "security-review:#3" in out["did"] and out["state"]["security"]["prs"]["3"]["sha"] == "h3"
    assert "security-review:#9" not in out["did"]


def test_an_unlinked_change_that_touches_no_matched_file_still_gets_no_review(tmp_path):
    out = go(tmp_path, changes=[SAFE, RELAY, SAFE_FIX], state=entry(), security_verdicts={})
    assert "security-review:#3" not in out["did"]


# ---------------------------------------------------------------- the verdict command


def _keeper_state(root, st):
    from orch import runs

    d = runs.run_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / "release-keeper.json").write_text(json.dumps(st))


def test_a_person_records_a_verdict_for_the_reviewed_head(tmp_path, monkeypatch):
    from orch import tickets, worktrees

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    _keeper_state(root, entry(sha="a2b2c2d" + "0" * 33))
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: None)
    monkeypatch.setattr(tickets, "log", lambda *a, **k: {})
    with pytest.raises(Refused, match="Give the commit you reviewed"):
        secreview.verdict(root, 2, "ok", "fine", "human:owner", "abcdef0")
    res = secreview.verdict(root, 2, "ok", "  nothing High or Medium;  one Low  ", "human:owner", "a2b2c2d")
    assert res["sha"].startswith("a2b2c2d") and res["line"] == "nothing High or Medium; one Low"
    assert secreview.read_verdicts(root)["2"]["verdict"] == "ok"


def test_only_the_review_helper_of_that_pull_request_records_it(tmp_path, monkeypatch):
    from orch import worktrees

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    _keeper_state(root, entry())
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: "t_other")
    with pytest.raises(Refused, match="Only the security review helper"):
        secreview.verdict(root, 2, "ok", "fine", "agent:claude", "h2")
    with pytest.raises(Refused, match="not waiting for a security review"):
        secreview.verdict(root, 5, "ok", "fine", "human:owner", "h2")
    with pytest.raises(Refused, match="one line"):
        secreview.verdict(root, 2, "ok", "   ", "human:owner", "h2")


H2 = "a2b2c2d" + "0" * 33


def test_a_person_links_the_fix_of_a_problems_finding(tmp_path, monkeypatch):
    from orch import tickets, worktrees

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    _keeper_state(root, entry(sha=H2))
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: None)
    monkeypatch.setattr(tickets, "log", lambda *a, **k: {})
    with pytest.raises(Refused, match="no problems verdict"):
        secreview.link_fix(root, 2, 3, "human:owner")
    secreview.verdict(root, 2, "problems", "race in subs", "human:owner", H2[:7])
    with pytest.raises(Refused, match="not the same one"):
        secreview.link_fix(root, 2, 2, "human:owner")
    res = secreview.link_fix(root, 2, 3, "human:owner")
    assert res["fixed_by"] == 3
    got = secreview.read_verdicts(root)["2"]
    assert got["verdict"] == "problems" and got["fixed_by"] == 3 and got["line"] == "race in subs"


def test_another_helper_may_not_link_a_fix_even_from_a_sub_ticket(tmp_path, monkeypatch):
    from orch import tickets, worktrees

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    _keeper_state(root, entry(sha=H2))
    monkeypatch.setattr(tickets, "log", lambda *a, **k: {})
    monkeypatch.setattr(tickets, "load", lambda r, t: {"id": t, "parent": "t_sec2"})  # a helper can re-parent
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: "t_sec2")
    secreview.verdict(root, 2, "problems", "race", "agent:claude", H2[:7])
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: "t_recheck")
    with pytest.raises(Refused, match="fixed-by <fix pull request>"):
        secreview.link_fix(root, 2, 3, "agent:claude")
    with pytest.raises(Refused, match="Only the security review helper"):
        secreview.verdict(root, 2, "ok", "fine", "agent:claude", H2[:7])
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: "t_sec2")
    assert secreview.link_fix(root, 2, 3, "agent:claude")["fixed_by"] == 3


# ---------------------------------------------------------------- reading the release from git


def test_changes_reads_every_change_since_main_from_git(tmp_path):
    import subprocess

    repo = tmp_path / "clone"
    repo.mkdir()

    def git(*a):
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "auth.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-q", "-m", "start")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("checkout", "-q", "-b", "feature")
    git("mv", "pkg/auth.py", "pkg/access.py")
    git("commit", "-q", "-m", "rename")
    head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    git("merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #5 from x/feature")
    (repo / "README").write_text("y\n")
    git("add", ".")
    git("commit", "-q", "-m", "Direct change (#6)")
    git("update-ref", "refs/remotes/origin/develop", "HEAD")
    cfg = rk.Cfg(None, keeper="ORCH-79", repo="x/y", clone=str(repo), run_dir=tmp_path)
    got = rk.World(None, cfg).changes()
    assert [c["pr"] for c in got] == [None, 5]  # newest first; a "(#6)" in a subject is no proof
    assert got[1]["head"] == head and got[1]["url"] == "https://github.com/x/y/pull/5"
    assert sorted(got[1]["files"]) == ["pkg/access.py", "pkg/auth.py"]
    assert got[0]["files"] == ["README"]
