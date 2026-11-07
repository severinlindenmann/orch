import json
import re

from orch_dashboard import cli
from orch_dashboard.snapshot import publish_snapshot, render_snapshot, write_snapshot


def test_snapshot_single_file(ws):
    html = render_snapshot(ws)
    assert "window.ORCH_SNAPSHOT=" in html and "<style>" in html
    assert 'href="style.css"' not in html and 'src="app.js"' not in html and 'href="tokens.css"' not in html
    data = json.loads(re.search(r"window\.ORCH_SNAPSHOT=(.*?);</script>", html, re.DOTALL).group(1))
    assert any(t["id"] == "t_7k3f9q" for t in data["tickets"])
    assert "orn_SECRET" not in html and "weekly report query" not in html  # inbox text stays local


def test_snapshot_escapes_script_close(ws):
    p = ws / ".orch" / "tickets" / "t_other000x.json"
    t = json.loads(p.read_text())
    t["title"] = "</script><script>alert(1)</script>"
    p.write_text(json.dumps(t))
    html = render_snapshot(ws)
    assert "</script><script>alert(1)" not in html


def test_write_and_cli(ws, tmp_path, capsys):
    out = tmp_path / "s.html"
    assert write_snapshot(ws, out) == out and out.stat().st_size > 1000
    assert cli.main(["--dir", str(ws), "snapshot", "--out", str(tmp_path / "c.html")]) == 0
    assert (tmp_path / "c.html").is_file()


def test_cli_without_workspace(tmp_path):
    assert cli.main(["--dir", str(tmp_path)]) == 2


def test_publish_calls_orch_publish_app(ws):
    calls = []

    class R:
        returncode = 0

    publish_snapshot(ws, run=lambda cmd: calls.append(cmd) or R())
    assert calls[0][:3] == ["orch", "publish", "app"]


def test_publish_folder_is_a_deployable_static_app(ws):
    import tomllib

    seen = {}

    class R:
        returncode = 0

    def fake(cmd):
        from pathlib import Path

        folder = Path(cmd[3])
        seen["cmd"] = cmd
        seen["toml"] = tomllib.loads((folder / "app.toml").read_text())
        seen["index"] = (folder / "index.html").is_file()
        return R()

    assert publish_snapshot(ws, run=fake) == 0
    assert seen["cmd"][-1] == "--private" and seen["index"]
    m = seen["toml"]
    assert m["stack"] == "static" and m["public"] is False and re.fullmatch(r"[a-z0-9-]{2,40}", m["name"])
    assert "start" not in m and "health" not in m


def test_snapshot_logo_is_inline(ws):
    html = render_snapshot(ws)
    assert 'href="favicon.svg"' not in html and "apple-touch-icon" not in html
    assert 'src="logo.svg"' not in html and "data:image/svg+xml;base64," in html


def _has_ext_and_addons(ws, fake_orch, with_addons):
    html = render_snapshot(ws, with_addons=with_addons, orch_bin=str(fake_orch))
    return json.loads(re.search(r"window\.ORCH_SNAPSHOT=(.*?);</script>", html, re.DOTALL).group(1)), html


def test_snapshot_leaves_add_ons_out_by_default(ws, fake_orch):
    data, html = _has_ext_and_addons(ws, fake_orch, False)
    assert data["addons"] == [] and "views" not in data
    assert all("ext" not in t for t in data["tickets"]) and "Schedule" not in html.split("<script>")[1]


def test_snapshot_with_addons_includes_tab_rows_and_one_view(ws, fake_orch):
    data, _ = _has_ext_and_addons(ws, fake_orch, True)
    assert [a["name"] for a in data["addons"]] == ["scheduler"]
    assert data["views"]["scheduler"]["state"] == "ok"
    assert any("ext" in t for t in data["tickets"])
    assert cli.main(["--dir", str(ws), "snapshot", "--with-addons", "--out", str(ws / "s.html")]) == 0


def test_snapshot_preserves_project_and_local_reference_text(ws):
    ticket = ws / ".orch/tickets/t_weekly01.json"
    t = json.loads(ticket.read_text())
    t["refs"] = [{"kind": "file", "path": "docs/notes.md"}]
    ticket.write_text(json.dumps(t))
    local = ws / ".orch/local/refs"
    local.mkdir(parents=True)
    (local / "t_weekly01.json").write_text(
        json.dumps([{"kind": "file", "path": "/outside/private.txt", "local": True}])
    )
    html = render_snapshot(ws)
    data = json.loads(re.search(r"window\.ORCH_SNAPSHOT=(.*?);</script>", html, re.DOTALL).group(1))
    refs = next(t for t in data["tickets"] if t["id"] == "t_weekly01")["refs"]
    assert [r["path"] for r in refs] == ["docs/notes.md"]  # a shared snapshot carries no local path
    assert "/outside/private.txt" not in html
    from orch_dashboard.data import load_state

    live = next(t for t in load_state(ws, with_settings=True)["tickets"] if t["id"] == "t_weekly01")["refs"]
    assert [r["path"] for r in live] == ["docs/notes.md", "/outside/private.txt"]
