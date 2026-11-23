"""Leak run on this computer: the real broker, browser and filter against the hostile test world (world.py).
Runs on macOS, Windows and Linux wherever the pinned browser is downloaded; the Linux CI job adds the
network-namespace runs (wall/linux-world.sh)."""

import json
import time

import pytest
from conftest import browser_ready
from world import World

from orch_browse import cli, paths

pytestmark = pytest.mark.skipif(not browser_ready(), reason="the pinned browser is not downloaded")


@pytest.fixture
def world(ws, monkeypatch):
    w = World()
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_BROWSE_TEST_MAP", w.env_map())
    paths.save_sites(ws, "t_abc123", ["site.test"])
    yield w
    cli.main(["close", "--ticket", "t_abc123"])
    w.stop()


def run(capsys, *argv):
    code = cli.main([*argv, "--ticket", "t_abc123"])
    return code, capsys.readouterr().out


def test_reads_the_allowed_site_and_nothing_leaks(world, ws, capsys):
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 0, out
    assert "Opening hours" in out and "--- page content" in out
    code, out = run(capsys, "go", "http://site.test/hostile")
    assert code == 0, out
    time.sleep(3)  # let the page's scripts, worker and WebRTC try
    code, out = run(capsys, "look")
    assert code == 0
    assert world.leaks() == [], world.leaks()
    net = [json.loads(x) for x in (paths.run_dir(ws, "t_abc123") / "net.jsonl").read_text().splitlines()]
    assert all(n["verdict"] == "blocked" for n in net if n["host"] != "site.test"), net
    assert any(n["host"] == "evil.test" and n["verdict"] == "blocked" for n in net)


def test_redirect_and_clicks_cannot_leave_the_list(world, ws, capsys):
    run(capsys, "open", "http://site.test/")
    run(capsys, "go", "http://site.test/redir")
    assert world.log.of("evil") == []
    run(capsys, "go", "http://site.test/hostile")
    _code, out = run(capsys, "look")
    num = next(line.split("]")[0].strip("[") for line in out.splitlines() if 'button "Send"' in line)
    run(capsys, "click", num)
    time.sleep(1)
    assert world.leaks() == [], world.leaks()


def test_refuses_sites_off_the_list_addresses_and_other_ports(world, capsys):
    run(capsys, "open", "http://site.test/")
    for url in ("http://evil.test/", "http://127.0.0.1/", "http://site.test:8080/", "file:///etc/passwd"):
        code, out = run(capsys, "go", url)
        assert code == 2, (url, out)
    assert world.leaks() == []


def test_empty_site_list_opens_nothing(ws, capsys):
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 2 and "site list is empty" in out


def test_close_removes_the_temp_profile(world, ws, capsys):
    run(capsys, "open", "http://site.test/")
    run_dir = paths.run_dir(ws, "t_abc123")
    from pathlib import Path

    profile = Path((run_dir / "profile.path").read_text())
    assert profile.is_dir()
    code, out = run(capsys, "close")
    assert code == 0
    for _ in range(50):
        if not profile.exists():
            break
        time.sleep(0.1)
    assert not profile.exists()
    code, out = run(capsys, "status")
    assert "No browser is open" in out


def test_closes_when_idle(world, ws, capsys, monkeypatch):
    monkeypatch.setenv("ORCH_BROWSE_IDLE_SECONDS", "2")
    run(capsys, "open", "http://site.test/")
    for _ in range(60):
        if paths.read_state(paths.run_dir(ws, "t_abc123")).get("state") == "ended":
            break
        time.sleep(0.25)
    st = paths.read_state(paths.run_dir(ws, "t_abc123"))
    assert st.get("state") == "ended" and "15 minutes" in st.get("why", "")
    code, _out = run(capsys, "look")
    assert code == 2
