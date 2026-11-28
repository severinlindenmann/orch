"""R9.4 contract check (scripts/check_contracts.py): every vector has a consumer replay; changed examples are additive."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_contracts as cc  # noqa: E402


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)


def write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data))


def test_a_vector_without_a_consumer_test_fails(tmp_path, capsys):
    write(tmp_path, "contracts/vectors/thing-v1.json", {"cases": []})
    write(tmp_path, "contracts/vectors/group/valid-a.json", {})
    write(tmp_path, "relay/tests/thing.rs", 'include_str!("../../contracts/vectors/thing-v1.json")')
    assert cc.unreplayed(tmp_path) == ["group"]
    write(tmp_path, "mobile/OrchMobileTests/G.swift", 'appendingPathComponent("contracts/vectors/group")')
    assert cc.unreplayed(tmp_path) == []
    assert cc.main(["--repo", str(tmp_path)]) == 0
    write(tmp_path, "contracts/vectors/other-v1.json", {})
    write(tmp_path, "workspace/README.md", "other-v1.json")  # docs are not a replay
    assert cc.main(["--repo", str(tmp_path)]) == 1
    assert "contracts/vectors/other-v1: no consumer test replays it" in capsys.readouterr().out


def test_additions_are_fine_losses_and_changes_are_listed():
    old = {"about": "x", "cases": [{"name": "a", "ok": True}, {"name": "b", "ok": False}], "keep": {"k": 1}}
    grown = {"about": "y", "cases": [{"name": "new"}, {"name": "b", "ok": False}, {"name": "a", "ok": True, "x": 2}],
             "keep": {"k": 1, "more": 2}, "extra": []}
    assert cc.losses(old, grown) == []
    assert cc.losses(old, {**grown, "keep": {}}) == ["$.keep.k: removed"]
    changed = {**grown, "cases": [{"name": "a", "ok": False}, {"name": "b", "ok": False}]}
    assert cc.losses(old, changed) == ["$.cases[0]: removed or changed"]
    assert cc.losses({"v": 1}, {"v": "1"}) == ['$.v: 1 -> "1"']


def test_breaking_changes_against_the_base_are_warnings_only(tmp_path, capsys):
    git(tmp_path, "init", "-q", "-b", "main")
    write(tmp_path, "contracts/vectors/a-v1.json", {"cases": [1, 2]})
    write(tmp_path, "contracts/examples/k/valid-x.json", {"id": "x"})
    write(tmp_path, "relay/tests/a.rs", "a-v1.json")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "pr")
    write(tmp_path, "contracts/vectors/a-v1.json", {"cases": [1, 2, 3]})
    git(tmp_path, "commit", "-qam", "additive")
    assert cc.breaking_changes(tmp_path, "main") == []
    write(tmp_path, "contracts/vectors/a-v1.json", {"cases": [1]})
    git(tmp_path, "rm", "-q", "contracts/examples/k/valid-x.json")
    git(tmp_path, "commit", "-qam", "breaking")
    assert cc.breaking_changes(tmp_path, "main") == [
        "contracts/examples/k/valid-x.json file removed",
        "contracts/vectors/a-v1.json $.cases[1]: removed or changed",
    ]
    assert cc.main(["--repo", str(tmp_path), "--base", "main"]) == 0
    out = capsys.readouterr().out
    assert "::warning file=contracts/vectors/a-v1.json::not additive (R9.4): $.cases[1]" in out


def test_the_repo_has_no_vector_without_a_consumer():
    assert cc.unreplayed(Path(__file__).resolve().parents[2]) == []
