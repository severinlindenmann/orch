"""Go back one release in one command (ORCH-550): `orch update --to <N>` installs release N of the current
source through the normal update path (which restarts the running add-on services) and holds it there until a
release newer than the one left is out."""

import json
import subprocess

import pytest

from orch import addons, cli, updateinfo
from orch import home as home_mod
from orch.errors import Refused

OFFICIAL = addons.DEFAULT_REPO
SHA = {n: f"{n:02d}" * 20 for n in (30, 31, 32, 33, 34)}


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(addons, "_SWITCH_TO", None)
    monkeypatch.setattr(addons, "_SWITCH_REPO", None)
    monkeypatch.setattr(home_mod, "install_kind", lambda: "normal")
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    h = tmp_path / "orchhome"
    h.mkdir()
    monkeypatch.setattr(addons, "home", lambda: h)
    state = {"origin": {"repo": OFFICIAL, "ref": "main"}, "line": [(n, SHA[n]) for n in (33, 32, 31)]}
    monkeypatch.setattr(addons, "_install_origin", lambda: state["origin"])
    monkeypatch.setattr(updateinfo, "release_line", lambda: state["line"])
    (h / "installed.json").write_text(json.dumps({"sha": SHA[33], "release": 33}))
    return state


def _installed_at(state, n):
    """What uv records after the go-back install: the source zip at that commit."""
    state["origin"] = {"repo": OFFICIAL, "ref": SHA[n]}
    addons._SWITCH_TO = addons._SWITCH_REPO = None


def test_go_back_installs_that_release_commit_of_the_same_source(_setup):
    addons.switch_to("32")
    assert addons.repo() == OFFICIAL and addons.ref() == SHA[32]
    assert addons.spec("workspace") == f"{OFFICIAL}/archive/{SHA[32]}.zip#subdirectory=workspace"
    assert addons.pinned() == {"release": 32, "sha": SHA[32], "left": 33, "repo": OFFICIAL}
    assert addons.build() == "release"
    _installed_at(_setup, 32)
    assert addons.pinned()["release"] == 32 and addons.build() == "release"  # held, still the release


def test_go_back_from_a_branch_source_stays_on_that_source(_setup):
    other = "https://github.com/someone/orch"
    _setup["origin"] = {"repo": other, "ref": "main"}
    addons.switch_to("31")
    assert addons.repo() == other and addons.ref() == SHA[31]


def test_an_unknown_release_is_refused_with_the_newest_ones(_setup):
    with pytest.raises(Refused, match="Release 7 was not found.*33, 32, 31"):
        addons.switch_to("7")
    assert addons._SWITCH_TO is None and addons.pinned() is None


def test_no_release_list_is_refused(_setup):
    _setup["line"] = None
    with pytest.raises(Refused, match="Could not read the list of releases"):
        addons.switch_to("32")


def test_a_folder_install_has_no_releases_to_go_back_to(_setup, tmp_path):
    (tmp_path / "src" / "workspace").mkdir(parents=True)
    _setup["origin"] = {"repo": str(tmp_path / "src"), "local": True}
    with pytest.raises(Refused, match="installed from a folder"):
        addons.switch_to("32")


@pytest.mark.parametrize("bad", ["0", "-1", "32a", "feat/x", "1.2.3", ""])
def test_only_builds_and_release_numbers_are_taken(bad):
    with pytest.raises(Refused):
        addons.switch_to(bad)
    assert addons._SWITCH_TO is None


def test_a_stale_hold_does_not_count(_setup):
    addons.switch_to("32")
    addons._SWITCH_TO = addons._SWITCH_REPO = None  # the install failed: the source is still main
    assert addons.pinned() is None and addons.leave_pin_if_newer() == ("free", None)


def test_going_back_twice_remembers_the_first_release_left(_setup):
    addons.switch_to("32")
    _installed_at(_setup, 32)
    (addons.home() / "installed.json").write_text(json.dumps({"sha": SHA[32], "release": 32}))
    addons.switch_to("31")
    assert addons.pinned()["left"] == 33


def test_held_update_stays_until_a_newer_release(_setup):
    addons.switch_to("32")
    _installed_at(_setup, 32)
    how, text = addons.leave_pin_if_newer()
    assert how == "stay" and "Staying on orch 32: you went back from 33" in text
    assert "orch update --to release" in text and addons.ref() == SHA[32]
    _setup["line"] = None
    assert addons.leave_pin_if_newer()[0] == "stay"
    _setup["line"] = [(34, SHA[34]), (33, SHA[33]), (32, SHA[32])]
    how, text = addons.leave_pin_if_newer()
    assert how == "leave" and "Release 34 is out" in text
    assert addons.ref() == "main" and addons.repo() == OFFICIAL and not addons._pin_path().exists()


def test_switching_to_a_build_ends_the_hold(_setup):
    addons.switch_to("32")
    _installed_at(_setup, 32)
    addons.switch_to("release")
    assert addons.ref() == "main" and addons.pinned() is None and not addons._pin_path().exists()


def test_update_info_offers_only_a_newer_release_while_held(_setup, monkeypatch):
    monkeypatch.setattr(updateinfo, "_fetch_messages", lambda *a: [])
    addons.switch_to("32")
    _installed_at(_setup, 32)
    (addons.home() / "installed.json").write_text(json.dumps({"sha": SHA[32], "release": 32}))
    got = updateinfo._compute()
    assert got["update_available"] is False and got["held"] == {"release": 32, "left": 33}
    _setup["line"] = [(34, SHA[34]), (33, SHA[33])]
    got = updateinfo._compute()
    assert got["update_available"] is True and got["newest"]["release"] == 34


def _cli(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.setattr(updateinfo, "announce_lines", lambda *a: [])

    def fake_update(root, project_only, after_install, **kw):
        seen.append(addons.ref())
        return []

    monkeypatch.setattr(addons, "update", fake_update)
    ws = tmp_path / "ws"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.chdir(ws)
    return seen


def test_update_to_a_number_runs_the_normal_update(_setup, monkeypatch, tmp_path):
    seen = _cli(monkeypatch, tmp_path)
    assert not cli.main(["update", "--to", "32"])
    assert seen == [SHA[32]]  # the same update path that restarts the running add-on services


def test_plain_update_while_held_does_nothing_and_says_why(_setup, monkeypatch, tmp_path, capsys):
    seen = _cli(monkeypatch, tmp_path)
    addons.switch_to("32")
    _installed_at(_setup, 32)
    assert not cli.main(["update"])
    assert seen == [] and "Staying on orch 32" in capsys.readouterr().out
    _setup["line"] = [(34, SHA[34]), (33, SHA[33])]
    assert not cli.main(["update"])
    assert seen == ["main"]


def _git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


def test_release_line_from_a_git_source(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@example.invalid")
    _git(src, "config", "user.name", "t")
    for msg in (
        "start",
        "Merge pull request #5 from x/release/part31-1101\n\nRelease 31",
        "Merge pull request #6 from x/feat/thing\n\nA thing",
        "Merge pull request #7 from x/release/part32-1102\n\nRelease 32",
    ):
        _git(src, "commit", "-q", "--allow-empty", "-m", msg)
    out = subprocess.run(
        ["git", "-C", str(src), "log", "--format=%H"], check=True, capture_output=True, text=True
    ).stdout.split()
    monkeypatch.undo()  # the real release_line
    monkeypatch.setattr(addons, "_SWITCH_TO", None)
    monkeypatch.setattr(addons, "_install_origin", lambda: {"repo": f"file://{src}", "ref": "main"})
    monkeypatch.setattr(home_mod, "install_kind", lambda: "normal")
    monkeypatch.delenv("ORCH_REPO", raising=False)
    monkeypatch.delenv("ORCH_REF", raising=False)
    assert updateinfo.release_line() == [(32, out[0]), (31, out[2])]


# ---- fix releases (ORCH-552): release/part33.1 is "33.1", after 33 and before 34


def test_fix_release_numbers_read_and_order():
    msgs = ["Merge pull request #9 from x/release/part33.1-1118\n\nRelease 33.1: fix"]
    assert updateinfo.release_in(msgs) == "33.1"
    assert updateinfo.release_in(["Merge pull request #8 from x/release/part33-1118"]) == 33
    assert sorted(["34", 33, "33.2", "33.1"], key=updateinfo.vkey) == [33, "33.1", "33.2", "34"]
    assert updateinfo.as_version("33.0") is None and updateinfo.as_version(True) is None
    assert updateinfo.label("33.1", SHA[33], "main") == "orch 33.1"


def test_a_fix_release_ends_the_hold_and_can_be_gone_back_to(_setup):
    addons.switch_to("32")
    _installed_at(_setup, 32)
    fix = "ab" * 20
    _setup["line"] = [("33.1", fix), (33, SHA[33]), (32, SHA[32])]
    how, text = addons.leave_pin_if_newer()
    assert how == "leave" and "Release 33.1 is out" in text
    addons._SWITCH_TO = addons._SWITCH_REPO = None
    _setup["origin"] = {"repo": OFFICIAL, "ref": "main"}
    (addons.home() / "installed.json").write_text(json.dumps({"sha": fix, "release": "33.1"}))
    assert updateinfo.installed()["release"] == "33.1"
    addons.switch_to("33")
    assert addons.ref() == SHA[33] and addons.pinned()["left"] == "33.1"
