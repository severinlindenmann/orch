const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../src/orch_focus/web/helpers.js');

const web = name => fs.readFileSync(path.join(__dirname, '../src/orch_focus/web', name), 'utf8');

test('dash21/32: the row shows the next step only when it says more than the action chip', () => {
  assert.equal(H.nextStepText({next_step: 'Answer'}, 'Answer'), '');
  assert.equal(H.nextStepText({}, 'Start'), '');
  assert.equal(H.nextStepText({next_step: 'Which greeting?'}, 'Answer'), 'Which greeting?');
});

test('dash32: a group shows five rows and the rest behind Show all', () => {
  const rows = Array.from({length: 24}, (_, i) => i);
  assert.deepEqual(H.limitGroup(rows), {shown: [0, 1, 2, 3, 4], more: 19});
  assert.equal(H.limitGroup([1, 2]).more, 0);
  const src = web('ticket.js');
  assert.match(src, /Show all \(/);
  assert.match(src, /fx-row-chip/);
  assert.doesNotMatch(src, /row-action/);
});

test('dash30: Results counts tasks, the same unit as the task count', () => {
  const checklist = [{done: true, evidence: [{}, {}, {}]}, {done: false, evidence: [{}]}, {done: true, wont_do: true, evidence: [{}]}];
  assert.equal(H.resultCount(checklist), 1);
  const src = web('ticket.js') + web('used.js');
  assert.match(src, /'What it read'/);
  assert.doesNotMatch(src, /\['used', 'Used'\]/);
  assert.match(src, /showTab\(3, rows\.length > 0\)/);  // empty tabs are hidden
});

test('dash33/07: no "all at once" line; Back to Home and Create a ticket are offered', () => {
  const src = web('ticket.js');
  assert.doesNotMatch(src, /all at once/);
  assert.match(src, /Back to Home/);
  assert.match(src, /Create a ticket/);
  assert.doesNotMatch(src, /'Focus \/ '/);
});

test('dash07/09: one 48px header row like the dashboard; current step in the accent colour', () => {
  const css = web('focus.css');
  assert.doesNotMatch(css, /\.fx-top\{min-height:100px/);
  assert.match(css, /\.fx-top\{flex-wrap:nowrap!important;height:48px/);
  assert.match(css, /\.fx-stepper \[aria-current\]\{color:var\(--brand\)/);
  assert.match(web('ticket.js'), /fx-stepbar'\}, els\.steps, els\.liveWrap/);
});

test('dash24: no vendor name; the composer only has the placeholder', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.match(src, /'Write a message…'/);
  assert.doesNotMatch(src, /messageLabel/);
  assert.match(web('focus.js'), /els\.agent\.textContent = 'Helper'/);
});

test('dash26: Pause work / Continue and a Back to list arrow', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.match(src, /'Pause work'/);
  assert.doesNotMatch(src, /'Stop'|'Exit'|icon: 'x'/);
  assert.match(src, /Back to list/);
});

test('dash27: a fixed menu: greyed when n/a, desktop rows hidden on phones, Start fresh confirmed', () => {
  const t = web('ticket.js'), f = web('focus.js'), css = web('focus.css');
  assert.match(f, /els\.fresh\.disabled = /);
  assert.match(f, /els\.attachBtn\.disabled = /);
  assert.doesNotMatch(f, /els\.(fresh|attachBtn)\.hidden/);
  assert.match(t, /Technical details'\}\), els\.attachBtn/);
  assert.match(t, /fx-menu-divider/);
  assert.match(f, /Click again to start fresh/);
  assert.match(css, /\.fx-action-menu \.fx-desktop\{display:none\}/);
});

test('dash28: no phone switch in Focus', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.doesNotMatch(src, /phoneInput|Send questions to my phone|mobile\.set/);
});

test('dash56: one full-width Add a task field, Enter submits, 44px tall', () => {
  const t = web('ticket.js'), css = web('focus.css');
  assert.doesNotMatch(t + web('focus.js'), /addToggle|'data-act': 'add-task'|fx-adding/);
  assert.match(t, /fx-add-task', id: 'fx-add-task'\}, els\.addInput\)/);
  assert.match(css, /\.fx-add-task \.input\{width:100%;height:44px/);
});

/* ---- behaviour: the real ticket.js + focus.js wired on a tiny fake DOM ---- */
const vm = require('node:vm');
function fakeEl(name, act) {
  const on = {}, cls = new Set(), attrs = {};
  const e = {
    name, hidden: false, disabled: false, dataset: act ? {act} : {}, style: {setProperty() {}}, textContent: '', kids: [],
    lastElementChild: {textContent: ''},
    classList: {toggle(c, f) { f = f === undefined ? !cls.has(c) : f; if (f) cls.add(c); else cls.delete(c); return f; }, contains: c => cls.has(c), add: c => cls.add(c), remove: c => cls.delete(c)},
    addEventListener(t, f) { (on[t] = on[t] || []).push(f); }, fire(t, ev) { (on[t] || []).forEach(f => f(ev)); },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: k => (k in attrs ? attrs[k] : null),
    focus() {}, click() { e.fire('click', {target: e}); }, contains: x => x === e || e.kids.includes(x),
    closest: sel => (sel === '[data-act]' ? (e.dataset.act ? e : null) : sel === 'button' ? e : null),
    querySelector: () => fakeEl(), querySelectorAll: () => [], getBoundingClientRect: () => ({left: 0, right: 100}),
  };
  return e;
}
function focusPage() {
  const calls = [], docOn = {};
  const store = {};
  const els = new Proxy(store, {get: (t, k) => (k in t ? t[k] : (t[k] = fakeEl(String(k))))});
  els.tabs = [0, 1, 2, 3].map(i => { const b = fakeEl('tab' + i); b.setAttribute('aria-selected', String(i === 0)); return b; });
  els.fresh = fakeEl('fresh', 'fresh'); els.attachBtn = fakeEl('attach', 'attach'); els.help.hidden = true;
  els.menu.kids.push(els.fresh, els.attachBtn);
  const root = fakeEl('root');
  const S = {root, TID: 't_1', P: '', INAPP: true, els, h: () => fakeEl(), ic: () => '', toast() {}, act: async () => ({ok: true}),
    proof: {isOpen: () => false}, keyOf: JSON.stringify, state: {firstRender: true, tab: 0}, views: {}, register: (n, m) => { S.views[n] = m; }};
  S.views.live = {startFresh: () => calls.push('fresh'), stopToggle() {}, focusQuestion() {}};
  S.views.session = {showAttach: () => calls.push('attach')};
  const ctx = vm.createContext({
    window: {FocusStore: S, addEventListener() {}}, matchMedia: () => ({matches: false, addEventListener() {}}), innerWidth: 1000,
    document: {addEventListener(t, f) { (docOn[t] = docOn[t] || []).push(f); }, getElementById: () => Object.assign(fakeEl(), {hidden: true}), hidden: true}, location: {hash: ''},
    fetch: () => new Promise(() => {}), setTimeout: () => 0, clearTimeout() {}, CSS: {escape: s => s},
  });
  ctx.globalThis = ctx;
  for (const name of ['helpers', 'ticket']) vm.runInContext(web(name + '.js'), ctx);
  S.views.ticket.build = () => {};
  vm.runInContext(web('focus.js'), ctx);
  const doc = (t, ev) => (docOn[t] || []).forEach(f => f(ev));
  return {S, els, calls, click: el => root.fire('click', {target: el}), doc};
}

test('dash27: Start fresh needs two clicks, and closing the menu disarms it', () => {
  const p = focusPage();
  p.click(p.els.fresh);
  assert.deepEqual(p.calls, []);
  assert.ok(p.els.fresh.classList.contains('fx-confirm'));
  p.doc('click', {target: fakeEl('outside')});  // the menu closes
  assert.ok(!p.els.fresh.classList.contains('fx-confirm'));
  p.click(p.els.fresh);
  assert.deepEqual(p.calls, []);
  p.click(p.els.fresh);
  assert.deepEqual(p.calls, ['fresh']);
});

test('dash27: a greyed-out row does nothing even when its click gets through', () => {
  const p = focusPage();
  p.els.fresh.disabled = true; p.els.attachBtn.disabled = true;
  p.click(p.els.fresh); p.click(p.els.fresh); p.click(p.els.attachBtn);
  assert.deepEqual(p.calls, []);
  p.els.attachBtn.disabled = false;
  p.click(p.els.attachBtn);
  assert.deepEqual(p.calls, ['attach']);
});

test('dash30: hiding the open tab falls back to Live; a hidden tab cannot be picked with 1-4', () => {
  const p = focusPage();
  const key = k => p.doc('keydown', {key: k, target: fakeEl(), preventDefault() {}});
  key('3');
  assert.equal(p.S.state.tab, 2);
  p.els.tabs[2].setAttribute('aria-selected', 'true');
  p.S.views.ticket.showTab(2, false);
  assert.equal(p.els.tabs[2].hidden, true);
  assert.equal(p.S.state.tab, 0);
  key('3');
  assert.equal(p.S.state.tab, 0);
  p.S.views.ticket.showTab(2, true);
  key('3');
  assert.equal(p.S.state.tab, 2);
});

test('dash07: on a phone Back to list stays first in the header; only Pause and ••• move to the end', () => {
  const css = web('focus.css');
  for (const rule of css.match(/[^{}]*\{order:[1-9]\}/g) || []) assert.doesNotMatch(rule, /fx-exit/);
  assert.doesNotMatch(css, /fx-add-toggle|fx-adding/);
  assert.match(css, /\.fx-top \.btn,\.fx-mobile-tasks,\.fx-tech summary,\.fx-action-menu button\{min-height:44px/);
});

test('dash24: the vendor name is not shown on the helper row or in Results', () => {
  assert.match(web('used.js'), /'Main helper'/);
  assert.doesNotMatch(web('used.js') + web('ticket.js'), /'Main agent'|setAgent\(v\.run\.label\)/);
});

test('dash33: outside the app the empty state does not link back to the same page', () => {
  assert.match(web('ticket.js'), /INAPP \? h\('div', \{class: 'row'\}, h\('a', \{class: 'btn primary sm', href: '\/#new'/);
});
