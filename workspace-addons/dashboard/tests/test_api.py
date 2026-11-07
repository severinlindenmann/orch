import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from orch_dashboard.data import find_workspace, load_state


def get(url, method="GET"):
    req = urllib.request.Request(url, method=method, data=b"x" if method != "GET" else None)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_state_reads_contract_ticket(ws):
    s = load_state(ws)
    assert s["workspace"] == "Pilatus"
    ids = {t["id"] for t in s["tickets"]}
    assert "t_7k3f9q" in ids and "t_weekly01" in ids
    assert s["skipped"] == 1  # the broken file
    t = next(t for t in s["tickets"] if t["id"] == "t_7k3f9q")
    assert t["ext"]["dashboard"] == {"pinned": True}  # unknown fields kept
    assert len(t["checklist"]) == 3 and t["questions"][0]["answer"] is None


def test_scheduler_is_not_a_dashboard_concept(ws):
    s = load_state(ws)
    assert "scheduler" not in s and s["addons"] == []  # no orch command, no add-ons: no trace of any add-on


def test_http_state_and_static(server):
    code, body, _h = get(server + "/api/state")
    assert code == 200 and json.loads(body)["workspace"] == "Pilatus"
    for p in (
        "/",
        "/app.js",
        "/style.css",
        "/kit/tokens.css",
        "/logo.svg",
        "/favicon.svg",
        "/apple-touch-icon.png",
    ):
        assert get(server + p)[0] == 200, p
    assert get(server + "/../../etc/passwd")[0] == 404
    assert get(server + "/.orch/secrets/x.json")[0] == 404


def test_read_only_server_refuses_writes(server):
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        assert get(server + "/api/state", m)[0] == 405


def test_binds_loopback_only(ws):
    from orch_dashboard.server import make_server

    srv = make_server(ws, 0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_find_workspace_walks_up(ws):
    sub = ws / "a" / "b"
    sub.mkdir(parents=True)
    assert find_workspace(sub) == ws.resolve()


def test_rejects_foreign_host_header(server):
    import http.client

    port = int(server.rsplit(":", 1)[1])
    for host, want in (
        ("evil.example.com", 421),
        (f"evil.example.com:{port}", 421),
        (f"localhost:{port}", 200),
        (f"127.0.0.1:{port}", 200),
    ):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/api/state", headers={"Host": host})
        assert c.getresponse().status == want, host


def test_addon_endpoint_serves_only_active_tabs(ws, fake_orch):
    import threading

    from orch_dashboard.server import make_server

    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        st = json.loads(get(base + "/api/state")[1])
        assert [a["name"] for a in st["addons"]] == ["scheduler"]
        code, body, _ = get(base + "/api/addon/scheduler")
        assert code == 200 and json.loads(body)["state"] == "ok"
        assert get(base + "/api/addon/wiki")[0] == 404  # installed, not active
        assert get(base + "/api/addon/..%2F..%2Fx")[0] == 404
        assert get(base + "/api/addon/scheduler", "POST")[0] == 405
        assert get(base + "/blocks.js")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_tickets_come_from_the_orch_command_when_there_is_one(ws, fake_orch):
    t = json.loads((ws / ".orch" / "tickets" / "t_7k3f9q.json").read_text())
    t["title"] = "From the command"
    (fake_orch.parent / "tickets.json").write_text(json.dumps([t]))
    src = fake_orch.read_text().replace(
        'elif a[1:] == ["view", "--json"]:',
        'elif a[:2] == ["ticket", "list"]:\n    print((d / "tickets.json").read_text())\nelif a[1:] == ["view", "--json"]:',
    )
    fake_orch.write_text(src)
    s = load_state(ws, orch_bin=str(fake_orch))
    assert [x["title"] for x in s["tickets"]] == ["From the command"]


def test_ticket_list_asks_for_finished_tickets_too(ws, fake_orch):
    """`orch ticket list` hides done/dropped unless --all: without it they vanished from the dashboard (found by e2e A12)."""
    calls = fake_orch.parent / "calls.txt"
    fake_orch.write_text(
        fake_orch.read_text().replace(
            "mode = (d", f'open({str(calls)!r}, "a").write(" ".join(a) + "\\n")\nmode = (d', 1
        )
    )
    load_state(ws, orch_bin=str(fake_orch))
    assert "ticket list --all --json" in calls.read_text()


def test_foreign_origin_never_triggers_a_pull(ws, fake_orch):
    import http.client
    import threading

    from orch_dashboard.server import make_server

    runs = fake_orch.parent / "runs.txt"
    fake_orch.write_text(
        fake_orch.read_text().replace(
            "mode = (d",
            f'open({str(runs)!r}, "a").write("x") if a[1:] == ["view", "--json"] else None\nmode = (d',
        )
    )
    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for hdr, want in (
            ({"Origin": "https://evil.example"}, 403),
            ({"Origin": f"http://localhost:{port}"}, 403),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
            ({"Origin": f"http://127.0.0.1:{port}"}, 200),
            ({}, 200),
        ):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request("GET", "/api/addon/scheduler", headers={"Host": f"127.0.0.1:{port}", **hdr})
            assert c.getresponse().status == want, hdr
        assert runs.read_text() == "xx"  # only the two same-origin requests ran the add-on
    finally:
        srv.shutdown()
        srv.server_close()


def test_file_proof_knows_if_it_is_on_this_computer(ws):
    import json as _json

    from orch_dashboard.data import load_tickets

    p = ws / ".orch" / "tickets" / "t_proof0001.json"
    ex = _json.loads((ws / ".orch" / "tickets" / "t_weekly01.json").read_text())
    ex.update(
        id="t_proof0001",
        checklist=[
            {
                "id": "c1",
                "text": "x",
                "done": True,
                "evidence": [
                    {"type": "file", "ref": "out/here.csv"},
                    {"type": "file", "ref": "out/gone.csv"},
                    {"type": "file", "ref": "../../outside.txt"},
                    {"type": "note", "ref": "hello"},
                ],
            }
        ],
    )
    p.write_text(_json.dumps(ex))
    (ws / "out").mkdir()
    (ws / "out" / "here.csv").write_text("a")
    (ws.parent / "outside.txt").write_text("secret")
    t = next(x for x in load_tickets(ws)[0] if x["id"] == "t_proof0001")
    ev = t["checklist"][0]["evidence"]
    assert [e.get("missing") for e in ev] == [
        False,
        True,
        True,
        None,
    ]  # outside the workspace counts as not here


def test_file_proof_symlink_and_absolute_path_outside_the_workspace_count_as_missing(ws):
    import json as _json

    from orch_dashboard.data import load_tickets

    outside = ws.parent / "private.txt"
    outside.write_text("secret")
    (ws / "link.txt").symlink_to(outside)
    ex = _json.loads((ws / ".orch" / "tickets" / "t_weekly01.json").read_text())
    ex.update(
        id="t_proof0002",
        checklist=[
            {
                "id": "c1",
                "text": "x",
                "done": True,
                "evidence": [
                    {"type": "file", "ref": "link.txt"},
                    {"type": "file", "ref": str(outside)},
                    {"type": "file", "ref": "/etc/hosts"},
                ],
            }
        ],
    )
    (ws / ".orch" / "tickets" / "t_proof0002.json").write_text(_json.dumps(ex))
    t = next(x for x in load_tickets(ws)[0] if x["id"] == "t_proof0002")
    assert [e["missing"] for e in t["checklist"][0]["evidence"]] == [True, True, True]


def test_many_parallel_loads_never_reset(server):
    """The page fetches a dozen files at once; a small listen backlog used to reset some of them."""
    from concurrent.futures import ThreadPoolExecutor

    paths = [
        "/",
        "/app.js",
        "/style.css",
        "/helpers.js",
        "/blocks.js",
        "/kit/tokens.css",
        "/kit/components.css",
        "/kit/motion.css",
        "/kit/motion.js",
        "/kit/icons.js",
        "/kit/question-card.js",
        "/api/state",
    ] * 6
    with ThreadPoolExecutor(max_workers=36) as pool:
        codes = list(pool.map(lambda p: get(server + p)[0], paths))
    assert set(codes) == {200}


# ---- Artifacts tab: file list and safe file reads


def _get(base, path, headers=None):
    import http.client

    port = int(base.rsplit(":", 1)[1])
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())


@pytest.fixture
def art(ws, act_orch):
    import threading

    from orch_dashboard.server import make_server

    d = ws / ".orch" / "tickets" / "t_other000x"
    (d / "artifacts" / "sub").mkdir(parents=True)
    (d / "evidence").mkdir()
    (d / "files").mkdir()
    (d / "files" / "voice.m4a").write_bytes(b"0123456789")
    (d / "files" / "roof.jpg").write_bytes(b"\xff\xd8jpg")
    (d / "files" / "evil.exe").write_bytes(b"MZ")
    (d / "artifacts" / "notes.md").write_text("# hello")
    (d / "artifacts" / "page.html").write_text("<script>alert(1)</script>")
    (d / "artifacts" / "pic.png").write_bytes(b"\x89PNG")
    (d / "artifacts" / "pic.svg").write_text("<svg onload=alert(1)/>")
    (d / "artifacts" / "sub" / "a.txt").write_text("deep")
    (d / "artifacts" / "big.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (d / "evidence" / "proof.txt").write_text("proof")
    (ws / "secret.txt").write_text("outside")
    (d / "artifacts" / "link.txt").symlink_to(ws / "secret.txt")
    src = act_orch.read_text().replace(
        "mode = (d",
        'if a[:2] == ["ticket", "artifacts"]:\n    print(json.dumps([{"name": "notes.md", "size": 7, "mtime": "2026-11-06T16:05:00Z", "path": "x"},'
        ' {"name": "bad", "size": "x"}, {"size": 1}]))\n    sys.exit(0)\nmode = (d',
    )
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_artifact_list_comes_from_orch_and_drops_bad_rows(art):
    code, body, _ = _get(art, "/api/artifacts/t_other000x")
    assert code == 200 and json.loads(body) == {
        "available": True,
        "files": [{"name": "notes.md", "size": 7, "mtime": "2026-11-06T16:05:00Z"}],
    }
    assert _get(art, "/api/artifacts/..%2fx")[0] == 404 and _get(art, "/api/artifacts/t_x")[0] == 404


def test_artifact_list_says_unavailable_when_orch_cannot_list(ws, act_orch):
    from orch_dashboard import ticketfiles

    assert ticketfiles.listing(ws, str(act_orch), "t_other000x") == {
        "available": False,
        "files": [],
    }  # the fake exits 0 with no list
    assert ticketfiles.listing(ws, None, "t_other000x")["available"] is False


def test_files_are_shown_as_text_or_picture_only(art):
    q = "/api/file?t=t_other000x&k=artifacts&n="
    code, body, h = _get(art, q + "notes.md")
    assert (
        code == 200
        and body == b"# hello"
        and h["Content-Type"].startswith("text/plain")
        and h["X-Content-Type-Options"] == "nosniff"
    )
    assert "sandbox" in h["Content-Security-Policy"]
    code, body, h = _get(art, q + "page.html")  # a page is text, never a page
    assert code == 200 and h["Content-Type"].startswith("text/plain")
    assert _get(art, q + "pic.png")[2]["Content-Type"] == "image/png"
    assert _get(art, q + "pic.svg")[0] == 404  # svg can run code: no preview
    assert _get(art, q + "sub/a.txt")[1] == b"deep"
    assert _get(art, "/api/file?t=t_other000x&k=evidence&n=proof.txt")[1] == b"proof"
    assert _get(art, q + "pic.svg&dl=1")[2]["Content-Disposition"].startswith("attachment")
    assert _get(art, q + "big.txt")[0] == 413


@pytest.mark.parametrize(
    "q",
    [
        "t=t_other000x&k=artifacts&n=../../../../secret.txt",
        "t=t_other000x&k=artifacts&n=link.txt",
        "t=t_other000x&k=artifacts&n=/etc/passwd",
        "t=t_other000x&k=artifacts&n=sub/../notes.md",
        "t=t_other000x&k=artifacts&n=..%5csecret",
        "t=t_other000x&k=tickets&n=../t_other000x.json",
        "t=..&k=artifacts&n=notes.md",
        "t=t_other000x&k=artifacts&n=",
        "t=t_other000x&k=artifacts&n=nothere.txt",
        "t=t_other000x&k=artifacts&n=notes.md%00.png",
        "t=t_other000x&k=artifacts&n=sub",
    ],
)
def test_file_reads_cannot_leave_the_ticket_folders(art, q):
    assert _get(art, "/api/file?" + q)[0] in (404, 400)


def test_a_linked_folder_is_not_followed(art, ws, tmp_path):
    d = ws / ".orch" / "tickets" / "t_other000x"
    out = tmp_path / "elsewhere"
    out.mkdir()
    (out / "x.txt").write_text("leak")
    (d / "linked").symlink_to(out)
    import shutil

    shutil.rmtree(d / "evidence")
    (d / "evidence").symlink_to(out)
    assert _get(art, "/api/file?t=t_other000x&k=evidence&n=x.txt")[0] == 404


def test_file_reads_refuse_foreign_origins(art):
    assert (
        _get(art, "/api/file?t=t_other000x&k=artifacts&n=notes.md", {"Sec-Fetch-Site": "cross-site"})[0]
        == 403
    )
    assert _get(art, "/api/artifacts/t_other000x", {"Sec-Fetch-Site": "cross-site"})[0] == 403


def test_hard_links_and_pipes_are_not_served(art, ws):
    import os

    d = ws / ".orch" / "tickets" / "t_other000x" / "artifacts"
    os.link(ws / "secret.txt", d / "hard.txt")
    assert _get(art, "/api/file?t=t_other000x&k=artifacts&n=hard.txt")[0] == 404
    if hasattr(os, "mkfifo"):
        os.mkfifo(d / "pipe.txt")
        assert (
            _get(art, "/api/file?t=t_other000x&k=artifacts&n=pipe.txt")[0] == 404
        )  # answers at once, no hang


def test_file_reads_go_through_the_one_core_reader():
    src = (Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "ticketfiles.py").read_text()
    assert "safefile.read_ticket_file" in src and "os.open" not in src and "lstat" not in src


def test_phone_files_are_shown_and_a_voice_note_plays_with_byte_ranges(art):
    q = "/api/file?t=t_other000x&k=files&n="
    code, body, h = _get(art, q + "voice.m4a")
    assert (
        code == 200
        and h["Content-Type"] == "audio/mp4"
        and h["Accept-Ranges"] == "bytes"
        and body == b"0123456789"
    )
    code, body, h = _get(art, q + "voice.m4a", {"Range": "bytes=2-4"})
    assert code == 206 and body == b"234" and h["Content-Range"] == "bytes 2-4/10"
    assert _get(art, q + "roof.jpg")[2]["Content-Type"] == "image/jpeg"
    assert _get(art, q + "evil.exe")[0] == 404  # not shown inline
    assert _get(art, q + "evil.exe&dl=1")[2]["Content-Disposition"].startswith("attachment")
    assert _get(art, q + "../notes.md")[0] in (404, 400)
    assert _get(art, "/api/file?t=t_other000x&k=audio&n=voice.m4a")[0] == 404


def test_general_conversation_is_in_the_state_but_never_a_ticket(ws):
    from orch_dashboard.data import load_state

    t = ws / ".orch" / "tickets"
    skipped = load_state(ws)["skipped"]
    g = {
        "schema": "orch.ticket/1",
        "id": "t_general01",
        "title": "General",
        "general": True,
        "status": "open",
        "created_at": "2026-11-06T10:00:00Z",
        "updated_at": "2026-11-06T10:05:00Z",
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [
            {"at": "2026-11-06T10:00:00Z", "by": "x", "via": "cli", "text": "Created"},
            {"at": "2026-11-06T10:05:00Z", "by": "human:anna", "via": "phone", "text": "From Anna: hello"},
        ],
    }
    (t / "t_general01.json").write_text(json.dumps(g))
    st = load_state(ws)
    assert all(x["id"] != "t_general01" for x in st["tickets"]) and st["skipped"] == skipped
    assert st["general"]["id"] == "t_general01" and [h["text"] for h in st["general"]["history"]] == [
        "From Anna: hello"
    ]
    assert load_state(ws, with_addons=False)["general"] is None


def test_refs_carry_the_phone_artifact_id_rev_and_kind(ws):
    from orch_dashboard.data import add_artifact_marks

    t = {
        "refs": [{"url": "https://example.com/org/repo/pull/7"}, {"url": "https://x.example/f/abc123"}],
        "checklist": [{"evidence": [{"type": "commit", "ref": "https://github.com/o/r/commit/abcdef1234"}]}],
    }
    add_artifact_marks([t])
    assert t["art"]["https://x.example/f/abc123"]["kind"] == "html"
    assert t["art"]["https://github.com/o/r/commit/abcdef1234"]["kind"] == "commit"
    assert t["art"]["https://example.com/org/repo/pull/7"]["id"].startswith("a_")


def test_malformed_ticket_data_never_breaks_the_artifact_marks():
    from orch_dashboard.data import add_artifact_marks

    ts = [
        {
            "refs": "x",
            "checklist": [1, {"evidence": "no"}, {"evidence": [3, {"type": "pr", "ref": "http://[bad"}]}],
        },
        {"refs": [5, {"url": "http://[bad"}, {"url": "https://ok.example/f/zz"}], "checklist": None},
    ]
    add_artifact_marks(ts)
    assert ts[0]["art"] == {} and ts[1]["art"]["https://ok.example/f/zz"]["kind"] == "html"


@pytest.mark.parametrize(
    "rng,code",
    [
        ("bytes=20-30", 416),
        ("bytes=-", 200),
        ("bytes=a-b", 200),
        ("bytes=5-2", 200),
        ("bytes=0-99999999999999999999", 200),
        ("bytes=-3", 206),
        ("bytes=8-", 206),
    ],
)
def test_range_edge_cases_never_crash(art, rng, code):
    r = _get(art, "/api/file?t=t_other000x&k=files&n=voice.m4a", {"Range": rng})
    assert r[0] == code
    if code == 416:
        assert r[2]["Content-Range"] == "bytes */10"


@pytest.mark.parametrize(
    "path", ["../../etc/passwd", ".orch/secrets/x", ".git/config", "link.txt", "/etc/passwd"]
)
def test_ref_file_rejects_unsafe_stored_paths(ws, path):
    from orch_dashboard.reffiles import read

    outside = ws.parent / "private.txt"
    outside.write_text("secret")
    (ws / "link.txt").symlink_to(outside)
    ticket = ws / ".orch/tickets/t_weekly01.json"
    data = json.loads(ticket.read_text())
    data["refs"] = [{"kind": "file", "path": path}]
    ticket.write_text(json.dumps(data))
    assert read(ws, "t_weekly01", "1")[0] == 404


def test_ref_file_types_size_local_and_index(ws):
    from orch_dashboard.reffiles import read

    ticket = ws / ".orch/tickets/t_weekly01.json"
    data = json.loads(ticket.read_text())
    for name, content, status in [
        ("notes.md", b"# Hello", 200),
        ("page.html", b"<script>x</script>", 415),
        ("pic.svg", b"<svg/>", 415),
        ("pic.png", b"\x89PNG", 200),
        ("large.txt", b"a" * (512 * 1024 + 1), 404),
    ]:
        (ws / name).write_bytes(content)
        data["refs"] = [{"kind": "file", "path": name}]
        ticket.write_text(json.dumps(data))
        assert read(ws, "t_weekly01", "1")[0] == status
    for n in ("0", "-1", "2", "x"):
        assert read(ws, "t_weekly01", n)[0] == 404
    data["refs"] = [{"kind": "file", "path": "notes.md", "local": True}]
    ticket.write_text(json.dumps(data))
    assert read(ws, "t_weekly01", "1")[0] == 404


def test_ref_file_headers_and_foreign_origin(ws, server):
    ticket = ws / ".orch/tickets/t_weekly01.json"
    data = json.loads(ticket.read_text())
    data["refs"] = [{"kind": "file", "path": "notes.md"}]
    ticket.write_text(json.dumps(data))
    (ws / "notes.md").write_text("# Hello")
    path = "/api/ref-file?ticket=t_weekly01&n=1"
    code, body, headers = _get(server, path)
    assert code == 200 and body == b"# Hello"
    assert headers["Content-Type"].startswith("text/plain")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Disposition"] == "inline"
    assert "sandbox" in headers["Content-Security-Policy"]
    assert _get(server, path, {"Origin": "https://foreign.example"})[0] == 403


def test_events_change_within_one_second_and_initial_event(ws, server):
    import http.client
    import time

    c = http.client.HTTPConnection("127.0.0.1", int(server.rsplit(":", 1)[1]), timeout=1)
    c.request("GET", "/api/events")
    r = c.getresponse()
    try:
        assert r.status == 200
        assert r.getheader("X-Accel-Buffering") == "no"
        assert r.getheader("Cache-Control") == "no-store"
        assert r.readline() == b"event: rev\n"
        first = r.readline()
        assert first.startswith(b"data: ")
        assert r.readline() == b"\n"
        start = time.monotonic()
        (ws / ".orch/tickets/t_new00001.json").write_text("{}")
        assert r.readline() == b"event: rev\n"
        assert r.readline() != first
        assert time.monotonic() - start < 1
    finally:
        r.close()
        c.close()


def test_events_origin_and_client_cap(server):
    import http.client

    assert _get(server, "/api/events", {"Origin": "https://foreign.example"})[0] == 403
    connections = []
    responses = []
    try:
        for _ in range(20):
            c = http.client.HTTPConnection("127.0.0.1", int(server.rsplit(":", 1)[1]), timeout=2)
            connections.append(c)
            c.request("GET", "/api/events")
            r = c.getresponse()
            responses.append(r)
            assert r.status == 200
            assert r.readline() == b"event: rev\n"
        assert _get(server, "/api/events")[0] == 503
    finally:
        for r in responses:
            r.close()
        for c in connections:
            c.close()


def test_shared_watcher_cap_changes_and_stops(ws):

    from orch_dashboard.events import Revisions

    revisions = Revisions(ws)
    assert all(revisions.join() for _ in range(20))
    watcher = revisions.thread
    assert not revisions.join()
    old = revisions.rev
    (ws / ".orch/tickets/new.json").write_text("{}")
    with revisions.condition:
        assert revisions.condition.wait_for(lambda: revisions.rev != old, timeout=1)
    for _ in range(20):
        revisions.leave()
    watcher.join(timeout=1)
    assert not watcher.is_alive() and revisions.thread is None


def test_event_and_ref_routes_enforce_origin_and_host_without_a_listener(ws):
    """Exercise routing before opening a stream; no listening socket needed."""
    from orch_dashboard.server import Handler

    for path in ("/api/events", "/api/ref-file?ticket=t_weekly01&n=1"):
        for headers, expected in [
            ({"Host": "foreign.example"}, 421),
            ({"Host": "localhost:8420", "Origin": "https://foreign.example"}, 403),
            ({"Host": "localhost:8420", "Sec-Fetch-Site": "cross-site"}, 403),
        ]:
            handler = object.__new__(Handler)
            handler.path, handler.headers, handler.root = path, headers, ws
            sent = []
            handler._send = lambda *args, sent=sent, **kw: sent.append(args)
            handler.do_GET()
            assert sent[0][0] == expected


def test_event_handler_flushes_initial_and_changed_revision_without_a_listener(ws):
    import threading
    from types import SimpleNamespace

    from orch_dashboard.events import Revisions
    from orch_dashboard.server import Handler

    revisions = Revisions(ws)
    frames = []
    initial, changed = threading.Event(), threading.Event()

    class Writer:
        def write(self, frame):
            frames.append(frame)
            if len(frames) == 1:
                initial.set()
            else:
                changed.set()
                raise BrokenPipeError

        def flush(self):
            pass

    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(revisions=revisions)
    handler.wfile = Writer()
    handler.send_response = lambda *a: None
    handler.send_header = lambda *a: None
    handler.end_headers = lambda: None
    thread = threading.Thread(target=handler._events)
    thread.start()
    try:
        assert initial.wait(1)
        (ws / ".orch/tickets/new.json").write_text("{}")
        assert changed.wait(1)
        assert frames[0].startswith(b"event: rev\ndata: ")
        assert frames[0] != frames[1]
    finally:
        revisions.close()
        thread.join(1)
    assert revisions.clients == 0
