"""This computer's own networks: the Windows reading, odd rows, and the empty case."""

import ipaddress
import json
import subprocess
import sys
import types

import pytest

from orch_browse import localnets


def _ps(monkeypatch, stdout=None, exc=None):
    def fake(cmd, **kw):
        assert cmd[0] == "powershell" and "-NonInteractive" in cmd
        if exc:
            raise exc
        return types.SimpleNamespace(stdout=stdout, returncode=0)

    monkeypatch.setattr(localnets.subprocess, "run", fake)


def test_windows_reads_every_address_and_skips_odd_rows(monkeypatch):
    rows = [
        {"IPAddress": "192.168.1.23", "PrefixLength": 24},
        {"IPAddress": "fe80::1c2b:3d4e:5f60:7182%12", "PrefixLength": 64},  # scope id after %
        {"IPAddress": "127.0.0.1", "PrefixLength": 8},
        {"IPAddress": "not an address", "PrefixLength": 24},
        {"PrefixLength": 24},
        {"IPAddress": "10.0.0.5", "PrefixLength": None},
    ]
    _ps(monkeypatch, json.dumps(rows))
    got = {str(n) for n in localnets._windows()}
    assert got == {
        "192.168.1.0/24",
        "192.168.1.23/32",
        "fe80::/64",
        "fe80::1c2b:3d4e:5f60:7182/128",
        "127.0.0.0/8",
        "127.0.0.1/32",
    }


def test_windows_with_one_address_gets_one_object_not_a_list(monkeypatch):
    _ps(monkeypatch, json.dumps({"IPAddress": "172.16.4.2", "PrefixLength": 20}))
    assert [str(n) for n in localnets._windows()] == ["172.16.0.0/20", "172.16.4.2/32"]


@pytest.mark.parametrize(
    "stdout,exc",
    [
        ("", None),
        ("null", None),
        ("Get-NetIPAddress : not recognised", None),
        (None, FileNotFoundError("powershell")),
        (None, subprocess.TimeoutExpired("powershell", 20)),
    ],
)
def test_windows_reading_that_fails_is_empty_not_an_error(monkeypatch, stdout, exc):
    _ps(monkeypatch, stdout, exc)
    assert localnets._windows() == []


def test_default_routes_and_doubles_are_dropped(monkeypatch):
    n = ipaddress.ip_network
    monkeypatch.setattr(localnets.sys, "platform", "win32")
    monkeypatch.setattr(
        localnets,
        "_windows",
        lambda: [n("0.0.0.0/0"), n("10.1.0.0/16"), n("10.1.0.0/16"), n("::/0"), n("10.1.2.3/32")],
    )
    assert localnets.local_networks() == [n("10.1.0.0/16"), n("10.1.2.3/32")]


def test_a_reading_that_breaks_is_an_empty_list(monkeypatch):
    def broken():
        raise OSError("no libc")

    monkeypatch.setattr(localnets.sys, "platform", "linux")
    monkeypatch.setattr(localnets, "_posix", broken)
    assert localnets.local_networks() == []


@pytest.mark.skipif(sys.platform == "win32", reason="getifaddrs")
def test_this_computer_is_on_loopback():
    nets = localnets.local_networks()
    assert ipaddress.ip_network("127.0.0.1/32") in nets
    assert any(ipaddress.ip_address("127.0.0.1") in net and net.prefixlen < 32 for net in nets)
    assert all(net.prefixlen > 0 for net in nets)
