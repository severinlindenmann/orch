"""What the orch-shipped page servers (Focus, dashboard, Insights) use to mint human proofs (H1,
human-proof.md).

A page server holds the human key in memory, creates one session per start, and mints an hp1 proof only for a
request that (1) carries the session cookie, (2) arrived on the loopback listener with a loopback Host and
(3) carries no X-Forwarded-* / Forwarded header. The core is run as `sys.executable -I -m orch`, never through
ORCH_BIN or PATH, so a planted command never sees a proof.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from http.cookies import SimpleCookie
from pathlib import Path

from orch import humanproof, tickets
from orch.errors import Refused

SELF = "orch:self"  # the orch_bin value that means "this Python, `-I -m orch`"
COOKIE_PREFIX = "orch_page"
SERVERS = ("focus", "dashboard", "insights")
_SERVER_NAME_RE = re.compile(r"[a-z0-9_]{1,32}")
# The ops a page server may mint, enforced in PageSession.mint. A server not named here keeps every op (focus,
# dashboard: their behaviour before 2.11); Insights mints only its two (human-proof.md, step 3).
SERVER_OPS = {"insights": frozenset({"insights.settings", "record.delete_detail"})}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
REVOKED_MSG = "Someone else tried to use this sign-in link. Open the dashboard again from orch."


def argv0(orch_bin: str | None) -> list[str]:
    """The command prefix. SELF = this interpreter in isolated mode; any other value is a TEST fake."""
    return [sys.executable, "-I", "-P", "-m", "orch"] if orch_bin == SELF else [str(orch_bin)]


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


def cookie_name(server: str, port: int) -> str:
    """The session cookie of ONE page server on ONE port: `orch_page_<server>_<port>`. Cookies on 127.0.0.1
    are shared by every loopback port (Path=/), so a single name would let one server's login replace (log
    out) the other's and hand its value to every loopback server; a per-server, per-port name keeps them
    apart."""
    if not isinstance(server, str) or not _SERVER_NAME_RE.fullmatch(server):
        raise ValueError("not a page server name")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("not a port")
    return f"{COOKIE_PREFIX}_{server}_{port}"


def set_cookie_header(server: str, port: int, value: str) -> str:
    """The Set-Cookie value of a page session (HttpOnly, SameSite=Strict, Path=/)."""
    return f"{cookie_name(server, port)}={value}; HttpOnly; SameSite=Strict; Path=/"


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
        self.cookie = secrets.token_urlsafe(32)  # new on every start (but see the resume below)
        self.key: bytes | None = None
        self.spent: set[str] = set()  # sha256 of launch tokens already used in this server run
        self.revoked = False
        self._lock = threading.Lock()  # one lock across check, consume and spent.add (no race on reuse)
        if tickets.agent_tool():
            return
        try:
            self.key = humanproof.human_key(root)
        except (Refused, OSError):
            self.key = None
        if self.key is not None:  # a restart the person asked for (update) keeps the open tab's session
            self.cookie = humanproof.take_resume_cookie(root, server) or self.cookie

    # -- the launch token (one time, 120 s) ----------------------------------------------------------
    def launch(self, token) -> str | None:
        """Spend the launch token. Returns the cookie value to set, or None. A SECOND use of a token that was
        already spent revokes the session minted from it (new cookie secret: the old cookie is dead) and logs
        one line without any token value."""
        if self.key is None or not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
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

    def cookie_name(self, port: int) -> str:
        return cookie_name(self.server, port)

    def set_cookie(self, port: int, value: str) -> str:
        return set_cookie_header(self.server, port, value)

    def authed(self, headers, port: int) -> bool:
        """Only THIS server's cookie on THIS port counts (another loopback server's cookie is no session)."""
        raw = headers.get("Cookie") or ""
        try:
            name = self.cookie_name(port)
            jar = SimpleCookie(raw)
        except Exception:  # noqa: BLE001 - a broken cookie header (or port) is no session
            return False
        c = jar.get(name)
        return bool(c and hmac.compare_digest(c.value, self.cookie))

    def can_mint(self, headers, port: int) -> bool:
        """Session cookie + loopback Host + no proxy headers + a key."""
        return (
            self.key is not None
            and host_ok(headers, port)
            and not forwarded(headers)
            and self.authed(headers, port)
        )

    def mint(self, op: str, target: str) -> str:
        if self.key is None:
            raise Refused("no key")
        allowed = SERVER_OPS.get(self.server)
        if allowed is not None and op not in allowed:
            raise Refused("This page cannot approve that.")
        by = actor()
        return humanproof.mint(self.key, humanproof.new_payload(op, target, by))

    def mint_insights_setting(self, setting: str, value: bool | int) -> str:
        """An `insights.settings` proof: the target is built by config.insights_target, the ONE canonical form
        the core checks against (`insights.keep_days=365`, `insights.share_names=on`)."""
        from orch import config

        if setting not in config.INSIGHTS_KEYS:
            raise Refused("That is not an Insights setting.")
        return self.mint("insights.settings", config.insights_target(setting, value))


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
    i = argv.index("--") if "--" in argv else len(argv)  # the flag goes BEFORE the free text after `--`
    argv = [*argv[:i], "--proof-stdin", *argv[i:]]
    return subprocess.run(
        [*argv0(orch_bin), *argv],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=proof + "\n",
        env=child_env(env, orch_bin),
    )


def start_detached(argv: list[str], proof: str, *, orch_bin: str, cwd: Path, env: dict) -> int:
    """Run the core with `--proof-stdin` through a small detached RUNNER (own session, survives a restart of
    this server): it keeps the output in a log in the guarded home, stops a hung run after 30 minutes and
    records running / finished / failed for the page. The proof goes to its stdin; returns its pid at once."""
    i = argv.index("--") if "--" in argv else len(argv)
    full = [*argv0(orch_bin), *argv[:i], "--proof-stdin", *argv[i:]]
    kw: dict = {"start_new_session": True}
    if sys.platform == "win32":
        kw = {"creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen(  # noqa: S603
        [sys.executable, "-I", "-P", "-m", "orch.pageproof", json.dumps(full)],
        cwd=cwd,
        env=child_env(env, orch_bin),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        **kw,
    )
    try:
        p.stdin.write(proof + "\n")
        p.stdin.close()
    except OSError:
        pass
    return p.pid


def _short_reason(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    last = lines[-1] if lines else "it did not finish"
    return re.sub(r"^Refused:\s*", "", last)[:120]


def _runner(cmd: list[str]) -> int:
    """The detached runner: `python -I -P -m orch.pageproof '<json command>'`, the proof on its own stdin."""
    from orch import addons, winfinish

    root = Path.cwd()
    finish_home = addons.home()
    finish_log = winfinish.log_path(finish_home)
    windows = winfinish.needed()
    offset = finish_log.stat().st_size if windows and finish_log.exists() else 0
    proof = sys.stdin.readline()
    humanproof.write_update_status(root, "running")
    try:
        log = humanproof.key_dir(root) / "update.log"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except (Refused, OSError):
        humanproof.write_update_status(root, "failed", "the update could not write its log")
        return 1
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        try:
            p = subprocess.Popen(  # noqa: S603
                cmd, cwd=root, stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT, text=True
            )
            p.stdin.write(proof)
            p.stdin.close()
            code = p.wait(timeout=humanproof.UPDATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            humanproof.write_update_status(root, "failed", "it took too long and was stopped")
            return 1
        except OSError:
            humanproof.write_update_status(root, "failed", "the update could not be started")
            return 1
    if code == 0 and windows:
        # Exit so the finisher can rename the tool environment. The page polls its result.
        humanproof.write_update_status(root, "running", finish_offset=offset)
        return 0
    if code == 0:
        humanproof.write_update_status(root, "finished")
        return 0
    try:
        tail = log.read_text(errors="replace")  # lint-allow: our own log (plain text)
    except OSError:
        tail = ""
    humanproof.write_update_status(root, "failed", _short_reason(tail))
    return code


if __name__ == "__main__":
    try:
        sys.exit(_runner(json.loads(sys.argv[1])))
    except (ValueError, IndexError):
        sys.exit(2)
