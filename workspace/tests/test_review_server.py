"""`orch review` page server: session, origin checks, files, answers through the core, run file."""

import contextlib
import http.client
import io
import json
import subprocess
import threading
import time

import pytest

from orch import cli, history, review, review_server, tickets
from orch.errors import Refused

TOKENS = {}  # port -> page token of the servers made in this module
PNG = b"\x89PNG\r\n\x1a\nXX"


@pytest.fixture
def ws(proj, monkeypatch):
    """A test workspace with a real core: the child `orch review answer` runs in this process (cli.main)."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    monkeypatch.setenv("ORCH_BIN", "/tmp/planted-orch")  # must never be used

    seen = []

    def in_process(argv, cwd, env):
        seen.append({"argv": list(argv), "env": dict(env)})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())

    monkeypatch.setattr(review_server, "_child", in_process)
    real_make = review_server.make_server

    def make(root, port=0):
        srv = real_make(root, port)
        TOKENS[srv.server_address[1]] = srv.RequestHandlerClass.keywords["session"].token
        return srv

    monkeypatch.setattr(review_server, "make_server", make)
    ws_seen[root] = seen
    return root


ws_seen: dict = {}


def _add_card(root, run_cli, title="Block"):
    code, out, _ = run_cli("ticket", "new", "Q", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, err = run_cli(
        "ask", tid, title, "--draft", title, "--then", "I build it.", "--json", "--by", "agent:x"
    )
    assert code == 0, out + err
    q = json.loads(out)
    return tid, q["id"], tickets.question_digest(q)


@pytest.fixture
def card(ws, run):
    return _add_card(ws, run)


@pytest.fixture
def srv(ws):
    s = review_server.make_server(ws, 0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def req(port, method, path, body=None, headers=None, host=None, origin=True):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}"}
    if method == "POST":
        h["Content-Type"] = "application/json"
        if origin:
            h["Origin"] = f"http://127.0.0.1:{port}"
    h.update(headers or {})
    data = body if isinstance(body, (bytes, str)) else (json.dumps(body) if body is not None else None)
    c.request(method, path, data, h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def open_session(root, port):
    st, hd, body = req(port, "POST", "/session", {"token": TOKENS[port]})
    assert st == 200, body
    return hd["Set-Cookie"].split(";")[0]


def answer_body(tid, qid, d, **kw):
    return {"id": f"core:q:{tid}:{qid}", "digest": d, "verdict": "ok", "picked": None, "note": None, **kw}


def _reviewed(root, tid, sha, name, data):
    d = root / ".orch" / "tickets" / tid / "reviewed" / sha
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)


# ------------------------------------------------------------------ session and origin checks


def test_session_cookie_is_per_port_and_token_is_single_use(srv, ws):
    port = srv.server_address[1]
    tok = TOKENS[port]
    st, hd, _ = req(port, "POST", "/session", {"token": tok})
    ck = hd["Set-Cookie"]
    assert st == 200 and "HttpOnly" in ck and "SameSite=Strict" in ck
    assert ck.startswith(f"orch_review_{port}=")
    assert req(port, "POST", "/session", {"token": tok})[0] == 403  # single use
    assert req(port, "POST", "/session", {"token": "x" * 30})[0] == 403


def test_session_refused_through_a_proxy_or_foreign_host(srv, ws):
    port = srv.server_address[1]
    tok = TOKENS[port]
    assert req(port, "POST", "/session", {"token": tok}, {"X-Forwarded-For": "1.2.3.4"})[0] == 403
    assert req(port, "POST", "/session", {"token": tok}, {"Forwarded": "for=1.2.3.4"})[0] == 403
    assert req(port, "POST", "/session", {"token": tok}, host="evil.example:80")[0] == 403
    assert req(port, "POST", "/session", {"token": tok}, {"Origin": "http://evil.example"})[0] == 403
    assert req(port, "POST", "/session", {"token": tok}, origin=False)[0] == 403  # a POST needs an Origin
    assert req(port, "POST", "/session", {"token": tok}, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(port, "POST", "/session", {"token": tok})[0] == 200  # none of the above spent it


def test_unauthed_api_is_refused(srv, ws, card):
    port = srv.server_address[1]
    for path in ("/api/stack", "/api/answered"):
        st, _, body = req(port, "GET", path)
        assert st == 403 and json.loads(body)["error"]["code"] == "needs_person"
    tid, qid, d = card
    st, _, body = req(port, "POST", "/api/answer", answer_body(tid, qid, d))
    assert st == 403 and json.loads(body)["error"]["code"] == "needs_person"
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_a_wrong_cookie_is_no_session(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    wrong = ck.split("=")[0] + "=" + "x" * 32
    for path in ("/api/stack", "/api/answered"):
        assert req(port, "GET", path, headers={"Cookie": wrong})[0] == 403
    st, _, _ = req(port, "POST", "/api/answer", answer_body(tid, qid, d), {"Cookie": wrong})
    assert st == 403
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None
    assert req(port, "GET", "/api/stack", headers={"Cookie": ck})[0] == 200


def test_header_tricks_are_refused_even_with_a_session(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    body = answer_body(tid, qid, d)
    bad = [
        {"Cookie": ck, "X-Forwarded-For": "1.2.3.4"},
        {"Cookie": ck, "Forwarded": "for=1.2.3.4"},
        {"Cookie": ck, "Origin": "http://evil.example"},
        {"Cookie": ck, "Origin": "null"},
        {"Cookie": ck, "Sec-Fetch-Site": "cross-site"},
    ]
    for h in bad:
        assert req(port, "POST", "/api/answer", body, h)[0] == 403, h
    assert req(port, "POST", "/api/answer", body, {"Cookie": ck}, host="localhost.evil.example:1")[0] == 403
    assert req(port, "GET", "/api/stack", {"Cookie": ck}, host="evil.example:80")[0] == 403
    assert req(port, "GET", "/api/stack", headers={"Cookie": ck, "Forwarded": "for=1.2.3.4"})[0] == 403
    assert ws_seen[ws] == []  # no child ran
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


# ------------------------------------------------------------------ the stack and answers


def test_stack_and_answered_for_a_session(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    st, _, body = req(port, "GET", "/api/stack", headers={"Cookie": ck})
    data = json.loads(body)
    assert st == 200 and data["workspace"] == ws.name
    (c,) = [c for c in data["cards"] if c["ticket"] == tid]
    assert c["id"] == f"core:q:{tid}:{qid}" and c["digest"] == d
    st, _, body = req(port, "GET", "/api/answered", headers={"Cookie": ck})
    assert st == 200 and json.loads(body) == []


def test_answer_runs_the_core_in_a_child(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    st, _, body = req(port, "POST", "/api/answer", answer_body(tid, qid, d), {"Cookie": ck})
    assert st == 200 and json.loads(body) == {"ok": True}, body
    (call,) = ws_seen[ws]
    assert call["env"]["ORCH_ROOT"] == str(ws)
    assert call["argv"][:6] == ["review", "answer", tid, qid, "--verdict", "ok"]
    assert "--via" in call["argv"] and "page" in call["argv"] and "ORCH_VIA" in call["env"]
    q = tickets.load(ws, tid)["questions"][0]
    assert q["answer"] is not None and q["answered_by"].startswith("human:") and q["via"] == "page"
    st, _, body = req(port, "GET", "/api/answered", headers={"Cookie": ck})
    assert [e["key"] for e in json.loads(body)] == [qid]


def test_stale_digest_is_changed(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    st, _, body = req(port, "POST", "/api/answer", answer_body(tid, qid, "0" * 64), {"Cookie": ck})
    e = json.loads(body)
    assert st == 409 and e["ok"] is False and e["error"]["code"] == "changed"
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_answer_input_is_checked_before_anything_runs(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    h = {"Cookie": ck}
    cases = [
        answer_body(tid, qid, d, extra=1),  # unknown field
        answer_body(tid, qid, d, verdict="maybe"),
        answer_body(tid, qid, "xyz"),
        answer_body(tid, qid, d, picked="a b"),
        answer_body(tid, qid, d, picked=["A"]),
        answer_body(tid, qid, d, note="text"),
        {**answer_body(tid, qid, d), "id": "core:q:../../etc:q1"},
        {**answer_body(tid, qid, d), "id": f"core:q:{tid}:q1 --by human:x"},
        {**answer_body(tid, qid, d), "id": 5},
        [1, 2],
    ]
    for b in cases:
        st, _, body = req(port, "POST", "/api/answer", b, h)
        assert st == 400 and json.loads(body)["ok"] is False, b
    assert req(port, "POST", "/api/answer", "not json", h)[0] == 400
    assert req(port, "POST", "/api/answer", "x" * 20000, h)[0] == 400  # over the body limit
    big = answer_body(tid, qid, d, note={"text": "x" * 9000})
    st, _, body = req(port, "POST", "/api/answer", big, h)
    assert st == 413 and json.loads(body)["error"]["code"] == "too_large"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(
        "POST",
        "/api/answer",
        "{}",
        {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Cookie": ck,
         "Content-Type": "text/plain"},
    )  # fmt: skip
    assert c.getresponse().status == 400
    assert ws_seen[ws] == []


def test_check_card_answer_goes_through_review_answer(srv, ws, run):
    code, out, _ = run("ticket", "new", "Done?", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    tickets.load(ws, tid)  # exists
    from orch import review as rv

    t = tickets.load(ws, tid)
    assert rv.check_digest(t)  # the digest a Check card carries
    port = srv.server_address[1]
    ck = open_session(ws, port)
    st, _, body = req(
        port,
        "POST",
        "/api/answer",
        {"id": f"core:review:{tid}", "digest": "0" * 64, "verdict": "ok", "picked": None, "note": None},
        {"Cookie": ck},
    )
    (call,) = ws_seen[ws]
    assert call["argv"][:5] == ["review", "answer", tid, "review", "--verdict"] and st in (200, 409, 422), (
        body
    )


# ------------------------------------------------------------------ files


def test_file_route_serves_only_reviewed_copies(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, _, _ = card
    sha = "a" * 12
    _reviewed(ws, tid, sha, "shot.png", PNG)
    _reviewed(ws, tid, sha, "page.html", b"<script>alert(1)</script><p>hi</p>")
    _reviewed(ws, tid, sha, "evil.sh", b"echo hi")
    (ws / ".orch" / "tickets" / tid / "reviewed" / "notes.png").write_bytes(PNG)  # not inside a sha folder
    h = {"Cookie": ck}  # a frame or image sends the cookie only
    q = f"/api/file?t={tid}&c={sha}&n="
    st, hd, body = req(port, "GET", q + "shot.png", headers=h)
    assert st == 200 and body == PNG and hd["Content-Type"] == "image/png"
    assert hd["X-Content-Type-Options"] == "nosniff" and "sandbox" in hd["Content-Security-Policy"]
    st, hd, body = req(port, "GET", q + "page.html", headers=h)
    assert st == 200 and hd["Content-Type"].startswith("text/html")
    assert "sandbox" in hd["Content-Security-Policy"] and "script-src" not in hd["Content-Security-Policy"]
    assert "default-src 'none'" in hd["Content-Security-Policy"]
    for name in (
        "evil.sh",
        "../notes.png",
        "..%2Fnotes.png",
        "shot.png/",
        "/etc/passwd",
        "a\\b.png",
        "missing.png",
        "",
    ):
        assert req(port, "GET", q + name, headers=h)[0] == 404, name
    for path in (
        f"/api/file?t={tid}&c=bbbbbbbbbbbb&n=shot.png",  # a sha folder that does not exist
        f"/api/file?t={tid}&c={'a' * 11}&n=shot.png",
        f"/api/file?t={tid}&c=..&n=shot.png",
        f"/api/file?t=t_other123&c={sha}&n=shot.png",  # another ticket
        f"/api/file?t=..&c={sha}&n=shot.png",
        f"/api/file?c={sha}&n=shot.png",
    ):
        assert req(port, "GET", path, headers=h)[0] == 404, path
    assert req(port, "GET", q + "shot.png")[0] == 404  # no cookie
    assert req(port, "GET", q + "shot.png", headers={"Cookie": ck, "Forwarded": "for=1.1.1.1"})[0] == 404
    assert req(port, "GET", q + "shot.png", headers=h, host="evil.example:1")[0] == 403
    assert req(port, "GET", q + "shot.png", headers={**h, "Sec-Fetch-Site": "cross-site"})[0] == 403


def test_file_route_refuses_links(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, _, _ = card
    sha = "c" * 12
    d = ws / ".orch" / "tickets" / tid / "reviewed" / sha
    d.mkdir(parents=True)
    secret = ws / "secret.png"
    secret.write_bytes(PNG)
    (d / "link.png").symlink_to(secret)
    h = {"Cookie": ck}
    assert req(port, "GET", f"/api/file?t={tid}&c={sha}&n=link.png", headers=h)[0] == 404


# ------------------------------------------------------------------ the page files


def test_kit_allowlist(srv, ws):
    port = srv.server_address[1]
    st, hd, body = req(port, "GET", "/")
    assert st == 200 and b"review-host" in body and "frame-ancestors 'none'" in hd["Content-Security-Policy"]
    for f in review_server.KIT_FILES:
        assert req(port, "GET", f"/kit/{f}")[0] == 200, f
    st, hd, body = req(port, "GET", "/kit/review-boot.js")
    assert (
        st == 200
        and b"/session" in body
        and b"X-Orch-Page" not in body
        and hd["Content-Type"].startswith("text/javascript")
    )
    html = req(port, "GET", "/")[2].decode()
    import re

    linked = set(re.findall(r'(?:src|href)="kit/([^"]+)"', html))
    assert linked <= {*review_server.KIT_FILES, "review-boot.js"}  # review.html links nothing else
    for bad in (
        "origin.py", "__init__.py", "review.html", "demo.html", "DESIGN.md", "../origin.py", "..%2Forigin.py",
        "samples", "gallery.html", "fake_review_server.py", "",
    ):  # fmt: skip
        assert req(port, "GET", f"/kit/{bad}")[0] == 404, bad
    assert req(port, "GET", "/nope")[0] == 404
    assert req(port, "PUT", "/api/answer", "{}")[0] == 405


def test_missing_kit_message(ws, monkeypatch, capsys):
    monkeypatch.setattr(review_server, "kit_dir", lambda: None)

    class A:
        port, until, no_open, orch_root = 0, None, True, str(ws)

    assert review_server.serve(A) == 2
    assert capsys.readouterr().out.strip() == review_server.NO_KIT
    assert "orch review list" in review_server.NO_KIT and "orch review answer" in review_server.NO_KIT


# ------------------------------------------------------------------ serve(): lines, token, run file, link


def test_serve_prints_lines_never_the_token_and_keeps_a_run_file(ws, run, card, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(review_server, "_has_display", lambda: True)

    class A:
        port, until, no_open, orch_root = 0, "23:59", False, str(ws)

    t = threading.Thread(target=lambda: review_server.serve(A), daemon=True)
    # serve() waits for its deadline: let it end through the run file's deadline (set just ahead)
    monkeypatch.setattr(review_server, "parse_until", lambda text, now=None: ("23:59", time.time() + 3))
    t.start()
    for _ in range(100):
        if review_server.running(ws):
            break
        time.sleep(0.05)
    now = review_server.running(ws)
    assert now and now["url"].startswith("http://127.0.0.1:") and now["until"] == "23:59"
    port = now["port"]
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0] == "1 thing waits on you."
    assert lines[1] == f"Open: http://127.0.0.1:{port}/   works on this computer until 23:59"
    assert lines[2].startswith(f"On a server? From your laptop: ssh -L {port}:127.0.0.1:{port} ")
    assert lines[2].endswith("   then open the link.")
    for _ in range(100):  # the run file is written before the browser opens (CI race)
        if opened:
            break
        time.sleep(0.05)
    assert len(opened) == 1 and opened[0].startswith(f"http://127.0.0.1:{port}/#k=")
    token = opened[0].split("#k=")[1]
    assert token and token not in out and token not in err  # never printed
    d = json.loads(review_server.run_path(ws).read_text())
    assert (
        d["pid"] > 1
        and d["port"] == port
        and d["url"] == f"http://127.0.0.1:{port}/"
        and token not in json.dumps(d)
    )
    code, out, _ = run("review", "link", "--json")
    link = json.loads(out)
    assert code == 0 and link["running"] is True and link["url"] == now["url"] and link["until"] == "23:59"
    assert link["tunnel"].startswith("ssh -L")
    code, out, _ = run("review", "link")
    assert "The review page runs: " + now["url"] in out and "ssh -L" in out
    # the page signs in with the token the browser got, once
    assert req(port, "POST", "/session", {"token": token})[0] == 200
    t.join(10)
    assert not t.is_alive() and not review_server.run_path(ws).exists()
    assert review_server.running(ws) is None
    assert "The review page stopped." in capsys.readouterr().out
    code, out, _ = run("review", "link", "--json")
    assert json.loads(out)["running"] is False


def test_no_open_does_not_open_a_browser(ws, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(review_server, "parse_until", lambda text, now=None: ("23:59", time.time() + 1))

    class A:
        port, until, no_open, orch_root = 0, None, True, str(ws)

    assert review_server.serve(A) == 0
    assert opened == [] and "Nothing" not in capsys.readouterr().out


def test_busy_port_moves_to_the_next_one(ws, monkeypatch, capsys):
    first = review_server.make_server(ws, 0)
    p = first.server_address[1]
    try:
        monkeypatch.setattr(review_server, "parse_until", lambda text, now=None: ("23:59", time.time() + 1))

        class A:
            port, until, no_open, orch_root = p, None, True, str(ws)

        assert review_server.serve(A) == 0
        assert f"Open: http://127.0.0.1:{p}/" not in capsys.readouterr().out
    finally:
        first.server_close()


def test_parse_until():
    assert review_server.parse_until("9:05", now=0)[0] == "09:05"
    ts = review_server.parse_until("23:59")[1]
    assert time.time() < ts <= time.time() + 86400 + 60
    for bad in ("", "24:00", "12:60", "noon", "12:5", "12:30:00"):
        with pytest.raises(Refused):
            review_server.parse_until(bad)


def test_link_reports_not_running_when_the_process_is_gone(ws, run):
    p = review_server.write_run_file(ws, 8999, "23:59", time.time() + 600)
    d = json.loads(p.read_text())
    d["pid"] = 2**22 + 12345  # not a running process
    p.write_text(json.dumps(d))
    assert review_server.running(ws) is None
    p.write_text("not json")
    assert review_server.running(ws) is None
    code, out, _ = run("review", "link", "--json")
    assert json.loads(out)["running"] is False


def test_core_review_card_shapes_unchanged(ws, run, card):
    """the server uses the same stack and shown filter as `orch review list --json`"""
    code, out, _ = run("review", "list", "--json")
    assert json.loads(out)["cards"] == history.shown_json(ws, review.stack(ws))


def test_talk_answer_with_text_only_note_is_recorded(srv, ws, card):
    port = srv.server_address[1]
    ck = open_session(ws, port)
    tid, qid, d = card
    body = answer_body(tid, qid, d, verdict="talk", note={"text": "Move the title up.", "pins": []})
    st, _, out = req(port, "POST", "/api/answer", body, {"Cookie": ck})
    assert st == 200 and json.loads(out) == {"ok": True}, out
    q = tickets.load(ws, tid)["questions"][0]
    assert q["answer"] is not None and "Move the title up." in q["answer"]
