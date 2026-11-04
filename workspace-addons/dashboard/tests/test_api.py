import json
import urllib.error
import urllib.request

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


def test_scheduler_rows(ws):
    rows = load_state(ws)["scheduler"]
    by = {r["ticket"]: r for r in rows}
    assert by["t_weekly01"]["kind"] == "recurring" and by["t_weekly01"]["cron"] == "0 8 * * 1"
    assert by["t_weekly01"]["next_run"] == "2026-11-09T08:00:00Z"
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
