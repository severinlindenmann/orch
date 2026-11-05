import json
import urllib.error
import urllib.request

import pytest

from orch_dashboard.data import find_workspace, load_state


def get(url, method="GET"):
    req = urllib.request.Request(url, method=method, data=b"x" if method != "GET" else None)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_state_reads_contract_ticket(ws):
    s = load_state(ws)
    assert s["workspace"] == "Pilatus"
    ids = {t["id"] for t in s["tickets"]}
    assert "t_7k3f9q" in ids and "t_weekly01" in ids
    assert s["skipped"] == 1  # the broken file
    t = next(t for t in s["tickets"] if t["id"] == "t_7k3f9q")
    assert t["ext"]["dashboard"] == {"pinned": True}  # unknown fields kept
    assert len(t["checklist"]) == 3 and t["questions"][0]["answer"] is None


@pytest.mark.xfail(reason='contract changed in PR #52; rewritten in lane B (dashboard: scheduler is an add-on view now)', strict=True)
def test_scheduler_rows(ws):
    rows = load_state(ws)["scheduler"]
    by = {r["ticket"]: r for r in rows}
    assert by["t_weekly01"]["kind"] == "recurring" and by["t_weekly01"]["cron"] == "0 8 * * 1"
    assert by["t_weekly01"]["next_run"] == "2026-11-09T08:00:00Z"
    assert by["t_weekly01"]["last_exit"] == 1 and by["t_7k3f9q"]["last_exit"] is None
    assert by["t_7k3f9q"]["kind"] == "once" and by["t_7k3f9q"]["wake_at"] == "2026-11-05T07:00:00Z"


def test_inbox_seen_flag_and_no_secrets(ws):
    s = load_state(ws)
    first = next(m for m in s["inbox"] if m["id"] == "m_a1b2c3d4e5f6g7h8")
    assert first["seen"] is True and "weekly report" in first["text"]
    assert any(not m["seen"] for m in s["inbox"])
    assert "orn_SECRET" not in json.dumps(s)
    assert s["relay"] is True


def test_http_state_and_static(server):
    code, body, _h = get(server + "/api/state")
    assert code == 200 and json.loads(body)["workspace"] == "Pilatus"
    for p in ("/", "/app.js", "/style.css", "/tokens.css", "/logo.svg"):
        assert get(server + p)[0] == 200, p
    assert get(server + "/../../etc/passwd")[0] == 404
    assert get(server + "/.orch/secrets/relay.json")[0] == 404


def test_read_only_server_refuses_writes(server):
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        assert get(server + "/api/state", m)[0] == 405


def test_binds_loopback_only(ws):
    from orch_dashboard.server import make_server
    srv = make_server(ws, 0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_find_workspace_walks_up(ws):
    sub = ws / "a" / "b"
    sub.mkdir(parents=True)
    assert find_workspace(sub) == ws.resolve()


def test_rejects_foreign_host_header(server):
    import http.client
    port = int(server.rsplit(":", 1)[1])
    for host, want in (("evil.example.com", 421), (f"evil.example.com:{port}", 421), (f"localhost:{port}", 200),
                       (f"127.0.0.1:{port}", 200)):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/api/state", headers={"Host": host})
        assert c.getresponse().status == want, host


def test_inbox_shows_display_names_not_ids(ws):
    state = load_state(ws)
    senders = {m["from"] for m in state["inbox"]}
    assert "Your phone" in senders and "Another workspace" in senders or "Reports" in senders
    assert not any(s.startswith(("ws_", "ph_")) for s in senders)
    assert state["names"]["ws_reports001"] == "Reports"


def test_snapshot_state_has_no_names_and_unknown_sender_is_not_admin(tmp_path):
    from orch_dashboard.data import _who, load_state

    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    assert load_state(tmp_path, include_inbox=False)["names"] == {}
    assert _who("admin", {}) == "Admin"
    assert _who("someone", {}) == "Unknown sender"
