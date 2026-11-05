"""The cheap Host/Origin check for local web servers (dashboard, Focus).

Why: a page on any website can make the browser send requests to http://127.0.0.1:<port> (CSRF), and a DNS
name that resolves to 127.0.0.1 (DNS rebinding) reaches the same server with a foreign Host header.
The check is a few string compares:

- Host must be `127.0.0.1:<port>`, `localhost:<port>` or `<name>:<port>` for a name in `extra_hosts`, with a
  plain decimal port (1-65535, no leading zero). The port is not compared with the server's: only the name
  matters, so a dev proxy or a second server port works. Anything else is refused: another name, no port, a
  trailing dot, `[::1]` (the servers bind 127.0.0.1 only), userinfo tricks, `<name>.evil.example`.
  `extra_hosts` comes from an explicit server setting, never from the request.
- A request that changes something (not GET/HEAD/OPTIONS) with an Origin header must have exactly
  `http://<Host as sent>`. `Origin: null` and every other origin is refused. Without an Origin header (curl,
  agents, tests) it passes unless the browser says it is cross-site (`Sec-Fetch-Site` other than
  same-origin/none).
- GET/HEAD/OPTIONS of pages (`api=False`) pass, so links from mail or GitHub open. For `api=True` reads the
  same `Sec-Fetch-Site` rule applies: a cross-site page cannot read JSON from the local server.
- Duplicate Host, Origin or Sec-Fetch-Site headers are refused (`get_all` on http.server messages, lists in
  a mapping).

Servers must never send `Access-Control-Allow-*` headers: they would undo the fence.
No cookies, no tokens: this is not authentication, only the browser-side fence. Returns None when the request
is fine, otherwise a short plain message for a 403.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SAME_SITE = {"same-origin", "none"}
_PORT = re.compile(r"[1-9][0-9]{0,4}")
_REFUSED_SITE = "This request came from another website and was refused."


def _values(headers, name: str) -> list[str]:
    if hasattr(headers, "get_all"):
        return list(headers.get_all(name) or [])
    for k, v in headers.items():
        if k.lower() == name:
            return [v] if isinstance(v, str) else list(v)
    return []


def host_ok(host: str, extra_hosts: Sequence[str] = ()) -> bool:
    name, sep, port = host.rpartition(":")
    if not sep or not _PORT.fullmatch(port) or int(port) > 65535:
        return False
    return name in ("127.0.0.1", "localhost", *extra_hosts)


def check_request(
    method: str, headers: Mapping[str, str], port: int, *, api: bool = False, extra_hosts: Sequence[str] = ()
) -> str | None:
    """`port` is the server's own port, kept for the call shape; the check looks at the host name only."""
    one: dict[str, str | None] = {}
    for name in ("host", "origin", "sec-fetch-site"):
        vals = _values(headers, name)
        if len(vals) > 1:
            return "This request was refused (repeated header)."
        one[name] = vals[0] if vals else None
    host = one["host"]
    if host is None or not host_ok(host, extra_hosts):
        return f"This address is not allowed. Open orch at http://127.0.0.1:{port}"
    safe = method.upper() in SAFE_METHODS
    if safe and not api:
        return None
    origin, site = one["origin"], one["sec-fetch-site"]
    if not safe and origin is not None:
        return None if origin == f"http://{host}" else _REFUSED_SITE
    if site is not None and site not in _SAME_SITE:
        return _REFUSED_SITE
    return None
