#!/usr/bin/env python3
"""Send one push through Apple's SANDBOX APNs to a development device token (a Simulator on Apple silicon gets one).
Only a real push starts the notification service extension in the Simulator; `simctl push` never does (ORCH-1296).
usage: apns-sandbox-send.py <key.p8> <key id> <team id> <device token> <payload.json> [topic]
Needs openssl and curl. The key file is read only to sign the request token; nothing is printed but the HTTP status."""
import base64, json, subprocess, sys, time


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def der_to_raw(der: bytes) -> bytes:
    # ECDSA-Sig-Value ::= SEQUENCE { r INTEGER, s INTEGER } -> r||s, 32 bytes each
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = b""
    for _ in range(2):
        assert der[i] == 0x02
        n = der[i + 1]
        v = der[i + 2:i + 2 + n].lstrip(b"\0")
        out += v.rjust(32, b"\0")
        i += 2 + n
    return out


def main() -> int:
    key, kid, team, token, payload = sys.argv[1:6]
    topic = sys.argv[6] if len(sys.argv) > 6 else "io.severin.orch"
    head = b64(json.dumps({"alg": "ES256", "kid": kid}).encode())
    claims = b64(json.dumps({"iss": team, "iat": int(time.time())}).encode())
    msg = f"{head}.{claims}".encode()
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=msg, capture_output=True, check=True).stdout
    jwt = f"{head}.{claims}.{b64(der_to_raw(der))}"
    r = subprocess.run(["curl", "-sS", "--http2", "-o", "/dev/stderr", "-w", "%{http_code}",
                        "-H", f"authorization: bearer {jwt}", "-H", f"apns-topic: {topic}", "-H", "apns-push-type: alert",
                        "--data-binary", f"@{payload}", f"https://api.sandbox.push.apple.com/3/device/{token}"],
                       capture_output=True, text=True)
    print("apns", r.stdout, r.stderr.strip())
    return 0 if r.stdout == "200" else 1


if __name__ == "__main__":
    sys.exit(main())
