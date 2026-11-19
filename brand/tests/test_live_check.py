"""The live check of relay and publish (scripts/live_check.py, ORCH-950) says the right thing.

No network: a local HTTP server stands in for the sites, a fake runner for gh.
"""

import datetime as dt
import http.server
import importlib.util
import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_check", ROOT / "scripts" / "live_check.py")
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


def serve(routes: dict[str, tuple[int, bytes]]):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = routes.get(self.path, (404, b"not found"))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


@pytest.fixture
def site():
    servers = []

    def make(routes):
        s, url = serve(routes)
        servers.append(s)
        return url

    yield make
    for s in servers:
        s.shutdown()


def test_health_needs_ok(site):
    assert "ok" in lc.health(site({"/health": (200, b"ok\n")}))
    with pytest.raises(AssertionError):
        lc.health(site({"/health": (502, b"bad gateway")}))


def test_admin_on_public_site_must_be_404(site):
    assert "404" in lc.admin_closed_on_site(site({}))
    with pytest.raises(AssertionError, match="/admin answered 200"):
        lc.admin_closed_on_site(site({"/admin": (200, b"portal")}))
    # a login wall is not enough: the public site must not have the admin page at all
    with pytest.raises(AssertionError, match="401"):
        lc.admin_closed_on_site(site({"/admin/api/workspaces": (401, b"")}))


def test_admin_open_private(site):
    url = site({"/admin": (200, b"portal")})
    host, port = url.removeprefix("http://").split(":")
    assert "200" in lc.admin_open_private(host, int(port))
    with pytest.raises(OSError):  # nothing listens: check() turns it into a red line
        lc.admin_open_private(host, _free_port())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_admin_ports_closed(monkeypatch):
    monkeypatch.setattr(lc, "port_open", lambda h, p, timeout=5: False)
    assert "closed" in lc.admin_ports_closed("192.0.2.1")
    monkeypatch.setattr(lc, "port_open", lambda h, p, timeout=5: p == 8412)
    with pytest.raises(AssertionError, match="relay admin"):
        lc.admin_ports_closed("192.0.2.1")


def gh(stdout="", rc=0, stderr=""):
    return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout, stderr)


NOW = dt.datetime(2026, 11, 19, 22, 0, tzinfo=dt.UTC)


def run_json(conclusion, created="2026-11-19T21:17:00Z", status="completed"):
    return json.dumps([{"conclusion": conclusion, "status": status, "createdAt": created, "url": "u"}])


def test_outside_result():
    assert "success" in lc.outside_result("r", NOW, gh(run_json("success")))
    with pytest.raises(AssertionError, match="failure"):
        lc.outside_result("r", NOW, gh(run_json("failure")))
    with pytest.raises(AssertionError, match="old"):
        lc.outside_result("r", NOW, gh(run_json("success", "2026-11-19T10:00:00Z")))
    assert "in_progress" in lc.outside_result("r", NOW, gh(run_json("", status="in_progress")))
    with pytest.raises(lc.Skip):
        lc.outside_result(
            "r", NOW, gh(rc=1, stderr="HTTP 404: workflow live-check.yml not found on the default branch")
        )
    with pytest.raises(AssertionError, match="gh run list failed"):
        lc.outside_result("r", NOW, gh(rc=1, stderr="HTTP 401"))


def test_round_trips_skip_when_not_set_up():
    with pytest.raises(lc.Skip):
        lc.relay_round_trip("", "")
    with pytest.raises(lc.Skip):
        lc.publish_round_trip("")


def test_check_turns_errors_into_lines():
    assert lc.check("x", lambda: "fine")["ok"] is True
    assert lc.check("x", lambda: (_ for _ in ()).throw(lc.Skip("later")))["ok"] is None
    bad = lc.check("x", lambda: 1 / 0)
    assert bad["ok"] is False and "ZeroDivisionError" in bad["detail"]


def test_result_and_exit_code(site, tmp_path, monkeypatch):
    up = site({"/health": (200, b"ok")})
    monkeypatch.setattr(lc, "tls", lambda b: "TLS valid, 80 days left")
    out = tmp_path / "r.json"
    assert (
        lc.main(
            [
                "--where",
                "inside",
                "--relay",
                up,
                "--publish",
                up,
                "--private-host",
                "127.0.0.1",
                "--out",
                str(out),
            ]
        )
        == 1
    )  # nothing answers /admin on the private side
    res = json.loads(out.read_text())
    assert res["schema"] == "orch.livecheck/1" and res["ok"] is False
    assert {c["name"] for c in res["checks"] if c["ok"] is False} == {
        "publish admin open over the private network",
        "relay admin open over the private network",
    }
    assert [c["ok"] for c in res["checks"] if "round trip" in c["name"]] == [None, None]
    monkeypatch.setattr(lc, "admin_open_private", lambda h, p: "200")
    assert lc.main(["--where", "inside", "--relay", up, "--publish", up, "--out", str(out)]) == 0
    assert json.loads(out.read_text())["summary"] == "All checks passed."
