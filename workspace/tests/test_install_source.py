"""Release or development build (issue 957): orch says where it came from and `orch update --to` switches,
through the same update path as every other update."""

import pytest

from orch import addons, cli, updateinfo
from orch import home as home_mod
from orch.errors import Refused

OFFICIAL = addons.DEFAULT_REPO


@pytest.fixture(autouse=True)
def _no_switch(monkeypatch):
    monkeypatch.setattr(addons, "_SWITCH_TO", None)
    monkeypatch.setattr(home_mod, "install_kind", lambda: "normal")
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)


def _origin(monkeypatch, origin):
    monkeypatch.setattr(addons, "_install_origin", lambda: origin)


@pytest.mark.parametrize(
    ("origin", "want"),
    [
        ({"repo": OFFICIAL, "ref": "main"}, "release"),
        ({"repo": OFFICIAL + ".git", "ref": "main"}, "release"),
        ({"repo": OFFICIAL, "ref": "develop"}, "development"),
        ({"repo": OFFICIAL, "ref": "feat/x"}, "development"),
        ({"repo": "https://github.com/someone/orch", "ref": "main"}, "development"),
    ],
)
def test_build_follows_the_recorded_install_source(monkeypatch, origin, want):
    _origin(monkeypatch, origin)
    assert addons.build() == want


def test_a_folder_install_is_a_development_build(monkeypatch, tmp_path):
    (tmp_path / "workspace").mkdir()
    _origin(monkeypatch, {"repo": str(tmp_path), "local": True})
    assert addons.build() == "development"


def test_an_editable_checkout_is_a_development_build(monkeypatch):
    _origin(monkeypatch, {})
    monkeypatch.setattr(home_mod, "_source_tree", lambda: True)
    assert addons.build() == "development"


def test_no_recorded_source_outside_a_checkout_is_the_release(monkeypatch):
    _origin(monkeypatch, {})
    monkeypatch.setattr(home_mod, "_source_tree", lambda: False)
    assert addons.build() == "release"


def test_dev_install_env_ref_counts(monkeypatch):
    _origin(monkeypatch, {"repo": OFFICIAL, "ref": "main"})
    monkeypatch.setattr(home_mod, "install_kind", lambda: "dev")
    monkeypatch.setenv("ORCH_REF", "develop")
    assert addons.build() == "development"


@pytest.mark.parametrize(("to", "ref"), [("development", "develop"), ("release", "main")])
def test_switch_installs_the_official_source_at_that_branch(monkeypatch, tmp_path, to, ref):
    # even from a folder install on a dev machine with ORCH_REPO / ORCH_REF set
    (tmp_path / "workspace").mkdir()
    _origin(monkeypatch, {"repo": str(tmp_path), "local": True})
    monkeypatch.setattr(home_mod, "install_kind", lambda: "dev")
    monkeypatch.setenv("ORCH_REPO", str(tmp_path))
    monkeypatch.setenv("ORCH_REF", "feat/x")
    addons.switch_to(to)
    assert addons.repo() == OFFICIAL and addons.ref() == ref
    assert addons.spec("workspace") == f"{OFFICIAL}/archive/{ref}.zip#subdirectory=workspace"
    assert addons.spec("workspace-addons/dashboard").startswith(f"{OFFICIAL}/archive/{ref}.zip#")
    assert addons.build() == to


def test_switch_takes_only_the_two_builds():
    with pytest.raises(Refused):
        addons.switch_to("feat/evil")
    assert addons._SWITCH_TO is None


def test_update_to_runs_the_normal_update(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.setattr(updateinfo, "announce_lines", lambda: [])

    def fake_update(root, project_only, after_install, **kw):
        seen["ref"], seen["project_only"] = addons.ref(), project_only
        return []

    monkeypatch.setattr(addons, "update", fake_update)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".orch").mkdir()
    assert not cli.main(["update", "--to", "development"])
    assert seen == {"ref": "develop", "project_only": False}


def test_update_to_refuses_the_inner_steps(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".orch").mkdir()
    assert cli.main(["update", "--to", "release", "--project-only"]) == 2
    assert "--to goes with a plain orch update" in capsys.readouterr().err and addons._SWITCH_TO is None


def test_version_line_says_development_build(monkeypatch):
    monkeypatch.setattr(updateinfo, "installed", lambda: {"sha": "a" * 40, "release": None})
    _origin(monkeypatch, {"repo": OFFICIAL, "ref": "develop"})
    assert updateinfo.current_label().endswith(" (development build)")
    _origin(monkeypatch, {"repo": OFFICIAL, "ref": "main"})
    monkeypatch.setattr(updateinfo, "installed", lambda: {"sha": "a" * 40, "release": 31})
    assert updateinfo.current_label() == "orch 31"
