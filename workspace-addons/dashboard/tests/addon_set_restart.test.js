const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const start = src.indexOf('let restartHold = 0');
const end = src.indexOf('\n}\n', src.indexOf('async function addonWait(', start)) + 3;

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
  vm.runInContext(src.slice(start, end) + '\nthis.addonSet = addonSet; this.addonUninstall = addonUninstall; this.boot = () => serverBoot; this.addonWaiting = addonWaiting; this.SLOW = ADDON_SLOW; this.WAIT = ADDON_WAIT_TEXT;', c);
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

test('reachable but not changed: one plain sentence, never a bare Failed to fetch (ORCH-1046)', async () => {
  const off = {settings: {addons: [{name: 'factory', active: false}]}};
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, [off, off]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, false);
  assert.equal(r.text, 'orch is still restarting. Wait a moment, then try again.');
  assert.equal(r.text, c.SLOW);
});

test('while the page waits for the restarted server, the add-on says so; afterwards it does not (ORCH-1046)', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}]}};
  const painted = [];
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, ['down', 'down', on], {onRender: () => painted.push([...c.addonWaiting].join(','))});
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.deepEqual(painted, ['factory', '']);  // shown once at the start of the wait, cleared once at its end
  assert.equal(c.WAIT, 'Waiting for orch to restart…');
});

test('the server never comes back: the wait ends with the plain sentence (ORCH-1046)', async () => {
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, []);
  const r = await c.addonSet('factory', true, 3, 1);
  assert.equal(r.ok, false);
  assert.equal(r.status, 0);
  assert.equal(r.text, c.SLOW);
  assert.equal(c.addonWaiting.size, 0);
});

test('a real refusal shows no wait and keeps its own words', async () => {
  const painted = [];
  const c = page({ok: false, status: 422, text: 'That add-on is not installed.'}, [], {onRender: () => painted.push('x')});
  const r = await c.addonSet('factory', true);
  assert.equal(r.text, 'That add-on is not installed.');
  assert.deepEqual(painted, []);
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
  assert.deepEqual(seen[0], ['relay']);  // gone at once, and every repaint of the wait keeps it gone
  assert.ok(seen.every(names => names.join() === 'relay'));
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

// The click sent again when the server is back unchanged (ported from PR 2237, ORCH-1045 / ORCH-1046).
const lost = {ok: false, status: 0, text: 'Failed to fetch'};
function counted(answers, states, opts) {
  const c = page(lost, states, opts), sent = [];
  c.act = async (op, args) => { sent.push({op, args}); return Array.isArray(answers) ? answers.shift() : answers; };
  c.sent = sent;
  return c;
}

test('Add right after a Remove: the click never arrived, so it is sent once more and the add-on is added (ORCH-1045)', async () => {
  const gone = {settings: {addons: []}};
  const c = counted([lost, {ok: true, status: 200}], ['down', 'down', gone, [gone, 'b9'], [gone, 'b9']]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.equal(c.sent.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(c.sent[1])), {op: 'addon.set', args: {name: 'factory', on: true}});
});

test('the second click is lost too and the server is back unchanged: one error, no third click', async () => {
  const off = {settings: {addons: [{name: 'factory', active: false}]}};
  const c = counted(lost, [off, off]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, false);
  assert.equal(r.text, c.SLOW);
  assert.equal(c.sent.length, 2);
  assert.equal(c.addonWaiting.size, 0);
});

test('Remove during a restart: a click that never arrived is sent once more; a lost answer is not', async () => {
  const there = () => ({settings: {addons: [{name: 'factory', active: false}]}}), gone = {settings: {addons: []}};
  const again = counted([lost, {ok: true, status: 200}], [there(), gone, gone], {state: there()});
  assert.equal((await again.addonUninstall('factory')).ok, true);
  assert.deepEqual(again.sent.map(x => x.op), ['addon.uninstall', 'addon.uninstall']);
  const answered = counted(lost, ['down', gone], {state: there()});
  const r = await answered.addonUninstall('factory');
  assert.equal(r.recovered, true);
  assert.equal(answered.sent.length, 1);
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
    addonTitle: a => a?.dashboard?.label || a?.name, window: {},
    heading: (title, sub, o = {}) => el('header', {'data-key': 'heading'}, el('h1', {}, title), o.actions || null),
  });
  vm.runInContext(ssrc.slice(ps, pe) + '\nthis.f = pageStopped;', c);
  return c.f({id: 'factory', path: 'index.html'});
}
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.kids || []).map(text).join('');
const find = (n, key) => !n || typeof n === 'string' ? null : n.props?.['data-key'] === key ? n : (n.kids || []).map(k => find(k, key)).find(Boolean) || null;

test('a stopped background add-on page keeps its name and says so in the one notice, with Start (D5)', () => {
  const page = stoppedPage([{addon: 'factory', running: false}]);
  assert.equal(text(find(page, 'heading').kids[0]), 'Factory', 'the page keeps its name');
  const notice = find(page, 'page-stopped');
  assert.match(notice.props.className, /banner page-notice attn/);
  assert.match(text(notice), /^Factory has stopped\. Its work waits\. Your tickets and everything else still work\./);
  const start = find(page, 'page-start');
  assert.equal(start.props['data-action'], 'start');
  assert.match(start.props.className, /btn primary/);
  assert.equal(text(start), 'Start Factory');
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

test('a page script that fails to load (reinstall under way) reloads the page once, at most every 20 s', () => {
  const js = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/session.js'), 'utf8');
  const guard = js.slice(js.indexOf('(function () {\n  var KEY = "orch_reload_broken"'));
  const run = (store, now) => {
    let handler = null, reloads = 0;
    const timers = [];
    const c = vm.createContext({
      window: {addEventListener: (type, f) => { if (type === 'error') handler = f; }},
      location: {href: 'http://127.0.0.1:8000/', origin: 'http://127.0.0.1:8000', reload: () => { reloads++; }},
      sessionStorage: {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }},
      setTimeout: f => timers.push(f), URL, Date: {now: () => now}, Number, String,
    });
    vm.runInContext(guard, c);
    return {fire: target => handler({target}), flush: () => { timers.splice(0).forEach(f => f()); return reloads; }};
  };
  const store = {};
  const p = run(store, 100000);
  p.fire({tagName: 'IMG', src: 'http://127.0.0.1:8000/logo.svg'});
  p.fire({tagName: 'SCRIPT', src: 'https://cdn.example/x.js'});
  assert.equal(p.flush(), 0);  // a picture or another site's script: nothing
  p.fire({tagName: 'SCRIPT', src: 'http://127.0.0.1:8000/kit/diagtrail.js'});
  p.fire({tagName: 'SCRIPT', src: 'http://127.0.0.1:8000/pages/live.js'});
  assert.equal(p.flush(), 1);  // one reload for any number of broken scripts
  const again = run(store, 110000);  // the reloaded page breaks again within 20 s: no loop
  again.fire({tagName: 'SCRIPT', src: 'http://127.0.0.1:8000/pages/live.js'});
  assert.equal(again.flush(), 0);
  const later = run(store, 130001);
  later.fire({tagName: 'SCRIPT', src: 'http://127.0.0.1:8000/pages/live.js'});
  assert.equal(later.flush(), 1);
});
