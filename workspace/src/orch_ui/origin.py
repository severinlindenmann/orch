"""The cheap Host/Origin check for local web servers (dashboard, Focus).

Why: a page on any website can make the browser send requests to http://127.0.0.1:<port> (CSRF), and a DNS
name that resolves to 127.0.0.1 (DNS rebinding) reaches the same server with a foreign Host header.
The check is two string compares:

- Host must be exactly `127.0.0.1:<port>` or `localhost:<port>` for the port the server listens on.
  Anything else is refused: another name, no port, a trailing dot, `[::1]` (the servers bind 127.0.0.1 only),
  userinfo tricks.
- A request that changes something (not GET/HEAD/OPTIONS) with an Origin header must have exactly `http://<Host>`.
  `Origin: null` and every other origin is refused. Without an Origin header (curl, agents, tests) it passes
  unless the browser says it is cross-site (`Sec-Fetch-Site` other than same-origin/none).

No cookies, no tokens: this is not authentication, only the browser-side fence. Returns None when the request
is fine, otherwise a short plain message for a 403.
"""

from __future__ import annotations

from collections.abc import Mapping

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SAME_SITE = {"same-origin", "none"}


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def check_request(method: str, headers: Mapping[str, str], port: int) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    host = h.get("host")
    if host is None or host not in allowed_hosts(port):
        return f"This address is not allowed. Open orch at http://127.0.0.1:{port}"
    if method.upper() in SAFE_METHODS:
        return None
    origin = h.get("origin")
    if origin is not None:
        if origin != f"http://{host}":
            return "This request came from another website and was refused."
        return None
    site = h.get("sec-fetch-site")
    if site is not None and site not in _SAME_SITE:
        return "This request came from another website and was refused."
    return None
