import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const D = require('../static/diagtrail.js');

function fakeWindow(fetchImpl) {
  const listeners = {}, docListeners = {};
  const sent = [];
  const win = {
    location: {hash: '#home'},
    navigator: {userAgent: 'Mozilla/5.0 Chrome/131.0 Safari/537', maxTouchPoints: 0},
    innerWidth: 1280, innerHeight: 800, devicePixelRatio: 2,
    console: {error() {}},
    document: {addEventListener: (n, f) => { docListeners[n] = f; }, querySelector: () => null},
    addEventListener: (n, f) => { listeners[n] = f; },
    fetch: async (url, init) => {
      if (String(url).startsWith('/api/diag')) { sent.push(JSON.parse(init.body)); return {ok: true, json: async () => ({enabled: win.enabled !== false})}; }
      return fetchImpl ? fetchImpl(url, init) : {ok: true, status: 200};
    },
  };
  win.top = win;
  return {win, listeners, docListeners, sent};
}

test('env, route changes, errors and console.error are queued without any text', async () => {
  const {win, listeners, sent} = fakeWindow();
  const t = D.install(win);
  win.location.hash = '#ticket/t_abcdef12';
  listeners.hashchange();
  listeners.error({error: new TypeError('SECRET text'), message: 'SECRET text', filename: 'http://x/pages/ticket.js?v=1', lineno: 9, colno: 4});
  listeners.unhandledrejection({reason: new RangeError('SECRET')});
  win.console.error(new Error('SECRET'), 'more');
  await t.flush();
  const body = JSON.stringify(sent);
  assert.ok(!body.includes('SECRET'));
  const evs = sent[0].events;
  assert.deepEqual(evs.map(e => e.ev), ['ui.env', 'ui.route', 'ui.error', 'ui.error', 'ui.console_error']);
  assert.deepEqual(evs[0].kv, {w: 1280, h: 800, zoom: 200, browser: 'Chrome 131', assets: '', touch: false});
  assert.deepEqual(evs[1].kv, {from: '#home', to: '#ticket/:id'});
  assert.deepEqual(evs[2].kv, {kind: 'error', what: 'TypeError', file: 'ticket.js', line: 9, col: 4});
  assert.equal(evs[3].kv.what, 'RangeError');
  assert.deepEqual(evs[4].kv, {what: 'Error', n: 2});
  assert.equal(evs[2].ticket, 't_abcdef12'); // the page the person was on
});

test('fetch: route, status and duration only; quiet polls only when slow or failing; our own batches never', async () => {
  const {win, docListeners, sent} = fakeWindow(async url => {
    if (String(url).includes('boom')) throw new TypeError('network SECRET');
    if (String(url).includes('abort')) { const e = new Error('x'); e.name = 'AbortError'; throw e; }
    return {ok: !String(url).includes('bad'), status: String(url).includes('bad') ? 500 : 200};
  });
  const t = D.install(win);
  await win.fetch('/api/state?fresh=1');
  await win.fetch('/api/act', {method: 'POST', body: 'SECRET body'});
  await win.fetch('/api/file?name=bad.txt').catch(() => {});
  await win.fetch('/api/boom').catch(() => {});
  await win.fetch('/api/abort').catch(() => {});
  await win.fetch('/api/events');
  await t.flush();
  const f = sent[0].events.filter(e => e.ev === 'ui.fetch').map(e => ({...e.kv, ms: 0}));
  assert.deepEqual(f, [
    {route: '/api/act', method: 'POST', status: 200, ms: 0, outcome: 'ok'},
    {route: '/api/file', method: 'GET', status: 500, ms: 0, outcome: 'error'},
    {route: '/api/boom', method: 'GET', status: 0, ms: 0, outcome: 'failed'},
    {route: '/api/abort', method: 'GET', status: 0, ms: 0, outcome: 'cancelled'},
  ]);
  assert.ok(!JSON.stringify(sent).includes('SECRET'));
});

test('a click on a [data-action] button records its id only', async () => {
  const {win, docListeners, sent} = fakeWindow();
  const t = D.install(win);
  const btn = {dataset: {action: 'answer'}, textContent: 'SECRET label'};
  docListeners.click({target: {closest: sel => (sel === '[data-action]' ? btn : null)}});
  docListeners.click({target: {closest: () => null}});
  await t.flush();
  const clicks = sent[0].events.filter(e => e.ev === 'ui.action');
  assert.deepEqual(clicks.map(e => e.kv), [{id: 'answer', route: '#home'}]);
  assert.ok(!JSON.stringify(sent).includes('SECRET'));
});

test('state: client and server revision with the cache age', async () => {
  const {win, sent} = fakeWindow();
  const t = D.install(win);
  t.state('aaaaaaaaaaaaaaaa', 'bbbbbbbbbbbbbbbb', 1234.6);
  await t.flush();
  assert.deepEqual(sent[0].events.at(-1).kv, {client_rev: 'aaaaaaaaaaaa', server_rev: 'bbbbbbbbbbbb', cache_age_ms: 1235});
});

test('the answer "log is off" stops all sending', async () => {
  const {win, sent} = fakeWindow();
  win.enabled = false;
  const t = D.install(win);
  await t.flush();
  assert.equal(sent.length, 1);
  assert.equal(t.enabled, false);
  t.push('ui.route', {from: 'a', to: 'b'});
  await t.flush();
  assert.equal(sent.length, 1);
  assert.equal(t.queue.length, 0);
});

test('the queue is bounded and install is once per window', () => {
  const {win} = fakeWindow();
  const t = D.install(win);
  assert.equal(D.install(win), t);
  for (let i = 0; i < 500; i++) t.push('ui.route', {from: 'a', to: 'b'});
  assert.ok(t.queue.length <= 200);
});

test('fold hides ids and long numbers', () => {
  assert.equal(D.fold('/api/chat/thread/ws_abcdefghij?x=1'), '/api/chat/thread/:id');
  assert.equal(D.fold('#ticket/t_abc12345'), '#ticket/:id');
  assert.equal(D.browser('Mozilla Version/17.2 Safari/605'), 'Safari 17');
});
