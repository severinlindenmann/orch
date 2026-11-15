"""/api/file kind=reviewed: only .orch/tickets/<tid>/reviewed/<sha12>/<name>, plain names, inert and sandboxed."""

import http.client
import threading
from urllib.parse import quote

import pytest

from orch_dashboard import ticketfiles
from orch_dashboard.server import make_server

SHA = "0123456789ab"


@pytest.fixture
def rv(ws):
    d = ws / ".orch" / "tickets" / "t_other000x" / "reviewed" / SHA
    d.mkdir(parents=True)
    (d / "after.html").write_text("<h1>after</h1><script>alert(1)</script>")
    (d / "shot.png").write_bytes(b"\x89PNG")
    (d / "notes.md").write_text("# plan")
    (d / "run.exe").write_bytes(b"MZ")
    (d / "link.txt").symlink_to(ws / "secret.txt")
    (ws / "secret.txt").write_text("outside")
    (ws / ".orch" / "tickets" / "t_other000x" / "artifacts").mkdir()
    (ws / ".orch" / "tickets" / "t_other000x" / "artifacts" / "a.txt").write_text("artifact")
    return ws


def get(srv, t, n, k="reviewed"):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", f"/api/file?t={t}&k={k}&n={quote(n, safe='')}", headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())


def test_reviewed_files_are_served_sandboxed_and_inert(rv):
    srv = make_server(rv, 0, orch_bin="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, _body, h = get(srv, "t_other000x", f"{SHA}/after.html")
        assert code == 200 and h["Content-Type"].startswith("text/html")
        assert "sandbox" in h["Content-Security-Policy"] and "script-src" not in h["Content-Security-Policy"]
        assert (
            "default-src 'none'" in h["Content-Security-Policy"] and h["X-Content-Type-Options"] == "nosniff"
        )
        assert get(srv, "t_other000x", f"{SHA}/shot.png")[2]["Content-Type"] == "image/png"
        assert get(srv, "t_other000x", f"{SHA}/notes.md")[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize(
    "name",
    [
        f"{SHA}/run.exe",  # a type a card may not show
        f"{SHA}/link.txt",  # a link
        f"{SHA}/../../artifacts/a.txt",
        f"{SHA}/..%2F..",
        f"{SHA}/sub/after.html",
        f"{SHA}/.hidden.png",
        f"{SHA}\\after.html",
        "after.html",
        "ABCDEF012345/after.html",
        f"{SHA}/missing.png",
        "../after.html",
        f"{SHA}/after.html\x00.png",
        "/etc/passwd",
        "",
    ],
)
def test_reviewed_names_are_validated(rv, name):
    assert ticketfiles.read_reviewed(rv, "t_other000x", name)[0] == 404
    assert ticketfiles.read_file(rv, "t_other000x", "reviewed", name)[0] == 404


def test_reviewed_refuses_other_tickets_ids_and_download(rv):
    assert ticketfiles.read_reviewed(rv, "../x", f"{SHA}/shot.png")[0] == 404
    assert ticketfiles.read_reviewed(rv, "t_nobody00", f"{SHA}/shot.png")[0] == 404
    assert ticketfiles.read_file(rv, "t_other000x", "reviewed", f"{SHA}/shot.png", download=True)[0] == 404
    assert ticketfiles.read_reviewed(rv, "t_other000x", f"{SHA}/shot.png")[0] == 200


def test_a_swapped_sha_folder_link_is_refused(rv):
    t = rv / ".orch" / "tickets" / "t_other000x" / "reviewed"
    (t / "ffffffffffff").symlink_to(rv / ".orch" / "tickets" / "t_other000x" / "artifacts")
    assert ticketfiles.read_reviewed(rv, "t_other000x", "ffffffffffff/a.txt")[0] == 404


def test_the_page_and_the_kit_module_are_served(ws):
    srv = make_server(ws, 0, orch_bin="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        for path in ("/pages/review.js", "/kit/review.js"):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
            r = c.getresponse()
            assert r.status == 200 and "javascript" in r.getheader("Content-Type"), path
            assert b"reviewPage" in r.read()
    finally:
        srv.shutdown()
        srv.server_close()
