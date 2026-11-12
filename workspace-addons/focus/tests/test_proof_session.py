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

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **k: no_child(argv))
    srv = make_server(root, 0, orch_bin=pageproof.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


SECRETS = {}  # cookie -> page secret of the sessions this module signed in


def post(port, path, body, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Host": host or f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    if "X-Orch-Page" not in h and h.get("Cookie") in SECRETS:  # a signed-in page sends its secret
        h["X-Orch-Page"] = SECRETS[h["Cookie"]]
    if h.get("X-Orch-Page") is None:
        h.pop("X-Orch-Page", None)  # {"X-Orch-Page": None} = a request with the cookie only
    c.request("POST", path, json.dumps(body), h)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def session(root, port):
    tok = hp.write_launch_token(root, "focus")
    st, ck, body = post(port, "/session", {"token": tok})
    assert st == 200
    cookie = ck.split(";")[0]
    SECRETS[cookie] = json.loads(body)["secret"]
    return cookie


def test_launch_token_bootstraps_the_cookie_once(live):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 200 and "HttpOnly" in ck and "SameSite=Strict" in ck and ck.startswith(f"orch_page_focus_{port}=")
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

    for action in ("edit", "remove", "reopen"):  # the ACTION is part of the proof target
        assert actions.proof_for(f"check.{action}", {"ticket": "t_a", "check": "c1"}) == (
            "check.wont_do_undo",
            f"t_a:c1:{action}",
        )


# ---- #539: the cookie alone is never a session (browsers send it to every loopback port) -------------------------

ANSWER = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}}


def test_session_answer_hands_over_the_secret_in_the_body_not_in_a_cookie(live):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    st, ck, body = post(port, "/session", {"token": tok})
    secret = json.loads(body)["secret"]
    assert st == 200 and len(secret) >= 40 and secret not in ck


@pytest.mark.parametrize("body", [ANSWER, {"op": "area.accept", "args": {"area": "x"}}], ids=lambda b: b["op"])
def test_every_mint_route_refuses_the_cookie_alone(live, monkeypatch, body):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    for h in (
        {"Cookie": ck, "X-Orch-Page": None},  # a foreign local page that got the cookie
        {"Cookie": ck, "X-Orch-Page": "x" * 43},
        {"Cookie": ck, "X-Orch-Page": ck.split("=", 1)[1]},
    ):
        assert post(port, "/api/act", body, h)[0] == 403, h
    assert ran == []


def test_the_secret_with_the_cookie_still_mints(live, monkeypatch):
    root, port = live

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **k: ran.append(proof) or R())
    assert post(port, "/api/act", ANSWER, {"Cookie": ck})[0] == 200
    assert len(ran) == 1 and ran[0].startswith("hp1.")
    assert post(port, "/api/act", ANSWER, {"X-Orch-Page": SECRETS[ck]})[0] == 403  # the secret alone: no


def test_a_page_on_another_port_cannot_act_even_with_cookie_and_secret(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    foreign = {"Cookie": ck, "Origin": f"http://127.0.0.1:{port + 1}", "Sec-Fetch-Site": "cross-site"}
    assert post(port, "/api/act", ANSWER, foreign)[0] == 403 and ran == []


# ---- #539 (supervisor review): /session cannot be used by another local page; no secret leaks -----------------------


def _raw(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **(headers or {})}
    h = {k: v for k, v in h.items() if v is not None}
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://127.0.0.1:1"},  # another loopback port
        {"Origin": "http://localhost:1"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": None, "Sec-Fetch-Site": "cross-site"},
        {"Origin": None},  # a non-GET without Origin
        {"Host": "evil.example:{PORT}"},  # DNS rebinding
        {"Host": "127.0.0.1:1"},  # wrong port in Host
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Forwarded-For": "1.2.3.4"},
    ],
    ids=lambda e: ",".join(f"{k}={v}" for k, v in e.items()),
)
def test_session_refused_for_foreign_origin_missing_origin_or_wrong_host(live, extra):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    base = {"Origin": f"http://127.0.0.1:{port}"}
    extra = {k: (v.replace("{PORT}", str(port)) if isinstance(v, str) else v) for k, v in extra.items()}
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {**base, **extra})
    assert st == 403 and b"secret" not in body and "set-cookie" not in hdr
    assert not any(k.startswith("access-control-") for k in hdr)
    st, _, body = _raw(port, "POST", "/session", {"token": tok}, base)  # the token was not spent by the refusals
    assert st == 200 and json.loads(body)["secret"]


def test_no_response_carries_cors_headers_and_preflight_is_refused(live):
    root, port = live
    ck = session(root, port)
    origin = {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    for method, path, body in (
        ("OPTIONS", "/session", None),
        ("OPTIONS", "/api/act", None),
        ("GET", "/api/state", None),
        ("GET", "/", None),
        ("POST", "/api/act", ANSWER),
        ("POST", "/session", {"token": "x" * 30}),
    ):
        st, hdr, _ = _raw(port, method, path, body, {**origin, "Cookie": ck})
        assert not any(k.startswith("access-control-") for k in hdr), (method, path)
        if method == "OPTIONS":
            assert st >= 400


def test_the_secret_never_appears_in_logs_urls_redirects_or_gets(live, capfd):
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    secret = json.loads(body)["secret"]
    assert st == 200 and secret not in json.dumps(hdr)  # not in a header (Set-Cookie, Location, ...)
    assert "location" not in hdr
    ck = hdr["set-cookie"].split(";")[0]
    for path in ("/", "/api/state", "/api/notices", "/api/update-status", "/api/live", "/api/tickets"):
        st, hdr2, body2 = _raw(port, "GET", path, None, {"Cookie": ck, "X-Orch-Page": secret})
        assert secret.encode() not in body2 and secret not in json.dumps(hdr2), path
        assert "location" not in hdr2 and "access-control-allow-origin" not in hdr2
    post(port, "/api/act", ANSWER, {"Cookie": ck, "X-Orch-Page": secret})
    post(port, "/api/act", ANSWER, {"Cookie": ck, "X-Orch-Page": "x" * 43})
    out = capfd.readouterr()
    assert secret not in out.out and secret not in out.err and ck.split("=", 1)[1] not in out.err


def test_secret_compare_is_constant_time_and_rotates_with_the_session(live):
    import inspect

    src = inspect.getsource(pageproof.PageSession.authed)
    assert "compare_digest" in src and "self.secret" in src and "== self.secret" not in src
    root, port = live
    tok = hp.write_launch_token(root, "focus")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    old_ck, old_secret = hdr["set-cookie"].split(";")[0], json.loads(body)["secret"]
    SECRETS[old_ck] = old_secret
    # a reused link revokes the session: the old cookie AND the old secret are dead, a new link gets a new secret
    st, hdr, _ = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    assert st == 403 and "set-cookie" not in hdr
    tok2 = hp.write_launch_token(root, "focus")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok2}, {"Origin": f"http://127.0.0.1:{port}"})
    new_secret = json.loads(body)["secret"]
    assert st == 200 and new_secret and new_secret != old_secret
    new_ck = hdr["set-cookie"].split(";")[0]
    assert new_ck != old_ck
    assert post(port, "/api/act", ANSWER, {"Cookie": old_ck, "X-Orch-Page": old_secret})[0] == 403  # old pair dead
    assert post(port, "/api/act", ANSWER, {"Cookie": new_ck, "X-Orch-Page": old_secret})[0] == 403  # old secret dead
