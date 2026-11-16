"""The login of the orch-shipped page servers (Focus, dashboard, Insights).

The login is the ONLY gate (owner rule, 16 Nov): once a person signed in with a one-time sign-in link, every
action of the page works from any computer: the same one, another one through a proxy, a headless server.
Nothing here looks at where a request comes from (no loopback Host, no proxy-header check).

A request counts as the person's when it carries the session cookie AND the page secret in the X-Orch-Page
header. The cookie alone is never enough: browsers send a host's cookies to every port of that host, so
another local page could replay it. The secret is handed to the page once, in the body of the sign-in answer
(never in a cookie, the HTML or a URL) and lives in the browser's localStorage (per origin, so per host and
port; every tab of the browser shares it). The session is kept in the private key folder, so it survives a
restart or an update of the server for SESSION_LIFE. Behind the dashboard, an add-on page server (Focus,
Insights) also accepts the dashboard's word for the person (VOUCH_HEADER with the workspace's private vouch
key). The core is run as `sys.executable -I -m orch`, never through ORCH_BIN or PATH.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

from orch import pagelaunch, tickets
from orch.errors import Refused

PAGE_HEADER = "X-Orch-Page"  # the header that carries the page secret (the second half of a page session)
SELF = "orch:self"  # the orch_bin value that means "this Python, `-I -m orch`"
COOKIE_PREFIX = "orch_page"
SERVERS = ("focus", "dashboard", "insights")
_SERVER_NAME_RE = re.compile(r"[a-z0-9_]{1,32}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
SIGNIN_MSG = "Sign in to do this: open the dashboard with a sign-in link from orch."
SIGNIN_PREFIX = "Sign in to "  # session.js shows the sign-in notice for a refusal that starts with this
VOUCH_HEADER = "X-Orch-Person"  # the dashboard's word to an add-on page behind it: the person sent this
SESSION_LIFE = 30 * 24 * 3600  # seconds a page session lasts (cookie Max-Age and the kept session file)
REVOKED_MSG = "Someone else tried to use this sign-in link. Open the dashboard again from orch."


def argv0(orch_bin: str | None) -> list[str]:
    """The command prefix. SELF = this interpreter in isolated mode; any other value is a TEST fake."""
    return [sys.executable, "-I", "-P", "-m", "orch"] if orch_bin == SELF else [str(orch_bin)]


def child_env(env: dict, orch_bin: str | None) -> dict:
    """The environment of a child: ORCH_BIN is dropped for SELF (a child must never be pointed elsewhere)."""
    out = dict(env)
    if orch_bin == SELF:
        out.pop("ORCH_BIN", None)
        # nothing that makes a process load other code
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
    """The Set-Cookie value of a page session (HttpOnly, SameSite=Strict, Path=/, kept SESSION_LIFE)."""
    return f"{cookie_name(server, port)}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_LIFE}"


_KEEP_RE = re.compile(r"[A-Za-z0-9_-]{20,80}")


def _session_file(root: Path, server: str, port: int) -> Path:
    if not _SERVER_NAME_RE.fullmatch(server) or isinstance(port, bool) or not 0 < int(port) < 65536:
        raise ValueError("not a page server or port")
    return pagelaunch.key_dir(root) / f"session-{server}-{int(port)}.key"


def load_kept_session(root: Path, server: str, port: int) -> tuple[str, str] | None:
    """The (cookie, page secret) this server kept from an earlier start, while younger than SESSION_LIFE."""
    from orch import home as orch_home

    try:
        lines = orch_home._read_guarded(_session_file(root, server, port)).decode("ascii").split()
    except Exception:  # noqa: BLE001 - none, unreadable or refused: a new session
        return None
    if (
        len(lines) == 3
        and lines[2].isdigit()
        and time.time() < int(lines[2]) <= time.time() + SESSION_LIFE
        and _KEEP_RE.fullmatch(lines[0])
        and _KEEP_RE.fullmatch(lines[1])
    ):
        return lines[0], lines[1]
    return None


def keep_session(root: Path, server: str, port: int | None, cookie: str, secret: str) -> None:
    """Keep the session in the private key folder (0600): a restart or an update signs nobody out."""
    from orch import home as orch_home

    if port is None:  # a server that does not keep its session (Insights: its secret lives in memory only)
        return
    with contextlib.suppress(Exception):
        orch_home._write_private(
            _session_file(root, server, port), f"{cookie}\n{secret}\n{int(time.time()) + SESSION_LIFE}\n"
        )


def vouch_key(root: Path, create: bool = False) -> str | None:
    """The workspace's private key the dashboard uses to vouch for the person to an add-on page behind it."""
    from orch import home as orch_home

    try:
        f = pagelaunch.key_dir(root, create=create) / "page-vouch.key"
    except Exception:  # noqa: BLE001 - no private key folder here: nobody is vouched for
        return None
    try:
        raw = orch_home._read_guarded(f).decode("ascii").strip()
        if _KEEP_RE.fullmatch(raw):
            return raw
    except Exception:  # noqa: BLE001
        pass
    if not create:
        return None
    key = secrets.token_urlsafe(32)
    try:
        orch_home._write_private(f, key + "\n")
    except Exception:  # noqa: BLE001
        return None
    return key


def _say(line: str) -> None:
    """One diagnostic line on stderr; a closed stderr (detached start) must not stop a start."""
    try:
        print(line, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


class PageSession:
    """One per server start. `active` is False (watch-only) when an agent tool is in the environment of the
    server: it never logs in."""

    def __init__(self, root: Path, server: str, port: int | None = None):
        """`port`: the bound port of the server. With it, the session is kept for SESSION_LIFE in the key
        folder (per server and port, like the cookie name), so a restart or an update signs nobody out."""
        if server not in SERVERS:
            raise ValueError("not a page server")
        self.root, self.server, self.port = root, server, port
        self.cookie = secrets.token_urlsafe(32)  # new on every start (but see the resume below)
        self.secret = secrets.token_urlsafe(32)  # the page secret: sent as PAGE_HEADER, never as a cookie
        self.active = not tickets.agent_tool()
        self.spent: set[str] = set()  # sha256 of launch tokens already used in this server run
        self.revoked = False
        self.resumed = False  # True when this start adopted the open tab's session (after an update restart)
        self._lock = threading.Lock()  # one lock across check, consume and spent.add (no race on reuse)
        if not self.active:
            return
        # a restart the person asked for (update) keeps the open tab's session
        why: list = []
        resumed = pagelaunch.take_resume_session(root, server, why)
        pagelaunch.disarm_restart(root)  # the add-on restart this start belongs to is over (#705)
        for line in why:  # a restart that had a session to adopt and did not: say why (no secrets)
            _say(f"orch {server}: did not keep the open page's session: {line}.")
        if resumed:
            self.cookie, self.secret = resumed
            self.resumed = True
            _say(f"orch {server}: kept the open page's session after the restart.")
        elif port is not None:
            kept = load_kept_session(root, server, port)
            if kept:
                self.cookie, self.secret = kept
                self.resumed = True
        keep_session(root, server, port, self.cookie, self.secret)

    # -- the launch token (one time, 120 s) ----------------------------------------------------------
    def launch(self, token) -> str | None:
        """Spend the launch token. Returns the cookie value to set, or None; the page secret for the answer
        body is `self.secret`. A SECOND use of a token that was already spent revokes the session minted from
        it (new cookie and secret: the old ones are dead) and logs one line without any token value."""
        if not self.active or not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            if digest in self.spent:
                self.cookie = secrets.token_urlsafe(32)
                self.secret = secrets.token_urlsafe(32)
                self.revoked = True
                keep_session(self.root, self.server, self.port, self.cookie, self.secret)
                print(
                    f"orch {self.server}: a sign-in link was used twice; the page session was ended.",
                    file=sys.stderr,
                )
                return None
            if not pagelaunch.consume_launch_token(self.root, self.server, token):
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
        local page) is no session. This is the one place the rule lives: every route that acts with
        the session asks authed() or can_act()."""
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
        if not self.active or self.authed(headers, port):
            return False
        try:
            has_cookie = self.cookie_name(port) in SimpleCookie(headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001
            has_cookie = False
        return bool(headers.get(PAGE_HEADER)) or has_cookie

    def cookie_ok(self, headers, port: int) -> bool:
        """This server's cookie with the current value (no page secret): enough for a READ under a host name
        that is not this computer's (a proxy): only a browser that signed in at that name holds it."""
        if not self.active:
            return False
        try:
            c = SimpleCookie(headers.get("Cookie") or "").get(self.cookie_name(port))
        except Exception:  # noqa: BLE001
            return False
        return bool(c and hmac.compare_digest(c.value, self.cookie))

    def vouched(self, headers) -> bool:
        """The dashboard in front of this add-on page vouches that the person sent this (VOUCH_HEADER)."""
        sent = headers.get(VOUCH_HEADER) or ""
        if not self.active or self.server == "dashboard" or not isinstance(sent, str) or not sent:
            return False
        key = vouch_key(self.root)
        return bool(key) and hmac.compare_digest(sent.encode(), key.encode())

    def can_act(self, headers, port: int) -> bool:
        """The person's session: cookie + page secret, or the dashboard's word for it. Where the request comes
        from (this computer, a proxy, another computer) does not matter: the sign-in is the only gate."""
        return self.active and (self.authed(headers, port) or self.vouched(headers))


def run_core(
    argv: list[str], *, orch_bin: str, cwd: Path, env: dict, timeout: int
) -> subprocess.CompletedProcess:
    """Run the core as the person who opened the page."""
    return subprocess.run(
        [*argv0(orch_bin), *argv],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input="",
        env=child_env(env, orch_bin),
    )


def start_detached(argv: list[str], *, orch_bin: str, cwd: Path, env: dict) -> int:
    """Run the core through a small detached RUNNER (own session, survives a restart of this server): it keeps
    the output in a log in the guarded home, stops a hung run after 30 minutes and records running /
    finished / failed for the page. Returns its pid at once."""
    full = [*argv0(orch_bin), *argv]
    kw: dict = {"start_new_session": True}
    if sys.platform == "win32":
        kw = {"creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen(  # noqa: S603
        [sys.executable, "-I", "-P", "-m", "orch.pagesession", json.dumps(full)],
        cwd=cwd,
        env=child_env(env, orch_bin),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kw,
    )
    return p.pid


def _short_reason(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    last = re.sub(r"^Refused:\s*", "", lines[-1]) if lines else "it did not finish"
    return last[:120]


def _runner(cmd: list[str]) -> int:
    """The detached runner: `python -I -P -m orch.pagesession '<json command>'`."""
    from orch import addons, winfinish

    root = Path.cwd()
    finish_home = addons.home()
    finish_log = winfinish.log_path(finish_home)
    windows = winfinish.needed()
    offset = finish_log.stat().st_size if windows and finish_log.exists() else 0
    pagelaunch.write_update_status(root, "running")
    try:
        log = pagelaunch.key_dir(root) / "update.log"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except (Refused, OSError):
        pagelaunch.write_update_status(root, "failed", "the update could not write its log")
        return 1
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        try:
            p = subprocess.Popen(  # noqa: S603
                cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, text=True
            )
            code = p.wait(timeout=pagelaunch.UPDATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            pagelaunch.write_update_status(root, "failed", "it took too long and was stopped")
            return 1
        except OSError:
            pagelaunch.write_update_status(root, "failed", "the update could not be started")
            return 1
    if code == 0 and windows:
        # Exit so the finisher can rename the tool environment. The page polls its result.
        pagelaunch.write_update_status(root, "running", finish_offset=offset)
        return 0
    if code == 0:
        pagelaunch.write_update_status(root, "finished")
        return 0
    try:
        tail = log.read_text(errors="replace")  # lint-allow: our own log (plain text)
    except OSError:
        tail = ""
    pagelaunch.write_update_status(root, "failed", _short_reason(tail))
    return code


if __name__ == "__main__":
    try:
        sys.exit(_runner(json.loads(sys.argv[1])))
    except (ValueError, IndexError):
        sys.exit(2)
