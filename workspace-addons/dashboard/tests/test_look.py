import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from orch_dashboard import actions, look
from orch_dashboard.data import load_state

from .test_act import acts, post

HERE = Path(__file__).parent
WEB = HERE.parent / "src" / "orch_dashboard" / "web"
BY = actions.actor()


def fake(tmp_path, show=None, profile=None, services=("relay",)):
    """A fake `orch`: look show / shared-pages / status / <service> profile print canned JSON; every call is logged."""
    d = tmp_path / "lookorch"
    d.mkdir()
    st = {
        "show": show
        or {
            "icon": "wallet",
            "color": "amber",
            "set_by": "human",
            "services": {s: {"icon": "wallet"} for s in services},
        },
        "shared": True,
        "profile": profile
        or {
            "description": "Bills and taxes",
            "pending": {"description": "Bills, taxes and budget", "tags": None},
        },
        "status": [
            {
                "workspace": str(tmp_path / "Pilatus"),
                "name": "Pilatus",
                "icon": "wallet",
                "color": "amber",
                "addons": [{"addon": "dashboard", "url": "http://127.0.0.1:8421"}],
            },
            {
                "workspace": "/x/Home",
                "name": "Home",
                "icon": "house",
                "color": "teal",
                "addons": [{"addon": "dashboard", "url": "http://evil.example/"}],
            },
            {"workspace": "/x/Garden", "name": "Garden", "icon": None, "color": None, "addons": []},
        ],
    }
    (d / "state.json").write_text(json.dumps(st))
    s = d / "orch"
    s.write_text(f"""#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
argv = sys.argv[1:]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(argv) + "\\n")
st = json.loads((d / "state.json").read_text())
a = [x for x in argv if x not in ("--json", "--by") and not x.startswith("human:")]
if a[:2] == ["look", "show"]: print(json.dumps(st["show"]))
elif a[:2] == ["look", "shared-pages"]:
    if len(a) > 2: st["shared"] = a[2] == "on"; (d / "state.json").write_text(json.dumps(st))
    print(json.dumps({{"on": st["shared"]}}))
elif a[:2] == ["look", "set"]: print(json.dumps({{"icon": "x", "color": "y"}}))
elif a[:1] == ["status"]: print(json.dumps(st["status"]))
elif len(a) > 1 and a[1] == "profile": print(json.dumps(st["profile"]))
else: sys.exit(2)
""")
    s.chmod(0o755)
    return s


def test_op_table_builds_the_look_commands():
    assert actions.build_argv("look.set", {"icon": "wallet", "color": "amber"}) == [
        "look",
        "set",
        "--icon=wallet",
        "--color=amber",
        "--by",
        BY,
        "--json",
    ]
    assert actions.build_argv("look.set", {"icon": None, "color": None})[:4] == [
        "look",
        "set",
        "--icon=none",
        "--color=auto",
    ]
    assert actions.build_argv("look.shared", {"on": False}) == [
        "look",
        "shared-pages",
        "off",
        "--by",
        BY,
        "--json",
    ]
    assert actions.build_argv("look.description", {"service": "relay", "text": " Bills "}) == [
        "relay",
        "profile",
        "--description=Bills",
        "--by",
        BY,
        "--json",
    ]
    assert actions.build_argv("look.description", {"service": "publish", "text": "x"})[0] == "publish"


@pytest.mark.parametrize(
    "op,args",
    [
        ("look.set", {"icon": "../x", "color": "amber"}),
        ("look.set", {"icon": "wallet", "color": "Amber;rm"}),
        ("look.set", {"icon": 5}),
        ("look.set", {"icon": "wallet", "by": "agent:claude"}),  # a caller is never a request field
        ("look.shared", {"on": "yes"}),
        ("look.shared", {"on": True, "by": "human:boss"}),
        ("look.description", {"service": "ssh", "text": "x"}),
        ("look.description", {"service": "relay", "text": "two\nlines"}),
        ("look.description", {"service": "relay", "text": "x" * 281}),
        ("look.description", {"service": "relay", "text": "x", "tags": "a"}),
    ],
)
def test_bad_requests_are_refused(op, args):
    with pytest.raises(actions.BadRequest):
        actions.build_argv(op, args)


def test_load_look_reads_show_status_and_profile(tmp_path, ws):
    orch = fake(tmp_path)
    look.forget(ws)
    d = look.load_look(ws, str(orch), fresh=True)
    assert (d["icon"], d["color"], d["set_by"], d["shared_pages"], d["service"]) == (
        "wallet",
        "amber",
        "human",
        True,
        "relay",
    )
    assert d["description"] == "Bills and taxes" and d["pending"] == "Bills, taxes and budget"
    by_name = {w["name"]: w for w in d["workspaces"]}
    assert by_name["Pilatus"]["here"] is True and by_name["Pilatus"]["url"] == "http://127.0.0.1:8421"
    assert by_name["Home"]["url"] is None  # only a link to this computer is kept
    assert by_name["Garden"]["url"] is None and by_name["Garden"]["icon"] is None


def test_load_look_without_a_service_has_no_description_target(tmp_path, ws):
    orch = fake(tmp_path, services=())
    d = look.load_look(ws, str(orch), fresh=True)
    assert d["service"] is None and d["description"] is None and d["pending"] is None


def test_no_look_without_the_command(ws):
    assert look.load_look(ws, None, fresh=True) is None


def test_state_carries_look_only_on_the_live_page(tmp_path, ws):
    orch = fake(tmp_path)
    assert load_state(ws, str(orch), with_settings=True, fresh=True)["look"]["icon"] == "wallet"
    assert load_state(ws, str(orch))["look"] is None  # a snapshot is shared: no look block


def test_ops_run_orch_and_the_cache_is_dropped(tmp_path, act_server, act_orch):
    code, text, _ = post(act_server, {"op": "look.set", "args": {"icon": "bank", "color": None}})
    assert code == 200, text
    assert [c for c in acts(act_orch) if c[0] == "look"][-1] == [
        "look",
        "set",
        "--icon=bank",
        "--color=auto",
        "--by",
        BY,
        "--json",
    ]
    code, text, _ = post(act_server, {"op": "look.set", "args": {"icon": "a b"}})
    assert code == 400


def test_web_files_are_served_and_hooked(server):
    import urllib.request

    for name, marker in (
        ("look.js", "OrchLook"),
        ("switcher.js", "ws-switch"),
        ("look-icons.js", "OrchLookData"),
        ("look.css", ".wsb"),
        ("look-colors.css", "data-c=teal"),
    ):
        assert marker in urllib.request.urlopen(f"{server}/{name}").read().decode(), name
    page = urllib.request.urlopen(f"{server}/").read().decode()
    for tag in ("look-icons.js", "look.js", "switcher.js", "look.css", "look-colors.css"):
        assert tag in page
    assert page.index("look.js") < page.index("app.js")


def test_generated_files_match_the_contract():
    gen = HERE.parent / "tools" / "gen_look_icons.py"
    if not (HERE.parents[2] / "contracts" / "look.json").exists():
        pytest.skip("contracts/ not in this checkout")
    assert subprocess.run([sys.executable, str(gen), "--check"], check=False).returncode == 0, (
        "run tools/gen_look_icons.py"
    )


def test_node_tests():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run(
        [node, "--test", str(HERE / "look.test.js")], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]


def test_workspace_needs_are_local_and_cached(ws, tmp_path, monkeypatch):
    from orch_dashboard import data
    other = tmp_path / 'Other'
    (other / '.orch').mkdir(parents=True)
    outside = tmp_path / 'Outside'
    (outside / '.orch').mkdir(parents=True)
    seen = []
    def run(binary, args, root, timeout=5):
        if args[0] == 'look':
            return {'icon': 'house'}
        if args[0] == 'status':
            return [{"workspace": str(p), "name": p.name} for p in (ws, other, tmp_path / 'Missing')]
        assert args == ['needs', '--json'] and timeout == 3
        seen.append(root)
        return [{}, {}] if root == ws else None
    monkeypatch.setattr(data, 'run_orch', run)
    look.forget(ws)
    rows = look.load_look(ws, 'orch')['workspaces']
    assert [r['needs'] for r in rows] == [2, None, None]
    assert seen == [ws, other]
    look.load_look(ws, 'orch')
    assert seen == [ws, other]
