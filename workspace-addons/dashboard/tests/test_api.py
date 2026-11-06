import json
import urllib.error
import urllib.request

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
    for p in ("/", "/app.js", "/style.css", "/kit/tokens.css", "/logo.svg", "/favicon.svg", "/apple-touch-icon.png"):
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
    for host, want in (("evil.example.com", 421), (f"evil.example.com:{port}", 421), (f"localhost:{port}", 200),
                       (f"127.0.0.1:{port}", 200)):
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
    src = fake_orch.read_text().replace('elif a[1:] == ["view", "--json"]:',
                                        'elif a[:2] == ["ticket", "list"]:\n    print((d / "tickets.json").read_text())\nelif a[1:] == ["view", "--json"]:')
    fake_orch.write_text(src)
    s = load_state(ws, orch_bin=str(fake_orch))
    assert [x["title"] for x in s["tickets"]] == ["From the command"]


def test_ticket_list_asks_for_finished_tickets_too(ws, fake_orch):
    """`orch ticket list` hides done/dropped unless --all: without it they vanished from the dashboard (found by e2e A12)."""
    calls = fake_orch.parent / "calls.txt"
    fake_orch.write_text(fake_orch.read_text().replace(
        "mode = (d", f'open({str(calls)!r}, "a").write(" ".join(a) + "\\n")\nmode = (d', 1))
    load_state(ws, orch_bin=str(fake_orch))
    assert "ticket list --all --json" in calls.read_text()


def test_foreign_origin_never_triggers_a_pull(ws, fake_orch):
    import http.client
    import threading

    from orch_dashboard.server import make_server
    runs = fake_orch.parent / "runs.txt"
    fake_orch.write_text(fake_orch.read_text().replace("mode = (d", f'open({str(runs)!r}, "a").write("x") if a[1:] == ["view", "--json"] else None\nmode = (d'))
    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for hdr, want in (({"Origin": "https://evil.example"}, 403), ({"Origin": f"http://localhost:{port}"}, 403),
                          ({"Sec-Fetch-Site": "cross-site"}, 403), ({"Origin": f"http://127.0.0.1:{port}"}, 200), ({}, 200)):
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
    ex.update(id="t_proof0001", checklist=[{"id": "c1", "text": "x", "done": True, "evidence": [
        {"type": "file", "ref": "out/here.csv"}, {"type": "file", "ref": "out/gone.csv"},
        {"type": "file", "ref": "../../outside.txt"}, {"type": "note", "ref": "hello"}]}])
    p.write_text(_json.dumps(ex))
    (ws / "out").mkdir()
    (ws / "out" / "here.csv").write_text("a")
    (ws.parent / "outside.txt").write_text("secret")
    t = next(x for x in load_tickets(ws)[0] if x["id"] == "t_proof0001")
    ev = t["checklist"][0]["evidence"]
    assert [e.get("missing") for e in ev] == [False, True, True, None]  # outside the workspace counts as not here


def test_file_proof_symlink_and_absolute_path_outside_the_workspace_count_as_missing(ws):
    import json as _json

    from orch_dashboard.data import load_tickets
    outside = ws.parent / "private.txt"
    outside.write_text("secret")
    (ws / "link.txt").symlink_to(outside)
    ex = _json.loads((ws / ".orch" / "tickets" / "t_weekly01.json").read_text())
    ex.update(id="t_proof0002", checklist=[{"id": "c1", "text": "x", "done": True, "evidence": [
        {"type": "file", "ref": "link.txt"}, {"type": "file", "ref": str(outside)}, {"type": "file", "ref": "/etc/hosts"}]}])
    (ws / ".orch" / "tickets" / "t_proof0002.json").write_text(_json.dumps(ex))
    t = next(x for x in load_tickets(ws)[0] if x["id"] == "t_proof0002")
    assert [e["missing"] for e in t["checklist"][0]["evidence"]] == [True, True, True]


def test_many_parallel_loads_never_reset(server):
    """The page fetches a dozen files at once; a small listen backlog used to reset some of them."""
    from concurrent.futures import ThreadPoolExecutor
    paths = ["/", "/app.js", "/style.css", "/helpers.js", "/blocks.js", "/kit/tokens.css", "/kit/components.css", "/kit/motion.css",
             "/kit/motion.js", "/kit/icons.js", "/kit/question-card.js", "/api/state"] * 6
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
        "mode = (d", 'if a[:2] == ["ticket", "artifacts"]:\n    print(json.dumps([{"name": "notes.md", "size": 7, "mtime": "2026-11-06T16:05:00Z", "path": "x"},'
        ' {"name": "bad", "size": "x"}, {"size": 1}]))\n    sys.exit(0)\nmode = (d')
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_artifact_list_comes_from_orch_and_drops_bad_rows(art):
    code, body, _ = _get(art, "/api/artifacts/t_other000x")
    assert code == 200 and json.loads(body) == {"available": True, "files": [{"name": "notes.md", "size": 7, "mtime": "2026-11-06T16:05:00Z"}]}
    assert _get(art, "/api/artifacts/..%2fx")[0] == 404 and _get(art, "/api/artifacts/t_x")[0] == 404


def test_artifact_list_says_unavailable_when_orch_cannot_list(ws, act_orch):
    from orch_dashboard import ticketfiles
    assert ticketfiles.listing(ws, str(act_orch), "t_other000x") == {"available": False, "files": []}  # the fake exits 0 with no list
    assert ticketfiles.listing(ws, None, "t_other000x")["available"] is False


def test_files_are_shown_as_text_or_picture_only(art):
    q = "/api/file?t=t_other000x&k=artifacts&n="
    code, body, h = _get(art, q + "notes.md")
    assert code == 200 and body == b"# hello" and h["Content-Type"].startswith("text/plain") and h["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in h["Content-Security-Policy"]
    code, body, h = _get(art, q + "page.html")  # a page is text, never a page
    assert code == 200 and h["Content-Type"].startswith("text/plain")
    assert _get(art, q + "pic.png")[2]["Content-Type"] == "image/png"
    assert _get(art, q + "pic.svg")[0] == 404  # svg can run code: no preview
    assert _get(art, q + "sub/a.txt")[1] == b"deep"
    assert _get(art, "/api/file?t=t_other000x&k=evidence&n=proof.txt")[1] == b"proof"
    assert _get(art, q + "pic.svg&dl=1")[2]["Content-Disposition"].startswith("attachment")
    assert _get(art, q + "big.txt")[0] == 413


@pytest.mark.parametrize("q", ["t=t_other000x&k=artifacts&n=../../../../secret.txt", "t=t_other000x&k=artifacts&n=link.txt",
                               "t=t_other000x&k=artifacts&n=/etc/passwd", "t=t_other000x&k=artifacts&n=sub/../notes.md",
                               "t=t_other000x&k=artifacts&n=..%5csecret", "t=t_other000x&k=tickets&n=../t_other000x.json",
                               "t=..&k=artifacts&n=notes.md", "t=t_other000x&k=artifacts&n=", "t=t_other000x&k=artifacts&n=nothere.txt",
                               "t=t_other000x&k=artifacts&n=notes.md%00.png", "t=t_other000x&k=artifacts&n=sub"])
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
    assert _get(art, "/api/file?t=t_other000x&k=artifacts&n=notes.md", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert _get(art, "/api/artifacts/t_other000x", {"Sec-Fetch-Site": "cross-site"})[0] == 403
