"""The dashboard's page session: launch token -> session cookie + page secret, loopback Host, no X-Forwarded-*,
the core run as `sys.executable -I -m orch` (never ORCH_BIN). Needs orch importable (runs from workspace/)."""

import http.client
import json
import threading

import pytest

pytest.importorskip("orch")
from orch import (
    addons,
    pagelaunch,
    pagesession,
)
from orch import home as orch_home

from orch_dashboard import actions, data
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

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    srv = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVERS[srv.server_address[1]] = srv
    yield root, srv.server_address[1]
    SERVERS.pop(srv.server_address[1], None)
    srv.shutdown()
    srv.server_close()


SERVERS = {}  # port -> the fixture's running server (a test may swap it for a restarted one)
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
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok})
    assert st == 200
    cookie = ck.split(";")[0]
    SECRETS[cookie] = json.loads(body)["secret"]
    return cookie


def test_launch_token_bootstraps_the_cookie_once(live):
    root, port = live
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert (
        st == 200
        and "HttpOnly" in ck
        and "SameSite=Strict" in ck
        and ck.startswith(f"orch_page_dashboard_{port}=")
    )
    assert post(port, "/session", {"token": tok})[0] == 403  # single use
    assert post(port, "/session", {"token": "x" * 30})[0] == 403


REMOTE = "dash.example.org:8791"  # a proxy in front, reached from another computer


def remote(cookie=None, **extra):
    """The headers a browser on another computer sends through a proxy that keeps the host name."""
    h = {
        "Host": REMOTE,
        "Origin": f"https://{REMOTE}",
        "X-Forwarded-For": "203.0.113.7",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": REMOTE,
        "Forwarded": "for=203.0.113.7;proto=https",
        **extra,
    }
    if cookie:
        h["Cookie"] = cookie
    return h


def test_sign_in_and_every_click_work_through_a_proxy_from_another_computer(live, monkeypatch):
    """Owner rule (16 Nov): the sign-in is the ONLY check. Through a proxy, under a host name that is not this
    computer's, with proxy headers: the sign-in works, a person's click runs, reads work."""
    root, port = live
    ran = []

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: ran.append(argv) or R())
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok}, remote())
    assert st == 200, body
    cookie = ck.split(";")[0]
    secret = json.loads(body)["secret"]
    st, _, body = post(
        port, "/api/act", {"op": "answer", "args": ANS}, remote(cookie, **{"X-Orch-Page": secret})
    )
    assert st == 200 and ran, body
    st, _, body = post(
        port, "/api/act", {"op": "answer", "args": ANS}, remote(cookie, **{"X-Orch-Page": None})
    )
    assert st == 403 and body.decode().startswith("Sign in to ")  # the cookie alone is still no session
    # reads under the proxy's host name: with the cookie yes, without it only the page shell (no data)
    get = lambda path, h: _raw(port, "GET", path, None, h)[0]
    assert get("/api/state", {"Host": REMOTE, "Cookie": cookie, "Sec-Fetch-Site": "same-origin"}) == 200
    assert get("/api/state", {"Host": REMOTE}) == 421
    assert get("/", {"Host": REMOTE}) == 200
    assert get("/session.js", {"Host": REMOTE}) == 200
    assert get("/api/state", {"Host": "evil example"}) == 421


def test_click_without_a_session_is_watch_only(live, monkeypatch):
    _root, port = live
    ran = []
    monkeypatch.setattr(actions, "_run", lambda *a, **k: ran.append(a))
    st, _, _body = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}},
    )
    assert st == 403 and ran == []


def test_click_with_session_runs_core_as_the_person_with_no_proof(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    def fake(argv, **kw):
        seen.update(argv=argv, kw=kw)
        return R()

    monkeypatch.setattr(actions, "_run", fake)
    st, _, _ = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}},
        {"Cookie": ck},
    )
    assert st == 200, seen
    # a plain person action: no proof flag, nothing on stdin, the same isolated core command
    assert (
        "--proof-stdin" not in seen["argv"]
        and "x" in seen["argv"]
        and seen["argv"][:5] == [*pagesession.argv0(pagesession.SELF)][:5]
    )
    assert seen["kw"]["stdin"] is not None and "input" not in seen["kw"]
    assert "ORCH_BIN" not in seen["kw"]["env"]


def test_two_loopback_servers_keep_independent_sessions(live, monkeypatch):
    """Cookies on 127.0.0.1 reach every loopback port: each server has its own `orch_page_<server>_<port>`, so
    signing in to one does not log the other out, and a cookie of one is not accepted by the other."""
    root, port = live
    srv2 = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        port2 = srv2.server_address[1]
        ran = []

        class R:
            returncode, stdout, stderr = 0, "{}", ""

        monkeypatch.setattr(actions, "_run", lambda argv, **kw: ran.append(argv) or R())
        act = {
            "op": "answer",
            "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"},
        }
        ck1 = session(root, port)
        ck2 = session(root, port2)  # signing in to the second server ...
        assert (
            ck1.split("=")[0] == f"orch_page_dashboard_{port}"
            and ck2.split("=")[0] == f"orch_page_dashboard_{port2}"
        )
        both = f"{ck1}; {ck2}"  # ... leaves the first cookie in the browser jar (different names)
        page1, page2 = {"X-Orch-Page": SECRETS[ck1]}, {"X-Orch-Page": SECRETS[ck2]}  # each page's own secret
        assert post(port, "/api/act", act, {"Cookie": both, **page1})[0] == 200  # first still signed in
        assert post(port2, "/api/act", act, {"Cookie": both, **page2})[0] == 200
        n = len(ran)
        assert (
            post(port2, "/api/act", act, {"Cookie": ck1, **page2})[0] == 403
        )  # one's cookie is no session on the other
        assert post(port, "/api/act", act, {"Cookie": ck2, **page1})[0] == 403
        assert (
            post(port2, "/api/act", act, {"Cookie": ck2, **page1})[0] == 403
        )  # nor is one's secret the other's
        value1 = ck1.split("=", 1)[1]  # nor is its value under the other's name
        assert (
            post(port2, "/api/act", act, {"Cookie": f"orch_page_dashboard_{port2}={value1}", **page2})[0]
            == 403
        )
        assert (
            post(port2, "/api/act", act, {"Cookie": f"orch_page={value1}", **page2})[0] == 403
        )  # the old shared name
        assert len(ran) == n
    finally:
        srv2.shutdown()
        srv2.server_close()


def test_two_people_signed_in_through_the_proxy_both_keep_working_across_a_restart(live, monkeypatch):
    """The live case of 16 Nov (ORCH-59/ORCH-39): the owner's browser and a second browser (the manager's tool,
    another device) sign in through the same proxy, the second one many times. Every sign-in hands out the SAME
    session, so none ends the other; a restart of the server (an update) keeps it, so no tab is told "orch
    restarted" and nobody has to sign in again. Only a sign-in link used twice ends the session."""
    root, port = live
    ran = []

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: ran.append(argv) or R())

    def sign_in():
        tok = pagelaunch.write_launch_token(root, "dashboard")
        st, ck, body = post(port, "/session", {"token": tok}, remote())
        assert st == 200, body
        return remote(ck.split(";")[0], **{"X-Orch-Page": json.loads(body)["secret"]})

    owner = sign_in()
    others = [sign_in() for _ in range(5)]  # the second browser signs in again and again
    for who in (owner, *others):
        st, _, body = post(port, "/api/act", {"op": "answer", "args": ANS}, who)
        assert st == 200, body
    old = SERVERS[port]
    old.shutdown()
    old.server_close()
    new = _restart(port, root)  # e.g. `orch update` from a terminal: nobody clicked, nothing was handed over
    try:
        for who in (owner, others[-1]):
            st, _, body = post(port, "/api/act", {"op": "answer", "args": ANS}, who)
            assert st == 200 and b"restarted" not in body, body
    finally:
        new.shutdown()
        new.server_close()


def test_click_with_session_and_proxy_headers_acts(live, monkeypatch):
    root, port = live
    ran = []

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(actions, "_run", lambda argv, **kw: ran.append(argv) or R())
    ck = session(root, port)
    st, _, _ = post(
        port, "/api/act", {"op": "answer", "args": ANS}, {"Cookie": ck, "X-Forwarded-Host": "proxy"}
    )
    assert st == 200 and ran


def test_orch_bin_from_the_environment_is_ignored():
    argv = pagesession.argv0(pagesession.SELF)
    assert argv[1:5] == ["-I", "-P", "-m", "orch"] and argv[0] == pagesession.sys.executable


def test_second_use_of_a_link_ends_the_session_and_says_so(live):
    root, port = live
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 200
    st, _, body = post(port, "/session", {"token": tok})
    assert st == 403 and b"Someone else tried to use this sign-in link" in body
    st, _, body = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}},
        {"Cookie": ck.split(";")[0]},
    )
    assert st == 403 and b"Someone else tried" in body  # the first page's cookie no longer works


def test_a_sandboxed_addon_page_cannot_use_the_session(live):
    """A page of a local add-on runs in an opaque origin: its requests carry Origin "null" and the fence refuses
    them, even with the person's cookie in the jar."""
    root, port = live
    ck = session(root, port)
    for op in ("update.start", "link.stop"):
        st, _, _ = post(
            port,
            "/api/act",
            {"op": op, "args": {"id": "x"}},
            {"Cookie": ck, "Origin": "null", "Sec-Fetch-Site": "cross-site"},
        )
        assert st == 403


def test_resume_cookie_is_one_use_expires_and_only_after_a_click(live, monkeypatch):
    import time

    root, _ = live
    assert pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + pagelaunch.RESUME_LIFE + 5)
    assert pagelaunch.take_resume_session(root, "dashboard") is None  # expired
    monkeypatch.setattr(time, "time", real)
    assert pagelaunch.take_resume_session(root, "dashboard") is None  # and the file is gone
    assert not pagelaunch.write_resume_cookie(root, "mine", "c" * 40, "s" * 40)  # a local add-on gets nothing
    assert not pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "short")  # no secret, no resume
    assert pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    assert pagelaunch.take_resume_session(root, "dashboard") == ("c" * 40, "s" * 40)
    assert pagelaunch.take_resume_session(root, "dashboard") is None  # one use


def test_print_launch_url_gives_the_page_a_session_once_and_reuse_revokes(live):
    """`orch start --print-launch-url` (test install, test folder) uses the ONE launch-token writer: the link it
    prints opens the page once; a second use of it revokes the session it made."""
    root, port = live
    url = pagelaunch.printable_launch_url(root, "dashboard", f"http://127.0.0.1:{port}")
    token = url.split("#launch=")[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})  # the page loads (read-only, no cookie)
    assert c.getresponse().status == 200
    st, ck, _ = post(port, "/session", {"token": token})
    assert st == 200 and ck.startswith(f"orch_page_dashboard_{port}=")
    assert pagelaunch.LAUNCH_LIFE == 30 and not list(
        orch_home.key_dir(root).glob("launch-dashboard.token")
    )  # spent
    st, _, body = post(port, "/session", {"token": token})
    assert st == 403 and b"Someone else tried to use this sign-in link" in body
    st, _, _ = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}},
        {"Cookie": ck.split(";")[0]},
    )
    assert st == 403  # the first session is revoked


def test_the_printable_link_is_refused_outside_a_test_folder(live, monkeypatch):
    root, port = live
    monkeypatch.setattr(orch_home, "install_kind", lambda: "normal")
    with pytest.raises(orch_home.Refused):
        pagelaunch.printable_launch_url(root, "dashboard", f"http://127.0.0.1:{port}")


def test_update_result_is_shown_to_a_session_once(live):
    root, port = live
    pagelaunch.write_update_status(root, "failed", "The server said no.")

    def get(cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(
            "GET",
            "/api/update-status",
            headers={
                "Host": f"127.0.0.1:{port}",
                **({"Cookie": cookie, "X-Orch-Page": SECRETS[cookie]} if cookie else {}),
            },
        )
        return json.loads(c.getresponse().read())

    assert get() == {}  # no session: nothing, and nothing consumed
    ck = session(root, port)
    assert get(ck) == {"state": "failed", "reason": "The server said no."}
    assert get(ck) == {}  # once


# ---- 1.0a-3: every op that acts as the person needs the page session (watch-only without one) ---------------

TID = "t_abcdef"
ACT_ARGS = {
    "copies.ask-update": {"ticket": "t_abcdef"},
    "link.extend": {"id": "f_abc", "days": 3},
    "link.stop": {"id": "f_abc"},
    "answer": {"ticket": TID, "question": "q1", "digest": "a" * 64, "answer": "x"},
    "review.answer": {"ticket": TID, "key": "q1", "verdict": "ok", "digest": "a" * 64},
    "ticket.changes": {"ticket": TID, "text": "more"},
    "chat.say": {"text": "hi"},
    "chat.make_ticket": {"id": "m_abcdefghijkl"},
    "check.set": {"ticket": TID, "check": "c1", "done": True},
    "check.wont_do": {"ticket": TID, "check": "c1"},
    "ticket.model": {"ticket": TID, "model": "opus"},
    "check.reopen": {"ticket": TID, "check": "c1"},
    "check.edit": {"ticket": TID, "check": "c1", "text": "x"},
    "check.remove": {"ticket": TID, "check": "c1"},
    "run.start": {"ticket": TID},
    "run.stop": {"ticket": TID},
    "run.send": {"ticket": TID, "text": "x"},
    "pull.merge": {"ticket": TID, "url": "https://github.com/acme/app/pull/12", "head": "a" * 40},
    "run.take_back": {"ticket": TID, "id": "p_abcdef12"},
    "addon.start": {},
    "addon.act": {"addon": "scheduler", "verb": "pause", "target": TID},
    "config.agent": {"name": "claude"},
    "config.agent.add": {"name": "mine", "command": "mine {prompt}"},
    "config.permissions": {"mode": "auto"},
    "private.move": {},
    "private.allow": {"name": "mine", "key": "a" * 64},
    "addon.set": {"name": "scheduler", "on": True},
    "addon.uninstall": {"name": "scheduler"},
    "share.set": {"on": True},
    "workflow.set": {"on": True},
    "reviewer.set": {"on": True},
    "release_merge.set": {"on": False},
    "live.set": {"max": 3},
    "copies.set": {"mode": "off"},
    "workspace.set": {"field": "name", "text": "Demo"},
    "workspace.propose": {},
    "look.profile": {"service": "relay", "description": "Demo", "tags": ["a"]},
    "copies.clean": {},
    "diag.set": {"on": False},
    "typing.set": {"on": True},
    "update.auto": {"on": True},
    "diag.delete_reports": {},
    "copies.remove_orphaned": {"ws8": "abcd1234"},
    "copies.retry": {"ticket": TID},
    "logins.check": {},
    "copies.approve": {"ticket": TID, "tip": "a" * 40, "control_paths": 0, "paths_hash": "12345678"},
    "look.set": {"icon": "bolt", "color": "auto"},
    "look.shared": {"on": False},
    "mobile.set": {"on": True},
    "mobile.ack": {},
    "chat.send_ws": {"workspace": "ws_abcdefghij", "text": "hi"},
    "chat.sync_ws": {},
    "mobile.hours": {"hours": 8},
    "group.say": {"ticket": TID, "text": "hi"},
    "group.share": {"ticket": TID, "file": "report.txt"},
    "group.add": {"ticket": TID, "workspace": "peer"},
    "group.remove": {"ticket": TID, "workspace": "peer"},
    "relay.reply": {"to": "peer", "message": "m_abcdefghijklmnop", "text": "ok"},
    "relay.topic": {"message": "m_abcdefghijklmnop", "title": "A topic"},
    "message.send": {"workspace": "peer", "text": "hi"},
    "logins.renew": {"name": "claude"},
    "logins.status": {"name": "claude"},
    "logins.cancel": {"name": "claude"},
    "logins.code": {"name": "claude", "value": "abc#def"},
    "logins.replace": {"name": "payments", "value": "new-key-value"},
}


def test_every_person_op_is_refused_without_a_session_and_starts_no_child(live, monkeypatch):
    import subprocess

    from orch_dashboard import actions as acts

    _root, port = live
    calls = []
    from orch_dashboard import data as dash_data

    monkeypatch.setattr(acts, "_run", lambda *a, **k: calls.append(a))  # module-local, never subprocess.run
    monkeypatch.setattr(dash_data, "_run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    missing = [op for op in acts.OPS if acts.needs_session(op) and op not in ACT_ARGS]
    assert not missing, f"add valid args for: {missing}"
    for op, args in ACT_ARGS.items():
        assert acts.needs_session(op), op
        st, _, body = post(port, "/api/act", {"op": op, "args": args})
        assert st == 403, (op, st, body)
    assert calls == []  # nothing was run for any of them


def test_every_person_op_runs_after_sign_in_through_a_proxy_from_another_computer(live, monkeypatch):
    """Owner rule (16 Nov): after the sign-in, NO action is limited to the computer orch runs on. Every person
    op of the table, sent through a proxy (a host name that is not this computer's, proxy headers), passes the
    check: none is refused for the session or for where the browser is."""
    import subprocess

    from orch_dashboard import actions as acts
    from orch_dashboard import data as dash_data

    root, port = live

    class R:
        returncode, stdout, stderr, pid = 0, "{}", "", 4242

        def wait(self, *a, **k):
            return 0

    monkeypatch.setattr(acts, "_run", lambda *a, **k: R())
    monkeypatch.setattr(dash_data, "_run", lambda *a, **k: R())
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: R())
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok}, remote())
    assert st == 200, body
    person = remote(ck.split(";")[0], **{"X-Orch-Page": json.loads(body)["secret"]})
    for op, args in ACT_ARGS.items():
        st, _, body = post(port, "/api/act", {"op": op, "args": args}, person)
        assert st != 403 and not body.decode(errors="replace").startswith("Sign in to "), (op, st, body)


def test_the_free_ops_stay_free(live):
    from orch_dashboard import actions as acts

    for op in (
        "ticket.new",
        "ticket.paste",
        "ticket.edit",
        "ticket.field",
        "log",
        "check.add",
        "ref.add",
        "ref.rm",
    ):
        assert not acts.needs_session(op), op


# ---- #539: the cookie alone is never a session (browsers send it to every loopback port) -------------------------

ANSWER = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}}


def test_session_answer_hands_over_the_secret_in_the_body_not_in_a_cookie(live):
    root, port = live
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok})
    secret = json.loads(body)["secret"]
    assert st == 200 and len(secret) >= 40 and secret not in ck


@pytest.mark.parametrize(
    "body",
    [
        ANSWER,
        {"op": "update.start", "args": {}},
    ],
    ids=lambda b: b["op"],
)
def test_every_action_refuses_the_cookie_alone(live, monkeypatch, body):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "_run", lambda *a, **k: ran.append(a))
    only_cookie = {
        "Cookie": ck,
        "X-Orch-Page": None,
    }  # what a foreign local page that got the cookie can send
    wrong = {"Cookie": ck, "X-Orch-Page": "x" * 43}
    for h in (only_cookie, wrong, {"Cookie": ck, "X-Orch-Page": ck.split("=", 1)[1]}):
        st, _, _ = post(port, "/api/act", body, h)
        assert st == 403, (body["op"], h)
    assert ran == []


def test_the_secret_with_the_cookie_still_acts(live, monkeypatch):
    root, port = live
    ck = session(root, port)

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    ran = []
    monkeypatch.setattr(actions, "_run", lambda argv, **k: ran.append(argv) or R())
    assert post(port, "/api/act", ANSWER, {"Cookie": ck})[0] == 200  # post() adds this session's secret
    assert len(ran) == 1


def test_a_secret_without_the_cookie_does_not_act(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "_run", lambda *a, **k: ran.append(a))
    assert post(port, "/api/act", ANSWER, {"X-Orch-Page": SECRETS[ck]})[0] == 403 and ran == []


def test_a_page_on_another_port_cannot_act_even_with_cookie_and_secret(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "_run", lambda *a, **k: ran.append(a))
    foreign = {"Cookie": ck, "Origin": f"http://127.0.0.1:{port + 1}", "Sec-Fetch-Site": "cross-site"}
    assert post(port, "/api/act", ANSWER, foreign)[0] == 403
    assert post(port, "/api/act", ANSWER, {"Cookie": ck, "Origin": f"http://localhost:{port + 1}"})[0] == 403
    assert ran == []


def test_update_status_needs_the_secret_too(live):
    root, port = live
    pagelaunch.write_update_status(root, "failed", "The server said no.")
    ck = session(root, port)

    def get(path, headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **headers})
        return json.loads(c.getresponse().read())

    assert get("/api/update-status", {"Cookie": ck}) == {}  # cookie only: nothing, and nothing consumed
    assert get("/api/update-status", {"Cookie": ck, "X-Orch-Page": SECRETS[ck]}) == {
        "state": "failed",
        "reason": "The server said no.",
    }


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
        {"Sec-Fetch-Site": "cross-site"},
    ],
    ids=lambda e: ",".join(f"{k}={v}" for k, v in e.items()),
)
def test_session_refused_for_foreign_origin_missing_origin_or_wrong_host(live, extra):
    root, port = live
    tok = pagelaunch.write_launch_token(root, "dashboard")
    base = {"Origin": f"http://127.0.0.1:{port}"}
    extra = {k: (v.replace("{PORT}", str(port)) if isinstance(v, str) else v) for k, v in extra.items()}
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {**base, **extra})
    assert st == 403 and b"secret" not in body and "set-cookie" not in hdr
    assert not any(k.startswith("access-control-") for k in hdr)
    st, _, body = _raw(
        port, "POST", "/session", {"token": tok}, base
    )  # the token was not spent by the refusals
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
    tok = pagelaunch.write_launch_token(root, "dashboard")
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

    src = inspect.getsource(pagesession.PageSession.authed)
    assert "compare_digest" in src and "self.secret" in src and "== self.secret" not in src
    root, port = live
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    old_ck, old_secret = hdr["set-cookie"].split(";")[0], json.loads(body)["secret"]
    SECRETS[old_ck] = old_secret
    # a reused link revokes the session: the old cookie AND the old secret are dead, a new link gets a new secret
    st, hdr, _ = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    assert st == 403 and "set-cookie" not in hdr
    tok2 = pagelaunch.write_launch_token(root, "dashboard")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok2}, {"Origin": f"http://127.0.0.1:{port}"})
    new_secret = json.loads(body)["secret"]
    assert st == 200 and new_secret and new_secret != old_secret
    new_ck = hdr["set-cookie"].split(";")[0]
    assert new_ck != old_ck
    assert (
        post(port, "/api/act", ANSWER, {"Cookie": old_ck, "X-Orch-Page": old_secret})[0] == 403
    )  # old pair dead
    assert (
        post(port, "/api/act", ANSWER, {"Cookie": new_ck, "X-Orch-Page": old_secret})[0] == 403
    )  # old secret dead


def test_every_dashboard_answer_forbids_framing_by_other_sites(live):
    """A foreign local page must not frame a signed-in dashboard tab (clickjacking with the page secret)."""
    _root, port = live
    for path in ("/", "/api/notices", "/nope"):
        _st, hdr, _ = _raw(port, "GET", path)
        assert "frame-ancestors 'self'" in hdr.get("content-security-policy", ""), path


ANS = {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}


def _answer(port, ck):
    return post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "digest": "a" * 64, "answer": "x"}},
        {"Cookie": ck},
    )


def _restart(live_port, root):
    """What an update does to the server: the old one goes away, a new one binds the same port."""
    srv = make_server(root, live_port, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_open_tab_keeps_its_session_after_an_addon_change_restart(live, monkeypatch):
    """An add-on add/remove (addon.set) restarts the services like an update: the click arms the same one-use
    resume, so the same tab's next action works on the restarted server without a reload."""
    from orch_dashboard import actions

    root, port = live
    ck = session(root, port)
    monkeypatch.setattr(actions, "run_op", lambda *a, **k: (200, "", None))
    st, _, _ = post(
        port, "/api/act", {"op": "addon.set", "args": {"name": "factory", "on": True}}, {"Cookie": ck}
    )
    assert st == 200
    assert list(orch_home.key_dir(root).glob("resume-dashboard.cookie"))  # armed before the op ran
    old = SERVERS[port]
    old.shutdown()
    old.server_close()
    new = _restart(port, root)
    try:
        st, _, body = _answer(port, ck)
        assert st != 403 and b"Reload" not in body
    finally:
        new.shutdown()
        new.server_close()


def test_an_addon_change_without_a_session_arms_nothing(live, monkeypatch):
    from orch_dashboard import actions

    root, port = live
    monkeypatch.setattr(actions, "run_op", lambda *a, **k: (200, "", None))
    post(
        port, "/api/act", {"op": "addon.set", "args": {"name": "factory", "on": True}}, {"X-Orch-Page": None}
    )
    assert not list(orch_home.key_dir(root).glob("resume-dashboard.cookie"))


def test_a_busy_port_does_not_spend_the_resume_file(live):
    root, port = live
    assert pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    with pytest.raises(OSError):
        make_server(root, port, orch_bin=pagesession.SELF)  # the fixture's server still holds the port
    srv = make_server(root, 0, orch_bin=pagesession.SELF)  # the retry (auto-port) still adopts the session
    try:
        assert srv.RequestHandlerClass is not None
        assert (
            list(orch_home.key_dir(root).glob("resume-dashboard.cookie")) == []
        )  # spent by the server that bound
    finally:
        srv.server_close()


def test_an_unknown_session_is_asked_to_sign_in_never_told_orch_restarted(live):
    """ORCH-59/ORCH-39: nothing restarted, so no restart notice: a session this server does not know (another
    browser, an ended sign-in) is asked to sign in, in the same words as a page that never signed in."""
    root, port = live
    ck = session(root, port)
    stale = {"Cookie": ck, "X-Orch-Page": "z" * 43}  # a session this server never issued
    st, _, body = post(port, "/api/act", {"op": "answer", "args": ANS}, stale)
    assert st == 403 and body.decode() == pagesession.SIGNIN_MSG
    st, _, body = post(port, "/api/act", {"op": "update.start", "args": {}}, stale)
    assert st == 403 and body.decode() == pagesession.SIGNIN_MSG
    st, _, body = post(port, "/api/act", {"op": "answer", "args": ANS}, {"X-Orch-Page": None})
    assert st == 403 and body.decode() == pagesession.SIGNIN_MSG


def test_the_session_survives_a_restart_without_a_click(live):
    """A restart that nobody clicked (orch stop/start, a crash, an automatic update) keeps the sign-in: the
    restarted server on the same port knows the open tabs' session."""
    root, port = live
    ck = session(root, port)
    old = SERVERS[port]
    old.shutdown()
    old.server_close()
    new = _restart(port, root)
    try:
        st, _, body = post(port, "/api/act", {"op": "update.note.dismiss", "args": {}}, {"Cookie": ck})
        assert st == 200, body
    finally:
        new.shutdown()
        new.server_close()


def test_a_transient_read_failure_keeps_the_resume_file(live, monkeypatch):
    from orch import winacl

    root, _ = live
    assert pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    real = orch_home._read_guarded

    def flaky(path):
        raise winacl.Unknown("try again")

    monkeypatch.setattr(orch_home, "_read_guarded", flaky)
    assert pagelaunch.take_resume_session(root, "dashboard") is None
    monkeypatch.setattr(orch_home, "_read_guarded", real)
    assert pagelaunch.take_resume_session(root, "dashboard") == ("c" * 40, "s" * 40)


def test_a_resume_file_that_cannot_be_removed_is_not_adopted(live, monkeypatch):
    """No replay: when the one use cannot be proven (the unlink fails), nothing is adopted."""
    root, _ = live
    assert pagelaunch.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    f = orch_home.key_dir(root) / "resume-dashboard.cookie"
    real = type(f).unlink

    def deny(self, *a, **k):
        if self.name == f.name:
            raise PermissionError("in use")
        return real(self, *a, **k)

    monkeypatch.setattr(type(f), "unlink", deny)
    why = []
    assert pagelaunch.take_resume_session(root, "dashboard", why) is None and why
    monkeypatch.setattr(type(f), "unlink", real)


def test_settings_update_button_needs_a_session_and_starts_the_detached_update(live, monkeypatch):
    root, port = live
    from orch_dashboard import update

    started = {}

    def fake_start(argv, **kw):
        started.update(argv=argv)
        return 4343

    monkeypatch.setattr(update, "start_detached", fake_start)
    st, _, _ = post(port, "/api/act", {"op": "update.start", "args": {}})
    assert st == 403 and not started  # no session: a curl or an agent cannot update
    ck = session(root, port)
    st, _, body = post(port, "/api/act", {"op": "update.start", "args": {}}, {"Cookie": ck})
    assert st == 202 and b"Update started" in body
    assert started["argv"] == ["update"]


def test_switch_build_is_one_click_through_the_same_update(live, monkeypatch):
    # issue 957: Switch to release / development build runs the same detached `orch update`, with --to
    root, port = live
    from orch_dashboard import update

    started = {}
    monkeypatch.setattr(update, "start_detached", lambda argv, **kw: started.update(argv=argv) or 4344)
    st, _, _ = post(port, "/api/act", {"op": "update.start", "args": {"to": "development"}})
    assert st == 403 and not started  # a person's click only
    ck = session(root, port)
    st, _, _ = post(port, "/api/act", {"op": "update.start", "args": {"to": "feat/evil"}}, {"Cookie": ck})
    assert st == 400 and not started
    st, _, _ = post(port, "/api/act", {"op": "update.start", "args": {"to": "development"}}, {"Cookie": ck})
    assert st == 202 and started["argv"] == ["update", "--to", "development"]


def test_release_endpoint_gives_the_line_of_a_finished_ticket(live, monkeypatch):
    root, port = live
    from orch import released, tickets

    t = tickets.create(root, "Suggest button", "human:t")
    seen = []

    def line(ticket):
        seen.append(ticket.get("id"))
        return {"state": "installed", "release": 30, "text": "In release 30 (installed here)"}

    monkeypatch.setattr(released, "ticket_release", line)

    def get(q):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/api/release" + q, headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    assert get("?ticket=" + t["id"]) == (200, line({"id": t["id"]}))
    assert get("?ticket=../../etc") == (200, None)  # only a ticket id is looked up
    assert get("?ticket=t_missing00") == (200, None)  # no such ticket: no line, no error
    assert get("") == (200, None)
    assert seen == [t["id"], t["id"]]


def test_update_info_endpoint_gives_versions_and_changes(live, monkeypatch):
    _, port = live
    from orch import updateinfo

    monkeypatch.setattr(
        updateinfo,
        "info",
        lambda use_cache=True: {
            "installed": {"label": "orch 15", "release": 15, "sha": None},
            "newest": {"label": "orch 16", "release": 16, "sha": "b" * 40},
            "update_available": True,
            "changes": ["Helpers tidy up new tickets"],
        },
    )
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/update-info", headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    data = json.loads(r.read())
    assert (
        r.status == 200
        and data["newest"]["label"] == "orch 16"
        and data["changes"] == ["Helpers tidy up new tickets"]
    )
    assert "source" in data
