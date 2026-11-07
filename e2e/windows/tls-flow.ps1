# How orch checks web certificates on Windows (#226, #232), as a standard user with orch's own installed Python:
# a server whose trusted certificate names the host is accepted; a server with a trusted certificate for another
# name is refused by the name check; a local server with a self-signed certificate is refused and never gets
# the token; the Windows check (truststore) is strict. E2E_TLS_HOST (default relay.dev.severin.io) and
# E2E_TLS_MISMATCH_SERVER (default www.google.com) pick the servers.
# Installs orch if a flow before did not. Last log line "RESULT ok" or "RESULT fail: <what>".
$ErrorActionPreference = "Continue"
$log = "$env:USERPROFILE\orch-flow.log"
$fails = @()
function L($m) { Add-Content -Path $log -Value $m }
function Check($ok, $what) { if ($ok) { L "ok: $what" } else { L "FAIL: $what"; $script:fails += $what } }
L ""; L "=== tls (web certificates)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
if (-not (Get-Command orch -ErrorAction SilentlyContinue)) {
    L "--- install"
    try { Get-Content $env:ORCH_INSTALL_PS1 -Raw | Invoke-Expression *>&1 | Out-String | % { L $_ } } catch { L "install threw: $_" }
}
$py = Join-Path (uv tool dir) "orch-workspace\Scripts\python.exe"
Check (Test-Path $py) "orch's own Python found"
$tlsHost = if ($env:E2E_TLS_HOST) { $env:E2E_TLS_HOST } else { "relay.dev.severin.io" }
# a big public server that answers an unknown name with its default (valid) certificate: the name-check target
$mismatchServer = if ($env:E2E_TLS_MISMATCH_SERVER) { $env:E2E_TLS_MISMATCH_SERVER } else { "www.google.com" }
# One Python script: each check prints "ok: ..." or "FAIL: ..." (the same names as the unit tests in test_net_tls.py).
$code = @'
import datetime, http.server, ipaddress, os, socket, ssl, sys, tempfile, threading
from orch import net
from orch.errors import Refused
host = sys.argv[1]
net.time.sleep = lambda s: None  # connection-level retries without waiting
def say(ok, what): print(("ok: " if ok else "FAIL: ") + what, flush=True)
def refused(url, headers=None):  # True only when the certificate check refused it (not any network failure)
    try:
        net.call("GET", url, headers=headers, timeout=20); return False
    except Refused as e:  # ...and it says so in words (no "check your internet")
        return (isinstance(getattr(e.__context__, "reason", None), ssl.SSLCertVerificationError)
                and "security certificate is not valid" in str(e) and "internet" not in str(e))
ctx = net._tls()
say(ctx is not None and ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    and ctx.minimum_version >= ssl.TLSVersion.TLSv1_2, "the Windows check is strict (hostname, certificate, TLS 1.2+)")
try:
    status, body = net.call("GET", f"https://{host}/health", timeout=30)
    say(status == 200, f"https://{host} is accepted (trusted certificate for that name)")
except Refused as e:
    say(False, f"https://{host} is accepted: {e}")
# the name check: ask a big public server (a valid, trusted certificate) for a name it does not have. It answers
# with its default certificate, and orch's check must refuse it as a name mismatch (orch's own context, ctx)
srv_host = sys.argv[2]
try:
    with socket.create_connection((srv_host, 443), timeout=20) as raw, ctx.wrap_socket(raw, server_hostname="wrong-name.example.org"):
        say(False, f"a trusted certificate for another name is refused ({srv_host}: the handshake succeeded)")
except ssl.SSLCertVerificationError as e:
    msg = str(e.verify_message or e.reason or e)
    say("name" in msg.lower() or "mismatch" in msg.lower(), f"a trusted certificate for another name is refused for its name ({srv_host}: {msg})")
except OSError as e:
    say(False, f"a trusted certificate for another name is refused ({srv_host}: no handshake: {type(e).__name__} {e})")
# a local server with a self-signed certificate
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
now = datetime.datetime.now(datetime.UTC)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
d = tempfile.mkdtemp()
open(os.path.join(d, "c.pem"), "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(os.path.join(d, "k.pem"), "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
seen = []
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append(self.headers.get("Authorization", "")); self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
sc = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sc.load_cert_chain(os.path.join(d, "c.pem"), os.path.join(d, "k.pem"))
srv.socket = sc.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"https://127.0.0.1:{srv.server_address[1]}/health"
say(refused(url, {"Authorization": "Bearer tok_secret"}), "a local self-signed server is refused")
say(seen == [], "the self-signed server never got the token")
srv.shutdown()
import shutil; shutil.rmtree(d, ignore_errors=True)  # the throwaway key never stays in %TEMP%
'@
$script = "$env:TEMP\orch-tls-check.py"
$code | Set-Content $script -Encoding UTF8
$out = & $py $script $tlsHost $mismatchServer 2>&1 | Out-String
L $out
foreach ($line in ($out -split "`r?`n")) { if ($line -match '^FAIL: (.+)$') { $fails += $Matches[1] } }  # ok lines are in $out
Check ($out -match 'ok: a local self-signed server is refused') "the TLS check script ran to the end"
Remove-Item $script -ErrorAction SilentlyContinue
if ($fails.Count) { L "RESULT fail: $($fails -join '; ')" } else { L "RESULT ok" }
