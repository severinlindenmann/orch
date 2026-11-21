"""After the install script replaced orch: the add-on packages are gone but the registry still lists them,
or a registered folder is gone. None of that may block the user."""

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
    {"name": "automation", "source": "built-in", "version": "0.0.0"},
]


@pytest.fixture(autouse=True)
def source_metadata(monkeypatch):
    monkeypatch.setattr(addons, "_source_sha", lambda: None)
    monkeypatch.setattr(addons, "_release_title", lambda: None)


@pytest.fixture
def github(monkeypatch):
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    origin = {"repo": "https://github.com/o/orch", "ref": "develop"}
    monkeypatch.setattr(addons, "_install_origin", lambda: origin)


def _withs(call):
    return [call[i + 1].rsplit("=", 1)[-1] for i, a in enumerate(call) if a == "--with"]


def test_update_installs_every_registered_addon(proj, run, github, uv_calls, monkeypatch):  # noqa: F811
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
    assert addons.installed_names() == ["automation", "dashboard"]
    assert "dashboard" in addons.active(proj)


def test_after_install_puts_registered_addons_back(proj, run, github, uv_calls, capfd):  # noqa: F811
    assert run("update", "--after-install")[0] == 0 and uv_calls == []  # first install: nothing to do
    p = _write_registry(OLD)
    code, out, err = run("update", "--after-install")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard", "workspace-addons/automation"]
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["automation", "dashboard"]
    assert "automation" in out


def test_after_install_drops_a_builtin_that_no_longer_ships(proj, run, github, uv_calls):  # noqa: F811
    """An install from an older orch registered 'scheduler' (renamed to automation): the reinstall leaves it
    out and removes it from the registry instead of failing on a missing folder."""
    p = _write_registry([OLD[0], {"name": "scheduler", "source": "built-in", "version": "0.2.0"}])
    code, out, err = run("update", "--after-install")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard"]
    assert "scheduler" not in " ".join(uv_calls[0])
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]
    assert "scheduler removed" in out


def test_after_install_with_only_a_dropped_builtin(proj, run, github, uv_calls):  # noqa: F811
    p = _write_registry([{"name": "scheduler", "source": "built-in", "version": "0.2.0"}])
    code, out, err = run("update", "--after-install")
    assert code == 0, err
    assert uv_calls == [] and json.loads(p.read_text(encoding="utf-8")) == []


def test_update_leaves_out_a_builtin_that_no_longer_ships(proj, run, github, uv_calls, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    _write_registry([OLD[0], {"name": "scheduler", "source": "built-in", "version": "0.2.0"}])
    code, out, err = run("update")
    assert code == 0, err
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard"]
    assert "scheduler removed" in out


def test_an_unknown_old_name_is_refused_plainly(proj, run, uv_calls, tmp_path, monkeypatch):  # noqa: F811
    (proj / ".orch").mkdir()
    (proj / ".orch/addons.json").write_text('{"active": {"scheduler": {"version": "0.2.0"}}}')
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    (tmp_path / "repo" / "workspace-addons").mkdir(parents=True)
    monkeypatch.setenv("ORCH_REPO", str(tmp_path / "repo"))
    assert addons.active(proj) == {}
    code, _, err = run("addon", "add", "scheduler", "--yes")
    assert code == 2 and "no built-in add-on 'scheduler'" in err and "Traceback" not in err, err


def test_install_script_puts_addons_back():
    root = Path(__file__).resolve().parents[2]
    assert "update --after-install" in (root / "install.sh").read_text(encoding="utf-8")
    assert "update --after-install" in (root / "install.ps1").read_text(encoding="utf-8")


# ---------------------------------------------------------------- an add-on removed from the repository
# ORCH-1369: after #1772 removed dashboard-tester, `orch update` on an install that had it failed: the
# running (old) orch still listed it as shipped, so uv was asked for workspace-addons/dashboard-tester, which
# the new source no longer has, and the update was refused. `orch addon remove` refused it too (it was off).

# Every add-on that once shipped in workspace-addons/ and was removed. Removing another one from the
# repository: add its name here (test_every_removed_addon_is_listed fails until then); the tests below then
# prove an install that still lists it updates and can remove it.
REMOVED_ADDONS = ("dashboard-tester", "scheduler")
# Of those, the ones a release still ships: they keep a placeholder package in workspace-addons/<name>.
PLACEHOLDERS = ("dashboard-tester",)


def _old_orch_ships(monkeypatch, *names):
    """The running orch is the OLD one: its own catalog still lists these add-ons."""
    monkeypatch.setattr(addons, "SHIPPED_ADDONS", tuple(sorted({*addons.SHIPPED_ADDONS, *names})))


@pytest.mark.parametrize("gone", REMOVED_ADDONS)
def test_update_drops_an_addon_the_new_source_no_longer_ships(proj, run, github, uv_calls, monkeypatch, gone):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    _old_orch_ships(monkeypatch, gone)
    asked = []

    def catalog(r, at):
        asked.append((r, at))
        return frozenset({"dashboard", "automation"})

    monkeypatch.setattr(addons, "_fetch_source_catalog", catalog)
    p = _write_registry([OLD[0], {"name": gone, "source": "built-in", "version": "0.1.0"}])
    code, out, err = run("update")
    assert code == 0, err
    assert asked == [("https://github.com/o/orch", "develop")]
    assert _withs(uv_calls[0]) == ["workspace-addons/dashboard"]
    assert gone not in " ".join(uv_calls[0])
    assert f"Add-on {gone} removed: it no longer ships with orch." in out
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]


def test_update_drops_it_after_uv_says_the_folder_is_gone(proj, run, github, monkeypatch):  # noqa: F811
    """The source catalog could not be read (offline, another host): uv's own error names the missing
    folder, so the update drops that add-on and installs once more without it."""
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    _old_orch_ships(monkeypatch, "dashboard-tester")
    calls = []

    def fake_uv(args):
        calls.append(args)
        if "dashboard-tester" in " ".join(args):
            raise RuntimeError(
                "Failed to build `orch-dashboard-tester @ https://github.com/o/orch/archive/develop.zip`\n"
                "  Caused by: The source distribution has no subdirectory workspace-addons/dashboard-tester"
            )

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    monkeypatch.setattr(addons, "reexec", lambda args: None)
    p = _write_registry([OLD[0], {"name": "dashboard-tester", "source": "built-in", "version": "0.1.0"}])
    code, out, err = run("update")
    assert code == 0, err
    assert len(calls) == 2 and _withs(calls[1]) == ["workspace-addons/dashboard"]
    assert "Add-on dashboard-tester removed: it no longer ships with orch." in out
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]


def test_another_uv_failure_still_refuses_the_update(proj, run, github, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    calls = []

    def fake_uv(args):
        calls.append(args)
        raise RuntimeError("network down")

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    p = _write_registry(OLD)
    code, _, err = run("update")
    assert code == 2 and len(calls) == 1, err
    assert len(json.loads(p.read_text(encoding="utf-8"))) == 2


@pytest.mark.parametrize("shipped", [True, False])
def test_remove_uninstalls_an_addon_that_is_off(proj, run, github, uv_calls, monkeypatch, shipped):  # noqa: F811
    """`orch addon remove <name>` for an add-on that is installed but off here (also one this orch no longer
    ships): it is taken off this computer instead of 'not turned on in this workspace'."""
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    if shipped:
        _old_orch_ships(monkeypatch, "dashboard-tester")
    p = _write_registry([OLD[0], {"name": "dashboard-tester", "source": "built-in", "version": "0.1.0"}])
    code, out, err = run("addon", "remove", "dashboard-tester")
    assert code == 0, err
    assert "dashboard-tester is uninstalled." in out
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]
    assert _withs(uv_calls[-1]) == ["workspace-addons/dashboard"]


def test_remove_of_an_unknown_addon_is_still_refused(proj, run, uv_calls):  # noqa: F811
    code, _, err = run("addon", "remove", "never-was")
    assert code == 2 and "not turned on in this workspace" in err and uv_calls == []


def test_a_broken_source_catalog_never_drops_everything():
    assert addons._catalog_names("{}") is None
    assert addons._catalog_names("[]") is None
    assert addons._catalog_names("not json") is None
    assert addons._catalog_names('{"dashboard": {}, "../x": {}}') == frozenset({"dashboard"})


def test_every_removed_addon_is_listed():
    """Rule: an add-on removed from workspace-addons/ must be named in REMOVED_ADDONS, so update and remove
    paths above are proven for installs that still list it (ORCH-1369). One that a release still ships keeps a
    placeholder folder (pyproject.toml only, no src/): the OLD orch runs the install step of `orch update` and
    asks uv for that folder."""
    import subprocess

    top = Path(__file__).resolve().parents[2]
    r = subprocess.run(
        [
            "git",
            "log",
            "--diff-filter=D",
            "--name-only",
            "--format=",
            "--",
            "workspace-addons/*/*/*/orch-addon.toml",
        ],
        cwd=top,
        capture_output=True,
        text=True,
        check=False,
    )
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], cwd=top, capture_output=True, text=True, check=False
    ).stdout.strip()
    if r.returncode != 0 or shallow != "false":
        pytest.skip("no full git history here")
    removed = {
        line.split("/")[1]
        for line in r.stdout.splitlines()
        if line.startswith("workspace-addons/")
        and not (top / "workspace-addons" / line.split("/")[1] / "src").is_dir()
    }
    missing = sorted(removed - set(REMOVED_ADDONS))
    assert not missing, f"add-ons removed from the repository but not in REMOVED_ADDONS: {missing}"
    assert not set(REMOVED_ADDONS) & set(addons.SHIPPED_ADDONS)


@pytest.mark.parametrize("name", PLACEHOLDERS)
def test_a_placeholder_is_an_empty_package_orch_never_offers(name):
    import tomllib

    folder = Path(__file__).resolve().parents[2] / "workspace-addons" / name
    assert sorted(p.name for p in folder.iterdir() if not p.name.startswith(".")) == ["pyproject.toml"]
    data = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == f"orch-{name}"  # what spec() asks uv for
    assert data["project"]["dependencies"] == [] and "entry-points" not in data["project"]
    assert name not in addons.SHIPPED_ADDONS and name not in addons.bundled_manifests()


def test_the_project_step_drops_what_the_old_orch_kept(proj, run, github, uv_calls, monkeypatch):  # noqa: F811
    """A release that still shipped dashboard-tester installed it from the placeholder; the new code's project
    step then takes it off the list with the plain line."""
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    p = _write_registry([OLD[0], {"name": "dashboard-tester", "source": "built-in", "version": "0.1.0"}])
    code, out, err = run("update", "--project-only")
    assert code == 0, err
    assert "Add-on dashboard-tester removed: it no longer ships with orch." in out
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]


def test_a_failed_retry_keeps_the_add_on_list(proj, run, github, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    _old_orch_ships(monkeypatch, "dashboard-tester")

    def fake_uv(args):
        if "dashboard-tester" in " ".join(args):
            raise RuntimeError("has no subdirectory workspace-addons/dashboard-tester")
        raise RuntimeError("network down")

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    p = _write_registry([OLD[0], {"name": "dashboard-tester", "source": "built-in", "version": "0.1.0"}])
    code, _, err = run("update")
    assert code == 2, err
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard", "dashboard-tester"]


def test_a_local_source_placeholder_is_not_an_add_on(proj, run, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    """A source folder that keeps only the placeholder (no src/): the update drops the add-on there too."""
    monkeypatch.setattr(addons, "_entry_points", lambda: {})
    src = tmp_path / "src-repo"
    (src / "workspace-addons" / "dashboard-tester").mkdir(parents=True)
    (src / "workspace-addons" / "dashboard-tester" / "pyproject.toml").write_text(
        "[project]\n", encoding="utf-8"
    )
    (src / "workspace-addons" / "dashboard" / "src").mkdir(parents=True)
    monkeypatch.setenv("ORCH_REPO", str(src))
    p = _write_registry([OLD[0], {"name": "dashboard-tester", "source": "built-in", "version": "0.1.0"}])
    code, out, err = run("update")
    assert code == 0, err
    assert "Add-on dashboard-tester removed: it no longer ships with orch." in out
    assert [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))] == ["dashboard"]
