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
console.log(JSON.stringify({tiles: vm.runInContext('emptyTiles(' + JSON.stringify(view) + ')', ctx).map(text),
  services: text(vm.runInContext('servicesTile(' + JSON.stringify(view) + ')', ctx))}));
"""


def run(connections):
    view = json.dumps({"tabs": {"connections": connections}})
    data = json.loads(
        subprocess.run(
            ["node", "-e", RUNNER, str(JS), view], capture_output=True, text=True, check=True
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
    used = run({"count": 2, "known": False})["services"]
    assert "Not measured yet" in used and "2 services used by your helpers" in used


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_measured_services_show_the_count():
    assert run({"count": 3, "known": True})["services"].startswith(
        "Connected services|3|Used by your helpers"
    )
