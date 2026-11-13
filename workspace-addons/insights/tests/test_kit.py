import http.client
import sys

import orch_ui
import pytest


def get(srv, path):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    return r.status, r.read(), r.getheader("Content-Type") or ""


@pytest.fixture
def no_static(monkeypatch, tmp_path):
    monkeypatch.setattr(orch_ui, "__file__", str(tmp_path / "gone" / "__init__.py"))


def test_kit_css_is_served_as_css(start_server):
    srv = start_server()
    for name in ("tokens.css", "components.css"):
        code, body, ctype = get(srv, f"/kit/{name}")
        assert code == 200 and body and ctype.startswith("text/css"), name


def test_kit_missing_everywhere_is_404(start_server, no_static, monkeypatch):
    monkeypatch.setitem(sys.modules, "orch_dashboard", None)
    srv = start_server()
    assert get(srv, "/kit/tokens.css")[:2] == (404, b"not found")
    assert get(srv, "/web/insights.css")[0] == 200  # the server still answers


def test_kit_falls_back_to_the_dashboard_copy(start_server, no_static, monkeypatch, tmp_path):
    kit = tmp_path / "pkgs" / "orch_dashboard" / "web" / "kit"
    kit.mkdir(parents=True)
    (kit.parents[1] / "__init__.py").write_text("")
    (kit / "tokens.css").write_bytes(b":root{}")
    monkeypatch.delitem(sys.modules, "orch_dashboard", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgs"))
    code, body, ctype = get(start_server(), "/kit/tokens.css")
    assert (code, body) == (200, b":root{}") and ctype.startswith("text/css")
