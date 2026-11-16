const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web');
const ssrc = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');
const hsrc = fs.readFileSync(path.join(web, 'handoff.js'), 'utf8');

const el = (tag, props, ...kids) => {
  const n = {tag, props: props || {}, kids: kids.flat(Infinity).filter(k => k != null)};
  n.addEventListener = () => {}; n.append = (...k) => { n.kids.push(...k.flat(Infinity)); };
  n.replaceChildren = (...k) => { n.kids = k.flat(Infinity); };
  return n;
};
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.kids || []).map(text).join('');
const find = (n, pred) => !n || typeof n === 'string' ? null : pred(n) ? n : (n.kids || []).map(k => find(k, pred)).find(Boolean) || null;
const byKey = key => n => n.props?.['data-key'] === key;
const slice = (src, from, to) => { const i = src.indexOf(from); assert.ok(i >= 0, from); const j = src.indexOf(to, i); assert.ok(j > i, to); return src.slice(i, j); };

const capitalise = v => String(v).replace(/^./, c => c.toUpperCase());
function settingsCtx(extra = {}) {
  const ctx = {
    h: el, fragment: (...k) => ({tag: 'frag', props: {}, kids: k.flat(Infinity).filter(k2 => k2 != null)}),
    array: v => Array.isArray(v) ? v : [], capitalise, snapshot: false, settingsBusy: new Set(),
    state: {settings: {addons: [], available: []}, addons: []}, addons: () => [],
    asList: v => Array.isArray(v) ? v : [v],
    heading: (t, s, o) => el('h1', {}, t, s, o && o.actions),
    settingsText: (tag, attrs, value) => el(tag, attrs, String(value ?? '')),
    ...extra,
  };
  return vm.createContext(ctx);
}
function load(ctx, ...parts) { vm.runInContext(parts.join('\n') + '\nthis.rowLabel = rowLabel; this.switchBusy = switchBusy; this.addonChanging = addonChanging;', ctx); return ctx; }
const head = slice(ssrc, '// The add-on\'s name, the same', 'const asList');

// 26/42: one display name on or off
test('an add-on has the same display name on or off (never the lower-case package name)', () => {
  const c = load(settingsCtx(), head);
  for (const n of ['factory', 'insights', 'sync', 'publish', 'relay']) assert.equal(c.rowLabel({name: n, active: false}), capitalise(n));
  assert.equal(c.rowLabel({name: 'relay', active: true, dashboard: {label: 'Contacts'}}), 'Relay');
});

// 40: "Turning on…" next to the switch while it runs
test('the switch shows Turning on… / Turning off… while the change runs', () => {
  const ctx = settingsCtx(); const c = load(ctx, head);
  assert.equal(c.switchBusy({name: 'factory', active: false}), null);
  ctx.settingsBusy.add('addon-factory');
  assert.equal(text(c.switchBusy({name: 'factory', active: false})), 'Turning on…');
  assert.equal(text(c.switchBusy({name: 'factory', active: true})), 'Turning off…');
  assert.equal(c.addonChanging(), true);
});

// 23: no call to an add-on that is off/removed, none while the services restart
test('loadAddon asks nothing for a removed add-on or while an add-on change runs', async () => {
  const calls = [];
  const ctx = settingsCtx({
    addonBusy: new Set(), addonAgain: new Set(), addonViews: {}, fetch: async u => { calls.push(u); return {ok: true, json: async () => ({})}; },
    addons: () => [{name: 'sync'}], state: {}, isPublish: () => false, shownAddon: () => null, main: {querySelector: () => null},
    paintAddon: () => {}, loadSharedLinks: async () => {},
  });
  vm.runInContext(head + '\n' + slice(ssrc, 'async function loadAddon(', '\n}\n') + '\n}\nthis.loadAddon = loadAddon;', ctx);
  await ctx.loadAddon('factory');
  assert.deepEqual(calls, []);
  ctx.settingsBusy.add('addon-sync');
  await ctx.loadAddon('sync');
  assert.deepEqual(calls, []);
  ctx.settingsBusy.delete('addon-sync');
  await ctx.loadAddon('sync');
  assert.deepEqual(calls, ['/api/addon/sync']);
});

// 39 + 22: the catalogue lists add-ons that are off with "Turn on", and reads the add-ons again when it opens
function catalogue(state, freshState) {
  const dialogEl = el('dialog', {}); dialogEl.isConnected = true;
  const accepted = []; const fetched = [];
  const ctx = settingsCtx({
    state, dialog: () => ({d: dialogEl, actions: el('div', {})}), addonSet: async () => ({ok: true}), render: () => {}, accept: s => { accepted.push(s); ctx.state = s; },
    window: {orch: {open: () => {}, toast: () => {}}},
    fetch: async u => { fetched.push(u); return {ok: true, json: async () => freshState}; },
  });
  vm.runInContext(head + '\n' + slice(ssrc, 'function addonCatalog()', 'function settingsConfirm(') + '\nthis.addonCatalog = addonCatalog;', ctx);
  ctx.addonCatalog();
  return {ctx, dialogEl, accepted, fetched};
}
test('the catalogue lists add-ons that are off, with Turn on, next to those not installed yet', () => {
  const st = {settings: {
    addons: [{name: 'factory', active: false, description: 'Turn an idea into finished work.', consent: 'Turn an idea into finished work.\nfactory 0.1.0\nAdds the command: orch factory'}, {name: 'dashboard', active: false}, {name: 'sync', active: true}],
    available: [{name: 'insights', label: 'insights', description: 'See usage.', consent: 'See usage.\ninsights 0.1.0'}]}};
  const {dialogEl} = catalogue(st, st);
  const list = dialogEl.kids[0];
  const off = find(list, byKey('catalog-add-factory'));
  assert.equal(text(off), 'Turn on');
  assert.equal(text(find(list, byKey('catalog-card-factory'))).startsWith('Factory'), true);
  assert.equal(text(find(list, byKey('catalog-add-insights'))), 'Add');
  assert.equal(text(find(list, byKey('catalog-card-insights'))).startsWith('Insights'), true);
  assert.equal(find(list, byKey('catalog-add-sync')), null);       // on: nothing to add
  assert.equal(find(list, byKey('catalog-add-dashboard')), null);  // the dashboard is never offered
});
test('the catalogue reads the add-ons again when it opens (an add-on removed in the terminal is there at once)', async () => {
  const before = {settings: {addons: [], available: []}};
  const after = {settings: {addons: [], available: [{name: 'factory', description: 'x', consent: 'x'}]}};
  const {dialogEl, fetched, accepted} = catalogue(before, after);
  assert.ok(find(dialogEl.kids[0], byKey('catalog-empty')));
  await new Promise(r => setImmediate(r));
  assert.deepEqual(fetched, ['/api/state?fresh=1']);
  assert.equal(accepted.length, 1);
  assert.ok(find(dialogEl.kids[0], byKey('catalog-add-factory')));
  assert.equal(find(dialogEl.kids[0], byKey('catalog-empty')), null);
});

// 40: one plain sentence, the technical lines behind Details
test('turning on says one plain sentence and keeps the technical lines behind Details', () => {
  const body = slice(ssrc, 'function settingsConfirm(', 'async function settingsSend(');
  const d = el('dialog', {}); const kids = d.kids;
  d.querySelector = () => ({});
  const ctx = settingsCtx({dialog: () => ({d, actions: Object.assign(el('div', {}), {querySelectorAll: () => []})}), window: {orch: {open: () => {}, close: async () => {}}}});
  vm.runInContext(body + '\nthis.settingsConfirm = settingsConfirm;', ctx);
  ctx.settingsConfirm('Turn on Factory?', 'Adds a Factory tab.\nfactory 0.1.0\nAdds the command: orch factory\nRuns a background process.', 'preserve-lines', 'Turn on', async () => {});
  assert.equal(text(kids[0]), 'Adds a Factory tab.');
  assert.equal(kids[1].tag, 'details');
  assert.equal(text(kids[1].kids[0]), 'Details');
  assert.match(text(kids[1]), /Adds the command: orch factory/);
  assert.doesNotMatch(text(kids[0]), /command|background/);
});

// 20/21: Remove is offered, except for the add-ons that are part of orch (said plainly)
test('the add-on page offers Remove, and says plainly when the add-on is part of orch', () => {
  const ctx = settingsCtx({
    addons: () => [], state: {look: null}, heading: (t) => el('h1', {}, t),
  });
  vm.runInContext(head + '\n' + slice(ssrc, 'function addonDetailPage(', 'function settingsPage()') + '\nthis.page = addonDetailPage;', ctx);
  const removable = ctx.page({name: 'factory', active: false, description: 'd', removable: true});
  assert.equal(text(find(removable, byKey('addon-detail-remove'))), 'Remove from this computer');
  const core = ctx.page({name: 'relay', active: false, description: 'd', removable: false});
  assert.equal(find(core, byKey('addon-detail-remove')), null);
  assert.match(text(find(core, byKey('addon-detail-core'))), /Relay is part of orch\. You can turn it off, but not remove it\./);
});

// 19: the update banner while it runs
function fn(name) {
  const i = hsrc.indexOf('  function ' + name + '(');
  assert.ok(i >= 0, name);
  const j = hsrc.indexOf('\n  }\n', i) + 4;
  const ctx = vm.createContext({String, Array});
  vm.runInContext(hsrc.slice(i, j) + '\nthis.' + name + ' = ' + name + ';', ctx);
  return ctx[name];
}
test('while the update runs the banner names both versions and what changed', () => {
  const words = fn('updatingWords'), lines = fn('changesLine');
  const info = {update_available: true, installed: {label: 'orch 23'}, newest: {label: 'orch 24'}, changes: ['A', 'B', 'C', 'D']};
  assert.equal(words(info), 'Updating orch 23 → orch 24');
  assert.equal(words({update_available: true, newest: {label: 'orch 24'}}), 'Updating to orch 24');
  assert.equal(words({}), null);
  assert.equal(words(null), null);
  assert.equal(lines(info), 'A; B; C; …');
  assert.equal(lines({update_available: true, changes: ['A']}), 'A');
  assert.equal(lines(null), '');
  assert.match(hsrc, /sessionStorage\.setItem\("orch-update-from"/);  // so the end says "Updated orch 23 → 24."
});

// 885: the Focus add-on page has the one switch the refusal points to
test('the Focus add-on page shows the typing switch with one plain line, only when Focus is on', () => {
  const mk = (settings) => {
    const ctx = settingsCtx({addons: () => [], state: {look: null, settings}, heading: t => el('h1', {}, t)});
    vm.runInContext(head + '\n' + slice(ssrc, 'function addonDetailPage(', 'function settingsPage()') + '\nthis.page = addonDetailPage;', ctx);
    return ctx;
  };
  const on = mk({typing_on: false}).page({name: 'focus', page: {live_session: true}, active: true, description: 'd', removable: true});
  const sw = find(on, byKey('addon-detail-typing'));
  assert.equal(sw.props['data-action'], 'session-typing');
  assert.equal(sw.props['aria-checked'], false);
  assert.match(text(find(on, byKey('addon-detail-typing-row'))), /Let me type into the helper’s screen.*click the helper’s live screen and type into it/);
  assert.equal(find(mk({typing_on: false}).page({name: 'focus', page: {live_session: true}, active: false, description: 'd'}), byKey('addon-detail-typing')), null);
  assert.equal(find(mk({typing_on: true}).page({name: 'sync', active: true, description: 'd'}), byKey('addon-detail-typing')), null);
});
