import json
import os
import subprocess
from pathlib import Path

import pytest

from orch import adapters, cli_leave


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


def _git(proj, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *args], cwd=proj, env=env, capture_output=True, text=True, check=True
    ).stdout


def _snapshot(proj: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(proj.rglob("*")):
        rel = p.relative_to(proj).as_posix()
        if rel.startswith(".git/") and rel != ".git/info/exclude":
            continue
        if p.is_file() and not p.is_symlink():
            out[rel] = p.read_bytes()
    return out


USER_HOOK = {
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine", "timeout": 3}]}]},
    "theme": "dark",
}


def test_uninstall_leaves_the_folder_as_it_was(proj, run):
    _git(proj, "init", "-q")
    (proj / "CLAUDE.local.md").write_text("# My notes\n", encoding="utf-8")
    (proj / ".claude/skills/mine").mkdir(parents=True)
    (proj / ".claude/skills/mine/SKILL.md").write_text("mine\n", encoding="utf-8")
    (proj / ".claude/settings.local.json").write_text(
        json.dumps(USER_HOOK, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    before = _snapshot(proj)
    status = _git(proj, "status", "--porcelain", "--untracked-files=all")
    assert run("init")[0] == 0
    assert run("ticket", "new", "Keep me")[0] == 0
    assert (proj / ".claude/skills/orch").exists()
    code, out, _ = run("uninstall")
    assert code == 0
    assert "uv tool uninstall orch-workspace" in out.splitlines()[-1]
    after = _snapshot(proj)
    for rel, data in before.items():
        assert after.get(rel) == data, rel
    extra = sorted(set(after) - set(before))
    assert extra and all(
        x.startswith((".orch/tickets/", ".orch/diag/"))
        or x in (".orch/config.toml", ".orch/ticket-counter.json", ".orch/.gitignore")
        for x in extra
    ), extra
    assert not (proj / ".agents").exists()
    assert not (proj / ".orch/harness").exists() and not (proj / ".orch/run").exists()
    assert (proj / ".orch/.gitignore").is_file()  # kept tickets keep their ignore rules (R5.2)
    now = _git(proj, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert [x for x in now if not x[3:].startswith(".orch/")] == status.splitlines()
    code, out, _ = run("uninstall")
    assert code == 0 and "Nothing to remove." in out


def test_uninstall_after_a_plain_init_deletes_the_files_orch_made(proj, run):
    assert run("init")[0] == 0
    assert run("uninstall")[0] == 0
    assert not (proj / "CLAUDE.local.md").exists()
    assert not (proj / ".claude").exists()
    assert (proj / ".orch/tickets").is_dir()


def test_uninstall_refuses_a_folder_that_is_not_set_up(proj, run):
    code, _, err = run("uninstall")
    assert code != 0 and "not set up" in err


def test_uninstall_keeps_secrets_out_of_git(proj, run):
    _git(proj, "init", "-q")
    assert run("init")[0] == 0
    (proj / ".orch/secrets").mkdir()
    (proj / ".orch/secrets/k").write_text("x", encoding="utf-8")
    assert run("uninstall")[0] == 0
    assert (proj / ".orch/secrets/k").is_file()
    assert (proj / ".orch/.gitignore").is_file()


def test_uninstall_keeps_ignore_rules_while_data_stays(proj, run):
    """R5.2: no secrets folder, but tickets and config stay: .orch/.gitignore stays, so a later `git add -A`
    still leaves the kept tickets and orch's private files (here a message in .orch/inbox/) out of git."""
    _git(proj, "init", "-q")
    assert run("init")[0] == 0
    rules = (proj / ".orch/.gitignore").read_text(encoding="utf-8")
    assert run("ticket", "new", "Private plan")[0] == 0
    assert not (proj / ".orch/secrets").exists()
    assert run("uninstall")[0] == 0
    assert (proj / ".orch/.gitignore").read_text(encoding="utf-8") == rules
    (proj / ".orch/inbox").mkdir(exist_ok=True)
    (proj / ".orch/inbox/m_1.json").write_text("{}", encoding="utf-8")
    _git(proj, "add", "-A")
    staged = _git(proj, "diff", "--cached", "--name-only").splitlines()
    assert not [x for x in staged if x.startswith(".orch/")], staged  # nothing of .orch goes in


def test_uninstall_json(proj, run):
    assert run("init")[0] == 0
    code, out, _ = run("uninstall", "--json")
    d = json.loads(out)
    assert code == 0 and d["ok"] and d["removed"] and ".orch/tickets" in d["kept"]
    assert cli_leave.TOOL in d["remove_orch"]
