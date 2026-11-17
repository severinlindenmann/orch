// What helpers need (ORCH-45, look and words chosen by the owner on ORCH-43): Home warns days ahead and when a tool
// login, connection or key stopped working, names the tickets it stops, and Settings > Helper lists every one of them.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const home = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/home.js'), 'utf8');
const settings = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
const homePart = home.slice(home.indexOf('// What helpers need'), home.indexOf('// Home: what needs the person first'));
const settingsPart = settings.slice(settings.indexOf('// What helpers need'), settings.indexOf('// Share with team'));

const el = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false)});
const text = n => n == null ? '' : typeof n === 'string' ? n : n.textContent != null ? n.textContent : (n.kids || []).map(text).join('');
const find = (n, pred) => !n || typeof n !== 'object' ? [] : [...(pred(n) ? [n] : []), ...(n.kids || []).flatMap(k => find(k, pred))];

const T1 = {id: 't_aaa111', key: 'ORCH-12', title: 'Fix login page'}, T2 = {id: 't_bbb222', key: 'ORCH-14', title: 'Update the price list'};
const item = (over = {}) => ({name: 'claude', label: 'Claude Code', kind: 'login', state: 'works', ends_at: null, helper: 'claude', chosen: true, stops: [], ...over});

function page(logins, extra = {}) {
  const acted = [], toasts = [];
  const c = vm.createContext({
    window: {DashHelpers: helpers, orch: {toast: (t, k) => toasts.push([t, k])}}, h: el, clean: v => String(v ?? ''), href: id => '#ticket/' + id,
    snapshot: false, state: {logins}, locks: new Set(), render: () => {}, changeUnavailable: () => false, changeError: r => r.text,
    age: () => 'just now', settingsText: (tag, attrs, value) => ({...el(tag, attrs), textContent: String(value ?? '')}),
    button: (label, cls, click) => ({tag: 'button', attrs: {className: 'btn ' + cls}, kids: [label], dataset: {}, onclick: click}),
    act: async (op, args) => { acted.push([op, args]); c.state.logins = {items: [item({state: 'works'})]}; return {ok: true}; },
    ...extra,
  });
  vm.runInContext(homePart + settingsPart + '\nthis.api = {loginWarnings, loginBanner, loginSoonRow, loginAction, helperNeedsCard};', c);
  return {c, api: c.api, acted, toasts};
}

test('nothing shows when every login works or nothing was checked yet', () => {
  for (const logins of [null, {items: []}, {items: [item(), item({name: 'gh', label: 'GitHub'})]}]) {
    const {api} = page(logins);
    const w = api.loginWarnings();
    assert.equal(w.soon.length + w.stopped.length, 0);
    assert.equal(api.loginBanner(w.stopped), null);
  }
  assert.equal(page(null).api.helperNeedsCard(), null);
});

test('a login that runs out soon is a Needs you row with its end, the tickets it stops and one button', () => {
  const soon = item({state: 'soon', ends_at: new Date(2026, 10, 16, 22, 24).toISOString(), stops: [T1, T2]});
  const {api} = page({items: [soon]});
  const [one] = api.loginWarnings().soon;
  const row = api.loginSoonRow(one);
  assert.match(text(row), /^The Claude Code login ends on Monday 16 November at 22:24\./);
  assert.match(text(row), /After that helpers stop on 2 tickets: ORCH-12 Fix login page · ORCH-14 Update the price list/);
  assert.deepEqual(find(row, n => n.tag === 'a').map(a => a.attrs.href), ['#ticket/t_aaa111', '#ticket/t_bbb222']);
  assert.equal(find(row, n => n.tag === 'button').length, 1);
});

test('one login that stopped working is the red banner: what stopped, the tickets, no new work for the main helper', () => {
  const {api} = page({items: [item({name: 'gh', label: 'GitHub', state: 'renew', stops: [T1, T2]})]});
  const b = api.loginBanner(api.loginWarnings().stopped);
  assert.equal(b.attrs.className, 'banner error');
  assert.equal(b.attrs.role, 'alert');
  assert.match(text(b), /^The GitHub login stopped working/);
  assert.match(text(b), /Helpers stopped on 2 tickets and start no new work: ORCH-12 Fix login page · ORCH-14 Update the price list/);
  const other = page({items: [item({state: 'renew', chosen: false, stops: [T1]})]});
  assert.match(text(other.api.loginBanner(other.api.loginWarnings().stopped)), /Helpers stopped on 1 ticket: ORCH-12/);
});

test('several things that stopped are one banner with a count, their names and See what to fix', () => {
  const {api} = page({items: [item({name: 'gh', label: 'GitHub', state: 'renew', stops: [T1]}),
    item({name: 'wiki', label: 'Company wiki', kind: 'connection', state: 'unreachable', helper: null, chosen: false, stops: [T1, T2]}),
    item({name: 'pay', label: 'Payments key', kind: 'key', state: 'renew', helper: null, chosen: false})]});
  const b = api.loginBanner(api.loginWarnings().stopped);
  assert.match(text(b), /^3 things stopped working/);
  assert.match(text(b), /Helpers stopped on 2 tickets and start no new work\. GitHub login · Company wiki connection · Payments key\./);
  const go = find(b, n => n.tag === 'a')[0];
  assert.equal(go.attrs.href, '#settings/agent');
  assert.equal(text(go), 'See what to fix');
});

test('without the renew step the button checks again; a connection that cannot be reached says Try again', async () => {
  const {api, acted, toasts} = page({items: [item({state: 'renew'})]});
  const control = api.loginAction(api.loginWarnings().stopped[0], 'k');
  assert.equal(text(control), 'Check again');
  await control.onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(acted)), [['logins.check', {}]]);
  assert.deepEqual(toasts[0], ['Claude Code login: Works', 'ok']);
  assert.equal(text(api.loginAction(item({state: 'unreachable'}), 'k')), 'Try again');
  assert.equal(api.loginAction(item({state: 'unreachable'}), 'k').attrs.className, 'btn outline sm');  // never a second filled button
  assert.equal(api.loginAction(item(), 'k', true), null);  // a login that works has no button of its own
});

test('the renew step\'s own button takes the place, and a shared copy has none', () => {
  const own = {tag: 'button', attrs: {}, kids: ['Renew']};
  const seen = [];
  const {api} = page({items: [item({state: 'soon'})]}, {renewButton: (i, o) => { seen.push([i.name, o.quiet]); return own; }});
  assert.equal(api.loginAction(item({state: 'soon'}), 'k'), own);
  assert.deepEqual(seen, [['claude', false]]);
  const shared = page({items: [item({state: 'renew'})]}, {snapshot: true});
  assert.equal(shared.api.loginBanner(shared.api.loginWarnings().stopped), null);  // a snapshot carries no logins
  assert.equal(shared.api.loginAction(item({state: 'renew'}), 'k'), null);
});

test('Settings > Helper lists every login, connection and key with its state, the tickets it stops and when it was checked', () => {
  const {api} = page({checked_at: '2026-11-17T05:00:00Z', items: [
    item({state: 'soon', ends_at: new Date(2026, 10, 16, 22, 24).toISOString(), stops: [T1, T2, {id: 't_ccc333', title: 'x'}]}),
    item({name: 'gh', label: 'GitHub', state: 'renew', stops: [T1, T2]}),
    item({name: 'db', label: 'Databricks', helper: null}),
    item({name: 'wiki', label: 'Company wiki', kind: 'connection', state: 'unreachable', helper: null, stops: [T1]}),
    item({name: 'pay', label: 'Payments key', kind: 'key', helper: null})]});
  const card = api.helperNeedsCard();
  assert.equal(card.attrs.id, 'needs');
  assert.match(text(card), /^What helpers needChecked just now/);
  const rows = find(card, n => n.attrs?.className === 'setting-row');
  assert.deepEqual(rows.map(r => text(r).replace(/Check againTry again|Check again|Try again/, '')), [
    'Claude Code loginLoginRuns out soon · Mon 16 NovStops 3 tickets',
    'GitHub loginLoginNeeds renewingStops 2 tickets',
    'Databricks loginLogin✓ Works',
    'Company wikiConnectionCannot be reachedStops 1 ticket',
    'Payments keyKey✓ Works']);
  assert.deepEqual(rows.map(r => find(r, n => n.tag === 'span' && /badge/.test(n.attrs.className || ''))[0].attrs.className),
    ['badge needs', 'badge error', 'badge done', 'badge error', 'badge done']);
  assert.deepEqual(rows.map(r => find(r, n => n.tag === 'button').map(text).join()), ['Check again', 'Check again', '', 'Try again', '']);
});

test('the page files share one global scope: no name of this part is taken by another page file', () => {
  const names = [...(homePart + settingsPart).matchAll(/^(?:async )?function (\w+)|^const (\w+) =/gm)].map(m => m[1] || m[2]);
  assert.ok(names.includes('loginTicketLinks') && names.includes('helperNeedsCard'));
  const dir = path.join(__dirname, '../src/orch_dashboard/web');
  const files = ['app.js', 'blocks.js', 'helpers.js', ...fs.readdirSync(path.join(dir, 'pages')).filter(f => f.endsWith('.js')).map(f => 'pages/' + f)];
  for (const f of files) {
    let src = fs.readFileSync(path.join(dir, f), 'utf8');
    if (f === 'pages/home.js') src = src.replace(homePart, '');
    if (f === 'pages/settings.js') src = src.replace(settingsPart, '');
    for (const n of names) assert.doesNotMatch(src, new RegExp('(function|const|let) ' + n + '\\b'), n + ' is also defined in ' + f);
  }
});
