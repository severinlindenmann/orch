"""macOS folders a background job may not use (report r-1119-1255-ws-6): the check and the doctor row."""

import json
from pathlib import Path

import pytest

from orch import addons, cli_leave, macfolders


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for rel in (
        "Documents/proj",
        "Desktop",
        "Downloads",
        "Library/Mobile Documents/com~apple~CloudDocs/x",
        "Library/CloudStorage/OneDrive/y",
        "code/proj",
    ):
        (h / rel).mkdir(parents=True)
    return h


@pytest.mark.parametrize(
    "rel, word",
    [
        ("Documents/proj", "Documents"),
        ("Desktop", "Desktop"),
        ("Downloads", "Downloads"),
        ("Library/Mobile Documents/com~apple~CloudDocs/x", "iCloud Drive"),
        ("Library/CloudStorage/OneDrive/y", "a cloud storage folder"),
        ("code/proj", None),
        ("Documentsfoo", None),  # a name that only starts the same is not inside
    ],
)
def test_protected_folders_on_a_mac(home, rel, word):
    assert macfolders.protected(home / rel, home, "darwin") == word


def test_never_on_other_computers(home):
    assert macfolders.protected(home / "Documents/proj", home, "linux") is None
    assert macfolders.protected(home / "Documents/proj", home, "win32") is None


def test_links_are_followed(home):
    (home / "code" / "into-docs").symlink_to(home / "Documents" / "proj", target_is_directory=True)
    (home / "Documents" / "out").symlink_to(home / "code" / "proj", target_is_directory=True)
    assert macfolders.protected(home / "code" / "into-docs", home, "darwin") == "Documents"
    assert macfolders.protected(home / "Documents" / "out", home, "darwin") is None


def test_first_protected_and_shown(home):
    hit = macfolders.first_protected([None, home / "code/proj", home / "Desktop"], home, "darwin")
    assert hit == (home / "Desktop", "Desktop")
    assert macfolders.shown(home / "Desktop" / "x", home) == "~/Desktop/x"
    assert macfolders.shown(home.parent, home) == str(home.parent)


def test_doctor_row_only_with_services_on(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")
    assert macfolders.doctor_row(home / "Documents/proj", services_on=False) is None
    assert macfolders.doctor_row(home / "code/proj", services_on=True) is None
    row = macfolders.doctor_row(home / "Documents/proj", services_on=True)
    assert row["ok"] is False and "in Documents" in row["fact"] and "~/code" in row["next"]


def test_orch_doctor_names_it(proj, run, monkeypatch, tmp_path):
    assert run("init")[0] == 0
    home = tmp_path / "fakehome"
    home.mkdir()
    (home / "Documents").symlink_to(proj.parent, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")
    monkeypatch.setattr(addons, "active", lambda root: {"services": {}})
    res = cli_leave.doctor(proj)
    rows = [r for r in res["checks"] if r["name"] == "services folder"]
    assert len(rows) == 1 and rows[0]["ok"] is False, json.dumps(res["checks"])
    monkeypatch.setattr(addons, "active", lambda root: {})
    assert not [r for r in cli_leave.doctor(proj)["checks"] if r["name"] == "services folder"]


@pytest.fixture
def volumes(tmp_path, home, monkeypatch):
    """A /Volumes folder with one external disk; the home folder is on the Mac's own disk."""
    vol = tmp_path / "Volumes"
    (vol / "2TB" / "Management").mkdir(parents=True)
    (vol / "Macintosh HD").symlink_to(home, target_is_directory=True)  # the start disk is a link, as on a Mac
    monkeypatch.setattr(macfolders, "VOLUMES", vol)
    own = macfolders._device(home)
    monkeypatch.setattr(
        macfolders, "_device", lambda p: own + 1 if Path(p).resolve().is_relative_to(vol.resolve()) else own
    )
    return vol


def test_external_disk_on_a_mac(home, volumes):
    # report r-1120-0610-services: launchd cannot start a job or open its log on /Volumes/<disk>
    assert macfolders.external_disk(volumes / "2TB" / "Management", home, "darwin") is True
    gone = volumes / "2TB" / "gone"  # an unmounted disk cannot be read: still external
    assert macfolders.external_disk(gone, home, "darwin") is True
    assert macfolders.external_disk(volumes / "Macintosh HD" / "code", home, "darwin") is False
    assert macfolders.external_disk(home / "code/proj", home, "darwin") is False
    assert macfolders.external_disk(volumes / "2TB" / "Management", home, "linux") is False
    assert macfolders.protected(volumes / "2TB" / "Management", home, "darwin") is None  # never refused


def test_doctor_notes_an_external_disk_without_a_problem(home, volumes, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")
    assert macfolders.doctor_row(volumes / "2TB" / "Management", services_on=False) is None
    row = macfolders.doctor_row(volumes / "2TB" / "Management", services_on=True)
    assert row["ok"] is True and "external disk" in row["fact"] and "home folder" in row["fact"]
