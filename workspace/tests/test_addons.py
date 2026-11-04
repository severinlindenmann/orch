import json
import sys

import pytest

from orch import addons


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    sk = repo / "workspace-addons" / "dashboard" / "skills" / "orch-dashboard"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: orch-dashboard\ndescription: d\n---\nbody\n", encoding="utf-8")
    (sk / "AGENTS-block.md").write_text("## orch-dashboard\nRead the skill.\n", encoding="utf-8")
    monkeypatch.setenv("ORCH_REPO", str(repo))
    return repo


@pytest.fixture
def uv_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(addons, "run_uv", lambda args: calls.append(args))

    def reexec(args):
        from orch import cli

        if cli.main(args) != 0:
            raise addons.Refused("project step failed")

    monkeypatch.setattr(addons, "reexec", reexec)
    return calls


def test_spec_local_and_git(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_REPO", str(tmp_path))
    assert addons.spec("workspace") == str((tmp_path / "workspace").resolve())
    monkeypatch.setenv("ORCH_REPO", "https://github.com/x/y.git")
    monkeypatch.setenv("ORCH_REF", "feat")
    assert (
        addons.spec("workspace-addons/dashboard")
        == "git+https://github.com/x/y@feat#subdirectory=workspace-addons/dashboard"
    )


def test_default_source(monkeypatch):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    assert (
        addons.spec("workspace")
        == "git+https://github.com/severinlindenmann/orch@main#subdirectory=workspace"
    )


def test_add_list_remove(proj, run, fake_repo, uv_calls):
    assert run("addon", "list")[1].split() == [
        "dashboard",
        "not",
        "installed",
        "scheduler",
        "not",
        "installed",
    ]
    code, _, err = run("addon", "add", "dashboard")
    assert code == 0, err
    assert uv_calls[0][:3] == ["tool", "install", "--reinstall"]
    assert "--with" in uv_calls[0] and uv_calls[0][-1].replace("\\", "/").endswith("workspace-addons/dashboard")
    assert (proj / ".agents/skills/orch-dashboard/SKILL.md").is_file()
    assert "orch:begin orch-dashboard" in (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert json.loads(run("addon", "list", "--json")[1])["dashboard"] == "installed"
    assert addons.installed_names() == ["dashboard"]
    assert run("addon", "remove", "dashboard")[0] == 0
    assert not (proj / ".agents/skills/orch-dashboard").exists()
    assert "orch-dashboard" not in (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert addons.installed_names() == []


def test_unknown_addon_refused(proj, run, uv_calls):
    code, _, err = run("addon", "add", "nope")
    assert code == 2 and "Unknown" in err and not uv_calls


def test_update_reinstalls_and_refreshes(proj, run, fake_repo, uv_calls):
    run("init")
    run("addon", "add", "dashboard")
    uv_calls.clear()
    (proj / ".agents/skills/orch/SKILL.md").write_text("stale", encoding="utf-8")
    assert run("update")[0] == 0
    assert len(uv_calls) == 1 and uv_calls[0][-1].replace("\\", "/").endswith("workspace-addons/dashboard")
    assert "name: orch" in (proj / ".agents/skills/orch/SKILL.md").read_text(encoding="utf-8")
    assert (proj / ".agents/skills/orch-dashboard/SKILL.md").is_file()


def test_add_without_skill_refused(proj, run, tmp_path, monkeypatch, uv_calls):
    monkeypatch.setenv("ORCH_REPO", str(tmp_path))
    code, _, err = run("addon", "add", "scheduler")
    assert code == 2


def test_skill_found_in_installed_package(proj, tmp_path, monkeypatch):
    pkg = tmp_path / "site" / "orch_scheduler" / "skills" / "orch-scheduler"
    pkg.mkdir(parents=True)
    (tmp_path / "site" / "orch_scheduler" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(tmp_path / "site"), *sys.path])
    monkeypatch.delenv("ORCH_REPO", raising=False)
    assert addons.addon_skill_dir("scheduler") == pkg


def test_uv_in_cwd_rejected(tmp_path, monkeypatch):
    fake = tmp_path / ("uv.exe" if sys.platform == "win32" else "uv")
    fake.write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(addons.shutil, "which", lambda _n: str(fake))
    assert addons._which_uv() is None
