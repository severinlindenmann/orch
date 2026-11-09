"""What the orch-shipped page servers (Focus, dashboard) use to mint human proofs (H1, human-proof.md).

A page server holds the human key in memory, creates one session per start, and mints an hp1 proof only for a
request that (1) carries the session cookie, (2) arrived on the loopback listener with a loopback Host and
(3) carries no X-Forwarded-* / Forwarded header. The core is run as `sys.executable -I -m orch`, never through
ORCH_BIN or PATH, so a planted command never sees a proof.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import subprocess
import sys
from http.cookies import SimpleCookie
from pathlib import Path

from orch import humanproof, tickets
from orch.errors import Refused

SELF = "orch:self"  # the orch_bin value that means "this Python, `-I -m orch`"
COOKIE = "orch_page"
SERVERS = ("focus", "dashboard")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
REVOKED_MSG = "Someone else tried to use this sign-in link. Open the dashboard again from orch."


def argv0(orch_bin: str | None) -> list[str]:
    """The command prefix. SELF = this interpreter in isolated mode; any other value is a TEST fake."""
    return [sys.executable, "-I", "-m", "orch"] if orch_bin == SELF else [str(orch_bin)]


def child_env(env: dict, orch_bin: str | None) -> dict:
    """The environment of a child: ORCH_BIN is dropped for SELF (a child must never be pointed elsewhere)."""
    out = dict(env)
    if orch_bin == SELF:
        out.pop("ORCH_BIN", None)
        # nothing that makes a process load other code (a proof goes to this child's stdin)
        for k in [k for k in out if k.startswith(("LD_", "DYLD_", "PYTHON"))]:
            out.pop(k)
    else:
        out["ORCH_BIN"] = str(orch_bin)
    return out


def forwarded(headers) -> bool:
    return any(k.lower().startswith("x-forwarded-") or k.lower() == "forwarded" for k in headers)


def host_ok(headers, port: int) -> bool:
    host = (headers.get("Host") or "").strip().lower()
    return host in (f"127.0.0.1:{port}", f"localhost:{port}")


class PageSession:
    """One per server start. `key` is None (watch-only) when there is no key or an agent tool is in the
    environment of the server."""

    def __init__(self, root: Path, server: str):
        if server not in SERVERS:
            raise ValueError("not a page server")
        self.root, self.server = root, server
        self.cookie = secrets.token_urlsafe(32)  # new on every start
        self.key: bytes | None = None
        self.spent: set[str] = set()  # sha256 of launch tokens already used in this server run
        self.revoked = False
        if tickets.agent_tool():
            return
        try:
            self.key = humanproof.human_key(root)
        except (Refused, OSError):
            self.key = None

    # -- the launch token (one time, 120 s) ----------------------------------------------------------
    def launch(self, token) -> str | None:
        """Spend the launch token. Returns the cookie value to set, or None. A SECOND use of a token that was
        already spent revokes the session minted from it (new cookie secret: the old cookie is dead) and logs
        one line without any token value."""
        if self.key is None or not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        if digest in self.spent:
            self.cookie = secrets.token_urlsafe(32)
            self.revoked = True
            print(
                f"orch {self.server}: a sign-in link was used twice; the page session was ended.",
                file=sys.stderr,
            )
            return None
        if not humanproof.consume_launch_token(self.root, self.server, token):
            return None
        self.spent.add(digest)
        self.revoked = False
        return self.cookie

    def authed(self, headers) -> bool:
        raw = headers.get("Cookie") or ""
        try:
            jar = SimpleCookie(raw)
        except Exception:  # noqa: BLE001 - a broken cookie header is no session
            return False
        c = jar.get(COOKIE)
        return bool(c and hmac.compare_digest(c.value, self.cookie))

    def can_mint(self, headers, port: int) -> bool:
        """Session cookie + loopback Host + no proxy headers + a key."""
        return (
            self.key is not None
            and host_ok(headers, port)
            and not forwarded(headers)
            and self.authed(headers)
        )

    def mint(self, op: str, target: str) -> str:
        if self.key is None:
            raise Refused("no key")
        by = actor()
        return humanproof.mint(self.key, humanproof.new_payload(op, target, by))


def actor() -> str:
    import getpass

    try:
        who = re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:58]
    except (OSError, KeyError, ImportError):
        who = ""
    return f"human:{who or 'user'}"


def run_with_proof(
    argv: list[str], proof: str, *, orch_bin: str, cwd: Path, env: dict, timeout: int
) -> subprocess.CompletedProcess:
    """Run the core with `--proof-stdin`; the proof is the first line of stdin, never argv or env."""
    return subprocess.run(
        [*argv0(orch_bin), *argv, "--proof-stdin"],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=proof + "\n",
        env=child_env(env, orch_bin),
    )
