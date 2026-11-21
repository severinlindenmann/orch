"""Every data read of Focus needs the sign-in, this computer's own address too (ORCH-481, owner 18 Nov).

Its own session cookie, or the dashboard's word for a signed-in person in front of it. Only the page shell, its
program files and a ticket page by its unguessable key open without it. Needs orch importable."""

import http.client
import inspect
import json
import re
import threading

import pytest

pytest.importorskip("orch")
from orch import addons, pagelaunch, pagesession

from orch_focus import actions, server
from orch_focus.server import make_server

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
    srv = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    r = c.getresponse()
    return r.status, r.read()


def sign_in(root, port):
    tok = pagelaunch.write_launch_token(root, "focus")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Sec-Fetch-Site": "same-origin",
    }
    c.request("POST", "/session", json.dumps({"token": tok}), h)
    r = c.getresponse()
    assert r.status == 200, r.read()
    return r.getheader("Set-Cookie").split(";")[0]


def _api_reads():
    """Every /api/ address Focus reads, taken from its own GET code (a new one is covered by itself)."""
    src = inspect.getsource(server.Handler.do_GET)
    found = set(re.findall(r'"(/api/[a-z/-]+)"', src))
    found |= {"/api/t/t_abcdef", "/api/t/t_abcdef/sessions", "/api/file?t=t_abcdef&n=1"}
    return sorted(found)


READS = _api_reads()


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_no_read_on_this_computer_without_the_sign_in(live, name):
    _root, port = live
    assert "/api/live" in READS and "/api/tickets" in READS and "/api/events" in READS
    for path in READS:
        for extra in ({}, {"Sec-Fetch-Site": "same-origin"}):
            st, body = get(port, path, {"Host": f"{name}:{port}", **extra})
            assert st == 401, (path, extra, st)
            assert body.decode().startswith("Sign in to ")


def test_reads_work_with_the_own_cookie_or_the_dashboards_word(live):
    root, port = live
    ck = sign_in(root, port)
    st, body = get(port, "/api/live", {"Cookie": ck, "Sec-Fetch-Site": "same-origin"})
    assert st == 200 and "cards" in json.loads(body)
    read_key = pagesession.read_vouch_key(root, create=True)
    act_key = pagesession.vouch_key(root)
    assert read_key and act_key and read_key != act_key
    assert get(port, "/api/live", {pagesession.READ_VOUCH_HEADER: read_key})[0] == 200
    assert get(port, "/api/live", {pagesession.VOUCH_HEADER: act_key})[0] == 200
    # a made-up word, or the read word sent as the word that acts, is nothing
    assert get(port, "/api/live", {pagesession.READ_VOUCH_HEADER: "x" * 64})[0] == 401
    assert get(port, "/api/live", {pagesession.VOUCH_HEADER: read_key})[0] == 401
    assert get(port, "/api/live", {"Cookie": ck.split("=", 1)[0] + "=" + "x" * 43})[0] == 401


ANSWER = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}}


def test_the_read_word_never_acts(live):
    root, port = live
    read_key = pagesession.read_vouch_key(root, create=True)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Sec-Fetch-Site": "same-origin",
        pagesession.READ_VOUCH_HEADER: read_key,
    }
    c.request("POST", "/api/act", json.dumps(ANSWER), h)
    r = c.getresponse()
    assert r.status == 403 and r.read().decode().startswith("Sign in to ")


def test_the_page_shell_opens_without_the_sign_in(live):
    _root, port = live
    assert get(port, "/")[0] == 200
    assert get(port, "/t/t_abcdef")[0] == 200
    assert get(port, "/web/focus.js")[0] in (200, 404)
    assert get(port, "/web/focus.js")[0] != 401
