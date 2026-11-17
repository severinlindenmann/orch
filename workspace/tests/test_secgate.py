"""The release keeper's security gate (ORCH-317): pull requests that touch the servers, sign-in, secrets or
what leaves this computer get a security review by themselves, and no release is cut without every OK."""

import json

import pytest

from orch import releasekeeper as rk
from orch import secgate
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


SAFE = pr(1, ["workspace/src/orch/cli.py", "docs/x.md"])
RELAY = pr(2, ["relay/src/subs.rs", "workspace/src/orch/relay.py"])


def go(tmp_path, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN})
    sim.setdefault("last_release", 30)
    sim.setdefault("merged_prs", [SAFE, RELAY])
    st = json.loads(json.dumps(sim.pop("state", {})))
    cfg = rk.Cfg(None, keeper="ORCH-79", repo="x/y", clone=str(tmp_path), run_dir=tmp_path)
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
    assert secgate.matched([path], secgate.DEFAULT_PATHS) == [path]


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
    assert secgate.matched([path], secgate.DEFAULT_PATHS) == []


def test_own_paths_replace_the_defaults():
    pats = secgate.patterns("billing/*, *token*")
    assert secgate.matched(["billing/a.py", "relay/x.rs", "src/token_store.py"], pats) == [
        "billing/a.py",
        "src/token_store.py",
    ]
    assert secgate.patterns(None) == secgate.DEFAULT_PATHS


def test_the_paths_setting_refuses_nonsense():
    assert secgate.check_patterns(" relay/* , *secret* ") == "relay/*,*secret*"
    with pytest.raises(Refused):
        secgate.check_patterns("relay/*;rm -rf /")


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
    assert out["did"] and out["did"][0].startswith("dispatch:")  # the normal cut path starts


def test_no_matched_pull_request_changes_nothing(tmp_path):
    out = go(tmp_path, merged_prs=[SAFE, pr(2, ["docs/a.md"])])
    assert not any("security" in x for x in out["lines"]) and out["state"]["security"]["prs"] == {}


def test_an_ok_for_an_older_head_does_not_count(tmp_path):
    out = go(
        tmp_path,
        state=entry(sha="old"),
        open_reviews=["t_sec2"],
        security_verdicts={"2": {"sha": "old", "verdict": "ok"}},
    )
    assert (
        out["lines"][-1]
        == "waits for every security OK: #2 (security review of its last change still running)"
    )


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
        merged_prs=[],
        open_prs=[pr(9, ["publish/src/a.rs"]), pr(10, ["relay/x.rs"], draft=True)],
    )
    assert out["did"] == ["security-review:#9"]  # a draft waits until it is ready
    assert out["lines"][-1] == "develop has nothing main does not have"


def test_an_unreleased_pull_request_older_than_the_list_is_read_alone(tmp_path):
    out = go(tmp_path, merged_prs=[SAFE], pr_files={"2": RELAY})
    assert out["did"] == ["security-review:#2"]


def test_a_review_that_ended_twice_without_a_verdict_holds_and_says_so(tmp_path):
    out = go(tmp_path, state=entry(tries=2))
    assert out["did"] == []
    assert out["lines"][-1] == "waits for every security OK: #2 (security review ended without a verdict)"
    once = go(tmp_path, state=entry())
    assert once["did"] == ["security-review:#2"] and once["state"]["security"]["prs"]["2"]["tries"] == 2


def test_the_daily_cap_holds_instead_of_starting(tmp_path):
    out = go(tmp_path, state={"security": {"prs": {}, "starts": {secgate._day(): secgate.PER_DAY}}})
    assert out["did"] == []
    assert out["lines"][-1] == "waits for every security OK: #2 (security review not started yet)"


def test_a_failed_github_read_holds_the_cut(tmp_path, monkeypatch):
    def boom(self):
        raise Refused("gh pr list: network down")

    monkeypatch.setattr(rk.World, "merged_prs", boom)
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
    _keeper_state(root, entry())
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: None)
    monkeypatch.setattr(tickets, "log", lambda *a, **k: {})
    res = secgate.verdict(root, 2, "ok", "  nothing High or Medium;  one Low  ", "human:owner")
    assert res["sha"] == "h2" and res["line"] == "nothing High or Medium; one Low"
    assert secgate.read_verdicts(root)["2"]["verdict"] == "ok"


def test_only_the_review_helper_of_that_pull_request_records_it(tmp_path, monkeypatch):
    from orch import worktrees

    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    _keeper_state(root, entry())
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda r: "t_other")
    with pytest.raises(Refused, match="Only the security review helper"):
        secgate.verdict(root, 2, "ok", "fine", "agent:claude")
    with pytest.raises(Refused, match="not waiting for a security review"):
        secgate.verdict(root, 5, "ok", "fine", "human:owner")
    with pytest.raises(Refused, match="one line"):
        secgate.verdict(root, 2, "ok", "   ", "human:owner")
