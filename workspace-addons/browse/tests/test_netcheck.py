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
    # A /64 prefix (RFC 6052): 192.0.0.170 sits after the skipped u-octet.
    got = nc.nat64_prefixes(getaddrinfo=_gai("2001:db8:1:2:c0:0:aa00:0"))
    assert got == [ipaddress.ip_network("2001:db8:1:2::/64")]
    assert nc.blocked_ip(ipaddress.ip_address("2001:db8:1:2:7f:0:100:0"), (), got)  # 127.0.0.1 inside
    assert nc.blocked_ip(ipaddress.ip_address("2001:db8:1:2:5d:b8:d70e:0"), (), got) is None


def test_nat64_every_reading_counts():
    # Well-known local-use /48 with a local address in the low 32 bits: refused too.
    assert nc.blocked_ip(ipaddress.ip_address("64:ff9b:1:5db8:d70e::7f00:1"))
    # A discovered /64 prefix with 127.0.0.1 in the /96 position is refused as well.
    pref = [ipaddress.ip_network("2001:db8:1:2::/64")]
    assert nc.blocked_ip(ipaddress.ip_address("2001:db8:1:2:5d:b8:7f00:1"), (), pref)


# ---- O-21 (owner, 28 Nov): a pasted list, wildcards, a permanent workspace list ----
def test_a_pasted_list_is_read_as_it_would_be_stored():
    text = "*.20min.ch, https://www.SBB.ch/de/fahrplan\n20min.ch.\n  docs.python.org;10.0.0.1 localhost\nexample.com"
    read = nc.norm_many(text)
    assert read["sites"] == ["20min.ch", "www.sbb.ch", "docs.python.org", "example.com"]
    assert read["repeats"] == 1  # "20min.ch." says 20min.ch again
    assert {"entry": "*.20min.ch", "site": "20min.ch"} in read["changed"]
    assert {"entry": "https://www.SBB.ch/de/fahrplan", "site": "www.sbb.ch"} in read["changed"]
    assert not any(c["entry"] in ("docs.python.org", "example.com") for c in read["changed"])
    assert [r["entry"] for r in read["refused"]] == ["10.0.0.1", "localhost"]
    assert all(r["why"] for r in read["refused"])
    assert nc.norm_many(["  ", "", None]) == {"sites": [], "changed": [], "refused": [], "repeats": 0}


def test_a_wildcard_means_the_site_and_every_part_of_it():
    (site,) = nc.norm_many("*.20min.ch")["sites"]
    assert nc.site_allowed("20min.ch", [site]) and nc.site_allowed("www.20min.ch", [site])
    assert nc.site_allowed("a.b.20min.ch", [site]) and not nc.site_allowed("evil20min.ch", [site])
    assert not nc.site_allowed("20min.ch.evil.com", [site])


def test_a_thousand_sites_match_fast_and_exactly():
    import time

    sites = nc.norm_many("\n".join(f"*.site{i}.example.org" for i in range(1000)))["sites"]
    assert len(sites) == 1000
    start = time.perf_counter()
    for _ in range(200):
        assert nc.check_target("www.site999.example.org", 443, sites) is None
        assert "site list" in nc.check_target("www.site1000.example.org", 443, sites)
    assert time.perf_counter() - start < 2.0  # 400 checks against 1000 sites: far below a page's own time
