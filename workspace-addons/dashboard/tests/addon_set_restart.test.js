const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const start = src.indexOf('async function addonSet('), end = src.indexOf('\n}\n', start) + 3;

function page(actResult, states) {
  const accepted = [];
  const c = vm.createContext({
    snapshot: false, accepted, setTimeout: f => f(),
    array: v => Array.isArray(v) ? v : [],
    act: async () => actResult,
    accept: s => accepted.push(s),
    fetch: async () => { const s = states.shift(); if (s === 'down') throw new Error('Failed to fetch'); return {ok: true, json: async () => s}; },
  });
  vm.runInContext(src.slice(start, end) + '\nthis.addonSet = addonSet;', c);
  return c;
}

test('a lost answer during the restart: the state after reconnect says it worked', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, ['down', 'down', on]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.equal(r.recovered, true);
  assert.equal(c.accepted.length, 1);
});

test('reachable but not changed: the original error stays', async () => {
  const off = {settings: {addons: [{name: 'factory', active: false}]}};
  const r = await page({ok: false, status: 0, text: 'Failed to fetch'}, [off]).addonSet('factory', true);
  assert.equal(r.ok, false);
  assert.equal(r.text, 'Failed to fetch');
});

test('a real refusal is not retried', async () => {
  const r = await page({ok: false, status: 422, text: 'That add-on is not installed.'}, []).addonSet('factory', true);
  assert.equal(r.status, 422);
});

const ssrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
const ps = ssrc.indexOf('function pageStopped('), pe = ssrc.indexOf('function pageFrame(');
function stoppedPage(services, snap = false) {
  const el = (tag, props, ...kids) => ({tag, props: props || {}, kids: kids.flat().filter(k => k != null)});
  const c = vm.createContext({
    state: {services}, snapshot: snap, h: el, fragment: (...k) => ({tag: 'frag', kids: k}),
    array: v => Array.isArray(v) ? v : [],
    addons: () => [{name: 'factory', dashboard: {label: 'Factory'}}],
    addonLabel: a => a?.dashboard?.label || a?.name,
  });
  vm.runInContext(ssrc.slice(ps, pe) + '\nthis.f = pageStopped;', c);
  return c.f({id: 'factory', path: 'index.html'});
}
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.kids || []).map(text).join('');
const find = (n, key) => !n || typeof n === 'string' ? null : n.props?.['data-key'] === key ? n : (n.kids || []).map(k => find(k, key)).find(Boolean) || null;

test('a stopped background add-on page says so and offers Start (not the raw "not found")', () => {
  const page = stoppedPage([{addon: 'factory', running: false}]);
  assert.match(text(page), /Factory isn’t running\./);
  const start = find(page, 'page-start');
  assert.equal(start.props['data-action'], 'start');
  assert.equal(text(start), 'Start');
});

test('running, no service, or a shared copy: the page itself', () => {
  assert.equal(stoppedPage([{addon: 'factory', running: true}]), null);
  assert.equal(stoppedPage([]), null);
  assert.equal(stoppedPage([{addon: 'factory', running: false}], true), null);
});
