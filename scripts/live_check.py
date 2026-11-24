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
import errno
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
# the server's private name: the admin listeners themselves (direct path, plain http on 8411/8412)
SERVER_PRIVATE = "hostinger-vps.nb.severin.io"
# the admin pages as people open them: Management's https gateway on the private network (no port)
ADMIN_GATEWAY = {
    "publish admin": "https://publish-admin.internal.severin.io/admin",
    "relay admin": "https://relay-admin.internal.severin.io/admin",
}
ADMIN_PORTS = {"publish private apps": 8410, "publish admin": 8411, "relay admin": 8412}
ADMIN_PATHS = ["/admin", "/admin/", "/admin/api/workspaces"]
MIN_CERT_DAYS = 14
MIN_HSTS_DAYS = 180
OUTSIDE_MAX_AGE_H = 3
TIMEOUT = 8
RETRY_S = 5


def check(name: str, fn: Callable[[], str]) -> dict:
    """Runs one check. fn returns a detail line or raises; Skip marks a part that is not set up.
    `ms` is how long the check took."""
    t = time.monotonic()
    try:
        r = {"name": name, "ok": True, "detail": fn()}
    except Skip as e:
        r = {"name": name, "ok": None, "detail": str(e)}
    except Exception as e:  # noqa: BLE001 - every failure becomes a red line, never a crash
        r = {"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"[:300]}
    return {**r, "ms": round((time.monotonic() - t) * 1000)}


class Skip(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer of its own: a public /admin that redirects to a missing page is not 404,
    and a private page that redirects elsewhere is not 200."""

    def redirect_request(self, *a, **k):
        return None


urlopen = urllib.request.build_opener(_NoRedirect).open


def fetch(
    req: urllib.request.Request, timeout: float, tries: int = 2, headers: dict | None = None
) -> tuple[int, bytes]:
    """Status of the first answer (redirects are not followed) and start of the body (response headers
    into `headers` when given). A network error is tried once more, so one lost packet does not alert
    the owner; an HTTP answer is final."""
    for n in range(tries):
        try:
            with urlopen(req, timeout=timeout) as r:
                if headers is not None:
                    for k, v in r.headers.items():  # the first one counts, as in browsers
                        headers.setdefault(k.lower(), v)
                return r.status, r.read(1 << 20)
        except urllib.error.HTTPError as e:
            return e.code, b""
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(RETRY_S)
    raise AssertionError("unreachable")


def http_status(url: str, timeout: float = TIMEOUT) -> tuple[int, bytes]:
    return fetch(urllib.request.Request(url, headers={"User-Agent": "orch-live-check"}), timeout)


def hsts(base: str) -> str:
    """The site tells browsers to use https only, for at least MIN_HSTS_DAYS (set in the Caddy site)."""
    h: dict = {}
    fetch(
        urllib.request.Request(base + "/health", headers={"User-Agent": "orch-live-check"}),
        TIMEOUT,
        headers=h,
    )
    value = h.get("strict-transport-security", "")
    names = [d.split("=", 1)[0].strip().lower() for d in value.split(";") if d.strip()]
    ages = [
        d.split("=", 1)[1].strip().strip('"')
        for d in value.split(";")
        if "=" in d and d.split("=", 1)[0].strip().lower() == "max-age"
    ]
    age = ages[0] if len(ages) == 1 and len(names) == len(set(names)) else ""
    if not age.isdigit() or int(age) < MIN_HSTS_DAYS * 86400:
        raise AssertionError(
            f"Strict-Transport-Security is {value or 'missing'!r} (need max-age of {MIN_HSTS_DAYS} days)"
        )
    return f"Strict-Transport-Security max-age {int(age) // 86400} days"


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


# this machine has no route to the address (e.g. no IPv6 here): the port could not be looked at
NO_ROUTE = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT}


def port_open(host: str, port: int, timeout: float = 5) -> bool | None:
    """True open, False closed, None when this machine cannot reach the address at all."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as e:
        return None if e.errno in NO_ROUTE else False


def public_addresses(*bases: str) -> list[str]:
    """Every public IPv4 and IPv6 address of the sites' names, so a port open on a second address or on
    IPv6 does not pass."""
    out: list[str] = []
    for base in bases:
        host = base.split("://", 1)[1].split("/")[0].split(":")[0]
        for fam, *_, addr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            if fam in (socket.AF_INET, socket.AF_INET6) and addr[0] not in out:
                out.append(addr[0])
    if not out:
        raise AssertionError(f"no public address for {', '.join(bases)}")
    return out


def admin_ports_closed(hosts: str | list[str]) -> str:
    hosts = [hosts] if isinstance(hosts, str) else hosts
    open_, unreachable = [], []
    for h in hosts:
        states = {n: port_open(h, p) for n, p in ADMIN_PORTS.items()}
        open_ += [f"{n} ({ADMIN_PORTS[n]}) on {h}" for n, s in states.items() if s]
        if all(s is None for s in states.values()):
            unreachable.append(h)
    if open_:
        raise AssertionError(f"open on the public address: {', '.join(open_)}")
    if len(unreachable) == len(hosts):
        raise AssertionError(f"no public address reachable from here ({', '.join(hosts)})")
    ports = ", ".join(str(p) for p in ADMIN_PORTS.values())
    checked = [h for h in hosts if h not in unreachable]
    tail = f" ({', '.join(unreachable)} not reachable from here)" if unreachable else ""
    return f"{ports} closed on {', '.join(checked)}{tail}"


def admin_open_private(host: str, port: int) -> str:
    code, _ = http_status(f"http://{host}:{port}/admin")
    if code != 200:
        raise AssertionError(f"http://{host}:{port}/admin answered {code}")
    return f"http://{host}:{port}/admin answered 200"


def github_runs(repo: str) -> tuple[int, dict]:
    """Newest finished run of live-check.yml through GitHub's REST API (public repo: no login)."""
    url = f"https://api.github.com/repos/{repo}/actions/workflows/live-check.yml/runs?status=completed&per_page=1"
    req = urllib.request.Request(
        url, headers={"User-Agent": "orch-live-check", "Accept": "application/vnd.github+json"}
    )
    try:
        code, body = fetch(req, 20)
    except OSError as e:
        raise Skip(f"GitHub not reachable just now ({e})") from e
    return code, json.loads(body) if code == 200 else {}


def admin_gateway(url: str) -> str:
    code, _ = http_status(url)
    if code != 200:
        raise AssertionError(f"{url} answered {code}")
    return f"{url} answered 200"


def outside_result(repo: str, now: dt.datetime | None = None, fetch=github_runs) -> str:
    """The newest finished run of the outside job (GitHub Actions) must be green and recent."""
    code, data = fetch(repo)
    if code == 404:
        raise Skip("the outside job (live-check.yml) is not on the default branch yet")
    if code != 200:
        raise AssertionError(f"GitHub answered {code} for the outside runs")
    runs = data.get("workflow_runs") or []
    if not runs:
        raise Skip("no finished outside run yet (live-check.yml)")
    r = runs[0]
    started = dt.datetime.fromisoformat(r["created_at"])
    age_h = ((now or dt.datetime.now(dt.UTC)) - started).total_seconds() / 3600
    if r["conclusion"] != "success":
        raise AssertionError(f"outside run {r['conclusion']}: {r['html_url']}")
    if age_h > OUTSIDE_MAX_AGE_H:
        raise AssertionError(f"newest outside run is {age_h:.1f} h old: {r['html_url']}")
    return f"outside run passed {age_h:.1f} h ago"


def orch(ws: str, *args: str) -> dict | list:
    p = subprocess.run(
        [os.environ.get("ORCH_BIN", "orch"), *args, "--json"],
        cwd=ws,
        # the automation runs with ORCH_ROOT set to its own workspace; the check folder must be used instead
        env={k: v for k, v in os.environ.items() if k != "ORCH_ROOT"},
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
        checks.append(check(f"{name} https only (HSTS)", lambda b=base: hsts(b)))
        checks.append(
            check(f"{name} admin closed on the public site", lambda b=base: admin_closed_on_site(b))
        )
    if a.where == "outside":
        checks.append(
            check(
                "admin ports closed on the public address",
                lambda: admin_ports_closed(public_addresses(a.relay, a.publish)),
            )
        )
    if a.where == "inside":
        checks.append(
            check(
                "publish admin open over the private network",
                lambda: admin_open_private(a.private_host or SERVER_PRIVATE, ADMIN_PORTS["publish admin"]),
            )
        )
        checks.append(
            check(
                "relay admin open over the private network",
                lambda: admin_open_private(a.private_host or SERVER_PRIVATE, ADMIN_PORTS["relay admin"]),
            )
        )
        if not a.private_host:  # the gateway exists only in production
            for name, url in ADMIN_GATEWAY.items():
                checks.append(
                    check(f"{name} through the private https gateway", lambda u=url: admin_gateway(u))
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
    ap.add_argument(
        "--private-host",
        default="",
        help="one host for both admin listeners (default: the server's private name); skips the gateway",
    )
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
