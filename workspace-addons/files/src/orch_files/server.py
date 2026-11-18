"""Loopback HTTP server of the Files page, fenced by the shared UI origin checks (orch_ui.origin).

Reads: the folder tree, one folder, the ticket folders, search, one file's preview and the file itself (only paths
in the index, never a private one; files are sent with a sandbox policy so nothing in them runs). The only write
is a star or the "looked at" time (POST /api/act, same origin only), kept in `.orch/addons/files/state.json`.
While the page is open the index is checked again every 30 seconds in a background thread."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote

from . import extract, index, preview, state, walk

DEFAULT_PORT = 8433
MAX_BODY = 4096
KIT_FILES = (
    "frame.js",
    "tokens.css",
    "components.css",
    "motion.css",
    "interaction.css",
    "widgets.css",
    "results.css",
    "icons.js",
    "overlay.js",
    "select.js",
    "date.js",
    "components.js",
    "widgets.js",
    "results.js",
)
WEB_FILES = ("index.html", "files.js")
PLAIN = "text/plain; charset=utf-8"
TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript"}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; frame-src 'self'; object-src 'self'; "
    "frame-ancestors 'self'; base-uri 'none'"
)
# A file is never a page that runs: whatever is in it (an SVG, a web page), no script, no form, no plugin.
FILE_CSP = (
    "sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; media-src 'self'"
)
ACTIVE_FOR = 90  # seconds after the last page request the background check keeps running
CHECK_EVERY = 30
SAFE_TYPES = {
    "picture": None,
    "video": None,
    "audio": None,
    "pdf": "application/pdf",
    "page": "text/html; charset=utf-8",
}


def _web(name: str) -> bytes:
    return resources.files("orch_files").joinpath("web", name).read_bytes()


def _kit(name: str) -> bytes | None:
    try:
        import orch_ui

        return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()
    except (ImportError, OSError, TypeError):
        return None


def _ctype(row: dict) -> str:
    ext = extract.ext_of(row["name"])
    if row["kind"] in ("md", "text", "code", "data", "table", "change") and ext != "xlsx":
        return PLAIN
    if row["kind"] == "page":
        return "text/html; charset=utf-8"
    if ext == "svg":
        return "image/svg+xml"
    guess = mimetypes.guess_type("x." + ext)[0] if ext else None
    if guess and guess.split("/")[0] in ("image", "video", "audio") or guess == "application/pdf":
        return guess
    return "application/octet-stream"


class Indexer:
    """Keeps the index current while the page is used: on page open, then every 30 s while requests come in."""

    def __init__(self, root: Path):
        self.root = root
        self.last_hit = 0.0
        self.last_run = 0.0
        self.building = False
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.error: str | None = None

    def touch(self, now: bool = False) -> None:
        self.last_hit = time.monotonic()
        if now:
            self.wake.set()

    def run(self) -> None:
        while not self.stop.is_set():
            self.wake.wait(5)
            woke = self.wake.is_set()
            self.wake.clear()
            t = time.monotonic()
            due = t - self.last_run > CHECK_EVERY and t - self.last_hit < ACTIVE_FOR
            if not (woke and t - self.last_run > 2) and not due:
                continue
            self.building = True
            try:
                index.refresh(self.root)
                self.error = None
            except Exception as e:  # noqa: BLE001 - the page says it; the next pass tries again
                self.error = type(e).__name__
            finally:
                self.building = False
                self.last_run = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    timeout = 20

    def __init__(self, *args, root: Path, indexer: Indexer, **kwargs):
        self.root, self.indexer = root, indexer
        self.nonce = os.environ.get("ORCH_FILES_NONCE", "")
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    def _send(self, code, body: bytes, ctype=PLAIN, extra=None, csp=CSP):
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data).encode(), "application/json")

    def _fence(self, method: str, api: bool) -> str | None:
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Files is not available in this install."
        why = check_request(method, self.headers, self.server.server_address[1], api=api)
        if method == "POST" and self.headers.get("Origin") is None:
            return why or "This request was refused (no origin)."
        return why

    def _q(self) -> dict[str, str]:
        qs = parse_qs(self.path.partition("?")[2], keep_blank_values=True)
        return {k: v[0] for k, v in qs.items() if v}

    def do_GET(self):
        path = self.path.partition("?")[0]
        why = self._fence("GET", path.startswith("/api/") or path == "/ready")
        if why:
            return self._send(403, why.encode())
        if path == "/ready" and self.nonce:
            challenge = self.path.partition("?c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", challenge):
                return self._send(404, b"not found")
            mac = hmac.new(self.nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            return self._json({"pid": os.getpid(), "mac": mac})
        if path == "/":
            self.indexer.touch(now=True)
            state.page_opened(self.root)
            prefix = self.headers.get("X-Forwarded-Prefix") or ""
            prefix = prefix if PREFIX.fullmatch(prefix) else ""
            return self._send(200, _web("index.html").replace(b"__P__", prefix.encode()), TYPES["html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            body = _kit(path[5:])
            return (
                self._send(404, b"not found")
                if body is None
                else self._send(200, body, TYPES[path.rsplit(".", 1)[1]])
            )
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES[path.rsplit(".", 1)[1]])
        if not path.startswith("/api/"):
            return self._send(404, b"not found")
        self.indexer.touch()
        q = self._q()
        try:
            return self._api(path, q)
        except FileNotFoundError:
            return self._json({"ready": False, "building": True})
        except (OSError, ValueError):
            return self._send(500, b"That could not be read. Try again in a moment.")

    def _api(self, path: str, q: dict):
        root = self.root
        if path == "/api/status":
            st = index.status(root)
            s = state.load(root)
            st.update(
                building=self.indexer.building or not st["ready"],
                error=self.indexer.error,
                stars=len(s["stars"]),
                new_since=s["prev_seen"],
                new=index.count_since(root, s["prev_seen"]) if st["ready"] and s["prev_seen"] else 0,
                workspace=root.name,
                now=time.time(),
            )
            return self._json(st)
        if path == "/api/tree":
            return self._json(index.tree(root))
        if path == "/api/folder":
            return self._json(index.folder(root, q.get("p", "")))
        if path == "/api/tickets":
            return self._json({"groups": index.ticket_groups(root)})
        if path == "/api/search":
            limit = int(q.get("limit") or 60) if (q.get("limit") or "").isdigit() else 60
            return self._json(
                index.search(root, q.get("q", "")[:200], limit, names_only=q.get("names") == "1")
            )
        if path == "/api/recent":
            return self._json({"files": index.recent(root, 30)})
        if path == "/api/new":
            since = state.load(root)["prev_seen"]
            return self._json(
                {"files": index.recent(root, 200, since=since) if since else [], "since": since}
            )
        if path == "/api/starred":
            return self._json({"files": index.by_paths(root, state.load(root)["stars"])})
        if path == "/api/preview":
            item = preview.build(root, q.get("p", ""))
            return self._json(item) if item else self._send(404, b"not found")
        if path == "/api/file":
            return self._file(q.get("p", ""), q.get("dl") == "1")
        return self._send(404, b"not found")

    def _file(self, path: str, download: bool):
        row = index.one(self.root, path)
        if row is None or row["private"]:
            return self._send(404, b"not found")
        if row["size"] > preview.SERVE_LIMIT:
            return self._send(
                413, b"This file is too large to open here. Open it from its folder on your computer."
            )
        data = walk.read_head(str(self.root), path, preview.SERVE_LIMIT + 1)
        if data is None:
            return self._send(404, b"not found")
        if len(data) > preview.SERVE_LIMIT:
            return self._send(413, b"This file is too large to open here.")
        extra = {}
        ctype = _ctype(row)
        if download:
            ctype = "application/octet-stream"
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(row["name"], safe="")
        return self._send(200, data, ctype, extra, csp=FILE_CSP)

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path != "/api/act":
            return self._refuse()
        why = self._fence("POST", True)
        if why:
            return self._send(403, why.encode())
        if self.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
            return self._send(403, b"This request came from another website and was refused.")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON")
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(n))
        except (ValueError, OSError, RecursionError):
            return self._send(400, b"That request could not be read.")
        if not isinstance(body, dict) or set(body) - {"op", "args"}:
            return self._send(400, b"That request could not be read.")
        op, args = body.get("op"), body.get("args") or {}
        if not isinstance(args, dict):
            return self._send(400, b"That request could not be read.")
        if op in ("star", "unstar"):
            p = args.get("path")
            if not isinstance(p, str) or index.one(self.root, p) is None:
                return self._send(404, b"That file is not here any more.")
            stars = state.star(self.root, p, op == "star")
            return self._json({"result": {"stars": len(stars)}})
        return self._send(400, b"That action is not known here.")

    def _refuse(self):
        why = self._fence(self.command, True)
        return self._send(403, why.encode()) if why else self._send(405, b"not allowed")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _refuse

    def do_HEAD(self):
        return self._refuse()


class FilesServer(ThreadingHTTPServer):
    daemon_threads = True


def make_server(root: Path, port: int = DEFAULT_PORT, background: bool = True) -> FilesServer:
    root = Path(root).resolve()
    indexer = Indexer(root)
    srv = FilesServer(("127.0.0.1", port), partial(Handler, root=root, indexer=indexer))
    srv.indexer = indexer
    if background:
        threading.Thread(target=indexer.run, name="files-index", daemon=True).start()
        indexer.wake.set()
    return srv
