"""Address and site checks of the browser's network filter (ORCH-1492, wall note ORCH-1156 section 4).

Pure functions, no network: the filter (proxy.py) calls them for every connection the browser asks for.
A name or address is refused when it points to this computer, the local network, cloud metadata, a carrier
NAT, a multicast/broadcast/reserved range, or hides one of those inside an IPv6 form (IPv4-mapped,
IPv4-compatible, 6to4, Teredo, NAT64). Tricky IPv4 spellings (decimal, hex, octal, short forms) are read
the way a browser or the C library reads them, so "2130706433" or "0x7f.1" is 127.0.0.1 here too.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Iterable

IP = ipaddress.IPv4Address | ipaddress.IPv6Address
NET = ipaddress.IPv4Network | ipaddress.IPv6Network

# Ranges that are never the public internet. Documentation ranges (192.0.2/24, 198.51.100/24, 203.0.113/24,
# 2001:db8::/32) are NOT here: they never route on the internet, and the Linux test world uses them as its
# "public" sites. Python's is_private counts them as private, so it is not used.
BLOCKED_V4 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",  # this network, 0.0.0.0
        "10.0.0.0/8",
        "100.64.0.0/10",  # carrier NAT (also Alibaba metadata 100.100.100.200)
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local, cloud metadata 169.254.169.254 / 169.254.170.2
        "172.16.0.0/12",
        "192.0.0.0/24",  # IETF protocol assignments (incl. 192.0.0.192 Oracle metadata)
        "192.88.99.0/24",  # 6to4 relay anycast
        "192.168.0.0/16",
        "198.18.0.0/15",  # benchmarking, used inside networks
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved, incl. 255.255.255.255
    )
)
BLOCKED_V6 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::/128",
        "::1/128",
        "::/96",  # IPv4-compatible (old), checked again as IPv4 below
        "100::/64",  # discard
        "fc00::/7",  # unique local, incl. fd00:ec2::254 (AWS metadata)
        "fe80::/10",  # link-local
        "fec0::/10",  # old site-local
        "ff00::/8",  # multicast
    )
)
NAT64_WELL_KNOWN = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))

# Cloud metadata and local names, refused by name before any lookup.
BLOCKED_NAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.azure.com",
        "metadata.azure.internal",
        "instance-data",
        "instance-data.ec2.internal",
        "metadata.tencentyun.com",
        "metadata.platformequinix.com",
        "ipv4only.arpa",
    }
)
BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
    ".lan",
    ".intranet",
    ".corp",
    ".private",
    ".in-addr.arpa",
    ".ip6.arpa",
)

ALLOWED_PORTS = frozenset({80, 443})
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def literal_ip(host: str) -> IP | None:
    """The address a host string names when it is an address literal (any spelling a browser accepts), else
    None. '[::1]', '::ffff:127.0.0.1', '2130706433', '0x7f000001', '0177.0.0.1', '127.1' all give an address."""
    h = (host or "").strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    h = h.split("%", 1)[0]  # IPv6 zone id
    h = h.rstrip(".")
    if not h:
        return None
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass
    if ":" in h:
        return None
    # The browser's URL parser reads IPv4 the old way: up to 4 parts, each decimal, 0x hex or 0 octal.
    parts = h.split(".")
    if not 1 <= len(parts) <= 4 or not all(re.fullmatch(r"0x[0-9a-f]*|[0-9]+", p) for p in parts):
        return None
    try:
        nums = [
            int(p, 16) if p.startswith("0x") else int(p, 8) if len(p) > 1 and p[0] == "0" else int(p)
            for p in parts
        ]
    except ValueError:
        return None  # e.g. '08' is not octal: a browser refuses it as an address
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (5 - len(nums)):
        return None
    value = 0
    for n in head:
        value = value * 256 + n
    value = value * 256 ** (5 - len(nums)) + last
    return ipaddress.IPv4Address(value)


def embedded_v4(ip: ipaddress.IPv6Address, nat64: Iterable[NET] = ()) -> list[ipaddress.IPv4Address]:
    """Every IPv4 address an IPv6 address may carry (mapped, compatible, 6to4, Teredo client, NAT64). Inside a
    NAT64 range each reading counts (the prefix's own and the low 32 bits): any local one refuses."""
    out: list[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped:
        out.append(ip.ipv4_mapped)
    if ip.sixtofour:
        out.append(ip.sixtofour)
    if ip.teredo:
        out.append(ip.teredo[1])
    for net in (*nat64, *NAT64_WELL_KNOWN):
        if ip in net:
            out += [rfc6052_v4(ip, net.prefixlen), rfc6052_v4(ip, 96)]
    if int(ip) >> 32 == 0 and int(ip) > 1:  # ::a.b.c.d (IPv4-compatible)
        out.append(ipaddress.IPv4Address(int(ip)))
    return out


RFC6052_LENGTHS = (32, 40, 48, 56, 64, 96)


def rfc6052_v4(ip: ipaddress.IPv6Address, plen: int) -> ipaddress.IPv4Address:
    """The IPv4 address inside a NAT64 address with an RFC 6052 prefix of plen bits (bits 64-71 are skipped)."""
    b = ip.packed
    if plen == 96:
        v4 = b[12:16]
    else:
        start = plen // 8
        octets = [i for i in range(start, 16) if i != 8][:4]
        v4 = bytes(b[i] for i in octets)
    return ipaddress.IPv4Address(v4)


def blocked_ip(ip: IP, local_nets: Iterable[NET] = (), nat64: Iterable[NET] = ()) -> str | None:
    """Why the browser may not connect to this address, in plain words; None when it may."""
    local_nets = tuple(local_nets)
    if isinstance(ip, ipaddress.IPv6Address):
        for inner in embedded_v4(ip, nat64):
            why = blocked_ip(inner, local_nets, ())
            if why:
                return f"{why} (inside {ip})"
        if any(ip in n for n in BLOCKED_V6):
            return f"{ip} is this computer or the local network"
    else:
        if any(ip in n for n in BLOCKED_V4):
            return f"{ip} is this computer, the local network or a cloud metadata address"
    for n in local_nets:
        if ip.version == n.version and ip in n:
            return f"{ip} is on a network this computer is directly on"
    return None


def blocked_name(host: str) -> str | None:
    """Why a host name is refused before any lookup (local and metadata names, malformed names); None if not."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return "no site name"
    if literal_ip(h) is not None:
        return None
    if h in BLOCKED_NAMES or h.endswith(BLOCKED_SUFFIXES):
        return f"{h} is a local or cloud metadata name"
    if "." not in h:
        return f"{h} is a local name (no dot)"
    if len(h) > 253 or not all(_LABEL.match(lbl) for lbl in h.split(".")):
        return f"{h} is not a valid site name"
    return None


def norm_site(site: str) -> str:
    """A site list entry as stored: lower case, no scheme, path, port or trailing dot. Refuses addresses and
    local names (a site list never opens the local network)."""
    s = (site or "").strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        raise ValueError("a site name has no user part")
    s = s.removeprefix("*.")
    if s.count(":") == 1:
        s = s.split(":", 1)[0]
    s = s.rstrip(".")
    if literal_ip(s) is not None:
        raise ValueError(f"{site} is an address; give the site's name")
    why = blocked_name(s)
    if why:
        raise ValueError(why)
    return s


def site_allowed(host: str, sites: Iterable[str]) -> bool:
    """True when host is a listed site or a part of one (www.example.com for example.com)."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or literal_ip(h) is not None:
        return False
    return any(h == s or h.endswith("." + s) for s in sites)


def check_target(host: str, port: int, sites: Iterable[str]) -> str | None:
    """The checks that need no lookup, in order. None = go on and look the name up."""
    if port not in ALLOWED_PORTS:
        return f"port {port} is not a web port"
    why = blocked_name(host)
    if why:
        return why
    if literal_ip(host) is not None:
        return "the browser opens sites by name only, not by address"
    if not site_allowed(host, sites):
        return f"{host.lower().rstrip('.')} is not on this ticket's site list"
    return None


def resolve_checked(
    host: str,
    port: int,
    local_nets: Iterable[NET] = (),
    nat64: Iterable[NET] = (),
    getaddrinfo=socket.getaddrinfo,
) -> tuple[str | None, str]:
    """Look the name up once and check EVERY answer. Returns (address to connect to, why). The caller
    connects to exactly that address, so a name that changes its answer between two lookups cannot slip
    through. Any blocked answer refuses the whole name (a name with one local answer is a trick)."""
    try:
        infos = getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return None, f"{host} does not resolve"
    addrs: list[str] = []
    for *_, sa in infos:
        try:
            ip = ipaddress.ip_address(str(sa[0]).split("%", 1)[0])
        except ValueError:
            return None, f"{host} gave an answer that is not an address"
        why = blocked_ip(ip, local_nets, nat64)
        if why:
            return None, f"{host} points to {why}"
        addrs.append(str(ip))
    if not addrs:
        return None, f"{host} does not resolve"
    v4 = [a for a in addrs if ":" not in a]
    return (v4 or addrs)[0], "allowed"


def nat64_prefixes(getaddrinfo=socket.getaddrinfo) -> list[NET]:
    """The network's own NAT64 prefixes (RFC 7050: the AAAA answers for ipv4only.arpa). The prefix length is
    found from where the well-known 192.0.0.170/171 sits in the answer (RFC 6052: 32 to 96 bits)."""
    out: list[NET] = []
    try:
        infos = getaddrinfo("ipv4only.arpa", 80, family=socket.AF_INET6, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return out
    known = {ipaddress.IPv4Address("192.0.0.170"), ipaddress.IPv4Address("192.0.0.171")}
    for *_, sa in infos:
        try:
            ip = ipaddress.IPv6Address(str(sa[0]).split("%", 1)[0])
        except ValueError:
            continue
        if ip.ipv4_mapped:
            continue
        # Accept a length only when it is the one reading that fits (u-octet zero below /96); an unclear
        # answer adds every fitting length, so more is refused, never less.
        for plen in RFC6052_LENGTHS:
            if rfc6052_v4(ip, plen) in known and (plen == 96 or ip.packed[8] == 0):
                net = ipaddress.ip_network(f"{ip}/{plen}", strict=False)
                if net not in out:
                    out.append(net)
    return out
