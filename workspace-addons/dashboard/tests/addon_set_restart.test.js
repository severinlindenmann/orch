const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const start = src.indexOf('async function addonSet('), end = src.indexOf('\n}\n', start) + 3;
const ustart = src.indexOf('async function addonUninstall('), uend = src.indexOf('\n}\n', ustart) + 3;

// actResult: one answer for every click, or a list (one per click, in order); c.sent counts the clicks sent
function page(actResult, states, current = {settings: {addons: []}}) {
  const accepted = [], sent = [], answers = Array.isArray(actResult) ? actResult : null;
  const c = vm.createContext({
    snapshot: false, accepted, sent, setTimeout: f => f(), state: current,
    array: v => Array.isArray(v) ? v : [],
    act: async (op, args) => { sent.push({op, args}); return answers ? answers.shift() : actResult; },
    accept: s => { accepted.push(s); c.state = s; },
    fetch: async () => { const s = states.shift(); if (s === 'down') throw new Error('Failed to fetch'); return {ok: true, json: async () => s}; },
  });
  vm.runInContext(src.slice(start, end) + src.slice(ustart, uend) + '\nthis.addonSet = addonSet; this.addonUninstall = addonUninstall;', c);
  return c;
}
const lost = {ok: false, status: 0, text: 'Failed to fetch'};

test('a lost answer during the restart: the state after reconnect says it worked', async () => {
  const on = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page({ok: false, status: 0, text: 'Failed to fetch'}, ['down', 'down', on]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.equal(r.recovered, true);
  assert.equal(c.accepted.length, 1);
});

test('Add right after a Remove: the click never arrived, so it is sent once more and the add-on is added (ORCH-1045)', async () => {
  const gone = {settings: {addons: []}}, on = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page([lost, {ok: true, status: 200, state: on}], ['down', 'down', gone]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.equal(c.sent.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(c.sent[1])), {op: 'addon.set', args: {name: 'factory', on: true}});
});

test('the second click is lost too and the server is back unchanged: one error, no third click', async () => {
  const off = {settings: {addons: [{name: 'factory', active: false}]}};
  const c = page(lost, [off, off]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, false);
  assert.equal(r.text, 'Failed to fetch');
  assert.equal(c.sent.length, 2);
});

test('the second click lands during the restart and the state then shows it on: recovered', async () => {
  const off = {settings: {addons: [{name: 'factory', active: false}]}}, on = {settings: {addons: [{name: 'factory', active: true}]}};
  const c = page(lost, [off, 'down', on]);
  const r = await c.addonSet('factory', true);
  assert.equal(r.ok, true);
  assert.equal(r.recovered, true);
  assert.equal(c.sent.length, 2);
});

test('Remove during a restart: a click that never arrived is sent once more; a lost answer is not', async () => {
  const there = {settings: {addons: [{name: 'factory', active: false}]}}, gone = {settings: {addons: []}};
  const again = page([lost, {ok: true, status: 200}], [there], there);
  assert.equal((await again.addonUninstall('factory')).ok, true);
  assert.deepEqual(again.sent.map(x => x.op), ['addon.uninstall', 'addon.uninstall']);
  const answered = page(lost, ['down', gone], there);
  const r = await answered.addonUninstall('factory');
  assert.equal(r.recovered, true);
  assert.equal(answered.sent.length, 1);
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

test('the sign-in notice: plain wording, above any open dialog, never "orch restarted", no window opened on the server', () => {
  const js = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/session.js'), 'utf8');
  assert.match(js, /indexOf\("Sign in to "\) === 0/);
  assert.match(js, /querySelectorAll\("dialog\[open\]"\)/);
  assert.doesNotMatch(js, /orch restarted/);
  assert.doesNotMatch(js, /session\/reopen/);
  // the page secret is shared by every tab of the browser (a second window works: ORCH-39)
  assert.match(js, /localStorage\.setItem\(KEY/);
});
