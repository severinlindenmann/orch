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


def test_a_notice_is_read_not_consumed_and_only_the_ack_of_a_session_clears_it(live):
    root, port = live
    nid = hp._notice_id("protection_reset", "x", hp.RESET_NOTICE)
    d = hp.key_dir(root)
    note = {"id": nid, "kind": "protection_reset", "at": "x", "text": hp.RESET_NOTICE}
    hp._write_private(d / "notices.json", json.dumps([note]))

    def get(cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": f"127.0.0.1:{port}", **({"Cookie": cookie} if cookie else {})}
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
    s2 = pageproof.PageSession(root, "dashboard")
    assert s2.can_mint({"Host": "127.0.0.1:1", "Cookie": ck}, 1)
    s3 = pageproof.PageSession(root, "dashboard")  # a second restart: the marker is spent
    assert not s3.can_mint({"Host": "127.0.0.1:1", "Cookie": ck}, 1)


def test_resume_cookie_is_one_use_expires_and_only_after_a_click(live, monkeypatch):
    import time

    root, _ = live
    assert hp.write_resume_cookie(root, "dashboard", "c" * 40)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + hp.RESUME_LIFE + 5)
    assert hp.take_resume_cookie(root, "dashboard") is None  # expired
    monkeypatch.setattr(time, "time", real)
    assert hp.take_resume_cookie(root, "dashboard") is None  # and the file is gone
    assert not hp.write_resume_cookie(root, "mine", "c" * 40)  # a local add-on gets nothing


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
    assert st == 204 and ck.startswith("orch_page=")
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
            headers={"Host": f"127.0.0.1:{port}", **({"Cookie": cookie} if cookie else {})},
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
    assert a.proof_for("check.reopen", {"ticket": "t_a", "check": "c1"}) == ("check.wont_do_undo", "t_a:c1")
    assert a.proof_for("check.set", {"ticket": "t_a", "check": "c1", "done": False}) == (
        "check.wont_do_undo",
        "t_a:c1",
    )
    assert a.proof_for("check.set", {"ticket": "t_a", "check": "c1", "done": True}) is None


def test_check_edit_and_remove_clicks_need_a_proof_on_the_real_server_path():
    from orch_dashboard import actions as a

    args = {"ticket": "t_abcdef", "check": "c1"}
    assert a.proof_for("check.edit", {**args, "text": "x"}) == ("check.wont_do_undo", "t_abcdef:c1")
    assert a.proof_for("check.remove", args) == ("check.wont_do_undo", "t_abcdef:c1")
    assert a.build_argv("check.remove", args)[:4] == ["check", "remove", "t_abcdef", "c1"]
    assert a.build_argv("check.edit", {**args, "text": "a -- b"})[-2:] == ["--", "a -- b"]
