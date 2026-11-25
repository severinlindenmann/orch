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

Run by orch automation (ORCH_ROOT set), the inside check is the schedule: it does nothing while the workspace
is paused (orch pause), stops after RUNS_PER_DAY runs in 24 hours, and with --outside-from it starts the
outside job itself when GitHub's own hourly plan dropped it (issue #2657).

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
DISPATCH_AFTER_MIN = 50  # GitHub's hourly plan started the outside job this recently: no extra run
RUNS_PER_DAY = 30  # automatic runs in a rolling 24 h: the hourly plan plus a few Try again (R8.6)
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


def fetch(
    req: urllib.request.Request, timeout: float, tries: int = 2, headers: dict | None = None
) -> tuple[int, bytes]:
    """Status and start of the body (response headers into `headers` when given). A network error is
    tried once more, so one lost packet does not alert the owner; an HTTP answer is final."""
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if headers is not None:
                    for k, v in r.headers.items():  # the first one counts, as in browsers
                        headers.setdefault(k.lower(), v)
                return r.status, r.read(1 << 20)
        except urllib.error.HTTPError as e:
            if headers is not None and e.headers:
                for k, v in e.headers.items():
                    headers.setdefault(k.lower(), v)
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
    words = body.strip().split()
    if code != 200 or not words or words[0] != b"ok":  # `ok`, then the release when the build named one
        raise AssertionError(f"/health answered {code} {body[:40]!r}")
    return "/health answered " + b" ".join(words).decode("ascii", "replace")[:80]


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


def github_runs(repo: str) -> tuple[int, dict]:
    """Newest finished run of live-check.yml through GitHub's REST API (public repo: no login)."""
    url = f"https://api.github.com/repos/{repo}/actions/workflows/live-check.yml/runs?status=completed&per_page=1"
    req = urllib.request.Request(
        url, headers={"User-Agent": "orch-live-check", "Accept": "application/vnd.github+json"}
    )
    h: dict = {}
    try:
        code, body = fetch(req, 20, headers=h)
    except OSError as e:
        raise Skip(f"GitHub not reachable just now ({e})") from e
    # GitHub allows 60 calls an hour per address without a login, shared by everything on this computer:
    # a used-up limit says nothing about the outside job, so it is a skip like an unreachable GitHub
    if code == 429 or (code == 403 and h.get("x-ratelimit-remaining") == "0"):
        raise Skip("GitHub's call limit for this computer is used up just now; read again next time")
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


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=False)


def start_outside(repo: str, now: dt.datetime | None = None, run=gh) -> str:
    """GitHub drops or delays its hourly plan (issue #2657), so the inside run starts the outside job when the
    newest one is older than DISPATCH_AFTER_MIN. The hourly cron stays as a fallback. A gh failure is a skip:
    a missing outside run fails the freshness check above within OUTSIDE_MAX_AGE_H."""
    p = run("run", "list", "-R", repo, "--workflow", "live-check.yml", "-L", "1", "--json", "createdAt")
    if p.returncode != 0:
        raise Skip(f"gh could not list the outside runs ({(p.stderr or '').strip()[:120]})")
    runs = json.loads(p.stdout or "[]")
    if runs:
        started = dt.datetime.fromisoformat(runs[0]["createdAt"])
        age_min = ((now or dt.datetime.now(dt.UTC)) - started).total_seconds() / 60
        if age_min < DISPATCH_AFTER_MIN:
            raise Skip(f"not needed: the newest outside run started {age_min:.0f} min ago")
    p = run("workflow", "run", "live-check.yml", "-R", repo)
    if p.returncode != 0:
        raise Skip(f"gh could not start the outside run ({(p.stderr or '').strip()[:120]})")
    return "started the next outside run"


def automation_root() -> Path | None:
    """The workspace whose automation runs this check (it sets ORCH_ROOT), or None for a run by hand."""
    r = os.environ.get("ORCH_ROOT")
    return Path(r) if r else None


def paused(root: Path) -> bool:
    """`orch pause` holds all automation in the workspace (the same file core's brake writes)."""
    return (root / ".orch" / "run" / "paused.json").is_file()


def count_run(root: Path, now: float | None = None) -> bool:
    """Notes this automatic run; False (and nothing noted) when RUNS_PER_DAY already ran in the last 24 h."""
    f = root / ".orch" / "run" / "live-check-runs.json"
    t = time.time() if now is None else now
    try:
        runs = [x for x in json.loads(f.read_text()) if isinstance(x, (int, float)) and t - x < 86400]
    except (OSError, ValueError, TypeError):
        runs = []
    if len(runs) >= RUNS_PER_DAY:
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps([*runs, t]) + "\n")
    tmp.replace(f)
    return True


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
    sender = orch(a, "relay", "status").get("workspace")
    contacts = orch(b, "relay", "contacts")
    for c in contacts.get("items", []) if isinstance(contacts, dict) else []:
        if c.get("id") == sender and c.get("state") != "accepted" and c.get("held"):
            raise AssertionError(
                "the message is held: the second check workspace has not accepted the first one yet "
                f"(a person runs, in its folder: orch relay contacts accept {sender} --fingerprint "
                f"'{c.get('fingerprint')}')"
            )
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
                lambda: admin_ports_closed(public_address(a.relay)),
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
            if getattr(a, "scheduled", False):
                checks.append(check("start the next outside check", lambda: start_outside(a.outside_from)))
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
    root = automation_root()
    a.scheduled = root is not None
    if root is not None:
        if paused(root):
            print(
                "Automation is paused here, so the live check did not run; turn it back on with: orch resume"
            )
            return 0
        if not count_run(root):
            print(
                f"The live check already ran {RUNS_PER_DAY} times on its own in 24 hours, so it stops here; "
                "look at why it starts so often (orch automation list) or run it yourself."
            )
            return 1
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
