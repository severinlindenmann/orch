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


def test_scheduler_is_not_a_dashboard_concept(ws):
    s = load_state(ws)
    assert "scheduler" not in s and s["addons"] == []  # no orch command, no add-ons: no trace of any add-on


def test_inbox_seen_flag_and_no_secrets(ws, fake_orch):
    s = load_state(ws, orch_bin=str(fake_orch))
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


def test_inbox_shows_display_names_not_ids(ws, fake_orch):
    state = load_state(ws, orch_bin=str(fake_orch))
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


def test_addon_endpoint_serves_only_active_tabs(ws, fake_orch):
    import threading

    from orch_dashboard.server import make_server
    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        st = json.loads(get(base + "/api/state")[1])
        assert [a["name"] for a in st["addons"]] == ["scheduler"]
        code, body, _ = get(base + "/api/addon/scheduler")
        assert code == 200 and json.loads(body)["state"] == "ok"
        assert get(base + "/api/addon/wiki")[0] == 404  # installed, not active
        assert get(base + "/api/addon/..%2F..%2Fx")[0] == 404
        assert get(base + "/api/addon/scheduler", "POST")[0] == 405
        assert get(base + "/blocks.js")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_tickets_come_from_the_orch_command_when_there_is_one(ws, fake_orch):
    t = json.loads((ws / ".orch" / "tickets" / "t_7k3f9q.json").read_text())
    t["title"] = "From the command"
    (fake_orch.parent / "tickets.json").write_text(json.dumps([t]))
    src = fake_orch.read_text().replace('elif a[1:] == ["view", "--json"]:',
                                        'elif a[:2] == ["ticket", "list"]:\n    print((d / "tickets.json").read_text())\nelif a[1:] == ["view", "--json"]:')
    fake_orch.write_text(src)
    s = load_state(ws, orch_bin=str(fake_orch))
    assert [x["title"] for x in s["tickets"]] == ["From the command"]


def test_ticket_list_asks_for_finished_tickets_too(ws, fake_orch):
    """`orch ticket list` hides done/dropped unless --all: without it they vanished from the dashboard (found by e2e A12)."""
    calls = fake_orch.parent / "calls.txt"
    fake_orch.write_text(fake_orch.read_text().replace(
        "mode = (d", f'open({str(calls)!r}, "a").write(" ".join(a) + "\\n")\nmode = (d', 1))
    load_state(ws, orch_bin=str(fake_orch))
    assert "ticket list --all --json" in calls.read_text()


def test_foreign_origin_never_triggers_a_pull(ws, fake_orch):
    import http.client
    import threading

    from orch_dashboard.server import make_server
    runs = fake_orch.parent / "runs.txt"
    fake_orch.write_text(fake_orch.read_text().replace("mode = (d", f'open({str(runs)!r}, "a").write("x") if a[1:] == ["view", "--json"] else None\nmode = (d'))
    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for hdr, want in (({"Origin": "https://evil.example"}, 403), ({"Origin": f"http://localhost:{port}"}, 403),
                          ({"Sec-Fetch-Site": "cross-site"}, 403), ({"Origin": f"http://127.0.0.1:{port}"}, 200), ({}, 200)):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request("GET", "/api/addon/scheduler", headers={"Host": f"127.0.0.1:{port}", **hdr})
            assert c.getresponse().status == want, hdr
        assert runs.read_text() == "xx"  # only the two same-origin requests ran the add-on
    finally:
        srv.shutdown()
        srv.server_close()


def test_no_inbox_unless_the_relay_addon_is_on(ws, fake_orch):
    """relay.json and inbox files are there, but the relay add-on is off (or unknown): no Inbox at all."""
    s = load_state(ws)
    assert s["relay"] is False and s["inbox"] is None and s["names"] == {}
    rows = [a for a in json.loads((fake_orch.parent / "addons.json").read_text()) if a["name"] != "relay"]
    (fake_orch.parent / "addons.json").write_text(json.dumps(rows))
    s = load_state(ws, orch_bin=str(fake_orch))
    assert s["relay"] is False and s["inbox"] is None
