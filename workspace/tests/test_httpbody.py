"""A page server that refuses a POST before reading its body still gets its answer to the client
(orch.httpbody.ReadsWholeBody; WinError 10053 on Windows CI, 21 Nov)."""

import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orch.httpbody import ReadsWholeBody


class _Refuses(BaseHTTPRequestHandler):
    """Answers 403 at once and never reads the body, like a page server's early refusal."""

    timeout = 10

    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path == "/half":  # reads part of the body, then refuses
            self.rfile.read(1)
        self.send_response(403)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"no")


class _Drains(ReadsWholeBody, _Refuses):
    pass


@pytest.fixture
def server():
    made = []

    def start(handler):
        s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        made.append(s)
        return s.server_address[1]

    yield start
    for s in made:
        s.shutdown()
        s.server_close()


def post(port, path, size):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request("POST", path, b"x" * size, {"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


@pytest.mark.parametrize("path", ["/", "/half"])
@pytest.mark.parametrize("size", [1, 2000, 20000, 200000])
def test_an_early_refusal_reaches_the_client(server, path, size):
    port = server(_Drains)
    for _ in range(20):
        assert post(port, path, size) == (403, b"no")


def test_a_read_body_is_not_read_again(server):
    """A handler that reads its whole body leaves nothing to drain, and the next request is answered."""
    left = []
    drained = threading.Event()

    class Reads(ReadsWholeBody, BaseHTTPRequestHandler):
        timeout = 10

        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers["Content-Length"])
            body = self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _drain(self, n):
            left.append(n)
            super()._drain(n)
            drained.set()

    port = server(Reads)
    assert post(port, "/", 3000) == (200, b"x" * 3000)
    assert drained.wait(10)  # the server thread drains after the answer is out
    assert left == [0]
