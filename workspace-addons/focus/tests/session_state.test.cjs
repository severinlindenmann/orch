const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* A Focus feed drawer with a tiny fake store; each call draws one view and returns all visible text. */
function feedDrawer() {
  const h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), append(...k) { this.kids.push(...k); }, addEventListener() {}});
  const text = n => !n || typeof n !== 'object' ? '' : [n.attrs.text || '', ...n.kids.map(text)].join(' ');
  let drawn = [];
  const els = {agent: {textContent: 'Claude'}, feed: {classList: {toggle() {}}, contains: () => false, querySelectorAll: () => [], replaceChildren: (...k) => { drawn = k; }}};
  const ctx = vm.createContext({document: {activeElement: null}, window: {}});
  ctx.globalThis = ctx;
  const S = {state: {}, views: {}, register: (n, m) => { S.views[n] = m; }, h, els, keyOf: JSON.stringify, plainNames: s => s, hhmm: () => '', evText: () => '', STATUS_WORD: {}};
  ctx.window.FocusStore = S;
  ctx.window.UI = require('./kit_state.cjs');
  for (const name of ['helpers', 'live']) {
    const file = path.join(__dirname, '../src/orch_focus/web', name + '.js');
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  }
  return v => { drawn = []; S.views.live.renderFeed(v); return drawn.map(text).join(' '); };
}
const feedText = v => feedDrawer()(v);
globalThis.UI = require('./kit_state.cjs');
const {sessionState} = require('../src/orch_focus/web/helpers.js');

const view = (state, running) => ({
  state, done: 1, total: 1, events: [], record_notes: [],
  run: {running, run: 'r1', label: 'Claude'}, board: {step: ''},
  ticket: {status: 'active', started: true, questions: [], history: [], checklist: [{id: 'c1', text: 'Write it', done: true}]},
});

test('an idle live session reads Idle (the ticket page word), never as starting work', () => {
  const t = feedText(view('waiting', true));
  assert.match(t, /Idle/);
  assert.doesNotMatch(t, /Paused/);
  assert.doesNotMatch(t, /taking shape/);
  assert.doesNotMatch(t, /Waiting for the first step/);
  assert.match(t, /1 of 1 tasks finished/);
});

test('a stopped started session reads Work so far; a working one still shows the waiting row', () => {
  assert.match(feedText(view('stopped', false)), /^ *Work so far/);
  const w = feedText(view('working', true));
  assert.match(w, /The work is taking shape/);
  assert.match(w, /Waiting for the first step/);
});

test('a needs session reads Work so far once the run is not running', () => {
  assert.equal(sessionState(view('needs', false)).headline, 'Work so far');
  assert.equal(sessionState(view('needs', true)).headline, 'The work is taking shape');
  const t = feedText(view('needs', false));
  assert.match(t, /Work so far/);
  assert.doesNotMatch(t, /taking shape|Waiting for the first step/);
});

test('an idle session: pill Idle, headline Idle, no waiting row (ORCH-71: the ticket page words)', () => {
  const st = sessionState(view('waiting', true));
  assert.equal(st.pill, 'Idle');
  assert.equal(st.headline, 'Idle');
  assert.equal(st.active, false);
  assert.doesNotMatch(feedText(view('waiting', true)), /Waiting for the first step/);
});

test('the feed draws again when the ticket status flips to review', () => {
  const draw = feedDrawer();
  const v = view('waiting', true);
  assert.match(draw(v), /^ *Idle/);
  assert.match(draw({...v, state: 'stopped', run: {...v.run, running: false}, ticket: {...v.ticket, status: 'review'}}), /^ *Work so far/);
});

test('#862: no empty "Before the question" header, and the repeated stop line is not shown', () => {
  const asking = view('needs', false);
  asking.ticket.questions = [{id: 'q1', text: 'Which day?', answer: null}];
  asking.ticket.history = [{at: '2026-11-15T10:00:00Z', text: 'The agent stopped before the work was finished. Continue goes on where it left off.', by: 'orch'}];
  assert.equal(sessionState(asking).headline, '');
  const t = feedText(asking);
  assert.doesNotMatch(t, /Before the question/);
  assert.doesNotMatch(t, /Continue goes on where it left off/);
});

test('#862: the run clock reads "since 12:26", never a running 732:20', () => {
  const els = {time: {textContent: ''}};
  const S = {state: {view: {run: {first: '2026-11-15T12:26:00'}}, workedBase: 43940, workedAt: 0, clockWorking: false}, views: {}, register: (n, m) => { S.views[n] = m; }, h: () => ({}), TID: null, toast() {}, els, stamp: () => '', hhmm: at => at.slice(11, 16)};
  const ctx = vm.createContext({window: {FocusStore: S}, performance: {now: () => 0}, setInterval() {}});
  const file = path.join(__dirname, '../src/orch_focus/web/session.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  S.views.session.tickTimer();
  assert.equal(els.time.textContent, 'since 12:26');
  S.state.view.run.first = null; S.state.workedBase = 720;
  S.views.session.tickTimer();
  assert.equal(els.time.textContent, '12 min');
});
