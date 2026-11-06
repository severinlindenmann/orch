import http.client
import json

import pytest

from orch_focus import actions

from .conftest import TID, calls


def req(srv, method, path, body=None, headers=None):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body)
        h.setdefault("Content-Type", "application/json")
        h.setdefault("Origin", f"http://127.0.0.1:{port}")
    c.request(method, path, data, h)
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())


def test_page_and_assets(server):
    st, body, hdr = req(server, "GET", f"/t/{TID}")
    assert st == 200 and b"fx" in body and "frame-ancestors" in hdr["Content-Security-Policy"]
    for p in ("/web/focus.js", "/web/focus.css", "/kit/tokens.css", "/kit/question-card.js"):
        assert req(server, "GET", p)[0] == 200, p
    assert req(server, "GET", "/kit/../origin.py")[0] == 404
    assert req(server, "GET", "/web/../server.py")[0] == 404


def test_board_api_generic(server):
    st, body, _ = req(server, "GET", f"/api/t/{TID}")
    v = json.loads(body)
    assert st == 200 and v["state"] == "stopped" and v["generic"] is True
    assert v["done"] == 1 and v["total"] == 2
    assert req(server, "GET", "/api/t/t_nothere99")[0] == 404
    assert req(server, "GET", "/api/t/..%2f..")[0] == 404


def test_state_needs_when_question_open(server, ws):
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["questions"] = [{"id": "q1", "text": "CHF or EUR?", "options": ["CHF", "EUR"], "answer": None}]
    p.write_text(json.dumps(t))
    assert json.loads(req(server, "GET", f"/api/t/{TID}")[1])["state"] == "needs"


def test_running_claude_run_writes_events_and_board(server, ws, fake_orch):
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": "r_abc123", "agent": "claude", "mode": "live", "started_at": "2026-11-06T08:00:00Z"}}))  # fmt: skip
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["state"] == "working" and v["generic"] is False and v["live"] is True
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["checklist"][1].update(done=True, evidence=[{"type": "note", "ref": "ok", "text": "ok"}])
    p.write_text(json.dumps(t))
    server.RequestHandlerClass.keywords["tracker"].status_cache.clear()
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert [t["state"] for t in v["board"]["tasks"]] == ["done"]
    assert (ws / ".orch/addons/focus/runs/r_abc123.events.jsonl").exists()


@pytest.mark.parametrize(
    "headers,code",
    [({"Host": "evil.example:80"}, 403), ({"Origin": "http://evil.example"}, 403), ({"Origin": "null"}, 403),
     ({"Sec-Fetch-Site": "cross-site"}, 403)],
)  # fmt: skip
def test_post_fence(server, fake_orch, headers, code):
    st, _, _ = req(server, "POST", "/api/act", {"op": "run.stop", "args": {"ticket": TID}}, headers)
    assert st == code and calls(fake_orch) == []


def test_post_without_origin_refused_and_get_api_cross_site_refused(server, fake_orch):
    port = server.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", "/api/act", json.dumps({"op": "run.stop", "args": {"ticket": TID}}),
              {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})  # fmt: skip
    assert c.getresponse().status == 403
    assert req(server, "GET", f"/api/t/{TID}", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(server, "GET", f"/api/t/{TID}", headers={"Host": "evil.example:1"})[0] == 403
    assert calls(fake_orch) == [] or all(c[:2] == ["run", "status"] for c in calls(fake_orch))


def test_ops_build_exact_argv(server, fake_orch):
    def go(op, args):
        return req(server, "POST", "/api/act", {"op": op, "args": args})

    assert go("run.start", {"ticket": TID})[0] == 200
    assert go("run.start", {"ticket": TID, "fresh": True})[0] == 200
    assert go("run.stop", {"ticket": TID})[0] == 200
    assert go("run.send", {"ticket": TID, "text": "--delete everything"})[0] == 200
    assert go("check.move", {"ticket": TID, "check": "c2", "after": "c1"})[0] == 200
    assert (
        go(
            "check.edit",
            {"ticket": TID, "check": "c2", "text": "New name", "if_revision": 3, "was": "Review totals"},
        )[0]
        == 200
    )
    assert go("answer", {"ticket": TID, "question": "q1", "answer": "CHF"})[0] == 200
    got = [c for c in calls(fake_orch) if c[0] != "run" or c[1] != "status"]
    assert got[0][:4] == ["run", "start", TID, "--by"] and got[0][4] == "focus"
    assert "--fresh" in got[1]
    assert got[2][:3] == ["run", "stop", TID]
    assert got[3][-2:] == ["--", "--delete everything"]  # free text can never be an option
    assert got[4][:4] == ["check", "move", TID, "c2"] and "--after=c1" in got[4]
    assert got[5][-2:] == ["--", "New name"] and "--if-revision=3" in got[5]
    assert got[6][0] == "answer" and "--via" in got[6]


@pytest.mark.parametrize(
    "op,args",
    [("shell", {}), ("run.start", {"ticket": "../x"}), ("run.start", {"ticket": TID, "agent": "x"}),
     ("run.send", {"ticket": TID, "text": ""}), ("run.send", {"ticket": TID, "text": "x" * 2001}),
     ("check.remove", {"ticket": TID, "check": "c1; ls"}), ("check.edit", {"ticket": TID, "check": "c1", "text": "a\x00b"}),
     ("run.start", {"ticket": TID, "allow": ["Bash"]})],
)  # fmt: skip
def test_bad_ops_are_400_and_run_nothing(server, fake_orch, op, args):
    st, _, _ = req(server, "POST", "/api/act", {"op": op, "args": args})
    assert st == 400
    assert not [c for c in calls(fake_orch) if c[:2] != ["run", "status"]]


def test_build_argv_unknown_and_types():
    with pytest.raises(actions.BadRequest):
        actions.build_argv(["x"], {})
    with pytest.raises(actions.BadRequest):
        actions.build_argv("run.stop", [])


def test_refusal_text_and_conflict(server, ws, tmp_path):
    from orch_focus.server import make_server  # noqa: F401

    bad = tmp_path / "failorch"
    bad.write_text('#!/bin/sh\necho \'{"error":"Not done: c2"}\'\nexit 2\n')
    bad.chmod(0o755)
    code, text, _ = actions.run_op(ws, str(bad), "run.stop", {"ticket": TID})
    assert code == 422 and text == "Not done: c2"
    conf = tmp_path / "conforch"
    conf.write_text('#!/bin/sh\necho \'{"revision":4,"changed_by":"human:x","current":"y"}\'\nexit 2\n')
    conf.chmod(0o755)
    code, _, extra = actions.run_op(
        ws, str(conf), "check.edit", {"ticket": TID, "check": "c1", "text": "x", "if_revision": 3}
    )
    assert code == 409 and extra["revision"] == 4


def test_no_orch_binary_is_503(server, ws):
    with pytest.raises(actions.Unavailable):
        actions.run_op(ws, None, "run.stop", {"ticket": TID})


def test_stop_started_stops_runs_focus_started(server, fake_orch):
    from orch_focus.server import stop_started

    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})
    stop_started(server)
    assert any(c[:3] == ["run", "stop", TID] for c in calls(fake_orch))


@pytest.mark.parametrize("bad", ["../../x", "r_../../x", "r_ab", "R_ABCDEF", "r_abcdef/../../y", "x" * 5, 7])
def test_bad_run_id_writes_nothing_outside_runs(server, ws, fake_orch, bad):
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": bad, "agent": "claude", "mode": "live"}}))  # fmt: skip
    before = {p for p in ws.parent.rglob("*")}
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["run"]["run"] is None
    new = {p for p in ws.parent.rglob("*")} - before
    assert not [p for p in new if "events.jsonl" in p.name]
    assert not (ws.parent / "x").exists() and not (ws / "x").exists()


@pytest.mark.parametrize("bad", ["../../x", "r_../x", "", "r_a/b" + "c" * 8])
def test_event_log_refuses_a_bad_run_id(tmp_path, bad):
    from orch_focus.events import EventLog

    with pytest.raises(ValueError):
        EventLog(tmp_path, bad)
