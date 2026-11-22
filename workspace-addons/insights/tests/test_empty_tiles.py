"""Stat tiles: a number only when it is measured, else "Not measured yet" (ORCH-72). First day: the tiles at 0 with
one plain line, not one big empty box."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "src/orch_insights/web/insights.js"
RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function metric');
const end = src.indexOf('\nfunction fillMetrics', start);
if (start < 0 || end < 0) { console.log(JSON.stringify({missing: true})); process.exit(0); }
const el = (tag) => ({tag, cls: '', children: [], append(...k) { this.children.push(...k); }, set textContent(t) { this.children = [String(t)]; }});
const node = (tag, text, cls) => { const e = el(tag); if (text !== undefined) e.textContent = text; if (cls) e.cls = cls; return e; };
const text = n => typeof n === 'string' ? n : n.children.map(text).join('|');
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const ctx = vm.createContext({node, plural});
vm.runInContext(src.slice(start, end), ctx);
const view = JSON.parse(process.argv[2]);
console.log(JSON.stringify({tiles: vm.runInContext('emptyTiles(' + JSON.stringify(view) + ',' + process.argv[3] + ')', ctx).map(text),
  services: text(vm.runInContext('servicesTile(' + JSON.stringify(view) + ')', ctx))}));
"""


def run(connections, team=None):
    view = json.dumps({"tabs": {"connections": connections}})
    data = json.loads(
        subprocess.run(
            ["node", "-e", RUNNER, str(JS), view, json.dumps(team)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert not data.get("missing"), (
        "insights.js needs metric(), servicesTile() and emptyTiles() before fillMetrics()"
    )
    return data


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_first_day_shows_two_tiles():
    tiles = run({"count": 0, "known": True})["tiles"]
    assert len(tiles) == 2
    runs, services = tiles
    # no recorded run is "not measured", never a 0 (the record can be empty while helpers worked)
    assert "Times helpers worked" in runs and "Not measured yet" in runs and "|0|" not in runs + "|"
    assert "No helper runs are recorded here yet" in runs
    assert "Connected services" in services and "|0|" in services + "|"
    assert "Fills after the first helper run" in services


def test_orch_is_lower_case_mid_sentence():
    js = JS.read_text()
    assert "'orch can’t see this list yet'" in js and "'Orch can" not in js


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_unmeasured_services_show_no_number():
    data = run({"count": 0, "known": False})
    for tile in (data["tiles"][1], data["services"]):
        assert "Not measured yet" in tile and "|0|" not in tile + "|"
    # services seen in use are a true count even when the full list is unknown: one number, never "Not measured yet"
    used = run({"count": 2, "known": False})["services"]
    assert (
        used.startswith("Connected services|2|")
        and "Not measured yet" not in used
        and "there may be more" in used
    )


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_measured_services_show_the_count():
    assert run({"count": 3, "known": True})["services"].startswith(
        "Connected services|3|Used by your helpers"
    )


MODELS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function modelsEmptyText');
const end = src.indexOf('\nfunction renderModels', start);
if (start < 0 || end < 0) { console.log(JSON.stringify({missing: true})); process.exit(0); }
const ctx = vm.createContext({});
vm.runInContext(src.slice(start, end), ctx);
const [view, runs] = JSON.parse(process.argv[2]);
console.log(JSON.stringify({text: vm.runInContext('modelsEmptyText(' + JSON.stringify(view) + ',' + JSON.stringify(runs) + ')', ctx)}));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_runs_without_tokens_never_say_no_model_use():
    """ORCH-232: 5 runs recorded but no tokens must not read "No model use in the last 30 days"."""

    def text(runs):
        out = subprocess.run(
            [
                "node",
                "-e",
                MODELS,
                str(JS),
                json.dumps([{"empty": True, "text": "No model use in the last 30 days."}, runs]),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        data = json.loads(out)
        assert not data.get("missing"), "insights.js needs modelsEmptyText() right before renderModels()"
        return data["text"]

    assert text(5) == "Token use isn’t recorded for these runs yet."
    assert text(0) == "No model use in the last 30 days."


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_tile_does_not_contradict_the_helper_time_shown_above():
    """ORCH-410: no run is recorded but the tickets show helper time: the tile says where that time comes from."""
    tile = run({"count": 0, "known": True}, {"time": "88 h 28 min"})["tiles"][0]
    assert "No helper runs are recorded" not in tile and "helper time above" in tile
    assert "No helper runs are recorded" in run({"count": 0, "known": True}, {"time": "–"})["tiles"][0]


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_tile_says_runs_orch_started_are_not_measured():
    """ORCH-966: a custom helper writes no record lines; orch still started runs: not "No helper runs"."""
    view = json.dumps({"started": 4, "tabs": {"connections": {"count": 0, "known": True}}})
    out = json.loads(
        subprocess.run(
            ["node", "-e", RUNNER, str(JS), view, json.dumps({"time": "–"})],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    tile = out["tiles"][0]
    assert "orch started 4 runs" in tile and "not measured" in tile and "No helper runs" not in tile
