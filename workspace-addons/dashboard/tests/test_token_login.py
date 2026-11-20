"""ORCH-1035: the login screen with a token made on the command line, and the profile picked per browser.

Behind the internal gateway (https, its own host name) and on direct addresses; on any dashboard server,
whoever started it (a server started under an agent tool too)."""

import http.client
import json
import threading

import pytest

pytest.importorskip("orch")

from orch import addons, dashlogin, pagesession, tickets

from orch_dashboard import actions, data, people
from orch_dashboard.server import make_server

GATEWAY = "ws-orch.internal.severin.io"
ACT = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}}


@pytest.fixture
def live(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    import subprocess

    calls = []

    def no_child(argv, *a, **k):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    servers = []

    def start(agent_started=False):
        monkeypatch.setattr(tickets, "agent_tool", (lambda: "claude") if agent_started else (lambda: None))
        srv = make_server(root, 0, orch_bin=pagesession.SELF)
        monkeypatch.setattr(tickets, "agent_tool", lambda: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv.server_address[1]

    yield root, start, calls
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def req(port, method, path, body=None, host=None, https=True, cookie=None, page=None, origin=True):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    host = host or GATEWAY
    h = {"Host": host}
    if origin:
        h["Origin"] = f"{'https' if https else 'http'}://{host}"
    if body is not None:
        h["Content-Type"] = "application/json"
    if cookie:
        h["Cookie"] = cookie
    if page:
        h["X-Orch-Page"] = page
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def login(port, token, **kw):
    st, ck, body = req(port, "POST", "/session", {"login": token}, **kw)
    assert st == 200, body
    return ck, ck.split(";")[0], json.loads(body)["secret"]


def test_login_behind_the_gateway_then_pick_a_profile_then_act(live):
    root, start, calls = live
    port = start()
    token, _ = dashlogin.new_token(root)
    # not signed in: the page learns it must show the login screen
    assert req(port, "GET", "/session/me")[0] == 401
    assert req(port, "GET", "/api/state")[0] == 401
    raw, cookie, page = login(port, token)
    assert "HttpOnly" in raw and "SameSite=Strict" in raw and "Secure" in raw and "Path=/" in raw
    assert cookie.startswith(dashlogin.cookie_name(root) + "=")
    st, _, body = req(port, "GET", "/session/me", cookie=cookie, page=page)
    me = json.loads(body)
    assert st == 200 and me["login"] == "token" and me["needs_profile"] and me["person"] is None
    assert req(port, "GET", "/api/state", cookie=cookie)[0] == 200  # the cookie alone reads
    # acting before a profile is picked: refused with a plain line
    act = ACT
    st, _, body = req(port, "POST", "/api/act", act, cookie=cookie, page=page)
    assert st == 403 and body.decode() == "Pick a profile first."
    st, _, body = req(
        port, "POST", "/session/profile", {"name": "Anna", "add": True}, cookie=cookie, page=page
    )
    assert st == 200 and json.loads(body)["person"] == "Anna"
    assert "Anna" in people.load(root)["people"] and people.current(root) is None  # nothing machine-wide
    req(port, "POST", "/api/act", act, cookie=cookie, page=page)
    assert any("human:Anna" in argv for argv in calls)


def test_two_browsers_act_as_two_people(live):
    root, start, calls = live
    port = start()
    token, _ = dashlogin.new_token(root)
    people.add(root, "Anna")
    people.add(root, "Severin")
    _, c1, p1 = login(port, token)
    _, c2, p2 = login(port, token)
    for c, p, name in ((c1, p1, "Anna"), (c2, p2, "Severin")):
        assert req(port, "POST", "/session/profile", {"name": name}, cookie=c, page=p)[0] == 200
    for c, p, name in ((c1, p1, "Anna"), (c2, p2, "Severin")):
        calls.clear()
        req(port, "POST", "/api/act", ACT, cookie=c, page=p)
        assert any(f"human:{name}" in argv for argv in calls), (name, calls)
    # a profile that is not listed, and the computer's "You: ..." from a token browser, are refused
    assert req(port, "POST", "/session/profile", {"name": "Mallory"}, cookie=c1, page=p1)[0] == 400
    st, _, _ = req(
        port, "POST", "/api/act", {"op": "person.set", "args": {"name": "Severin"}}, cookie=c1, page=p1
    )
    assert st == 400 and people.current(root) is None


def test_wrong_token_revoke_and_logout(live):
    root, start, _ = live
    port = start()
    token, entry = dashlogin.new_token(root)
    st, _, body = req(port, "POST", "/session", {"login": "odt_00000000_" + "A" * 43})
    assert st == 403 and b"does not work" in body
    _, cookie, page = login(port, token)
    assert req(port, "GET", "/session/me", cookie=cookie, page=page)[0] == 200
    dashlogin.revoke_token(root, entry["id"])
    assert req(port, "GET", "/session/me", cookie=cookie, page=page)[0] == 401  # logged out at once
    token2, _ = dashlogin.new_token(root)
    _, cookie, page = login(port, token2)
    st, ck, _ = req(port, "POST", "/session/logout", {}, cookie=cookie, page=page)
    assert st == 200 and "Max-Age=0" in ck
    assert req(port, "GET", "/session/me", cookie=cookie, page=page)[0] == 401


def test_the_login_needs_the_fence(live):
    root, start, _ = live
    port = start()
    token, _ = dashlogin.new_token(root)
    assert req(port, "POST", "/session", {"login": token}, origin=False)[0] == 403
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(
        "POST",
        "/session",
        json.dumps({"login": token}),
        {"Host": GATEWAY, "Origin": "https://evil.example", "Content-Type": "application/json"},
    )
    assert c.getresponse().status == 403


def test_too_many_wrong_tokens_wait_a_minute(live):
    root, start, _ = live
    port = start()
    token, _ = dashlogin.new_token(root)
    for _ in range(10):
        assert req(port, "POST", "/session", {"login": "nope"})[0] == 403
    st, _, body = req(port, "POST", "/session", {"login": "nope"})
    assert st == 429 and b"Wait a minute" in body
    assert req(port, "POST", "/session", {"login": token})[0] == 200  # the right token is never locked out


def test_works_on_a_server_an_agent_started_and_after_a_restart_on_another_port(live):
    root, start, _ = live
    token, _ = dashlogin.new_token(root)
    port = start(agent_started=True)
    _, cookie, page = login(port, token)
    assert (
        req(port, "POST", "/session/profile", {"name": "Anna", "add": True}, cookie=cookie, page=page)[0]
        == 200
    )
    other = start()  # a new server on another port: the same browser is still signed in, with its profile
    st, _, body = req(other, "GET", "/session/me", cookie=cookie, page=page)
    assert st == 200 and json.loads(body)["person"] == "Anna"


def test_direct_address_over_http_has_no_secure_flag(live):
    root, start, _ = live
    port = start()
    token, _ = dashlogin.new_token(root)
    raw, cookie, page = login(port, token, host="10.0.0.5:8791", https=False)
    assert "Secure" not in raw
    st, _, body = req(port, "GET", "/session/me", host="10.0.0.5:8791", https=False, cookie=cookie, page=page)
    assert st == 200 and json.loads(body)["login"] == "token"


def test_the_sign_in_link_still_works(live):
    from orch import pagelaunch

    root, start, _ = live
    port = start()
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = req(port, "POST", "/session", {"token": tok}, host=f"127.0.0.1:{port}", https=False)
    assert st == 200 and ck.startswith(f"orch_page_dashboard_{port}=")
    cookie, page = ck.split(";")[0], json.loads(body)["secret"]
    st, _, body = req(
        port, "GET", "/session/me", host=f"127.0.0.1:{port}", https=False, cookie=cookie, page=page
    )
    assert st == 200 and json.loads(body)["login"] == "link"


def test_without_a_profile_a_token_login_cannot_report_or_type(live):
    root, start, _ = live
    port = start()
    token, _ = dashlogin.new_token(root)
    _, cookie, page = login(port, token)
    for path in ("/api/diag/report", "/api/term/keys"):
        st, _, _ = req(port, "POST", path, {"x": 1}, cookie=cookie, page=page)
        assert st == 403, path


def test_a_frame_pass_of_a_token_login_ends_with_it(live):
    from orch_dashboard import framepass

    root, _, _ = live
    token, entry = dashlogin.new_token(root)
    s = dashlogin.login(root, token)
    passes = framepass.FramePasses()
    header, file = passes.issue("focus", True, "tag", s["sid"])
    assert passes.owner(header) == s["sid"] and passes.owner(file) == s["sid"]
    assert passes.owner(passes.issue("focus", True, "tag")[0]) is None  # a sign-in link's pass has no owner
    assert dashlogin.alive(root, s["sid"])["sid"] == s["sid"]
    dashlogin.revoke_token(root, entry["id"])
    assert dashlogin.alive(root, s["sid"]) is None
    assert dashlogin.alive(root, "../etc") is None
