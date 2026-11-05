import copy
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from jsonschema import Draft202012Validator

from orch_dashboard.data import load_addons, load_state
from orch_dashboard.views import ViewPuller, check_view

from .conftest import CONTRACTS, VIEW

SCHEMA = json.loads((CONTRACTS.parent / "addon-view.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def example():
    return json.loads(VIEW.read_text())


def test_example_passes_both_checks():
    assert not list(VALIDATOR.iter_errors(example()))
    assert check_view(example())["blocks"] == example()["blocks"]


@pytest.mark.parametrize("mutate", [
    lambda v: v["blocks"][0].update(label="<b>x</b>"),
    lambda v: v["blocks"][4]["items"][0].update(link="javascript:alert(1)"),
    lambda v: v["blocks"][4]["items"][0].update(link="http://example.com"),
    lambda v: v["blocks"][3]["days"][0]["items"][0].update(time="25:99"),
    lambda v: v["blocks"][6]["rows"][0]["cells"].update(took="<i>"),
    lambda v: v.update(generated_at="yesterday"),
    lambda v: v.update(schema="orch.addon-view/2"),
    lambda v: v["blocks"][0].update(tone="loud"),
])
def test_bad_views_fail_both_checks(mutate):
    v = example()
    mutate(v)
    assert list(VALIDATOR.iter_errors(v)), "the schema should refuse it"
    assert check_view(v) is None


def test_unknown_block_type_is_skipped_not_fatal():
    v = example()
    v["blocks"].insert(1, {"type": "hologram", "x": 1})
    out = check_view(v)
    assert out and all(b["type"] != "hologram" for b in out["blocks"]) and len(out["blocks"]) == len(example()["blocks"])


def test_only_active_add_ons_with_known_icons(ws, fake_orch):
    names = [a["name"] for a in load_addons(ws, str(fake_orch))]
    assert names == ["scheduler"]  # wiki is installed but not active here
    assert load_state(ws, orch_bin=str(fake_orch))["addons"][0]["dashboard"]["label"] == "Schedule"
    assert load_addons(ws, None) == [] and load_addons(ws, "/nonexistent/orch") == []


def test_pull_ok_stale_error(ws, fake_orch):
    p = ViewPuller(ws, str(fake_orch), timeout=1.0)
    mode = fake_orch.parent / "mode.txt"
    mode.write_text("fail")
    r = p.pull("scheduler")
    assert r["state"] == "error" and r["view"] is None and r["message"]
    mode.write_text("ok")
    r = p.pull("scheduler")
    assert r["state"] == "ok" and r["as_of"] == "2026-11-05T08:00:03Z"
    for bad in ("slow", "fail", "junk", "big"):
        mode.write_text(bad)
        r = p.pull("scheduler")
        assert r["state"] == "stale" and r["view"] == check_view(example()) and r["message"], bad


def test_invalid_view_never_replaces_last_good(ws, fake_orch):
    p = ViewPuller(ws, str(fake_orch))
    assert p.pull("scheduler")["state"] == "ok"
    v = copy.deepcopy(example())
    v["blocks"][0]["label"] = "<script>"
    (fake_orch.parent / "view.json").write_text(json.dumps(v))
    r = p.pull("scheduler")
    assert r["state"] == "stale" and "<script>" not in json.dumps(r["view"])


def test_no_orch_command_is_an_error_state(ws):
    assert ViewPuller(ws, None).pull("scheduler")["state"] == "error"


def _script(fake_orch, body):
    fake_orch.write_text(f"#!{sys.executable}\nimport sys, time, os, subprocess\n" + body)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def test_timeout_kills_the_whole_process_group(ws, fake_orch):
    pidfile = fake_orch.parent / "child.pid"
    _script(fake_orch, f"""
c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open({str(pidfile)!r}, "w").write(str(c.pid))
time.sleep(60)
""")
    r = ViewPuller(ws, str(fake_orch), timeout=0.5).pull("scheduler")
    assert r["state"] == "error" and "too long" in r["message"]
    pid = int(pidfile.read_text())
    for _ in range(20):
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid), "orphaned child survived"


def test_output_is_capped_while_reading(ws, fake_orch):
    _script(fake_orch, """
while True:
    sys.stdout.write("a" * 65536); sys.stdout.flush()
""")
    t0 = time.time()
    r = ViewPuller(ws, str(fake_orch), timeout=5).pull("scheduler")
    assert r["state"] == "error" and "too large" in r["message"] and time.time() - t0 < 3  # killed at the cap, not at the timeout


def test_one_pull_in_flight_per_add_on(ws, fake_orch):
    counter = fake_orch.parent / "runs.txt"
    _script(fake_orch, f"""
open({str(counter)!r}, "a").write("x")
time.sleep(0.6)
print(open({str(fake_orch.parent / "view.json")!r}).read())
""")
    p = ViewPuller(ws, str(fake_orch), timeout=3)
    with ThreadPoolExecutor(5) as ex:
        results = list(ex.map(lambda _: p.pull("scheduler"), range(5)))
    assert all(r["state"] == "ok" for r in results)
    assert counter.read_text() == "x"
