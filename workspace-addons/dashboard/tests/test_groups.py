"""Group chats in the dashboard server: the three ops (argv only) and the `groups` data of /api/state."""

import json
import sys

from orch_dashboard.data import load_state
from orch_dashboard.mobile import load_groups

from .test_act import acts, post

LIST = {
    "hosted": [
        {
            "id": "grp_t_abcdef",
            "ticket": "t_abcdef",
            "title": "Pay car tax 2027",
            "seq": 7,
            "closed": False,
            "members": [
                {
                    "ws": "ws_fin0000001",
                    "name": "Finance",
                    "host": True,
                    "look": {"icon": "bank", "color": "teal"},
                },
                {
                    "ws": "ws_hom0000001",
                    "name": "Home",
                    "seen": 6,
                    "token": "SECRET",
                    "joined_at": "2026-11-08T10:00:00Z",
                },
            ],
            "tasks": [{"delegate": "m_x", "ws": "ws_hom0000001", "status": "working", "secret": "no"}],
            "connectable": [{"ws": "ws_ban0000001", "name": "Bank", "x": 1}],
        }
    ],
    "joined": [
        {
            "host": "ws_fin0000001",
            "id": "grp_t_zzzzzz",
            "title": "From Finance",
            "closed": False,
            "left": False,
            "seq_max": 9,
            "members": [],
            "card": {"title": "Pay"},
            "log": [
                {
                    "id": "m_1",
                    "seq": 3,
                    "text": "hi " + "x" * 900,
                    "shown": "Finance (person)",
                    "authority": False,
                    "evil": 1,
                }
            ],
        }
    ],
}


def fake(tmp_path, listing):
    d = tmp_path / "grorch"
    d.mkdir()
    (d / "list.json").write_text(json.dumps(listing))
    s = d / "orch"
    s.write_text(f"""#!{sys.executable}
import pathlib, sys
a = [x for x in sys.argv[1:] if x != "--json"]
if a[:3] == ["relay", "group", "list"]:
    print((pathlib.Path(__file__).parent / "list.json").read_text())
    sys.exit(0)
sys.exit(2)
""")
    s.chmod(0o755)
    return s


def test_groups_are_read_trimmed_and_only_on_the_live_page(ws, tmp_path):
    orch = fake(tmp_path, LIST)
    g = load_groups(ws, str(orch))
    h = g["hosted"][0]
    assert h["id"] == "grp_t_abcdef" and h["members"][1] == {
        "ws": "ws_hom0000001",
        "name": "Home",
        "look": None,
        "host": False,
        "left_at": None,
        "seen": 6,
        "joined_at": "2026-11-08T10:00:00Z",
    }
    assert h["connectable"] == [{"ws": "ws_ban0000001", "name": "Bank"}]
    assert g["joined"][0]["seq_max"] == 9
    assert h["tasks"] == [{"delegate": "m_x", "ws": "ws_hom0000001", "status": "working"}]
    item = g["joined"][0]["log"][0]
    assert len(item["text"]) == 600 and "evil" not in item and item["authority"] is False
    assert load_state(ws, orch_bin=str(orch), with_addons=True)["groups"]["hosted"][0]["ticket"] == "t_abcdef"
    assert load_state(ws, orch_bin=str(orch), with_addons=False)["groups"] is None  # a snapshot carries none


def test_no_groups_no_data(ws, act_orch, tmp_path):
    assert load_groups(ws, str(act_orch)) is None
    assert load_groups(ws, str(fake(tmp_path, {"hosted": [], "joined": []}))) is None
    assert load_groups(ws, None) is None


def test_group_ops_run_orch_with_exact_argv(act_server, act_orch):
    bad = [
        ("group.say", {"ticket": "t_abcdef"}),
        ("group.say", {"ticket": "../x", "text": "hi"}),
        ("group.say", {"ticket": "t_abcdef", "text": "  "}),
        ("group.say", {"ticket": "t_abcdef", "text": "hi", "by": "agent"}),
        ("group.add", {"ticket": "t_abcdef", "workspace": "--file"}),
        ("group.add", {"ticket": "t_abcdef"}),
        ("group.say", {"group": "grp_t_abcdef", "text": "hi"}),
        ("group.say", {"group": "../x", "host": "ws_fin0000001", "text": "hi"}),
        ("group.say", {"group": "grp_t_abcdef", "host": "--file", "text": "hi"}),
        ("group.say", {"group": "grp_t_abcdef", "host": "ws_fin0000001", "text": "hi", "ticket": "t_abcdef"}),
        ("group.remove", {"ticket": "t_abcdef", "workspace": "a b"}),
        ("group.remove", {"ticket": "t_abcdef", "workspace": "ws_1", "x": 1}),
    ]
    for op, args in bad:
        assert post(act_server, {"op": op, "args": args})[0] == 400, (op, args)
    assert acts(act_orch) == []
    assert (
        post(act_server, {"op": "group.say", "args": {"ticket": "t_abcdef", "text": "--dashboard x"}})[0]
        == 200
    )
    assert (
        post(act_server, {"op": "group.add", "args": {"ticket": "t_abcdef", "workspace": "ws_1"}})[0] == 200
    )
    assert (
        post(act_server, {"op": "group.remove", "args": {"ticket": "t_abcdef", "workspace": "ws_1"}})[0]
        == 200
    )
    assert (
        post(
            act_server,
            {"op": "group.say", "args": {"group": "grp_t_abcdef", "host": "ws_fin0000001", "text": "yo"}},
        )[0]
        == 200
    )
    say, add, rm, reply = acts(act_orch)[-4:]
    assert reply[:6] == ["relay", "group", "reply", "ws_fin0000001", "grp_t_abcdef", "--dashboard"] and reply[
        -2:
    ] == ["--", "yo"]
    assert say[:5] == ["relay", "group", "say", "t_abcdef", "--dashboard"] and say[-2:] == [
        "--",
        "--dashboard x",
    ]
    assert add[:5] == ["relay", "group", "add", "t_abcdef", "ws_1"]
    assert rm[:5] == ["relay", "group", "remove", "t_abcdef", "ws_1"]
    json.dumps(say)


def test_groups_pass_only_cleaned_fields(ws, tmp_path):
    listing = {
        "hosted": [],
        "joined": [
            {
                "host": "ws_fin0000001",
                "id": "grp_t_zzzzzz",
                "title": "T",
                "members": [
                    {"ws": "ws_a", "name": "A", "look": {"icon": "<script>", "color": "red"}},
                    {"ws": "ws_b", "name": "B", "look": {"icon": "house", "color": "amber", "x": "y"}},
                ],
                "card": {
                    "title": "C",
                    "ticket": "t_abcdef",
                    "evil": "x",
                    "done": "many",
                    "total": 3,
                    "rev": 2,
                    "checklist": [{"text": "a", "done": True, "x": 1}],
                    "question": {"text": "q", "evil": 1},
                },
                "log": [
                    {
                        "id": "m_1",
                        "seq": 1,
                        "type": "text",
                        "text": "hi",
                        "shown": "F",
                        "authority": True,
                        "task": {"status": "done", "evil": "no"},
                        "event": {"kind": "closed", "evil": "no"},
                        "file": {"name": "n.txt", "evil": "no"},
                    }
                ],
            }
        ],
    }
    g = load_groups(ws, str(fake(tmp_path, listing)))["joined"][0]
    assert g["members"][0]["look"] is None and g["members"][1]["look"] == {"icon": "house", "color": "amber"}
    assert "evil" not in g["card"] and g["card"]["done"] is None and g["card"]["total"] == 3
    assert g["card"]["checklist"] == [{"text": "a", "done": True}] and g["card"]["question"] == {"text": "q"}
    item = g["log"][0]
    assert (
        item["authority"] is False
        and item["task"] == {"status": "done"}
        and item["event"] == {"kind": "closed"}
    )
    assert item["file"] == {"name": "n.txt"}


def test_group_share_op_builds_the_click_argv_and_is_strict(act_server, act_orch):
    bad = [
        {"ticket": "t_abcdef"},
        {"ticket": "t_abcdef", "file": "../secrets/x.txt"},
        {"ticket": "t_abcdef", "file": "a/b.pdf"},
        {"ticket": "t_abcdef", "file": ".env"},
        {"ticket": "t_abcdef", "file": "--click"},
        {"ticket": "t_abcdef", "file": "a.pdf", "confirm": "yes"},
        {"ticket": "t_abcdef", "file": "a.pdf", "path": "/etc/passwd"},
        {"ticket": "../x", "file": "a.pdf"},
    ]
    for args in bad:
        assert post(act_server, {"op": "group.share", "args": args})[0] == 400, args
    assert acts(act_orch) == []
    assert post(act_server, {"op": "group.share", "args": {"ticket": "t_abcdef", "file": "Letter 1.pdf"}})[0] == 400
    assert post(act_server, {"op": "group.share", "args": {"ticket": "t_abcdef", "file": "letter.pdf"}})[0] == 200
    assert (
        post(act_server, {"op": "group.share", "args": {"ticket": "t_abcdef", "file": "letter.pdf", "confirm": True}})[0]
        == 200
    )
    first, second = acts(act_orch)[-2:]
    path = ".orch/tickets/t_abcdef/artifacts/letter.pdf"
    assert first[:5] == ["relay", "group", "share", "t_abcdef", path] and "--click" in first
    assert "--unchecked-ok" not in first and "--unchecked-ok" in second and "--click" in second


def test_ticket_page_has_the_share_button_only_for_an_open_hosted_group():
    from tests import webjs

    js = (webjs.WEB / "pages" / "ticket.js").read_text(encoding="utf-8")
    assert "'Share with group'" in js and "act('group.share'" in js
    assert "g.ticket === t.id && !g.closed" in js  # shown only when the ticket hosts an open group
    assert "Share anyway" in js and "confirm:true" in js
    assert "ticketShareButton(t, file)" in js and "kind === 'artifacts'" in js
    app = (webjs.WEB / "app.js").read_text(encoding="utf-8")
    assert "wsNames" in app and "state?.groups?.[k]" in app  # ws ids are shown as the member's name


def test_ws_ids_are_shown_as_names_in_the_page_code():
    import subprocess

    from tests import webjs

    app = (webjs.WEB / "app.js").read_text(encoding="utf-8")
    start = app.index("let wsNames")
    end = app.index("const name = value")
    code = app[start:end] + "\nwsNames = new Map([['ws_home000001', 'Home']]);\n" + (
        "console.log(JSON.stringify([clean('agent:ws_home000001 answered'), clean('Asked ws_unknown01 (group)')]));"
    )
    out = subprocess.run(["node", "-e", "const array=v=>Array.isArray(v)?v:[];" + code], check=False, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["agent:Home answered", "Asked  (group)"]  # an unknown id is dropped, never shown raw
