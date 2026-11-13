"""What the orch-shipped page servers (Focus, dashboard, Insights) use to mint human proofs (H1,
human-proof.md).

A page server holds the human key in memory, creates one session per start, and mints an hp1 proof (or acts
with the session at all) only for a request that (1) carries the session cookie AND the page secret in the
X-Orch-Page header, (2) arrived on the loopback listener with a loopback Host and (3) carries no
X-Forwarded-* / Forwarded header. The cookie alone is never enough: browsers send a host's cookies to every
loopback port, so another local page could replay it. The secret is handed to the page once, in the body of
the launch answer (never in a cookie, the HTML or a URL) and lives in that page's sessionStorage (per origin,
so per port). The core is run as `sys.executable -I -m orch`, never through ORCH_BIN or PATH, so a planted
command never sees a proof.
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

PAGE_HEADER = "X-Orch-Page"  # the header that carries the page secret (the second half of a page session)
SELF = "orch:self"  # the orch_bin value that means "this Python, `-I -m orch`"
COOKIE_PREFIX = "orch_page"
SERVERS = ("focus", "dashboard", "insights")
_SERVER_NAME_RE = re.compile(r"[a-z0-9_]{1,32}")
# The ops a page server may mint, enforced in PageSession.mint. A server not named here keeps every op (focus,
# dashboard: their behaviour before 2.11); Insights mints only its two (human-proof.md, step 3).
SERVER_OPS = {"insights": frozenset({"insights.settings", "record.delete_detail"})}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
EXPIRED_MSG = "This request expired. Run the update again."
RESTARTED_MSG = "orch restarted. Reload this page to keep working."
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
    out) the other's. The per-server, per-port name keeps the SESSIONS of the servers apart on the same host
    (one server's login never replaces another's, and a server only accepts its own name). It does NOT keep
    the values apart: the browser still sends every cookie of the host to every localhost port, so any
    local server the person visits (an agent-run dev server too) receives them. That is why a cookie alone
    is no session: PageSession.authed also needs the page secret (PAGE_HEADER), which is not a cookie."""
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


def _say(line: str) -> None:
    """One diagnostic line on stderr; a closed stderr (detached start) must not stop a start."""
    try:
        print(line, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


class PageSession:
    """One per server start. `key` is None (watch-only) when there is no key or an agent tool is in the
    environment of the server."""

    def __init__(self, root: Path, server: str):
        if server not in SERVERS:
            raise ValueError("not a page server")
        self.root, self.server = root, server
        self.cookie = secrets.token_urlsafe(32)  # new on every start (but see the resume below)
        self.secret = secrets.token_urlsafe(32)  # the page secret: sent as PAGE_HEADER, never as a cookie
        self.key: bytes | None = None
        self.spent: set[str] = set()  # sha256 of launch tokens already used in this server run
        self.revoked = False
        self.resumed = False  # True when this start adopted the open tab's session (after an update restart)
        self._lock = threading.Lock()  # one lock across check, consume and spent.add (no race on reuse)
        if tickets.agent_tool():
            return
        try:
            self.key = humanproof.human_key(root)
        except (Refused, OSError):
            self.key = None
        if self.key is not None:  # a restart the person asked for (update) keeps the open tab's session
            why: list = []
            resumed = humanproof.take_resume_session(root, server, why)
            for line in why:  # a restart that had a session to adopt and did not: say why (no secrets)
                _say(f"orch {server}: did not keep the open page's session: {line}.")
            if resumed:
                self.cookie, self.secret = resumed
                self.resumed = True
                _say(f"orch {server}: kept the open page's session after the restart.")

    # -- the launch token (one time, 120 s) ----------------------------------------------------------
    def launch(self, token) -> str | None:
        """Spend the launch token. Returns the cookie value to set, or None; the page secret for the answer
        body is `self.secret`. A SECOND use of a token that was already spent revokes the session minted from
        it (new cookie and secret: the old ones are dead) and logs one line without any token value."""
        if self.key is None or not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            if digest in self.spent:
                self.cookie = secrets.token_urlsafe(32)
                self.secret = secrets.token_urlsafe(32)
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
        """A page session = THIS server's cookie on THIS port AND the page secret in PAGE_HEADER, both
        compared in constant time. A cookie alone (another loopback server's, or one replayed from a foreign
        local page) is no session. This is the one place the rule lives: every route that mints or acts with
        the session asks authed() or can_mint()."""
        sent = headers.get(PAGE_HEADER) or ""
        if not isinstance(sent, str) or not hmac.compare_digest(sent.encode(), self.secret.encode()):
            return False
        raw = headers.get("Cookie") or ""
        try:
            name = self.cookie_name(port)
            jar = SimpleCookie(raw)
        except Exception:  # noqa: BLE001 - a broken cookie header (or port) is no session
            return False
        c = jar.get(name)
        return bool(c and hmac.compare_digest(c.value, self.cookie))

    def stale(self, headers, port: int) -> bool:
        """The page presents a session (this server's cookie name or the page secret) that this server does
        not know: the server restarted without adopting it. A page that never signed in presents neither."""
        if self.key is None or self.authed(headers, port):
            return False
        try:
            has_cookie = self.cookie_name(port) in SimpleCookie(headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001
            has_cookie = False
        return bool(headers.get(PAGE_HEADER)) or has_cookie

    def can_mint(self, headers, port: int) -> bool:
        """Session (cookie + page secret) + loopback Host + no proxy headers + a key."""
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
    last = re.sub(r"^Refused:\s*", "", lines[-1]) if lines else "it did not finish"
    if last == humanproof.HANDOFF:  # the core did not accept the click's proof (expired or used): say that
        return EXPIRED_MSG
    return last[:120]


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
