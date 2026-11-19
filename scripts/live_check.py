#!/usr/bin/env python3
"""Live check of the relay and publish servers (ORCH-950). No AI, standard library only.

What must be true:
- both answer /health, their TLS is valid and lasts at least 14 more days;
- the admin pages are closed from the internet: /admin and /admin/api/... answer 404 on the public
  sites, and the admin ports are closed on the server's public address;
- the admin pages are open over the private network (run with --where inside);
- a real round trip works when check workspaces are set up: a relay message from one check workspace
  to another, and a tiny file published, fetched and deleted.

--where outside  : from a machine outside the private network (the GitHub Actions job live-check.yml).
--where inside   : from a machine on the private network (this workspace's automation script). With
                   --outside-from REPO it also reads the newest outside run of live-check.yml (gh).

Writes one result (format orch.livecheck/1, see docs/live-check.md) to --out and a short text to stdout.
Exit 0 = every check passed (skipped parts are not failures), 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

RELAY = "https://relay.severin.io"
PUBLISH = "https://publish.severin.io"
PRIVATE_HOST = "hostinger-vps.nb.severin.io"
ADMIN_PORTS = {"publish private apps": 8410, "publish admin": 8411, "relay admin": 8412}
ADMIN_PATHS = ["/admin", "/admin/", "/admin/api/workspaces"]
MIN_CERT_DAYS = 14
OUTSIDE_MAX_AGE_H = 3
TIMEOUT = 8


def check(name: str, fn: Callable[[], str]) -> dict:
    """Runs one check. fn returns a detail line or raises; Skip marks a part that is not set up."""
    try:
        return {"name": name, "ok": True, "detail": fn()}
    except Skip as e:
        return {"name": name, "ok": None, "detail": str(e)}
    except Exception as e:  # noqa: BLE001 - every failure becomes a red line, never a crash
        return {"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"[:300]}


class Skip(Exception):
    pass


def http_status(url: str, timeout: float = TIMEOUT) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "orch-live-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, b""


def health(base: str) -> str:
    code, body = http_status(base + "/health")
    if code != 200 or body.strip() != b"ok":
        raise AssertionError(f"/health answered {code} {body[:40]!r}")
    return "/health answered ok"


def cert_days(host: str, port: int = 443, now: dt.datetime | None = None) -> int:
    """Days the TLS still lasts; the default context checks the chain and the host name."""
    ctx = ssl.create_default_context()
    with (
        socket.create_connection((host, port), timeout=TIMEOUT) as s,
        ctx.wrap_socket(s, server_hostname=host) as t,
    ):
        cert = t.getpeercert()
    end = dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), dt.UTC)
    return (end - (now or dt.datetime.now(dt.UTC))).days


def tls(base: str) -> str:
    days = cert_days(base.split("://", 1)[1].split("/")[0])
    if days < MIN_CERT_DAYS:
        raise AssertionError(f"TLS ends in {days} days (less than {MIN_CERT_DAYS})")
    return f"TLS valid, {days} days left"


def admin_closed_on_site(base: str) -> str:
    bad = []
    for p in ADMIN_PATHS:
        code, _ = http_status(base + p)
        if code != 404:
            bad.append(f"{p} answered {code}")
    if bad:
        raise AssertionError("; ".join(bad))
    return f"{', '.join(ADMIN_PATHS)} answer 404"


def port_open(host: str, port: int, timeout: float = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def public_address(base: str) -> str:
    return socket.getaddrinfo(base.split("://", 1)[1], 443, socket.AF_INET)[0][4][0]


def admin_ports_closed(host: str) -> str:
    open_ = [f"{n} ({p})" for n, p in ADMIN_PORTS.items() if port_open(host, p)]
    if open_:
        raise AssertionError(f"open on the public address {host}: {', '.join(open_)}")
    return f"{', '.join(str(p) for p in ADMIN_PORTS.values())} closed on {host}"


def admin_open_private(host: str, port: int) -> str:
    code, _ = http_status(f"http://{host}:{port}/admin")
    if code != 200:
        raise AssertionError(f"http://{host}:{port}/admin answered {code}")
    return f"http://{host}:{port}/admin answered 200"


def outside_result(repo: str, now: dt.datetime | None = None, runner=subprocess.run) -> str:
    """The newest run of the outside job (GitHub Actions) must be green and recent."""
    p = runner(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            "live-check.yml",
            "--status",
            "completed",
            "--limit",
            "1",
            "--json",
            "conclusion,status,createdAt,url",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 and "not found on the default branch" in p.stderr:
        raise Skip("the outside job (live-check.yml) is not on the default branch yet")
    if p.returncode != 0:
        raise AssertionError(f"gh run list failed: {p.stderr.strip()[:200]}")
    runs = json.loads(p.stdout or "[]")
    if not runs:
        raise Skip("no finished outside run yet (live-check.yml)")
    r = runs[0]
    started = dt.datetime.fromisoformat(r["createdAt"])
    age_h = ((now or dt.datetime.now(dt.UTC)) - started).total_seconds() / 3600
    if r["conclusion"] != "success":
        raise AssertionError(f"outside run {r['conclusion']}: {r['url']}")
    if age_h > OUTSIDE_MAX_AGE_H:
        raise AssertionError(f"newest outside run is {age_h:.1f} h old: {r['url']}")
    return f"outside run passed {age_h:.1f} h ago"


def orch(ws: str, *args: str) -> dict | list:
    p = subprocess.run(
        [os.environ.get("ORCH_BIN", "orch"), *args, "--json"],
        cwd=ws,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if p.returncode != 0:
        raise AssertionError(f"orch {' '.join(args[:2])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout)


def relay_round_trip(a: str, b: str, wait_s: int = 60) -> str:
    if not (a and b):
        raise Skip("check workspaces not set up (--relay-a, --relay-b)")
    to = orch(b, "relay", "status")
    if not to.get("configured"):
        raise AssertionError("the second check workspace is not connected to the relay")
    nonce = f"live check {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} {os.urandom(4).hex()}"
    orch(a, "relay", "send", to["workspace"], nonce)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        for m in orch(b, "relay", "inbox", "--wait", "20"):
            if nonce in json.dumps(m.get("body", {})):
                return f"message arrived in {wait_s - int(end - time.monotonic())} s"
    raise AssertionError(f"message did not arrive within {wait_s} s")


def publish_round_trip(ws: str, base: str = PUBLISH) -> str:
    if not ws:
        raise Skip("check workspace not set up (--publish-ws)")
    with tempfile.TemporaryDirectory(prefix="orch-live-check-") as d:
        f = Path(d) / "live-check.txt"
        f.write_text(f"orch live check {dt.datetime.now(dt.UTC).isoformat()}\n")
        r = orch(ws, "publish", "file", str(f), "--days", "1", "--note", "orch live check")
    fid = r["id"]
    try:
        for part in ("meta", "blob"):
            code, body = http_status(f"{base}/f/{fid}/{part}")
            if code != 200 or not body:
                raise AssertionError(f"fetch of the published file ({part}) answered {code}")
    finally:
        orch(ws, "publish", "delete", fid)
    code, _ = http_status(f"{base}/f/{fid}/meta")
    if code not in (404, 410):
        raise AssertionError(f"after delete the file answered {code} (expected 404 or 410)")
    return "published, fetched and deleted a test file"


def run(a: argparse.Namespace) -> dict:
    checks = []
    for name, base in (("relay", a.relay), ("publish", a.publish)):
        checks.append(check(f"{name} health", lambda b=base: health(b)))
        checks.append(check(f"{name} TLS", lambda b=base: tls(b)))
        checks.append(
            check(f"{name} admin closed on the public site", lambda b=base: admin_closed_on_site(b))
        )
    if a.where == "outside":
        checks.append(
            check(
                "admin ports closed on the public address",
                lambda: admin_ports_closed(public_address(a.relay)),
            )
        )
    if a.where == "inside":
        checks.append(
            check(
                "publish admin open over the private network",
                lambda: admin_open_private(a.private_host, ADMIN_PORTS["publish admin"]),
            )
        )
        checks.append(
            check(
                "relay admin open over the private network",
                lambda: admin_open_private(a.private_host, ADMIN_PORTS["relay admin"]),
            )
        )
        if a.outside_from:
            checks.append(
                check("check from outside the private network", lambda: outside_result(a.outside_from))
            )
        checks.append(check("relay message round trip", lambda: relay_round_trip(a.relay_a, a.relay_b)))
        checks.append(check("publish file round trip", lambda: publish_round_trip(a.publish_ws, a.publish)))
    failed = [c for c in checks if c["ok"] is False]
    return {
        "schema": "orch.livecheck/1",
        "source": "orch",
        "where": a.where,
        "targets": [a.relay, a.publish],
        "checked_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": not failed,
        "summary": "All checks passed."
        if not failed
        else f"{len(failed)} failed: " + ", ".join(c["name"] for c in failed),
        "checks": checks,
    }


def text(res: dict) -> str:
    mark = {True: "ok  ", False: "FAIL", None: "skip"}
    return "\n".join(
        [res["summary"], *(f"{mark[c['ok']]} {c['name']}: {c['detail']}" for c in res["checks"])]
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--where", choices=["inside", "outside"], required=True)
    ap.add_argument("--relay", default=RELAY)
    ap.add_argument("--publish", default=PUBLISH)
    ap.add_argument("--private-host", default=PRIVATE_HOST)
    ap.add_argument("--outside-from", default="", help="GitHub repo whose live-check.yml runs outside")
    ap.add_argument("--relay-a", default="", help="folder of the check workspace that sends")
    ap.add_argument("--relay-b", default="", help="folder of the check workspace that receives")
    ap.add_argument("--publish-ws", default="", help="folder of the check workspace that publishes")
    ap.add_argument("--out", default="", help="write the result (JSON) here")
    a = ap.parse_args(argv)
    res = run(a)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(a.out).with_suffix(".tmp")
        tmp.write_text(json.dumps(res, indent=2) + "\n")
        tmp.replace(a.out)
    print(text(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
