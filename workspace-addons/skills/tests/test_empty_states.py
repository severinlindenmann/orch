"""Every empty list on the Skills page is the master empty state with one next step (R7.2, SX-10): a search that
finds nothing offers Clear search, a filter that shows nothing offers Show all, an empty Bin goes to Skills, and an
empty tab names where its rows come from."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "src/orch_skills/web/skills.js"
# The real page in a tiny DOM: UI.state records the last empty state the page asked for.
RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const [file, model, tab, show, query] = process.argv.slice(1);
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.className = ''; this.hidden = false; this.value = ''; this.on = {}; }
  append(...k) { this.children.push(...k); }
  replaceChildren(...k) { this.children = k; }
  replaceWith() {}
  setAttribute(k, v) { this.attrs[k] = v; if (k === 'id') ids[v] = this; }
  addEventListener(t, f) { this.on[t] = f; }
  focus() {}
  set textContent(t) { this.text = String(t); }
}
const ids = {};
const document = {documentElement: new N('html'), body: new N('body'), createElement: t => new N(t),
  getElementById: id => ids[id] || (ids[id] = new N('div')), querySelector: () => null};
let shown = null;
const UI = {state: o => { shown = o; return new N('div'); }, stamp: x => x, toast() {}};
const window = {UI};
window.parent = window;
const search = 'tab=' + tab + (show ? '&show=' + show : '');
const ctx = vm.createContext({document, window, location: {search: '?' + search, href: 'http://x/?' + search, origin: 'http://x'},
  history: {replaceState() {}, state: null}, URL, URLSearchParams, addEventListener() {}, console, setTimeout,
  fetch: async () => ({ok: true, json: async () => JSON.parse(model)})});
vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
setTimeout(() => {
  if (query) {
    const find = (n) => n && (n.attrs && n.attrs.type === 'search' ? n : (n.children || []).map(find).find(Boolean));
    const box = find(ids.loaded); box.value = query; box.on.input();
  }
  console.log(JSON.stringify({first: shown && {title: shown.title, text: shown.text, action: shown.action && shown.action.label}}));
}, 20);
"""


def page(model, tab="skills", show="", query=""):
    out = subprocess.run(
        ["node", "-e", RUNNER, str(JS), json.dumps(model), tab, show, query],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["first"]


SKILL = {"id": "skill:workspace:release", "kind": "skill", "where": "workspace", "name": "release", "on": True}
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node missing")


def test_a_search_that_finds_nothing_offers_clear_search():
    got = page({"skills": [SKILL]}, query="zzz")
    assert got["title"] == "Nothing matches “zzz”" and got["action"] == "Clear search"


def test_a_filter_that_shows_nothing_offers_show_all():
    got = page({"skills": [SKILL]}, show="off")
    assert got["title"] == "Nothing is off" and got["action"] == "Show all"
    assert page({"skills": [SKILL]}, show="needs")["title"] == "Nothing needs a look"


def test_an_empty_tab_says_where_rows_come_from_and_has_one_step():
    assert page({}, tab="skills")["action"] == "New skill"
    logins = page({}, tab="logins")
    assert "orch secret add" in logins["text"] and logins["action"] == "Look again"
    for tab in ("instructions", "services"):
        assert page({}, tab=tab)["action"] == "Look again"


def test_an_empty_bin_goes_back_to_skills():
    got = page({}, tab="bin")
    assert got["title"] == "The Bin is empty" and got["action"] == "Show skills"
