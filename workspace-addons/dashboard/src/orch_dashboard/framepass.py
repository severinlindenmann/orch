"""Frame passes (ORCH-186): the add-on pages orch ships run in a sandboxed frame (an opaque origin), so a script in
one can never read the dashboard's page secret or reach into the dashboard page. The dashboard page (signed in)
asks for a pass for one add-on and hands it to that frame in the frame address's fragment (never sent in a request).
The frame sends it as X-Orch-Frame (or, for a picture or file address, the `orch-frame` query value).

A pass:
- works for ONE add-on: its pages under /addon/<name>/ and the few dashboard calls an add-on page makes
  (FRAME_ROOT_PATHS); never for minting another pass, the sign-in or any other dashboard call;
- belongs to the page session that minted it: a new sign-in or a revoked one ends every pass;
- is kept in memory only (a hash of it), lives LIFE seconds, at most MAX at a time;
- is read-only when the page that asked had no sign-in (watch-only on this computer, as before the frames moved).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time

FRAME_HEADER = "X-Orch-Frame"
FRAME_PARAM = "orch-frame"
FRAME_ROOT_PATHS = ("/api/act", "/api/events", "/api/term", "/api/term/keys")
PASS_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
LIFE = 8 * 3600
MAX = 64


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class FramePasses:
    """The passes of one dashboard server. Thread-safe."""

    def __init__(self, life: float = LIFE, limit: int = MAX):
        self._lock = threading.Lock()
        self._life = life
        self._limit = limit
        self._passes: dict[
            str, tuple[str, bool, str, float]
        ] = {}  # digest -> (addon, act, session tag, expires)

    def mint(self, addon: str, act: bool, session_tag: str) -> str:
        value = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._passes = {k: v for k, v in self._passes.items() if v[3] > now}
            while len(self._passes) >= self._limit:  # the oldest goes first
                self._passes.pop(min(self._passes, key=lambda k: self._passes[k][3]))
            self._passes[_digest(value)] = (addon, bool(act), session_tag, now + self._life)
        return value

    def check(self, value: str | None, session_tag: str) -> tuple[str, bool] | None:
        """(add-on, may act) for a live pass of this session, else None."""
        if not isinstance(value, str) or not PASS_RE.fullmatch(value):
            return None
        with self._lock:
            hit = self._passes.get(_digest(value))
        if not hit or hit[3] <= time.time() or not hmac.compare_digest(hit[2], session_tag):
            return None
        return hit[0], hit[1]

    def clear(self) -> None:
        with self._lock:
            self._passes.clear()


def session_tag(session) -> str:
    """Ties a pass to the page session: a new secret (new sign-in) or a revoked session ends every pass."""
    if session is None:
        return "none"
    if getattr(session, "revoked", False):
        return "revoked:" + secrets.token_hex(8)  # never equal to a stored tag
    secret = getattr(session, "secret", "") or ""
    return _digest("orch-frame:" + secret)
