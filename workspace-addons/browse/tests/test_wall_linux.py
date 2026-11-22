"""The Linux test world (wall/linux-world.sh): the real broker, filter and browser with NO test-only name map.

site.test sits on 203.0.113.10 behind a router; local.test, meta.test, lan.test, both.test and mapped6.test are
on the ticket's site list too, so only the filter's address rules stop them. Canaries on 127.0.0.1, ::1,
10.0.0.5, 192.168.1.5, 169.254.169.254 and fd00::5 and the attacker evil.test (203.0.113.66) log every hit into
$ORCH_WALL_DIR/hits.jsonl (wall/servers.py). The script runs this file twice: the leak run (only the browser's
proxy setting holds it back) and the hard run (nftables lets the browser's processes reach only the filter).
Skipped unless ORCH_BROWSE_LINUX_WORLD=1 (set only by the script).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path

import pytest

from orch_browse import cli, paths

pytestmark = pytest.mark.skipif(
    os.environ.get("ORCH_BROWSE_LINUX_WORLD") != "1", reason="runs inside wall/linux-world.sh only"
)

TID = "t_abc123"
SITES = ["site.test", "local.test", "meta.test", "lan.test", "both.test", "mapped6.test"]
LOCAL_NAMES = ("local.test", "meta.test", "lan.test", "both.test", "mapped6.test")
WORLD = Path(os.environ.get("ORCH_WALL_DIR", "/nonexistent"))
CGROUP = Path(os.environ.get("ORCH_WALL_CGROUP", "/nonexistent"))


def hits() -> list[dict]:
    try:
        return [json.loads(x) for x in (WORLD / "hits.jsonl").read_text().splitlines() if x.strip()]
    except OSError:
        return []


class Since:
    def __init__(self):
        self.start = len(hits())

    def new(self) -> list[dict]:
        return hits()[self.start :]

    def leaks(self) -> list[dict]:
        """Every hit that must never happen: a canary, the attacker, a non-read request to the site."""
        return [h for h in self.new() if h["who"] != "site" or h["method"] not in ("GET", "HEAD")]


def browser_procs() -> list[str]:
    try:
        return (CGROUP / "cgroup.procs").read_text().split()
    except OSError:
        return []


def net_log(ws: Path) -> list[dict]:
    f = paths.run_dir(ws, TID) / "net.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def run(capsys, *argv):
    code = cli.main([*argv, "--ticket", TID])
    return code, capsys.readouterr().out


@pytest.fixture
def world(ws, monkeypatch):
    monkeypatch.delenv("ORCH_BROWSE_TEST_MAP", raising=False)  # the real address checks, no exemption
    paths.save_sites(ws, TID, SITES)
    since = Since()
    yield since
    cli.main(["close", "--ticket", TID])


def _listeners_in_range() -> dict[int, int]:
    """{port: socket inode} of TCP listeners on 127.0.0.1 inside the port range the filter binds in."""
    lo, hi = (int(x) for x in Path("/proc/sys/net/ipv4/ip_local_port_range").read_text().split())
    out = {}
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        f = line.split()
        addr, port = f[1].split(":")
        if f[3] == "0A" and addr == "0100007F" and lo <= int(port, 16) <= hi:
            out[int(port, 16)] = int(f[9])
    return out


def _socket_inodes(pid: int) -> set[int]:
    found = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            found.add(int(target[8:-1]))
    return found


def test_the_world_has_no_shortcut():
    """No test-only name map; the names resolve as planned (both.test gives a public and a loopback answer)."""
    assert os.environ.get("ORCH_BROWSE_TEST_MAP") in (None, "")
    got = {a[4][0] for a in socket.getaddrinfo("both.test", 80, type=socket.SOCK_STREAM)}
    assert {"203.0.113.10", "127.0.0.1"} <= got, got
    assert Path(os.environ["ORCH_BROWSE_TEST_BROWSER"]).is_file()


def test_reads_the_site_and_the_hostile_page_leaks_nothing(world, ws, capsys):
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 0, out
    assert "Opening hours" in out and "--- page content" in out
    assert browser_procs(), "the browser does not run inside the walled cgroup"
    # The filter is the only listener in its port range on 127.0.0.1: the hard run's rule lets the browser reach
    # that range and nothing else, so it reaches exactly the filter.
    pid = int(paths.read_state(paths.run_dir(ws, TID))["pid"])
    listeners = _listeners_in_range()
    assert len(listeners) == 1 and set(listeners.values()) <= _socket_inodes(pid), listeners

    code, out = run(capsys, "go", "http://site.test/hostile")
    assert code == 0, out
    time.sleep(6)  # let the scripts, frames, worker, popup and WebRTC try
    code, out = run(capsys, "look")
    assert code == 0, out
    assert world.leaks() == [], world.leaks()
    assert any(h["path"] == "/hostile" for h in world.new())

    net = net_log(ws)
    assert all(n["verdict"] == "blocked" for n in net if n["host"] != "site.test"), net
    for name in LOCAL_NAMES:  # on the site list: only the address check stopped them
        mine = [n for n in net if n["host"] == name]
        assert mine and all(n["verdict"] == "blocked" and "points to" in n["why"] for n in mine), (name, mine)
    assert any(n["host"] == "evil.test" and "site list" in n["why"] for n in net)
    for spelled in ("127.0.0.1", "2130706433", "10.0.0.5", "169.254.169.254"):
        assert any(n["host"] == spelled and n["verdict"] == "blocked" for n in net), (spelled, net)


@pytest.mark.parametrize(
    "url",
    [
        "http://local.test/",
        "http://meta.test/latest/meta-data/",
        "http://lan.test/",
        "http://both.test/",
        "http://mapped6.test/",
        "https://local.test/",
        "http://site.test/r?to=http://10.0.0.5/",
        "http://site.test/r?to=http://meta.test/",
        "http://site.test/r?to=http://evil.test/",
        "http://site.test/nav",
    ],
)
def test_top_level_pages_and_redirects_reach_nothing_local(world, capsys, url):
    run(capsys, "open", "http://site.test/")
    _code, out = run(capsys, "go", url)
    time.sleep(1.5)
    _code, out2 = run(capsys, "look")
    assert world.leaks() == [], (url, world.leaks())
    assert "canary" not in out + out2 and "evil 203" not in out + out2


def test_damaged_site_list_opens_nothing(world, ws, capsys):
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 0, out
    paths.sites_file(ws, TID).write_text("{ not json", encoding="utf-8")
    seen = len(world.new())
    code, out = run(capsys, "go", "http://site.test/hostile")
    assert code == 2, out
    time.sleep(2)
    assert world.new()[seen:] == [], world.new()[seen:]  # not even the allowed site
    assert world.leaks() == []
    run(capsys, "close")
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 2 and "damaged" in out, out
    assert world.leaks() == []


def test_killed_broker_takes_the_browser_and_leaves_nothing(world, ws, capsys):
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 0, out
    run_dir = paths.run_dir(ws, TID)
    profile = Path((run_dir / "profile.path").read_text())
    pid = int(paths.read_state(run_dir)["pid"])
    assert profile.is_dir() and browser_procs()
    os.kill(pid, signal.SIGKILL)
    for _ in range(100):
        if not browser_procs():
            break
        time.sleep(0.2)
    assert browser_procs() == [], "the browser outlived its killed broker"
    assert world.leaks() == []
    code, out = run(capsys, "status")
    assert "No browser is open" in out, out
    code, out = run(capsys, "open", "http://site.test/")
    assert code == 0, out
    assert not profile.exists(), "the killed broker's temp folder was not cleaned up"
    assert world.leaks() == []
