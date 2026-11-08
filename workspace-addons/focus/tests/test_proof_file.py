"""GET /api/file: proof files of a ticket, read only through orch.safefile."""

import os
import sys

import orch.safefile  # noqa: F401  (added by PR #160; fails until it is merged)
import pytest

from .conftest import TID
from .test_server import req


@pytest.fixture
def ev(ws):
    d = ws / ".orch" / "tickets" / TID / "evidence"
    d.mkdir(parents=True)
    return d


def get(srv, name, mode="view", t=TID):
    from urllib.parse import quote

    return req(srv, "GET", f"/api/file?t={t}&n={quote(name, safe='')}&m={mode}")


def test_kinds_are_labelled_and_locked_down(server, ev):
    (ev / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ev / "a.csv").write_text("a,b\n1,2\n")
    (ev / "r.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    (ev / "p.html").write_text("<script>alert(1)</script><b>hi</b>")
    st, body, h = get(server, "shot.png")
    assert st == 200 and h["Content-Type"] == "image/png" and h["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in h["Content-Security-Policy"]
    st, body, h = get(server, "a.csv")
    assert st == 200 and h["Content-Type"].startswith("text/plain") and body == b"a,b\n1,2\n"
    st, body, h = get(server, "r.pdf")
    assert (
        st == 200
        and h["Content-Type"] == "application/pdf"
        and "frame-ancestors 'self'" in h["Content-Security-Policy"]
    )
    # an HTML file is text in the plain view, a sandboxed page only when asked
    st, _, h = get(server, "p.html")
    assert st == 200 and h["Content-Type"].startswith("text/plain")
    st, _, h = get(server, "p.html", "page")
    assert st == 200 and h["Content-Type"].startswith("text/html")
    assert (
        " sandbox" in " " + h["Content-Security-Policy"] and "script-src" not in h["Content-Security-Policy"]
    )
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert len([k for k in h if k.lower() == "content-security-policy"]) == 1


def test_not_a_pdf_and_not_a_page_and_unknown_kind(server, ev):
    (ev / "fake.pdf").write_text("<html>")
    (ev / "x.txt").write_text("x")
    (ev / "blob.bin").write_bytes(b"\0\1")
    assert get(server, "fake.pdf")[0] == 415
    assert get(server, "x.txt", "page")[0] == 404
    assert get(server, "blob.bin")[0] == 404  # no preview for an unknown kind ...
    st, body, h = get(server, "blob.bin", "dl")  # ... but a download
    assert (
        st == 200
        and "attachment" in h["Content-Disposition"]
        and h["Content-Type"] == "application/octet-stream"
    )
    st, body, _ = get(server, "blob.bin", "info")
    assert st == 200 and b'"size": 2' in body


def test_size_cap(server, ev):
    (ev / "big.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (ev / "ok.txt").write_bytes(b"x" * (2 * 1024 * 1024))
    assert get(server, "big.txt")[0] == 413
    assert get(server, "ok.txt")[0] == 200
    assert get(server, "big.txt", "dl")[0] == 200  # a download has the larger cap


@pytest.mark.parametrize(
    "name",
    ["../x.txt", "..", "a/../../x.txt", "/etc/passwd", "a\\b.txt", "c:x.txt", "", "x\x00.txt", "a//b.txt"],
)
def test_traversal_and_odd_names_refused(server, ev, name):
    (ev.parent / "x.txt").write_text("secret")
    assert get(server, name)[0] == 404
    assert get(server, name, "dl")[0] == 404


def test_other_folders_and_tickets_refused(server, ws, ev):
    (ws / ".orch" / "secrets").mkdir()
    (ws / ".orch" / "secrets" / "k.txt").write_text("secret")
    (ev.parent / "artifacts").mkdir()
    (ev.parent / "artifacts" / "a.txt").write_text("art")
    assert get(server, "../artifacts/a.txt")[0] == 404  # proof means the evidence folder only
    assert get(server, "../../../secrets/k.txt")[0] == 404
    assert get(server, "x.txt", t="t_../..")[0] == 404
    assert get(server, "x.txt", t="../..")[0] == 404


def test_bad_mode_is_refused(server, ev):
    (ev / "x.txt").write_text("x")
    assert get(server, "x.txt", "edit")[0] == 404


@pytest.mark.skipif(sys.platform == "win32", reason="refs")
def test_symlink_hardlink_fifo_refused(server, ws, ev):
    secret = ws / ".orch" / "secrets"
    secret.mkdir()
    (secret / "k.txt").write_text("secret")
    os.symlink(secret / "k.txt", ev / "link.txt")
    os.link(secret / "k.txt", ev / "hard.txt")
    os.mkfifo(ev / "pipe.txt")
    for n in ("link.txt", "hard.txt", "pipe.txt"):
        for mode in ("view", "dl", "info"):
            assert get(server, n, mode)[0] == 404, (n, mode)
    # a folder swapped for a link is refused too
    real = ws / "elsewhere"
    real.mkdir()
    (real / "y.txt").write_text("y")
    os.symlink(real, ev / "dir")
    assert get(server, "dir/y.txt")[0] == 404


def test_other_hosts_refused(server, ev):
    (ev / "x.txt").write_text("x")
    st, _, _ = req(server, "GET", f"/api/file?t={TID}&n=x.txt", headers={"Host": "evil.test"})
    assert st == 403


def test_page_and_script_are_served(server):
    assert req(server, "GET", "/web/proof.js")[0] == 200
