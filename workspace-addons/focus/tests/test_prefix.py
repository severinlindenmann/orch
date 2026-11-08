"""The prefix the dashboard sends is put into the page's links, and only a /addon/<name> prefix is accepted."""

import threading
import urllib.request

from orch_focus.server import make_server


def _get(base, headers):
    req = urllib.request.Request(base + "/", headers=headers)
    with urllib.request.urlopen(req) as r:
        return r.read().decode()


def test_prefix_is_applied_and_validated(tmp_path):
    (tmp_path / ".orch").mkdir()
    srv = make_server(tmp_path, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert 'src="/addon/viewer/web/focus.js"' in _get(base, {"X-Forwarded-Prefix": "/addon/viewer"})
        for bad in ("//evil.example", "/addon/x/../y", '"><script>', "/other"):
            page = _get(base, {"X-Forwarded-Prefix": bad})
            assert (
                'src="/web/focus.js"' in page
                and "evil" not in page
                and "<script>" not in page.replace("<script src", "")
            )
        assert 'data-prefix=""' in _get(base, {})
    finally:
        srv.shutdown()
        srv.server_close()
