"""A release build on main sees everything that changed since the last release (ORCH-370).

After a release main's tree equals develop. Comparing main with develop (the filter's default) found 0 changed
files, so relay and publish were skipped and no binaries were built. scripts/ci_changes_base.sh gives the filter the
previous release instead; these tests replay a release merge in a throwaway git repo.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci_changes_base.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, env=ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def release_repo(tmp_path: Path) -> tuple[Path, str]:
    """main = release 32; develop changes relay/; release 33 merges develop into main. Returns (repo, release 32)."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "relay/src.rs", "v32\n")
    write(repo, "workspace/a.py", "v32\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "release 32")
    r32 = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "develop")
    write(repo, "relay/src.rs", "v33\n")
    git(repo, "commit", "-qam", "relay change")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "release 33", "develop")
    return repo, r32


def base(repo: Path, before: str = "") -> str:
    return subprocess.run(
        ["bash", str(SCRIPT), before], cwd=repo, env=ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


def changed(repo: Path, since: str) -> list[str]:
    return git(repo, "diff", "--name-only", since, "HEAD").splitlines()


def test_default_compare_with_develop_sees_nothing(tmp_path):
    """The bug: main and develop have the same tree after a release."""
    repo, _ = release_repo(tmp_path)
    assert git(repo, "diff", "--name-only", "develop...main") == ""


def test_release_push_compares_with_before(tmp_path):
    repo, r32 = release_repo(tmp_path)
    assert base(repo, r32) == r32
    assert changed(repo, base(repo, r32)) == ["relay/src.rs"]


def test_manual_run_compares_with_previous_release(tmp_path):
    """workflow_dispatch has no "before": the first parent of the release merge is the previous release."""
    repo, r32 = release_repo(tmp_path)
    assert base(repo, "") == r32
    assert changed(repo, base(repo)) == ["relay/src.rs"]


def test_unknown_or_zero_before_falls_back_to_first_parent(tmp_path):
    repo, r32 = release_repo(tmp_path)
    assert base(repo, "0" * 40) == r32
    assert base(repo, "f" * 40) == r32


def test_ci_main_uses_the_base():
    text = CI.read_text(encoding="utf-8")
    assert "scripts/ci_changes_base.sh" in text
    assert "base: ${{ steps.base.outputs.sha }}" in text
    assert "fetch-depth: 0" in text  # the base commit must be in the clone


def dev_clone(tmp_path: Path) -> tuple[Path, str]:
    """origin: main = release 32, develop two changes ahead. Returns (a clone on develop, release 32)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    write(origin, "relay/src.rs", "v32\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "release 32")
    r32 = git(origin, "rev-parse", "HEAD")
    git(origin, "switch", "-qc", "develop")
    write(origin, "relay/src.rs", "v33\n")
    git(origin, "commit", "-qam", "relay change")
    write(origin, "workspace/a.py", "v33\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "workspace change")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-b", "develop", str(origin), str(clone)], env=ENV, check=True)
    return clone, r32


def test_manual_run_on_develop_compares_with_main(tmp_path):
    """#2559: the release keeper's manual run on develop compared develop with itself (0 changed files) and
    skipped 14 of 17 jobs. --since-main gives where develop meets main: everything since the last release."""
    clone, r32 = dev_clone(tmp_path)
    assert git(clone, "diff", "--name-only", "origin/develop...HEAD") == ""  # the bug: the default
    got = subprocess.run(
        ["bash", str(SCRIPT), "--since-main"], cwd=clone, env=ENV, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert got == r32 and changed(clone, got) == ["relay/src.rs", "workspace/a.py"]


def test_since_main_prints_nothing_without_main(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "develop")
    write(repo, "a.txt", "a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    write(repo, "a.txt", "b\n")
    git(repo, "commit", "-qam", "two")
    assert base(repo, "--since-main") == ""


def test_ci_manual_runs_on_any_branch_get_the_base():
    text = CI.read_text(encoding="utf-8")
    step = text[text.index("- id: base") : text.index("- id: f")]
    assert "github.event_name == 'workflow_dispatch'" in step.split("env:")[0]
    assert "ci_changes_base.sh --since-main" in step
