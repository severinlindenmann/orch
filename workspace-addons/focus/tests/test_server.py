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
    assert go("check.add", {"ticket": TID, "text": "--new task"})[0] == 200
    got = [
        c
        for c in calls(fake_orch)
        if c[:2] not in (["run", "status"], ["ticket", "show"], ["run", "session"], ["ext", "set"], ["agents", "--json"], ["relay", "mobile"])
    ]
    assert got[0][:4] == ["run", "start", TID, "--by"] and got[0][4] == "focus"
    assert "--fresh" in got[1]
    assert got[2][:3] == ["run", "stop", TID]
    assert got[3][-3:] == ["--", TID, "--delete everything"]  # free text can never be an option
    assert got[4][:4] == ["check", "move", TID, "c2"] and "--after=c1" in got[4]
    assert got[5][-2:] == ["--", "New name"] and "--if-revision=3" in got[5]
    assert got[6][0] == "answer" and "--via" in got[6]
    assert got[7][:3] == ["check", "add", TID] and got[7][-2:] == ["--", "--new task"]


@pytest.mark.parametrize(
    "op,args",
    [("shell", {}), ("run.start", {"ticket": "../x"}), ("run.start", {"ticket": TID, "agent": "x"}),
     ("run.send", {"ticket": TID, "text": ""}), ("run.send", {"ticket": TID, "text": "x" * 2001}),
     ("check.remove", {"ticket": TID, "check": "c1; ls"}), ("check.edit", {"ticket": TID, "check": "c1", "text": "a\x00b"}),
     ("run.start", {"ticket": TID, "allow": ["Bash"]}), ("check.add", {"ticket": TID, "text": "x" * 501}),
     ("check.add", {"ticket": TID, "text": "  "}), ("check.add", {"ticket": TID, "text": "a", "check": "c1"})],
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
    assert v["state"] == "needs" and v["attention"] is True and v["why"] == ""


def test_a_live_session_waiting_for_a_message_is_not_working(server, fake_orch):
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": "r_idl00001", "agent": "claude", "mode": "live", "live": {"state": "idle"}}}))  # fmt: skip
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["state"] == "waiting" and v["run"]["running"] is True


def test_attention_shows_what_the_live_tool_waits_for(server, fake_orch):
    why = "Claude asks whether to trust this folder. Open the live session and answer: orch run attach t_x"
    (fake_orch.parent / "status.json").write_text(json.dumps(
        {"running": True, "claim": {"run": "r_att00002", "agent": "claude", "mode": "live",
                                    "live": {"state": "attention", "why": why}}}))  # fmt: skip
    v = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert v["state"] == "needs" and v["why"] == why


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


def test_run_start_marks_the_ticket_page_once(server, fake_orch, ws):
    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})
    ext = [c for c in calls(fake_orch) if c[:2] == ["ext", "set"]]
    assert ext == [
        ["ext", "set", TID, "focus", json.dumps({"page": f"t/{TID}"}), "--by", "agent:focus", "--json"]
    ]
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["ext"] = {"focus": {"page": f"t/{TID}"}}
    p.write_text(json.dumps(t))
    server.RequestHandlerClass.keywords["tracker"].ticket_cache.clear()
    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})
    assert len([c for c in calls(fake_orch) if c[:2] == ["ext", "set"]]) == 1  # already set: not again


@pytest.mark.parametrize("path", [f"/t/{TID}", f"//t/{TID}", f"/t/t/{TID}"])
def test_page_route_tolerates_how_a_surface_joins_the_path(server, path):
    assert req(server, "GET", path)[0] == 200


def test_retry_error_shows_on_the_view(server):
    tr = server.RequestHandlerClass.keywords["tracker"]
    tr.perms.failed[TID] = "Busy now."
    assert json.loads(req(server, "GET", f"/api/t/{TID}")[1])["retry_error"] == "Busy now."


def test_ticket_key_in_view_and_list(server, ws):
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["key"] = "MEC-4"
    p.write_text(json.dumps(t))
    assert json.loads(req(server, "GET", f"/api/t/{TID}")[1])["ticket"]["key"] == "MEC-4"
    rows = json.loads(req(server, "GET", "/api/tickets")[1])["tickets"]
    assert [r["key"] for r in rows if r["id"] == TID] == ["MEC-4"]


def test_a_done_ticket_is_listed_and_opens_as_a_board(server, ws):
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["status"] = "done"
    p.write_text(json.dumps(t))
    rows = json.loads(req(server, "GET", "/api/tickets")[1])["tickets"]
    assert [r["status"] for r in rows if r["id"] == TID] == ["done"]
    st, body, _ = req(server, "GET", f"/api/t/{TID}")
    v = json.loads(body)
    assert st == 200 and v["state"] == "done" and v["run"]["running"] is False and v["ticket"]["history"]


def test_events_stream_pushes_a_change_and_keeps_the_fence(server, ws):
    import time

    port = server.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    c.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    try:
        assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
        assert r.readline() == b"event: rev\n"
        first = r.readline()
        r.readline()
        start = time.monotonic()
        (ws / ".orch/tickets/t_new00001.json").write_text("{}")
        assert r.readline() == b"event: rev\n"
        assert r.readline() != first
        assert time.monotonic() - start < 1
    finally:
        r.close()
        c.close()
    assert req(server, "GET", "/api/events", headers={"Origin": "https://foreign.example"})[0] == 403
    assert req(server, "GET", "/api/events", headers={"Host": "evil.example"})[0] == 403


def test_events_client_cap_is_20(server):
    conns = []
    port = server.server_address[1]
    try:
        for _ in range(20):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conns.append(c)
            c.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{port}"})
            r = c.getresponse()
            assert r.status == 200
            assert r.readline() == b"event: rev\n"
        assert req(server, "GET", "/api/events")[0] == 503
    finally:
        for c in conns:
            c.close()


def test_fresh_view_refetches_once_per_change(server, fake_orch, ws):
    fresh = f"/api/t/{TID}?fresh=1"
    assert req(server, "GET", f"/api/t/{TID}")[0] == 200
    n = len(calls(fake_orch))
    assert req(server, "GET", f"/api/t/{TID}")[0] == 200
    assert len(calls(fake_orch)) == n  # cached
    assert req(server, "GET", fresh)[0] == 200
    n2 = len(calls(fake_orch))
    assert n2 > n  # the first fresh refetches
    assert req(server, "GET", fresh)[0] == 200
    assert len(calls(fake_orch)) == n2  # nothing changed since: no stampede
    (ws / ".orch/tickets/t_new00002.json").write_text("{}")
    assert req(server, "GET", fresh)[0] == 200
    assert len(calls(fake_orch)) > n2  # a change refetches, however young the cache


def test_run_send_argv_parses_on_every_python(tmp_path):
    """fb14: `orch run send <ticket> --by .. --json -- <text>` failed with "unrecognized arguments: -- <text>" on
    Python 3.11 (an optional positional after the ticket is taken early). The ticket must follow the options."""
    argv = actions.build_argv("run.send", {"ticket": TID, "text": "can you mark all tickets as done"})
    assert argv[:2] == ["run", "send"] and argv[2] != TID
    assert argv[-3:] == ["--", TID, "can you mark all tickets as done"]
    import argparse

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--by")
    top = argparse.ArgumentParser()
    x = top.add_subparsers(dest="cmd").add_parser("run").add_subparsers(dest="sub").add_parser("send", parents=[common])
    x.add_argument("ticket")
    x.add_argument("text", nargs="?")
    ns = top.parse_args(argv)
    assert (ns.ticket, ns.text) == (TID, "can you mark all tickets as done")


def test_listen_backlog_is_large(server):
    # the default backlog of 5 resets connections when a page loads many files at once (blank Focus page)
    assert server.request_queue_size >= 128

def test_view_carries_the_hold_reason_only_while_the_run_runs(server, ws, fake_orch):
    """fb18 (hold-why): the core's one-line reason shows as `hold`; it is empty without one or without a run."""
    import json

    tracker = server.RequestHandlerClass.keywords["tracker"]
    status = fake_orch.parent / "status.json"
    why = "Waiting: clear the text in the agent's window."
    status.write_text(json.dumps({"running": True, "state": "alive", "claim": {"mode": "live", "run": "r_abcd1234"}, "hold": why + "\n<b>x</b>"}))
    tracker.status_cache.clear()
    assert tracker.view(TID)["hold"] == why + " <b>x</b>"
    status.write_text(json.dumps({"running": True, "state": "alive", "claim": {"mode": "live", "run": "r_abcd1234"}}))
    tracker.status_cache.clear()
    assert tracker.view(TID)["hold"] == ""
    status.write_text(json.dumps({"running": False, "hold": why}))
    tracker.status_cache.clear()
    assert tracker.view(TID)["hold"] == ""
