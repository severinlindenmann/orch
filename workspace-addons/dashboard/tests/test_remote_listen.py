"""Remote listening (ORCH-106): the dashboard answers other computers itself, opt-in, with no proxy in front.

The second socket shares the loopback server's sign-in (one cookie name, one session). On it no name of this
computer is trusted: every read and action needs the person's session from a sign-in link."""

import contextlib
import http.client
import json
import socket
import threading

import pytest

pytest.importorskip("orch")
from orch import addons, pagelaunch, pagesession

from orch_dashboard import actions, cli, data, remote
from orch_dashboard.server import make_server

NAME = "dash.example.org"
ANS = {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _outside_ip() -> str | None:
    """An address of this computer that is not loopback (no packet is sent), or None."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") or ip == "0.0.0.0" else ip
    return None


@pytest.fixture
def ws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    import os

    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT"):
            monkeypatch.delenv(k, raising=False)
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)

    import subprocess

    def no_child(argv, *a, **k):
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    return root


@pytest.fixture
def live(ws):
    """A real dashboard with remote listening on all addresses at a fixed port."""
    rport = _free_port()
    srv = make_server(ws, 0, orch_bin=pagesession.SELF, remote=("0.0.0.0", rport))
    assert srv.remote_server is not None, srv.remote_error
    for s in (srv, srv.remote_server):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield ws, srv.server_address[1], rport
    srv.remote_server.shutdown()
    srv.shutdown()
    srv.server_close()


def req(port, method, path, headers, body=None, at="127.0.0.1"):
    c = http.client.HTTPConnection(at, port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None, headers)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def outside(port, cookie=None, secret=None, host=None):
    """What a browser on another computer sends straight to the dashboard (no proxy, no forwarded headers)."""
    h = {"Host": host or f"{NAME}:{port}", "Origin": f"http://{host or f'{NAME}:{port}'}"}
    h["Content-Type"] = "application/json"
    h["Sec-Fetch-Site"] = "same-origin"
    if cookie:
        h["Cookie"] = cookie
    if secret:
        h["X-Orch-Page"] = secret
    return h


def sign_in(root, rport, at="127.0.0.1"):
    url = pagelaunch.printable_launch_url(root, "dashboard", f"http://{NAME}:{rport}")
    token = url.split("#launch=")[1]
    st, ck, body = req(rport, "POST", "/session", outside(rport), {"token": token}, at=at)
    assert st == 200, body
    return ck.split(";")[0], json.loads(body)["secret"]


def test_sign_in_link_opens_the_dashboard_on_the_remote_port_with_no_proxy(live, monkeypatch):
    root, port, rport = live
    ran = []

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: ran.append(argv) or R())
    cookie, secret = sign_in(root, rport)
    # one session for both sockets: the cookie is named after the loopback port
    assert cookie.startswith(f"orch_page_dashboard_{port}=")
    assert req(rport, "GET", "/api/state", outside(rport, cookie))[0] == 200
    st, _, body = req(
        rport, "POST", "/api/act", outside(rport, cookie, secret), {"op": "answer", "args": ANS}
    )
    assert st == 200 and ran, body
    st, _, body = req(rport, "POST", "/api/act", outside(rport, cookie), {"op": "answer", "args": ANS})
    assert st == 403 and body.decode().startswith("Sign in to ")  # the cookie alone is no session


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]", NAME])
def test_nothing_is_trusted_on_the_remote_port_before_sign_in(live, host):
    """A name of this computer in Host proves nothing on the remote port: any computer can send it."""
    _root, _port, rport = live
    h = outside(rport, host=f"{host}:{rport}")
    assert req(rport, "GET", "/api/state", h)[0] == 421
    assert req(rport, "GET", "/view/t_abc123/x.png", h)[0] == 421
    forged = {**h, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "image"}
    assert req(rport, "GET", "/view/t_abc123/artifacts/x.png", forged)[0] == 421
    assert req(rport, "GET", "/", h)[0] == 200  # the page shell (no data), so the sign-in can run
    st, _, body = req(rport, "POST", "/api/act", h, {"op": "answer", "args": ANS})
    assert st == 403 and body.decode().startswith("Sign in to ")
    assert req(rport, "POST", "/api/diag", h, {"events": []})[0] == 403


def test_the_loopback_port_is_unchanged(live):
    _root, port, _rport = live
    h = {"Host": f"127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"}
    assert req(port, "GET", "/api/state", h)[0] == 200


def test_a_session_from_the_remote_port_also_counts_on_the_loopback_port(live):
    root, port, rport = live
    cookie, _secret = sign_in(root, rport)
    assert req(port, "GET", "/api/state", outside(port, cookie, host=f"{NAME}:{port}"))[0] == 200


def test_reached_from_an_outside_address(live):
    """The real path: a connection to an address of this computer that is not loopback."""
    root, _port, rport = live
    ip = _outside_ip()
    if ip is None:
        pytest.skip("this computer has no address besides loopback")
    cookie, _ = sign_in(root, rport, at=ip)
    assert req(rport, "GET", "/api/state", outside(rport, cookie), at=ip)[0] == 200
    assert req(rport, "GET", "/api/state", outside(rport, host=f"127.0.0.1:{rport}"), at=ip)[0] == 421


def test_a_busy_remote_port_leaves_the_dashboard_local_and_says_why(ws):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        rport = busy.getsockname()[1]
        srv = make_server(ws, 0, orch_bin=pagesession.SELF, remote=("127.0.0.1", rport))
        try:
            assert srv.remote_server is None and f"port {rport}" in srv.remote_error
        finally:
            srv.server_close()


def test_off_by_default_no_second_socket(ws):
    srv = make_server(ws, 0, orch_bin=pagesession.SELF)
    try:
        assert srv.remote_server is None and srv.remote_error is None
    finally:
        srv.server_close()
    assert remote.settings(ws) is None and cli._listen(ws) == (None, None)


def test_the_setting_turns_on_and_off(ws, capsys):
    assert cli.main(["--dir", str(ws), "remote", "on", "--port", "8791", "--name", "My-Server.example"]) == 0
    assert "after signing in" in capsys.readouterr().out
    assert remote.settings(ws) == {"listen": "0.0.0.0", "port": 8791, "name": "my-server.example"}
    assert cli._listen(ws) == (("0.0.0.0", 8791), None)
    assert pagelaunch.remote_base(ws, "dashboard") == "http://my-server.example:8791"
    assert pagelaunch.remote_base(ws, "focus") is None
    assert cli.main(["--dir", str(ws), "remote", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"] == "http://my-server.example:8791"
    assert cli.main(["--dir", str(ws), "remote", "off"]) == 0
    assert remote.settings(ws) is None and pagelaunch.remote_base(ws, "dashboard") is None
    assert "[dashboard]" in (ws / ".orch" / "config.toml").read_text()  # the table stays, the keys go


@pytest.mark.parametrize(
    "argv",
    [
        ["remote", "on"],  # no port
        ["remote", "on", "--port", "80"],
        ["remote", "on", "--port", "8791", "--listen", "not-an-address"],
        ["remote", "on", "--port", "8791", "--listen", "127.0.0.1"],  # this computer only
        ["remote", "on", "--port", "8791", "--name", "evil.example:1/x"],
        ["remote", "on", "--port", "8791", "--name", "bad name"],
    ],
)
def test_a_bad_setting_is_refused_and_nothing_is_saved(ws, argv):
    assert cli.main(["--dir", str(ws), *argv]) == 2
    assert remote.settings(ws) is None


def test_a_broken_file_setting_keeps_the_dashboard_local(ws):
    (ws / ".orch" / "config.toml").write_text('[dashboard]\nlisten = "0.0.0.0"\nlisten_port = "x"\n')
    listen, why = cli._listen(ws)
    assert listen is None and "port" in why
    assert pagelaunch.remote_base(ws, "dashboard") is None


def test_only_a_person_lets_other_computers_in(ws, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    assert cli.main(["--dir", str(ws), "remote", "on", "--port", "8791"]) == 2
    assert remote.settings(ws) is None
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: True)  # a test folder may (e2e lane)
    assert cli.main(["--dir", str(ws), "remote", "on", "--port", "8791"]) == 0


def _go(port, secret, host):
    return req(port, "GET", f"/go/{secret}", {"Host": host})


def test_the_sign_in_bookmark_signs_in_again_and_a_new_one_kills_the_old(live):
    """The standing sign-in link (owner's /go bookmark, built in): each visit gives a fresh one-time link."""
    root, port, rport = live
    secret = pagelaunch.standing_link_secret(root)
    assert pagelaunch.standing_link_secret(root) == secret  # stable until renewed
    c = http.client.HTTPConnection("127.0.0.1", rport, timeout=10)
    c.request("GET", f"/go/{secret}", headers={"Host": f"{NAME}:{rport}"})
    r = c.getresponse()
    loc = r.getheader("Location")
    assert r.status == 302 and loc.startswith("/#launch=")
    st, ck, body = req(rport, "POST", "/session", outside(rport), {"token": loc.split("=", 1)[1]})
    assert st == 200, body
    cookie = ck.split(";")[0]
    assert req(rport, "GET", "/api/state", outside(rport, cookie))[0] == 200
    new = pagelaunch.standing_link_secret(root, new=True)
    assert new != secret
    assert _go(rport, secret, f"{NAME}:{rport}")[0] == 404  # the old bookmark is dead
    assert _go(rport, new, f"{NAME}:{rport}")[0] == 302
    assert _go(port, new, f"127.0.0.1:{port}")[0] == 302  # the loopback port knows it too


@pytest.mark.parametrize("sent", ["", "x", "a" * 43, "../../etc"])
def test_a_wrong_or_missing_bookmark_is_a_plain_404(live, sent):
    root, _port, rport = live
    assert _go(rport, sent or "a" * 43, f"{NAME}:{rport}")[0] == 404  # no bookmark made yet
    pagelaunch.standing_link_secret(root)
    assert _go(rport, sent or "b" * 43, f"{NAME}:{rport}")[0] == 404
    assert pagelaunch.remove_standing_link(root)
    assert not pagelaunch.standing_link_ok(root, sent)


def test_only_a_person_makes_the_bookmark(ws, monkeypatch, capsys):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    assert cli.main(["--dir", str(ws), "remote", "link"]) == 2
    with pytest.raises(Exception, match="Only a person"):
        pagelaunch.standing_link_secret(ws)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    assert cli.main(["--dir", str(ws), "remote", "on", "--port", "8791", "--name", NAME]) == 0
    capsys.readouterr()
    assert cli.main(["--dir", str(ws), "remote", "link", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"].startswith(f"http://{NAME}:8791/go/")
    assert cli.main(["--dir", str(ws), "remote", "link", "--remove"]) == 0
