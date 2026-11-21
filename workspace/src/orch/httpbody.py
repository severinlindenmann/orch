"""Read the rest of a request body before the connection closes, for the local page servers.

A server that answers early (a refusal before the body is read, a body over the limit) and then closes the
socket with request bytes still unread makes the operating system reset the connection instead of closing
it. Windows then drops the answer already on its way, and the client sees WinError 10053/10054 instead of
the 400 or 403 (CI, 21 Nov: test_diag_api, test_review_server). Linux and macOS can do the same under load.

`ReadsWholeBody` goes first in the bases of a BaseHTTPRequestHandler: it counts what the handler reads of
the body and, after the answer is sent, reads and drops what is left (at most `body_drain_max` bytes,
waiting at most `body_drain_wait` seconds), so the close is a normal one. Handlers need no change.
"""

from __future__ import annotations

import contextlib


class _CountedBody:
    """The request's rfile while a request is handled: counts the body bytes the handler reads."""

    def __init__(self, raw, length: int):
        self._raw = raw
        self.left = length

    def _took(self, data):
        if data:
            self.left = max(0, self.left - len(data))
        return data

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.left
        return self._took(self._raw.read(n))

    def read1(self, n=-1):
        return self._took(self._raw.read1(self.left if n is None or n < 0 else n))

    def readline(self, limit=-1):
        return self._took(self._raw.readline(limit))

    def readinto(self, b):
        got = self._raw.readinto(b)
        if got:
            self.left = max(0, self.left - got)
        return got

    def __getattr__(self, name):
        return getattr(self._raw, name)


class ReadsWholeBody:
    """Mixin for BaseHTTPRequestHandler (list it before the handler class): drains the unread body after each
    request."""

    body_drain_max = 1 << 20
    body_drain_wait = 2.0

    def parse_request(self):
        ok = super().parse_request()
        if ok:
            try:
                n = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                n = 0
            if n > 0:
                self.rfile = _CountedBody(self.rfile, n)
        return ok

    def handle_one_request(self):
        try:
            super().handle_one_request()
        finally:
            body = self.rfile
            if isinstance(body, _CountedBody):
                self.rfile = body._raw
                self._drain(body.left)

    def _drain(self, left: int):
        if left <= 0:
            return
        self.close_connection = True  # a body not used up never shares its connection with a next request
        if left > self.body_drain_max:
            return  # too much to read: the reset is the lesser evil
        with contextlib.suppress(OSError, ValueError):
            old = self.connection.gettimeout()
            self.connection.settimeout(self.body_drain_wait)
            try:
                while left > 0:
                    chunk = self.rfile.read(min(left, 65536))
                    if not chunk:
                        break
                    left -= len(chunk)
            finally:
                self.connection.settimeout(old)
