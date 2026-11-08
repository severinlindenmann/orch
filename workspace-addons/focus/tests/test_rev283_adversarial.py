"""Opus review #283: adversarial checks on GET /page/<ticket>/<key>/<file> (F1 inverted: the hole is closed)."""

import pytest

from orch_focus.proofs import page_key

from .conftest import TID
from .test_proof_file import ev  # noqa: F401
from .test_server import req

EVIL = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors"}
K = lambda: page_key(TID)


def test_F1_foreign_site_cannot_include_evidence_js_and_css(server, ev):  # noqa: F811
    """A page on any website knows (or guesses) ticket id and file name but not the key: 404, nothing served."""
    (ev / "data.js").write_text("window.RESULTS={customer:'ACME', total:42}")
    (ev / "style.css").write_text("b{color:red}")
    for n in ("data.js", "style.css"):
        for path in (f"/page/{TID}/{n}", f"/page/{TID}/{'0' * 16}/{n}"):
            st, body, _ = req(server, "GET", path, headers=EVIL)
            assert st == 404 and b"ACME" not in body, path
        st, _, _ = req(server, "GET", f"/api/file?t={TID}&n={n}&m=dl", headers=EVIL)
        assert st == 403


@pytest.mark.parametrize("name", ["..%20/x.css", "...%2fx.css", "a/.%20/x.css"])
def test_trailing_space_dot_parts_stay_inside_on_posix(server, ev, name):  # noqa: F811
    (ev.parent / "x.css").write_text("secret")
    st, body, _ = req(server, "GET", f"/page/{TID}/{K()}/{name}")
    assert st == 404 and b"secret" not in body


def test_html_page_top_level_still_sandboxed(server, ev):  # noqa: F811
    (ev / "p.html").write_text("<script>fetch('/api/tickets')</script>")
    st, _, h = req(
        server,
        "GET",
        f"/page/{TID}/{K()}/p.html",
        headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "document"},
    )
    csp = h["Content-Security-Policy"]
    assert st == 200 and "sandbox allow-scripts" in csp and "allow-same-origin" not in csp
    assert "connect-src 'none'" in csp and "allow-top-navigation" not in csp and "allow-popups" not in csp
    assert "allow-forms" not in csp and "frame-src 'none'" in csp


def test_svg_and_png_kinds_are_fixed_by_extension(server, ev):  # noqa: F811
    (ev / "evil.png").write_text("<html><script>alert(1)</script>")
    (ev / "x.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    _, _, h = req(server, "GET", f"/page/{TID}/{K()}/evil.png")
    assert h["Content-Type"] == "image/png" and h["X-Content-Type-Options"] == "nosniff"
    _, _, h = req(server, "GET", f"/page/{TID}/{K()}/x.svg")
    assert h["Content-Type"] == "image/svg+xml" and "sandbox allow-scripts" in h["Content-Security-Policy"]
