"""An add-on's [page] is shown under /addon/<name>/ of the dashboard; both fences stay on."""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orch_dashboard.data import load_state
from orch_dashboard.server import make_server

SEEN = []


class Up(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, body=b"<html>hi __P__</html>"):
        SEEN.append((self.command, self.path, dict(self.headers)))
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header(
            "Content-Security-Policy",
            "script-src 'self'; sandbox allow-scripts"
            if "/page/" in self.path and "/sb/" in self.path
            else "frame-ancestors 'none'",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._reply(b"{}")


@pytest.fixture
def stack(ws, tmp_path):
    SEEN.clear()
    up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    port = up.server_address[1]
    script = tmp_path / "orch"
    script.write_text(f"""#!{sys.executable}
import sys, json
a = sys.argv[1:]
if a[:2] == ["addon", "list"]:
    print(json.dumps([
      {{"name": "viewer", "source": "local", "active": True, "description": "d", "dashboard": {{"label": "Viewer", "icon": "bolt"}},
        "page": {{"path": "/", "label": "Open"}}, "ticket_view": []}},
      {{"name": "focus", "source": "built-in", "active": True, "description": "d", "dashboard": {{"label": "F", "icon": "bolt"}},
        "page": {{"path": "/", "label": "Open"}}, "ticket_view": []}},
      {{"name": "nopage", "active": True, "description": "d", "dashboard": {{"label": "N", "icon": "bolt"}}, "ticket_view": []}}]))
elif a[:2] == ["status", "--json"]:
    print(json.dumps([{{"workspace": {str(ws.resolve())!r}, "addons": [
      {{"addon": "viewer", "running": True, "url": "http://127.0.0.1:{port}/"}},
      {{"addon": "focus", "running": True, "url": "http://127.0.0.1:{port}/"}},
      {{"addon": "nopage", "running": True, "url": "http://127.0.0.1:{port}/"}}]}}]))
else:
    sys.exit(2)
""")
    script.chmod(0o755)
    srv = make_server(ws, 0, orch_bin=str(script))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", port
    srv.shutdown()
    srv.server_close()
    up.shutdown()
    up.server_close()


def call(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_get_is_forwarded_with_the_addons_own_host_and_a_prefix(stack):
    base, port = stack
    code, body, h = call(base + "/addon/viewer/t/t_abcdef?x=1")
    assert code == 200 and b"hi" in body
    _m, path, hd = SEEN[-1]
    assert (
        path == "/t/t_abcdef?x=1"
        and hd["Host"] == f"127.0.0.1:{port}"
        and hd["X-Forwarded-Prefix"] == "/addon/viewer"
    )
    csp = h["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in csp and "frame-ancestors 'none'" not in csp
    assert csp.endswith("; sandbox allow-scripts")  # "viewer" is a local folder: opaque origin (H1)


def test_a_shipped_addon_page_keeps_its_origin_and_a_local_one_does_not(stack):
    base, _ = stack
    _c, _b, shipped = call(base + "/addon/focus/")
    _c, _b, local = call(base + "/addon/viewer/")
    assert "sandbox" not in shipped["Content-Security-Policy"]
    assert "sandbox allow-scripts" in local["Content-Security-Policy"]


def test_an_addon_not_listed_as_shipped_is_sandboxed_fail_closed(ws, tmp_path):
    import orch_dashboard.server as s

    h = s.Handler.__new__(s.Handler)
    h.root, h.orch_bin = ws, str(tmp_path / "missing")
    assert h._shipped("focus") is False  # no list, no proof it is shipped


def test_the_dashboard_marks_which_addons_are_shipped(stack):
    base, _ = stack
    _code, body, _h = call(base + "/api/state")
    by = {a["name"]: a["shipped"] for a in json.loads(body)["addons"]}
    assert by == {"viewer": False, "focus": True, "nopage": False}


def test_only_addons_with_a_page_that_run_are_shown(stack):
    base, _ = stack
    assert call(base + "/addon/nopage/")[0] == 404
    assert call(base + "/addon/ghost/")[0] == 404
    assert call(base + "/addon/viewer/../x")[0] in (404,)
    assert not SEEN


def test_get_from_another_site_or_host_is_refused(stack):
    base, _ = stack
    assert call(base + "/addon/viewer/", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(base + "/addon/viewer/", headers={"Host": "evil.example"})[0] == 421
    assert not SEEN


def test_post_passes_dashboard_fence_then_gets_the_addons_origin(stack):
    base, port = stack
    host = base.split("//")[1]
    j = {"Content-Type": "application/json"}
    ok = call(base + "/addon/viewer/api/act", "POST", {**j, "Origin": base}, b'{"op":"x"}')
    assert ok[0] == 200
    _, _, hd = SEEN[-1]
    assert hd["Origin"] == f"http://127.0.0.1:{port}" and hd["Host"] == f"127.0.0.1:{port}"
    n = len(SEEN)
    for headers in (
        {**j},
        {**j, "Origin": "http://evil.example"},
        {**j, "Origin": base, "Sec-Fetch-Site": "cross-site"},
        {**j, "Origin": "null"},
        {"Origin": base, "Content-Type": "text/plain"},
    ):
        assert call(base + "/addon/viewer/api/act", "POST", headers, b"{}")[0] in (403, 415), headers
    assert call(base + "/addon/viewer/other", "POST", {**j, "Origin": base}, b"{}")[0] == 405
    assert (
        call(base + "/addon/viewer/api/act", "POST", {**j, "Origin": base, "Host": "evil.example"}, b"{}")[0]
        == 403
    )
    assert len(SEEN) == n and host


def test_page_is_in_the_addon_data(stack, ws):
    base, _ = stack
    state = json.loads(call(base + "/api/state")[1])
    assert next(a for a in state["addons"] if a["name"] == "viewer")["page"] == {"path": "/", "label": "Open"}
    assert next(a for a in state["addons"] if a["name"] == "nopage")["page"] is None
    assert load_state(ws)["addons"] == []


def test_addon_connection_detail_has_no_token(ws, tmp_path):
    from orch_dashboard.data import _addon_detail

    assert _addon_detail(ws, "relay") is None  # the fixture link has no address
    (ws / ".orch" / "secrets" / "thing.json").write_text(
        '{"url": "https://u:p@x.example/a", "token": "SECRET"}'
    )
    assert _addon_detail(ws, "thing")["connected"] is False  # user info in the address is never shown
    (ws / ".orch" / "secrets" / "thing.json").write_text(
        '{"url": "https://x.example:8443/a", "token": "SECRET"}'
    )
    d = _addon_detail(ws, "thing")
    assert d == {"connected": True, "address": "https://x.example:8443", "workspaces": []}
    assert _addon_detail(ws, "none") is None


def test_ticket_edit_accepts_a_title_and_never_an_empty_one():
    from orch_dashboard import actions

    argv = actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "title": "New name"})
    assert "--title=New name" in argv
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "title": "  "})


def test_agent_test_op_argv_and_reply(act_orch, ws):
    import json as _json
    import threading

    from orch_dashboard import actions

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["agents", "test"]:\n    print(json.dumps({"name": a[2], "ok": False, "reason": "Codex is not installed."}))\n    sys.exit(1)\n'
        'if a[:1] == ["agents"]:\n    print(json.dumps([{"name": "codex"}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]',
        1,
    )
    act_orch.write_text(src)
    assert actions.build_argv("config.agent.test", {"name": "codex"}) == ["agents", "test", "codex", "--json"]
    for bad in ({"name": "../x"}, {"name": "codex", "x": 1}, {}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("config.agent.test", bad)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        h = {"Content-Type": "application/json", "Origin": base}
        code, body, _ = call(
            base + "/api/act",
            "POST",
            h,
            _json.dumps({"op": "config.agent.test", "args": {"name": "codex"}}).encode(),
        )
        assert code == 200 and _json.loads(body)["test"] == {
            "name": "codex",
            "ok": False,
            "reason": "Codex is not installed.",
        }
        code, _, _ = call(
            base + "/api/act",
            "POST",
            h,
            _json.dumps({"op": "config.agent.test", "args": {"name": "nobody"}}).encode(),
        )
        assert code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_focus_page_files_load_cross_site_with_their_own_sandbox_csp(stack):
    """A sandboxed frame (opaque origin) loads its css/js cross-site: only Focus's GET /page/<ticket>/<file>."""
    base, _ = stack
    cross = {"Sec-Fetch-Site": "cross-site"}
    code, _, h = call(base + "/addon/focus/page/t_abcdef/0123456789abcdef/sb/a%20b/style.css", headers=cross)
    assert code == 200
    assert h["Content-Security-Policy"] == "script-src 'self'; sandbox allow-scripts"
    assert h["Cross-Origin-Resource-Policy"] == "cross-origin"
    assert SEEN[-1][1] == "/page/t_abcdef/0123456789abcdef/sb/a%20b/style.css"
    # nothing else loosens: other add-ons, other Focus paths, other methods
    n = len(SEEN)
    post = {**cross, "Origin": base, "Content-Type": "application/json"}
    assert call(base + "/addon/focus/api/tickets", headers=cross)[0] == 403
    assert call(base + "/addon/focus/page/t_abcdef/0123456789abcdef/..%2fx.css", headers=cross)[0] == 404
    assert call(base + "/addon/focus/page/t_abcdef/0123456789abcdef/x.css", "POST", post, b"{}")[0] in (
        403,
        405,
    )
    assert len(SEEN) == n
    # an add-on that does not answer with a sandbox policy gets no cross-site read, whatever the path
    assert call(base + "/addon/viewer/page/t_abcdef/0123456789abcdef/x.css", headers=cross)[0] == 403
    assert call(base + "/addon/viewer/page/t_abcdef/0123456789abcdef/x.css")[0] == 200
    # a same-site request to a non-page path keeps the dashboard's own CSP
    _, _, h2 = call(base + "/addon/focus/t/t_abcdef")
    assert (
        "script-src" not in h2["Content-Security-Policy"] and "sandbox" not in h2["Content-Security-Policy"]
    )


def test_cross_site_page_path_needs_the_key_segment(stack):
    """F1: without a 16-hex key between ticket and file the cross-site exception does not apply."""
    base, _ = stack
    cross = {"Sec-Fetch-Site": "cross-site"}
    n = len(SEEN)
    for p in (
        "/page/t_abcdef/sb/x.css",
        "/page/t_abcdef/short/sb/x.css",
        "/page/t_abcdef/0123456789ABCDEF/sb/x.css",
    ):
        assert call(base + "/addon/focus" + p, headers=cross)[0] == 403, p
    assert len(SEEN) == n


def test_weak_sandbox_csp_is_not_served_cross_site(stack, monkeypatch):
    """F2: a CSP that only contains the word, or keeps allow-same-origin/popups/forms/top-navigation, is refused."""
    base, _ = stack
    weak_list = (
        "default-src 'self'; report-uri /no-sandbox",
        "sandbox allow-scripts allow-same-origin",
        "sandbox allow-scripts allow-popups",
        "sandbox allow-scripts allow-forms",
        "sandbox allow-scripts allow-top-navigation",
        "script-src 'self'",
    )
    for weak in weak_list:

        def do_GET(self, weak=weak):
            body = b"<script src=/app.js></script>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Security-Policy", weak)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        monkeypatch.setattr(Up, "do_GET", do_GET)
        url = base + "/addon/viewer/page/t_abcdef/0123456789abcdef/x.html"
        assert call(url, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403, weak


def test_proxy_path_tricks(stack):
    base, _ = stack
    cross = {"Sec-Fetch-Site": "cross-site"}
    k = "0123456789abcdef"
    for p in (
        "/addon/focus/page/t_abcdef/../../api/tickets",
        f"/addon/focus/page/t_abcdef//{k}/x.css",
        f"/addon/focus/page/t_abcdef/{k}/%2e%2e/x.css",
        f"/addon/focus/page/t_ABCDEF/{k}/sb/x.css",
        f"/addon/focus/page/t_abcdef/{k}/sb/x.css%3f",
        "/addon/focus/page/t_abcdef",
    ):
        assert call(base + p, headers=cross)[0] in (403, 404), p
