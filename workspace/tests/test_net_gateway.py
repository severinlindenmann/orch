"""A gateway answer (502/503/504 from a proxy, no orch message) names the address and the likely cause
(ORCH-1026: during the server move a stale DNS cache sent relay sends to an old proxy and the refusal said
only "502")."""

import http.server
import threading

import pytest

from orch import net
from orch.errors import Refused


def _server(code: int, body: bytes, ctype: str):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("code", [502, 503, 504])
def test_gateway_answer_names_the_address_and_dns(code):
    srv = _server(code, b"<html>Bad Gateway</html>", "text/html")
    try:
        with pytest.raises(Refused) as e:
            net.call("GET", f"http://127.0.0.1:{srv.server_port}/v1/messages", timeout=5)
    finally:
        srv.shutdown()
    text = str(e.value)
    assert text.startswith(f"127.0.0.1 answered {code}: something in between")
    assert "DNS" in text and "Try again in a few minutes." in text
    assert e.value.status == code  # callers still decide retries by the code


def test_other_errors_keep_the_short_line_and_a_server_message_wins():
    srv = _server(500, b"oops", "text/plain")
    try:
        with pytest.raises(Refused) as e:
            net.call("GET", f"http://127.0.0.1:{srv.server_port}/x", timeout=5)
    finally:
        srv.shutdown()
    assert str(e.value) == "The server answered 500."
    srv = _server(503, b'{"message": "The relay is being updated."}', "application/json")
    try:
        with pytest.raises(Refused) as e:
            net.call("GET", f"http://127.0.0.1:{srv.server_port}/x", timeout=5)
    finally:
        srv.shutdown()
    assert str(e.value) == "The relay is being updated."
