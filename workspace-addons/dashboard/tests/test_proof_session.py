"""H1 in the dashboard server: launch token -> session cookie, loopback Host, no X-Forwarded-*, proof on stdin,
the core run as `sys.executable -I -m orch` (never ORCH_BIN). Needs orch importable (runs from workspace/)."""

import http.client
import json
import threading

import pytest

pytest.importorskip("orch")
from orch import (
    addons,
    pageproof,
)
from orch import humanproof as hp

from orch_dashboard import actions
from orch_dashboard.server import make_server


@pytest.fixture
def live(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test").mkdir(
        parents=True
    )  # a test workspace pairs only with a test home (never the real one)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    import os

    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT"):
            monkeypatch.delenv(k, raising=False)
    (acct / ".orch-test" / "home").mkdir()
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    monkeypatch.setenv("ORCH_BIN", "/tmp/planted-orch")  # must never be used

    # No child `orch` here: a child would see the REAL account home (pwd) and fall back to ~/.orch-tool.
    import subprocess

    def no_child(argv, *a, **k):
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(subprocess, "run", no_child)
    srv = make_server(root, 0, orch_bin=pageproof.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def post(port, path, body, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Host": host or f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    c.request("POST", path, json.dumps(body), h)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def session(root, port):
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 204
    return ck.split(";")[0]


def test_launch_token_bootstraps_the_cookie_once(live):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 204 and "HttpOnly" in ck and "SameSite=Strict" in ck and ck.startswith("orch_page=")
    assert post(port, "/session", {"token": tok})[0] == 403  # single use
    assert post(port, "/session", {"token": "x" * 30})[0] == 403


def test_session_refused_through_a_proxy_or_foreign_host(live):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
    assert post(port, "/session", {"token": tok}, {"X-Forwarded-For": "1.2.3.4"})[0] == 403
    assert post(port, "/session", {"token": tok}, {"Forwarded": "for=1.2.3.4"})[0] == 403


def test_click_without_a_session_is_watch_only(live, monkeypatch):
    _root, port = live
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    st, _, _body = post(
        port, "/api/act", {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}}
    )
    assert st == 403 and ran == []


def test_click_with_session_runs_core_with_proof_on_stdin(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    def fake(argv, proof, **kw):
        seen.update(argv=argv, proof=proof, kw=kw)
        return R()

    monkeypatch.setattr(actions, "run_with_proof", fake)
    st, _, _ = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}},
        {"Cookie": ck},
    )
    assert st == 200, seen
    assert "--proof-stdin" not in seen["argv"] and "x" in seen["argv"]  # run_with_proof adds the flag itself
    payload = json.loads(__import__("base64").urlsafe_b64decode(seen["proof"].split(".")[1] + "=="))
    assert payload["op"] == "ticket.answer" and payload["target"] == "t_abc123:q1"
    assert seen["kw"]["orch_bin"] == pageproof.SELF
    assert "ORCH_BIN" not in seen["kw"]["env"]


def test_click_with_session_but_forwarded_is_refused(live):
    root, port = live
    ck = session(root, port)
    st, _, _ = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}},
        {"Cookie": ck, "X-Forwarded-Host": "evil"},
    )
    assert st == 403


def test_orch_bin_from_the_environment_is_ignored():
    argv = pageproof.argv0(pageproof.SELF)
    assert argv[1:5] == ["-I", "-P", "-m", "orch"] and argv[0] == pageproof.sys.executable


def test_handoff_listing_hides_the_command_and_confirm_runs_it_with_a_proof(live, monkeypatch):
    root, port = live
    hp.request_handoff(
        root,
        "ticket.answer",
        "t_abc123:q1",
        "Answer q1",
        "Blue",
        argv=["answer", "t_abc123", "q1", "--", "Blue"],
    )
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/handoffs", headers={"Host": f"127.0.0.1:{port}"})
    items = json.loads(c.getresponse().read())
    assert items and "argv" not in items[0] and items[0]["value"] == "Blue"
    hid = items[0]["id"]
    # no session: watch-only, nothing taken
    assert post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": hid}})[0] == 403
    ck = session(root, port)
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    from orch_dashboard import handoff

    monkeypatch.setattr(
        handoff, "run_with_proof", lambda argv, proof, **kw: seen.update(argv=argv, proof=proof) or R()
    )
    st, _, _ = post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": hid}}, {"Cookie": ck})
    assert st == 200 and seen["argv"][0] == "answer" and seen["proof"].startswith("hp1.")
    assert post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": hid}}, {"Cookie": ck})[0] == 404


def test_second_use_of_a_link_ends_the_session_and_says_so(live):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 204
    st, _, body = post(port, "/session", {"token": tok})
    assert st == 403 and b"Someone else tried to use this sign-in link" in body
    st, _, body = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}},
        {"Cookie": ck.split(";")[0]},
    )
    assert st == 403 and b"Someone else tried" in body  # the first page's cookie no longer mints


def test_one_time_notice_is_shown_once_with_the_core_text(live):
    root, port = live
    d = hp.key_dir(root)
    hp._write_private(
        d / "notices.json", json.dumps([{"kind": "protection_reset", "at": "x", "text": hp.RESET_NOTICE}])
    )

    def get():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/api/notices", headers={"Host": f"127.0.0.1:{port}"})
        return json.loads(c.getresponse().read())

    first = get()
    assert first and first[0]["text"] == hp.RESET_NOTICE[:600]
    assert get() == []  # once
