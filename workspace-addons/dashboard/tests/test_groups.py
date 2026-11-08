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
                {"ws": "ws_hom0000001", "name": "Home", "seen": 6, "token": "SECRET"},
            ],
            "tasks": [{"delegate": "m_x", "ws": "ws_hom0000001", "status": "working", "secret": "no"}],
        }
    ],
    "joined": [
        {
            "host": "ws_fin0000001",
            "id": "grp_t_zzzzzz",
            "title": "From Finance",
            "closed": False,
            "left": False,
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
    }
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
    say, add, rm = acts(act_orch)[-3:]
    assert say[:5] == ["relay", "group", "say", "t_abcdef", "--dashboard"] and say[-2:] == [
        "--",
        "--dashboard x",
    ]
    assert add[:5] == ["relay", "group", "add", "t_abcdef", "ws_1"]
    assert rm[:5] == ["relay", "group", "remove", "t_abcdef", "ws_1"]
    json.dumps(say)
