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
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok})
    assert st == 200
    cookie = ck.split(";")[0]
    SECRETS[cookie] = json.loads(body)["secret"]
    return cookie


def test_launch_token_bootstraps_the_cookie_once(live):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, _ = post(port, "/session", {"token": tok})
    assert st == 200 and "HttpOnly" in ck and "SameSite=Strict" in ck and ck.startswith(f"orch_page_dashboard_{port}=")
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


def test_two_loopback_servers_keep_independent_sessions(live, monkeypatch):
    """Cookies on 127.0.0.1 reach every loopback port: each server has its own `orch_page_<server>_<port>`, so
    signing in to one does not log the other out, and a cookie of one is not accepted by the other."""
    root, port = live
    srv2 = make_server(root, 0, orch_bin=pageproof.SELF)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        port2 = srv2.server_address[1]
        ran = []

        class R:
            returncode, stdout, stderr = 0, "{}", ""

        monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **kw: ran.append(argv) or R())
        act = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}}
        ck1 = session(root, port)
        ck2 = session(root, port2)  # signing in to the second server ...
        assert ck1.split("=")[0] == f"orch_page_dashboard_{port}" and ck2.split("=")[0] == f"orch_page_dashboard_{port2}"
        both = f"{ck1}; {ck2}"  # ... leaves the first cookie in the browser jar (different names)
        page1, page2 = {"X-Orch-Page": SECRETS[ck1]}, {"X-Orch-Page": SECRETS[ck2]}  # each page's own secret
        assert post(port, "/api/act", act, {"Cookie": both, **page1})[0] == 200  # first still signed in
        assert post(port2, "/api/act", act, {"Cookie": both, **page2})[0] == 200
        n = len(ran)
        assert post(port2, "/api/act", act, {"Cookie": ck1, **page2})[0] == 403  # one's cookie is no session on the other
        assert post(port, "/api/act", act, {"Cookie": ck2, **page1})[0] == 403
        assert post(port2, "/api/act", act, {"Cookie": ck2, **page1})[0] == 403  # nor is one's secret the other's
        value1 = ck1.split("=", 1)[1]  # nor is its value under the other's name
        assert post(port2, "/api/act", act, {"Cookie": f"orch_page_dashboard_{port2}={value1}", **page2})[0] == 403
        assert post(port2, "/api/act", act, {"Cookie": f"orch_page={value1}", **page2})[0] == 403  # the old shared name
        assert len(ran) == n
    finally:
        srv2.shutdown()
        srv2.server_close()


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
    assert st == 200
    st, _, body = post(port, "/session", {"token": tok})
    assert st == 403 and b"Someone else tried to use this sign-in link" in body
    st, _, body = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}},
        {"Cookie": ck.split(";")[0]},
    )
    assert st == 403 and b"Someone else tried" in body  # the first page's cookie no longer mints


def test_a_notice_is_read_not_consumed_and_only_the_ack_of_a_session_clears_it(live):
    root, port = live
    nid = hp._notice_id("protection_reset", "x", hp.RESET_NOTICE)
    d = hp.key_dir(root)
    note = {"id": nid, "kind": "protection_reset", "at": "x", "text": hp.RESET_NOTICE}
    hp._write_private(d / "notices.json", json.dumps([note]))

    def get(cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": f"127.0.0.1:{port}", **({"Cookie": cookie, "X-Orch-Page": SECRETS[cookie]} if cookie else {})}
        c.request("GET", "/api/notices", headers=h)
        return json.loads(c.getresponse().read())

    assert get() == []  # a curl without a session sees nothing
    ck = session(root, port)
    assert get(ck)[0]["text"] == hp.RESET_NOTICE[:600] and get(ck)[0]["id"] == nid
    assert get(ck)  # read twice: still there (the launch reload must not lose it)
    ack = {"op": "notice.ack", "args": {"id": nid}}
    assert post(port, "/api/act", ack)[0] == 403 and get(ck)  # no session: the notice stays
    assert post(port, "/api/act", ack, {"Cookie": ck})[0] == 200
    assert get(ck) == []  # acknowledged: gone


def test_dismiss_needs_a_session(live):
    root, port = live
    hp.request_handoff(root, "ticket.answer", "t_a:q1", "L", "x", argv=["answer", "t_a", "q1", "--", "x"])
    hid = hp.handoffs(root)[0]["id"]
    assert post(port, "/api/act", {"op": "handoff.dismiss", "args": {"id": hid}})[0] == 403
    assert hp.handoffs(root)  # still there
    ck = session(root, port)
    assert post(port, "/api/act", {"op": "handoff.dismiss", "args": {"id": hid}}, {"Cookie": ck})[0] == 200
    assert hp.handoffs(root) == []


def test_a_sandboxed_addon_page_cannot_use_the_session(live):
    """A page of a local add-on runs in an opaque origin: its requests carry Origin "null" and the fence refuses
    them, even with the person's cookie in the jar."""
    root, port = live
    ck = session(root, port)
    for op in ("handoff.confirm", "handoff.dismiss"):
        st, _, _ = post(
            port,
            "/api/act",
            {"op": op, "args": {"id": "x"}},
            {"Cookie": ck, "Origin": "null", "Sec-Fetch-Site": "cross-site"},
        )
        assert st == 403


def test_update_click_runs_detached_answers_at_once_and_the_restart_keeps_the_session(live, monkeypatch):
    root, port = live
    hp.request_handoff(root, "update", "orch", "Update orch", "", argv=["update"])
    hid = hp.handoffs(root)[0]["id"]
    ck = session(root, port)
    started = {}
    from orch_dashboard import handoff

    def fake_start(argv, proof, **kw):  # stands in for the detached child: records, does not wait
        started.update(argv=argv, proof=proof)
        return 4242

    monkeypatch.setattr(handoff, "start_detached", fake_start)
    monkeypatch.setattr(
        handoff, "run_with_proof", lambda *a, **k: pytest.fail("an update must not run with a timeout")
    )
    st, _, body = post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": hid}}, {"Cookie": ck})
    assert st == 202 and b"Update started" in body and started["proof"].startswith("hp1.")
    # the update restarts the server: a NEW server for the same workspace adopts the page's session once
    s2 = pageproof.PageSession(root, "dashboard")  # restarted on the same port: the cookie name is per port
    page = {"Host": f"127.0.0.1:{port}", "Cookie": ck, "X-Orch-Page": SECRETS[ck]}
    assert s2.can_mint(page, port)  # the open tab's cookie AND secret still work
    s3 = pageproof.PageSession(root, "dashboard")  # a second restart: the marker is spent
    assert not s3.can_mint(page, port)


def test_resume_cookie_is_one_use_expires_and_only_after_a_click(live, monkeypatch):
    import time

    root, _ = live
    assert hp.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + hp.RESUME_LIFE + 5)
    assert hp.take_resume_session(root, "dashboard") is None  # expired
    monkeypatch.setattr(time, "time", real)
    assert hp.take_resume_session(root, "dashboard") is None  # and the file is gone
    assert not hp.write_resume_cookie(root, "mine", "c" * 40, "s" * 40)  # a local add-on gets nothing
    assert not hp.write_resume_cookie(root, "dashboard", "c" * 40, "short")  # no secret, no resume
    assert hp.write_resume_cookie(root, "dashboard", "c" * 40, "s" * 40)
    assert hp.take_resume_session(root, "dashboard") == ("c" * 40, "s" * 40)
    assert hp.take_resume_session(root, "dashboard") is None  # one use


def test_print_launch_url_gives_the_page_a_session_once_and_reuse_revokes(live):
    """`orch start --print-launch-url` (test install, test folder) uses the ONE launch-token writer: the link it
    prints opens the page once; a second use of it revokes the session it made."""
    root, port = live
    url = hp.printable_launch_url(root, "dashboard", f"http://127.0.0.1:{port}")
    token = url.split("#launch=")[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})  # the page loads (read-only, no cookie)
    assert c.getresponse().status == 200
    st, ck, _ = post(port, "/session", {"token": token})
    assert st == 200 and ck.startswith(f"orch_page_dashboard_{port}=")
    assert hp.LAUNCH_LIFE == 30 and not list(hp.key_dir(root).glob("launch-dashboard.token"))  # spent
    st, _, body = post(port, "/session", {"token": token})
    assert st == 403 and b"Someone else tried to use this sign-in link" in body
    st, _, _ = post(
        port,
        "/api/act",
        {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}},
        {"Cookie": ck.split(";")[0]},
    )
    assert st == 403  # the first session is revoked


def test_the_printable_link_is_refused_outside_a_test_folder(live, monkeypatch):
    root, port = live
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    with pytest.raises(hp.Refused):
        hp.printable_launch_url(root, "dashboard", f"http://127.0.0.1:{port}")


def test_update_result_is_shown_to_a_session_once(live):
    root, port = live
    hp.write_update_status(root, "failed", "The server said no.")

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


def test_the_listing_sends_structured_parts_and_the_exact_value_never_a_sentence_or_the_command(live):
    root, port = live
    hp.request_handoff(
        root,
        "ticket.answer",
        "t_a:q1",
        "",
        "Blue {value}",
        argv=["answer", "t_a", "q1", "--", "Blue {value}"],
        parts={"title": "T {value}", "question": "Which"},
    )
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/handoffs", headers={"Host": f"127.0.0.1:{port}"})
    item = json.loads(c.getresponse().read())[0]
    assert item["parts"] == {"title": "T {value}", "question": "Which"} and item["value"] == "Blue {value}"
    assert item["exact"] == ""
    assert "argv" not in item and "label" not in item


def test_the_listing_carries_the_full_exact_target_for_a_long_host(live):
    root, port = live
    host = ".".join(["a" * 50] * 4) + ".example"
    hp.request_handoff(
        root, "relay.connect", host, "", "", argv=["relay", "connect", f"https://{host}", "--workspace", "w"],
        parts={"host": host}, exact=host,
    )  # fmt: skip
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/handoffs", headers={"Host": f"127.0.0.1:{port}"})
    item = json.loads(c.getresponse().read())[0]
    assert item["exact"] == host and item["parts"]["host"] == host and len(host) > 120


def test_wont_do_clicks_need_a_proof_on_the_real_server_path():
    from orch_dashboard import actions as a

    assert a.proof_for("check.wont_do", {"ticket": "t_a", "check": "c1"}) == ("check.wont_do", "t_a:c1")
    assert a.proof_for("check.reopen", {"ticket": "t_a", "check": "c1"}) == (
        "check.wont_do_undo",
        "t_a:c1:reopen",
    )
    assert a.proof_for("check.set", {"ticket": "t_a", "check": "c1", "done": False}) == (
        "check.wont_do_undo",
        "t_a:c1:reopen",
    )
    assert a.proof_for("check.set", {"ticket": "t_a", "check": "c1", "done": True}) is None


def test_check_edit_and_remove_clicks_need_a_proof_on_the_real_server_path():
    from orch_dashboard import actions as a

    args = {"ticket": "t_abcdef", "check": "c1"}
    assert a.proof_for("check.edit", {**args, "text": "x"}) == ("check.wont_do_undo", "t_abcdef:c1:edit")
    assert a.proof_for("check.remove", args) == ("check.wont_do_undo", "t_abcdef:c1:remove")
    assert a.build_argv("check.remove", args)[:4] == ["check", "remove", "t_abcdef", "c1"]
    assert a.build_argv("check.edit", {**args, "text": "a -- b"})[-2:] == ["--", "a -- b"]


GIT_CLICKS = (
    ("private.move", {}, ("private.move", "move"), ["private", "move"]),
    (
        "private.allow",
        {"name": "mine", "key": "a" * 64},
        ("private.allow", "mine:" + "a" * 64),
        ["private", "allow", "mine", "--key", "a" * 64],
    ),
    (
        "config.agent.add",
        {"name": "mine", "command": "x {prompt}"},
        ("config.agent_add", hp.agent_add_target("mine", "x {prompt}")),
        ["config", "agent", "add", "mine"],
    ),
)


@pytest.mark.parametrize(("op", "args", "need", "head"), GIT_CLICKS)
def test_git_clicks_take_the_page_proof_with_their_own_op_and_target(op, args, need, head):
    assert actions.proof_for(op, args) == need
    assert actions.build_argv(op, args)[: len(head)] == head


@pytest.mark.parametrize(("op", "args", "need", "head"), GIT_CLICKS)
def test_git_click_without_a_session_is_watch_only(live, monkeypatch, op, args, need, head):
    _root, port = live
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(actions, "_agent_exists", lambda *a: False)
    assert post(port, "/api/act", {"op": op, "args": args})[0] == 403 and ran == []


@pytest.mark.parametrize(("op", "args", "need", "head"), GIT_CLICKS)
def test_git_click_with_a_session_is_one_step_with_a_proof(live, monkeypatch, op, args, need, head):
    root, port = live
    ck = session(root, port)
    seen = []

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(
        actions, "run_with_proof", lambda argv, proof, **kw: seen.append((argv, proof)) or R()
    )
    monkeypatch.setattr(actions, "_agent_exists", lambda *a: False)
    st, _, _ = post(port, "/api/act", {"op": op, "args": args}, {"Cookie": ck})
    assert st == 200 and len(seen) == 1  # one click, one command, one proof
    payload = json.loads(__import__("base64").urlsafe_b64decode(seen[0][1].split(".")[1] + "=="))
    assert (payload["op"], payload["target"]) == need
    assert seen[0][0][: len(head)] == head


# ---- 1.0a-3: every op that acts as the person needs the page session (watch-only without one) ---------------

TID = "t_abcdef"
ACT_ARGS = {
    "link.extend": {"id": "f_abc", "days": 3},
    "link.stop": {"id": "f_abc"},
    "answer": {"ticket": TID, "question": "q1", "answer": "x"},
    "ticket.changes": {"ticket": TID, "text": "more"},
    "chat.say": {"text": "hi"},
    "chat.make_ticket": {"id": "m_abcdefghijkl"},
    "check.set": {"ticket": TID, "check": "c1", "done": True},
    "check.wont_do": {"ticket": TID, "check": "c1"},
    "check.reopen": {"ticket": TID, "check": "c1"},
    "check.edit": {"ticket": TID, "check": "c1", "text": "x"},
    "check.remove": {"ticket": TID, "check": "c1"},
    "run.start": {"ticket": TID},
    "run.stop": {"ticket": TID},
    "run.send": {"ticket": TID, "text": "x"},
    "addon.start": {},
    "addon.act": {"addon": "scheduler", "verb": "pause", "target": TID},
    "config.agent": {"name": "claude"},
    "config.agent.add": {"name": "mine", "command": "mine {prompt}"},
    "config.permissions": {"mode": "auto"},
    "private.move": {},
    "private.allow": {"name": "mine", "key": "a" * 64},
    "addon.set": {"name": "scheduler", "on": True},
    "share.set": {"on": True},
    "workflow.set": {"on": True},
    "copies.set": {"mode": "off"},
    "copies.clean": {},
    "copies.remove_orphaned": {"ws8": "abcd1234"},
    "copies.retry": {"ticket": TID},
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
    assert acts.proof_for("ticket.patch", {"ticket": TID, "data": {"note": "x"}}) is None


def test_the_core_gated_config_ops_mint_for_the_right_target():
    from orch_dashboard import actions as acts

    assert acts.proof_for("workflow.set", {"on": True}) == ("config.agents_may_finish", "on")
    assert acts.proof_for("workflow.set", {"on": False}) is None  # off needs no proof
    assert acts.proof_for("share.set", {"on": True}) == ("config.share", "on")
    assert acts.proof_for("share.set", {"on": False}) is None
    assert acts.proof_for("config.permissions", {"mode": "full"}) == ("config.permissions", "full")
    assert acts.proof_for("config.agent.add", {"name": "mine", "command": "mine {prompt}"}) == (
        "config.agent_add",
        hp.agent_add_target("mine", "mine {prompt}"),  # core's own function, not the dashboard's
    )
    assert acts.proof_for("look.shared", {"on": True}) == ("look.shared_pages", "on")
    assert acts.proof_for("look.shared", {"on": False}) == ("look.shared_pages", "off")
    assert acts.proof_for("look.set", {"icon": "bolt"}) == ("look.icon", "look")


def test_group_clicks_mint_for_the_right_target_and_a_share_binds_the_files_content(tmp_path):
    from orch_dashboard import actions as acts

    assert acts.proof_for("group.say", {"ticket": TID, "text": "x"}) == ("group.write_as_person", TID)
    assert acts.proof_for("group.say", {"group": "grp_t_abcdef", "host": "peer", "text": "x"}) == (
        "group.write_as_person",
        "peer:grp_t_abcdef",  # host:group (the host is part of what is approved)
    )
    assert acts.proof_for("group.remove", {"ticket": TID, "workspace": "peer"}) == (
        "group.remove_member",
        f"{TID}:peer",
    )
    art = tmp_path / ".orch" / "tickets" / TID / "artifacts"
    art.mkdir(parents=True)
    (art / "report.txt").write_text("one")
    a = acts.proof_for("group.share", {"ticket": TID, "file": "report.txt"}, tmp_path)
    (art / "report.txt").write_text("two")
    b = acts.proof_for("group.share", {"ticket": TID, "file": "report.txt"}, tmp_path)
    assert a[0] == b[0] == "group.share_file" and a[1] != b[1] and a[1].startswith(f"{TID}:")  # content-bound


def test_copy_setup_click_mints_for_the_hash_of_the_command_only():
    import hashlib

    from orch_dashboard import actions as acts

    got = acts.proof_for("copies.set", {"setup": "  make prepare "})
    assert got == ("config.copy_setup", hashlib.sha256(b"make prepare").hexdigest())
    assert acts.proof_for("copies.set", {"setup": ""}) is None  # clearing needs none
    assert acts.proof_for("copies.set", {"setup": "none"}) is None
    assert acts.proof_for("copies.set", {"mode": "off"}) is None


def test_no_session_means_no_file_read_before_the_refusal(monkeypatch, tmp_path):
    """F8: a request without a page session is refused before the artifact is hashed."""
    from orch_dashboard import actions as acts

    def boom(*a, **k):
        raise AssertionError("the artifact was read before the session check")

    monkeypatch.setattr(acts, "_share_sha", boom)
    with pytest.raises(acts.NeedsPerson):
        acts.run_op(tmp_path, acts.SELF, "group.share", {"ticket": TID, "file": "a.txt"}, mint=None)


def test_group_say_target_is_host_and_group_like_the_cli(tmp_path, monkeypatch):
    """The dashboard's proof target for a joined group is <host>:<group>, the same string the CLI builds
    (humanproof.group_target); a host-side group (by ticket) stays the ticket id."""
    from orch import relay

    from orch_dashboard import actions as acts

    monkeypatch.setattr(relay, "resolve", lambda root, name: {"Alpha": "ws_hosta00001"}.get(name, name))
    gid = "grp_t_abcdef12"
    want = ("group.write_as_person", f"ws_hosta00001:{gid}")
    assert acts.proof_for("group.say", {"group": gid, "host": "Alpha"}, tmp_path) == want
    assert acts.proof_for("group.say", {"group": gid, "host": "ws_hosta00001"}, tmp_path) == want
    assert hp.group_target(tmp_path, "Alpha", gid) == want[1]
    assert acts.proof_for("group.say", {"group": gid, "host": "ws_hostb00002"}, tmp_path) != want
    assert acts.proof_for("group.say", {"ticket": TID, "text": "x"}) == ("group.write_as_person", TID)


@pytest.mark.parametrize(
    "op,args,target,head",
    [
        ("copies.remove_orphaned", {"ws8": "deadbeef"}, "deadbeef", "remove-orphaned"),
        ("copies.retry", {"ticket": "t_abc123"}, "t_abc123", "retry"),
    ],
)
def test_copy_click_mints_exact_target(live, monkeypatch, op, args, target, head):
    root, port = live
    ck = session(root, port)
    seen = {}

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    def fake(argv, proof, **kw):
        seen.update(argv=argv, proof=proof)
        return R()

    monkeypatch.setattr(actions, "run_with_proof", fake)
    st, _, body = post(port, "/api/act", {"op": op, "args": args}, {"Cookie": ck})
    assert st == 200, body
    assert seen["argv"][:3] == ["copy", head, target]
    core_op = "copy." + head.replace("-", "_")
    assert hp.verify_and_consume(root, seen["proof"], core_op, target).startswith("human:")


# ---- #539: the cookie alone is never a session (browsers send it to every loopback port) -------------------------

ANSWER = {"op": "answer", "args": {"ticket": "t_abc123", "question": "q1", "answer": "x"}}


def test_session_answer_hands_over_the_secret_in_the_body_not_in_a_cookie(live):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok})
    secret = json.loads(body)["secret"]
    assert st == 200 and len(secret) >= 40 and secret not in ck


@pytest.mark.parametrize(
    "body",
    [
        ANSWER,
        {"op": "notice.ack", "args": {"id": "n1"}},
        {"op": "handoff.dismiss", "args": {"id": "h1"}},
        {"op": "handoff.confirm", "args": {"id": "h1"}},
    ],
    ids=lambda b: b["op"],
)
def test_every_mint_route_refuses_the_cookie_alone(live, monkeypatch, body):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    from orch_dashboard import handoff

    monkeypatch.setattr(handoff, "run_with_proof", lambda *a, **k: ran.append(a))
    only_cookie = {"Cookie": ck, "X-Orch-Page": None}  # what a foreign local page that got the cookie can send
    wrong = {"Cookie": ck, "X-Orch-Page": "x" * 43}
    for h in (only_cookie, wrong, {"Cookie": ck, "X-Orch-Page": ck.split("=", 1)[1]}):
        st, _, _ = post(port, "/api/act", body, h)
        assert st in (403, 404), (body["op"], h)  # 404: handoff gone, i.e. no mint was reachable either
        assert st != 404 or body["op"] == "handoff.confirm"
    assert ran == []


def test_the_secret_with_the_cookie_still_mints(live, monkeypatch):
    root, port = live
    ck = session(root, port)

    class R:
        returncode, stdout, stderr = 0, "{}", ""

    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda argv, proof, **k: ran.append(proof) or R())
    assert post(port, "/api/act", ANSWER, {"Cookie": ck})[0] == 200  # post() adds this session's secret
    assert len(ran) == 1 and ran[0].startswith("hp1.")


def test_a_secret_without_the_cookie_does_not_mint(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    assert post(port, "/api/act", ANSWER, {"X-Orch-Page": SECRETS[ck]})[0] == 403 and ran == []


def test_a_page_on_another_port_cannot_act_even_with_cookie_and_secret(live, monkeypatch):
    root, port = live
    ck = session(root, port)
    ran = []
    monkeypatch.setattr(actions, "run_with_proof", lambda *a, **k: ran.append(a))
    foreign = {"Cookie": ck, "Origin": f"http://127.0.0.1:{port + 1}", "Sec-Fetch-Site": "cross-site"}
    assert post(port, "/api/act", ANSWER, foreign)[0] == 403
    assert post(port, "/api/act", ANSWER, {"Cookie": ck, "Origin": f"http://localhost:{port + 1}"})[0] == 403
    assert ran == []


def test_notices_and_update_status_need_the_secret_too(live):
    root, port = live
    hp.write_update_status(root, "failed", "The server said no.")
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
        {"Host": "evil.example:{PORT}"},  # DNS rebinding
        {"Host": "127.0.0.1:1"},  # wrong port in Host
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Forwarded-For": "1.2.3.4"},
    ],
    ids=lambda e: ",".join(f"{k}={v}" for k, v in e.items()),
)
def test_session_refused_for_foreign_origin_missing_origin_or_wrong_host(live, extra):
    root, port = live
    tok = hp.write_launch_token(root, "dashboard")
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
    tok = hp.write_launch_token(root, "dashboard")
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
    tok = hp.write_launch_token(root, "dashboard")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    old_ck, old_secret = hdr["set-cookie"].split(";")[0], json.loads(body)["secret"]
    SECRETS[old_ck] = old_secret
    # a reused link revokes the session: the old cookie AND the old secret are dead, a new link gets a new secret
    st, hdr, _ = _raw(port, "POST", "/session", {"token": tok}, {"Origin": f"http://127.0.0.1:{port}"})
    assert st == 403 and "set-cookie" not in hdr
    tok2 = hp.write_launch_token(root, "dashboard")
    st, hdr, body = _raw(port, "POST", "/session", {"token": tok2}, {"Origin": f"http://127.0.0.1:{port}"})
    new_secret = json.loads(body)["secret"]
    assert st == 200 and new_secret and new_secret != old_secret
    new_ck = hdr["set-cookie"].split(";")[0]
    assert new_ck != old_ck
    assert post(port, "/api/act", ANSWER, {"Cookie": old_ck, "X-Orch-Page": old_secret})[0] == 403  # old pair dead
    assert post(port, "/api/act", ANSWER, {"Cookie": new_ck, "X-Orch-Page": old_secret})[0] == 403  # old secret dead


def test_every_dashboard_answer_forbids_framing_by_other_sites(live):
    """A foreign local page must not frame a signed-in dashboard tab (clickjacking with the page secret)."""
    _root, port = live
    for path in ("/", "/api/notices", "/nope"):
        _st, hdr, _ = _raw(port, "GET", path)
        assert "frame-ancestors 'self'" in hdr.get("content-security-policy", ""), path
