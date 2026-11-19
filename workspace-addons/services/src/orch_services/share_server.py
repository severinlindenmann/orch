"""The file server behind `orch services share`: one folder, read-only, on 127.0.0.1 only.

Never sits next to another server on the same port: the socket is bound without SO_REUSEADDR (on Windows with
SO_EXCLUSIVEADDRUSE), so a server that listens on every address (`*:<port>`, a dashboard) makes this bind fail
instead of quietly taking the 127.0.0.1 part of that port (report r-1118-2103-ws). Every answer carries the
X-Orch-Share header with this share's mark, so the link check can tell this server from any other one.
"""

from __future__ import annotations

import argparse
import html
import io
import os
import socket
import sys
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HEADER = "X-Orch-Share"
HOST = "127.0.0.1"
PRIVATE = {".orch", ".ssh", ".gnupg", ".git", ".env", ".aws", ".netrc"}  # never served, at any depth


def exclusive(sock: socket.socket) -> None:
    """No sharing of the port with any other socket (set before bind)."""
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True

    def server_bind(self):
        exclusive(self.socket)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    mark = ""
    root = ""

    def end_headers(self):
        self.send_header(HEADER, self.mark)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _allowed(self, path: str) -> bool:
        """The file's real place lies inside the shared folder and on no private folder (.orch, .ssh, ...)."""
        try:
            real = os.path.realpath(path)
            if os.path.commonpath([real, self.root]) != self.root:
                return False
        except ValueError:  # another drive on Windows
            return False
        rel = os.path.relpath(real, self.root)
        return not any(part.lower() in PRIVATE for part in Path(rel).parts)

    def send_head(self):
        """Only files that really lie inside the shared folder: a link that leads out of it (to the home folder,
        say), a private folder or an index page that is such a link is answered as not found."""
        path = self.translate_path(self.path)
        bad = not self._allowed(path)
        if not bad and os.path.isdir(path):
            for index in self.index_pages:
                page = os.path.join(path, index)
                if os.path.lexists(page):
                    bad = not self._allowed(page)
                    break
        if bad:
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, path):
        """The folder's own list, without private folders and without links that lead out of the folder."""
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except OSError:
            self.send_error(404)
            return None
        rows = []
        for name in names:
            full = os.path.join(path, name)
            if not self._allowed(full):
                continue
            shown = name + ("/" if os.path.isdir(full) else "")
            rows.append(f'<li><a href="{urllib.parse.quote(shown)}">{html.escape(shown)}</a></li>')
        title = html.escape(urllib.parse.unquote(self.path.split("?", 1)[0]))
        body = f"<!doctype html><meta charset=utf-8><title>{title}</title><h1>{title}</h1><ul>{''.join(rows)}</ul>"
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)

    def do_POST(self):  # read-only
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, format, *args):
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


def make(folder: Path, port: int, mark: str) -> Server:
    root = os.path.realpath(folder)
    handler = type("ShareHandler", (Handler,), {"mark": mark, "root": root})
    return Server((HOST, port), partial(handler, directory=root))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orch_services.share_server")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--mark", required=True)
    a = ap.parse_args(argv)
    folder = Path(a.dir)
    if not folder.is_dir():
        sys.stderr.write(f"The folder {folder} does not exist.\n")
        return 2
    try:
        srv = make(folder, a.port, a.mark)
    except OSError as e:
        sys.stderr.write(f"Port {a.port} is taken ({e.strerror or e}).\n")
        return 3
    sys.stderr.write(f"Sharing {folder} on http://{HOST}:{a.port}/\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
