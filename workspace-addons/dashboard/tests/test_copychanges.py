import subprocess
from pathlib import Path

from orch_dashboard import copychanges


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.x", *args], cwd=root, check=True, capture_output=True)


def make(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "start")
    git(tmp_path, "branch", "orch/t_abc123")
    git(tmp_path, "checkout", "-q", "orch/t_abc123")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    (tmp_path / "new.md").write_text("hello\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "work")
    git(tmp_path, "checkout", "-q", "-")


def test_listing_and_diff(tmp_path):
    make(tmp_path)
    got = copychanges.listing(tmp_path, "t_abc123")["files"]
    assert {f["path"]: (f["added"], f["removed"]) for f in got} == {"a.txt": (1, 0), "new.md": (1, 0)}
    code, data = copychanges.diff(tmp_path, "t_abc123", "a.txt")
    assert code == 200 and "+two" in data["diff"]


def test_refuses_unknown_names(tmp_path):
    make(tmp_path)
    assert copychanges.listing(tmp_path, "../x") == {"files": []}
    assert copychanges.diff(tmp_path, "t_abc123", "../../etc/passwd")[0] == 404
    assert copychanges.diff(tmp_path, "t_abc123", "README")[0] == 404
