"""The local-only ignore list (contracts/local-files.md) is ONE constant; init and the update path write
all of it, and rewriting the exclude block keeps every orch-owned line (skill links)."""

import os
import re
import subprocess
from pathlib import Path

from orch import harness


def git(proj, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=proj, env=env, capture_output=True, text=True, check=check)


def repo(proj):
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@example.com")
    git(proj, "config", "user.name", "t")


def _contract_list() -> list[str]:
    doc = (Path(__file__).resolve().parents[2] / "contracts" / "local-files.md").read_text(encoding="utf-8")
    section = doc.split("## Local-only lines", 1)[1]
    block = re.search(r"```\n(.*?)\n```", section, re.S).group(1)
    return block.split()


def test_the_constant_is_the_contract_list():
    assert harness.CONTRACT_IGNORE == _contract_list()
    assert set(harness.CONTRACT_IGNORE) <= set(harness.ORCH_IGNORE)  # the written list starts from it
    assert {"record/", ".usage-salt"} <= set(harness.CONTRACT_IGNORE)


def _ignored(proj):
    for rel in (".orch/record/x", ".orch/.usage-salt"):
        assert git(proj, "check-ignore", "-q", rel, check=False).returncode == 0, rel


def test_init_ignores_record_and_usage_salt(proj, run):
    repo(proj)
    assert run("init", "--json")[0] == 0
    _ignored(proj)
    assert "record/" in (proj / ".orch" / ".gitignore").read_text().split()


def test_the_update_path_adds_them_to_an_older_workspace(proj, run):
    repo(proj)
    assert run("init", "--json")[0] == 0
    old = [
        ln
        for ln in (proj / ".orch" / ".gitignore").read_text().splitlines()
        if ln not in ("record/", ".usage-salt")
    ]
    (proj / ".orch" / ".gitignore").write_text("\n".join(old) + "\n")
    ex = proj / ".git" / "info" / "exclude"
    ex.write_text(
        "\n".join(ln for ln in ex.read_text().splitlines() if "record" not in ln and "usage-salt" not in ln)
        + "\n"
    )
    assert git(proj, "check-ignore", "-q", ".orch/record/x", check=False).returncode == 1  # the old state
    assert run("init", "--json")[0] == 0  # what an update runs (init is safe to run again)
    _ignored(proj)


def test_move_to_private_keeps_the_skill_exclude_lines(proj, run):
    repo(proj)
    assert run("init", "--json")[0] == 0
    assert (proj / ".agents" / "skills" / "orch").exists()
    git(proj, "add", "-f", ".orch/config.toml")
    git(proj, "commit", "-qm", "oops")
    assert harness.move_to_private(proj)
    status = git(proj, "status", "--porcelain").stdout
    assert ".agents/skills" not in status, status
