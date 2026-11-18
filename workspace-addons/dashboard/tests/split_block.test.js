'use strict';
// List and panel (split block, ORCH-326): choosing an item keeps an address and shows only its panel; the phone's
// "All services" goes back to the list; Remove says what happens in the shared dialog with Keep it, no typed word.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');

// A small DOM: enough for blocks.js to build a split block and for splitPick to walk it.
const camel = k => k.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.className = ''; this.dataset = {}; this.attrs = {}; this.kids = []; this.text = ''; this.hidden = false; this.style = {}; }
  get classList() { const self = this; return {
    contains: c => self.className.split(' ').includes(c),
    toggle: (c, on) => { const s = new Set(self.className.split(' ').filter(Boolean)); if (on) s.add(c); else s.delete(c); self.className = [...s].join(' '); },
  }; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  set textContent(v) { this.text = String(v); this.kids = []; }
  get textContent() { return this.text + this.kids.map(k => k.textContent).join(''); }
  set href(v) { this.attrs.href = v; } set type(v) { this.attrs.type = v; }
  append(...c) { for (const x of c) this.kids.push(typeof x === 'string' ? Object.assign(new El('#text'), {text: x}) : x); }
  get childNodes() { return this.kids; }
  focus() { focused = this; }
  all() { return this.kids.flatMap(k => [k, ...k.all()]); }
  matches(sel) {
    return sel.split(/(?=[.[])/).every(part => part.startsWith('.') ? this.classList.contains(part.slice(1))
      : part.startsWith('[') ? Object.prototype.hasOwnProperty.call(this.dataset, camel(part.slice(1, -1))) : this.tagName === part.toUpperCase());
  }
  querySelectorAll(sel) {
    const [first, ...rest] = sel.trim().split(/\s+/);
    let found = this.all().filter(n => n.matches(first));
    for (const s of rest) found = found.flatMap(n => n.all().filter(m => m.matches(s)));
    return [...new Set(found)];
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
let focused = null, address = '#addon/services';
global.document = {createElement: t => new El(t), createElementNS: (_, t) => new El(t), createDocumentFragment: () => new El('#frag')};
global.location = {get hash() { return address; }};
global.history = {replaceState: (_, __, u) => { address = u; }};
global.matchMedia = () => ({matches: false});
const B = require('../src/orch_dashboard/web/blocks.js');
const page = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../contracts/examples/addon-view/valid-services-page.json'), 'utf8'));
const draw = () => B.render(page.blocks, {self: 'services'}).kids[0];
const shown = s => s.querySelectorAll('[data-split-panel]').filter(p => !p.hidden).map(p => p.dataset.splitPanel);
const current = s => s.querySelectorAll('[data-split-row]').filter(r => r.classList.contains('cur')).map(r => r.dataset.splitRow);

test('choosing an item shows only its panel, marks its row and keeps the address', () => {
  address = '#addon/services';
  const s = draw();
  assert.deepEqual(shown(s), ['budget-guard']);
  B.splitPick(s, 'web-preview');
  assert.equal(address, '#addon/services?svc=web-preview');
  assert.deepEqual(shown(s), ['web-preview']);
  assert.deepEqual(current(s), ['web-preview']);
  assert.equal(s.querySelector('.split-view').dataset.picked, 'true');
  assert.equal(focused.dataset.splitPanel, 'web-preview');
  const a = s.querySelectorAll('[data-split-row]').find(r => r.dataset.splitRow === 'web-preview').querySelector('[data-split-pick]');
  assert.equal(a.getAttribute('aria-current'), 'true');
});

test('the address opens the same item again, and All services goes back to the list', () => {
  address = '#addon/services?svc=dashboard-front';
  const s = draw();
  assert.deepEqual(shown(s), ['dashboard-front']);
  assert.equal(s.querySelector('.split-view').dataset.picked, 'true');
  B.splitPick(s, '');
  assert.equal(address, '#addon/services');
  assert.equal(s.querySelector('.split-view').dataset.picked, undefined);
  assert.equal(focused.dataset.splitPick, 'dashboard-front');   // back on the list, on the row it came from
});

test('an unknown item in the address or in a click changes nothing', () => {
  address = '#addon/services?svc=nope';
  const s = draw();
  assert.deepEqual(shown(s), ['budget-guard']);
  B.splitPick(s, 'not-there');
  assert.equal(address, '#addon/services?svc=nope');
  assert.deepEqual(shown(s), ['budget-guard']);
});

test('the page sends picks and Open log to blocks.js before any add-on action', () => {
  const app = web('app.js');
  const i = app.indexOf("closest('[data-split-pick]')"), j = app.indexOf("closest('[data-addon-act]')");
  assert.ok(i > 0 && j > i);
  assert.match(app, /OrchBlocks\.splitPick\(pick\.closest\('\.blk-split'\), pick\.dataset\.splitPick\)/);
  assert.match(app, /OrchBlocks\.splitLogShow\(showLog\.closest\('\.blk-split'\), showLog\.dataset\.splitLog\)/);
});

test('Remove says what happens with Keep it and its own word, never a typed word', () => {
  const settings = web('pages/settings.js');
  const body = settings.slice(settings.indexOf('async function addonAct('), settings.indexOf('async function addonReview('));
  assert.match(body, /control\.dataset\.confirmLines\.split\('\\n'\)/);
  assert.match(body, /'This is what happens:'/);
  assert.match(body, /actions\.firstChild\.textContent = control\.dataset\.keep \|\| 'Keep it'/);
  assert.match(body, /button\(control\.dataset\.label \|\| 'Yes', 'danger'/);
  assert.doesNotMatch(body, /<input|type=['"]text/);
  assert.match(body, /act_answer\?\.addon === id/);   // the toast uses only the open add-on's own answer
});
