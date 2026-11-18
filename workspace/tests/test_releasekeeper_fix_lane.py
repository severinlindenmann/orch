"""The fix lane of the release keeper (ORCH-552): a merged pull request labelled "fix for release N", N the
newest release, ships at once as N.1 from main with only that change; no pace, no other work, no walks."""

import subprocess

import pytest
from test_releasekeeper import DEV, MAIN, ROLLUP_DONE, cfg, go

from orch import releasekeeper as rk

FIX = {"number": 50, "release": 30, "sha": "5" * 40, "title": "Factory takes orders again",
       "url": "https://github.com/x/y/pull/50"}  # fmt: skip


@pytest.mark.parametrize(
    ("labels", "want"),
    [
        ([{"name": "fix for release 33"}], 33),
        ([{"name": "Fix-for-release-7"}, {"name": "urgent"}], 7),
        (["fix for release 12"], 12),
        ([{"name": "fix for release"}], None),
        ([{"name": "fix for release 0"}], None),
        ([{"name": "urgent"}], None),
        (None, None),
    ],
)
def test_the_label_names_the_release(labels, want):
    assert rk.fix_target(labels) == want


def test_a_fix_ships_at_once_as_n_point_1_without_the_pace(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat(), fixes=[FIX])
    assert out["did"] == ["cut:release 30.1 with #50"]
    rel = out["state"]["release"]
    assert rel["n"] == "30.1" and rel["fix"] == 50 and rel["phase"] == "gate" and rel["unreleased"] == []
    assert out["state"]["fixes_shipped"] == [50]
    assert "fix release 30.1: cut with only #50" in out["lines"][-1]


def test_a_shipped_fix_is_not_cut_again(tmp_path, capsys):
    out = go(
        tmp_path, capsys, last_release_at=rk.now().isoformat(), fixes=[FIX], state={"fixes_shipped": [50]}
    )
    assert out["did"] == []


def test_the_second_fix_of_a_release_is_n_point_2(tmp_path, capsys):
    out = go(tmp_path, capsys, fixes=[FIX], fix_count={"30": 1})
    assert out["state"]["release"]["n"] == "30.2"


def test_a_fix_for_an_older_release_waits_for_the_next_release(tmp_path, capsys):
    out = go(tmp_path, capsys, last_release_at=rk.now().isoformat(), fixes=[dict(FIX, release=29)])
    assert out["did"] == [] and "ships with the next release" in out["lines"][0]
    assert out["state"]["fixes_shipped"] == [50]


def test_a_fix_goes_before_a_release_in_testing(tmp_path, capsys):
    testing = {
        "n": 31,
        "sha": DEV,
        "phase": "testing",
        "dispatched_at": rk.now().isoformat(),
        "unreleased": [],
    }
    out = go(tmp_path, capsys, fixes=[FIX], state={"release": testing})
    assert out["did"] == ["cut:release 30.1 with #50"] and out["state"]["release"]["n"] == "30.1"
    assert any("testing stopped for fix release 30.1" in x for x in out["lines"])


def test_a_fix_waits_while_a_release_pull_request_is_open(tmp_path, capsys):
    gate = {"n": 31, "sha": DEV, "phase": "gate", "pr": 9031, "wt": "/x", "main_before": MAIN}
    prs = {
        "9031": {
            "url": "u",
            "state": "OPEN",
            "statusCheckRollup": [{"name": "t", "status": "IN_PROGRESS"}, ROLLUP_DONE],
        }
    }
    out = go(tmp_path, capsys, fixes=[FIX], state={"release": gate}, open_release={"number": 9031}, prs=prs)
    assert out["state"]["release"]["n"] == 31 and "cut:release 30.1 with #50" not in out["did"]


def test_hold_stops_the_fix_lane_too(tmp_path, capsys):
    out = go(tmp_path, capsys, fixes=[FIX], hold="security fix pending")
    assert out["did"] == [] and "on hold" in out["lines"][0]


def test_a_fix_release_gate_has_no_walks_and_gets_the_merge_card(tmp_path, capsys):
    rel = {"n": "30.1", "fix": 50, "sha": "f" * 40, "phase": "gate", "pr": 9550, "wt": "/x"}
    rel.update(main_before=MAIN, unreleased=[])
    green = [{"name": "t", "status": "COMPLETED", "conclusion": "SUCCESS"}, ROLLUP_DONE]
    prs = {"9550": {"url": "https://github.com/x/y/pull/9550", "state": "OPEN", "statusCheckRollup": green}}
    sim = {"heads": {"develop": DEV, "main": MAIN, "unreleased": []}, "last_release": 30}
    sim.update(open_release={"number": 9550}, prs=prs)
    w = rk.World(None, cfg(tmp_path, walks="release-walk"), sim)
    st = {"release": rel}
    lines = rk.pass_once(w, st, "ORCH-79", None)
    assert "card:release 30.1" in w.did and not any("walk" in x for x in lines)


def test_a_fix_release_is_never_cut_again_from_develop(tmp_path):
    w = rk.World(None, cfg(tmp_path), {"tickets": []})
    assert rk.recut(w, {}, {"n": "30.1", "fix": 50, "sha": "f" * 40}, {"green": DEV}, "checks") is False


# ---- the cut itself, with real git: main plus only the fix -------------------------------------------------


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_cut_fix_takes_only_the_fix_onto_main(tmp_path):
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    for k, v in {"user.email": "t@example.invalid", "user.name": "t", "commit.gpgsign": "false"}.items():
        _git(clone, "config", k, v)
    (clone / "app.txt").write_text("release 30\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "release 30")
    _git(clone, "push", "-q", "origin", "main")
    _git(clone, "checkout", "-q", "-b", "develop")
    (clone / "other.txt").write_text("unreleased work\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "other work")
    _git(clone, "checkout", "-q", "-b", "fix")
    (clone / "app.txt").write_text("release 30, fixed\n")
    _git(clone, "commit", "-qam", "the fix")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", "fix", "-m", "Merge pull request #50 from x/fix")
    merge = _git(clone, "rev-parse", "HEAD")
    _git(clone, "push", "-q", "origin", "develop")
    _git(clone, "fetch", "-q", "origin")
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\necho https://github.com/x/y/pull/77\n")
    gh.chmod(0o755)
    w = rk.World(None, cfg(tmp_path, clone=str(clone), bot=None), None)
    w.gh = str(gh)
    got = w.cut_fix(30, 1, dict(FIX, sha=merge), "Fix release 30.1")
    assert got["number"] == 77 and got["branch"].startswith("release/part30.1-")
    wt = got["wt"]
    assert (tmp_path / "clone").exists() and _git(wt, "show", "HEAD:app.txt") == "release 30, fixed"
    assert (
        subprocess.run(["git", "cat-file", "-e", "HEAD:other.txt"], cwd=wt, capture_output=True).returncode
        != 0
    )
    assert _git(wt, "rev-parse", "HEAD~1") == _git(wt, "rev-parse", "origin/main") and got["sha"] == _git(
        wt, "rev-parse", "HEAD"
    )
    assert _git(origin, "rev-parse", got["branch"]) == got["sha"]  # pushed


def test_a_fix_waits_for_its_own_security_ok(tmp_path, monkeypatch):
    w = rk.World(None, cfg(tmp_path), {"fixes": [FIX], "last_release": 30})
    st = {}
    lines = rk.fix_lane(
        w, st, None, ["#50 (security review not started yet)", "#7 (security review running)"]
    )
    assert w.did == [] and "waits for its security OK: #50 (security review not started yet)" in lines[-1]
    assert st.get("fixes_shipped") == []  # not marked shipped: it is cut once the OK is there
    lines = rk.fix_lane(w, st, None, ["#7 (security review running)"])  # another pull request's hold
    assert w.did == ["cut:release 30.1 with #50"]


def test_the_pass_hands_the_security_holds_to_the_fix_lane(tmp_path, monkeypatch):
    from orch import secreview

    monkeypatch.setattr(secreview, "tend", lambda w, st, role: ([], ["#50 (security review found problems)"]))
    out = go(tmp_path, fixes=[FIX])
    assert out["did"] == [] and any("waits for its security OK" in x for x in out["lines"])
