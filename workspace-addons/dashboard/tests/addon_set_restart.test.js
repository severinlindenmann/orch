const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const start = src.indexOf('let restartHold = 0');
const end = src.indexOf('\n}\n', src.indexOf('async function addonUninstall(', start)) + 3;

// states: 'down' (refused), or [state, boot] / a bare state (no boot header)
function page(actResult, states, opts = {}) {
  const accepted = [], quietSeen = [];
  const win = {};
  const c = vm.createContext({
    snapshot: false, accepted, window: win, Date, serverBoot: opts.boot || null,
    state: opts.state || {settings: {addons: []}},
    setTimeout: f => f(),
    array: v => Array.isArray(v) ? v : [],
    act: async () => actResult, render: () => { if (opts.onRender) opts.onRender(); },
    accept: s => accepted.push(s),
    fetch: async url => {
      quietSeen.push(win.orchQuiet());
      if (opts.urls) opts.urls.push(url);
      const s = states.shift();
      if (s === 'down' || s === undefined) throw new Error('Failed to fetch');
      if (s === 'broken') return {ok: true, headers: {get: () => 'b2'}, json: async () => { throw new Error('body cut off'); }};
      const [body, boot] = Array.isArray(s) ? s : [s, null];
      return {ok: true, headers: {get: k => k === 'X-Orch-Boot' ? boot : null}, json: async () => body};
    },
  });
  vm.runInContext(src.slice(start, end) + '\nthis.addonSet = addonSet; this.addonUninstall = addonUninstall; this.boot = () => serverBoot;', c);
  c.quietSeen = quietSeen; c.win = win;
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
  const urls = [];
  const r = await page({ok: false, status: 422, text: 'That add-on is not installed.'}, [], {urls}).addonSet('factory', true);
  assert.equal(r.status, 422);
  assert.deepEqual(urls, []);
});

test('an answered change: the page stays quiet until the restarted server answers, then reads it once (ORCH-1034)', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}]}};
  const urls = [];
  const c = page({ok: true, status: 200}, [[{}, 'b1'], 'down', 'down', [on, 'b2']], {boot: 'b1', urls});
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.deepEqual(c.quietSeen, [true, true, true, true]);  // every wait read happens while the page is quiet
  assert.equal(c.win.orchQuiet(), false);  // and the polls start again after it
  assert.deepEqual(c.accepted, [on]);  // the old run's answer is not taken; the new one is
  assert.equal(c.boot(), 'b2');
  assert.ok(urls.every(u => u === '/api/state?fresh=1'));
});

test('nothing restarted: the same run answering twice is taken', async () => {
  const same = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page({ok: true, status: 200}, [[{}, 'b1'], [same, 'b1']], {boot: 'b1'});
  await c.addonSet('factory', true);
  assert.deepEqual(c.accepted, [same]);
  assert.equal(c.win.orchQuiet(), false);
});

test('Remove: the row leaves the Settings list at once and the restarted server confirms it (ORCH-1034)', async () => {
  const listed = {settings: {addons: [{name: 'factory', active: false}, {name: 'relay', active: true}]}};
  const gone = {settings: {addons: [{name: 'relay', active: true}]}};
  const seen = [];
  const c = page({ok: true, status: 200}, ['down', [gone, 'b2']], {boot: 'b1', state: listed, onRender: () => seen.push(c.state.settings.addons.map(a => a.name))});
  const r = await c.addonUninstall('factory');
  assert.equal(r.ok, true);
  assert.deepEqual(seen, [['relay']]);
  assert.deepEqual(c.accepted, [gone]);
});

test('Remove of a switched-on add-on: the uninstall goes right after the answered turn-off, one wait after both', async () => {
  const listed = {settings: {addons: [{name: 'factory', active: true}]}};
  const gone = {settings: {addons: []}};
  const steps = [];
  const c = page({ok: true, status: 200}, ['down', [gone, 'b2']], {boot: 'b1', state: listed});
  c.act = async (op, args) => { steps.push(op + (op === 'addon.set' ? ':' + args.on : '')); return {ok: true, status: 200}; };
  const realFetch = c.fetch;
  c.fetch = async url => { steps.push('read'); return realFetch(url); };
  const r = await c.addonUninstall('factory');
  assert.equal(r.ok, true);
  assert.deepEqual(steps, ['addon.set:false', 'addon.uninstall', 'read', 'read']);
  assert.deepEqual(c.accepted, [gone]);
});

test('Remove with a lost answer: recovered when the restarted server no longer lists it', async () => {
  const gone = {settings: {addons: []}};
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, ['down', [gone, 'b2']], {boot: 'b1', state: {settings: {addons: [{name: 'factory', active: false}]}}});
  const r = await c.addonUninstall('factory');
  assert.equal(r.ok, true);
  assert.equal(r.recovered, true);
});

test('a reply whose body breaks off during the restart counts as still restarting', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page({ok: true, status: 200}, ['broken', [on, 'b2']], {boot: 'b1'});
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.deepEqual(c.accepted, [on]);
  assert.equal(c.win.orchQuiet(), false);
});

test('two changes at once: the first one ending does not end the quiet time of the second', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}, {name: 'relay', active: true}]}};
  const reply = boot => ({ok: true, headers: {get: () => boot}, json: async () => on});
  let release;
  const held = new Promise(done => { release = done; });
  const replies = [() => held, () => Promise.resolve(reply('b2'))];  // the second change's read waits until released
  const c = page({ok: true, status: 200}, [], {boot: 'b1'});
  c.fetch = async () => replies.shift()();
  const second = c.addonSet('relay', true);
  const first = c.addonSet('factory', true);
  await first;
  assert.equal(c.win.orchQuiet(), true);  // the second change still waits for the server
  release(reply('b2'));
  await second;
  assert.equal(c.win.orchQuiet(), false);
});

test('the poll, the live sessions and the debug log skip their requests while the page is quiet', () => {
  const live = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livesessions.js'), 'utf8');
  const trail = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/diagtrail.js'), 'utf8');
  const refresh = src.slice(src.indexOf('async function refresh()'), src.indexOf('fetching = true;', src.indexOf('async function refresh()')));
  assert.match(refresh, /window\.orchQuiet\(\)\) return;/);
  assert.match(live, /window\.orchQuiet\?\.\(\)\) return;/);
  assert.match(trail, /win\.orchQuiet\(\)/);
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

test('the sign-in notice: plain wording, above any open dialog, never "orch restarted", no window opened on the server', () => {
  const js = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/session.js'), 'utf8');
  assert.match(js, /indexOf\("Sign in to "\) === 0/);
  assert.match(js, /querySelectorAll\("dialog\[open\]"\)/);
  assert.doesNotMatch(js, /orch restarted/);
  assert.doesNotMatch(js, /session\/reopen/);
  // the page secret is shared by every tab of the browser (a second window works: ORCH-39)
  assert.match(js, /localStorage\.setItem\(KEY/);
});

test('the debug log keeps its events while the page is quiet and sends them once the server is back', async () => {
  const trail = require(path.join(__dirname, '../../../workspace/src/orch_ui/static/diagtrail.js'));
  let quiet = true;
  const sent = [];
  const win = {
    fetch: async (url, init) => { sent.push(url); return {ok: true, json: async () => ({enabled: true})}; },
    location: {hash: ''}, navigator: {}, addEventListener: () => {}, innerWidth: 1280, innerHeight: 800,
    console: {error: () => {}}, document: {addEventListener: () => {}}, orchQuiet: () => quiet,
  };
  const t = trail.install(win);
  assert.ok(t.queue.length >= 1);  // the load's ui.env event
  await t.flush();
  assert.deepEqual(sent, []);
  assert.ok(t.queue.length >= 1);
  quiet = false;
  await t.flush();
  assert.deepEqual(sent, ['/api/diag']);
  assert.equal(t.queue.length, 0);
});
