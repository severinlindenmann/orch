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
