"""The fix lane of the release keeper (ORCH-552): a merged pull request labelled "fix for release N", N the
newest release, ships at once as N.1 from main with only that change; no pace, no other work, no walks."""

import os
import subprocess

import pytest
from test_releasekeeper import DEV, MAIN, ROLLUP_DONE, cfg, go, run

from orch import releasekeeper as rk


def cut_release(tmp_path) -> dict:
    """A normal release 31 just cut (pull request open, checks next), as the keeper itself leaves it."""
    green = {"ci.yml": [run(DEV, "schedule")], "e2e.yml": [run(DEV, "schedule")]}
    return go(tmp_path / "normal", runs=green)["state"]["release"]


FIX = {"number": 50, "release": 30, "sha": "5" * 40, "head": "6" * 40, "files": [],
       "title": "Factory takes orders again", "url": "https://github.com/x/y/pull/50"}  # fmt: skip


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
    assert rel["n"] == "30.1" and rel["fix"] == 50 and rel["unreleased"] == []
    assert rel["phase"] == cut_release(tmp_path)["phase"]  # right where a normal release is after its cut
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
    normal = cut_release(tmp_path)
    prs = {
        "9031": {
            "url": "u",
            "state": "OPEN",
            "statusCheckRollup": [{"name": "t", "status": "IN_PROGRESS"}, ROLLUP_DONE],
        }
    }
    out = go(tmp_path, capsys, fixes=[FIX], state={"release": normal}, open_release={"number": 9031}, prs=prs)
    assert out["state"]["release"]["n"] == 31 and "cut:release 30.1 with #50" not in out["did"]


def test_hold_stops_the_fix_lane_too(tmp_path, capsys):
    out = go(tmp_path, capsys, fixes=[FIX], hold="security fix pending")
    assert out["did"] == [] and "on hold" in out["lines"][0]


def test_a_fix_release_has_no_walks_and_gets_the_merge_card(tmp_path, capsys):
    rel = go(tmp_path / "cut", fixes=[FIX])["state"]["release"]  # as the fix lane leaves it
    assert rel["pr"] == 9550
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


def _fake_gh(tmp_path):
    """A `gh` that prints a pull request link; a .cmd on Windows, which cannot start a #!/bin/sh file."""
    if os.name == "nt":
        gh = tmp_path / "gh.cmd"
        gh.write_text("@echo off\r\necho https://github.com/x/y/pull/77\r\n")
    else:
        gh = tmp_path / "gh"
        gh.write_text("#!/bin/sh\necho https://github.com/x/y/pull/77\n")
        gh.chmod(0o755)
    return gh


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
    gh = _fake_gh(tmp_path)
    w = rk.World(None, cfg(tmp_path, clone=str(clone), bot=None), None)
    w.gh = str(gh)
    got = w.cut_fix(30, 1, dict(FIX, sha=merge, head=_git(clone, "rev-parse", "fix")), "Fix release 30.1")
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


@pytest.mark.parametrize(
    ("hold", "blocks"),
    [
        ("#50 (security review running)", True),
        ("#7 (security review running)", False),
        ("5555555 (changes relay/ but no pull request with its merged commit was found)", True),
        ("abcdef12 (changes relay/ but no pull request with its merged commit was found)", False),
        ("6666666 (its merge line does not match pull request #9 on GitHub)", True),  # the fix's own head
        ("the security check could not run", True),
        ("#50x odd", True),
    ],
)
def test_unknown_security_holds_hold_the_fix_too(hold, blocks):
    assert rk._other_change(hold, FIX) is not blocks


# ---- a fix merged inside a merge-queue group (ORCH-786) ----------------------------------------------------


def _repo(tmp_path):
    """origin + clone with main at release 30 and develop one unreleased change ahead."""
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
    return origin, clone


def _commit(clone, branch, start, name, text):
    _git(clone, "checkout", "-q", "-B", branch, start)
    (clone / name).write_text(text)
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", f"{branch}: {name}")
    return _git(clone, "rev-parse", "HEAD")


def _keeper(tmp_path, clone):
    gh = _fake_gh(tmp_path)
    w = rk.World(None, cfg(tmp_path, clone=str(clone), bot=None), None)
    w.gh = str(gh)
    return w


def _files(wt):
    return set(_git(wt, "ls-tree", "-r", "--name-only", "HEAD").split())


def test_a_fix_merged_inside_a_queue_group_ships_without_the_group(tmp_path):
    """The queue built a group branch from develop, took in #49 (unreviewed, relay/ change) and the fix #50,
    and merged the group pull request into develop. GitHub names the group's merge commit as the fix's merge
    commit: the fix release must hold only #50's change, never #49's."""
    origin, clone = _repo(tmp_path)
    other = _commit(clone, "pr49", "develop", "relay.txt", "unreviewed relay change\n")
    fix = _commit(clone, "pr50", "develop", "app.txt", "release 30, fixed\n")
    _git(clone, "checkout", "-q", "-B", "orch-queue/develop-1", "develop")
    _git(clone, "merge", "-q", "--no-ff", other, "-m", "Merge queue: take in #49")
    _git(clone, "merge", "-q", "--no-ff", fix, "-m", "Merge queue: take in #50")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", "orch-queue/develop-1", "-m", "Merge pull request #51 from x/queue")
    group = _git(clone, "rev-parse", "HEAD")
    _git(clone, "push", "-q", "origin", "develop")
    _git(clone, "fetch", "-q", "origin")
    w = _keeper(tmp_path, clone)
    got = w.cut_fix(30, 1, dict(FIX, sha=group, head=fix), "Fix release 30.1")
    wt = got["wt"]
    assert _git(wt, "show", "HEAD:app.txt") == "release 30, fixed"
    assert _files(wt) == {"app.txt"}  # neither #49's relay.txt nor develop's other.txt
    assert _git(wt, "rev-parse", "HEAD~1") == _git(wt, "rev-parse", "origin/main")
    assert _git(origin, "rev-parse", got["branch"]) == got["sha"]


def test_a_fix_branch_that_took_develop_in_ships_only_its_own_change(tmp_path):
    origin, clone = _repo(tmp_path)
    _commit(clone, "fixb", "develop", "app.txt", "release 30, fixed\n")
    later = _commit(clone, "develop", "develop", "later.txt", "merged later into develop\n")
    _git(clone, "checkout", "-q", "fixb")
    _git(clone, "merge", "-q", "--no-ff", later, "-m", "Merge origin/develop into fixb")
    head = _git(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", head, "-m", "Merge pull request #50 from x/fixb")
    merge = _git(clone, "rev-parse", "HEAD")
    _git(clone, "push", "-q", "origin", "develop")
    _git(clone, "fetch", "-q", "origin")
    got = _keeper(tmp_path, clone).cut_fix(30, 1, dict(FIX, sha=merge, head=head), "Fix release 30.1")
    assert _files(got["wt"]) == {"app.txt"}


def test_a_fix_whose_head_is_not_in_the_merged_commit_is_refused(tmp_path):
    origin, clone = _repo(tmp_path)
    head = _commit(clone, "pr50", "develop", "app.txt", "release 30, fixed\n")
    other = _commit(clone, "pr49", "develop", "relay.txt", "someone else's change\n")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", other, "-m", "Merge pull request #49 from x/pr49")
    stray = _git(clone, "rev-parse", "HEAD")  # a merge commit that does not hold the fix's head
    _git(clone, "push", "-q", "origin", "develop")
    _git(clone, "fetch", "-q", "origin")
    w = _keeper(tmp_path, clone)
    with pytest.raises(rk.Refused, match="cannot be told apart"):
        w.cut_fix(30, 1, dict(FIX, sha=stray, head=head), "Fix release 30.1")
    with pytest.raises(rk.Refused, match="no known merged commit"):
        w.cut_fix(30, 2, dict(FIX, sha=stray, head=""), "Fix release 30.2")


def _sec(tmp_path, entry=None, verdict=None, files=("relay/src/main.rs",)):
    sim = {"fixes": [dict(FIX, files=[{"path": f} for f in files])], "last_release": 30}
    if verdict:
        sim["security_verdicts"] = {"50": verdict}
    w = rk.World(None, cfg(tmp_path), sim)
    st = {"security": {"prs": {"50": entry}}} if entry else {}
    return w, st


@pytest.mark.parametrize(
    ("entry", "verdict", "files", "holds", "starts"),
    [
        (None, None, ("docs/a.md",), None, False),  # touches no watched path: no review needed
        (None, None, ("relay/src/main.rs",), "#50 (security review has no OK yet)", True),
        ({"sha": "7" * 40}, {"sha": "7" * 40, "verdict": "ok"}, ("relay/src/main.rs",),
         "#50 (security review has no OK yet)", True),  # an OK for an earlier head does not count
        ({"sha": "6" * 40}, None, ("relay/src/main.rs",), "#50 (security review has no OK yet)", False),
        ({"sha": "6" * 40}, {"sha": "6" * 40, "verdict": "problems"}, ("relay/src/main.rs",),
         "#50 (security review found problems)", False),
        ({"sha": "6" * 40}, {"sha": "6" * 40, "verdict": "ok"}, ("relay/src/main.rs",), None, False),
    ],
)  # fmt: skip
def test_a_fix_from_a_group_needs_its_own_security_ok(tmp_path, entry, verdict, files, holds, starts):
    w, st = _sec(tmp_path, entry, verdict, files)
    # the release's list only names the group pull request #51; it does not ship, so it is not the fix's hold
    lines = rk.fix_lane(w, st, None, ["#51 (security review running)"])
    assert ("security-review:#50" in w.did) is starts  # a missing review of its merged head is started
    if holds:
        assert "cut:release 30.1 with #50" not in w.did
        assert lines[-1].endswith(f"waits for its security OK: {holds}")
    else:
        assert w.did == ["cut:release 30.1 with #50"]


def test_a_fix_with_unknown_files_waits(tmp_path):
    w = rk.World(None, cfg(tmp_path), {"fixes": [dict(FIX, files=None)], "last_release": 30})
    lines = rk.fix_lane(w, {}, None, [])
    assert w.did == [] and "#50 (its own changed files are not known)" in lines[-1]


def test_the_files_of_a_fix_come_from_git_with_both_names_of_a_rename(tmp_path):
    """A fix that moves a watched file out of a watched path still needs the review: both names count."""
    origin, clone = _repo(tmp_path)
    (clone / "relay").mkdir()
    (clone / "relay" / "keys.py").write_text("x = 1\n" * 20)
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "relay file")
    _git(clone, "checkout", "-q", "-b", "pr50")
    _git(clone, "mv", "relay/keys.py", "moved.py")
    _git(clone, "commit", "-q", "-m", "move it")
    head = _git(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", head, "-m", "Merge pull request #50 from x/pr50")
    merge = _git(clone, "rev-parse", "HEAD")
    w = _keeper(tmp_path, clone)
    assert sorted(w.fix_files(dict(FIX, sha=merge, head=head))) == ["moved.py", "relay/keys.py"]
    _git(clone, "checkout", "-q", "-b", "pr51")
    (clone / "relay").mkdir(exist_ok=True)
    (clone / "relay" / "\u00fcber.rs").write_text("x\n")  # git would quote this name without -z
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "odd name")
    odd = _git(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--no-ff", odd, "-m", "Merge pull request #51 from x/pr51")
    got = w.fix_files(dict(FIX, number=51, sha=_git(clone, "rev-parse", "HEAD"), head=odd))
    assert got == ["relay/\u00fcber.rs"]
    assert w.fix_files(dict(FIX, sha=merge, head="")) is None  # unknown: the fix waits


def test_a_squashed_fix_ships_its_reviewed_head_not_the_squash(tmp_path):
    """A squash commit that also holds someone else's edit in the same file: only the reviewed head ships."""
    origin, clone = _repo(tmp_path)
    head = _commit(clone, "pr50", "develop", "app.txt", "release 30, fixed\n")
    _git(clone, "checkout", "-q", "develop")
    _git(clone, "merge", "-q", "--squash", head)
    (clone / "app.txt").write_text("release 30, fixed\nand an unreviewed line\n")
    _git(clone, "commit", "-qam", "The fix (#50)")
    squash = _git(clone, "rev-parse", "HEAD")
    _git(clone, "push", "-q", "origin", "develop")
    _git(clone, "fetch", "-q", "origin")
    got = _keeper(tmp_path, clone).cut_fix(30, 1, dict(FIX, sha=squash, head=head), "Fix release 30.1")
    assert _files(got["wt"]) == {"app.txt"} and _git(got["wt"], "show", "HEAD:app.txt") == "release 30, fixed"
