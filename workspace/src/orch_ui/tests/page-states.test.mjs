import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// Dashboard decisions D4-D6 (26 Nov, owner picked A): one empty page, one notice, one Settings button, from the master.
const read = f => readFileSync(new URL('../static/' + f, import.meta.url), 'utf8');
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.className = ''; this.own = ''; }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this.own = ''; }
  append(...c) { c.forEach(x => this.children.push(typeof x === 'string' ? Object.assign(new N('#text'), {own: x}) : x)); }
  setAttribute(k, v) { this.attrs[k] = v; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
}
function load() {
  const UI = {};
  const document = {createElement: t => new N(t), createElementNS: (_, t) => new N(t), createTextNode: v => Object.assign(new N('#text'), {own: String(v)})};
  vm.runInNewContext(read('widgets.js'), {window: {UI}, document, Node: N, setTimeout, clearTimeout, console});
  return UI;
}

test('pageEmpty: what is missing, one sentence, and the first step only where there is one', () => {
  const UI = load();
  const helper = UI.pageEmpty({title: 'No lessons yet', text: 'Your helper adds a lesson. Nothing to do for you.'});
  assert.equal(helper.className, 'card page-empty');
  assert.deepEqual(helper.children.map(c => c.tag), ['h2', 'p'], 'no button where the helper fills the page');
  const start = UI.pageEmpty({title: 'All clear', text: 'Questions show up here.', step: {label: 'New ticket', href: '#new'}, dataKey: 'empty'});
  const step = start.children[2];
  assert.equal(step.className, 'page-empty-step');
  assert.equal(step.children[0].className, 'btn primary sm');
  assert.equal(step.children[0].href, '#new');
  assert.equal(start.dataset.key, 'empty');
  const own = new N('div');
  assert.equal(UI.pageEmpty({title: 'x', step: own}).children[1].children[0], own, "the page's own input is the step");
});

test('pageNotice: what happened in bold, what still works, one green button; error tone is an alert', () => {
  const UI = load();
  const n = UI.pageNotice({what: 'Factory has stopped.', still: 'Your tickets still work.', action: {label: 'Start Factory', data: {action: 'start'}}});
  assert.equal(n.className, 'banner page-notice attn');
  assert.equal(n.attrs.role, 'status');
  assert.equal(n.children[0].children[0].tag, 'strong');
  assert.equal(n.children[0].textContent, 'Factory has stopped. Your tickets still work.');
  assert.equal(n.children[1].className, 'btn primary sm');
  assert.equal(n.children[1].dataset.action, 'start');
  const e = UI.pageNotice({tone: 'error', what: 'Can’t show it.'});
  assert.equal(e.className, 'banner page-notice error');
  assert.equal(e.attrs.role, 'alert');
  assert.equal(e.children.length, 1);
});

test('settingsButton: gear and the word Settings, outline, to the add-on settings', () => {
  const UI = load();
  const b = UI.settingsButton({href: '#settings/addons/automation', dataKey: 'addon-settings'});
  assert.equal(b.tag, 'a');
  assert.equal(b.className, 'btn outline sm page-settings settings-btn');
  assert.equal(b.href, '#settings/addons/automation');
  assert.equal(b.textContent.trim(), 'Settings');
  assert.equal(b.dataset.key, 'addon-settings');
});
