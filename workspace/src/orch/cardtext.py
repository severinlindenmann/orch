"""Short plain text for cards and lists: one untrusted fragment, a path tail, a server address."""

from __future__ import annotations

from orch.errors import Refused

PART_MAX = 120


def part(text) -> str:
    """One untrusted fragment (a title, a question, a task, a path) for the card: one line, quotes normalised
    so it cannot fake the quotes around it, at most 120 characters with an ellipsis. The page shows it as
    plain text in its own element; `{value}` and the like stay literal."""
    t = " ".join(str(text if text is not None else "").split())
    t = t.translate({ord(c): "'" for c in '"\u201c\u201d\u201e\u2033\u00ab\u00bb'})
    return t[:PART_MAX] + "\u2026" if len(t) > PART_MAX else t


def tail(text, n: int = 60) -> str:
    """A long path for the sentence: its END ("\u2026/real/folder"), never its head. The full value is
    always in the card's exact block."""
    t = " ".join(str(text if text is not None else "").split())
    return t if len(t) <= n else "\u2026" + t[-n:]


NO_USERINFO = "This address contains a name or password. Use just the server address."


def server_address(url: str) -> str:
    """hostname[:port] of a server URL, built from urlsplit; a URL with userinfo (user@ / user:pass@) is
    refused, so what the card shows is what is connected to."""
    from urllib.parse import urlsplit

    try:
        u = urlsplit(url.strip())
        host, port = u.hostname, u.port
    except ValueError:
        raise Refused("That is not a server address.") from None
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise Refused(NO_USERINFO)
    if not host:
        raise Refused("That is not a server address.")
    return f"{host}:{port}" if port else host
