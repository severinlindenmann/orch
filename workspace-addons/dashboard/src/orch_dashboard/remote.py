"""Remote listening: the dashboard also answers other computers, without a proxy in front (opt-in, off by default).

The setting is the [dashboard] table of .orch/config.toml:

    [dashboard]
    listen = "0.0.0.0"          # the address to listen on for other computers (an IPv4 address; 0.0.0.0 = all)
    listen_port = 8791          # a fixed port, so a link or bookmark keeps working across restarts
    listen_name = "my-server"   # the name other computers use for this computer (in the printed sign-in link)

No `listen` = off. The loopback server stays as it was (its own port, the local links); the second socket shares
its sign-in. On that socket nothing counts as "this computer": every page and action needs the person's session,
which only a sign-in link gives (`orch start --print-launch-url`, a person only, single use). No pairing here.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

TABLE = "dashboard"


class Invalid(ValueError):
    """A setting that cannot be used; the text says why in plain words."""


def _config():
    """orch's settings file module; a stand-alone dashboard (no orch to import) has no remote listening."""
    try:
        from orch import config
    except ImportError:
        return None
    return config


def _address(v: object) -> str:
    try:
        return str(ipaddress.IPv4Address(str(v).strip()))
    except ValueError:
        raise Invalid(
            f"'{v}' is not an address this computer can listen on (an IPv4 address such as 0.0.0.0)."
        ) from None


def _port(v: object) -> int:
    if isinstance(v, bool) or not str(v).isdigit() or not 1024 <= int(v) <= 65535:
        raise Invalid(f"'{v}' is not a port between 1024 and 65535.")
    return int(v)


def _name(v: object) -> str:
    try:
        from orch_ui.origin import any_host_ok
    except ImportError:
        raise Invalid("This install cannot check a computer name.") from None

    name = str(v).strip().lower()
    if not name or ":" in name or not any_host_ok(name):
        raise Invalid(f"'{v}' is not a computer name (a name such as my-server.example or an address).")
    return name


def settings(root: Path) -> dict | None:
    """{"listen", "port", "name"} when remote listening is on and valid; None when off. A broken setting
    raises Invalid (the server then stays local and says why)."""
    config = _config()
    if config is None:
        return None
    table = config.read(root).get(TABLE)
    if not isinstance(table, dict) or table.get("listen") in (None, ""):
        return None
    listen = _address(table.get("listen"))
    if table.get("listen_port") is None:
        raise Invalid("Remote listening needs a fixed port: set listen_port.")
    port = _port(table.get("listen_port"))
    raw_name = table.get("listen_name")
    name = _name(raw_name) if raw_name not in (None, "") else (None if listen == "0.0.0.0" else listen)
    return {"listen": listen, "port": port, "name": name}


def url(s: dict) -> str | None:
    """The address other computers open, or None when no name is known (listening on all addresses)."""
    return f"http://{s['name']}:{s['port']}" if s.get("name") else None


def turn_on(root: Path, listen: str, port: object, name: str | None) -> dict:
    config = _config()
    if config is None:
        raise Invalid("This dashboard runs without orch; other computers cannot be let in from here.")

    s = {"listen": _address(listen), "port": _port(port), "name": _name(name) if name else None}
    if s["listen"].startswith("127."):
        raise Invalid("That address is this computer only; other computers cannot reach it.")
    config.set_key(root, TABLE, "listen", s["listen"])
    config.set_key(root, TABLE, "listen_port", s["port"])
    config.set_key(root, TABLE, "listen_name", s["name"])
    return settings(root) or s


def turn_off(root: Path) -> None:
    config = _config()
    if config is None:
        return
    for key in ("listen", "listen_port", "listen_name"):
        config.set_key(root, TABLE, key, None)
