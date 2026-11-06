"""Upgrading from an old orch: the install script drops the add-on packages, the registry may name `scheduler`
(now automation), and a folder may still have `scheduler` turned on. None of that may block the user."""

import json
import os
import sys
from pathlib import Path

import pytest
from test_addons import make_addon, run, uv_calls  # noqa: F401

from orch import addons


def _write_registry(entries):
    p = Path(os.environ["ORCH_HOME"]) / "addons.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


OLD = [
    {"name": "dashboard", "source": "built-in", "version": "0.0.0"},
    {"name": "scheduler", "source": "built-in", "version": "0.0.0"},
]


@pytest.fixture
def github(monkeypatch):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    origin = {"repo": "https://github.com/o/orch", "ref": "develop"}
    monkeypatch.setattr(addons, "_install_origin", lambda: origin)


def _withs(call):
    return [call[i + 1].rsplit("=", 1)[-1] for i, a in enumerate(call) if a == "--with"]


def test_registry_reads_scheduler_as_automation(proj, github):
    _write_registry([*OLD, {"name": "automation", "source": "built-in", "version": "0.0.0"}])
    assert addons.installed_names() == ["dashboard", "automation"]


def test_update_installs_automation_not_scheduler(proj, run, github, uv_calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    _write_registry(OLD)
    code, _, err = run("update")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard", "workspace-addons/automation"]


def test_update_leaves_out_a_folder_that_is_gone(proj, run, github, uv_calls, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    gone = str(tmp_path / "no-such-addon")
    _write_registry([OLD[0], {"name": "mine", "source": gone, "version": "0.1.0"}])
    code, _, err = run("update")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard"] and gone not in uv_calls[0]
    assert "mine was left out" in err and "folder" in err


def test_add_reinstalls_when_the_package_is_gone(proj, run, github, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    """The registry says dashboard is installed, but the install script removed the package."""
    folder = make_addon(tmp_path / "pkgs", name="dashboard")
    eps = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))

    def fake_uv(args):
        uv_calls.append(args)
        sys.path.insert(0, str(folder / "src"))
        eps["dashboard"] = "orch_dashboard"

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    _write_registry(OLD)
    try:
        code, out, err = run("addon", "add", "dashboard", "--yes")
    finally:
        sys.path.remove(str(folder / "src"))
    assert code == 0, err
    assert len(uv_calls) == 1
    assert _withs(uv_calls[0]) == ["workspace-addons/automation", "workspace-addons/dashboard"]
    assert addons.installed_names() == ["automation", "dashboard"]  # saved under the new name
    assert "dashboard" in addons.active(proj)


def test_after_install_puts_registered_addons_back(proj, run, github, uv_calls, capfd):  # noqa: F811
    assert run("update", "--after-install")[0] == 0 and uv_calls == []  # first install: nothing to do
    p = _write_registry(OLD)
    code, out, err = run("update", "--after-install")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard", "workspace-addons/automation"]
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["automation", "dashboard"]
    assert "automation" in out


def test_scheduler_turned_on_in_a_folder_counts_as_automation(proj, run, monkeypatch):  # noqa: F811
    (proj / ".orch").mkdir()
    (proj / ".orch/addons.json").write_text('{"active": {"scheduler": {"version": "0.2.0"}}}')
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    addons.record_consent(proj, "scheduler")  # what the old orch wrote
    assert list(addons.listed(proj)) == ["automation"]
    assert list(addons.active(proj)) == ["automation"]
    code, _, err = run("addon", "remove", "scheduler")  # the old name still turns it off
    assert code == 0, err
    assert addons.listed(proj) == {} and addons.active(proj) == {}


def test_install_script_puts_addons_back():
    root = Path(__file__).resolve().parents[2]
    assert "update --after-install" in (root / "install.sh").read_text(encoding="utf-8")
    assert "update --after-install" in (root / "install.ps1").read_text(encoding="utf-8")
