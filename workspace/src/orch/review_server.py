"""`orch review`: the Review page, served by orch itself (no dashboard needed).

Stdlib HTTP on 127.0.0.1, in the foreground, until a time of day or Ctrl-C. Loopback Host and Origin
checks (orch_ui.origin), no proxy headers, and a plain localhost session: the server makes a random
token at start, the browser is opened with it in the URL fragment (`#k=<token>`, never printed,
never written to the run file), the page posts it once to /session and gets an HttpOnly
SameSite=Strict cookie that every /api route needs. An answer runs `orch review answer ...` in a
child, so the one place that decides is the core. The page files come from orch_ui's static folder
(found by path only: the core never imports orch_ui) through a fixed allowlist, and the reviewed
files from the ticket's own `reviewed/<sha12>/` copy through orch.safefile's reader.
"""

from __future__ import annotations

import contextlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
from functools import partial
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from orch import history, review, runs, safefile
from orch.errors import Refused

DEFAULT_PORT = 8432
PORT_TRIES = 40
MAX_BODY = 16 * 1024
COOKIE = "orch_review_{port}"
AGENT_REFUSED = "Only a human can do this. Ask the human to run it themselves."
RUN_FILE = "review-page.json"
NO_KIT = "The review page needs orch's page files. Use: orch review list / orch review answer"
ID_RE = re.compile(r"core:(?:q:(t_[a-z0-9]{6,16}):(q[0-9]+)|review:(t_[a-z0-9]{6,16}))")
TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
SHA12 = re.compile(r"[0-9a-f]{12}")
SHA64 = re.compile(r"[0-9a-f]{64}")
PICK_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
ANSWER_FIELDS = {"id", "digest", "verdict", "picked", "note"}
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; frame-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
# a reviewed file: no network, no scripts, no forms, its own opaque origin (the frame that shows it has the
# same sandbox); `frame-ancestors 'self'` so the page can frame it
FILE_CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src data:; sandbox; "
    "frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
)
KIT_FILES = (
    "tokens.css",
    "components.css",
    "motion.css",
    "widgets.css",
    "interaction.css",
    "overlay.js",
    "components.js",
    "icons.js",
    "widgets.js",
    "review.js",
    "review-boot.js",
)  # fmt: skip  (every file review.html links)
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
FILE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
}  # fmt: skip


def kit_dir() -> Path | None:
    """orch_ui's static folder, found by path next to the installed orch package (never imported, never
    searched on sys.path: a planted orch_ui is not used); None when the kit is not installed."""
    import orch

    d = Path(orch.__file__).resolve().parent.parent / "orch_ui" / "static"
    return d if (d / "review.html").is_file() else None


_ORIGIN: list = []


def _origin_check():
    """check_request of the kit's origin.py, loaded from its file (the core never imports orch_ui); None when
    the kit is missing. Loaded once."""
    if not _ORIGIN:
        fn = None
        d = kit_dir()
        if d is not None:
            spec = importlib.util.spec_from_file_location("_orch_review_origin", d.parent / "origin.py")
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                with contextlib.suppress(Exception):
                    spec.loader.exec_module(mod)
                    fn = mod.check_request
        _ORIGIN.append(fn)
    return _ORIGIN[0]


def _kit_bytes(name: str) -> bytes | None:
    d = kit_dir()
    if d is None:
        return None
    try:
        return (d / name).read_bytes()
    except OSError:
        return None


def _err(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


class Session:
    """The page's session: a random token made at start (single use), swapped for a cookie value."""

    def __init__(self) -> None:
        self.token: str | None = secrets.token_urlsafe(24)
        self.cookie: str | None = None
        self._lock = threading.Lock()

    def launch(self, given) -> str | None:
        with self._lock:
            if not isinstance(given, str) or self.token is None or not hmac.compare_digest(given, self.token):
                return None
            self.token = None  # used once
            self.cookie = secrets.token_urlsafe(24)
            return self.cookie


def _host_ok(headers, port: int) -> bool:
    return (headers.get("Host") or "").strip().lower() in (f"127.0.0.1:{port}", f"localhost:{port}")


def _forwarded(headers) -> bool:
    return any(k.lower().startswith("x-forwarded-") or k.lower() == "forwarded" for k in headers)


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def __init__(self, *a, root: Path, session, **kw):
        self.root, self.session = root, session
        super().__init__(*a, **kw)

    def log_message(self, *a):
        pass

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if "Content-Security-Policy" not in (extra or {}):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data):
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _text(self, code: int, text: str):
        self._send(code, text.encode(), "text/plain; charset=utf-8")

    def _origin_gate(self, method: str, api: bool) -> str | None:
        """Host + Origin (the kit's origin.py); a POST without Origin is refused too (the page sends one)."""
        check_request = _origin_check()
        if check_request is None:
            return NO_KIT
        if method == "POST" and self.headers.get("Origin") is None:
            return "This request was refused (no origin)."
        return check_request(method, self.headers, self.port, api=api)

    def _cookie_ok(self) -> bool:
        """This server's session cookie on this port (also what the files a frame or <img> loads send)."""
        s = self.session
        if s is None or s.cookie is None or not _host_ok(self.headers, self.port):
            return False
        if _forwarded(self.headers):
            return False
        try:
            c = SimpleCookie(self.headers.get("Cookie") or "").get(COOKIE.format(port=self.port))
        except Exception:  # noqa: BLE001 - a broken cookie header is no session
            return False
        return bool(c and hmac.compare_digest(c.value, s.cookie))

    _api_authed = _cookie_ok

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        path, _, query = self.path.partition("?")
        why = self._origin_gate("GET", path.startswith("/api/"))
        if why:
            return self._text(403, why)
        if path == "/":
            body = _kit_bytes("review.html")
            if body is None:
                return self._text(503, NO_KIT)
            return self._send(200, body, TYPES[".html"])
        if path.startswith("/kit/"):
            name = path[5:]
            if name not in KIT_FILES:
                return self._text(404, "not found")
            body = _kit_bytes(name)
            if body is None:
                return self._text(404, "not found")
            return self._send(200, body, TYPES[name[name.rfind(".") :]])
        if path == "/api/file":
            return self._file(parse_qs(query, keep_blank_values=True))
        if path in ("/api/stack", "/api/answered"):
            if not self._api_authed():
                return self._json(
                    403, _err("needs_person", "Sign in first: run orch review in your terminal.")
                )
            return self._read(path)
        self._text(404, "not found")

    def _read(self, path: str):
        try:
            if path == "/api/stack":
                cards = history.shown_json(self.root, review.stack(self.root))
                return self._json(200, {"workspace": self.root.name, "cards": cards})
            from orch import cli_review  # late: cli_review imports this module

            return self._json(200, history.shown_json(self.root, cli_review._answered(self.root)))
        except Exception:  # noqa: BLE001 - nothing of the failure goes to the page
            return self._json(503, _err("refused", "orch could not read the review list just now."))

    def _file(self, q: dict):
        one = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        tid, sha, name = one("t"), one("c"), one("n")
        ext = Path(name).suffix.lower()
        if (
            not self._cookie_ok()
            or not TID_RE.fullmatch(tid)
            or not SHA12.fullmatch(sha)
            or ext not in FILE_TYPES
            or (parts := safefile._parts(name)) is None  # noqa: SLF001
        ):
            return self._text(404, "not found")
        try:
            data = safefile._read_parts(  # noqa: SLF001 - the one hardened reader, as review.changed_files
                self.root, [".orch", "tickets", tid, review.REVIEWED, sha], parts, review.MAX_FILE
            )
        except (safefile.TooLarge, OSError, ValueError):
            data = None
        if data is None:
            return self._text(404, "not found")
        self._send(200, data, FILE_TYPES[ext], {"Content-Security-Policy": FILE_CSP})

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/session", "/api/answer"):
            return self._text(405, "not allowed")
        why = self._origin_gate("POST", True)
        if why:
            return self._text(403, why)
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
            return self._text(403, "This request came from another website and was refused.")
        body = self._body()
        if path == "/session":
            return self._session(body)
        self._answer(body)

    def _body(self) -> dict | None:
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return None
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= MAX_BODY:
                return None
            body = json.loads(self.rfile.read(n))
        except (ValueError, RecursionError, OSError):
            return None
        return body if isinstance(body, dict) else None

    def _session(self, body: dict | None):
        if self.session is None or _forwarded(self.headers) or not _host_ok(self.headers, self.port):
            return self._text(403, "forbidden")
        cookie = self.session.launch(body.get("token") if body else None)
        if not cookie:
            return self._text(403, "This link was already used. Run orch review again.")
        self._send(
            200,
            b"{}",
            "application/json",
            {"Set-Cookie": f"{COOKIE.format(port=self.port)}={cookie}; HttpOnly; SameSite=Strict; Path=/"},
        )

    def _answer(self, body: dict | None):
        if body is None or set(body) - ANSWER_FIELDS:
            return self._json(400, _err("refused", "That request could not be read."))
        if not self._cookie_ok():
            return self._json(403, _err("needs_person", "Sign in first: run orch review in your terminal."))
        m = ID_RE.fullmatch(body.get("id") if isinstance(body.get("id"), str) else "")
        digest, verdict, picked, note = (body.get(k) for k in ("digest", "verdict", "picked", "note"))
        if (
            m is None
            or not isinstance(digest, str)
            or not SHA64.fullmatch(digest)
            or verdict not in review.VERDICTS
            or not (picked is None or (isinstance(picked, str) and PICK_RE.fullmatch(picked)))
            or not (note is None or isinstance(note, dict))
        ):
            return self._json(400, _err("refused", "That request could not be read."))
        note_json = None if note is None else json.dumps(note, ensure_ascii=False, separators=(",", ":"))
        if note_json is not None and len(note_json.encode("utf-8")) > review.MAX_NOTE_BYTES:
            return self._json(413, _err("too_large", "A note is at most 8 KB."))
        tid = m.group(1) or m.group(3)
        key = m.group(2) or "review"
        argv = ["review", "answer", tid, key, "--verdict", verdict, "--digest", digest, "--via", "page"]
        if picked:
            argv += ["--picked", picked]
        if note_json is not None:
            argv += ["--note", note_json]
        argv += ["--by", _actor(), "--json"]
        _code, out = run_answer(self.root, argv)
        err = (out.get("error") or {}).get("code")
        status = (
            200 if out.get("ok") else {"too_large": 413, "needs_person": 403, "changed": 409}.get(err, 422)
        )
        self._json(status, out)

    do_PUT = do_DELETE = do_PATCH = lambda self: self._text(405, "not allowed")


def _actor() -> str:
    import getpass

    try:
        who = re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:58]
    except (OSError, KeyError, ImportError):
        who = ""
    return f"human:{who or 'user'}"


def _child(argv: list[str], root: Path, env: dict):
    import subprocess

    return subprocess.run(
        [sys.executable, "-I", "-P", "-m", "orch", *argv],
        cwd=root, env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )  # fmt: skip


def run_answer(root: Path, argv: list[str]) -> tuple[int, dict]:
    """The core, as `sys.executable -I -m orch`, without any agent tool's variables. Returns (0, {"ok": True})
    or (1, {"ok": False, "error": {code, message}})."""
    import subprocess

    try:
        from orch.adapters import human_environ

        env = {**human_environ(os.environ), "ORCH_ROOT": str(root), "ORCH_VIA": "page"}
    except Exception:  # noqa: BLE001 - cannot tell whose environment this is: refuse
        return 1, _err("refused", "orch could not check who is acting here.")
    try:
        r = _child(argv, root, env)
    except subprocess.TimeoutExpired:
        return 1, _err("busy", "That took too long. Please try again.")
    except OSError:
        return 1, _err("refused", "The orch command could not be started.")
    if r.returncode == 0:
        return 0, {"ok": True}
    try:
        e = json.loads(r.stdout)
        code = e.get("code") if isinstance(e.get("code"), str) else "refused"
        msg = str(e.get("error") or "")
    except (ValueError, AttributeError):
        code, msg = "refused", ""
    return 1, _err(code, msg[:200] or "orch could not save that answer.")


class _Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def make_server(root: Path, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1:port (0 = any) with a new session. The caller runs serve_forever()."""
    return _Server(("127.0.0.1", port), partial(Handler, root=root, session=Session()))


# ------------------------------------------------------------------ run file, command line


def run_path(root: Path) -> Path:
    return runs.run_dir(root) / RUN_FILE


def write_run_file(root: Path, port: int, until: str, until_ts: float) -> Path:
    p = run_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "pid": os.getpid(),
        "port": port,
        "url": f"http://127.0.0.1:{port}/",
        "until": until,
        "until_ts": until_ts,
    }
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".review-page-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, p)
    return p


def tunnel_line(port: int) -> str:
    import getpass

    try:
        who = getpass.getuser()
    except (OSError, KeyError, ImportError):
        who = "user"
    return f"ssh -L {port}:127.0.0.1:{port} {who}@{socket.gethostname() or 'host'}"


def running(root: Path) -> dict | None:
    """The review page that runs for this workspace now ({url, until, tunnel, port}), else None."""
    from orch import services

    try:
        d = json.loads(
            run_path(root).read_text(encoding="utf-8")
        )  # lint-allow: our own run file (no secrets)
        port, pid, until_ts = d["port"], d["pid"], float(d["until_ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (
        not (isinstance(port, int) and 0 < port < 65536)
        or not services.pid_alive(pid)
        or until_ts <= time.time()
    ):
        return None
    return {
        "url": f"http://127.0.0.1:{port}/",
        "until": str(d.get("until") or ""),
        "tunnel": tunnel_line(port),
        "port": port,
    }


def parse_until(text: str, now: float | None = None) -> tuple[str, float]:
    """HH:MM (local time) -> (the same, the next time it is that clock time)."""
    m = re.fullmatch(r"([01]?[0-9]|2[0-3]):([0-5][0-9])", (text or "").strip())
    if not m:
        raise Refused("--until is a time of day like 18:30.")
    now = time.time() if now is None else now
    lt = time.localtime(now)
    ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
    if ts <= now:
        ts += 86400
    return f"{int(m.group(1)):02d}:{m.group(2)}", ts


def _has_display() -> bool:
    return sys.platform in ("darwin", "win32") or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def serve(args) -> int:
    root = history.args_root(args)
    if kit_dir() is None:
        print(NO_KIT)
        return 2
    until, until_ts = parse_until(getattr(args, "until", None) or "23:59")
    start = getattr(args, "port", None) or DEFAULT_PORT
    srv = None
    for port in range(start, min(start + PORT_TRIES, 65536)):
        try:
            srv = make_server(root, port)
            break
        except OSError:
            continue
    if srv is None:
        print("No free port was found. Try: orch review --port 8500")
        return 2
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    n = len(review.stack(root))
    print(f"{n} thing{'' if n == 1 else 's'} wait{'s' if n == 1 else ''} on you.")
    print(f"Open: {url}   works on this computer until {until}")
    print(f"On a server? From your laptop: {tunnel_line(port)}   then open the link.")
    sys.stdout.flush()
    write_run_file(root, port, until, until_ts)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="review-page")
    t.start()
    try:
        if not getattr(args, "no_open", False) and _has_display():
            import webbrowser

            token = srv.RequestHandlerClass.keywords["session"].token
            webbrowser.open(f"{url}#k={token}")  # the token only in the fragment: never printed or saved
        while t.is_alive() and time.time() < until_ts:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
        with contextlib.suppress(OSError):
            run_path(root).unlink()
    print("The review page stopped.")
    return 0
