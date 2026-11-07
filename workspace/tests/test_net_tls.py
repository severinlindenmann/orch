"""TLS checks of orch.net, the only HTTPS client (relay, publish), #232: an untrusted server is refused
before it sees a token, the Windows context (truststore) is strict, and a broken Windows install fails
closed in plain words."""

import datetime
import http.server
import ipaddress
import ssl
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from orch import net
from orch.errors import Refused


def _self_signed(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    crt, pem = tmp_path / "cert.pem", tmp_path / "key.pem"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return crt, pem


@pytest.fixture
def untrusted_server(tmp_path):
    """HTTPS on 127.0.0.1 with a self-signed certificate; records the Authorization headers it got."""
    seen: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server's name)
            seen.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(*_self_signed(tmp_path))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()
    srv.server_close()


def test_an_untrusted_certificate_is_refused_before_the_token_is_sent(untrusted_server, monkeypatch):
    url, seen = untrusted_server
    monkeypatch.setattr(net.time, "sleep", lambda s: None)  # connection-level retries without waiting
    net._tls.cache_clear()
    with pytest.raises(Refused, match="reach"):
        net.call("GET", url + "/health", headers={"Authorization": "Bearer tok_secret"}, timeout=10)
    assert seen == []  # the handshake failed: the server never got a request, so never the token


@pytest.mark.skipif(sys.platform != "win32", reason="truststore is installed on Windows only")
def test_the_windows_context_is_strict():
    net._tls.cache_clear()
    ctx = net._tls()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_a_windows_install_without_truststore_fails_closed_in_plain_words(monkeypatch):
    monkeypatch.setattr(net.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "truststore", None)  # import raises ImportError
    net._tls.cache_clear()
    try:
        with pytest.raises(Refused, match="Install orch again"):
            net.call("GET", "https://relay.example/health")
    finally:
        net._tls.cache_clear()
