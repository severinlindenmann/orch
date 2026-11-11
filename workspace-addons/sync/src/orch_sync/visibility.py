"""Unauthenticated visibility probe: network failures never imply privacy."""

import urllib.error
import urllib.parse
import urllib.request


def remote_visibility(url):
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
        return "unknown"
    address = "https://api.github.com/repos/" + "/".join(urllib.parse.quote(p, safe="") for p in parts)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(address, headers={"User-Agent": "orch-sync"}), timeout=5
        ) as response:
            return "public" if response.status == 200 else "unknown"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "unknown"  # 404 also cannot distinguish private from nonexistent.
