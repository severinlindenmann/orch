/* ORCH-232: the Live tab never says "0 of 0", never shows a raw repeat rule, and log times over several days carry their day. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = name => path.join(__dirname, '../src/orch_focus/web', name);

function drawer() {
  const h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), append(...k) { this.kids.push(...k); }, addEventListener() {}});
  const text = n => !n || typeof n !== 'object' ? '' : [n.attrs.text || '', ...n.kids.map(text)].join(' ');
  let drawn = [];
  const els = {agent: {textContent: 'Claude'}, feed: {classList: {toggle() {}}, contains: () => false, querySelectorAll: () => [], replaceChildren: (...k) => { drawn = k; }}};
  const ctx = vm.createContext({document: {activeElement: null}, window: {}});
  ctx.globalThis = ctx;
  const S = {state: {}, views: {}, register: (n, m) => { S.views[n] = m; }, h, els, keyOf: JSON.stringify, plainNames: s => s, hhmm: () => '', evText: () => '', STATUS_WORD: {}};
  ctx.window.FocusStore = S;
  ctx.window.UI = require('./kit_state.cjs');
  for (const name of ['helpers.js', 'live.js']) vm.runInContext(fs.readFileSync(web(name), 'utf8'), ctx, {filename: web(name)});
  return {feed: v => { drawn = []; S.views.live.renderFeed(v); return drawn.map(text).join(' '); }, live: S.views.live};
}

const noTasks = (state, running) => ({
  state, done: 0, total: 0, events: [], record_notes: [],
  run: {running, run: 'r1', label: 'Claude'}, board: {step: ''},
  ticket: {status: 'active', started: true, questions: [], history: [], checklist: []},
});

test('a working ticket without tasks never reads "0 of 0" or "taking shape"', () => {
  const t = drawer().feed(noTasks('working', true));
  assert.doesNotMatch(t, /0 of 0|taking shape/);
  assert.match(t, /Working, no tasks yet/);
});

test('a stopped ticket without tasks says so in words', () => {
  const t = drawer().feed(noTasks('stopped', false));
  assert.doesNotMatch(t, /0 of 0/);
  assert.match(t, /No tasks yet\./);
});

test('an old automation line shows no raw repeat rule', () => {
  const line = drawer().live.plainLine('Automation started an agent run (cron 0 */2 * * *).', []);
  assert.equal(line, 'Automation started an agent run (on its repeat).');
});

test('a time of another day carries its day; a time of today is the clock only', () => {
  const src = fs.readFileSync(web('store.js'), 'utf8');
  const start = src.indexOf('  const MONTHS'), end = src.indexOf('\n  const evText', start);
  assert.ok(start > 0 && end > start, 'store.js needs MONTHS, clock and hhmm before evText');
  const ctx = vm.createContext({});
  vm.runInContext(src.slice(start, end) + '\nthis.hhmm = hhmm; this.clock = clock;', ctx);
  const now = new Date();
  assert.equal(ctx.hhmm(now.toISOString()), ctx.clock(now.toISOString()));
  const old = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 2, 12, 26);
  const said = ctx.hhmm(old.toISOString());
  assert.match(said, new RegExp('^' + old.getDate() + ' [A-Z][a-z]{2}( \\d{4})? '));
  assert.ok(said.endsWith(ctx.clock(old.toISOString())));
  assert.equal(ctx.hhmm(''), '');
});
