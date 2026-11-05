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
