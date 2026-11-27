"""ORCH-1692: the Skills list shows plain names, a skill that needs a look shows no green switch, one count per tab.

The page script runs in node with a tiny stand-in DOM (no browser) on a sample answer of `api/page`."""

import json
import shutil
import subprocess
from importlib import resources

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

DOM = r"""
const vm = require('node:vm');
class N {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.className = ''; this.hidden = false; this._t = ''; }
  set textContent(v) { this._t = String(v); this.kids = []; }
  get textContent() { return this._t + this.kids.map(k => typeof k === 'string' ? k : k.textContent).join(''); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener() {}
  append(...k) { this.kids.push(...k); }
  replaceChildren(...k) { this.kids = k; }
  all() { return [this, ...this.kids.flatMap(k => typeof k === 'string' ? [] : k.all())]; }
}
const ids = {};
const document = {createElement: t => new N(t), getElementById: id => (ids[id] = ids[id] || new N('div')),
  documentElement: {dataset: {}}};
const model = JSON.parse(process.argv[1]);
const ctx = {document, window: {}, location: {href: 'http://x/', search: '', origin: 'http://x'}, history: {replaceState() {}},
  addEventListener() {}, URL, URLSearchParams, crypto: globalThis.crypto, setTimeout, clearTimeout, console,
  fetch: async () => ({ok: true, json: async () => model})};
ctx.window.parent = ctx.window;
vm.createContext(ctx);
vm.runInContext(require('node:fs').readFileSync(process.argv[2], 'utf8'), ctx);
setTimeout(() => {
  const nodes = ids.loaded.all();
  const rows = nodes.filter(n => n.tag === 'tr' && n.attrs.tabindex === '0');
  process.stdout.write(JSON.stringify({
    tabs: nodes.filter(n => n.attrs.role === 'tab').map(n => n.textContent),
    filters: nodes.filter(n => n.tag === 'button' && n.attrs['aria-pressed']).map(n => n.textContent),
    rows: rows.map(r => ({name: r.attrs['aria-label'], text: r.textContent, switch: r.all().some(n => n.attrs.role === 'switch')})),
  }));
}, 50);
"""


def _skill(name, description, problems=()):
    return {"id": "skill:mine:" + name, "kind": "skill", "name": name, "where": "mine", "on": True,
            "can_off": True, "description": description, "problems": list(problems)}  # fmt: skip


def test_the_list_says_plain_names_hides_a_broken_switch_and_counts_once():
    page = {
        "skills": [
            _skill("claude-api-credit", "Check the credit left (codex:codex-rescue, /codex:review) before a run."),
            _skill("pass-tool", "Read a password.", ["Not ready here: a program it needs is not installed (pass-cli)"]),
        ]
    }
    js = str(resources.files("orch_skills").joinpath("web", "skills.js"))
    out = subprocess.run(
        ["node", "-e", DOM, json.dumps(page), js], check=False, capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    by = {r["name"]: r for r in got["rows"]}
    assert set(by) == {"Claude API credit", "Pass tool"}
    assert (
        "codex:" not in by["Claude API credit"]["text"]
        and "Check the credit left before a run." in by["Claude API credit"]["text"]
    )
    assert by["Claude API credit"]["switch"] is True
    assert by["Pass tool"]["switch"] is False  # Needs a look: no switch that looks on
    assert got["tabs"][0] == "Skills 2"  # one number, not "Skills 2 1"
    assert "Needs a look (1)" in got["filters"]


def _run(page):
    js = str(resources.files("orch_skills").joinpath("web", "skills.js"))
    out = subprocess.run(
        ["node", "-e", DOM, json.dumps(page), js], check=False, capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return {r["name"]: r for r in json.loads(out.stdout)["rows"]}


def test_names_keep_their_spelling_and_the_line_is_one_plain_sentence():
    """Report r-1127-0540-ws: 'Github links', 'Openai api credit' and helper instructions as the description."""
    workspace_copy = (
        "(Workspace copy of the shipped orch-github skill; orch installs it only with a GitHub remote.) "
        "Link GitHub issues and pull requests to tickets. Keep their state current."
    )
    by = _run(
        {
            "skills": [
                _skill("github-links", workspace_copy),
                _skill("openai-api-credit", "Use when the owner says use openai (or GPT API) for a task. More text."),
                _skill("orch-ux-checklist", "Use for ANY orch UI work, a new page or a state."),
                _skill("constructor", "A skill whose name is also a word of every script object."),
            ]
        }
    )
    assert set(by) == {"GitHub links", "OpenAI API credit", "orch UX checklist", "Constructor"}
    assert "Link GitHub issues and pull requests to tickets." in by["GitHub links"]["text"]
    assert "Workspace copy" not in by["GitHub links"]["text"] and "Keep their" not in by["GitHub links"]["text"]
    assert "When the owner says use openai for a task." in by["OpenAI API credit"]["text"]
    assert "Use when" not in by["OpenAI API credit"]["text"]
    assert "For any orch UI work, a new page or a state." in by["orch UX checklist"]["text"]


def test_a_second_copy_is_named_on_the_row():
    mine = _skill("orch-mockup", "How a mockup is built.")
    ws = dict(_skill("orch-mockup", "How a mockup is built here."), id="skill:workspace:orch-mockup", where="workspace")
    mine["copy"], ws["copy"] = "A different copy is also in this workspace", "A different copy is also on your computer"
    js = str(resources.files("orch_skills").joinpath("web", "skills.js"))
    out = subprocess.run(
        ["node", "-e", DOM, json.dumps({"skills": [mine, ws]}), js],
        check=False, capture_output=True, text=True, timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    texts = [r["text"] for r in json.loads(out.stdout)["rows"]]
    assert len(texts) == 2
    assert any("also on your computer" in t for t in texts) and any("also in this workspace" in t for t in texts)
