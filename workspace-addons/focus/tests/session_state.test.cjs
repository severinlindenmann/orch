const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* Draw the Focus feed for one view with a tiny fake store; return all visible text. */
function feedText(v) {
  const h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), append(...k) { this.kids.push(...k); }, addEventListener() {}});
  const text = n => !n || typeof n !== 'object' ? '' : [n.attrs.text || '', ...n.kids.map(text)].join(' ');
  let drawn = [];
  const els = {agent: {textContent: 'Claude'}, feed: {classList: {toggle() {}}, contains: () => false, querySelectorAll: () => [], replaceChildren: (...k) => { drawn = k; }}};
  const ctx = vm.createContext({document: {activeElement: null}, window: {}});
  ctx.globalThis = ctx;
  const S = {state: {}, views: {}, register: (n, m) => { S.views[n] = m; }, h, els, keyOf: JSON.stringify, plainNames: s => s, hhmm: () => '', evText: () => '', STATUS_WORD: {}};
  ctx.window.FocusStore = S;
  for (const name of ['helpers', 'live']) {
    const file = path.join(__dirname, '../src/orch_focus/web', name + '.js');
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  }
  S.views.live.renderFeed(v);
  return drawn.map(text).join(' ');
}

const view = (state, running) => ({
  state, done: 1, total: 1, events: [], record_notes: [],
  run: {running, run: 'r1', label: 'Claude'}, board: {step: ''},
  ticket: {status: 'active', started: true, questions: [], history: [], checklist: [{id: 'c1', text: 'Write it', done: true}]},
});

test('a paused live session reads Paused everywhere, never as starting work', () => {
  const t = feedText(view('waiting', true));
  assert.match(t, /Paused/);
  assert.doesNotMatch(t, /taking shape/);
  assert.doesNotMatch(t, /Waiting for the first step/);
  assert.match(t, /1 of 1 tasks finished/);
});

test('a stopped started session reads Paused; a working one still shows the waiting row', () => {
  assert.match(feedText(view('stopped', false)), /^ *Paused/);
  const w = feedText(view('working', true));
  assert.match(w, /The work is taking shape/);
  assert.match(w, /Waiting for the first step/);
});
