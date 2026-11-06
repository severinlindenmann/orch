import getpass
import http.client
import json
import re

import pytest

from orch_dashboard import actions


def post(base, body, headers=None, raw=None):
    port = int(base.rsplit(":", 1)[1])
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    c.request("POST", "/api/act", body=raw if raw is not None else json.dumps(body), headers=h)
    r = c.getresponse()
    return r.status, r.read().decode(), dict(r.getheaders())


def calls(act_orch):
    f = act_orch.parent / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x] if f.exists() else []


def acts(act_orch):
    return [c for c in calls(act_orch) if c[0] not in ("addon", "needs", "status", "agents") and c[:2] not in (["run", "status"], ["ticket", "list"])]


def test_foreign_or_missing_origin_and_wrong_host_are_refused(act_server, act_orch):
    body = {"op": "log", "args": {"ticket": "t_abcdef", "text": "hi"}}
    port = act_server.rsplit(":", 1)[1]
    for h in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Origin": None},
              {"Origin": "http://evil.example:" + port, "Host": "evil.example:" + port},
              {"Host": "evil.example:" + port}):
        assert post(act_server, body, h)[0] in (403, 421, 400), h
    assert post(act_server, body, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert acts(act_orch) == []


def test_other_paths_and_content_types_are_refused(act_server):
    assert post(act_server, {}, raw="x", headers={"Content-Type": "text/plain"})[0] == 415
    assert post(act_server, None, raw="not json")[0] == 400
    assert post(act_server, None, raw="[1]")[0] == 400
    assert post(act_server, {"op": "log", "args": {}, "more": 1})[0] == 400


@pytest.mark.parametrize("op", ["shell", "addon.stop", "relay.allow", "ticket.delete", "", "log; rm -rf /", None, 5])
def test_op_outside_the_table_is_refused(act_server, act_orch, op):
    code, text, _ = post(act_server, {"op": op, "args": {}})
    assert code == 400 and "not available" in text
    assert acts(act_orch) == []


def test_ids_and_text_are_checked(act_server, act_orch):
    bad = [("log", {"ticket": "../x", "text": "a"}), ("log", {"ticket": "t_abcdef", "text": "x" * 2001}),
           ("log", {"ticket": "t_abcdef", "text": "  "}), ("answer", {"ticket": "t_abcdef", "question": "q1; ls", "answer": "a"}),
           ("ticket.edit", {"ticket": "t_abcdef", "due": "tomorrow"}), ("ticket.edit", {"ticket": "t_abcdef"}),
           ("ticket.patch", {"ticket": "t_abcdef", "data": {"title": "x"}}),
           ("ticket.patch", {"ticket": "t_abcdef", "data": {"id": "t_other1"}, "if_revision": 1}),
           ("ticket.patch", {"ticket": "t_abcdef", "data": {"status": "weird"}, "if_revision": 1}),
           ("run.start", {"ticket": "t_abcdef", "fresh": "yes"}), ("run.start", {"ticket": "t_abcdef", "agent": "x"}),
           ("addon.start", {"name": "x"})]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []


def test_argv_snapshot_per_op(act_server, act_orch):
    me = "human:" + re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:64]
    common = ["--by", me, "--json"]
    cases = [
        ({"op": "answer", "args": {"ticket": "t_abcdef", "question": "q1", "answer": "Yes"}},
         ["answer", "t_abcdef", "q1", "--via", "dashboard", *common, "--", "Yes"]),
        ({"op": "ticket.new", "args": {"title": "--sneaky"}}, ["ticket", "new", *common, "--", "--sneaky"]),
        ({"op": "ticket.new", "args": {"title": "Child", "parent": "t_abcdef"}},
         ["ticket", "new", "--parent=t_abcdef", *common, "--", "Child"]),
        ({"op": "ticket.patch", "args": {"ticket": "t_abcdef", "data": {"title": "New"}, "if_revision": 3}},
         ["ticket", "patch", "t_abcdef", "--if-revision=3", *common, "--", '{"title": "New"}']),
        ({"op": "ticket.edit", "args": {"ticket": "t_abcdef", "owner": "Marco", "due": "2026-11-30", "note": "-n", "if_revision": 2}},
         ["ticket", "edit", "t_abcdef", "--owner=Marco", "--due=2026-11-30", "--note=-n", "--if-revision=2", *common]),
        ({"op": "ticket.edit", "args": {"ticket": "t_abcdef", "due": ""}}, ["ticket", "edit", "t_abcdef", "--due=", *common]),
        ({"op": "log", "args": {"ticket": "t_abcdef", "text": "-hello"}}, ["log", "t_abcdef", *common, "--", "-hello"]),
        ({"op": "run.start", "args": {"ticket": "t_abcdef"}}, ["run", "start", "t_abcdef", *common]),
        ({"op": "run.start", "args": {"ticket": "t_abcdef", "fresh": True, "take_over": True}},
         ["run", "start", "t_abcdef", "--fresh", "--take-over", *common]),
        ({"op": "run.stop", "args": {"ticket": "t_abcdef"}}, ["run", "stop", "t_abcdef", *common]),
        ({"op": "addon.start", "args": {}}, ["start", "--no-open", *common]),
    ]
    for body, want in cases:
        code, text, _ = post(act_server, body)
        assert code == 200, (body, text)
        assert acts(act_orch)[-1] == want, body
        assert json.loads(text)["workspace"] == "Pilatus"  # the reply is a fresh state


def test_actor_is_human_and_answer_via_dashboard(act_server, act_orch):
    post(act_server, {"op": "answer", "args": {"ticket": "t_abcdef", "question": "q2", "answer": "No"}})
    a = acts(act_orch)[-1]
    assert a[a.index("--by") + 1].startswith("human:") and a[a.index("--via") + 1] == "dashboard"
    assert actions.actor().startswith("human:")


def test_stale_patch_gives_409_with_revision(act_server, act_orch):
    (act_orch.parent / "mode.txt").write_text("conflict")
    code, text, hdr = post(act_server, {"op": "ticket.patch",
                                        "args": {"ticket": "t_abcdef", "data": {"title": "x"}, "if_revision": 1}})
    assert code == 409 and "changed by agent:claude" in text and hdr["X-Revision"] == "7"


def test_refusal_comes_back_as_plain_text(act_server, act_orch):
    (act_orch.parent / "mode.txt").write_text("refuse")
    code, text, _ = post(act_server, {"op": "run.stop", "args": {"ticket": "t_abcdef"}})
    assert code == 422 and text == "Nope, not allowed."


def test_no_orch_command_is_a_plain_503(ws):
    import threading

    from orch_dashboard.server import make_server
    srv = make_server(ws, 0, orch_bin="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert post(f"http://127.0.0.1:{srv.server_address[1]}", {"op": "run.stop", "args": {"ticket": "t_abcdef"}})[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()


def test_state_reply_has_needs_services_and_runs(ws, tmp_path):
    from orch_dashboard.data import load_state
    d = tmp_path / "o"
    d.mkdir()
    script = d / "orch"
    import sys
    script.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
if a[:1] == ["needs"]: print(json.dumps([{{"id": "question:t_1:q1", "title": "x"}}]))
elif a[:1] == ["status"]: print(json.dumps([{{"workspace": {str(ws.resolve())!r}, "name": "w", "addons": [{{"addon": "automation", "running": False}}]}}]))
elif a[:2] == ["run", "status"]: print(json.dumps({{"ticket": a[2], "running": False, "pending": 0}}))
else: sys.exit(2)
""")
    script.chmod(0o755)
    s = load_state(ws, orch_bin=str(script))
    assert s["needs"][0]["id"] == "question:t_1:q1"
    assert s["services"] == [{"addon": "automation", "running": False}]
    active = next(t["id"] for t in s["tickets"] if t["status"] in ("active", "waiting"))
    assert s["runs"][active]["running"] is False
    assert all(next(t for t in s["tickets"] if t["id"] == k)["status"] not in ("done", "dropped") for k in s["runs"])


def test_dashboard_source_names_no_addon():
    from pathlib import Path
    src = Path(actions.__file__).parent
    text = "".join((src / f).read_text() for f in ("actions.py", "server.py", "data.py"))
    for name in ("scheduler", "automation", "relay", "focus", "publish", "wiki"):
        assert not re.search(rf"\b{name}\b", text, re.IGNORECASE), name


def test_snapshot_state_has_no_needs_services_or_runs(ws, act_orch):
    from orch_dashboard.data import load_state
    s = load_state(ws, orch_bin=str(act_orch), with_addons=False)
    assert s["needs"] == [] and s["services"] == [] and s["runs"] == {}


def test_runs_are_cached_between_polls(ws, tmp_path):
    from orch_dashboard import data
    d = tmp_path / "c"
    d.mkdir()
    script = d / "orch"
    import sys
    script.write_text(f"""#!{sys.executable}
import json, sys, pathlib
a = sys.argv[1:]
if a[:2] == ["run", "status"]:
    open(pathlib.Path(__file__).parent / "n", "a").write("x")
    print(json.dumps({{"running": True}}))
else: sys.exit(2)
""")
    script.chmod(0o755)
    data._RUNS.clear()
    data.load_state(ws, orch_bin=str(script))
    n1 = len((d / "n").read_text())
    data.load_state(ws, orch_bin=str(script))
    assert len((d / "n").read_text()) == n1  # second poll: no new calls
    data.load_state(ws, orch_bin=str(script), fresh=True)
    assert len((d / "n").read_text()) == 2 * n1


def test_trailing_newline_ids_and_deep_json_are_refused(act_server, act_orch):
    assert post(act_server, {"op": "log", "args": {"ticket": "t_abcdef\n", "text": "a"}})[0] == 400
    assert post(act_server, {"op": "ticket.edit", "args": {"ticket": "t_abcdef", "due": "2026-11-30\n"}})[0] == 400
    assert post(act_server, None, raw="[" * 100000)[0] == 400
    assert acts(act_orch) == []


def test_addon_act_runs_one_generic_argv_for_an_active_addon(act_orch, ws):
    import threading

    from orch_dashboard.server import make_server
    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "alpha", "active": True}, {"name": "beta", "active": False},'
        ' {"name": "ticket", "active": True}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]')
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    me = actions.actor()
    try:
        code, text, _ = post(base, {"op": "addon.act", "args": {"addon": "alpha", "verb": "toggle", "target": "t_abcdef"}})
        assert code == 200, text
        assert acts(act_orch)[-1] == ["alpha", "act", "toggle", "--by", me, "--json", "--", "t_abcdef"]
        bad = [{"addon": "beta", "verb": "run", "target": "t_abcdef"},       # installed but off
               {"addon": "gamma", "verb": "run", "target": "t_abcdef"},      # unknown
               {"addon": "ticket", "verb": "run", "target": "t_abcdef"},     # a core command, never a target
               {"addon": "alpha", "verb": "Run now", "target": "t_abcdef"},
               {"addon": "alpha", "verb": "run;ls", "target": "t_abcdef"},
               {"addon": "alpha", "verb": "run", "target": "--evil"},
               {"addon": "alpha", "verb": "run", "target": "t_abcdef\n"},
               {"addon": "../x", "verb": "run", "target": "t_abcdef"},
               {"addon": "alpha", "verb": "run", "target": "t_abcdef", "extra": 1}]
        for args in bad:
            assert post(base, {"op": "addon.act", "args": args})[0] == 400, args
        assert not any(c[1:2] == ["act"] and c[0] in ("beta", "gamma", "ticket") for c in calls(act_orch))
    finally:
        srv.shutdown()
        srv.server_close()


def _fake_with_addons(act_orch):
    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "alpha", "active": True}, {"name": "beta", "active": False},'
        ' {"name": "dashboard", "active": True}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]')
    act_orch.write_text(src)


def test_settings_ops_argv_and_checks(act_orch, ws):
    import threading

    from orch_dashboard.server import make_server
    _fake_with_addons(act_orch)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    me = actions.actor()
    common = ["--by", me, "--json"]
    try:
        cases = [
            ({"op": "config.agent", "args": {"name": "codex"}}, ["config", "set", "workspace.agent", "codex", *common]),
            ({"op": "config.agent.add", "args": {"name": "my-agent", "command": "mytool --yes {prompt}"}},
             ["config", "agent", "add", "my-agent", "--command=mytool --yes {prompt}", *common]),
            ({"op": "config.agent.add", "args": {"name": "x1", "command": "--evil -x 'a b' \"c\" $(d)", "prompt_via": "stdin"}},
             ["config", "agent", "add", "x1", "--command=--evil -x 'a b' \"c\" $(d)", "--prompt-via=stdin", *common]),
            ({"op": "addon.set", "args": {"name": "beta", "on": True}}, ["addon", "add", "beta", "--yes", *common]),
            ({"op": "addon.set", "args": {"name": "alpha", "on": False}}, ["addon", "remove", "alpha", *common]),
        ]
        for body, want in cases:
            code, text, _ = post(base, body)
            assert code == 200, (body, text)
            last = [c for c in calls(act_orch) if c[:2] not in (["addon", "list"], ["run", "status"], ["ticket", "list"])
                    and c[0] not in ("needs", "status", "agents")][-1]
            assert last == want, body
        n = len(calls(act_orch))
        bad = [
            {"op": "config.agent", "args": {"name": "Bad Name"}}, {"op": "config.agent", "args": {"name": "a"}},
            {"op": "config.agent", "args": {"name": "codex\n"}}, {"op": "config.agent", "args": {"name": "codex", "x": 1}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "a\nb"}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "a\rb"}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "a\u0000b"}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "x" * 501}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "   "}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": ""}},
            {"op": "config.agent.add", "args": {"name": "ok-name"}},
            {"op": "config.agent.add", "args": {"name": "../x", "command": "ok"}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "ok", "prompt_via": "file"}},
            {"op": "config.agent.add", "args": {"name": "ok-name", "command": "ok", "interactive": "x"}},
            {"op": "addon.set", "args": {"name": "gamma", "on": True}},          # not installed
            {"op": "addon.set", "args": {"name": "dashboard", "on": False}},      # never from itself
            {"op": "addon.set", "args": {"name": "ticket", "on": True}},
            {"op": "addon.set", "args": {"name": "alpha", "on": "yes"}},
            {"op": "addon.set", "args": {"name": "alpha"}},
        ]
        for body in bad:
            assert post(base, body)[0] == 400, body
        assert not [c for c in calls(act_orch)[n:] if c[0] in ("config", "addon") and c[1] in ("set", "agent", "add", "remove")]
        assert actions.MAX_COMMAND == 500
        # a command that starts with a dash is still one argv value that begins with --command=
        argv = actions.build_argv("config.agent.add", {"name": "x1", "command": "-rf /"})
        assert "--command=-rf /" in argv and argv.count("--command=-rf /") == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_settings_state_has_agents_and_every_addon(ws, act_orch):
    from orch_dashboard.data import load_state
    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:1] == ["agents"]:\n    print(json.dumps([{"name": "claude", "label": "Claude", "adapter": "claude", "found": True,'
        ' "version": "2.1", "can": "x", "status": "found 2.1", "chosen": True, "secret": "no"}]))\n    sys.exit(0)\n'
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "alpha", "description": "A", "active": True},'
        ' {"name": "beta", "description": "B", "active": False}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]')
    act_orch.write_text(src)
    s = load_state(ws, orch_bin=str(act_orch))["settings"]
    assert s["agents"] == [{"name": "claude", "label": "Claude", "adapter": "claude", "found": True, "version": "2.1",
                            "can": "x", "status": "found 2.1", "chosen": True}]
    assert [(a["name"], a["active"]) for a in s["addons"]] == [("alpha", True), ("beta", False)]
    assert s["folder"] == str(ws)
    assert load_state(ws, orch_bin=str(act_orch), with_addons=False)["settings"] is None
