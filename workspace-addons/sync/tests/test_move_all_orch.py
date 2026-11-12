"""#591: needs-move only for tracked .orch files that are not team-owned (core TEAM_FILES); Move clears it."""

import io
import subprocess

from orch import cli as core_cli
from orch import humanproof

from orch_sync import repo


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def init(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")


def test_team_owned_gitignore_alone_is_not_needs_move(root):
    init(root)
    (root / ".orch" / ".gitignore").write_text("run/\n")
    git(root, "add", "-f", ".orch/.gitignore")
    git(root, "commit", "-qm", "team")
    assert repo.state(root) == "new"


def test_unknown_orch_file_is_needs_move(root):
    init(root)
    (root / ".orch" / "unknown").write_text("personal")
    git(root, "add", "-f", ".orch/unknown")
    assert repo.state(root) == "needs-move"


def test_git_cannot_tell_stays_needs_move(root, monkeypatch):
    init(root)
    (root / ".orch" / "unknown").write_text("personal")
    git(root, "add", "-f", ".orch/unknown")

    def refused(*a, **k):
        raise repo.Refused("Git operation failed")

    monkeypatch.setattr(repo, "git", refused)
    assert repo.state(root) == "needs-move"


def test_move_with_extra_orch_files_clears_needs_move(root, monkeypatch):
    init(root)
    (root / ".orch" / "config.toml").write_text("[workspace]\n")
    (root / ".orch" / ".gitignore").write_text("run/\n")
    (root / ".orch" / "unknown").write_text("personal")
    (root / "team.txt").write_text("team")
    git(root, "add", "-f", ".orch", "team.txt")
    git(root, "commit", "-qm", "oops")
    assert repo.state(root) == "needs-move"
    key = humanproof.human_key(root)
    token = humanproof.mint(key, humanproof.new_payload("private.move", "move", "human:Pat"))
    monkeypatch.setattr("sys.stdin", io.StringIO(token + "\n"))
    monkeypatch.chdir(root)
    assert core_cli.main(["private", "move", "--proof-stdin"]) in (0, None)
    assert repo.state(root) == "new"
    assert (root / ".orch" / "unknown").is_file()
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", ".orch"], capture_output=True, text=True, check=True
    ).stdout
    assert out.split() == [".orch/.gitignore"]  # the team-owned file stays tracked


# #604 review: state() uses core's one discovery (harness.private_tracked) and fails closed.


def plant(root, path):
    """A raw index entry (update-index refuses `..`): a same-length stand-in, renamed in the index bytes."""
    import hashlib

    stand = path.replace("/../", "/aa/")
    blob = subprocess.run(
        ["git", "-C", str(root), "hash-object", "-w", "--stdin"],
        input="x",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{stand}")
    if stand != path:
        idx = root / ".git" / "index"
        data = idx.read_bytes()[:-20].replace(stand.encode(), path.encode())
        idx.write_bytes(data + hashlib.sha1(data).digest())


def agree(root):
    from orch import harness

    found = harness.private_tracked(root)
    assert repo.state(root) == ("needs-move" if found is None or found else "new")
    return found


def test_non_canonical_index_name_stays_needs_move(root):
    init(root)
    (root / "README.md").write_text("team")
    git(root, "add", "README.md")
    plant(root, ".orch/../README.md")
    assert agree(root) is None
    assert repo.state(root) == "needs-move"


def test_kelvin_workspace_toml_is_needs_move(root):
    init(root)
    plant(root, ".orch/wor\u212aspace.toml")
    assert agree(root) == [".orch/wor\u212aspace.toml"]


def test_case_variant_orch_folder_is_needs_move(root):
    init(root)
    probe = root / ".orch" / "CaseProbe"
    probe.write_text("x")
    icase = (root / ".orch" / "caseprobe").exists()
    probe.unlink()
    if not icase:
        import pytest

        pytest.skip("case-sensitive filesystem")
    (root / ".orch" / "unknown").write_text("x")
    (root / ".orch").rename(root / ".ORCH")
    git(root, "add", "-f", ".ORCH/unknown")
    (root / ".ORCH").rename(root / ".orch")
    assert agree(root) == [".ORCH/unknown"]


def test_discovery_failure_is_needs_move(root, monkeypatch):
    from orch import safegit

    init(root)
    (root / ".orch" / "unknown").write_text("x")
    git(root, "add", "-f", ".orch/unknown")
    real = safegit.run_bytes
    monkeypatch.setattr(
        safegit,
        "run_bytes",
        lambda args, *a, **k: (123, b"", "") if args[:1] == ["ls-files"] else real(args, *a, **k),
    )
    assert agree(root) is None
    assert repo.state(root) == "needs-move"
