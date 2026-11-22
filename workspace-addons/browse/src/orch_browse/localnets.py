"""This computer's own addresses and the networks it is directly on (wall note section 4).

A local network with public addresses is still the local network: the filter refuses every address on a
network one of this computer's interfaces sits on. Read at broker start and again every minute (Wi-Fi
changes). macOS and Linux: getifaddrs through ctypes. Windows: Get-NetIPAddress (no admin needed).
Nothing found is not an error: the fixed ranges in netcheck still hold.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import ipaddress
import json
import socket
import subprocess
import sys

from .netcheck import NET


def _posix() -> list[NET]:
    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)

    class Sockaddr(ctypes.Structure):
        if sys.platform == "darwin":
            _fields_ = [
                ("sa_len", ctypes.c_uint8),
                ("sa_family", ctypes.c_uint8),
                ("sa_data", ctypes.c_char * 14),
            ]
        else:
            _fields_ = [("sa_family", ctypes.c_ushort), ("sa_data", ctypes.c_char * 14)]

    class Ifaddrs(ctypes.Structure):
        pass

    Ifaddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(Ifaddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.POINTER(Sockaddr)),
        ("ifa_netmask", ctypes.POINTER(Sockaddr)),
    ]

    def raw(sa_ptr, family: int) -> bytes | None:
        if not sa_ptr:
            return None
        base = ctypes.addressof(sa_ptr.contents)
        off, size = (4, 4) if family == socket.AF_INET else (8, 16)  # sockaddr_in6: family/port + flowinfo
        if sys.platform == "darwin":
            # macOS shortens netmask sockaddrs (sa_len < full size): the rest is zero, never read past it.
            have = max(0, min(size, sa_ptr.contents.sa_len - off))
            return ctypes.string_at(base + off, have) + b"\0" * (size - have)
        return ctypes.string_at(base + off, size)

    head = ctypes.POINTER(Ifaddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        return []
    out: list[NET] = []
    try:
        p = head
        while p:
            ifa = p.contents
            p = ifa.ifa_next
            if not ifa.ifa_addr:
                continue
            fam = ifa.ifa_addr.contents.sa_family
            if fam not in (socket.AF_INET, socket.AF_INET6):
                continue
            addr, mask = raw(ifa.ifa_addr, fam), raw(ifa.ifa_netmask, fam)
            if not addr:
                continue
            ip = ipaddress.ip_address(addr)
            bits = int.from_bytes(mask, "big").bit_count() if mask else ip.max_prefixlen
            out.append(ipaddress.ip_network(f"{ip}/{bits}", strict=False))
            out.append(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}"))
    finally:
        libc.freeifaddrs(head)
    return out


def _windows() -> list[NET]:
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-NetIPAddress | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress",
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, creationflags=0x08000000, check=False
        )
        rows = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    out: list[NET] = []
    for row in rows if isinstance(rows, list) else [rows]:
        try:
            ip = ipaddress.ip_address(str(row["IPAddress"]).split("%", 1)[0])
            out.append(ipaddress.ip_network(f"{ip}/{int(row['PrefixLength'])}", strict=False))
            out.append(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}"))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def local_networks() -> list[NET]:
    """Every network this computer is on, plus each own address as a single-address network. Default
    routes (a /0 from a point-to-point link) are dropped: they would refuse the whole internet."""
    try:
        nets = _windows() if sys.platform == "win32" else _posix()
    except (OSError, AttributeError, ValueError):
        nets = []
    seen: list[NET] = []
    for n in nets:
        if n.prefixlen == 0 or n in seen:
            continue
        seen.append(n)
    return seen
