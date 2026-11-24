'use strict';
// ORCH-1806: on the Services page a click on another button while one action still ran was dropped without a sign.
// Now it waits its turn (its button busy meanwhile) and runs afterwards.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const settings = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
const piece = (start, end) => { const i = settings.indexOf(start); return settings.slice(i, settings.indexOf(end, i) + end.length); };
const code = (settings.includes('const addonTurn = ') ? piece('const addonTurn = ', 'look(); });') : '') + '\n' + piece('async function addonAct(', '\n}\n');

function page() {
  const locks = new Set(), sent = [], pending = [];
  const act = (_, args) => new Promise(done => { sent.push(args.target); pending.push(() => done({ok: true})); });
  const window = {orch: {toast() {}}};
  const run = Function('locks', 'act', 'shownAddon', 'loadAddon', 'window', 'setTimeout',
    code + '\nreturn addonAct;')(locks, act, () => 'services', async () => {}, window, (f) => setImmediate(f));
  return {addonAct: run, sent, pending};
}
const button = target => ({dataset: {verb: 'act', target}, disabled: false, isConnected: true, attrs: {},
  closest: () => null, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }});
const tick = () => new Promise(r => setImmediate(r));

test('a click during another action waits, shows busy, and runs afterwards (ORCH-1806)', async () => {
  const p = page(), stop = button('web'), manage = button('found:job');
  const first = p.addonAct(stop);
  await tick();
  assert.deepEqual(p.sent, ['web']);
  const second = p.addonAct(manage);
  await tick();
  assert.deepEqual(p.sent, ['web'], 'the second waits while the first runs');
  assert.equal(manage.disabled, true);
  assert.equal(manage.attrs['aria-busy'], 'true', 'its button shows busy');
  p.pending.shift()();
  await first;
  for (let i = 0; i < 5 && p.sent.length < 2; i++) await tick();
  assert.deepEqual(p.sent, ['web', 'found:job'], 'the second click ran afterwards');
  p.pending.shift()();
  await second;
  assert.equal(manage.disabled, false);
  assert.equal(manage.attrs['aria-busy'], undefined);
});
