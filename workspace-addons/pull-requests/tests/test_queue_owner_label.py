"""A member's owner-approved label on the merge queue group (ORCH-1363).

The banned-words check lifts the whole group's diff when the group pull request carries the label, so the queue
puts it on only when a member carries it and every other member's own banned-words check is green at the head
that is in the group.
"""

from __future__ import annotations

import json
import shutil
import sys

import pytest
from test_queue import FakeGit, FakeGitHub, _git, _make_prs, make, states, url

from orch_pull_requests import localcheck, required_checks, runner, store
from orch_pull_requests.group import Git

REPO = "acme/app"
LABEL = runner.LABEL


class LabelHub(FakeGitHub):
    """FakeGitHub with labels, the members' own banned-words results and the labels a group was opened with."""

    def __init__(self, prs, words=None):
        super().__init__(prs)
        self.words = words or {}  # number -> conclusion of its own newest banned-words run at its head
        self.looked: list[tuple[str, str]] = []  # (commit, check name)
        self.opened_with: list[tuple[str, ...]] = []

    def pr(self, u):
        v = super().pr(u)
        n = int(u.rsplit("/", 1)[1])
        if v is not None and n in self.prs:
            v["labels"] = [{"name": x} for x in self.prs[n].get("labels", ())]
            if "now" in self.prs[n]:  # the head GitHub shows now (a push after the group was built)
                v["headRefOid"] = self.prs[n]["now"]
        return v

    def check_state(self, repo, sha, name):
        self.looked.append((sha, name))
        return self.words.get(int(sha))

    def create_pr(self, repo, base, branch, title, body, labels=()):
        self.opened_with.append(tuple(labels))
        return super().create_pr(repo, base, branch, title, body)


def _add(ws, *nums):
    for n in nums:
        store.add(ws, url(n), None, "agent:t", login="bot")


def _head(n: int) -> str:
    return f"{n:040d}"


def test_a_group_with_a_labelled_member_gets_the_label_when_the_others_passed_on_their_own(ws):
    _add(ws, 1, 2)
    gh = LabelHub({1: {"labels": [LABEL]}, 2: {}}, words={2: "success"})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert gh.opened_with == [(LABEL,)]
    assert runner.LABEL_LINE in gh.bodies[0]
    assert gh.looked == [(_head(2), required_checks.WORDS)]  # only the unlabelled member, at its group head
    assert states(ws) == {1: "merged", 2: "merged"} and len(calls) == 1


@pytest.mark.parametrize("own", ["failure", "pending", "skipped", None])
def test_an_unlabelled_member_without_its_own_green_banned_words_keeps_the_group_unlabelled(ws, own):
    """#2 adds banned words (or its own check did not pass yet): it never rides on #1's label."""
    _add(ws, 1, 2)
    logs: list[str] = []
    gh = LabelHub({1: {"labels": [LABEL]}, 2: {}}, words={2: own} if own else {})
    r, _ = make(ws, gh, FakeGit(), log=logs.append)
    r.run()
    assert gh.opened_with == [()]
    assert runner.LABEL_LINE not in gh.bodies[0]
    assert any("#2 has no green banned-words check of its own" in x for x in logs)


def test_no_labelled_member_no_label_and_no_extra_look(ws):
    _add(ws, 1, 2)
    gh = LabelHub({1: {}, 2: {}}, words={1: "success", 2: "success"})
    r, _ = make(ws, gh, FakeGit())
    r.run()
    assert gh.opened_with == [()] and gh.looked == []


def test_a_member_whose_head_moved_since_the_group_was_built_gives_no_label(ws):
    """Its green result would be for another head than the one in the group."""
    gh = LabelHub({1: {"labels": [LABEL]}, 2: {"now": "f" * 40}}, words={2: "success"})
    r, _ = make(ws, gh, FakeGit())
    inside = [{"url": url(n), "number": n, "head": _head(n)} for n in (1, 2)]
    assert r.owner_label(REPO, inside) == ""
    gh.prs[2].pop("now")
    assert r.owner_label(REPO, inside) == LABEL


def test_every_member_labelled_needs_no_look(ws):
    _add(ws, 1, 2)
    gh = LabelHub({1: {"labels": [LABEL]}, 2: {"labels": [LABEL, "x"]}})
    r, _ = make(ws, gh, FakeGit())
    r.run()
    assert gh.opened_with == [(LABEL,)] and gh.looked == []


def test_the_local_check_gets_the_label_too(ws):
    (ws / ".orch" / "config.toml").write_text('[pull_requests]\ngroup_check = "local"\n', encoding="utf-8")
    _add(ws, 1, 2)
    gh = LabelHub({1: {"labels": [LABEL]}, 2: {}}, words={2: "success"})
    gh.post_status = lambda repo, sha, context, state, description: True
    r, _ = make(ws, gh, FakeGit())
    seen: list[str] = []

    def local_check(repo, sha, on, labels=""):
        seen.append(labels)
        return localcheck.Result(localcheck.GREEN, 1.0, "the local check passed in 1s")

    r.local_check = local_check
    r.run()
    assert seen == [LABEL] and states(ws) == {1: "merged", 2: "merged"}


# -- the real local check, with real git ---------------------------------------------------------------------
# the stand-in banned-words check: bad.txt is a banned word unless the labels lift it, like the real script
WORDS = (
    "import pathlib, sys\n"
    "labels = sys.argv[sys.argv.index('--labels') + 1].split(',')\n"
    "sys.exit(0 if 'owner-approved' in labels or not pathlib.Path('bad.txt').exists() else 1)\n"
)


@pytest.fixture
def words_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("no git")
    work = tmp_path / "work"
    (work / "scripts").mkdir(parents=True)
    _git(work, "init", "-q")
    (work / "scripts" / "check_banned_words.py").write_text(WORDS, encoding="utf-8")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    for n, name in ((1, "bad.txt"), (2, "b.txt"), (3, "c.txt"), (4, "d.txt")):
        _git(work, "checkout", "-q", "-B", f"pr{n}", base)
        (work / name).write_text("x\n", encoding="utf-8")
        _git(work, "add", name)
        _git(work, "commit", "-q", "-m", f"pr {n}")
    _git(work, "checkout", "-q", "develop")
    return _make_prs(work)


def test_real_check_passes_a_labelled_group(ws, words_repo):
    git = Git(store.folder(ws), REPO, url=str(words_repo))
    heads = git.fetch("develop", [1, 2])
    sha, included, _ = git.build(heads["base"], [(1, heads["1"]), (2, heads["2"])])
    assert included == [1, 2]
    res = localcheck.run(git, sha, heads["base"], [sys.executable, "-c", "pass"], labels=LABEL)
    assert res.verdict == localcheck.GREEN, res.line


def test_real_check_still_fails_a_group_with_banned_words_and_no_label(ws, words_repo):
    git = Git(store.folder(ws), REPO, url=str(words_repo))
    heads = git.fetch("develop", [1, 2])
    sha, _, _ = git.build(heads["base"], [(1, heads["1"]), (2, heads["2"])])
    res = localcheck.run(git, sha, heads["base"], [sys.executable, "-c", "pass"])
    assert res.verdict == localcheck.RED and res.failed == ["banned-words"]


def test_the_check_command_sees_the_labels_in_its_environment(ws, words_repo, tmp_path):
    git = Git(store.folder(ws), REPO, url=str(words_repo))
    heads = git.fetch("develop", [2])
    out = tmp_path / "labels.json"
    code = f"import json, os; json.dump(os.environ.get('ORCH_CHECK_LABELS'), open({str(out)!r}, 'w'))"
    assert localcheck.run(
        git, heads["2"], heads["base"], [sys.executable, "-c", code], labels=LABEL
    ).verdict == (localcheck.GREEN)
    assert json.loads(out.read_text()) == LABEL
    assert (
        localcheck.run(git, heads["2"], heads["base"], [sys.executable, "-c", code]).verdict
        == localcheck.GREEN
    )
    assert json.loads(out.read_text()) == ""
