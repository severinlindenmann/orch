const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/handoff.js'), 'utf8');
const start = src.indexOf('  // The page stops waiting'), end = src.indexOf('  notices(); poll();');

function page(now, store, reply) {
  const banners = [];
  const sessionStorage = {getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; }};
  const fetch = () => reply === 'down'
    ? {then() { return {then() { return {catch(f) { f(); }}; }}; }}
    : {then(f) { const s = f({ok: true, json: () => reply}); return {then(g) { g(s); return {catch() {}}; }}; }};
  const c = vm.createContext({sessionStorage, fetch, Date: {now: () => now}, Number, String, shown: ''});
  vm.runInContext('var shown = ""; function banner(t) { out.push(t); }\n' + src.slice(start, end) + '\nthis.S = updateStatus; this.go = updateStarted;', Object.assign(c, {out: banners}));
  return {c, banners};
}

test('the page stops waiting after 3 minutes with "still the old version" when the server says running', () => {
  const store = {'orch-update-started': '1000'};
  const early = page(1000 + 60000, store, {state: 'running'});
  early.c.S();
  assert.deepEqual(early.banners, []);
  const late = page(1000 + 181000, store, {state: 'running'});  // still running after the wait
  late.c.S();
  assert.equal(late.banners.length, 1);
  assert.match(late.banners[0], /did not finish\. orch is still the old version\./);
  assert.ok(!('orch-update-started' in store));
});

test('a failed update shows the plain reason once', () => {
  const store = {'orch-update-started': '1000'};
  const p = page(2000, store, {state: 'failed', reason: 'No internet connection to GitHub - orch is still the old version. Try again later.'});
  p.c.S();
  assert.deepEqual(p.banners, ['Update failed: No internet connection to GitHub - orch is still the old version. Try again later.']);
  assert.ok(!('orch-update-started' in store));
});

test('a server that cannot be reached after the wait says "orch restarted", not "did not finish"', () => {
  const store = {'orch-update-started': '1000'};
  const late = page(1000 + 181000, store, 'down');
  late.c.S();
  assert.deepEqual(late.banners, ['orch restarted. Reload the dashboard.']);
  assert.ok(!('orch-update-started' in store));
});
