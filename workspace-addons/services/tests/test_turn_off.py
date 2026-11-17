"""Turning the add-on on and off through the real core: tickets stay readable, the command is refused once off,
and the records stay (kept unless --purge), like every add-on (contracts/addon-manifest.md, Install and activation)."""

import json
import sys
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[1]


@pytest.fixture
def core(tmp_path, monkeypatch, capsys):
    from orch import addons, cli, runs_live

    proj = tmp_path / "pröject"
    proj.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(proj)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    monkeypatch.setattr(addons, "real_home", lambda: home)
    monkeypatch.setenv("ORCH_HOME", str(home / "orchhome"))
    monkeypatch.setenv("ORCH_NO_PULL_LOOK", "1")
    monkeypatch.setenv("ORCH_NO_HEALTH_CHECK", "1")
    monkeypatch.setattr(runs_live, "resume_after_answer", lambda *a, **k: None)
    eps: dict = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))

    def fake_uv(args):  # "installing" = the package is already importable here; register its entry point
        eps["services"] = "orch_services"

    monkeypatch.setattr(addons, "run_uv", fake_uv)

    def reexec(args):
        if cli.main(args) != 0:
            raise RuntimeError("project step failed")

    monkeypatch.setattr(addons, "reexec", reexec)

    def run(*argv):
        code = cli.main(list(argv))
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return proj, run


def test_turning_the_addon_off_leaves_the_core_and_tickets_working(core, fake, monkeypatch, capsys):
    proj, run = core
    assert run("init")[0] == 0
    code, out, err = run("ticket", "new", "Keep the preview running", "--json")
    assert code == 0, err
    tid = json.loads(out)["id"]
    code, out, err = run("addon", "add", str(ADDON), "--yes")
    assert code == 0, err
    assert (proj / ".agents/skills/orch-services/SKILL.md").is_file()
    assert "## orch-services" in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")

    from orch_services.cli import main as services

    monkeypatch.setenv("ORCH_ROOT", str(proj))
    assert (
        services(["add", "Web", "--id", "web", "--ticket", tid, "--start", "--json", "--", sys.executable])
        == 0
    )
    capsys.readouterr()
    assert fake.entries["web"]["running"]

    code, out, err = run("addon", "remove", "services")
    assert code == 0, err
    assert not (proj / ".agents/skills/orch-services").exists()
    assert "orch-services" not in (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    code, out, err = run("services", "list")
    assert code == 2 and "not turned on" in err
    code, out, err = run("ticket", "list", "--json")
    assert code == 0 and tid in out
    code, out, err = run("ticket", "show", tid, "--json")
    assert code == 0 and json.loads(out)["title"] == "Keep the preview running"
    code, out, err = run("check", "add", tid, "Still works")
    assert code == 0, err
    assert (proj / ".orch/addons/services/services/web.json").is_file()  # kept unless --purge
