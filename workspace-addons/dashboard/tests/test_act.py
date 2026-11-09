import getpass
import http.client
import json
import os
import re
import sys
from pathlib import Path

import pytest

from orch_dashboard import actions

from . import webjs


def post(base, body, headers=None, raw=None):
    port = int(base.rsplit(":", 1)[1])
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    c.request("POST", "/api/act", body=raw if raw is not None else json.dumps(body), headers=h)
    r = c.getresponse()
    return r.status, r.read().decode(), dict(r.getheaders())


def calls(act_orch):
    f = act_orch.parent / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x] if f.exists() else []


def acts(act_orch):
    return [c for c in calls(act_orch) if c[0] not in ("addon", "needs", "status", "agents") and c[:3] not in (["relay", "mobile", "status"], ["relay", "group", "list"]) and c[:2] not in (["run", "status"], ["ticket", "list"], ["config", "get"], ["look", "show"], ["chat", "status"])
            and c[:2] != ["look", "shared-pages"] and not (c[1:2] == ["profile"] and c[-1] == "--json")]


def test_foreign_or_missing_origin_and_wrong_host_are_refused(act_server, act_orch):
    body = {"op": "log", "args": {"ticket": "t_abcdef", "text": "hi"}}
    port = act_server.rsplit(":", 1)[1]
    for h in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": None},
        {"Origin": "http://evil.example:" + port, "Host": "evil.example:" + port},
        {"Host": "evil.example:" + port},
    ):
        assert post(act_server, body, h)[0] in (403, 421, 400), h
    assert post(act_server, body, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert acts(act_orch) == []


def test_other_paths_and_content_types_are_refused(act_server):
    assert post(act_server, {}, raw="x", headers={"Content-Type": "text/plain"})[0] == 415
    assert post(act_server, None, raw="not json")[0] == 400
    assert post(act_server, None, raw="[1]")[0] == 400
    assert post(act_server, {"op": "log", "args": {}, "more": 1})[0] == 400


@pytest.mark.parametrize(
    "op", ["shell", "addon.stop", "relay.allow", "ticket.delete", "", "log; rm -rf /", None, 5]
)
def test_op_outside_the_table_is_refused(act_server, act_orch, op):
    code, text, _ = post(act_server, {"op": op, "args": {}})
    assert code == 400 and "not available" in text
    assert acts(act_orch) == []


def test_ids_and_text_are_checked(act_server, act_orch):
    bad = [
        ("log", {"ticket": "../x", "text": "a"}),
        ("log", {"ticket": "t_abcdef", "text": "x" * 2001}),
        ("log", {"ticket": "t_abcdef", "text": "  "}),
        ("answer", {"ticket": "t_abcdef", "question": "q1; ls", "answer": "a"}),
        ("ticket.edit", {"ticket": "t_abcdef", "due": "tomorrow"}),
        ("ticket.edit", {"ticket": "t_abcdef"}),
        ("ticket.patch", {"ticket": "t_abcdef", "data": {"title": "x"}}),
        ("ticket.patch", {"ticket": "t_abcdef", "data": {"id": "t_other1"}, "if_revision": 1}),
        ("ticket.patch", {"ticket": "t_abcdef", "data": {"status": "weird"}, "if_revision": 1}),
        ("run.start", {"ticket": "t_abcdef", "fresh": "yes"}),
        ("run.start", {"ticket": "t_abcdef", "agent": "x"}),
        ("addon.start", {"name": "x"}),
    ]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []


def test_argv_snapshot_per_op(act_server, act_orch):
    me = "human:" + re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:64]
    common = ["--by", me, "--json"]
    cases = [
        (
            {"op": "answer", "args": {"ticket": "t_abcdef", "question": "q1", "answer": "Yes"}},
            ["answer", "t_abcdef", "q1", "--via", "dashboard", *common, "--", "Yes"],
        ),
        ({"op": "ticket.new", "args": {"title": "--sneaky"}}, ["ticket", "new", *common, "--", "--sneaky"]),
        (
            {"op": "ticket.new", "args": {"title": "Child", "parent": "t_abcdef"}},
            ["ticket", "new", "--parent=t_abcdef", *common, "--", "Child"],
        ),
        (
            {"op": "ticket.new", "args": {"title": "T", "owner": "Sam", "due": "2026-12-01", "note": "-n"}},
            ["ticket", "new", "--owner=Sam", "--due=2026-12-01", "--note=-n", *common, "--", "T"],
        ),
        (
            {
                "op": "ticket.patch",
                "args": {"ticket": "t_abcdef", "data": {"title": "New"}, "if_revision": 3},
            },
            ["ticket", "patch", "t_abcdef", "--if-revision=3", *common, "--", '{"title": "New"}'],
        ),
        (
            {
                "op": "ticket.edit",
                "args": {
                    "ticket": "t_abcdef",
                    "owner": "Marco",
                    "due": "2026-11-30",
                    "note": "-n",
                    "if_revision": 2,
                },
            },
            [
                "ticket",
                "edit",
                "t_abcdef",
                "--owner=Marco",
                "--due=2026-11-30",
                "--note=-n",
                "--if-revision=2",
                *common,
            ],
        ),
        (
            {"op": "ticket.edit", "args": {"ticket": "t_abcdef", "due": ""}},
            ["ticket", "edit", "t_abcdef", "--due=", *common],
        ),
        (
            {"op": "log", "args": {"ticket": "t_abcdef", "text": "-hello"}},
            ["log", "t_abcdef", *common, "--", "-hello"],
        ),
        ({"op": "run.start", "args": {"ticket": "t_abcdef"}}, ["run", "start", "t_abcdef", *common]),
        (
            {"op": "run.start", "args": {"ticket": "t_abcdef", "fresh": True, "take_over": True}},
            ["run", "start", "t_abcdef", "--fresh", "--take-over", *common],
        ),
        ({"op": "run.stop", "args": {"ticket": "t_abcdef"}}, ["run", "stop", "t_abcdef", *common]),
        ({"op": "share.set", "args": {"on": True}}, ["share", "on", *common]),
        ({"op": "share.set", "args": {"on": False}}, ["share", "off", *common]),
        (
            {"op": "check.add", "args": {"ticket": "t_abcdef", "text": "--draft the page"}},
            ["check", "add", "t_abcdef", *common, "--", "--draft the page"],
        ),
        (
            {"op": "config.permissions", "args": {"mode": "full", "confirm": True}},
            ["config", "set", "workspace.permissions", "full", *common],
        ),
        (
            {
                "op": "ticket.patch",
                "args": {"ticket": "t_abcdef", "data": {"status": "done"}, "if_revision": 4},
            },
            ["ticket", "patch", "t_abcdef", "--if-revision=4", *common, "--", '{"status": "done"}'],
        ),
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
    code, text, hdr = post(
        act_server,
        {"op": "ticket.patch", "args": {"ticket": "t_abcdef", "data": {"title": "x"}, "if_revision": 1}},
    )
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
        assert (
            post(
                f"http://127.0.0.1:{srv.server_address[1]}",
                {"op": "run.stop", "args": {"ticket": "t_abcdef"}},
            )[0]
            == 503
        )
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
    assert all(
        next(t for t in s["tickets"] if t["id"] == k)["status"] not in ("done", "dropped") for k in s["runs"]
    )


def test_dashboard_source_names_no_addon():
    from pathlib import Path

    src = Path(actions.__file__).parent
    text = "".join((src / f).read_text() for f in ("actions.py", "server.py", "data.py"))
    assert "relay" in (src / "mobile.py").read_text()  # the one file allowed to name an add-on: Mobile mode
    for name in ("scheduler", "automation", "relay", "focus", "wiki"):
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
    assert (
        post(act_server, {"op": "ticket.edit", "args": {"ticket": "t_abcdef", "due": "2026-11-30\n"}})[0]
        == 400
    )
    assert post(act_server, None, raw="[" * 100000)[0] == 400
    assert acts(act_orch) == []


def test_addon_act_runs_one_generic_argv_for_an_active_addon(act_orch, ws):
    import threading

    from orch_dashboard.server import make_server

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "alpha", "active": True}, {"name": "beta", "active": False},'
        ' {"name": "ticket", "active": True}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]',
    )
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    me = actions.actor()
    try:
        code, text, _ = post(
            base, {"op": "addon.act", "args": {"addon": "alpha", "verb": "toggle", "target": "t_abcdef"}}
        )
        assert code == 200, text
        assert acts(act_orch)[-1] == ["alpha", "act", "toggle", "--by", me, "--json", "--", "t_abcdef"]
        bad = [
            {"addon": "beta", "verb": "run", "target": "t_abcdef"},  # installed but off
            {"addon": "gamma", "verb": "run", "target": "t_abcdef"},  # unknown
            {"addon": "ticket", "verb": "run", "target": "t_abcdef"},  # a core command, never a target
            {"addon": "alpha", "verb": "Run now", "target": "t_abcdef"},
            {"addon": "alpha", "verb": "run;ls", "target": "t_abcdef"},
            {"addon": "alpha", "verb": "run", "target": "--evil"},
            {"addon": "alpha", "verb": "run", "target": "t_abcdef\n"},
            {"addon": "../x", "verb": "run", "target": "t_abcdef"},
            {"addon": "alpha", "verb": "run", "target": "t_abcdef", "extra": 1},
        ]
        for args in bad:
            assert post(base, {"op": "addon.act", "args": args})[0] == 400, args
        assert not any(c[1:2] == ["act"] and c[0] in ("beta", "gamma", "ticket") for c in calls(act_orch))
    finally:
        srv.shutdown()
        srv.server_close()


def _fake_with_addons(act_orch):
    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:1] == ["agents"]:\n    print(json.dumps([{"name": "claude"}]))\n    sys.exit(0)\n'
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "alpha", "active": True}, {"name": "beta", "active": False},'
        ' {"name": "dashboard", "active": True}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]',
    )
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
            (
                {"op": "config.agent", "args": {"name": "codex"}},
                ["config", "set", "workspace.agent", "codex", *common],
            ),
            (
                {"op": "config.agent.add", "args": {"name": "my-agent", "command": "mytool --yes {prompt}"}},
                ["config", "agent", "add", "my-agent", "--command=mytool --yes {prompt}", *common],
            ),
            (
                {
                    "op": "config.agent.add",
                    "args": {"name": "x1", "command": "--evil -x 'a b' \"c\" $(d)", "prompt_via": "stdin"},
                },
                [
                    "config",
                    "agent",
                    "add",
                    "x1",
                    "--command=--evil -x 'a b' \"c\" $(d)",
                    "--prompt-via=stdin",
                    *common,
                ],
            ),
            (
                {"op": "addon.set", "args": {"name": "beta", "on": True}},
                ["addon", "add", "beta", "--yes", *common],
            ),
            (
                {"op": "addon.set", "args": {"name": "alpha", "on": False}},
                ["addon", "remove", "alpha", *common],
            ),
        ]
        for body, want in cases:
            code, text, _ = post(base, body)
            assert code == 200, (body, text)
            last = [c for c in calls(act_orch) if c[:2] not in (["addon", "list"], ["run", "status"], ["ticket", "list"])
                    and c[0] not in ("needs", "status", "agents") and c[:2] not in (["config", "get"], ["chat", "status"])
                    and c[:3] not in (["relay", "mobile", "status"], ["relay", "group", "list"]) and c[0] != "look"][-1]
            assert last == want, body
        n = len(calls(act_orch))
        bad = [
            {"op": "config.agent", "args": {"name": "Bad Name"}},
            {"op": "config.agent", "args": {"name": "a"}},
            {"op": "config.agent", "args": {"name": "codex\n"}},
            {"op": "config.agent", "args": {"name": "codex", "x": 1}},
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
            {"op": "addon.set", "args": {"name": "gamma", "on": True}},  # not installed
            {"op": "addon.set", "args": {"name": "dashboard", "on": False}},  # never from itself
            {"op": "addon.set", "args": {"name": "ticket", "on": True}},
            {"op": "addon.set", "args": {"name": "alpha", "on": "yes"}},
            {"op": "addon.set", "args": {"name": "alpha"}},
        ]
        for body in bad:
            assert post(base, body)[0] == 400, body
        assert not [
            c
            for c in calls(act_orch)[n:]
            if c[0] in ("config", "addon") and c[1] in ("set", "agent", "add", "remove")
        ]
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
        ' {"name": "beta", "description": "B", "active": False}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]',
    )
    act_orch.write_text(src)
    s = load_state(ws, orch_bin=str(act_orch), with_settings=True)["settings"]
    assert s["agents"] == [
        {
            "name": "claude",
            "label": "Claude",
            "adapter": "claude",
            "found": True,
            "version": "2.1",
            "can": "x",
            "status": "found 2.1",
            "chosen": True,
        }
    ]
    assert [(a["name"], a["active"]) for a in s["addons"]] == [("alpha", True), ("beta", False)]
    assert s["folder"] == str(ws)
    assert load_state(ws, orch_bin=str(act_orch))["settings"] is None  # only the live server asks for it
    assert load_state(ws, orch_bin=str(act_orch), with_addons=False, with_settings=False)["settings"] is None
    assert "consent" in s["addons"][0] and s["addons"][0]["consent"].splitlines()[1].startswith("alpha")


def test_snapshots_carry_no_settings_and_no_folder_path(ws, act_orch):
    from orch_dashboard.snapshot import render_snapshot

    for with_addons in (False, True):
        html = render_snapshot(ws, with_addons=with_addons, orch_bin=str(act_orch))
        assert '"settings"' not in html.replace('"settings": null', "").replace('"settings":null', "")
        assert str(ws) not in html and str(ws.parent) not in html


def test_settings_state_only_from_the_live_server(ws, act_orch):
    import threading

    from orch_dashboard.server import make_server

    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import urllib.request

        st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/state").read())
        assert isinstance(st["settings"], dict) and st["settings"]["folder"] == str(ws)
    finally:
        srv.shutdown()
        srv.server_close()


def test_agent_add_never_overwrites_and_is_logged(act_orch, ws):
    import threading

    from orch_dashboard.server import make_server

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:1] == ["agents"]:\n    print(json.dumps([{"name": "claude"}, {"name": "mine"}]))\n    sys.exit(0)\nif a[:2] in (["addon", "list"]',
    )
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, text, _ = post(
            base, {"op": "config.agent.add", "args": {"name": "mine", "command": "tool {prompt}"}}
        )
        assert code == 400 and "already set up" in text
        assert not [c for c in calls(act_orch) if c[:3] == ["config", "agent", "add"]]
        code, text, _ = post(
            base, {"op": "config.agent.add", "args": {"name": "fresh", "command": "tool {prompt}"}}
        )
        assert code == 200, text
        log = (ws / ".orch" / "run" / "dashboard" / "actions.log").read_text().splitlines()
        rec = json.loads(log[-1])
        assert (
            rec["op"] == "config.agent.add" and rec["name"] == "fresh" and rec["command"] == "tool {prompt}"
        )
        assert rec["via"] == "dashboard" and rec["by"].startswith("human:")
    finally:
        srv.shutdown()
        srv.server_close()


def test_agent_exists_check_fails_closed(act_orch, ws):
    """When `orch agents` cannot be read, the name counts as taken: nothing is added."""
    from orch_dashboard.actions import _agent_exists

    assert _agent_exists(ws, str(act_orch), "anything") is True  # the fake exits 2 for `agents`
    assert _agent_exists(ws, "/nonexistent/orch", "anything") is True


def test_audit_log_is_private_and_never_follows_a_symlink(act_orch, ws):
    import os
    import stat

    from orch_dashboard.actions import _audit

    _audit(ws, "config.agent", {"name": "codex"})
    log = ws / ".orch" / "run" / "dashboard" / "actions.log"
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600 and stat.S_IMODE(os.stat(log.parent).st_mode) == 0o700
    target = ws.parent / "victim.txt"
    target.write_text("keep")
    log.unlink()
    log.symlink_to(target)
    _audit(ws, "config.agent", {"name": "codex"})  # refused quietly; the target stays untouched
    assert target.read_text() == "keep"
    log.unlink()
    d = log.parent
    for p in d.iterdir():
        p.unlink()
    d.rmdir()
    d.symlink_to(ws.parent)  # the folder itself is a symlink
    _audit(ws, "config.agent", {"name": "codex"})
    assert not (ws.parent / "actions.log").exists()


def test_check_add_and_permissions_are_checked(act_server, act_orch):
    bad = [
        ("check.add", {"ticket": "t_abcdef", "text": "x" * 501}),
        ("check.add", {"ticket": "t_abcdef", "text": "  "}),
        ("check.add", {"ticket": "../x", "text": "a"}),
        ("check.add", {"ticket": "t_abcdef", "text": "a", "check": "c1"}),
        ("config.permissions", {"mode": "bypass"}),
        ("config.permissions", {"mode": "Full"}),
        ("config.permissions", {"mode": "full"}),
        ("config.permissions", {"mode": "full", "confirm": False}),
        ("config.permissions", {"mode": "full", "confirm": "yes"}),
        ("config.permissions", {}),
        ("config.permissions", {"mode": "ask", "x": 1}),
        ("share.set", {}),
        ("share.set", {"on": "yes"}),
        ("share.set", {"on": True, "x": 1}),
        ("ticket.patch", {"ticket": "t_abcdef", "data": {"status": "finished"}, "if_revision": 1}),
        ("ticket.patch", {"ticket": "t_abcdef", "data": {"status": "done"}}),
    ]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []
    assert post(act_server, {"op": "check.add", "args": {"ticket": "t_abcdef", "text": "x" * 500}})[0] == 200


def test_check_set_ticks_and_reopens_with_a_fixed_note(act_server, act_orch):
    bad = [
        ("check.set", {"ticket": "t_abcdef", "check": "c1"}),
        ("check.set", {"ticket": "t_abcdef", "check": "c1", "done": "yes"}),
        ("check.set", {"ticket": "t_abcdef", "check": "--x", "done": True}),
        ("check.set", {"ticket": "t_abcdef", "check": "c1", "done": True, "note": "mine"}),
        ("check.set", {"ticket": "../x", "check": "c1", "done": True}),
    ]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []
    assert post(act_server, {"op": "check.set", "args": {"ticket": "t_abcdef", "check": "c1", "done": True}})[0] == 200
    assert post(act_server, {"op": "check.set", "args": {"ticket": "t_abcdef", "check": "c1", "done": False}})[0] == 200
    done, reopen = acts(act_orch)[-2:]
    assert done[:4] == ["check", "done", "t_abcdef", "c1"] and "--note=Ticked off in the dashboard" in done
    assert reopen[:4] == ["check", "reopen", "t_abcdef", "c1"]


def test_relay_send_runs_orch_relay_send_with_the_text_after_dashes(act_server, act_orch):
    bad = [
        ("message.send", {"workspace": "ws_1"}),
        ("message.send", {"workspace": "--file", "text": "hi"}),
        ("message.send", {"workspace": "a b", "text": "hi"}),
        ("message.send", {"workspace": "ws_1", "text": "  "}),
        ("message.send", {"workspace": "ws_1", "text": "x" * 2001}),
        ("message.send", {"workspace": "ws_1", "text": "hi", "file": "/etc/passwd"}),
    ]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []
    assert post(act_server, {"op": "message.send", "args": {"workspace": "ws_1", "text": "--file /etc/passwd"}})[0] == 200
    sent = acts(act_orch)[-1]
    assert sent[:3] == ["relay", "send", "ws_1"] and sent[-2:] == ["--", "--file /etc/passwd"]


def test_permissions_setting_is_read_and_logged(ws, act_orch):
    from orch_dashboard.actions import run_op
    from orch_dashboard.data import load_settings

    assert load_settings(ws, str(act_orch))["permissions"] == "auto"  # the fake cannot answer: the default
    src = act_orch.read_text().replace(
        "mode = (d",
        'if a[:2] == ["config", "get"]:\n    print(json.dumps({"workspace.permissions": "full"}))\n    sys.exit(0)\nmode = (d',
    )
    act_orch.write_text(src)
    assert load_settings(ws, str(act_orch))["permissions"] == "full"
    assert run_op(ws, str(act_orch), "config.permissions", {"mode": "ask"})[0] == 200
    log = (ws / ".orch" / "run" / "dashboard" / "actions.log").read_text().splitlines()
    assert json.loads(log[-1])["mode"] == "ask"


def test_full_is_only_sent_after_the_yes_dialog():
    """The page asks (Yes/No) before it sends Full, and the op itself refuses Full without confirm."""
    js = webjs.all_js()
    sender = js[js.index("const mode = perm.dataset.settingsPermissions;") :]
    sender = sender[: sender.index("return;\n    }")]
    assert "settingsConfirm(" in sender and "confirm:true" in sender
    assert (
        sender.index("settingsConfirm(") < sender.rindex("send")
        and "if (mode !== 'full') { await send(); return; }" in sender
    )
    assert actions.build_argv("config.permissions", {"mode": "ask"})[:3] == [
        "config",
        "set",
        "workspace.permissions",
    ]
    assert "confirm" not in " ".join(
        actions.build_argv("config.permissions", {"mode": "full", "confirm": True})
    )


def test_workflow_and_review_actions_use_human_actor():
    from orch_dashboard.actions import build_argv

    for status in ("ready", "active", "review", "done"):
        argv = build_argv(
            "ticket.patch", {"ticket": "t_abcdef", "data": {"status": status}, "if_revision": 1}
        )
        assert argv[argv.index("--by") + 1].startswith("human:")
    for on in (True, False):
        argv = build_argv("workflow.set", {"on": on})
        assert argv[:4] == ["config", "set", "workflow.agents_may_finish", "on" if on else "off"]
        assert argv[argv.index("--by") + 1].startswith("human:")


def test_browser_actions_do_not_inherit_the_servers_agent_identity(ws, monkeypatch):
    from orch.adapters import detect_env

    monkeypatch.setenv("ORCH_AGENT", "claude")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CODEX_TEST", "1")
    monkeypatch.setenv("ORCH_RUN", "run123")
    monkeypatch.setenv("ORCH_TICKET", "t_abcdef")
    from orch.adapters import _registry

    removed = {"ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET"}
    for adapter in _registry().values():
        detection = adapter.get("detect") or {}
        removed.update(detection.get("env_any") or [])
        if detection.get("env_prefix"):
            removed.add(detection["env_prefix"] + "TEST")
    for name in removed:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("KEEP_FOR_AGENT", "yes")
    env = actions.human_env(ws, "orch")
    assert detect_env(env) is None
    assert removed.isdisjoint(env)
    assert env["KEEP_FOR_AGENT"] == "yes"
    assert env["ORCH_VIA"] == "dashboard"


def test_workflow_state_defaults_off_and_reads_core_config(ws):
    from orch import config

    from orch_dashboard.data import load_settings

    assert load_settings(ws, None)["agents_may_finish"] is False
    config.set_agents_may_finish(ws, True)
    assert load_settings(ws, None)["agents_may_finish"] is True


def test_human_review_done_and_workflow_reach_core_even_when_server_was_started_by_agent(
    ws, tmp_path, monkeypatch
):
    import sys

    from orch import config

    monkeypatch.setenv("ORCH_AGENT", "claude")
    pytest.importorskip("cryptography")  # the real CLI runs in a subprocess; this venv may lack the core deps
    command = tmp_path / "orch-core"
    src = Path(__file__).resolve().parents[3] / "workspace" / "src"
    command.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(src)!r})\n"
        "from orch.cli import main\nraise SystemExit(main())\n"
    )
    command.chmod(0o700)
    p = ws / ".orch/tickets/t_7k3f9q.json"
    t = json.loads(p.read_text())
    t["status"] = "review"
    p.write_text(json.dumps(t))
    code, text, _ = actions.run_op(
        ws,
        str(command),
        "ticket.patch",
        {"ticket": t["id"], "data": {"status": "done"}, "if_revision": t["revision"]},
    )
    assert code == 200, text
    saved = json.loads(p.read_text())
    assert saved["status"] == "done" and saved["history"][-1]["by"].startswith("human:")
    code, text, _ = actions.run_op(ws, str(command), "workflow.set", {"on": True})
    assert code == 200, text
    assert config.agents_may_finish(ws) is True


def test_human_env_drops_the_agent_variables(ws, monkeypatch):
    monkeypatch.setenv("ORCH_AGENT", "claude")
    monkeypatch.setenv("CLAUDECODE", "1")
    env = actions.human_env(ws, "orch")
    assert "ORCH_AGENT" not in env and "CLAUDECODE" not in env and env["ORCH_VIA"] == "dashboard"


def test_share_state_is_read_from_agents_md_only(ws):
    from orch_dashboard.data import load_settings

    assert load_settings(ws, None)["share"] is False
    (ws / "AGENTS.md").write_text("# Team\n<!-- orch:begin share -->\nx\n<!-- orch:end share -->\n", encoding="utf-8")
    assert load_settings(ws, None)["share"] is True


def test_ask_for_changes_is_one_op_with_only_a_ticket_and_a_note():
    argv = actions.build_argv("ticket.changes", {"ticket": "t_abcdef", "text": "Make it blue"})
    assert argv[-3:] == ["--", "t_abcdef", "Make it blue"] or argv[-2:] == ["t_abcdef", "Make it blue"]
    assert "changes" in argv and "patch" not in argv
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.changes", {"ticket": "t_abcdef", "text": " "})
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.changes", {"ticket": "t_abcdef", "text": "x", "status": "active"})


def test_link_commands_and_validation():
    common = ['--by', actions.actor(), '--json']
    assert actions.build_argv('link.extend', {'id': 'f_abc123', 'days': 7}) == ['publish', 'extend', 'f_abc123', '--days', '7', *common]
    assert actions.build_argv('link.stop', {'id': 'f_abc123'}) == ['publish', 'delete', 'f_abc123', *common]
    for op, args in [('link.stop', {'id': 'app'}), ('link.stop', {'id': 'f_a', 'extra': 1})] + [('link.extend', {'id': 'f_a', 'days': n}) for n in (0, 91, True, '7')]:
        with pytest.raises(actions.BadRequest):
            actions.build_argv(op, args)


def test_links_fail_closed(ws, monkeypatch):
    from orch_dashboard import data
    monkeypatch.setattr(data, 'run_orch', lambda *a, **kw: None)
    with pytest.raises(actions.BadRequest, match='Sharing is not set up here.'):
        actions.run_op(ws, 'orch', 'link.stop', {'id': 'f_a'})


def test_addon_repeat_and_copy_argv():
    common = ['--by', actions.actor(), '--json', '--', 't_abcdef']
    assert actions.build_argv('addon.act', {"addon": 'automation', "verb": 'repeat', "target": 't_abcdef', "value": 'every day at 9'}) == ['automation', 'act', 'repeat', '--value=every day at 9', *common]
    assert actions.build_argv('addon.act', {"addon": 'automation', "verb": 'copy', "target": 't_abcdef'}) == ['automation', 'act', 'copy', *common]
    for verb, value in [('copy', 'daily'), ('repeat', 'x' * 201), ('repeat', '')]:
        with pytest.raises(actions.BadRequest):
            actions.build_argv('addon.act', {"addon": 'automation', "verb": verb, "target": 't_abcdef', "value": value})


@pytest.mark.parametrize('who', [None, {}, {'error': 'No connection'}, {'id': ''}])
def test_link_auth_refuses_unreadable_identity(ws, monkeypatch, who):
    from orch_dashboard import data
    monkeypatch.setattr(data, 'run_orch', lambda binary, args, root: [{'name': 'publish', 'active': True}] if args[0] == 'addon' else who)
    with pytest.raises(actions.BadRequest, match='Sharing is not set up here.'):
        actions.run_op(ws, 'orch', 'link.stop', {'id': 'f_a'})


def test_link_actions_are_audited(ws, monkeypatch):
    import subprocess
    monkeypatch.setattr(actions, 'publish_connected', lambda *a: True)
    monkeypatch.setattr(actions, 'human_env', lambda *a: {})
    monkeypatch.setattr(actions.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, '{}', ''))
    for op, args in [('link.extend', {'id': 'f_a', 'days': 7}), ('link.stop', {'id': 'f_a'})]:
        assert actions.run_op(ws, 'orch', op, args)[0] == 200
    rows = [json.loads(line) for line in (ws / '.orch/run/dashboard/actions.log').read_text().splitlines()]
    assert [(r['op'], r['id'], r.get('days')) for r in rows] == [('link.extend', 'f_a', 7), ('link.stop', 'f_a', None)]


# ---- fb19: long text and attached files for a new ticket


def _post_raw(base, body, headers=None):
    h = {"X-Orch-Op": body.get("op")} if isinstance(body.get("op"), str) else {}
    return post(base, None, headers={**h, **(headers or {})}, raw=json.dumps(body))


def test_big_body_is_allowed_only_for_a_new_ticket(act_server, act_orch):
    big = "x" * 40000
    s, _, _ = _post_raw(act_server, {"op": "ticket.new", "args": {"title": "T", "long_text": big}})
    assert s == 200
    c = acts(act_orch)[-1]
    assert c[:2] == ["ticket", "new"] and not any(a.startswith("--note=") and len(a) > 2100 for a in c)
    assert any(a.startswith("--note=The full text is attached as note.md") for a in c)
    s, _, _ = _post_raw(act_server, {"op": "log", "args": {"ticket": "t_abcdef", "text": "x"}, "pad": big})
    assert s == 400
    s, _, _ = _post_raw(act_server, {"op": "log", "args": {"ticket": "t_abcdef", "text": big[:30000]}})
    assert s == 400  # over 16 KB for an ordinary action


def test_body_over_the_hard_cap_is_refused(act_server):
    try:
        status = _post_raw(
            act_server, {"op": "ticket.new", "args": {"title": "T", "long_text": "y" * (5 * 1024 * 1024)}}
        )[0]
    except (BrokenPipeError, ConnectionResetError):  # answered before the whole body was sent
        return
    assert status == 400


def test_long_text_over_the_limit_and_short_text_cap_unchanged(act_server):
    assert (
        _post_raw(act_server, {"op": "ticket.new", "args": {"title": "T", "long_text": "z" * 500_001}})[0]
        == 400
    )
    assert _post_raw(act_server, {"op": "ticket.new", "args": {"title": "T", "note": "n" * 2001}})[0] == 400


def test_paste_long_text_keeps_the_note_short():
    text = "First line\n" + "word " * 800
    _, flags, tail = actions.OPS["ticket.paste"]({"text": text})
    assert tail == ["First line"]
    assert flags == ["--title-auto", "--note=" + actions.LONG_NOTE]
    assert [n for n, _ in actions.attachments("ticket.paste", {"text": text})] == ["note.md"]
    # a short paste is unchanged: no file, the text is the note
    short = "Short title\nand some more"
    _, flags, _ = actions.OPS["ticket.paste"]({"text": short})
    assert flags == ["--title-auto", "--note=" + short]  # several lines: the agent writes the title
    _, flags, _ = actions.OPS["ticket.paste"]({"text": "Fix the login"})
    assert flags == ["--note=Fix the login"]  # one short line is its own title
    assert actions.attachments("ticket.paste", {"text": short}) == []


def test_attachments_shape_and_limits():
    import base64

    ok = actions.attachments(
        "ticket.new",
        {
            "title": "T",
            "files": [
                {"name": "a.md", "text": "hi"},
                {"name": "p.png", "data": base64.b64encode(b"\x89PNG").decode()},
            ],
        },
    )
    assert ok == [("a.md", b"hi"), ("p.png", b"\x89PNG")]
    bad = (
        {"files": "nope"},
        {"files": [{"name": "a.md"}]},
        {"files": [{"name": "a.md", "text": "x", "path": "/etc/passwd"}]},
        {"files": [{"name": "a.md", "text": "x", "data": "eA=="}]},
        {"files": [{"name": "a.png", "data": "not base64!"}]},
        {"files": [{"name": "a\x00.md", "text": "x"}]},
        {"files": [{"name": "a.md", "text": "x"}] * 6},
        {"long_text": "t", "files": [{"name": "a.md", "text": "x"}] * 5},
    )
    for args in bad:
        with pytest.raises(actions.BadRequest):
            actions.attachments("ticket.new", {"title": "T", **args})
    assert actions.attachments("log", {"files": [1]}) == []  # only a new ticket takes files
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.paste", {"text": "x", "files": []})


def test_attach_all_pipes_each_file_to_orch_and_reports_failures(tmp_path, monkeypatch):
    fake = tmp_path / "orch"
    fake.write_text(
        f"""#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
data = sys.stdin.buffer.read()
with open(d / "att.jsonl", "a") as f:
    f.write(json.dumps([a, data.decode("latin1")]) + "\\n")
name = [x for x in a if x.startswith("--name=")][0][7:]
if name.endswith(".exe"):
    sys.stderr.write("Refused: no\\n"); sys.exit(2)
print(json.dumps({{"name": "kept-" + name}}))
"""
    )
    fake.chmod(0o755)
    monkeypatch.setattr(actions, "human_env", lambda root, b: dict(os.environ))
    r = actions._attach_all(tmp_path, str(fake), "t_abcdef", [("note.md", b"BODY"), ("bad.exe", b"MZ")])
    assert r == {"saved": ["kept-note.md"], "failed": ["bad.exe"]}
    rows = [json.loads(x) for x in (tmp_path / "att.jsonl").read_text().splitlines()]
    assert rows[0][0][:4] == ["ticket", "attach", "t_abcdef", "--name=note.md"] and rows[0][1] == "BODY"


def test_body_limit_comes_from_the_op_header(act_server):
    big = "x" * 40000
    body = {"op": "ticket.new", "args": {"title": "T", "long_text": big}}
    assert _post_raw(act_server, body, {"X-Orch-Op": None})[0] == 400  # no header: the small limit
    assert _post_raw(act_server, body, {"X-Orch-Op": "log"})[0] == 400  # header and body disagree
    assert _post_raw(act_server, body)[0] == 200


def test_lone_surrogate_and_early_refusals_are_plain_400s(act_server, act_orch):
    for args in (
        {"title": "T", "long_text": "a\ud800b"},
        {"title": "T\ud800"},
        {"title": "T", "files": [{"name": "a.md", "text": "x\udc00"}]},
        {"title": "T", "files": [{"name": "tool.exe", "text": "x"}]},
        {"title": "T", "files": [{"name": "big.txt", "text": "x" * (2 * 1024 * 1024 + 1)}]},
    ):
        assert _post_raw(act_server, {"op": "ticket.new", "args": args})[0] == 400, args
    assert acts(act_orch) == []  # nothing was created
