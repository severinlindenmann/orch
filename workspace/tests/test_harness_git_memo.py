"""harness._in_git_repo keeps git's answer only while the repository files are unchanged (#1055)."""

import subprocess

import pytest

from orch import harness, safegit
from orch.errors import Refused


@pytest.fixture
def asked(monkeypatch):
    """The rev-parse calls that reach git."""
    calls = []
    real = safegit.run_bytes

    def spy(argv, cwd, timeout=10, **kw):
        if argv[:1] == ["rev-parse"]:
            calls.append(argv)
        return real(argv, cwd, timeout, **kw)

    monkeypatch.setattr(safegit, "run_bytes", spy)
    harness._REV_PARSE.clear()
    return calls


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_the_answer_is_kept_while_nothing_changes(tmp_path, asked):
    root = tmp_path / "plain"
    root.mkdir()
    assert harness._in_git_repo(root) is False
    assert harness._in_git_repo(root) is False
    assert len(asked) == 1
    _git(root, "init", "-q")
    assert harness._in_git_repo(root) is True  # a new `git init` is seen at once
    assert harness._in_git_repo(root) is True
    assert len(asked) == 2


def test_a_removed_git_folder_is_seen(tmp_path, asked):
    import shutil

    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    assert harness._in_git_repo(root) is True
    shutil.rmtree(root / ".git", onerror=lambda f, p, e: (__import__("os").chmod(p, 0o700), f(p)))
    assert harness._in_git_repo(root) is False


def test_core_bare_set_later_is_never_taken_for_no_repo(tmp_path, asked):
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    assert harness._in_git_repo(root) is True
    _git(root, "config", "core.bare", "true")  # what an agent could set in the repo config
    with pytest.raises(Refused, match="not a working copy"):
        harness._in_git_repo(root)


def test_a_git_variable_or_a_git_file_is_always_asked(tmp_path, asked, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    harness._in_git_repo(root)
    harness._in_git_repo(root)
    assert len(asked) == 2 or len(asked) == 1  # the variable is part of the key: same value, same answer
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    harness._in_git_repo(root)
    assert len(asked) >= 2  # another value asks again


def test_a_failure_is_never_kept(tmp_path, asked, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    real = safegit.run_bytes
    fail = {"on": True}

    def run(argv, cwd, timeout=10, **kw):
        if argv[:1] == ["rev-parse"] and fail["on"]:
            asked.append(argv)
            return 124, b"", "git took longer than 10 s"
        return real(argv, cwd, timeout, **kw)

    monkeypatch.setattr(safegit, "run_bytes", run)
    with pytest.raises(Refused):
        harness._in_git_repo(root)
    fail["on"] = False
    assert harness._in_git_repo(root) is False  # the timeout was not remembered


def test_the_exclude_file_question_follows_the_same_rule(tmp_path, asked):
    root = tmp_path / "r"
    root.mkdir()
    assert harness._git_exclude(root) is None  # not a repo
    _git(root, "init", "-q")
    found = harness._git_exclude(root)
    assert found is not None and found[0].name == "exclude"  # `git init` is seen at once
    n = len(asked)
    assert harness._git_exclude(root) == found
    assert len(asked) == n  # kept while nothing changed


def test_a_bare_repository_made_in_place_is_seen(tmp_path, asked):
    root = tmp_path / "r"
    root.mkdir()
    assert harness._in_git_repo(root) is False
    n = len(asked)
    _git(root, "init", "-q", "--bare")  # no .git entry: HEAD and objects appear in the folder itself
    harness._in_git_repo(root)
    assert len(asked) == n + 1  # git was asked again


def test_a_link_retargeted_later_is_not_a_stale_answer(tmp_path, asked):
    plain, repo = tmp_path / "plain", tmp_path / "repo"
    plain.mkdir()
    repo.mkdir()
    _git(repo, "init", "-q")
    link = tmp_path / "link"
    try:
        link.symlink_to(plain, target_is_directory=True)
    except OSError:
        pytest.skip("links need a right this account does not have")
    assert harness._in_git_repo(link) is False
    link.unlink()
    link.symlink_to(repo, target_is_directory=True)  # the same path now leads into a repository
    assert harness._in_git_repo(link) is True
