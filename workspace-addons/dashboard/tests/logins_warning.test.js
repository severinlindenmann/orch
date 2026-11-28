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
const homePart = home.slice(home.indexOf('// What helpers need'), home.indexOf('// Tickets waiting in line'));
// the one row shape of Blocked now (O-01 D), defined above that part
const blockedPart = home.slice(home.indexOf('function blockedRow'), home.indexOf('const ticketLink'));
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
  vm.runInContext(blockedPart + homePart + settingsPart + '\nthis.api = {loginWarnings, blockedLogins, loginStoppedRow, loginSoonRow, loginAction, helperNeedsCard};', c);
  return {c, api: c.api, acted, toasts};
}

test('nothing shows when every login works or nothing was checked yet', () => {
  for (const logins of [null, {items: []}, {items: [item(), item({name: 'gh', label: 'GitHub'})]}]) {
    const {api} = page(logins);
    const w = api.loginWarnings();
    assert.equal(w.soon.length + w.stopped.length, 0);
    assert.equal(api.blockedLogins(w.stopped).length, 0);
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

// O-01 D and W-017 (28 Nov): a login that stopped is one line with one button in Blocked now, never a red banner
// with a terminal command.
test('a login that stopped working is one row of Blocked now: what stopped, how many tickets, no new work for the main helper, one button', () => {
  const {api} = page({items: [item({name: 'gh', label: 'GitHub', state: 'renew', stops: [T1, T2]})]});
  const [row] = api.blockedLogins(api.loginWarnings().stopped).map(api.loginStoppedRow);
  assert.equal(row.attrs['data-blocked'], 'login');
  assert.equal(text(row), 'The GitHub login stopped working.Helpers stopped on 2 tickets and start no new work.Sign in');
  assert.equal(find(row, n => n.tag === 'button' || n.tag === 'a').length, 1);
  const other = page({items: [item({name: 'wiki', label: 'Company wiki', kind: 'connection', helper: null, state: 'unreachable', chosen: false, stops: [T1]})]});
  assert.equal(text(other.api.loginStoppedRow(other.api.loginWarnings().stopped[0])), 'The Company wiki connection cannot be reached.Helpers stopped on 1 ticket.Try again');
});

test('several things that stopped are one row each; the sign-in of a helper tool that is not the chosen one is left out', () => {
  const {api} = page({items: [item({name: 'gh', label: 'GitHub', state: 'renew', stops: [T1]}),
    item({name: 'codex', label: 'Codex', state: 'renew', helper: 'codex', chosen: false}),
    item({name: 'wiki', label: 'Company wiki', kind: 'connection', state: 'unreachable', helper: null, chosen: false, stops: [T1, T2]}),
    item({name: 'pay', label: 'Payments key', kind: 'key', state: 'renew', helper: null, chosen: false})]});
  const rows = api.blockedLogins(api.loginWarnings().stopped);
  assert.deepEqual(rows.map(i => i.name), ['gh', 'wiki', 'pay']);
  assert.deepEqual(rows.map(i => find(api.loginStoppedRow(i), n => n.tag === 'button' || n.tag === 'a').map(text)), [['Sign in'], ['Try again'], ['Sign in']]);
  assert.equal(find(api.loginStoppedRow(rows[0]), n => n.tag === 'a')[0].attrs.href, '#settings/agent');
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
  assert.equal(shared.api.loginWarnings().stopped.length, 0);  // a snapshot carries no logins
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

// ORCH-218 (owner, 17 Nov): a tool orch cannot sign in itself shows the exact command with one Copy button, in Settings.
// W-017 (28 Nov): Home's line never names a terminal or the command; its one button, Sign in, opens that place.
test('a tool orch cannot renew: Home says one line with Sign in, Settings shows its sign-in command with a Copy button', () => {
  const copies = [];
  const UI = {commandCopy: (cmd, o) => { copies.push([cmd, o]); return {tag: 'div', attrs: {className: 'cmd-copy', 'data-key': o.dataKey}, kids: [o.lead || '', cmd, 'Copy']}; }};
  const az = item({name: 'azure', label: 'Azure CLI', helper: null, chosen: false, state: 'renew', sign_in: 'az login'});
  const {api, c} = page({items: [az]});
  c.window.UI = UI;
  const row = api.loginStoppedRow(api.loginWarnings().stopped[0]);
  assert.equal(text(row), 'The Azure CLI login stopped working.Sign in');
  assert.doesNotMatch(text(row), /terminal|az login|this computer/);
  assert.equal(copies.length, 0);
  const card = api.helperNeedsCard();
  assert.match(text(card), /az loginCopy/);
  // a Renew button or Replace key takes the place: no command then, and none while it works
  assert.equal(helpers.needSignIn({...az, renew: true}), '');
  assert.equal(helpers.needSignIn({...az, key: 'K'}), '');
  assert.equal(helpers.needSignIn({...az, state: 'works'}), '');
  assert.equal(helpers.needSignIn({...az, sign_in: 'az login; rm -rf ~'}), '');
  assert.equal(helpers.needHow({...az, how: 'Ask IT to reset it.'}), 'Ask IT to reset it.');
});

test('a command a helper writes in backticks in its question is offered to copy; names and step ids are not', () => {
  const q = 'The Azure login ran out. Sign in again with `az login`, then `gcloud auth login --update-adc`; see `c1`, `Wiki` and `rm`.';
  assert.deepEqual(helpers.questionCommands(q), ['az login', 'gcloud auth login --update-adc']);
  assert.deepEqual(helpers.questionCommands('no command here'), []);
  assert.deepEqual(helpers.questionCommands('`a b` `c d` `e f`'), ['a b', 'c d']);  // at most two
  assert.equal(helpers.questionWords(q), 'The Azure login ran out. Sign in again with az login, then gcloud auth login --update-adc; see `c1`, `Wiki` and `rm`.');
});

test('a check file that waits for the person says so on Home and in Settings, with no terminal command (#1549)', () => {
  const check = item({name: 'db-dev', label: 'Databricks dev', state: 'unreachable', approve: 'new', runs: 'databricks current-user me',
    hash: '0123456789abcdef0123456789abcdef', how: 'Look at it, then approve it.', sign_in: 'orch checks approve db-dev --hash 0123'});
  assert.deepEqual(helpers.needState(check), {word: 'Not approved yet', tone: 'needs'});
  assert.equal(helpers.needSignIn(check), '');  // the Approve button takes its place
  assert.equal(helpers.needKindWord({kind: 'tool'}), 'Tool');
  assert.deepEqual(helpers.needState({...check, approve: 'broken', runs: undefined, hash: undefined}), {word: 'Cannot be read', tone: 'error'});
  const {api} = page({items: [check]});
  const own = {tag: 'button', attrs: {}, kids: ['Approve']};
  const b = page({items: [check]}, {renewButton: () => own}).api.loginStoppedRow(api.loginWarnings().stopped[0]);
  assert.match(text(b), /^The Databricks dev login waits for you to approve it\.Approve$/);
  assert.doesNotMatch(text(b), /orch checks approve/);
});
