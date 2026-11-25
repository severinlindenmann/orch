"""ORCH-1664: every page load sent the page's own files again (about 2.6 MB, no-store, not compressed: 15 s on a slow
link). Now they are kept by the browser and checked by content hash (ETag + no-cache, 304 when unchanged), and text
goes gzip-compressed when the browser accepts it. The page itself and every /api/ answer are still never kept."""

import gzip
import http.client

import pytest

from orch_dashboard import server as srv_mod
from orch_dashboard.server import STATIC_CACHE, kit_file, web_file

STATIC = [
    ("/kit/widgets.css", lambda: kit_file("widgets.css")[0]),
    ("/kit/xterm.js", lambda: kit_file("xterm.js")[0]),
    ("/pages/ticket.js", lambda: web_file("pages/ticket.js")),
    ("/app.js", lambda: web_file("app.js")),
    ("/record.js", lambda: web_file("record.js")),
    ("/style.css", lambda: web_file("style.css")),
    ("/kit/icons.js", lambda: kit_file("icons.js")[0]),
]


def _get(base, path, headers=None):
    port = int(base.rsplit(":", 1)[1])
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    r = c.getresponse()
    out = r.status, r.read(), {k.lower(): v for k, v in r.getheaders()}, r.getheaders()
    c.close()
    return out


@pytest.mark.parametrize("path,raw", STATIC)
def test_a_static_file_is_gzipped_when_accepted_and_plain_otherwise(server, path, raw):
    code, body, h, _ = _get(server, path, {"Accept-Encoding": "gzip, deflate, br"})
    assert code == 200 and h["content-encoding"] == "gzip" and "Accept-Encoding" in h["vary"]
    assert gzip.decompress(body) == raw() and len(body) < len(raw()) / 2
    assert h["content-length"] == str(len(body))
    for plain in ({}, {"Accept-Encoding": "identity"}, {"Accept-Encoding": "gzip;q=0, deflate"}):
        code, body, h, _ = _get(server, path, plain)
        assert code == 200 and "content-encoding" not in h and body == raw(), plain
        assert "Accept-Encoding" in h["vary"]


@pytest.mark.parametrize("path,raw", STATIC)
def test_a_static_file_is_kept_and_answers_304_while_unchanged(server, path, raw):
    for enc in ({"Accept-Encoding": "gzip"}, {}):
        code, _, h, _ = _get(server, path, enc)
        assert code == 200 and h["cache-control"] == STATIC_CACHE == "private, no-cache"
        tag = h["etag"]
        assert tag.startswith('"') and tag.endswith('"')
        code, body, h2, _ = _get(server, path, {**enc, "If-None-Match": tag})
        assert code == 304 and body == b"" and h2["etag"] == tag
        # a 304 carries the same rules as the file: kept, never sniffed, the same security policy
        assert h2["cache-control"] == STATIC_CACHE and h2["x-content-type-options"] == "nosniff"
        assert h2["content-security-policy"] == h["content-security-policy"]
    # only the tag of the copy this request gets counts (outside review): a gzip tag never answers a plain ask
    _, _, hg, _ = _get(server, path, {"Accept-Encoding": "gzip"})
    _, _, hp, _ = _get(server, path)
    assert hg["etag"] != hp["etag"]
    assert _get(server, path, {"If-None-Match": hg["etag"]})[0] == 200
    assert _get(server, path, {"Accept-Encoding": "gzip", "If-None-Match": "W/" + hg["etag"]})[0] == 304
    assert _get(server, path, {"If-None-Match": '"0000", ' + hp["etag"]})[0] == 304
    code, body, _, _ = _get(server, path, {"If-None-Match": '"not-this-one"'})
    assert code == 200 and body == raw()


def test_a_changed_file_is_sent_again_with_a_new_tag(server, monkeypatch):
    _, _, h, _ = _get(server, "/app.js", {"Accept-Encoding": "gzip"})
    real = srv_mod.web_file
    monkeypatch.setattr(
        srv_mod, "web_file", lambda n: real(n) + b"\n// new version\n" if n == "app.js" else real(n)
    )
    code, body, h2, _ = _get(server, "/app.js", {"Accept-Encoding": "gzip", "If-None-Match": h["etag"]})
    assert code == 200 and h2["etag"] != h["etag"] and gzip.decompress(body).endswith(b"// new version\n")


def test_the_gallery_keeps_its_own_policy_on_a_304(server):
    code, _, h, _ = _get(server, "/kit/gallery.html", {"Accept-Encoding": "gzip"})
    assert code == 200 and h["content-encoding"] == "gzip" and "unsafe-inline" in h["content-security-policy"]
    code, _, h2, _ = _get(
        server, "/kit/gallery.html", {"Accept-Encoding": "gzip", "If-None-Match": h["etag"]}
    )
    assert code == 304 and h2["content-security-policy"] == h["content-security-policy"]


def test_a_tiny_file_is_kept_but_not_compressed(server):
    code, body, h, _ = _get(server, "/logo.svg", {"Accept-Encoding": "gzip"})
    assert code == 200 and "content-encoding" not in h and body == web_file("logo.svg")
    assert (
        h["cache-control"] == STATIC_CACHE
        and _get(server, "/logo.svg", {"If-None-Match": h["etag"]})[0] == 304
    )


def test_a_picture_is_kept_but_not_compressed(server):
    code, body, h, _ = _get(server, "/apple-touch-icon.png", {"Accept-Encoding": "gzip"})
    assert code == 200 and "content-encoding" not in h and body == web_file("apple-touch-icon.png")
    assert h["cache-control"] == STATIC_CACHE and h["etag"]
    assert _get(server, "/apple-touch-icon.png", {"If-None-Match": h["etag"]})[0] == 304


def test_the_page_itself_and_api_answers_are_never_kept(server):
    for path in ("/", "/index.html", "/record.html"):
        code, _, h, _ = _get(server, path, {"Accept-Encoding": "gzip"})
        assert code == 200 and h["cache-control"] == "no-store" and "etag" not in h, path
        assert _get(server, path, {"If-None-Match": "*"})[0] == 200
    code, _, h, _ = _get(server, "/api/state", {"Accept-Encoding": "gzip"})
    assert code == 200 and h["cache-control"] == "no-store" and "etag" not in h


def test_the_compressed_copy_is_made_once_per_content(server, monkeypatch):
    calls = []
    real = gzip.compress
    monkeypatch.setattr(gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    srv_mod._GZIPPED.clear()
    for _ in range(3):
        assert _get(server, "/kit/widgets.css", {"Accept-Encoding": "gzip"})[0] == 200
    assert len(calls) == 1


@pytest.mark.parametrize(
    "header,ok",
    [
        ("gzip", True),
        ("gzip, deflate, br, zstd", True),
        ("br;q=1.0, gzip;q=0.8", True),
        ("*", True),
        ("gzip;q=0", False),
        ("gzip; q=0.000", False),
        ("identity", False),
        ("*;q=1, gzip;q=0", False),  # an explicit gzip wins over * (outside review)
        ("gzip;q=0.5, *;q=0", True),
        ("", False),
        (None, False),
    ],
)
def test_accept_encoding(header, ok):
    assert srv_mod._accepts_gzip(header) is ok
