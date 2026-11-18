'use strict';
// ORCH-363: the History tab of a layer pane (pages/live-history.js): the last 10 sessions of a ticket, newest first,
// with Reopen on the earlier ones; the session in use says so. The model is plain data.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dir = path.join(__dirname, '../src/orch_dashboard/web');
const source = fs.readFileSync(path.join(dir, 'pages/live-history.js'), 'utf8');
const model = source.slice(0, source.indexOf('// --- the page ---'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(model + '\nthis.api = {liveHistRow, liveHistView, LIVE_HIST_MAX, LIVE_HIST_EMPTY};', ctx);
const H = ctx.api;
const when = at => 'at ' + at.toISOString().slice(11, 16);
const now = new Date('2026-11-17T20:00:00Z');
const row = (id, extra = {}) => ({id, label:'Helper', last_used:'2026-11-17T14:05:00Z', title:'Fix the login', turns:3, current:false, reopenable:true, ...extra});

test('loading, could not load, and nothing earlier yet', () => {
  assert.equal(H.liveHistView(null, now, when).state, 'loading');
  assert.equal(H.liveHistView({available:false, sessions:[]}, now, when).state, 'error');
  assert.equal(H.liveHistView({available:true, sessions:[]}, now, when).state, 'empty');
  assert.equal(H.liveHistView({available:true, sessions:[row('a', {current:true, reopenable:false})]}, now, when).state, 'empty', 'only the one in use: nothing to reopen');
});

test('a row: when, the first message, plain facts with the right plural, Reopen only for an earlier one', () => {
  const r = H.liveHistRow(row('a'), now, when);
  assert.equal(r.day, 'at 14:05');
  assert.equal(r.title, 'Fix the login');
  assert.equal(r.facts, '3 messages · Helper');
  assert.equal(r.reopen, true);
  assert.equal(H.liveHistRow(row('b', {turns:1}), now, when).facts, '1 message · Helper');
  const cur = H.liveHistRow(row('c', {current:true, reopenable:false}), now, when);
  assert.equal(cur.current, true);
  assert.equal(cur.reopen, false);
  const gone = H.liveHistRow(row('d', {turns:0, reopenable:false, title:''}), now, when);
  assert.equal(gone.facts, 'Not on this computer · Helper');
  assert.equal(gone.title, 'No first message');
  assert.equal(gone.reopen, false);
  assert.equal(H.liveHistRow(row('e', {last_used:''}), now, when).day, 'Earlier');
});

test('at most 10 rows, in the order orch gives (newest first)', () => {
  const many = Array.from({length:14}, (_, i) => row('s' + i));
  const v = H.liveHistView({available:true, sessions:many}, now, when);
  assert.equal(H.LIVE_HIST_MAX, 10);
  assert.equal(v.rows.length, 10);
  assert.deepEqual(v.rows.map(r => r.id), many.slice(0, 10).map(r => r.id));
});

test('the layer shows the History button and the list in the pane, and the page loads the file', () => {
  const layer = fs.readFileSync(path.join(dir, 'pages/live-layer.js'), 'utf8');
  assert.match(layer, /liveHistButton\(sess, label\)/);
  assert.match(layer, /liveHistShown\(sess\) \? h\('div', \{className:'live-pb live-pb-hist'\}, liveHistBody\(sess\)\)/);
  assert.match(layer, /liveHistKey\(\)/, 'opening History repaints the dock');
  const index = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
  assert.ok(index.indexOf('pages/live-history.js') > 0 && index.indexOf('pages/live-history.js') < index.indexOf('pages/live-layer.js'));
  assert.match(source, /act\('session\.reopen', \{ticket:id, session:b\.dataset\.id\}\)/);
  assert.match(source, /fetch\('\/api\/sessions\/' \+ encodeURIComponent\(id\)\)/);
});

test('the empty line says why nothing earlier is kept and the one in use still shows', () => {
  assert.match(H.LIVE_HIST_EMPTY, /same conversation/);
  const v = H.liveHistView({available:true, sessions:[row('a', {current:true, reopenable:false})]}, now, when);
  assert.equal(v.state, 'empty');
  assert.equal(v.rows.length, 1);
  assert.equal(v.rows[0].current, true);
});
