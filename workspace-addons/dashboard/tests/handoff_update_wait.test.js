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
  vm.runInContext('var shown = ""; function poll() {} function banner(t) { out.push(t); }\n' + src.slice(start, end) + '\nthis.S = updateStatus; this.go = updateStarted; this.hold = function (b) { startedBanner = b; };', Object.assign(c, {out: banners}));
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

// fb1: "Update started" and "Update finished" stayed stacked
test('the "Update started" banner goes away when the update finishes, fails or is overdue', () => {
  for (const [now, reply] of [[2000, {state: 'finished'}], [2000, {state: 'failed', reason: 'No internet'}], [1000 + 181000, {state: 'running'}]]) {
    const store = {'orch-update-started': '1000'};
    const p = page(now, store, reply);
    let removed = 0;
    p.c.hold({remove() { removed++; }});
    p.c.S();
    assert.equal(p.banners.length, 1);
    assert.equal(removed, 1, JSON.stringify(reply));
  }
  const store = {'orch-update-started': '1000'}, p = page(2000, store, {state: 'running'});
  let removed = 0;
  p.c.hold({remove() { removed++; }});
  p.c.S();
  assert.equal(removed, 0, 'still running: the started banner stays');
});
