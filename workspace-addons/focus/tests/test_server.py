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
        {"running": True, "claim": {"run": "r_abc12345", "agent": "claude", "mode": "live", "started_at": "2026-11-06T08:00:00Z"}}))  # fmt: skip
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["state"] == "working" and v["generic"] is False and v["live"] is True
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["checklist"][1].update(done=True, evidence=[{"type": "note", "ref": "ok", "text": "ok"}])
    p.write_text(json.dumps(t))
    server.RequestHandlerClass.keywords["tracker"].status_cache.clear()
    server.RequestHandlerClass.keywords["tracker"].ticket_cache.clear()
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert [t["state"] for t in v["board"]["tasks"]] == ["done"]
    assert (ws / ".orch/addons/focus/runs/r_abc12345.events.jsonl").exists()


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
    assert calls(fake_orch) == [] or all(
        c[:2] in (["run", "status"], ["ticket", "show"]) for c in calls(fake_orch)
    )


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
    got = [
        c
        for c in calls(fake_orch)
        if c[:2] not in (["run", "status"], ["ticket", "show"], ["run", "session"])
    ]
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
    assert not [c for c in calls(fake_orch) if c[:2] not in (["run", "status"], ["ticket", "show"])]


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


@pytest.mark.parametrize(
    "bad",
    ["../../x", "/tmp/x", "r_../../x", "r_ab", "R_ABCDEFG", "r_abcdefg/../../y", "r_abcdefgh/x", "x" * 5, 7],
)
def test_bad_run_id_writes_nothing_outside_runs(server, ws, fake_orch, bad):
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": bad, "agent": "claude", "mode": "live"}}))  # fmt: skip
    before = {p for p in ws.parent.rglob("*")}
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["run"]["run"] is None
    new = {p for p in ws.parent.rglob("*")} - before
    assert not [p for p in new if "events.jsonl" in p.name]
    assert not (ws.parent / "x").exists() and not (ws / "x").exists()


@pytest.mark.parametrize("bad", ["../../x", "/tmp/x", "r_../x", "", "r_a/b" + "c" * 8, "r_abcdefghi"])
def test_event_log_refuses_a_bad_run_id(tmp_path, bad):
    from orch_focus.events import EventLog

    with pytest.raises(ValueError):
        EventLog(tmp_path, bad)


@pytest.mark.parametrize("link", [".orch/addons", ".orch/addons/focus", ".orch/addons/focus/runs", ".orch"])
def test_symlinked_folder_on_the_way_is_refused(tmp_path, link):
    from orch_focus.events import EventLog

    root = tmp_path / "ws"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = root / link
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(elsewhere)
    with pytest.raises(OSError):
        EventLog(root, "r_abcdefgh").append({"v": 1})
    assert list(elsewhere.rglob("*")) == []


def _status(fake, run, by="focus", running=True):
    (fake.parent / "status.json").write_text(
        json.dumps({"running": running, "claim": {"run": run, "by": by, "agent": "x", "mode": "oneshot"}})
    )


def test_exit_stops_only_the_run_focus_started(server, fake_orch):
    from orch_focus.server import stop_started

    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})
    tr = server.RequestHandlerClass.keywords["tracker"]
    assert tr.started == {TID: "r_start001"}
    # someone else started a different run on the same ticket meanwhile: not touched
    _status(fake_orch, "r_other002", by="human:anna")
    stop_started(server)
    assert not any(c[:2] == ["run", "stop"] for c in calls(fake_orch))
    # the same run id, but not started by focus: not touched
    tr.started = {TID: "r_start001"}
    _status(fake_orch, "r_start001", by="human:anna")
    stop_started(server)
    assert not any(c[:2] == ["run", "stop"] for c in calls(fake_orch))
    # our own run: stopped
    tr.started = {TID: "r_start001"}
    _status(fake_orch, "r_start001")
    stop_started(server)
    assert any(c[:3] == ["run", "stop", TID] for c in calls(fake_orch))


def test_stop_from_the_page_forgets_the_run_and_started_survives_a_restart(server, ws, fake_orch):
    from orch_focus.server import Tracker

    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})
    assert Tracker(ws, str(fake_orch)).started == {TID: "r_start001"}  # a crash is recoverable
    req(server, "POST", "/api/act", {"op": "run.stop", "args": {"ticket": TID}})
    assert Tracker(ws, str(fake_orch)).started == {}


def test_control_characters_are_dropped_from_text():
    argv = actions.build_argv("run.send", {"ticket": TID, "text": "hi\x1b[31m there\x7f\nnext\t!"})
    assert argv[-1] == "hi[31m there\nnext\t!"
    with pytest.raises(actions.BadRequest):
        actions.build_argv("run.send", {"ticket": TID, "text": "\x1b\x07"})


def test_attention_state_in_a_live_run(server, fake_orch):
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": "r_att00001", "agent": "claude", "mode": "live", "live": {"state": "attention"}}}))  # fmt: skip
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["state"] == "needs" and v["attention"] is True


def test_generic_comes_from_adapter_data_not_the_agent_name(server, ws, fake_orch):
    def view(agent, mode):
        (fake_orch.parent / "status.json").write_text(
            json.dumps({"running": True, "claim": {"run": "r_gen00001", "agent": agent, "mode": mode}})
        )
        tr = server.RequestHandlerClass.keywords["tracker"]
        tr.status_cache.clear()
        return json.loads(req(server, "GET", f"/api/t/{TID}")[1])

    assert view("claude", "oneshot")["generic"] is False
    assert view("codex", "oneshot")["generic"] is True
    (ws / ".orch" / "config.toml").write_text('[agents.mine]\nadapter = "claude"\n')
    assert view("mine", "live")["generic"] is False


def test_oneshot_denial_asks_and_run_send_note(server, ws, fake_orch):
    (ws / ".orch" / "run" / "logs").mkdir(parents=True)
    (ws / ".orch" / "run" / "logs" / f"{TID}-r_den00001.log").write_text(
        json.dumps({"type": "result", "permission_denials": [{"tool_name": "WebFetch"}]}) + "\n"
    )
    (fake_orch.parent / "status.json").write_text(
        json.dumps(
            {
                "running": True,
                "claim": {"run": "r_den00001", "agent": "claude", "mode": "oneshot", "by": "focus"},
            }
        )
    )
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["board"]["denials"][0]["tool"] == "WebFetch"
    assert [c for c in calls(fake_orch) if c[0] == "ask" and "focus:permission" in c]
    _st, body, _ = req(
        server, "POST", "/api/act", {"op": "run.send", "args": {"ticket": TID, "text": "hello"}}
    )
    assert json.loads(body)["note"] == "Goes in after this step."
