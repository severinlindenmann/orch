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


LAST = {}  # the stack fixture's dashboard server and workspace (a test may give it a page session)


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
    open({str(tmp_path / "status-calls")!r}, "a").write("x")
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
    LAST["srv"], LAST["ws"] = srv, ws
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
    # ORCH-186: a page orch ships is sandboxed too (an opaque origin, never allow-same-origin): it acts with a pass
    assert "sandbox allow-scripts allow-forms" in shipped["Content-Security-Policy"]
    assert "allow-same-origin" not in shipped["Content-Security-Policy"]
    assert "allow-top-navigation" not in shipped["Content-Security-Policy"]
    assert local["Content-Security-Policy"].endswith("; sandbox allow-scripts")


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
    assert call(base + "/addon/viewer/", headers={"Host": "evil.example"})[0] == 401
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


def test_workspace_propose_op_is_read_only_and_answers_the_proposal(act_orch, ws):
    """Settings > Workspace profile > Suggest: no --by (nothing is saved), the answer comes back trimmed."""
    import json as _json
    import threading

    from orch_dashboard import actions

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["config", "propose"]:\n    print(json.dumps({"name": "N" * 99, "description": "One line.", '
        '"tags": ["a", 7, "b", "c", "d", "e"], "icon": "code", "from": ["x"]}))\n    sys.exit(0)\n'
        'if a[:2] in (["addon", "list"]',
        1,
    )
    act_orch.write_text(src)
    assert actions.build_argv("workspace.propose", {}) == ["config", "propose", "--json"]
    with pytest.raises(actions.BadRequest):
        actions.build_argv("workspace.propose", {"x": 1})
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        h = {"Content-Type": "application/json", "Origin": base}
        code, body, _ = call(
            base + "/api/act", "POST", h, _json.dumps({"op": "workspace.propose", "args": {}}).encode()
        )
        assert code == 200
        assert _json.loads(body)["proposal"] == {
            "name": "N" * 60,
            "description": "One line.",
            "tags": ["a", "b", "c", "d"],
            "icon": "code",
        }
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
    assert "script-src" not in h2["Content-Security-Policy"]
    assert (
        "allow-same-origin" not in h2["Content-Security-Policy"]
    )  # sandboxed, its own origin opaque (ORCH-186)


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


def _status_calls(tmp_path):
    f = tmp_path / "status-calls"
    return len(f.read_text()) if f.exists() else 0


def test_fb22_switching_back_to_an_addon_page_does_not_ask_orch_again_for_its_port(
    stack, tmp_path, monkeypatch
):
    """Owner feedback 14 Nov fb22: each switch ran `orch status` again (about 0.2 s) after only 3 s."""
    import orch_dashboard.server as srvmod

    base, _port = stack
    srvmod._PORTS.clear()
    assert call(base + "/addon/viewer/")[0] == 200
    first = _status_calls(tmp_path)
    assert first >= 1
    # the port was found 20 s ago: still known, no second look
    monkeypatch.setattr(srvmod, "_services_stamp", lambda: (1, 1))  # orch's record of what runs is unchanged
    srvmod._PORTS.clear()
    assert call(base + "/addon/viewer/")[0] == 200
    first = _status_calls(tmp_path)
    for key, (stamp, p, st) in list(srvmod._PORTS.items()):
        srvmod._PORTS[key] = (stamp - 20, p, st)
    assert call(base + "/addon/viewer/")[0] == 200
    assert _status_calls(tmp_path) == first


def test_fb22_a_moved_addon_port_is_found_again_without_waiting(stack, tmp_path):
    import orch_dashboard.server as srvmod

    base, _port = stack
    srvmod._PORTS.clear()
    assert call(base + "/addon/viewer/")[0] == 200
    key = next(k for k in srvmod._PORTS if k[1] == "viewer")
    srvmod._PORTS[key] = (srvmod._PORTS[key][0], 1, srvmod._PORTS[key][2])  # a stale port nobody listens on
    assert call(base + "/addon/viewer/")[0] == 200


def test_fb22_static_files_of_an_addon_page_may_be_kept_by_the_browser_the_page_itself_may_not(stack):
    base, _port = stack
    code, _, h = call(base + "/addon/viewer/kit/tokens.css")
    assert code == 200 and h["Cache-Control"].startswith("private, max-age=")
    code, _, h = call(base + "/addon/viewer/web/app.js")
    assert h["Cache-Control"].startswith("private, max-age=")
    code, _, h = call(base + "/addon/viewer/")
    assert h["Cache-Control"] == "no-store"
    code, _, h = call(base + "/addon/viewer/api/state.json")
    assert h["Cache-Control"] == "no-store"


def test_fb22_a_changed_record_of_what_runs_drops_the_remembered_port(stack, tmp_path, monkeypatch):
    """The add-on restarted (running.json changed): the remembered port is not trusted, so a port another add-on
    has taken over can never be shown under this add-on's name and fence."""
    import orch_dashboard.server as srvmod

    base, port = stack
    stamp = {"v": (1, 1)}
    monkeypatch.setattr(srvmod, "_services_stamp", lambda: stamp["v"])
    srvmod._PORTS.clear()
    assert call(base + "/addon/viewer/")[0] == 200
    first = _status_calls(tmp_path)
    key = next(k for k in srvmod._PORTS if k[1] == "viewer")
    srvmod._PORTS[key] = (srvmod._PORTS[key][0] - 20, 1, stamp["v"])  # remembered, and wrong
    stamp["v"] = (2, 1)  # orch's record changed
    code, body, _h = call(base + "/addon/viewer/")
    assert code == 200 and b"hi" in body  # looked up live: the real port, not the remembered one
    assert _status_calls(tmp_path) == first + 1
    assert srvmod._PORTS[key][1] == port


def test_fb22_an_action_clears_every_remembered_port(stack):
    import orch_dashboard.server as srvmod

    base, _port = stack
    srvmod._PORTS[("x", "y")] = (0.0, 5, None)
    call(base + "/api/act", "POST", {"Content-Type": "application/json", "Origin": base}, b"{}")
    assert ("x", "y") not in srvmod._PORTS


class _Person:
    """A page session stand-in: the person when the page secret is sent (the real rule: PageSession.can_act)."""

    revoked = False

    def can_act(self, headers, port):
        return headers.get("X-Orch-Page") == "secret"

    def cookie_ok(self, headers, port):
        return "orch_page" in (headers.get("Cookie") or "")


def test_the_dashboard_vouches_for_a_signed_in_person_to_the_addon_page_from_any_computer(stack, monkeypatch):
    """Owner rule (16 Nov): an add-on page behind the dashboard (Focus, Insights) works for the signed-in person
    from any computer: the dashboard passes its word on (X-Orch-Person with the workspace's private key), never
    for a request without the person's session, and never a key a browser sent."""
    import functools

    from orch import pagesession

    base, _port = stack
    srv = LAST["srv"]
    srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=_Person())
    key = (
        "workspace-vouch-key-" + "k" * 30
    )  # the real one lives in the private key folder (test_vouch in core)
    monkeypatch.setattr(pagesession, "vouch_key", lambda root, create=False: key)
    remote = {"Host": "orch.team.example:8791", "X-Forwarded-For": "203.0.113.7", "Cookie": "orch_page_x=1"}
    code, _, _ = call(base + "/addon/viewer/api/x", headers={**remote, "X-Orch-Page": "secret"})
    assert code == 200 and SEEN[-1][2].get(pagesession.VOUCH_HEADER) == key
    code, _, _ = call(base + "/addon/viewer/api/x", headers={**remote, pagesession.VOUCH_HEADER: key})
    assert (
        code == 200 and pagesession.VOUCH_HEADER not in SEEN[-1][2]
    )  # no session: no word, and none passed on
    j = {"Content-Type": "application/json", "Origin": "https://orch.team.example:8791"}
    code, _, _ = call(base + "/addon/viewer/api/act", "POST", {**remote, **j, "X-Orch-Page": "secret"}, b"{}")
    assert code == 200 and SEEN[-1][2].get(pagesession.VOUCH_HEADER) == key


# ORCH-186: the page orch ships runs in a sandboxed frame and acts with a frame pass for its add-on only.
REMOTE = {"Host": "orch.team.example:8791"}
FRAME = {
    "Origin": "null",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def _with_person(monkeypatch, secret="s1"):
    import functools

    from orch import pagesession

    person = _Person()
    person.secret = secret
    srv = LAST["srv"]
    srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=person)
    monkeypatch.setattr(
        pagesession, "vouch_key", lambda root, create=False: "workspace-vouch-key-" + "k" * 30
    )
    return person


def _mint(base, addon="focus", headers=None):
    h = {
        "Content-Type": "application/json",
        "Origin": base,
        "Sec-Fetch-Site": "same-origin",
        **(headers or {}),
    }
    return call(base + "/api/frame-pass", "POST", h, json.dumps({"addon": addon}).encode())


def test_the_dashboard_page_gets_a_pass_for_a_shipped_page_only(stack, monkeypatch):
    base, _ = stack
    _with_person(monkeypatch)
    code, body, _ = _mint(base, headers={"X-Orch-Page": "secret"})
    assert code == 200 and json.loads(body)["act"] is True and len(json.loads(body)["pass"]) >= 40
    code, body, _ = _mint(base)  # no sign-in on this computer: a read-only pass (it could read anyway)
    assert code == 200 and json.loads(body)["act"] is False
    assert _mint(base, headers=REMOTE)[0] == 403  # another computer without sign-in: none
    assert _mint(base, "viewer", {"X-Orch-Page": "secret"})[0] == 404  # not shipped: never a pass
    assert _mint(base, "nopage", {"X-Orch-Page": "secret"})[0] == 404
    assert _mint(base, headers={"X-Orch-Page": "secret", "Sec-Fetch-Site": "cross-site"})[0] == 403
    assert _mint(base, headers={"X-Orch-Page": "secret", "Origin": "null"})[0] == 403
    # a frame can never mint a pass, not even with its own valid one
    p = json.loads(_mint(base, headers={"X-Orch-Page": "secret"})[1])["pass"]
    assert _mint(base, headers={"X-Orch-Page": "secret", "X-Orch-Frame": p})[0] == 403


def test_a_pass_works_for_its_own_addon_from_any_computer_and_is_readable_by_the_frame(stack, monkeypatch):
    from orch import pagesession

    base, _ = stack
    _with_person(monkeypatch)
    p = json.loads(_mint(base, headers={"X-Orch-Page": "secret"})[1])["pass"]
    for extra in ({}, REMOTE):
        code, _, h = call(base + "/addon/focus/api/x", headers={**FRAME, **extra, "X-Orch-Frame": p})
        assert code == 200 and h["Access-Control-Allow-Origin"] == "null"
        assert SEEN[-1][2].get(pagesession.VOUCH_HEADER)  # the dashboard vouches for the person
        assert "X-Orch-Frame" not in SEEN[-1][2]  # the add-on never sees the pass
    j = {**FRAME, "Content-Type": "application/json", "X-Orch-Frame": p}
    code, _, _ = call(base + "/addon/focus/api/act", "POST", j, b"{}")
    assert code == 200 and SEEN[-1][2].get(pagesession.VOUCH_HEADER)
    # a picture or file address carries it as a query value; the add-on gets the address without it
    code, _, _ = call(
        base + f"/addon/focus/api/file?t=t_abcdef&orch-frame={p}&m=view",
        headers={**REMOTE, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "image"},
    )
    assert code == 200 and SEEN[-1][1] == "/api/file?t=t_abcdef&m=view"


def test_a_pass_is_refused_for_another_addon_another_call_or_another_sign_in(stack, monkeypatch):
    base, _ = stack
    person = _with_person(monkeypatch)
    p = json.loads(_mint(base, headers={"X-Orch-Page": "secret"})[1])["pass"]
    n = len(SEEN)
    code, _, h = call(base + "/addon/viewer/api/x", headers={**FRAME, "X-Orch-Frame": p})
    assert (
        code == 401 and h["Access-Control-Allow-Origin"] == "null"
    )  # readable: the frame asks for a new pass
    assert (
        call(base + "/api/state", headers={**FRAME, "X-Orch-Frame": p})[0] == 401
    )  # not a call a frame makes
    assert call(base + "/addon/focus/api/x", headers={**FRAME, "X-Orch-Frame": "x" * 43})[0] == 401
    assert (
        call(
            base + "/addon/focus/api/x",
            headers={**FRAME, "Origin": "https://evil.example", "X-Orch-Frame": p},
        )[0]
        == 401
    )
    assert call(base + "/addon/focus/api/x", headers=FRAME)[0] == 403  # no pass, cross-site: as before
    person.secret = "s2"  # a new sign-in ends every pass
    assert call(base + "/addon/focus/api/x", headers={**FRAME, "X-Orch-Frame": p})[0] == 401
    person.secret, person.revoked = "s1", True  # so does a revoked session
    assert call(base + "/addon/focus/api/x", headers={**FRAME, "X-Orch-Frame": p})[0] == 401
    assert len(SEEN) == n  # nothing reached an add-on


def test_a_read_only_pass_reads_but_never_acts_or_vouches(stack, monkeypatch):
    from orch import pagesession

    base, _ = stack
    _with_person(monkeypatch)
    p = json.loads(_mint(base)[1])["pass"]
    assert call(base + "/addon/focus/api/x", headers={**FRAME, "X-Orch-Frame": p})[0] == 200
    assert pagesession.VOUCH_HEADER not in SEEN[-1][2]
    j = {**FRAME, "Content-Type": "application/json", "X-Orch-Frame": p}
    call(base + "/addon/focus/api/act", "POST", j, b"{}")
    assert pagesession.VOUCH_HEADER not in SEEN[-1][2]
    code, body, _ = call(
        base + "/api/term/keys", "POST", j, json.dumps({"ticket": "t_abcdef", "items": []}).encode()
    )
    assert code == 403 and body.decode().startswith("Sign in to ")


def test_a_shipped_pages_own_code_loads_in_its_sandboxed_frame_and_nothing_else_does(stack):
    base, _ = stack
    code_of = lambda path, dest="script", extra=None: call(
        base + path,
        headers={**REMOTE, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": dest, **(extra or {})},
    )[0]
    assert code_of("/addon/focus/kit/frame.js") == 200
    assert code_of("/addon/focus/web/focus.css", "style") == 200
    assert code_of("/addon/focus/logo.svg", "image") == 200
    assert code_of("/addon/viewer/web/x.js") in (401, 403)  # not shipped
    assert code_of("/addon/focus/api/x.js") in (401, 403)  # data, whatever its ending
    assert code_of("/addon/focus/web/x.js", "document") in (401, 403)  # not a page's own code
    assert code_of("/addon/focus/t/t_abcdef", "script") in (401, 403)  # not a code file


def test_the_preflight_of_a_frame_call_is_answered_only_for_frame_calls(stack):
    base, _ = stack
    ask = {
        "Origin": "null",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-orch-frame",
    }
    code, _, h = call(base + "/addon/focus/api/act", "OPTIONS", ask)
    assert code == 204 and h["Access-Control-Allow-Origin"] == "null"
    assert "X-Orch-Frame" in h["Access-Control-Allow-Headers"]
    assert call(base + "/api/act", "OPTIONS", ask)[0] == 204
    assert call(base + "/api/state", "OPTIONS", ask)[0] == 405
    assert call(base + "/addon/viewer/api/act", "OPTIONS", ask)[0] == 405
    assert call(base + "/addon/focus/api/act", "OPTIONS", {**ask, "Origin": "https://evil.example"})[0] == 405
    assert (
        call(
            base + "/addon/focus/api/act",
            "OPTIONS",
            {**ask, "Access-Control-Request-Headers": "x-orch-frame,x-orch-page"},
        )[0]
        == 405
    )
    assert (
        call(
            base + "/addon/focus/api/act",
            "OPTIONS",
            {**ask, "Access-Control-Request-Headers": "content-type"},
        )[0]
        == 405
    )


def test_frame_passes_end_expire_and_stay_few():
    from orch_dashboard.framepass import FramePasses

    passes = FramePasses(life=60, limit=3)
    a = passes.mint("focus", True, "tag")
    assert passes.check(a, "tag") == ("focus", True)
    assert (
        passes.check(a, "other") is None
        and passes.check(None, "tag") is None
        and passes.check("short", "tag") is None
    )
    for _ in range(3):
        passes.mint("focus", False, "tag")
    assert passes.check(a, "tag") is None  # the oldest went first
    short = FramePasses(life=-1)
    assert short.check(short.mint("focus", True, "tag"), "tag") is None  # expired
