"""Every data read needs the sign-in, this computer's own address too (ORCH-481, owner 18 Nov).

Ticket files are private on disk; a dashboard that answered any local user or process on 127.0.0.1 would get
around that. Only the page shell and its program files open without the sign-in. Needs orch importable."""

import http.client
import inspect
import json
import re
import threading

import pytest

pytest.importorskip("orch")
from orch import addons, pagelaunch, pagesession

from orch_dashboard import actions, data, server
from orch_dashboard.server import make_server

pytestmark = pytest.mark.real_signin


@pytest.fixture
def live(tmp_path, monkeypatch):
    import os
    import subprocess

    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT"):
            monkeypatch.delenv(k, raising=False)
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)

    def no_child(argv, *a, **k):  # no child `orch`: it would see the real account home
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    srv = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def call(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None, {**(headers or {})})
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def sign_in(root, port):
    tok = pagelaunch.write_launch_token(root, "dashboard")
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    st, ck, body = call(port, "POST", "/session", h, {"token": tok})
    assert st == 200, body
    return ck.split(";")[0]


def _api_reads():
    """Every /api/ address the dashboard reads, taken from its own GET code (a new one is covered by itself)."""
    src = inspect.getsource(server.Handler.do_GET)
    found = set(re.findall(r'"(/api/[a-z/-]+)"', src))
    found |= {"/api/sessions/t_abcdef", "/api/artifacts/t_abcdef", "/api/chat/day/2026-11-18"}
    found |= {"/api/chat/thread/ws_abcdefghij", "/api/addon/focus"}
    found |= {"/addon/focus/api/live", "/addon/focus/", "/view/t_abcdef/artifacts/page.html", "/styleguide/"}
    return sorted(found)


READS = _api_reads()
# a local process sends no browser headers (curl); a page of this app sends same-origin ones: both are refused
WITHOUT = (
    {},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none", "Accept": "application/json"},
)


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_no_read_on_this_computer_without_the_sign_in(live, name):
    _root, port = live
    assert "/api/state" in READS and "/api/term" in READS and "/api/events" in READS
    for path in READS:
        for extra in WITHOUT:
            st, _, body = call(port, "GET", path + "?ticket=t_abcdef", {"Host": f"{name}:{port}", **extra})
            assert st == 401, (path, extra, st)
            assert body.decode().startswith("Sign in to ")  # the page shows the sign-in notice for it


def test_reads_work_after_the_sign_in(live):
    root, port = live
    ck = sign_in(root, port)
    h = {"Host": f"127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin", "Cookie": ck}
    st, _, body = call(port, "GET", "/api/state", h)
    assert st == 200 and "tickets" in json.loads(body)
    for path in ("/api/links", "/api/update-info", "/api/sessions"):
        assert call(port, "GET", path, h)[0] == 200, path
    # a wrong or old cookie is no sign-in
    bad = {**h, "Cookie": ck.split("=", 1)[0] + "=" + "x" * 43}
    assert call(port, "GET", "/api/state", bad)[0] == 401


def test_the_page_shell_and_its_files_open_without_the_sign_in(live):
    """So the sign-in link can run and the page can say how to sign in: no workspace data in any of them."""
    _root, port = live
    h = {"Host": f"127.0.0.1:{port}"}
    for path in ("/", "/app.js", "/session.js", "/style.css", "/pages/home.js", "/kit/kit.css"):
        st, _, _ = call(port, "GET", path, h)
        assert st in (200, 404), path  # 404: a kit file this install lacks; never 401
        assert st != 401, path
    assert call(port, "GET", "/", h)[0] == 200


def test_no_frame_pass_without_the_sign_in(live):
    """The frame pass used to be handed out read-only to any page on this computer: no more."""
    _root, port = live
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Sec-Fetch-Site": "same-origin",
    }
    st, _, body = call(port, "POST", "/api/frame-pass", h, {"addon": "focus"})
    assert st == 403 and body.decode().startswith("Sign in to ")


def test_the_start_check_still_answers_on_this_computer(live, monkeypatch):
    """orch start/stop asks /ready with a challenge; the answer proves the start secret and carries no data."""
    import hashlib
    import hmac

    _root, port = live
    monkeypatch.setenv("ORCH_DASHBOARD_NONCE", "n" * 32)
    c = "ab" * 16
    st, _, body = call(port, "GET", f"/ready?c={c}", {"Host": f"127.0.0.1:{port}"})
    assert st == 200
    assert json.loads(body)["mac"] == hmac.new(b"n" * 32, c.encode(), hashlib.sha256).hexdigest()
    monkeypatch.delenv("ORCH_DASHBOARD_NONCE")
    assert (
        call(port, "GET", f"/ready?c={c}", {"Host": f"127.0.0.1:{port}"})[0] == 401
    )  # no start secret: closed


def test_a_ticket_page_needs_the_sign_in_or_its_key_never_forged_headers(live):
    """A sandboxed ticket page loads its own files without a cookie (opaque origin): by the unguessable key in the
    address a signed-in request was sent on to. Browser headers a local script can forge are no proof."""
    root, port = live
    d = root / ".orch" / "tickets" / "t_abcdef" / "artifacts" / "site"
    d.mkdir(parents=True)
    (d / "index.html").write_text('<link rel="stylesheet" href="style.css">')
    (d / "style.css").write_text("body{color:red}")
    h = {"Host": f"127.0.0.1:{port}"}
    forged = {**h, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "style"}
    assert call(port, "GET", "/view/t_abcdef/artifacts/site/style.css", forged)[0] == 401
    assert call(port, "GET", "/view/t_abcdef/artifacts/site/index.html", h)[0] == 401
    ck = sign_in(root, port)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/view/t_abcdef/artifacts/site/index.html", headers={**h, "Cookie": ck})
    r = c.getresponse()
    r.read()
    where = r.getheader("Location")
    assert r.status == 302 and re.fullmatch(
        r"/view/t_abcdef/k/[0-9a-f]{16}/artifacts/site/index\.html", where
    )
    keyed = where.rsplit("/", 1)[0]
    st, _, body = call(port, "GET", keyed + "/style.css", forged)  # the page's own stylesheet, no cookie
    assert st == 200 and body == b"body{color:red}"
    assert call(port, "GET", keyed.replace(keyed.split("/")[4], "0" * 16) + "/style.css", forged)[0] == 401
    assert call(port, "GET", keyed.replace("t_abcdef", "t_abcdeg") + "/style.css", forged)[0] == 401
