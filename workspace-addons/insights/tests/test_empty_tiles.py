"""First day (nothing recorded yet): the stat tiles show at 0 with one plain line, not one big empty box."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "src/orch_insights/web/insights.js"
RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function emptyTiles');
if (start < 0) { console.log(JSON.stringify({missing: true})); process.exit(0); }
const end = src.indexOf('\nfunction ', start + 10);
const el = (tag) => ({tag, cls: '', children: [], append(...k) { this.children.push(...k); }, set textContent(t) { this.children = [String(t)]; }});
const node = (tag, text, cls) => { const e = el(tag); if (text !== undefined) e.textContent = text; if (cls) e.cls = cls; return e; };
const text = n => typeof n === 'string' ? n : n.children.map(text).join('|');
const ctx = vm.createContext({node});
vm.runInContext(src.slice(start, end), ctx);
const out = vm.runInContext('emptyTiles({tabs: {connections: {count: 0}}})', ctx);
console.log(JSON.stringify({tiles: out.map(text)}));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_first_day_shows_two_tiles_at_zero():
    out = subprocess.run(["node", "-e", RUNNER, str(JS)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    assert not data.get("missing"), "insights.js needs emptyTiles()"
    tiles = data["tiles"]
    assert len(tiles) == 2
    for tile, label in zip(tiles, ("Times helpers worked", "Connected services"), strict=True):
        assert label in tile and "|0|" in tile + "|"
        assert "Fills after the first helper run" in tile
