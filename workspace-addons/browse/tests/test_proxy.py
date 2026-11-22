import base64
import socket

from world import World

from orch_browse.proxy import Filter


def _ask(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                return out
            out += chunk


def _auth(f: Filter) -> bytes:
    return b"Proxy-Authorization: Basic " + base64.b64encode(f"{f.user}:{f.password}".encode()) + b"\r\n"


def test_needs_this_runs_password(monkeypatch, tmp_path):
    w = World()
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_BROWSE_TEST_MAP", w.env_map())
    f = Filter(lambda: ["site.test"], tmp_path / "net.jsonl")
    port = f.start()
    try:
        got = _ask(port, b"GET http://site.test/ HTTP/1.1\r\nHost: site.test\r\n\r\n")
        assert got.startswith(b"HTTP/1.1 407")
        wrong = b"Proxy-Authorization: Basic " + base64.b64encode(b"orch-x:nope") + b"\r\n"
        assert _ask(
            port, b"GET http://site.test/ HTTP/1.1\r\nHost: site.test\r\n" + wrong + b"\r\n"
        ).startswith(b"HTTP/1.1 407")
        ok = _ask(port, b"GET http://site.test/ HTTP/1.1\r\nHost: site.test\r\n" + _auth(f) + b"\r\n")
        assert b"Opening hours" in ok
        assert w.log.of("site") == [("site", "GET", "/")]
        # The run's password never reaches the site.
        assert f.password.encode() not in b"".join(h[2].encode() for h in w.log.hits)
        bad = _ask(port, b"CONNECT evil.test:443 HTTP/1.1\r\nHost: evil.test\r\n" + _auth(f) + b"\r\n")
        assert bad.startswith(b"HTTP/1.1 403") and w.log.of("evil") == []
        assert f.alive()
    finally:
        f.stop()
        w.stop()
    assert not f.alive()


def test_damaged_site_list_allows_nothing(tmp_path):
    def broken():
        raise ValueError("damaged")

    f = Filter(broken)
    assert f.decide("example.com", 443) == (None, "the site list could not be read, so nothing is allowed")


def test_test_map_is_off_outside_a_strict_test_home(monkeypatch):
    monkeypatch.setenv("ORCH_BROWSE_TEST_MAP", "site.test=127.0.0.1:1")
    monkeypatch.delenv("ORCH_HOME_STRICT", raising=False)
    f = Filter(lambda: ["site.test"])
    assert f.mapped == {}
    to, _why = f.decide("site.test", 80)
    assert to is None
