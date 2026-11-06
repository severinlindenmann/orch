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
    return [c for c in calls(act_orch) if c[0] not in ("addon", "needs", "status") and c[:2] not in (["run", "status"], ["ticket", "list"])]


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
    assert s["runs"]["t_7k3f9q"]["running"] is False and "t_other1x" not in s["runs"]
    assert not any(k.startswith("t_other") and "done" in k for k in s["runs"])


def test_dashboard_source_names_no_addon():
    from pathlib import Path
    # the act path (the old inbox/snapshot code names relay/publish; P2 removes it)
    src = Path(actions.__file__).parent
    text = (src / "actions.py").read_text() + (src / "server.py").read_text()
    for name in ("scheduler", "automation", "relay", "focus", "publish", "wiki"):
        assert not re.search(rf"\b{name}\b", text, re.IGNORECASE), name


def test_snapshot_state_has_no_needs_services_or_runs(ws, act_orch):
    from orch_dashboard.data import load_state
    s = load_state(ws, orch_bin=str(act_orch), with_addons=False)
    assert s["needs"] == [] and s["services"] == [] and s["runs"] == {}
