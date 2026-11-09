"""H1 in the Focus server: launch token -> session cookie, loopback Host, no X-Forwarded-*, proof on stdin,
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

from orch_focus import actions
from orch_focus.server import make_server


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
    tok = hp.write_launch_token(root, "focus")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 204
    return ck.split(";")[0]


def test_launch_token_bootstraps_the_cookie_once(live):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 204 and "HttpOnly" in ck and "SameSite=Strict" in ck and ck.startswith("orch_page=")
    assert post(port, "/session", {"token": tok})[0] == 403  # single use
    assert post(port, "/session", {"token": "x" * 30})[0] == 403


def test_session_refused_through_a_proxy_or_foreign_host(live):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
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


def test_focus_check_remove_edit_reopen_and_wont_do_need_a_session_proof(live):
    """An agent posting to Focus's act endpoint (no session cookie) can not change a person's Won't do."""
    _root, port = live
    for op, args in (
        ("check.remove", {"ticket": "t_abc123", "check": "c1"}),
        ("check.edit", {"ticket": "t_abc123", "check": "c1", "text": "x"}),
        ("check.reopen", {"ticket": "t_abc123", "check": "c1"}),
        ("check.wont_do", {"ticket": "t_abc123", "check": "c1"}),
    ):
        st, _, body = post(port, "/api/act", {"op": op, "args": args})
        assert st == 403, (op, body)
    from orch_focus import actions

    assert actions.proof_for("check.edit", {"ticket": "t_a", "check": "c1"}) == (
        "check.wont_do_undo",
        "t_a:c1",
    )
    assert actions.proof_for("check.remove", {"ticket": "t_a", "check": "c1"}) == (
        "check.wont_do_undo",
        "t_a:c1",
    )
