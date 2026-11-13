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


def test_state_rev_covers_every_ticket_field(ws):
    """The page re-renders when `rev` changes: it is a hash of the whole state, so a ticket that only gets `work`
    (its separate copy) or any other field still changes it; the clock alone does not."""
    f = ws / ".orch" / "tickets" / "t_7k3f9q.json"
    before = load_state(ws)["rev"]
    assert load_state(ws)["rev"] == before
    t = json.loads(f.read_text())
    t["work"] = {"folders": [{"branch": "orch/t_7k3f9q", "base": "abc", "sub": "", "host": "m"}]}
    f.write_text(json.dumps(t))
    with_copy = load_state(ws)["rev"]
    assert with_copy != before
    t["work"]["folders"][0]["sub"] = "app"
    f.write_text(json.dumps(t))
    assert load_state(ws)["rev"] not in (before, with_copy)


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


# ---- Files tab: file list and safe file reads


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
    (d / "artifacts" / "data.json").write_text('{"a": 1}')
    (d / "artifacts" / "feed.xml").write_text("<x/>")
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


def test_artifact_list_from_the_real_core_for_a_ticket_with_only_artifacts(tmp_path):
    """#351: a ticket whose only files are in its artifacts folder (no evidence/, no proofs) lists them, end
    to end through the real `orch ticket artifacts --json` (a workspace made by `orch init` + `ticket new`)."""
    import os
    import subprocess
    import sys

    from orch_dashboard import ticketfiles

    pytest.importorskip("cryptography")  # the real CLI runs in a subprocess; this venv may lack the core deps
    command = tmp_path / "orch-core"
    src = Path(__file__).resolve().parents[3] / "workspace" / "src"
    command.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(src)!r})\n"
        "from orch.cli import main\nraise SystemExit(main())\n"
    )
    command.chmod(0o700)
    root = tmp_path / "Demo"
    root.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("ORCH_ROOT", "ORCH_BIN")}

    def orch(*argv):
        r = subprocess.run(
            [str(command), *argv], check=False, cwd=root, capture_output=True, text=True, env=env
        )
        assert r.returncode == 0, r.stderr + r.stdout
        return r.stdout

    orch("init", "--yes", "--json")
    tid = json.loads(orch("ticket", "new", "Demo with files", "--json"))["id"]
    d = root / ".orch" / "tickets" / tid
    (d / "artifacts" / "sub").mkdir(parents=True)
    (d / "artifacts" / "report.md").write_text("# report")
    (d / "artifacts" / "sub" / "data.csv").write_text("a,b\n")
    assert not (d / "evidence").exists()
    got = ticketfiles.listing(root, str(command), tid)
    assert got["available"] is True
    assert sorted(f["name"] for f in got["files"]) == ["report.md", "sub/data.csv"]
    assert {f["name"]: f["size"] for f in got["files"]} == {"report.md": 8, "sub/data.csv": 4}
    assert all(f["mtime"] for f in got["files"])


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
    assert _get(art, q + "pic.png")[2]["X-Content-Type-Options"] == "nosniff"
    for name in ("data.json", "feed.xml"):  # never served with their own type
        h = _get(art, q + name)[2]
        assert h["Content-Type"].startswith("text/plain") and h["X-Content-Type-Options"] == "nosniff"
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
            {
                "at": "2026-11-06T10:05:00Z",
                "by": "human:anna",
                "via": "phone",
                "text": "From Anna: hello",
                "chat_message": True,
            },
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


def test_links_shape_and_origin(act_server, act_orch, ws):
    import http.client

    script = act_orch.read_text()
    pos = script.index("\n") + 1
    script = (
        script[:pos]
        + """import sys, json
if sys.argv[1:3] == ["addon", "list"]:
    print('[{"name":"publish","active":true}]'); sys.exit(0)
if sys.argv[1:3] == ["publish", "whoami"]:
    print('{"id":"w_local"}'); sys.exit(0)
if sys.argv[1:3] == ["publish", "list"]:
    print(json.dumps({"files":[{"id":"f_a","name":"Report","size":3,"expires_at":"2020-01-01T00:00:00Z","url":"https://example.test/f/a","key":"secretsecretsecret1"},{"id":"f_b","name":"Other","size":4,"expires_at":None,"url":"https://example.test/f/b"}],"apps":[{"token":"hidden"}]})); sys.exit(0)
"""
        + script[pos:]
    )
    act_orch.write_text(script)
    secrets = ws / ".orch" / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "publish.json").write_text(
        json.dumps({"url": "https://example.test", "workspace": "w", "token": "t"})
    )
    code, body, _ = get(act_server + "/api/links")
    assert code == 200
    rows = json.loads(body)["links"]
    assert rows[0] == {
        "id": "f_a",
        "name": "Report",
        "size": 3,
        "expires_at": "2020-01-01T00:00:00Z",
        "expired": True,
        "link": "https://example.test/f/f_a#k=secretsecretsecret1",
        "copy": True,
    }
    assert rows[1]["link"] is None and rows[1]["copy"] is False  # no saved key
    assert "hidden" not in body.decode() and '"key"' not in body.decode()
    c = http.client.HTTPConnection("127.0.0.1", int(act_server.rsplit(":", 1)[1]))
    c.request("GET", "/api/links", headers={"Origin": "https://evil.example"})
    assert c.getresponse().status == 403


def _links_with(act_server, act_orch, ws, saved, files):
    script = act_orch.read_text()
    pos = script.index("\n") + 1
    script = (
        script[:pos]
        + "import sys, json\n"
        + 'if sys.argv[1:3] == ["addon", "list"]:\n    print(\'[{"name":"publish","active":true}]\'); sys.exit(0)\n'
        + 'if sys.argv[1:3] == ["publish", "whoami"]:\n    print(\'{"id":"w_local"}\'); sys.exit(0)\n'
        + f'if sys.argv[1:3] == ["publish", "list"]:\n    print(json.dumps({{"files": {files!r}}})); sys.exit(0)\n'
        + script[pos:]
    )
    act_orch.write_text(script)
    secrets = ws / ".orch" / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "publish.json").write_text(json.dumps({**saved, "workspace": "w", "token": "t"}))
    return json.loads(get(act_server + "/api/links")[1])["links"]


FILE = {"id": "f_a", "name": "R", "size": 3, "expires_at": None, "key": "secretsecretsecret1"}


def test_a_link_never_uses_an_address_the_server_supplies(act_server, act_orch, ws):
    rows = _links_with(
        act_server,
        act_orch,
        ws,
        {"url": "https://pub.example.test"},
        [{**FILE, "url": "https://evil.example/f/x"}],
    )
    assert rows[0]["link"] == "https://pub.example.test/f/f_a#k=secretsecretsecret1"
    rows = _links_with(act_server, act_orch, ws, {}, [{**FILE, "url": "https://evil.example/f/x"}])
    assert rows[0]["link"] is None and rows[0]["copy"] is False  # no saved address: no link


def test_a_saved_sub_path_is_kept_and_odd_addresses_are_refused(act_server, act_orch, ws):
    rows = _links_with(act_server, act_orch, ws, {"url": "https://pub.example.test/orch/"}, [FILE])
    assert rows[0]["link"] == "https://pub.example.test/orch/f/f_a#k=secretsecretsecret1"
    # self-hosted on localhost or a LAN address, TLS optional: http is fine, exactly the saved base
    rows = _links_with(act_server, act_orch, ws, {"url": "http://192.168.1.20:8080"}, [FILE])
    assert rows[0]["link"] == "http://192.168.1.20:8080/f/f_a#k=secretsecretsecret1"
    for bad in (
        "https://user@pub.example.test",
        "https://pub.example.test/a?x=1",
        "https://pub.example.test/a b",
    ):
        assert _links_with(act_server, act_orch, ws, {"url": bad}, [FILE])[0]["link"] is None


def test_links_off(server):
    assert json.loads(get(server + "/api/links")[1]) == {"links": []}


def test_state_preserves_started(ws):
    path = ws / ".orch" / "tickets" / "t_7k3f9q.json"
    ticket = json.loads(path.read_text())
    ticket.update(status="ready", started=True)
    path.write_text(json.dumps(ticket))
    result = next(t for t in load_state(ws)["tickets"] if t["id"] == ticket["id"])
    assert result["started"] is True
    assert result["status"] == "ready"


def test_standalone_fallback_shows_a_raw_done_as_review(tmp_path):
    """Without the orch core nothing can verify a signed verdict (V1): a raw `done` file reads as Review."""
    from orch_dashboard import data

    folder = tmp_path / ".orch" / "tickets"
    folder.mkdir(parents=True)
    t = json.loads((Path(__file__).parents[3] / "contracts" / "review" / "ticket.example.json").read_text())
    t.update(id="t_abc123", title="Export", status="done")
    (folder / "t_abc123.json").write_text(json.dumps(t))
    tickets, _skipped = data.load_tickets(tmp_path, orch_bin=None)
    assert [(x["id"], x["status"], x["verdict_needed"]) for x in tickets] == [("t_abc123", "review", True)]


def test_links_say_so_when_the_sharing_server_cannot_be_reached(monkeypatch, tmp_path):
    from orch_dashboard import data

    monkeypatch.setattr(data, "publish_connected", lambda root, orch_bin: True)
    monkeypatch.setattr(data, "run_orch", lambda *a, **k: None)  # `orch publish list` failed
    assert data.load_links(tmp_path, "orch") == {"links": [], "unreachable": True}
    monkeypatch.setattr(data, "run_orch", lambda *a, **k: {"files": []})
    assert data.load_links(tmp_path, "orch") == {"links": []}
