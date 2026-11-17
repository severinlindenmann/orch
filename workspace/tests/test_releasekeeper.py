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


def test_the_pace_counts_from_the_last_try(tmp_path, capsys):
    out = go(tmp_path, capsys, state={"last_cut_at": rk.now().isoformat()})
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
    assert out["did"] == ["ticket:Release 31 gate is red: macos"]


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
        lambda self, parent, title, note, dw, priority="high": seen.update(note=note) or "t_sim",
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
        lambda self, parent, title, note, dw, priority="high": seen.update(note=note) or "t_sim",
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
    assert rk.deploy_answer(t, 31, "q7", proven=lambda tk, qq: False) is None  # a synced answer


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
