"""`orch shot`: the browser always starts with the keychain-safe options; widths, files and cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from orch import cli_shot
from orch.errors import Refused


def test_command_has_keychain_safe_flags(tmp_path):
    cmd = cli_shot.command("/b", "/p", "http://x/", tmp_path / "a.png", 390, 844, 8)
    assert "--use-mock-keychain" in cmd and "--password-store=basic" in cmd
    assert "--window-size=390,844" in cmd and cmd[-1] == "http://x/"


def test_widths():
    assert cli_shot.parse_widths("1280, 390") == [1280, 390]
    for bad in ("", "abc", "50"):
        with pytest.raises(Refused):
            cli_shot.parse_widths(bad)


def test_target_url(tmp_path):
    f = tmp_path / "m.html"
    f.write_text("<p>x</p>")
    assert cli_shot.target_url(str(f)).startswith("file://")
    assert cli_shot.target_url("http://127.0.0.1:1/") == "http://127.0.0.1:1/"
    with pytest.raises(Refused):
        cli_shot.target_url(str(tmp_path / "none.html"))


def test_shoot_writes_files_and_removes_profile(tmp_path, monkeypatch):
    f = tmp_path / "m.html"
    f.write_text("<p>x</p>")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        shot = next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]
        Path(shot).write_bytes(b"png")

    monkeypatch.setattr(cli_shot, "find_browser", lambda: "/b")
    monkeypatch.setattr(cli_shot.subprocess, "run", fake_run)
    out = cli_shot.shoot(str(f), [1280, 390], tmp_path / "o", "n", None, 1)
    assert [p.name for p in out] == ["n-1280.png", "n-390.png"]
    profiles = {next(a for a in c if a.startswith("--user-data-dir=")) for c in seen}
    assert len(profiles) == 1 and not Path(profiles.pop().split("=", 1)[1]).exists()


def test_launch_link_only_on_first_width(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(cli_shot, "find_browser", lambda: "/b")

    def fake_run(cmd, **kw):
        urls.append(cmd[-1])
        Path(next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]).write_bytes(b"p")

    monkeypatch.setattr(cli_shot.subprocess, "run", fake_run)
    cli_shot.shoot("http://h/#launch=tok", [1280, 390], tmp_path, "n", None, 1)
    assert urls == ["http://h/#launch=tok", "http://h/"]
