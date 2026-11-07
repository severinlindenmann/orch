import json
import sys

import pytest

from orch_dashboard import actions
from orch_dashboard.data import load_state
from orch_dashboard.mobile import load_mobile

from .test_act import acts, post


def fake(tmp_path, state):
    """A fake `orch`: `relay mobile status` prints state.json; on/off/hours/ack change it like the real command."""
    d = tmp_path / "mmorch"
    d.mkdir()
    (d / "state.json").write_text(json.dumps(state))
    s = d / "orch"
    s.write_text(f"""#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
a = [x for x in sys.argv[1:] if x not in ("--json", "--by") and not x.startswith("human:")]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
st = json.loads((d / "state.json").read_text())
if a[:2] != ["relay", "mobile"]:
    sys.exit(2)
v = a[2]
if v == "on":
    st.update(on=True, awake="ok", since="2026-11-07T14:02:00Z", ends_at="2026-11-08T02:02:00Z", ended=None)
elif v == "off":
    st.update(on=False, awake=None, since=None, ends_at=None, ended=None)
elif v == "hours":
    st["default_hours"] = int(a[3])
elif v == "ack":
    st["ended"] = None
(d / "state.json").write_text(json.dumps(st))
print(json.dumps(st))
""")
    s.chmod(0o755)
    return s


OFF = {"on": False, "default_hours": 12, "hours_choices": [4, 8, 12, 24], "awake": None, "since": None,
       "ends_at": None, "machine": "Acme PC", "ended": None}


def test_op_table_builds_the_relay_commands():
    by = actions.actor()
    assert actions.build_argv("mobile.set", {"on": True}) == ["relay", "mobile", "on", "--by", by, "--json"]
    assert actions.build_argv("mobile.set", {"on": True, "hours": 8}) == ["relay", "mobile", "on", "--hours=8", "--by", by, "--json"]
    assert actions.build_argv("mobile.set", {"on": False})[:3] == ["relay", "mobile", "off"]
    assert actions.build_argv("mobile.hours", {"hours": 24})[:4] == ["relay", "mobile", "hours", "24"]
    assert actions.build_argv("mobile.ack", {})[:3] == ["relay", "mobile", "ack"]


@pytest.mark.parametrize("op,args", [("mobile.set", {}), ("mobile.set", {"on": "yes"}), ("mobile.set", {"on": True, "hours": 5}),
                                     ("mobile.set", {"on": True, "hours": True}), ("mobile.set", {"on": False, "hours": 4}),
                                     ("mobile.set", {"on": True, "x": 1}), ("mobile.hours", {"hours": "8"}),
                                     ("mobile.hours", {}), ("mobile.ack", {"x": 1})])
def test_bad_mobile_args_are_refused(act_server, act_orch, op, args):
    assert post(act_server, {"op": op, "args": args})[0] == 400
    assert [c for c in acts(act_orch) if c[2:3] != ["status"]] == []


def test_act_runs_one_command_through_the_server(act_server, act_orch):
    code, text, _ = post(act_server, {"op": "mobile.set", "args": {"on": True, "hours": 4}})
    assert code == 200, text
    assert [c[:4] for c in acts(act_orch) if c[2:3] != ["status"]] == [["relay", "mobile", "on", "--hours=4"]]


def test_state_carries_mobile_mode_only_for_the_live_page(ws, tmp_path):
    orch = fake(tmp_path, {**OFF, "ended": {"at": "2026-11-07T10:00:00Z", "reason": "restart", "text": "Mobile mode ended when the computer restarted.", "x": 1}})
    live = load_state(ws, orch_bin=str(orch), with_settings=True)["mobile_mode"]
    assert live["on"] is False and live["default_hours"] == 12 and live["ended"]["reason"] == "restart"
    assert "x" not in live["ended"]
    assert load_state(ws, orch_bin=str(orch))["mobile_mode"] is None


def test_no_switch_when_the_relay_is_not_on(ws, act_orch):
    assert load_mobile(ws, str(act_orch)) is None  # the fake exits 2 for unknown calls...
    assert load_mobile(ws, None) is None


def test_odd_values_are_cleaned(ws, tmp_path):
    orch = fake(tmp_path, {**OFF, "default_hours": 7, "awake": "maybe", "hours_choices": [3, 4], "machine": "x" * 500})
    m = load_mobile(ws, str(orch))
    assert m["default_hours"] == 12 and m["awake"] is None and m["hours_choices"] == [4]
    assert len(m["machine"]) == 60


def test_web_files_are_served(server):
    import urllib.request
    for n in ("mobile-mode.js", "index.html"):
        body = urllib.request.urlopen(f"{server}/{n}").read().decode()
        assert "mm-toggle" in body or "orch:state" in body
