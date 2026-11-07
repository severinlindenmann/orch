"""Tiny subscriber receiver: records every request body + headers it gets (signed push check, retry check)."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Receiver:
    def __init__(self, port: int = 0, fail_first: int = 0):
        self.got: list[dict] = []
        self.fail_first = fail_first
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                outer.got.append({"t": time.time(), "path": self.path, "headers": dict(self.headers.items()),
                                  "body": body.decode("utf-8", "replace")})
                code = 500 if len(outer.got) <= outer.fail_first else 200
                self.send_response(code)
                self.end_headers()

        self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def start(self):
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def wait(self, n: int, secs: float = 20) -> bool:
        end = time.time() + secs
        while time.time() < end:
            if len(self.got) >= n:
                return True
            time.sleep(0.2)
        return False
