"""The release keeper (`orch github release`, ORCH-225; was the script release-keeper.py of ORCH-79): every
read and write of a pass simulated. The pass-level tests are the script's 52 tests, carried over."""

import json
import subprocess

import pytest

from orch import brake, tickets
from orch import releasekeeper as rk
from orch.errors import Refused

DEV, MAIN, OLD = "d" * 40, "m" * 40, "o" * 40
UN3 = [
    {"sha": f"{i}" * 40, "at": "2026-11-17T00:00:00+00:00", "subject": f"Merge pull request #{i} from x/y"}
    for i in range(1, 4)
]
WIN_FULL = "workspace / test (windows-latest)"
KNOWN = {WIN_FULL: "ORCH-32"}  # what the automation passes with --known-red


def cfg(tmp_path, **over):
    base = dict(
        keeper="ORCH-79",
        repo="severinlindenmann/orch",
        workflows="ci.yml:windows=true,e2e.yml",
        servers="relay,publish",
        clone=str(tmp_path / "clone"),
        run_dir=tmp_path,
    )
    return rk.Cfg(None, **{**base, **over})


def go(tmp_path, capsys=None, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN3})
    sim.setdefault("last_release", 30)
    st = json.loads(json.dumps(sim.pop("state", {})))
    hold = sim.pop("hold", None)
    w = rk.World(None, cfg(tmp_path), json.loads(json.dumps(sim)), known=KNOWN)
    lines = rk.pass_once(w, st, "ORCH-79", hold)
    return json.loads(json.dumps({"state": st, "did": w.did, "lines": lines}, default=str))


def run(sha, event, conclusion="success", status="completed", at="2026-11-17T01:00:00Z", rid=None):
    r = {
        "headSha": sha,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "createdAt": at,
        "url": "https://github.com/x/y/actions/runs/1",
    }
    if rid is not None:
        r["databaseId"] = rid
    return r


def job(name, conclusion="success", status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion}


CI_JOBS = [
    job("workspace / test (ubuntu-latest)"),
    job("workspace / test (macos-latest)"),
    job("workspace / windows-standard-user"),
    job("mobile / test"),
]


def test_nothing_unreleased_does_nothing(tmp_path, capsys):
    out = go(tmp_path, capsys, heads={"develop": DEV, "main": MAIN, "unreleased": []})
    assert out["did"] == [] and out["state"].get("release") is None


def test_a_release_less_than_3_hours_ago_waits(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat())
    assert out["did"] == [] and "next after 3 h" in out["lines"][0]


def test_an_urgent_pull_request_releases_at_once(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat(), urgent=[2])
    assert out["did"] == ["dispatch:ci.yml", "dispatch:e2e.yml"] and "#2" in out["lines"][0]


def test_an_urgent_label_on_older_work_does_not_count(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat(), urgent=[77])
    assert out["did"] == []


def test_a_blocked_try_does_not_move_the_pace(tmp_path, capsys):
    out = go(tmp_path, capsys, state={"last_cut_at": rk.now().isoformat()})
    assert out["did"] == ["dispatch:ci.yml", "dispatch:e2e.yml"]
    assert out["state"]["release"]["phase"] == "testing"


def test_a_started_try_does_not_write_the_pace(tmp_path, capsys):
    out = go(tmp_path, capsys)
    assert "last_cut_at" not in out["state"]


def test_the_pace_counts_from_the_last_merged_release(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat())
    assert out["did"] == []


def test_enough_merged_starts_the_full_signal(tmp_path, capsys):
    out = go(tmp_path, capsys)
    assert out["did"] == ["dispatch:ci.yml", "dispatch:e2e.yml"]
    rel = out["state"]["release"]
    assert rel["phase"] == "testing" and rel["n"] == 31 and rel["sha"] == DEV


def test_green_nightly_on_the_head_cuts_at_once(tmp_path, capsys):
    out = go(tmp_path, capsys, runs={"ci.yml": [run(DEV, "schedule")], "e2e.yml": [run(DEV, "schedule")]})
    assert [d.split(":")[0] for d in out["did"]] == ["cut"]
    assert out["state"]["release"]["phase"] == "gate" and out["state"]["release"]["pr"] == 9031


def test_hold_stops_cutting(tmp_path, capsys):
    out = go(tmp_path, capsys, hold="security fix pending")
    assert out["did"] == [] and "on hold" in out["lines"][0]


def in_testing(**kw):
    return {
        "n": 31,
        "sha": DEV,
        "phase": "testing",
        "dispatched_at": "2026-11-17T00:30:00+00:00",
        "unreleased": UN3,
        **kw,
    }


def test_both_dispatched_runs_green_cut(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": in_testing()},
        runs={"ci.yml": [run(DEV, "workflow_dispatch")], "e2e.yml": [run(DEV, "workflow_dispatch")]},
    )
    assert [d.split(":")[0] for d in out["did"]] == ["cut"] and out["state"]["release"]["phase"] == "gate"


def at(monkeypatch, iso):
    """Pin the keeper's clock: in_testing() dispatches at 00:30, and after TEST_TIMEOUT_H (4 h) the keeper
    gives up on the runs, so a test of the testing phase read on the wall clock went red every day after
    04:30 (ORCH-216)."""
    monkeypatch.setattr(rk, "now", lambda: rk.datetime.fromisoformat(iso))


def test_a_run_from_before_the_dispatch_does_not_count(tmp_path, capsys, monkeypatch):
    at(monkeypatch, "2026-11-17T01:00:00+00:00")
    old = run(DEV, "workflow_dispatch", at="2026-11-16T10:00:00Z")
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs={"ci.yml": [old], "e2e.yml": [old]})
    assert out["did"] == [] and "ci none, e2e none" in out["lines"][0]


def test_runs_that_do_not_finish_in_4_hours_are_given_up(tmp_path, capsys, monkeypatch):
    at(monkeypatch, "2026-11-17T05:00:00+00:00")
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs={"ci.yml": [], "e2e.yml": []})
    assert "did not finish in 4 h" in out["lines"][0] and out["state"]["release"] is None


def test_red_run_opens_one_top_ticket_and_skips_the_commit(tmp_path, capsys):
    runs = {"ci.yml": [run(DEV, "workflow_dispatch")], "e2e.yml": [run(DEV, "workflow_dispatch", "failure")]}
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs)
    assert out["did"] == ["ticket:e2e run is red on develop (release 31 blocked)"]
    assert out["state"]["release"] is None and out["state"]["skip_sha"] == DEV
    again = go(tmp_path, capsys, state=out["state"], runs=runs)
    assert again["did"] == [] and "was red" in again["lines"][0]  # same head: no new dispatch, no ticket


def test_red_with_an_open_ticket_makes_no_second(tmp_path, capsys):
    runs = {"ci.yml": [run(DEV, "workflow_dispatch", "failure")], "e2e.yml": []}
    open_t = [{"id": "t_1", "key": "ORCH-200", "status": "open", "title": "Nightly ci run is red on develop"}]
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs, tickets=open_t)
    assert not any(d.startswith("ticket:") for d in out["did"])
    assert any(d.startswith("note:") for d in out["did"])  # said once on the open ticket


ROLLUP_DONE = {"name": "gate", "status": "COMPLETED", "conclusion": "SUCCESS"}


def gate(**kw):
    return {"n": 31, "sha": DEV, "phase": "gate", "pr": 9031, "wt": "/x/release-31", "main_before": OLD, **kw}


def pr(state="OPEN", checks=None, body="- Fix A (#1)\n- Add B (#2)"):
    checks = (
        checks
        if checks is not None
        else [{"name": "t", "status": "COMPLETED", "conclusion": "SUCCESS"}, ROLLUP_DONE]
    )
    return {
        "9031": {
            "url": "https://github.com/x/y/pull/9031",
            "state": state,
            "statusCheckRollup": checks,
            "body": body,
        }
    }


def test_gate_pending_waits(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=[{"name": "t", "status": "IN_PROGRESS"}, ROLLUP_DONE]),
    )
    assert out["did"] == [] and "still running" in out["lines"][0]


def test_gate_green_asks_the_merge_card_and_tends(tmp_path, capsys):
    out = go(tmp_path, capsys, state={"release": gate()}, open_release={"number": 9031}, prs=pr())
    assert out["did"] == ["card:release 31", "tend-releases"]
    assert out["state"]["release"]["phase"] == "card"


def test_gate_red_opens_a_ticket(tmp_path, capsys):
    bad = [{"name": "macos", "status": "COMPLETED", "conclusion": "FAILURE"}, ROLLUP_DONE]
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=bad),
        heads={"develop": DEV, "main": MAIN, "unreleased": UN3},
    )
    assert out["did"] == ["ticket:Release 31 checks are red: macos"]


def test_gate_red_and_develop_moved_closes_and_recuts(tmp_path, capsys):
    bad = [{"name": "macos", "status": "COMPLETED", "conclusion": "FAILURE"}, ROLLUP_DONE]
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=bad),
        heads={"develop": "e" * 40, "main": MAIN, "unreleased": UN3},
    )
    assert out["did"] == ["close:release 31 PR 9031"] and out["state"]["release"] is None


def test_merged_updates_notes_highlights_and_asks_deploy(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card")},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/src/main.rs"],
    )
    kinds = [d.split(":")[0] for d in out["did"]]
    assert kinds == ["update", "deploy-card", "note", "rmwt"]
    note = next(d for d in out["did"] if d.startswith("note:"))
    assert "Release 31 is on main and installed here" in note
    assert out["state"]["release"] is None and out["state"]["last_installed"] == 31
    dep = out["state"]["deploy"]
    assert {k: dep[k] for k in ("n", "what", "sha")} == {"n": 31, "what": "relay", "sha": DEV}
    assert dep["prep"]["relay"]["ready"] is False and "no green relay build" in dep["prep"]["relay"]["why"]


def test_deploy_go_opens_a_helper_ticket(tmp_path, capsys):
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay server. Deploy it to production now?",
                "answer": "Deploy now",
                "answered_by": "human:t",
            }
        ]
    }
    out = go(
        tmp_path,
        capsys,
        state={"deploy": {"n": 31, "what": "relay"}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
    )
    assert out["did"] == ["ticket:Deploy release 31 relay to production"] and out["state"]["deploy"] is None


def test_a_release_the_keeper_did_not_cut_is_only_watched(tmp_path, capsys):
    out = go(tmp_path, capsys, open_release={"number": 1095})
    assert out["did"] == [] and "watching only" in out["lines"][0]


@pytest.mark.parametrize(
    ("rollup", "want"),
    [
        ([], "pending"),
        ([{"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"}], "green"),
        ([{"name": "a", "status": "COMPLETED", "conclusion": "SKIPPED"}], "pending"),
        (
            [
                {"name": "a", "status": "COMPLETED", "conclusion": "FAILURE", "startedAt": "1"},
                {"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "2"},
            ],
            "green",
        ),  # re-run
        (
            [
                {"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "b", "status": "COMPLETED", "conclusion": "CANCELLED"},
            ],
            "red",
        ),
        (
            [
                {"context": "x", "state": "PENDING"},
                {"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
            "pending",
        ),
    ],
)
def test_checks_green(rollup, want):
    assert rk.checks_green(rollup) == want


def test_known_red_windows_full_suite_is_noted_not_a_blocker(tmp_path, capsys):
    runs = {
        "ci.yml": [run(DEV, "workflow_dispatch", "failure", rid=5)],
        "e2e.yml": [run(DEV, "workflow_dispatch")],
    }
    jobs = {"5": [*CI_JOBS, job(WIN_FULL, "failure"), job("gate", "failure")]}
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs, jobs=jobs)
    assert [d.split(":")[0] for d in out["did"]] == ["cut"]
    assert out["state"]["release"]["known_red"] == [f"{WIN_FULL} (ORCH-32)"]


def test_known_red_still_running_is_not_waited_for(tmp_path, capsys):
    runs = {
        "ci.yml": [run(DEV, "workflow_dispatch", None, "in_progress", rid=5)],
        "e2e.yml": [run(DEV, "workflow_dispatch")],
    }
    jobs = {"5": [*CI_JOBS, job(WIN_FULL, None, "in_progress"), job("gate", None, "queued")]}
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs, jobs=jobs)
    assert [d.split(":")[0] for d in out["did"]] == ["cut"]


def test_windows_standard_user_red_blocks(tmp_path, capsys):
    runs = {
        "ci.yml": [run(DEV, "workflow_dispatch", "failure", rid=5)],
        "e2e.yml": [run(DEV, "workflow_dispatch")],
    }
    jobs = {
        "5": [job("workspace / test (ubuntu-latest)"), job("workspace / windows-standard-user", "failure")]
    }
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs, jobs=jobs)
    assert out["did"] == ["ticket:ci run is red on develop (release 31 blocked)"]


def test_known_red_counts_once_its_ticket_is_done(tmp_path, capsys):
    runs = {
        "ci.yml": [run(DEV, "workflow_dispatch", "failure", rid=5)],
        "e2e.yml": [run(DEV, "workflow_dispatch")],
    }
    jobs = {"5": [*CI_JOBS, job(WIN_FULL, "failure")]}
    done = [{"id": "t_32", "key": "ORCH-32", "status": "done", "title": "Windows full suite"}]
    out = go(tmp_path, capsys, state={"release": in_testing()}, runs=runs, jobs=jobs, tickets=done)
    assert out["did"] == ["ticket:ci run is red on develop (release 31 blocked)"]


def test_gate_ignores_known_red_and_the_rollup(tmp_path, capsys):
    checks = [
        {"name": "workspace / test (ubuntu-latest)", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": WIN_FULL, "status": "COMPLETED", "conclusion": "FAILURE"},
        {"name": "gate", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]
    out = go(
        tmp_path, capsys, state={"release": gate()}, open_release={"number": 9031}, prs=pr(checks=checks)
    )
    assert out["did"] == ["card:release 31", "tend-releases"]


def test_highlights_name_the_known_red_job(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card", known_red=[f"{WIN_FULL} (ORCH-32)"])},
        open_release=None,
        prs=pr("MERGED"),
    )
    note = next(d for d in out["did"] if d.startswith("note:"))
    assert "Release 31" in note


# A release pull request goes INTO main: main's required checks count, never develop's (manager, 17 Nov:
# develop's second required check, banned-words, is skipped on release/* into main by design and must not
# hold the release).
RELEASE_1113 = [
    {"name": "workspace / test (ubuntu-latest)", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"name": "mobile", "status": "COMPLETED", "conclusion": "SKIPPED"},
    {"name": "banned-words", "status": "COMPLETED", "conclusion": "SKIPPED"},
    ROLLUP_DONE,
]


def test_release_into_main_with_develops_second_check_skipped_is_green(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=RELEASE_1113),
        required={"develop": ["banned-words", "gate"], "main": []},
    )
    assert out["did"] == ["card:release 31", "tend-releases"]


def test_release_into_main_waits_for_the_rollup_when_main_has_no_rules(tmp_path, capsys):
    early = [c for c in RELEASE_1113 if c["name"] != "gate"]
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=early),
        required={"develop": ["banned-words", "gate"], "main": []},
    )
    assert out["did"] == [] and "not reported yet: gate" in out["lines"][0]


def test_release_into_main_uses_mains_own_rules_once_it_has_some(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=RELEASE_1113),
        required={"main": ["deploy-check"]},
    )
    assert out["did"] == [] and "not reported yet: deploy-check" in out["lines"][0]


def test_not_reported():
    queued = {"name": "gate", "status": "QUEUED"}
    assert rk.not_reported([queued], ["gate"]) == ["gate"]
    assert rk.not_reported([ROLLUP_DONE], ["gate"]) == []
    assert rk.not_reported([{"context": "x", "state": "PENDING"}], ["x"]) == ["x"]
    assert rk.not_reported([{"context": "x", "state": "SUCCESS"}], ["x"]) == []


# ORCH-216 (report r-1117-1032-ws): release 32's note read 'Merge pull request #1147 (#1147); ...' because
# the keeper took GitHub's merge subject; and it asked to deploy a relay the manager had deployed 25
# minutes before.
REAL = [
    {
        "sha": "a" * 40,
        "at": "2026-11-17T00:00:00+00:00",
        "subject": "Merge pull request #1155 from o/feat/copy-doc",
        "title": "Relay admin: Copy Doc for subscribers",
    },
    {
        "sha": "b" * 40,
        "at": "2026-11-17T00:00:00+00:00",
        "subject": "Merge pull request #1156 from o/fix/copy-doc-2",
        "title": "Copy Doc: second fix",
    },
    {
        "sha": "c" * 40,
        "at": "2026-11-17T00:00:00+00:00",
        "subject": "Merge pull request #1147 from o/fix/x",
        "title": "Fix the page height",
    },
    {
        "sha": "e" * 40,
        "at": "2026-11-17T00:00:00+00:00",
        "subject": "Merge pull request #1140 from o/fix/y",
        "title": "",
    },
]
TICKETS = [
    {
        "key": "ORCH-41",
        "title": "Copy Doc for webhook subscribers",
        "status": "done",
        "refs": [
            {"kind": "url", "url": "https://github.com/severinlindenmann/orch/pull/1155"},
            {"kind": "url", "url": "https://github.com/severinlindenmann/orch/pull/1156"},
        ],
    }
]


def test_highlights_name_tickets_and_pr_titles_never_merge_lines():
    own = {
        "sha": "f" * 40,
        "at": "",
        "subject": "Release 31: merge main (ours) - tree equals develop",
        "title": "",
    }
    got = rk.highlights(REAL + [own], TICKETS, "severinlindenmann/orch")
    assert got == [
        "ORCH-41 Copy Doc for webhook subscribers",
        "Fix the page height (#1147)",
        "pull request (#1140)",
    ]
    assert not any("Merge pull request" in x for x in got)


def test_release_body_lists_tickets_and_titles():
    body = rk.release_body(32, DEV, REAL, TICKETS, "severinlindenmann/orch", "ci and e2e")
    assert "- ORCH-41 Copy Doc for webhook subscribers (#1155)" in body
    assert "- Fix the page height (#1147)" in body and "Merge pull request" not in body


def notes(monkeypatch):
    seen = []
    monkeypatch.setattr(
        rk.World, "note", lambda self, tid, text: self.did.append("note:") or seen.append(text)
    )
    return seen


def test_merged_note_has_one_line_per_ticket(tmp_path, capsys, monkeypatch):
    seen = notes(monkeypatch)
    go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card", unreleased=REAL)},
        open_release=None,
        prs=pr("MERGED"),
        tickets=TICKETS,
    )
    assert "Merge pull request" not in seen[0] and "\n- ORCH-41 Copy Doc" in seen[0]


def test_a_long_release_counts_what_does_not_fit():
    items = [f"ORCH-{i} " + "x" * 80 for i in range(40)]
    text = rk.highlight_block(items, 1000)
    assert len(text) <= 1000 and text.endswith("more (see the release)") and text.count("\n- ORCH-") >= 5


def test_relay_already_deployed_asks_no_card(tmp_path, capsys, monkeypatch):
    seen = notes(monkeypatch)
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card", unreleased=REAL)},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/web/portal.html"],
        deployed={"relay": {"sha": "5" * 40, "at": "2026-11-17T10:06:00+00:00", "by": "by hand"}},
        same_tree={"relay": ["5" * 40]},
    )
    assert [d.split(":")[0] for d in out["did"]] == ["update", "note", "rmwt"]
    assert "already runs this release" in seen[0] and "deploy card" not in seen[0]
    assert out["state"].get("deploy") is None


def test_an_older_deploy_still_asks_with_already_deployed_as_an_answer(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card")},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/src/main.rs"],
        deployed={"relay": {"sha": "4" * 40}},
        same_tree={"relay": []},
    )
    assert "deploy-card:relay" in out["did"]
    assert out["state"]["deploy"]["sha"] == DEV


def test_deploy_now_after_a_hand_deploy_opens_no_ticket(tmp_path, capsys):
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay server. Deploy it to production now?",
                "answer": "Deploy now",
                "answered_by": "human:t",
            }
        ]
    }
    out = go(
        tmp_path,
        capsys,
        state={"deploy": {"n": 31, "what": "relay", "sha": DEV}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
        deployed={"relay": {"sha": "5" * 40}},
        same_tree={"relay": ["5" * 40]},
    )
    assert not any(d.startswith("ticket:") for d in out["did"]) and out["state"]["deploy"] is None


def test_already_deployed_answer_writes_the_record(tmp_path, capsys):
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay and publish server. Deploy it to production now?",
                "answer": "Already deployed",
                "answered_by": "human:t",
            }
        ]
    }
    out = go(
        tmp_path,
        capsys,
        state={"deploy": {"n": 31, "what": "relay and publish", "sha": DEV}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
    )
    assert f"deployed:relay and publish {DEV[:8]}" in out["did"] and out["state"]["deploy"] is None


def test_deploy_ticket_says_how_to_write_down_the_deploy(tmp_path, capsys, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        rk.World,
        "new_ticket",
        lambda self, parent, title, note, dw, priority="high", over_limit=False: (
            seen.update(note=note) or "t_sim"
        ),
    )
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay server. Deploy it to production now?",
                "answer": "Deploy now",
                "answered_by": "human:t",
            }
        ]
    }
    go(
        tmp_path,
        capsys,
        state={"deploy": {"n": 31, "what": "relay", "sha": DEV}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
    )
    assert f"orch github release-deployed relay={DEV}" in seen["note"]


def test_deployed_cli_writes_the_record(proj, monkeypatch, run_cli):
    (proj / "clone" / ".git").mkdir(parents=True)
    assert run_cli("config", "set", "github.release_clone", str(proj / "clone"), "--by", "human:t")[0] == 0
    assert run_cli("config", "set", "github.release_servers", "relay,publish", "--by", "human:t")[0] == 0
    sha = "f" * 40
    monkeypatch.setattr(
        rk.World, "_git", lambda self, *a, **k: subprocess.CompletedProcess(a, 0, sha + "\n", "")
    )
    code, out, _ = run_cli("github", "release-deployed", "relay=58e00713", "--by", "human:t")
    assert code == 0 and "relay runs ffffffff" in out
    rec = json.loads((proj / ".orch" / "run" / "release-deployed.json").read_text())
    assert rec["relay"]["sha"] == sha and rec["relay"]["by"] == "human:t"
    assert run_cli("github", "release-deployed", "hub=58e00713")[0] == 2


def test_heads_reads_the_pr_title_from_the_merge_body(monkeypatch, tmp_path):
    w = rk.World(None, cfg(tmp_path))
    log_out = (
        "a" * 40 + "\x1f2026-11-17T00:00:00+00:00\x1fMerge pull request #1155 from o/b\x1fRelay admin: "
        "Copy Doc\n\nmore text\n\x1e\n" + "b" * 40 + "\x1f2026-11-17T00:00:00+00:00\x1fMerge pull request "
        "#1147 from o/c\x1f\x1e\n"
    )
    monkeypatch.setattr(
        w,
        "_run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, log_out if "log" in argv else "s\n", ""),
    )
    monkeypatch.setattr(w, "green_develop", lambda: "s")  # the green commit; its runs are tested above
    rows = w.heads()["unreleased"]
    assert [r["title"] for r in rows] == ["Relay admin: Copy Doc", ""]


# ---- deploy preparation (ORCH-178): fetched and checked before the card; production only on the owner's go
BUILT = {"relay": {"databaseId": 777, "headSha": "b" * 40}}
FETCHED = {"relay": {"path": "/st/relay-r31/orch-relay", "sha256": "a" * 64, "linux": True}}


def test_deploy_card_comes_with_the_prepared_server(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card")},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/src/main.rs"],
        built=BUILT,
        fetched=FETCHED,
        prod_sha={"relay": "c" * 64},
        needs_person={"relay": ["new settings: ORCH_RELAY_X"]},
    )
    assert [d.split(":")[0] for d in out["did"]] == ["update", "fetch", "deploy-card", "note", "rmwt"]
    p = out["state"]["deploy"]["prep"]["relay"]
    assert (
        p["ready"] and p["run"] == 777 and p["sha256"] == "a" * 64 and p["prod"] == "c" * 64 and not p["live"]
    )
    assert rk.prep_line("relay", p) == "The relay server is fetched and checked (new settings: ORCH_RELAY_X)."


def test_production_already_runs_the_built_program_asks_no_card(tmp_path, capsys):
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card")},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/src/main.rs"],
        built=BUILT,
        fetched=FETCHED,
        prod_sha={"relay": "a" * 64},
    )
    assert not any(d.startswith("deploy-card") for d in out["did"])
    assert f"deployed:relay {DEV[:8]}" in out["did"] and out["state"].get("deploy") is None


def test_a_build_not_for_linux_is_not_prepared(tmp_path, capsys):
    bad = {"relay": dict(FETCHED["relay"], linux=False)}
    out = go(
        tmp_path,
        capsys,
        state={"release": gate(phase="card")},
        open_release=None,
        prs=pr("MERGED"),
        changed=["relay/src/main.rs"],
        built=BUILT,
        fetched=bad,
    )
    p = out["state"]["deploy"]["prep"]["relay"]
    assert not p["ready"] and "not for Linux" in p["why"] and "deploy-card:relay" in out["did"]
    assert "not prepared" in rk.prep_line("relay", p)


def test_deploy_go_hands_the_helper_the_prepared_program(tmp_path, capsys, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        rk.World,
        "new_ticket",
        lambda self, parent, title, note, dw, priority="high", over_limit=False: (
            seen.update(note=note) or "t_sim"
        ),
    )
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay server. Deploy it to production now? x",
                "answer": "Deploy now",
                "answered_by": "human:t",
            }
        ]
    }
    prep = {
        "relay": {
            "ready": True,
            "run": 777,
            "path": "/st/relay-r31/orch-relay",
            "sha256": "a" * 64,
            "prod": "c" * 64,
            "needs": ["data changes: 0004_reach.sql"],
        }
    }
    go(
        tmp_path,
        capsys,
        state={"deploy": {"n": 31, "what": "relay", "sha": DEV, "prep": prep}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
    )
    assert "/st/relay-r31/orch-relay" in seen["note"] and "a" * 64 in seen["note"]
    assert (
        "Look at: data changes: 0004_reach.sql" in seen["note"]
        and f"orch github release-deployed relay={DEV}" in seen["note"]
    )


def test_old_stages_are_dropped_newest_two_kept(tmp_path, monkeypatch):
    stage = tmp_path / "release-staged"
    for n in (29, 30, 31, 9):
        (stage / f"relay-r{n}").mkdir(parents=True)
    (stage / "publish-r1").mkdir()
    rk.World(None, cfg(tmp_path)).drop_old_stages("relay")
    assert sorted(d.name for d in stage.iterdir()) == ["publish-r1", "relay-r30", "relay-r31"]


# ---- built into orch (ORCH-225): settings, off, paused, state, hold, CLI


@pytest.fixture
def run_cli(run):
    return run


def test_off_until_role_repo_and_clone_are_set(proj, run_cli, new_ticket):
    assert rk.run(proj)["off"] is True
    code, out, _ = run_cli("github", "release")
    assert code == 0 and "off here" in out and "github.release_keeper" in out
    tid = new_ticket("Release keeper role")
    assert run_cli("config", "set", "github.release_keeper", tid, "--by", "human:t")[0] == 0
    assert run_cli("config", "set", "github.release_repo", "acme/app", "--by", "human:t")[0] == 0
    assert rk.run(proj)["missing"] == ["github.release_clone"]
    assert run_cli("config", "set", "github.release_repo", "not a repo", "--by", "human:t")[0] == 2
    assert run_cli("config", "set", "github.release_keeper", "ORCH-999", "--by", "human:t")[0] == 2
    assert run_cli("config", "set", "github.release_clone", str(proj), "--by", "human:t")[0] == 2  # no .git
    assert (
        run_cli(
            "config", "set", "github.release_workflows", "ci.yml:windows=true,e2e.yml", "--by", "human:t"
        )[0]
        == 0
    )
    assert run_cli("config", "set", "github.release_workflows", "ci.yml;rm", "--by", "human:t")[0] == 2
    assert (
        run_cli("config", "set", "github.release_deploy_host", "ubuntu@10.0.0.1", "--by", "human:t")[0] == 0
    )
    code, out, _ = run_cli("config", "get", "github.release_workflows")
    assert code == 0 and "ci.yml:windows=true,e2e.yml" in out
    assert run_cli("config", "set", "github.release_repo", "off", "--by", "human:t")[0] == 0
    assert rk.get(proj, "github.release_repo") is None


def test_workflows_setting_becomes_dispatch_flags():
    assert rk.workflows("ci.yml:windows=true,e2e.yml") == [
        ("ci.yml", ["-f", "windows=true"]),
        ("e2e.yml", []),
    ]
    assert rk.workflows(None) == [("ci.yml", [])]


@pytest.fixture
def on(proj, run_cli, new_ticket):
    (proj / "clone" / ".git").mkdir(parents=True)
    tid = new_ticket("Release keeper role")
    for k, v in (("keeper", tid), ("repo", "acme/app"), ("clone", str(proj / "clone"))):
        assert run_cli("config", "set", f"github.release_{k}", v, "--by", "human:t")[0] == 0
    return tid


def sim_world(proj, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN3})
    sim.setdefault("last_release", 30)
    return rk.World(proj, rk.Cfg(proj), sim, known=KNOWN)


def test_a_pass_keeps_its_state_in_the_run_folder(proj, on):
    res = rk.run(proj, world=sim_world(proj))
    assert res["did"] == ["dispatch:ci.yml"] and "started ci on" in res["lines"][0]
    st = json.loads((proj / ".orch" / "run" / "release-keeper.json").read_text())
    assert st["release"]["phase"] == "testing" and st["release"]["n"] == 31
    again = rk.run(proj, world=sim_world(proj))  # the next pass reads it: testing, nothing new dispatched
    assert again["did"] == [] and "ci none" in again["lines"][0]


def test_dry_run_writes_no_state(proj, on):
    rk.run(proj, dry_run=True, world=sim_world(proj))
    assert not (proj / ".orch" / "run" / "release-keeper.json").exists()


def test_paused_automation_does_nothing(proj, on, monkeypatch):
    monkeypatch.setattr(brake, "paused", lambda root: {"by": "human:t"})
    assert rk.run(proj, world=sim_world(proj))["paused"] is True


def test_hold_from_the_command_line_stops_cutting(proj, on, run_cli):
    code, out, _ = run_cli("github", "release-hold", "security fix pending", "--by", "human:t")
    assert code == 0 and "security fix pending" in out
    res = rk.run(proj, world=sim_world(proj))
    assert res["did"] == [] and res["lines"] == ["on hold: security fix pending"]
    assert run_cli("github", "release-hold", "off", "--by", "human:t")[0] == 0
    assert rk.run(proj, world=sim_world(proj))["did"] == ["dispatch:ci.yml"]


def test_a_red_run_opens_a_real_top_ticket_under_the_role(proj, on, monkeypatch):
    from orch import runs

    started = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(kw.get("priority")))
    rk.set_hold(proj, "off")
    t0 = rk.now().replace(microsecond=0)
    st = {
        "release": {
            "n": 31,
            "sha": DEV,
            "phase": "testing",
            "dispatched_at": t0.isoformat(),
            "unreleased": UN3,
        }
    }
    (proj / ".orch" / "run").mkdir(parents=True, exist_ok=True)
    (proj / ".orch" / "run" / "release-keeper.json").write_text(json.dumps(st))
    w = sim_world(proj, runs={"ci.yml": [run(DEV, "workflow_dispatch", "failure", at=t0.isoformat())]})
    w.act = lambda what, fn=None: (w.did.append(what), fn() if fn else None)[1]  # writes for real
    res = rk.run(proj, world=w)
    made = [t for t in tickets.list_all(proj) if t["title"].startswith("ci run is red on develop")]
    assert len(made) == 1 and made[0]["parent"] == on and started == ["high"], res


def test_known_red_needs_job_and_ticket():
    assert rk.parse_known(["workspace / test (windows-latest)=ORCH-32"]) == KNOWN
    with pytest.raises(Refused):
        rk.parse_known(["no ticket"])


def test_the_bot_check_refuses_a_write_as_someone_else(tmp_path, monkeypatch):
    w = rk.World(None, cfg(tmp_path, bot="acme-bot"))
    monkeypatch.setattr(w, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "the-owner\n", ""))
    with pytest.raises(Refused, match="does not act as the bot"):
        w.bot_ok()


def test_a_missing_bot_login_file_refuses(tmp_path):
    w = rk.World(None, cfg(tmp_path, env=str(tmp_path / "nope.inc")))
    with pytest.raises(Refused, match="bot login file is missing"):
        w._run(["true"])


def test_linux_x86_64_check():
    elf = b"\x7fELF\x02" + b"\0" * 13 + (0x3E).to_bytes(2, "little")
    assert rk.is_linux_x86_64(elf[:20]) and not rk.is_linux_x86_64(b"\xcf\xfa\xed\xfe" + b"\0" * 16)


def test_needs_lines_name_new_settings_data_and_service_files():
    diff = '+++ b/relay/src/x.rs\n+let a = env("ORCH_RELAY_NEW");\n-let b = env("ORCH_RELAY_OLD");\n'
    names = ["relay/migrations/0004_reach.sql", "relay/deploy/orch-relay.service", "relay/src/x.rs"]
    assert rk.needs_lines("relay", names, diff) == [
        "new settings: ORCH_RELAY_NEW",
        "data changes: 0004_reach.sql",
        "service files: orch-relay.service",
    ]


def test_only_the_asked_question_answered_by_a_person_counts():
    q = {"id": "q7", "text": "Release 31 changed the relay server. Deploy?", "answer": "Deploy now"}
    t = {"questions": [{**q, "answered_by": "agent:claude"}]}
    assert rk.deploy_answer(t, 31, "q7") is None  # an agent's answer never leads to production
    t = {"questions": [{**q, "id": "q8", "answered_by": "human:t"}]}
    assert rk.deploy_answer(t, 31, "q7") is None  # a look-alike question is not the card
    t = {"questions": [{**q, "answered_by": "human:t"}]}
    assert rk.deploy_answer(t, 31, "q7") == "Deploy now"


def test_an_agents_deploy_now_opens_no_ticket(tmp_path):
    t = {
        "questions": [
            {
                "text": "Release 31 changed the relay server. Deploy it to production now?",
                "answer": "Deploy now",
                "answered_by": "agent:codex",
            }
        ]
    }
    out = go(
        tmp_path,
        state={"deploy": {"n": 31, "what": "relay", "sha": DEV}},
        heads={"develop": MAIN, "main": MAIN, "unreleased": []},
        ticket={"ORCH-79": t},
    )
    assert out["did"] == [] and out["state"]["deploy"]["n"] == 31


def test_a_helper_cannot_point_the_keeper_elsewhere(proj, run_cli, monkeypatch):
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    code, _, err = run_cli("config", "set", "github.release_env", "/tmp/x.sh")
    assert code == 2 and "Only a person" in err
    assert run_cli("config", "set", "github.release_env", "off")[0] == 0


def test_a_known_red_job_covers_its_parts():
    # CI splits a test job into parts (ORCH-315): the known-red entry for the whole job covers every part
    known = {"workspace / test (windows-latest)": "ORCH-32"}
    assert (
        rk.known_name("workspace / test (windows-latest, 3/6)", known) == "workspace / test (windows-latest)"
    )
    assert rk.known_name("workspace / test (windows-latest)", known) == "workspace / test (windows-latest)"
    assert rk.known_name("workspace / test (macos-latest, 1/5)", known) is None
    assert rk.known_name("workspace / test (windows-latest-arm, 1/2)", known) is None
    red = {"name": "workspace / test (windows-latest, 2/6)", "status": "COMPLETED", "conclusion": "FAILURE"}
    green = {"name": "workspace / test (ubuntu-latest, 1/2)", "status": "COMPLETED", "conclusion": "SUCCESS"}
    assert rk.checks_green([red, green], frozenset(known)) == "green"
    assert rk.failed_checks([red, green], frozenset(known)) == []
    assert rk.checks_green([red, green]) == "red"


# ---- ORCH-314: develop's push runs are never cancelled; releases are cut only from the last green commit
G1, G2 = "a" * 40, "b" * 40


def world(tmp_path, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN3})
    return rk.World(None, cfg(tmp_path), json.loads(json.dumps(sim)), known=KNOWN)


def test_green_develop_skips_a_newer_red_or_running_commit(tmp_path):
    runs = [
        run(DEV, "push", status="in_progress", conclusion=None, at="2026-11-17T03:00:00Z", rid=3),
        run(G2, "push", conclusion="failure", at="2026-11-17T02:00:00Z", rid=2),
        run(G1, "push", at="2026-11-17T01:00:00Z", rid=1),
    ]
    jobs = {
        "3": [job("workspace / test (macos-latest)", None, "in_progress")],
        "2": [job("workspace / test (macos-latest)", "failure")],
        "1": CI_JOBS,
    }
    assert world(tmp_path, runs={"ci.yml": runs}, jobs=jobs).green_develop() == G1


def test_green_develop_is_none_when_nothing_finished_green(tmp_path):
    runs = [run(G1, "push", conclusion="cancelled", rid=1)]
    assert (
        world(
            tmp_path, runs={"ci.yml": runs}, jobs={"1": [job("mobile / test", "cancelled")]}
        ).green_develop()
        is None
    )


def test_green_develop_ignores_known_red_and_the_rollup(tmp_path):
    runs = [run(G1, "push", conclusion="failure", rid=1)]
    jobs = {"1": [job(WIN_FULL, "failure"), job("gate", "failure"), job("mobile / test")]}
    assert world(tmp_path, runs={"ci.yml": runs}, jobs=jobs).green_develop() == G1


def test_nothing_is_cut_while_no_develop_commit_is_green(tmp_path):
    out = go(tmp_path, heads={"develop": DEV, "green": None, "main": MAIN, "unreleased": []})
    assert out["did"] == [] and "no develop commit is fully green" in out["lines"][0]


def test_a_release_is_cut_from_the_green_commit_not_the_head(tmp_path):
    heads = {"develop": DEV, "green": G1, "main": MAIN, "unreleased": UN3}
    out = go(tmp_path, heads=heads, runs={"ci.yml": [run(G1, "schedule")], "e2e.yml": [run(G1, "schedule")]})
    assert out["state"]["release"]["sha"] == G1 and out["state"]["release"]["phase"] == "gate"
    assert not any(r["sha"] == DEV for r in [out["state"]["release"]])


def test_the_full_signal_is_started_on_the_green_commit(tmp_path):
    out = go(tmp_path, heads={"develop": DEV, "green": G1, "main": MAIN, "unreleased": UN3})
    assert out["state"]["release"]["sha"] == G1 and out["state"]["release"]["phase"] == "testing"


def test_ci_never_cancels_a_develop_push_run():
    import re
    from pathlib import Path

    ci = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
    cancel = re.search(r"cancel-in-progress: (.+)", ci).group(1)
    group = re.search(r"group: (ci-.+)", ci).group(1)
    assert "github.ref != 'refs/heads/develop'" in cancel  # develop pushes are never cancelled ...
    assert "format('develop-{0}', github.sha)" in group  # ... and never replaced by a newer pending run


# macOS and Windows run only on develop, not in the merge queue (ORCH-315): a red develop run opens the
# red-develop ticket by itself, once per commit.
def test_red_develop_push_run_opens_the_red_develop_ticket_once(tmp_path, capsys):
    runs = {"ci.yml": [run(DEV, "push", "failure", rid=7)], "e2e.yml": []}
    jobs = {
        "7": [
            job("workspace / test (macos-latest, 2/5)", "failure"),
            job("workspace / test (ubuntu-latest, 1/2)"),
        ]
    }
    out = go(tmp_path, capsys, runs=runs, jobs=jobs)
    assert "ticket:ci run is red on develop (dddddddd)" in out["did"]
    assert out["state"]["develop_red_sha"] == DEV
    again = go(tmp_path, capsys, state=out["state"], runs=runs, jobs=jobs)
    assert not any(d.startswith("ticket:") for d in again["did"])


def test_red_develop_with_an_open_ticket_makes_no_second(tmp_path, capsys):
    runs = {"ci.yml": [run(DEV, "schedule", "failure")], "e2e.yml": []}
    open_t = [
        {
            "id": "t_1",
            "key": "ORCH-393",
            "status": "open",
            "title": "ci run is red on develop (release 34 blocked)",
        }
    ]
    out = go(tmp_path, capsys, runs=runs, tickets=open_t)
    assert not any(d.startswith("ticket:") for d in out["did"])


def test_a_running_newer_develop_run_is_skipped_and_green_opens_nothing(tmp_path, capsys):
    newer = run("n" * 40, "push", "", status="in_progress", at="2026-11-17T02:00:00Z")
    runs = {"ci.yml": [newer, run(DEV, "push")], "e2e.yml": []}
    out = go(tmp_path, capsys, runs=runs)
    assert not any(d.startswith("ticket:") for d in out["did"])
    assert "develop_red_sha" not in out["state"]


def test_known_red_windows_on_develop_opens_nothing(tmp_path, capsys):
    runs = {"ci.yml": [run(DEV, "push", "failure", rid=8)], "e2e.yml": []}
    jobs = {
        "8": [
            job("workspace / test (windows-latest, 3/10)", "failure"),
            job("workspace / test (macos-latest, 1/5)"),
        ]
    }
    out = go(tmp_path, capsys, runs=runs, jobs=jobs)
    assert not any(d.startswith("ticket:") for d in out["did"])


def test_the_limit_setting_is_set_by_a_person_only(proj, run_cli):
    key = "github.security_reviews_per_day"
    assert run_cli("config", "set", key, "30", "--by", "agent:claude")[0] == 2
    assert run_cli("config", "set", key, "lots", "--by", "human:t")[0] == 2
    assert run_cli("config", "set", key, "30", "--by", "human:t")[0] == 0
    assert rk.Cfg(proj).security_limit == "30" and rk.secreview.limit(rk.Cfg(proj).security_limit) == 30
    code, out, _ = run_cli("config", "get", key)
    assert code == 0 and "30" in out


# ---- release proof (ORCH-456): a red check needs a named, recorded exception; every release runs its walks

WALKS = "install=release-walk,services,clickthrough"
MAC = "workspace / test (macos-latest)"
EXC = {MAC: {"ticket": "ORCH-454", "until": "2099-01-01", "why": "tmux missing on the runner"}}


def go_walks(tmp_path, walks=WALKS, **sim):
    sim.setdefault("heads", {"develop": DEV, "main": MAIN, "unreleased": UN3})
    sim.setdefault("last_release", 30)
    st = json.loads(json.dumps(sim.pop("state", {})))
    w = rk.World(None, cfg(tmp_path, walks=walks), json.loads(json.dumps(sim)), known=KNOWN)
    lines = rk.pass_once(w, st, "ORCH-79", None)
    return json.loads(json.dumps({"state": st, "did": w.did, "lines": lines}, default=str))


def red_mac():
    return [
        {"name": "workspace / test (ubuntu-latest)", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": MAC, "status": "COMPLETED", "conclusion": "FAILURE"},
        {"name": "gate", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]


def test_a_red_check_with_a_recorded_exception_gets_the_card_and_is_named(tmp_path, capsys):
    out = go(
        tmp_path,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=red_mac()),
        exceptions=EXC,
    )
    assert out["did"] == ["card:release 31", "tend-releases"]
    assert out["state"]["release"]["known_red"] == [f"{MAC} (ORCH-454, until 2099-01-01)"]


def test_a_red_check_without_an_exception_gets_no_card_and_says_how_to_record_one(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        rk.World,
        "new_ticket",
        lambda self, parent, title, note, dw, priority="high", over_limit=False: (
            seen.update(title=title, note=note) or "t_sim"
        ),
    )
    out = go(tmp_path, state={"release": gate()}, open_release={"number": 9031}, prs=pr(checks=red_mac()))
    assert "card:release 31" not in out["did"]
    assert seen["title"].startswith("Release 31 checks are red") and "release-exception" in seen["note"]


def test_an_expired_exception_no_longer_lets_the_check_through(tmp_path):
    old = {MAC: {**EXC[MAC], "until": "2020-01-01"}}
    out = go(
        tmp_path,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=red_mac()),
        exceptions=old,
    )
    assert out["did"] == [f"ticket:Release 31 checks are red: {MAC}"]


def test_an_exception_ends_when_its_ticket_is_done(tmp_path):
    done = [{"id": "t_454", "key": "ORCH-454", "status": "done", "title": "tmux on macOS runners"}]
    out = go(
        tmp_path,
        state={"release": gate()},
        open_release={"number": 9031},
        prs=pr(checks=red_mac()),
        exceptions=EXC,
        tickets=done,
    )
    assert out["did"] == [f"ticket:Release 31 checks are red: {MAC}"]


def test_a_cut_release_starts_every_walk_and_waits_for_them(tmp_path):
    out = go_walks(
        tmp_path,
        state={"release": gate(url="https://github.com/x/y/pull/9031")},
        open_release={"number": 9031},
        prs=pr(),
    )
    assert out["did"] == [
        "ticket:Release 31: install walk",
        "ticket:Release 31: services walk",
        "ticket:Release 31: clickthrough walk",
    ]
    assert set(out["state"]["release"]["walks"]) == {"install", "services", "clickthrough"}
    assert "waits for the walks" in out["lines"][-1] and out["state"]["release"]["phase"] == "gate"
    again = go_walks(tmp_path, state=out["state"], open_release={"number": 9031}, prs=pr())
    assert again["did"] == []  # no second ticket per walk


def started(at="2026-11-18T10:00:00+00:00"):
    return {
        k: {"ticket": f"ORCH-{i}", "at": at} for i, k in enumerate(("install", "services", "clickthrough"), 1)
    }


def result(verdict="pass", commit=DEV[:12], line="walked it"):
    return {
        "verdict": verdict,
        "line": line,
        "commit": commit,
        "at": "2026-11-18T11:00:00+00:00",
        "by": "agent:x",
    }


def test_every_walk_passed_puts_the_card(tmp_path):
    res = {"31": {k: result() for k in ("install", "services", "clickthrough")}}
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release={"number": 9031},
        prs=pr(),
        walk_results=res,
    )
    assert out["did"] == ["card:release 31", "tend-releases"]


def test_one_walk_missing_still_waits(tmp_path):
    res = {"31": {k: result() for k in ("install", "services")}}
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release={"number": 9031},
        prs=pr(),
        walk_results=res,
    )
    assert out["did"] == [] and "clickthrough (ORCH-3)" in out["lines"][-1]


def test_a_result_from_an_earlier_cut_does_not_count(tmp_path):
    res = {"31": {k: result(commit="e" * 12) for k in ("install", "services", "clickthrough")}}
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release={"number": 9031},
        prs=pr(),
        walk_results=res,
    )
    assert out["did"] == [] and "waits for the walks" in out["lines"][-1]


def test_a_failed_walk_opens_one_red_ticket(tmp_path):
    res = {"31": {"install": result("fail", line="Factory refuses every order"), "services": result()}}
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release={"number": 9031},
        prs=pr(),
        walk_results=res,
    )
    assert out["did"] == ["ticket:Release 31 walks failed: install (ORCH-1): Factory refuses every order"]


def test_a_walk_ticket_finished_without_a_result_says_how_to_record_it(tmp_path):
    rows = [{"id": "t_3", "key": "ORCH-3", "status": "done", "title": "Release 31: clickthrough walk"}]
    res = {"31": {k: result() for k in ("install", "services")}}
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release={"number": 9031},
        prs=pr(),
        walk_results=res,
        tickets=rows,
    )
    assert (
        "finished without a result" in out["lines"][-1] and "release-walk 31 clickthrough" in out["lines"][-1]
    )


def test_a_release_merged_red_before_its_card_is_noted_as_without_proof(tmp_path):
    out = go_walks(
        tmp_path,
        state={"release": gate(walks=started())},
        open_release=None,
        prs=pr("MERGED", checks=red_mac()),
    )
    note = next(d for d in out["did"] if d.startswith("note:"))
    assert "reached main without" in note
    assert (
        "WITHOUT PROOF" in out["lines"][-1]
        and MAC in out["lines"][-1]
        and "walks without a pass" in out["lines"][-1]
    )


def test_a_release_merged_from_its_card_has_no_proof_line(tmp_path):
    out = go_walks(
        tmp_path, state={"release": gate(phase="card", walks=started())}, open_release=None, prs=pr("MERGED")
    )
    assert "WITHOUT PROOF" not in out["lines"][-1]


def test_exception_command_is_a_persons_and_dated(proj, run_cli, new_ticket, monkeypatch):
    tid = new_ticket("macOS runners lack tmux")
    code, out, _ = run_cli("github", "release-exception")
    assert code == 0 and "No exception recorded" in out
    args = ("github", "release-exception", MAC, "--ticket", tid, "--until", "2099-01-01")
    assert run_cli(*args, "--by", "agent:claude")[0] == 2
    assert run_cli("github", "release-exception", MAC, "--ticket", tid, "--by", "human:t")[0] == 2  # no date
    assert (
        run_cli(
            "github", "release-exception", MAC, "--ticket", tid, "--until", "2020-01-01", "--by", "human:t"
        )[0]
        == 2
    )
    code, out, _ = run_cli(*args, "--why", "tmux missing", "--by", "human:t")
    assert code == 0 and "until 2099-01-01" in out
    saved = json.loads((proj / ".orch" / "run" / "release-exceptions.json").read_text())
    assert saved[MAC]["until"] == "2099-01-01" and saved[MAC]["by"] == "human:t"
    code, out, _ = run_cli("github", "release-exception")
    assert MAC in out and "tmux missing" in out
    assert run_cli("github", "release-exception", MAC, "--ticket", "off", "--by", "human:t")[0] == 0
    assert rk.list_exceptions(proj) == {}


def test_walk_command_records_only_a_named_walk(proj, run_cli):
    assert (
        run_cli("config", "set", "github.release_walks", "install=release-walk;rm", "--by", "human:t")[0] == 2
    )
    assert run_cli("config", "set", "github.release_walks", WALKS, "--by", "human:t")[0] == 0
    assert run_cli("config", "set", "github.release_walks", WALKS, "--by", "agent:claude")[0] == 2
    assert run_cli("github", "release-walk", "31", "nope", "pass", "x", "--commit", DEV[:12])[0] == 2
    assert run_cli("github", "release-walk", "31", "services", "pass", "x", "--commit", "nope")[0] == 2
    code, out, _ = run_cli(
        "github",
        "release-walk",
        "31",
        "services",
        "fail",
        "watcher left",
        "--commit",
        DEV[:12],
        "--by",
        "agent:x",
    )
    assert code == 0 and "FAILED" in out
    saved = json.loads((proj / ".orch" / "run" / "release-walks.json").read_text())
    assert saved["31"]["services"]["verdict"] == "fail" and saved["31"]["services"]["commit"] == DEV[:12]
    assert rk.walks(WALKS) == [("install", "release-walk"), ("services", None), ("clickthrough", None)]


def test_walks_start_at_the_cut_with_the_commit_in_the_note(tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(
        rk.World,
        "new_ticket",
        lambda self, parent, title, note, dw, priority="high", over_limit=False: (
            notes.append((title, note)) or "t_sim"
        ),
    )
    out = go_walks(
        tmp_path,
        state={"release": in_testing()},
        runs={"ci.yml": [run(DEV, "workflow_dispatch")], "e2e.yml": [run(DEV, "workflow_dispatch")]},
    )
    assert out["state"]["release"]["phase"] == "gate" and len(out["state"]["release"]["walks"]) == 3
    assert [t for t, _ in notes] == [f"Release 31: {k} walk" for k in ("install", "services", "clickthrough")]
    assert f"--commit {DEV[:12]}" in notes[0][1] and "Use the skill release-walk." in notes[0][1]


# ---- a refused cut: the line it stopped at, one card, nothing left behind (ORCH-1000)


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def real_clone(tmp_path, monkeypatch):
    for k, v in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(k, v)
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    _git("init", "-q", "--bare", "-b", "main", str(origin))
    _git("clone", "-q", str(origin), str(clone))
    (clone / "a.txt").write_text("a\n")
    _git("add", "a.txt", cwd=clone)
    _git("commit", "-q", "-m", "first", cwd=clone)
    _git("push", "-q", "origin", "HEAD:main", cwd=clone)
    (clone / "a.txt").write_text("b\n")
    _git("commit", "-q", "-am", "work", cwd=clone)
    _git("push", "-q", "origin", "HEAD:develop", cwd=clone)
    _git("fetch", "-q", "origin", cwd=clone)
    sha = _git("rev-parse", "origin/develop", cwd=clone)
    c = cfg(tmp_path, clone=str(clone), worktrees=str(tmp_path / "wts"), repo="o/r")
    w = rk.World(None, c)
    monkeypatch.setattr(rk.World, "bot_ok", lambda self: None)
    return w, clone, sha, tmp_path / "wts" / "release-35"


def test_a_cut_stopped_by_the_secret_check_names_the_line_masked_and_leaves_nothing(real_clone):
    w, clone, sha, wt = real_clone
    body = (
        "Release 35\n\nWhat goes to main:\n- ORCH-447 a test count before pass: is no password label (#1481)"
    )
    with pytest.raises(Refused) as e:
        w.cut(35, sha, body)
    msg = str(e.value)
    assert msg.startswith("line 4 of the release text looks like it holds a password or secret value: ")
    assert "ORCH-447" in msg and "is no password" not in msg  # the value is hidden, the ticket shows
    assert w.secret_hit["line"] == 4
    assert not wt.exists()
    assert _git("branch", "--list", "release/*", cwd=clone) == ""
    assert "release/" not in _git("ls-remote", "--heads", "origin", cwd=clone)
    with pytest.raises(Refused) as again:  # the next pass shows the same real cause, not "exists already"
        w.cut(35, sha, body)
    assert "exists already" not in str(again.value) and "line 4" in str(again.value)


def test_a_cut_refused_after_its_push_removes_the_pushed_branch_too(real_clone, monkeypatch):
    w, clone, sha, wt = real_clone
    real_run = rk.World._run

    def fake(self, argv, cwd=None, timeout=120):
        if argv[:3] == [self.gh, "pr", "create"]:
            return subprocess.CompletedProcess(argv, 1, "", "GraphQL: no")
        return real_run(self, argv, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(rk.World, "_run", fake)
    with pytest.raises(Refused, match="pr create"):
        w.cut(35, sha, "Release 35\n- plain work (#1)")
    assert not wt.exists()
    assert _git("branch", "--list", "release/*", cwd=clone) == ""
    assert "release/" not in _git("ls-remote", "--heads", "origin", cwd=clone)


def test_a_leftover_folder_is_not_removed_by_the_cut(real_clone):
    w, clone, sha, wt = real_clone
    wt.mkdir(parents=True)
    (wt / "keep.txt").write_text("someone's\n")
    with pytest.raises(Refused, match="exists already"):
        w.cut(35, sha, "Release 35")
    assert (wt / "keep.txt").exists()


def test_a_secret_stop_puts_one_card_per_line_on_the_role_ticket(tmp_path, monkeypatch):
    w = rk.World(None, cfg(tmp_path))
    asked = []
    hit = {
        "line": 4,
        "kind": "secret-value",
        "words": "a password or secret value",
        "shown": "- ORCH-447 x [hidden]",
    }

    def cut(self, n, sha, body):
        self.secret_hit = dict(hit)
        raise Refused("line 4 of the release text looks like it holds a password or secret value: x")

    monkeypatch.setattr(rk.World, "cut", cut)
    monkeypatch.setattr(rk.World, "tickets", lambda self: [])
    monkeypatch.setattr(
        rk.World, "ask", lambda self, args: asked.append(args) or subprocess.CompletedProcess(args, 0, "", "")
    )
    st = {"release": {"n": 35, "sha": DEV, "unreleased": [], "phase": "cut"}}
    first = rk.cut_now(w, st, {"main": MAIN}, "ORCH-79")
    again = rk.cut_now(w, st, {"main": MAIN}, "ORCH-79")
    assert len(asked) == 1 and asked[0][0] == "ORCH-79"
    assert "line 4" in asked[0][1] and "- ORCH-447 x [hidden]" in asked[0][1]
    assert "card on the role ticket" in first[-1] and len(again) == 1
    st["release"]["secret_card"] = None
    rk.cut_now(w, st, {"main": MAIN}, None)  # no role (a dry look): no card
    assert len(asked) == 1


def test_a_line_that_also_holds_a_stored_key_shows_no_text(monkeypatch):
    from orch import secretscan

    monkeypatch.setattr(
        secretscan,
        "find",
        lambda text, root=None: [{"kind": "secret-value", "line": 2}, {"kind": "stored-key", "line": 2}],
    )
    got = rk.secret_lines("Release 35\n- pass: hunter2hunter2", None)
    assert [g["shown"] for g in got] == ["(not shown)", "(not shown)"]


def test_a_branch_already_on_github_is_never_deleted_by_a_refused_cut(real_clone, monkeypatch):
    w, clone, sha, wt = real_clone
    br = f"release/part35-{rk.now().astimezone().strftime('%m%d')}"
    _git("push", "-q", "origin", f"{sha}:refs/heads/{br}", cwd=clone)
    with pytest.raises(Refused, match="on GitHub already"):
        w.cut(35, sha, "Release 35\n- plain work (#1)")
    assert br in _git("ls-remote", "--heads", "origin", cwd=clone)
    assert not wt.exists() and _git("branch", "--list", "release/*", cwd=clone) == ""


def test_a_worktree_git_made_before_failing_is_removed(real_clone):
    w, clone, sha, wt = real_clone
    hook = clone / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(Refused, match="git worktree"):
        w.cut(35, sha, "Release 35")
    assert not wt.exists() and _git("branch", "--list", "release/*", cwd=clone) == ""


def test_a_local_branch_that_was_there_before_is_kept(real_clone):
    w, clone, sha, wt = real_clone
    br = f"release/part35-{rk.now().astimezone().strftime('%m%d')}"
    _git("branch", br, sha, cwd=clone)
    with pytest.raises(Refused, match="git worktree"):
        w.cut(35, sha, "Release 35")
    assert br in _git("branch", "--list", "release/*", cwd=clone)
