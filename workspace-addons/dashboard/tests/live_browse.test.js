// ORCH-1493: the dashboard's connector for the helper's browser (pages/livebrowse.js): stream events reach the kit
// view, a dropped stream reopens with a growing wait, a final end does not reopen, Stop names the generation.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const timers = [];
global.setTimeout = (f, ms) => { timers.push({f, ms}); return timers.length; };
global.clearTimeout = () => {};
const streams = [];
global.EventSource = class {
  constructor(url) { this.url = url; this.l = {}; this.closed = false; streams.push(this); }
  addEventListener(t, f) { this.l[t] = f; }
  emit(t, data) { this.l[t]({data: JSON.stringify(data)}); }
  close() { this.closed = true; }
};
const calls = [];
const ui = () => ({el: {parentNode: null, isConnected: true}, hello: d => calls.push(['hello', d]), tabs: t => calls.push(['tabs', t]),
  frame: f => calls.push(['frame', f]), clear: () => calls.push(['clear']), event: e => calls.push(['event', e]),
  show: s => calls.push(['show', s]), end: e => calls.push(['end', e]), dispose() {}});
global.window = {UI: {browserView: () => ui()}};
const lb = require('../src/orch_dashboard/web/pages/livebrowse.js');

test('events reach the view; a drop reopens after 1, 2, 4 s; a final end stays closed', () => {
  const b = lb.liveBrowseFor('t_abc123');
  lb.liveBrowseOpen('t_abc123', b);
  const es = streams.at(-1);
  assert.equal(es.url, '/api/browse/stream?ticket=t_abc123');
  es.emit('hello', {generation: '0123456789abcdef'});
  es.emit('frame', {jpeg: 'AAAA', w: 1, h: 1, at: 1});
  assert.deepEqual(calls.map(c => c[0]), ['hello', 'frame']);
  for (const want of [1000, 2000, 4000]) {
    streams.at(-1).onerror();
    assert.equal(timers.at(-1).ms, want);
    timers.at(-1).f();
  }
  assert.ok(calls.some(c => c[0] === 'show' && c[1] === 'lost'));
  streams.at(-1).emit('end', {why: 'stopped by a person', final: true});
  const n = streams.length;
  lb.liveBrowseOpen('t_abc123', b);
  assert.equal(streams.length, n);  // final: no new stream
});

test('no browser yet: the end is not final and it looks again later', () => {
  const b = lb.liveBrowseFor('t_other1');
  lb.liveBrowseOpen('t_other1', b);
  streams.at(-1).emit('end', {why: 'No browser is open for this ticket.', final: false});
  assert.equal(b.final, false);
  const n = streams.length;
  timers.at(-1).f();
  assert.equal(streams.length, n + 1);
});

test('served as a page module, loaded after the kit view, and the route is #browser/<ticket>', () => {
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.ok(html.indexOf('kit/browser.js') < html.indexOf('pages/livebrowse.js'));
  assert.ok(html.indexOf('pages/livebrowse.js') < html.indexOf('app.js'));
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /livebrowse\|liveterm\)\\\.js/);
  assert.match(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), /#browser\\\/t_\[a-z0-9\]\{4,32\}\$/);
});
