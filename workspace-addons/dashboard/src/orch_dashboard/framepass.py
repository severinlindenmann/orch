"""Frame passes (ORCH-186): the add-on pages orch ships run in a sandboxed frame (an opaque origin), so a script in
one can never read the dashboard's page secret or reach into the dashboard page. The dashboard page (signed in)
asks for passes for one add-on and hands them to that add-on's own page (never a file, a ticket page or any other
address under it) in the frame address's fragment, which is never sent in a request.

Two passes are minted together:
- the pass (`kind="header"`), sent only as X-Orch-Frame: the add-on's pages under /addon/<name>/ and the dashboard
  calls that add-on's page makes (FRAME_ROOT); it acts when the page that asked could act;
- the file pass (`kind="file"`), sent only as the `orch-frame` query value of a picture, file or download address
  (an <img> or a link cannot send a header): GET of the add-on's file and picture addresses only, never acts. A
  file pass seen in a log or a download history can only read those files for the rest of its short life.

What a pass may do through the dashboard's /api/act is a fixed list per add-on (FRAME_OPS): the person's actions
that add-on page offers, nothing else (never settings, keys, updates, add-ons or helpers' starts).

Every pass belongs to the server's page secret and to the address it was minted on (host name, and this
computer's port or the port for other computers): a revoked sign-in (every pass is then dropped), another host
name or the other port ends it. A second normal sign-in keeps the same secret, so passes live on until LIFE ends.
Kept in memory only (a hash of it), LIFE seconds, at most MAX at a time.
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
# The dashboard calls an add-on page makes itself (beyond its own /addon/<name>/): Focus shows and types into the
# live helper session and acts through the dashboard. Every other add-on page: none.
FRAME_ROOT = {"focus": ("/api/act", "/api/events", "/api/term", "/api/term/keys")}
ALL_ROOT_PATHS = frozenset(p for paths in FRAME_ROOT.values() for p in paths)
PASS_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
# the addresses a file pass may read: an add-on's file and picture answers (Focus /api/file, Factory order files)
FILE_PATH = re.compile(r"/api/(?:file|order/[A-Za-z0-9_-]{1,64}/file/[A-Za-z0-9_./%-]{1,300})")
LIFE = 900  # 15 minutes: the frame asks for new passes by itself when a call answers 401
# What each add-on's pass may run through the dashboard's /api/act (Focus's store.js EMBED_HUMAN, `ticket.done`
# arriving as `ticket.patch` to done). Everything else is refused (ORCH-186 review M1).
FRAME_OPS = {
    "focus": frozenset(
        {
            "answer",
            "ticket.patch",
            "run.send",
            "check.wont_do",
            "check.reopen",
            "check.edit",
            "check.remove",
            "ticket.attach",
            "run.take_back",
        }
    )
}
REFUSED_OP = "This page may not do that. Do it in the dashboard."


def op_refusal(addon: str, body: dict) -> str | None:
    """None when the add-on page's pass may run this /api/act body, else the refusal words."""
    op, args = body.get("op"), body.get("args")
    if op not in FRAME_OPS.get(addon, ()) or not isinstance(args, dict):
        return REFUSED_OP
    # ticket.patch: only Done (Focus's "Looks good"), nothing else of the ticket
    if op == "ticket.patch" and (
        set(args) - {"ticket", "data", "if_revision"} or args.get("data") != {"status": "done"}
    ):
        return REFUSED_OP
    return None


MAX = 128
KINDS = ("header", "file")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class FramePasses:
    """The passes of one dashboard server. Thread-safe."""

    def __init__(self, life: float = LIFE, limit: int = MAX):
        self._lock = threading.Lock()
        self._life = life
        self._limit = limit
        # digest -> (addon, act, tag, expires, kind)
        self._passes: dict[str, tuple[str, bool, str, float, str]] = {}

    def issue(self, addon: str, act: bool, tag: str) -> tuple[str, str]:
        """(pass, file pass) for one add-on page."""
        header, file = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._passes = {k: v for k, v in self._passes.items() if v[3] > now}
            while len(self._passes) >= self._limit - 1:  # the oldest go first
                self._passes.pop(min(self._passes, key=lambda k: self._passes[k][3]))
            self._passes[_digest(header)] = (addon, bool(act), tag, now + self._life, "header")
            self._passes[_digest(file)] = (addon, False, tag, now + self._life, "file")
        return header, file

    def check(self, value: str | None, tag: str, kind: str) -> tuple[str, bool] | None:
        """(add-on, may act) for a live pass of this kind, session and address, else None."""
        if kind not in KINDS or not isinstance(value, str) or not PASS_RE.fullmatch(value):
            return None
        with self._lock:
            hit = self._passes.get(_digest(value))
        if not hit or hit[3] <= time.time() or hit[4] != kind or not hmac.compare_digest(hit[2], tag):
            return None
        return hit[0], hit[1]

    def clear(self) -> None:
        with self._lock:
            self._passes.clear()


def pass_tag(session, host: str, remote: bool) -> str:
    """Ties a pass to the page session (a new secret or a revoked session ends it) and to the address it was
    minted on (the Host name and which port)."""
    if session is None:
        base = "none"
    elif getattr(session, "revoked", False):
        return "revoked:" + secrets.token_hex(8)  # never equal to a stored tag
    else:
        base = "orch-frame:" + (getattr(session, "secret", "") or "")
    return _digest(base + "\n" + ("remote" if remote else "local") + "\n" + (host or "").strip().lower())
