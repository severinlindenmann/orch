import ipaddress
import socket

import pytest

from orch_browse import netcheck as nc


@pytest.mark.parametrize(
    "host,ip",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("0x7f000001", "127.0.0.1"),
        ("0x7F.0.0.1", "127.0.0.1"),
        ("0177.0.0.1", "127.0.0.1"),
        ("127.1", "127.0.0.1"),
        ("127.0.1", "127.0.0.1"),
        ("0", "0.0.0.0"),
        ("[::1]", "::1"),
        ("[::ffff:127.0.0.1]", "::ffff:7f00:1"),
        ("fe80::1%en0", "fe80::1"),
        ("169.254.169.254.", "169.254.169.254"),
        ("0xa9.0xfe.0xa9.0xfe", "169.254.169.254"),
    ],
)
def test_literal_spellings(host, ip):
    assert nc.literal_ip(host) == ipaddress.ip_address(ip)


@pytest.mark.parametrize("host", ["example.com", "08.1.1.1", "1.2.3.4.5", "256.1.1.1", "0x", "a.b", ""])
def test_not_literals(host):
    assert nc.literal_ip(host) is None


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.255.0.9",
        "0.0.0.0",
        "10.0.0.5",
        "172.16.3.4",
        "172.31.255.255",
        "192.168.1.5",
        "169.254.169.254",
        "169.254.170.2",
        "100.64.0.1",
        "100.100.100.200",
        "192.0.0.192",
        "224.0.0.251",
        "255.255.255.255",
        "198.18.0.1",
        "::1",
        "::",
        "fd00::5",
        "fd00:ec2::254",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::127.0.0.1",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::c0a8:105",
        "2002:7f00:1::",
        "2001:0:4136:e378:8000:63bf:80ff:fffe",
    ],
)
def test_blocked_addresses(ip):
    assert nc.blocked_ip(ipaddress.ip_address(ip)), ip


@pytest.mark.parametrize(
    "ip", ["93.184.215.14", "203.0.113.10", "2606:4700::6810:84e5", "64:ff9b::5db8:d70e", "8.8.8.8"]
)
def test_public_addresses_pass(ip):
    assert nc.blocked_ip(ipaddress.ip_address(ip)) is None


def test_own_networks_and_nat64_prefix():
    lan = [ipaddress.ip_network("81.6.0.0/24")]
    assert nc.blocked_ip(ipaddress.ip_address("81.6.0.20"), lan)
    assert nc.blocked_ip(ipaddress.ip_address("81.6.1.20"), lan) is None
    pref = [ipaddress.ip_network("2001:db8:64::/96")]
    assert nc.blocked_ip(ipaddress.ip_address("2001:db8:64::7f00:1"), (), pref)
    assert nc.blocked_ip(ipaddress.ip_address("2001:db8:64::7f00:1")) is None


@pytest.mark.parametrize(
    "name",
    [
        "localhost",
        "x.localhost",
        "metadata.google.internal",
        "printer.local",
        "nas.home.arpa",
        "router",
        "instance-data",
        "metadata.azure.com",
        "1.0.0.127.in-addr.arpa",
        "bad_name.com",
        "-a.com",
    ],
)
def test_blocked_names(name):
    assert nc.blocked_name(name)


def test_site_list_rules():
    sites = ["example.com"]
    assert nc.site_allowed("example.com", sites)
    assert nc.site_allowed("www.example.com", sites)
    assert nc.site_allowed("WWW.Example.com.", sites)
    assert not nc.site_allowed("evilexample.com", sites)
    assert not nc.site_allowed("example.com.evil.test", sites)
    assert not nc.site_allowed("93.184.215.14", sites)
    assert nc.check_target("example.com", 8080, sites) == "port 8080 is not a web port"
    assert "site list" in nc.check_target("other.org", 443, sites)
    assert "by name only" in nc.check_target("93.184.215.14", 443, ["93.184.215.14"])
    assert nc.check_target("www.example.com", 443, sites) is None


@pytest.mark.parametrize(
    "raw,want",
    [
        ("https://Example.com/path?x", "example.com"),
        ("*.example.com", "example.com"),
        ("example.com:443", "example.com"),
        ("example.com.", "example.com"),
    ],
)
def test_norm_site(raw, want):
    assert nc.norm_site(raw) == want


@pytest.mark.parametrize(
    "raw", ["127.0.0.1", "localhost", "user@example.com", "[::1]", "printer.local", "router"]
)
def test_norm_site_refuses_local(raw):
    with pytest.raises(ValueError):
        nc.norm_site(raw)


def _gai(*answers):
    def gai(host, port, **kw):
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in answers
        ]

    return gai


def test_every_answer_is_checked_and_the_checked_one_is_used():
    assert nc.resolve_checked("ok.test", 443, getaddrinfo=_gai("93.184.215.14")) == (
        "93.184.215.14",
        "allowed",
    )
    addr, why = nc.resolve_checked("rebind.test", 443, getaddrinfo=_gai("93.184.215.14", "127.0.0.1"))
    assert addr is None and "127.0.0.1" in why
    addr, why = nc.resolve_checked("six.test", 443, getaddrinfo=_gai("::ffff:192.168.1.1"))
    assert addr is None
    assert nc.resolve_checked("none.test", 443, getaddrinfo=_gai())[0] is None


def test_nat64_discovery():
    got = nc.nat64_prefixes(getaddrinfo=_gai("2001:db8:64::c000:aa", "2001:db8:64::c000:ab"))
    assert got == [ipaddress.ip_network("2001:db8:64::/96")]
