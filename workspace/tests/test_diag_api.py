"""Problem reports in the dashboard: the page's action trail (POST /api/diag), Report a problem
(POST /api/diag/report), the Settings card ops and the traceparent echo (D3)."""

import base64
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from orch import addons, config, diag, pagelaunch, pagesession, runs, tickets

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-addons" / "dashboard" / "src"))
pytest.importorskip("orch_dashboard.server")
from orch_dashboard import actions, data, diagapi  # noqa: E402
from orch_dashboard.server import make_server  # noqa: E402


@pytest.fixture
def live(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test").mkdir(parents=True)  # a test workspace pairs only with a test home
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT", "ORCH_BIN"):
            monkeypatch.delenv(k, raising=False)
    (acct / ".orch-test" / "home").mkdir()
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)

    def no_child(argv, *a, **k):  # a child `orch` would see the real account home
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(actions, "_run", no_child)
    monkeypatch.setattr(data, "_run", no_child)
    srv = make_server(root, 0, orch_bin=pagesession.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


SECRETS = {}


def post(port, path, body, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    if h.get("Cookie") in SECRETS:
        h["X-Orch-Page"] = SECRETS[h["Cookie"]]
    c.request("POST", path, json.dumps(body), h)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read()


def session(root, port):
    tok = pagelaunch.write_launch_token(root, "dashboard")
    st, ck, body = post(port, "/session", {"token": tok})
    assert st == 200
    cookie = ck.split(";")[0]
    SECRETS[cookie] = json.loads(body)["secret"]
    return cookie


@pytest.fixture(autouse=True)
def fresh_diag(monkeypatch):
    monkeypatch.setattr(diag, "_state", {"root": None, "src": "cli", "seq": 0, "last_prune": None})
    for d in (diag._dropped, diag._rate, diag._enabled_cache, diag._hider_cache, diag._ws_cache):
        d.clear()


def events(root, src=None):
    return [e for e in diag.read_events(root) if src is None or e["src"] == src]


def stuck(root: Path) -> str:
    t = tickets.create(root, "Write the invoice export", "human:t")
    tickets.set_status(root, t["id"], "active", "human:t")
    raw = tickets.load(root, t["id"])
    raw["updated_at"] = runs._iso(time.time() - 1800)
    tickets._write(root, raw)
    return t["id"]


def trail(port, body, headers=None):
    return post(port, "/api/diag", body, headers)


def test_trail_writes_only_known_ui_events_with_typed_values(live):
    root, port = live
    code, _, out = trail(
        port,
        {
            "events": [
                {
                    "ev": "ui.fetch",
                    "kv": {
                        "route": "/api/state?x=1",
                        "method": "GET",
                        "status": 200,
                        "ms": 12,
                        "outcome": "ok",
                        "body": "SECRET",
                    },
                },
                {"ev": "ui.route", "kv": {"from": "#home", "to": "#ticket/t_abcdef12"}},
                {
                    "ev": "ui.action",
                    "kv": {"id": "answer", "route": "#ticket/t_abcdef12"},
                    "ticket": "t_abcdef12",
                    "ago": 40,
                },
                {
                    "ev": "ui.error",
                    "kv": {
                        "kind": "error",
                        "what": "TypeError",
                        "file": "http://x/pages/ticket.js?v=3",
                        "line": 9,
                        "col": 2,
                    },
                },
                {"ev": "cli.command", "kv": {"command": "x"}},  # not a ui event: dropped
                {"ev": "ui.fetch", "kv": {"status": "200"}},  # wrong type: the key is dropped
                "junk",
            ]
        },
    )
    assert code == 200 and json.loads(out) == {"enabled": True, "written": 5}
    got = events(root, "ui")
    assert [e["ev"] for e in got] == ["ui.fetch", "ui.route", "ui.action", "ui.error", "ui.fetch"]
    assert got[0]["kv"] == {"route": "/api/state", "method": "GET", "status": 200, "ms": 12, "outcome": "ok"}
    assert "SECRET" not in json.dumps(got)
    assert got[1]["kv"]["to"] == "#ticket/:id"
    assert (
        got[2]["kv"] == {"id": "answer", "route": "#ticket/:id", "ago_ms": 40}
        and got[2]["ticket"] == "t_abcdef12"
    )
    assert got[3]["lvl"] == "error" and got[3]["kv"]["file"] == "ticket.js"
    assert got[4]["kv"] == {}


def test_trail_writes_nothing_when_the_log_is_off(live):
    root, port = live
    config.set_diag_enabled(root, False)
    diag.forget_settings()
    before = events(root)
    code, _, out = trail(port, {"events": [{"ev": "ui.route", "kv": {"from": "#a", "to": "#b"}}]})
    assert code == 200 and json.loads(out) == {"enabled": False}
    assert events(root) == before


def test_trail_is_fenced_and_bounded(live):
    root, port = live
    assert trail(port, {"events": []}, {"Origin": "http://evil.example"})[0] == 403
    assert post(port, "/api/diag", {"events": []}, {"Content-Type": "text/plain"})[0] == 415
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(
        "POST",
        "/api/diag",
        "x" * 40000,
        {
            "Host": f"127.0.0.1:{port}",
            "Origin": f"http://127.0.0.1:{port}",
            "Content-Type": "application/json",
        },
    )
    assert c.getresponse().status == 400
    assert events(root, "ui") == []


def test_response_repeats_the_traceparent_of_the_request(live):
    root, port = live
    tp = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{port}", "traceparent": tp})
    r = c.getresponse()
    r.read()
    echoed = r.getheader("traceparent")
    assert echoed and echoed.split("-")[1] == "ab" * 16 and echoed != tp  # same trace id, our own span
    ev = [e for e in events(root) if e["ev"] == "dashboard.request"][-1]
    assert ev["trace"]["trace_id"] == "ab" * 16 and ev["trace"]["parent_span_id"] == "cd" * 8


def test_report_needs_the_persons_session(live):
    root, port = live
    assert post(port, "/api/diag/report", {"note": "x"})[0] == 403


def test_report_of_a_stuck_ticket_has_a_problem_check_and_the_page(live):
    root, port = live
    tid = stuck(root)
    ck = session(root, port)
    page = "<html><body><h1>Ticket</h1><input value='[masked]'></body></html>"
    code, _, out = post(
        port,
        "/api/diag/report",
        {"ticket": tid, "note": "stuck", "expected": "done", "content": True, "page": page},
        {"Cookie": ck},
    )
    assert code == 200, out
    r = json.loads(out)
    assert r["ref"].startswith("r-") and any(c["verdict"] == "problem" for c in r["checks"])
    folder = Path(r["path"])
    assert (folder / "screen" / "page.html").read_text() == page
    assert "screen/page.html" in json.loads((folder / "manifest.json").read_text())["files"]
    made = [e for e in events(root) if e["ev"] == "diag.report_made"][-1]
    assert made["kv"]["scope"] == "ticket" and made["kv"]["page"] is True


def test_report_without_content_keeps_the_page_out(live):
    root, port = live
    tid = stuck(root)
    ck = session(root, port)
    code, _, out = post(
        port,
        "/api/diag/report",
        {"ticket": tid, "content": False, "page": "<p>secret ticket text</p>"},
        {"Cookie": ck},
    )
    assert code == 200
    assert not (Path(json.loads(out)["path"]) / "screen").exists()


def test_report_refuses_bad_input(live):
    root, port = live
    ck = session(root, port)
    for bad in ({"ticket": "../etc"}, {"addon": "Bad Name"}, {"note": 5}, {"zzz": 1}, {"page": 3}):
        assert post(port, "/api/diag/report", bad, {"Cookie": ck})[0] == 400, bad


def test_open_folder_only_for_a_report_of_this_workspace(live, monkeypatch):
    root, port = live
    tid = stuck(root)
    ck = session(root, port)
    ref = json.loads(post(port, "/api/diag/report", {"ticket": tid}, {"Cookie": ck})[2])["ref"]
    calls = []
    monkeypatch.setattr(diagapi.subprocess, "Popen", lambda argv, **k: calls.append(argv))
    code, _, out = post(port, "/api/diag/open", {"ref": ref}, {"Cookie": ck})
    assert code == 200 and json.loads(out)["opened"] is True and calls[0][-1].endswith(ref)
    assert post(port, "/api/diag/open", {"ref": "../../x"}, {"Cookie": ck})[0] == 400
    assert post(port, "/api/diag/open", {"ref": "r-0101-0101-nope"}, {"Cookie": ck})[0] == 404
    assert len(calls) == 1


def test_settings_ops_build_one_core_command_each():
    assert actions.build_argv("diag.set", {"on": True})[:4] == ["config", "set", "diag.enabled", "on"]
    assert actions.build_argv("diag.set", {"on": False})[3] == "off"
    assert actions.build_argv("diag.delete_reports", {})[:3] == ["diag", "delete", "reports"]
    for bad in ({}, {"on": "yes"}, {"on": True, "x": 1}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("diag.set", bad)
    with pytest.raises(actions.BadRequest):
        actions.build_argv("diag.delete_reports", {"x": 1})


def test_diag_ops_need_the_page_session():
    assert all(actions.needs_session(o) for o in ("diag.set", "diag.delete_reports"))


def test_settings_numbers_and_deletes(live):
    root, port = live
    tid = stuck(root)
    ck = session(root, port)
    post(port, "/api/diag/report", {"ticket": tid}, {"Cookie": ck})
    s = diag.stats(root)
    assert (
        s["reports"]["count"] == 1
        and s["reports"]["last"]
        and s["notes"]["bytes"] > 0
        and s["notes"]["since"]
    )
    from orch import diag_report

    assert diag_report.delete_all(root) == 1 and diag.stats(root)["reports"]["count"] == 0
    assert diag.delete_notes(root) >= 1
    after = diag.stats(root)["notes"]  # only the line that says the notes were deleted is left
    assert after["files"] == 1 and any(e["ev"] == "diag.notes_deleted" for e in events(root))


def test_delete_command_deletes_reports_and_notes(proj, run):
    from orch import diag_report

    run("init")
    tid = stuck(proj)
    diag_report.make(proj, ticket=tid)
    assert diag.stats(proj)["reports"]["count"] == 1
    code, out, _ = run("diag", "delete", "reports", "--json")
    assert code == 0 and json.loads(out) == {"deleted": 1, "what": "reports"}
    assert diag.stats(proj)["reports"]["count"] == 0
    assert run("diag", "delete", "notes")[0] == 0
    assert any(e["ev"] == "diag.notes_deleted" for e in diag.read_events(proj))


def test_report_takes_more_details_and_added_files(live):
    root, port = live
    ck = session(root, port)
    shot = base64.b64encode(b"\x89PNG\x00").decode()
    body = {"note": "x", "more": "it worked yesterday", "files": [{"name": "../shot.png", "data": shot}]}
    code, _, out = post(port, "/api/diag/report", body, {"Cookie": ck})
    assert code == 200, out
    folder = Path(json.loads(out)["path"])
    assert (folder / "attachments" / "shot.png").read_bytes() == b"\x89PNG\x00"
    assert json.loads((folder / "manifest.json").read_text())["more"] == "it worked yesterday"
    for bad in (
        {"files": [{"name": "a", "data": "not base64!"}]},
        {"files": [{"name": "a"}]},
        {"files": [{"name": f"f{i}", "data": ""} for i in range(11)]},
        {"more": 5},
        {"share": "yes"},
    ):
        assert post(port, "/api/diag/report", bad, {"Cookie": ck})[0] == 400, bad


def test_share_without_a_relay_keeps_the_report_and_says_why(live):
    root, port = live
    assert post(port, "/api/diag/share", {"ref": "r-1116-1200-ws"})[0] == 403  # the person's session only
    ck = session(root, port)
    code, _, out = post(port, "/api/diag/report", {"note": "x", "share": True}, {"Cookie": ck})
    r = json.loads(out)
    assert code == 200 and "shared" not in r and "not connected" in r["share_error"]
    assert Path(r["path"]).is_dir()
    code, _, out = post(port, "/api/diag/share", {"ref": r["ref"]}, {"Cookie": ck})
    assert code == 422 and b"not connected" in out
    assert post(port, "/api/diag/share", {"ref": "../x"}, {"Cookie": ck})[0] == 400
