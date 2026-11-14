// Sync card (Settings › General, draft sync-card.html Variant A) and the sync rows on Home › Needs you.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const PAGES = path.join(__dirname, '../src/orch_dashboard/web/pages');
function node(tag, attrs = {}, children = []) {
  return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false), dataset:{}, listeners:{},
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }, append(...kids) { this.children.push(...kids.filter(Boolean)); },
    querySelectorAll() { return []; }};
}
const text = n => n == null ? '' : typeof n === 'string' || typeof n === 'number' ? String(n) : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
const byKey = (n, key) => all(n, x => x.attrs?.['data-key'] === key || x.dataset?.key === key)[0];
const click = async n => { for (const fn of n.listeners.click || []) await fn({preventDefault() {}}); };

// reviews: the add-on's {target, review} answer to the review phase (`review: true`), per verb
function context({settings = {}, needs = [], answers = {}, reviews = {}} = {}) {
  const calls = [], dialogs = [], toasts = [];
  const c = vm.createContext({
    window:{DashHelpers:helpers, orch:{toast:(t, k) => toasts.push([t, k]), open() {}, close:async () => {}}},
    localStorage:{store:{}, getItem(k) { return this.store[k] ?? null; }, setItem(k, v) { this.store[k] = v; }},
    h:(tag, attrs, ...children) => node(tag, attrs || {}, children), fragment:(...children) => node('fragment', {}, children),
    el:(tag, cls, t) => node(tag, {className:cls}, t === undefined ? [] : [t]),
    button:(t, cls, fn) => { const b = node('button', {className:'btn ' + cls}, [t]); b.listeners.click = [fn]; return b; },
    iconEl:name => node('icon', {name}), array:v => Array.isArray(v) ? v : [], snapshot:false, clean:v => String(v ?? ''),
    name:v => String(v ?? '').replace(/^(human|agent):/, ''), capitalise:v => String(v).replace(/^./, x => x.toUpperCase()),
    time:v => v ? '10:15' : '', today:() => '2026-11-11', render() {}, route:() => ({kind:'settings'}), location:{hash:'#settings'},
    requestAnimationFrame:fn => fn(), queueMicrotask() {}, setTimeout:() => 1, clearTimeout() {}, document:{getElementById:() => null},
    locks:new Set(), changeUnavailable:() => false, changeError:r => r.text, previewFile:(...a) => calls.push(JSON.parse(JSON.stringify(['preview', ...a]))),
    tickets:() => [], ticketOf:() => null, needsList:() => needs, questions:() => [], shown:t => t, href:id => '#ticket/' + id,
    chip:(t, cls) => node('span', {className:'chip ' + cls}, [t]), statusChip:() => null, heading:(...t) => node('h1', {}, t),
    now:() => new Date('2026-11-11T13:00:00'), parse:() => null, emptyRow:t => node('p', {}, [t]), card:(k, t, s, b) => node('section', {}, [t, b]),
    activeTicket:() => true, sorted:v => v, state:{who:'mia', settings, needs}, addons:() => [], addonLabel:a => a?.dashboard?.label || a?.name,
    dialog:title => { const d = node('dialog', {title}), actions = node('div', {className:'actions'}); dialogs.push({d, actions, title}); return {d, actions}; },
    URL,
    act:async (op, args) => {
      calls.push(JSON.parse(JSON.stringify([op, args])));  // plain objects of this realm
      if (args?.review) return reviews[args.verb] ? {ok:true, state:{act_answer:{addon:args.addon, answer:reviews[args.verb]}}} : {ok:false, text:'This file is not waiting for a choice'};
      const answer = typeof answers[args?.verb] === 'function' ? answers[args.verb](args) : answers[args?.verb];
      return {ok:true, state:{act_answer:{addon:'sync', answer:answer ?? {}}}};
    },
  });
  for (const file of ['home', 'settings']) vm.runInContext(fs.readFileSync(path.join(PAGES, file + '.js'), 'utf8'), c);
  return {c, calls, dialogs, toasts, ui:vm.runInContext('syncUi', c)};
}
const BASE = {mode:'remote', remote:'https://files.example.org/mia/month-end', confirmed:true, unconfirmed:false, interval:15, shown:'synced', last_ok:'2026-11-11T09:15:00Z',
  last_try:'2026-11-11T09:15:00Z', last_error:null, paused_needs:0, not_synced:[], public:null, remote_allowed:true, running:true};
const ON = {addons:[{name:'sync', active:true, consent:'sync 1.0'}]};

test('add-on off: one switch row that turns it on through the add-on switch path; not installed: no card', () => {
  const {c} = context();
  assert.equal(c.syncCard({addons:[]}), null);
  const row = c.syncCard({addons:[{name:'sync', active:false, consent:'sync 1.0'}]});
  assert.equal(text(row), 'Keep a copy of my tickets');
  const sw = byKey(row, 'settings-switch-sync-off');
  assert.deepEqual([sw.attrs.role, sw.attrs['aria-checked'], sw.attrs['data-action'], sw.attrs['data-name']], ['switch', false, 'settings-addon', 'sync']);
  assert.equal(all(row, n => n.tag === 'fieldset').length, 0);
});

test('Settings › General: the Sync card comes right after Workspace', () => {
  const {c, ui} = context({settings:{...ON, folder:'/Users/mia/close'}});
  ui.card = {...BASE};
  const general = all(c.settingsPage(), n => n.attrs?.id === 'settings-panel-general')[0];
  const keys = general.children.map(n => n.attrs?.['data-key']).filter(Boolean);
  assert.equal(keys[keys.indexOf('settings-workspace') + 1], 'settings-sync');
});

test('turned on just now: "On this computer only" is offered in the review line, nothing saved without Save', async () => {
  const {c, calls, ui} = context({answers:{status:{...BASE, mode:'off', remote:null, shown:'off'}}});
  c.syncCard({addons:[{name:'sync', active:false}]});
  await c.syncLoad();
  assert.deepEqual(calls.map(([, a]) => a.verb), ['status']);
  const card = c.syncCard(ON);
  assert.equal(byKey(card, 'sync-where-local').checked, true);
  assert.equal(text(byKey(card, 'sync-review-text')), 'Sync will keep a copy on this computer only.');
  assert.equal(ui.draft.where, 'local');
});

test('the status line, one state at a time; files not synced; Details with the last error and the names', () => {
  const {c, ui} = context();
  const cases = {synced:'Last synced 10:15', never:'Not synced yet', offline:'Offline, will sync when connected', syncing:'Syncing…', paused:'Paused, review below'};
  for (const [shown, want] of Object.entries(cases)) {
    ui.card = {...BASE, shown};
    const card = c.syncCard(ON);
    assert.equal(text(byKey(card, 'sync-status')), want, shown);
    const link = byKey(card, 'sync-paused-link');
    assert.equal(!!link, shown === 'paused', shown);
    if (link) assert.equal(link.attrs.href, '#home');
    assert.match(byKey(card, 'sync-status').attrs.className, shown === 'paused' ? /you/ : /^sync-status$/);
  }
  ui.card = {...BASE, shown:'offline', last_error:'offline', not_synced:[{name:'scans-march.zip', why:'too big, stays on this computer'},
    {name:'payroll-access.txt', why:'may contain a password or access key'}]};
  const card = c.syncCard(ON);
  assert.equal(text(byKey(card, 'sync-skipped')), '2 files not synced');
  assert.equal(text(byKey(card, 'sync-last-error')), 'Last error 10:15: could not reach the sync address.');
  assert.deepEqual(all(byKey(card, 'sync-details'), n => n.tag === 'li').map(text),
    ['Last error 10:15: could not reach the sync address.', 'Not synced: scans-march.zip (too big, stays on this computer)', 'Not synced: payroll-access.txt (may contain a password or access key)']);
  ui.card = {...BASE, mode:'off', shown:'off'};
  const off = c.syncCard(ON);
  assert.equal(byKey(off, 'sync-status'), undefined);
  assert.equal(byKey(off, 'sync-details'), undefined);
  assert.equal(byKey(off, 'sync-where-off').checked, true);
  assert.doesNotMatch(text(c.syncCard(ON)), /\b(git|rebase|commit|branch|VPN)\b/i);
});

test('the card has the draft parts: where, sync address with Check connection, Sync every chips, Sync now', async () => {
  const {c, calls, ui} = context({answers:{check:a => ({ok:a.target.startsWith('https://files')})}});
  ui.card = {...BASE};
  const card = c.syncCard(ON);
  assert.equal(text(all(card, n => n.tag === 'legend')[0]), 'Where to keep a copy');
  assert.deepEqual(all(card, n => n.attrs?.type === 'radio').map(n => [n.attrs.value, n.checked]), [['off', false], ['local', false], ['remote', true]]);
  assert.equal(byKey(card, 'sync-addr').attrs.value, 'https://files.example.org/mia/month-end');
  assert.deepEqual(['5', '15', '60'].map(v => [text(byKey(card, 'sync-every-' + v)), byKey(card, 'sync-every-' + v).attrs['aria-pressed']]), [['5 min', false], ['15 min', true], ['1 hour', false]]);
  assert.equal(byKey(card, 'sync-now').attrs.className, 'btn primary');
  assert.equal(byKey(card, 'sync-review'), undefined, 'no review line while nothing changed');
  await click(byKey(card, 'sync-check'));
  assert.deepEqual(calls.at(-1), ['addon.act', {addon:'sync', verb:'check', target:'https://files.example.org/mia/month-end'}]);
  assert.equal(text(byKey(c.syncCard(ON), 'sync-check-res')), 'Connection works');
  ui.draft = {...vm.runInContext('syncNow()', c), addr:'https://nowhere.example'};
  await click(byKey(c.syncCard(ON), 'sync-check'));
  assert.equal(text(byKey(c.syncCard(ON), 'sync-check-res')), 'Can’t reach this address');
});

const SET_TARGET = 'sync:set-remote:' + 'c'.repeat(64);
const SET_REVIEW = {target:SET_TARGET, review:{title:'Sync to this address?', body:'Your tickets and their files are copied there every 60 minutes.', value:'https://box.example.net/orch'}};

test('changing the choice, address or interval shows a review line; Undo drops it, Save sends the click', async () => {
  const {c, calls, ui, toasts, dialogs} = context({answers:{set:{mode:'remote'}, status:{...BASE, remote:'https://box.example.net/orch', interval:60}}, reviews:{set:SET_REVIEW}});
  ui.card = {...BASE, mode:'off', remote:null, shown:'off'};
  ui.draft = {where:'remote', addr:'https://box.example.net/orch', every:'60'};
  let card = c.syncCard(ON);
  assert.equal(text(byKey(card, 'sync-review-text')), 'Sync will copy tickets to box.example.net every 1 hour.');
  assert.deepEqual(all(byKey(card, 'sync-review'), n => n.tag === 'button').map(text), ['Undo', 'Save']);
  await click(byKey(card, 'sync-review-save'));
  // choosing the address is signed: the add-on's review first (the exact address), then Sign echoes its target
  assert.deepEqual(calls, [['addon.act', {addon:'sync', verb:'set', target:'https://box.example.net/orch', value:'60', review:true}]]);
  const {d, actions, title} = dialogs.at(-1);
  assert.equal(title, 'Sync to this address?');
  assert.equal(text(byKey(d, 'sign-value')), 'https://box.example.net/orch');
  await click(byKey(actions, 'sign-ok'));
  assert.deepEqual(calls.slice(-2), [['addon.act', {addon:'sync', verb:'set', target:'https://box.example.net/orch', value:'60', sign:true, seen:SET_TARGET}], ['addon.act', {addon:'sync', verb:'status', target:'sync'}]]);
  assert.deepEqual(toasts.at(-1), ['Signed. Sync address chosen.', 'ok']);
  assert.equal(ui.draft, null);
  // the same address, only how often: no sign step
  ui.card = {...BASE, remote:'https://box.example.net/orch', interval:60};
  ui.draft = {where:'remote', addr:'https://box.example.net/orch', every:'5'};
  await click(byKey(c.syncCard(ON), 'sync-review-save'));
  assert.deepEqual(calls.at(-2), ['addon.act', {addon:'sync', verb:'set', target:'https://box.example.net/orch', value:'5'}]);
  assert.equal(dialogs.length, 1);
  assert.equal(byKey(c.syncCard(ON), 'sync-review'), undefined);
  ui.draft = {where:'off', addr:'', every:'15'};
  card = c.syncCard(ON);
  assert.equal(text(byKey(card, 'sync-review-text')), 'Sync will stop. Your tickets stay on this computer as they are.');
  await click(all(byKey(card, 'sync-review'), n => n.tag === 'button')[0]);
  assert.equal(ui.draft, null);
  ui.draft = {where:'remote', addr:'  ', every:'15'};
  card = c.syncCard(ON);
  assert.equal(text(byKey(card, 'sync-review-text')), 'Enter a sync address first.');
  assert.equal(byKey(card, 'sync-review-save').disabled, true);
  ui.draft = {where:'local', addr:'', every:'15'};
  await click(byKey(c.syncCard(ON), 'sync-review-save'));
  assert.deepEqual(calls.at(-2), ['addon.act', {addon:'sync', verb:'set', target:'local'}]);
});

test('Sync now while paused is secondary and never clears the pause: "Still paused: N things need you"', async () => {
  const paused = {...BASE, shown:'paused', paused_needs:2, last_error:'Not synced: tickets/t_abc123.json: conflict'};
  const {c, calls, ui} = context({answers:{now:{still_paused:2, text:'Still paused: 2 things need you'}, status:paused}});
  ui.card = paused;
  const card = c.syncCard(ON);
  assert.equal(byKey(card, 'sync-now').attrs.className, 'btn ghost');
  await click(byKey(card, 'sync-now'));
  assert.deepEqual(calls.map(([, a]) => a.verb), ['now', 'status']);
  const after = c.syncCard(ON);
  assert.equal(text(byKey(after, 'sync-note')), 'Still paused: 2 things need you');
  assert.equal(text(byKey(after, 'sync-status')), 'Paused, review below');
});

const PUBLIC_TARGET = 'sync:use-public:' + 'd'.repeat(64);

test('a public sync address: the warning, Use public location goes through the sign step, Keep on this computer', async () => {
  // the card's own `public` text and the address the add-on signs differ: the dialog shows only the add-on's review
  const {c, calls, ui, dialogs, toasts} = context({answers:{status:{...BASE, mode:'local', shown:'synced', public:'https://github.com/mia/orch'}, 'use-public':{mode:'remote'}, set:{mode:'local'}},
    reviews:{'use-public':{target:PUBLIC_TARGET, review:{title:'Use a public location?', body:'Anyone who knows the address can read your tickets.', value:'https://github.com/mia/orch-public'}}}});
  ui.card = {...BASE, mode:'local', public:'https://github.com/mia/orch'};
  const card = c.syncCard(ON);
  const warn = byKey(card, 'sync-public');
  assert.equal(warn.attrs.role, 'alert');
  assert.equal(text(all(warn, n => n.tag === 'p')[0]), 'This sync address is public. Anyone can read your tickets.');
  const [use, keep] = all(warn, n => n.tag === 'button');
  assert.deepEqual([text(use), text(keep)], ['Use public location', 'Keep on this computer']);
  await click(use);
  assert.deepEqual(calls, [['addon.act', {addon:'sync', verb:'use-public', target:'pending', review:true}]], 'only the review before the person signs');
  const {d, actions, title} = dialogs.at(-1);
  assert.equal(title, 'Use a public location?');
  assert.equal(text(byKey(d, 'sign-value')), 'https://github.com/mia/orch-public', 'the exact address the add-on signs');
  assert.match(text(d), /Anyone who knows the address can read your tickets\. You sign this as mia\./);
  await click(byKey(actions, 'sign-ok'));
  assert.deepEqual(calls[1], ['addon.act', {addon:'sync', verb:'use-public', target:'pending', sign:true, seen:PUBLIC_TARGET}]);
  assert.deepEqual(toasts.at(-1), ['Signed. Using the public location.', 'ok']);
  await click(keep);
  assert.deepEqual(calls.find(([, a]) => a.verb === 'set'), ['addon.act', {addon:'sync', verb:'set', target:'local'}]);
});

const ROWS = [
  {id:'sync:paused:abc', source:'sync', kind:'sync:paused', ticket:null, title:'t_abc123.json', tone:'needs-you', since:'2026-11-11T10:12:00Z',
    text:'Sync paused: “Close March books” changed here and on another computer.', answer:{question:'q1', options:['Keep mine', 'Keep theirs'], recommended:null},
    actions:[{label:'Keep mine', verb:'keep-mine', target:'tickets/t_abc123.json', sign:true, review:{title:'Keep your version of “Close March books”?', body:'The change from the other computer is set aside.', here:'Due: 2026-03-31', there:'Note: bank fees', done:'Kept your version.'}},
      {label:'Keep theirs', verb:'keep-theirs', target:'tickets/t_abc123.json', sign:true, review:{title:'Keep the other computer’s version of “Close March books”?', body:'The change made here is set aside.', here:'Due: 2026-03-31', there:'Note: bank fees', done:'Kept the other version.'}}]},
  {id:'sync:move:orch-files', source:'sync', kind:'sync:move', ticket:null, title:'Sync', tone:'needs-you', since:'2026-11-11T10:12:00Z',
    text:'Move your orch files out of the team repository?',
    actions:[{label:'Move', op:'private.move', sign:true, review:{title:'Move your orch files out of the team repository?', body:'Why: … Where: …', done:'Moved your orch files.'}}, {label:'Not now', later:true}]},
  {id:'sync:secret:def', source:'sync', kind:'sync:secret', ticket:null, title:'payroll-access.txt', tone:'needs-you', since:'2026-11-11T10:12:00Z',
    text:'Not synced: payroll-access.txt may contain a password or access key.',
    actions:[{label:'Leave it out', verb:'leave-out', target:'tickets/t_abc123/artifacts/payroll-access.txt', sign:true, review:{title:'Leave payroll-access.txt out of sync?', body:'It stays on this computer only.', done:'Left out. It stays on this computer.'}},
      {label:'View file', view:{ticket:'t_abc123', name:'payroll-access.txt'}}]},
];

test('Home › Needs you: the three sync rows in the draft words, with "Needs your signature" and their buttons', () => {
  const {c} = context({needs:ROWS});
  vm.runInContext('needsOpen = true', c);
  const home = c.home();
  const rows = all(home, n => String(n.attrs?.className || '').includes('need-acts'));
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map(r => text(all(r, n => n.tag === 'p')[0])), ROWS.map(r => r.text));
  assert.deepEqual(rows.map(r => text(all(r, n => n.tag === 'p')[1])), ['Sync', 'Sync', 'Sync']);
  assert.deepEqual(rows.map(r => all(r, n => n.attrs?.className === 'sig').map(text)), [['Needs your signature'], ['Needs your signature'], ['Needs your signature']]);
  assert.deepEqual(rows.map(r => all(r, n => n.tag === 'button').map(text)), [['Keep mine', 'Keep theirs'], ['Move', 'Not now'], ['Leave it out', 'View file']]);
  assert.match(text(home), /Needs you · 3/);
});

const KEEP_TARGET = 'sync:keep-theirs:' + 'e'.repeat(64);
// the add-on's own review of the click (from the bytes it hashes): deliberately not the row's words
const KEEP_REVIEW = {target:KEEP_TARGET, review:{title:'Keep the other computer’s version of “Close March books (v2)”?', body:'The change made here is set aside.',
  here:'due: 2026-03-31; note: (none)', there:'due: (none); note: bank fees'}};

test('a signed need shows the add-on’s review (not the row’s) and signs the target it showed; Move uses the signed core op', async () => {
  const {c, calls, dialogs, toasts} = context({needs:ROWS, reviews:{'keep-theirs':KEEP_REVIEW}});
  const row = c.needRow(ROWS[0], null);
  await click(all(row, n => n.tag === 'button')[1]);
  assert.deepEqual(calls, [['addon.act', {addon:'sync', verb:'keep-theirs', target:'tickets/t_abc123.json', review:true}]], 'only the review before Sign');
  const {d, actions, title} = dialogs.at(-1);
  assert.equal(title, 'Keep the other computer’s version of “Close March books (v2)”?');
  assert.deepEqual(all(d, n => n.tag === 'li').map(text), ['Here: due: 2026-03-31; note: (none)', 'Other computer: due: (none); note: bank fees']);
  assert.doesNotMatch(text(d), /Due: 2026-03-31|Note: bank fees/, 'never the row’s own text');
  assert.match(text(d), /The change made here is set aside\. You sign this as mia\./);
  assert.match(text(byKey(actions, 'sign-ok')), /Sign/);
  await click(byKey(actions, 'sign-ok'));
  assert.deepEqual(calls[1], ['addon.act', {addon:'sync', verb:'keep-theirs', target:'tickets/t_abc123.json', sign:true, seen:KEEP_TARGET}]);
  assert.deepEqual(toasts.at(-1), ['Signed. Kept the other version.', 'ok']);
  await click(all(c.needRow(ROWS[1], null), n => n.tag === 'button')[0]);
  await click(byKey(dialogs.at(-1).actions, 'sign-ok'));
  assert.deepEqual(calls[2], ['private.move', {}]);
  await click(all(c.needRow(ROWS[2], null), n => n.tag === 'button')[1]);
  assert.deepEqual(calls[3], ['preview', 't_abc123', 'artifacts', 'payroll-access.txt']);
});

test('no review from the add-on: no sign step, nothing signed', async () => {
  const {c, calls, dialogs, toasts} = context({needs:ROWS});
  await click(all(c.needRow(ROWS[0], null), n => n.tag === 'button')[0]);
  assert.equal(dialogs.length, 0);
  assert.deepEqual(calls.map(([, a]) => [a.verb, !!a.review, !!a.sign]), [['keep-mine', true, false]]);
  assert.deepEqual(toasts.at(-1), ['This file is not waiting for a choice', 'error']);
});

test('private.move in a row: only from the sync add-on, always with the core’s own label and wording', async () => {
  const sneaky = {...ROWS[1], id:'sync:move:x', actions:[{label:'Keep mine', op:'private.move', sign:true, review:{title:'Keep your version?', body:'Nothing changes.', done:'Kept.'}}]};
  const {c, calls, dialogs} = context({needs:[sneaky]});
  const row = c.needRow(sneaky, null);
  const [move] = all(row, n => n.tag === 'button');
  assert.equal(text(move), 'Move', 'the row’s label is never shown for a core op');
  await click(move);
  const {d, title} = dialogs.at(-1);
  assert.equal(title, 'Move your orch files out of the team repository?');
  assert.match(text(d), /everyone on the team sees each change/);
  assert.doesNotMatch(text(d), /Keep your version|Nothing changes/);
  await click(byKey(dialogs.at(-1).actions, 'sign-ok'));
  assert.deepEqual(calls, [['private.move', {}]]);
  // from any other add-on: no button at all (also not when it names a verb next to the op)
  for (const source of ['insights', 'automation']) {
    const other = {...sneaky, source, id:source + ':move:x'};
    assert.equal(all(c.needRow(other, null), n => String(n.attrs?.className || '').includes('need-acts')).length, 0, source);
    const mixed = {...other, actions:[{label:'Move', op:'private.move', verb:'move', sign:true}]};
    assert.equal(all(c.needRow(mixed, null), n => String(n.attrs?.className || '').includes('need-acts')).length, 0, source + ' op+verb');
  }
  const smuggled = {...sneaky, actions:[{label:'Fix', op:'ticket.patch', verb:'fix'}]};
  assert.equal(all(c.needRow(smuggled, null), n => String(n.attrs?.className || '').includes('need-acts')).length, 0, 'an op next to a verb is not a verb');
});

test('Not now waits a day; a row may not name any other core op; snapshots show no buttons', async () => {
  const {c, calls} = context({needs:ROWS});
  await click(all(c.needRow(ROWS[1], null), n => n.tag === 'button')[1]);
  assert.equal(calls.length, 0);
  assert.equal(all(c.home(), n => String(n.attrs?.className || '').includes('need-acts')).length, 2);
  const acts = n => all(n, x => String(x.attrs?.className || '').includes('need-acts') && !String(x.attrs?.className).includes('need-notice')).length;
  const evil = {...ROWS[1], id:'sync:x:y', actions:[{label:'Delete', op:'ticket.patch', sign:true}]};
  assert.equal(acts(c.needRow(evil, null)), 0);
  const core = {...ROWS[0], source:'core'};
  assert.equal(acts(c.needRow(core, null)), 0);
});

// Owner feedback 14 Nov, fb14: a row with answer options but no ticket and no buttons showed as a ticket question
// titled ".json"; every click failed with "That is not a ticket id." and it could not be removed.
test('a row with options but no ticket and no buttons is a notice in plain words that can always be dismissed', async () => {
  const stuck = {id:'sync:paused:zz', source:'sync', kind:'sync:paused', ticket:null, title:'.json', tone:'needs-you', since:'2026-11-11T10:12:00Z',
    text:'Sync paused: “.json” changed here and on another computer.', answer:{question:'q1', options:['Keep mine', 'Keep theirs'], recommended:null}};
  const {c, calls} = context({needs:[stuck]});
  const row = c.needRow(stuck, null);
  const labels = all(row, n => n.tag === 'button').map(text);
  assert.deepEqual(labels, ['Not now'], 'no answer buttons that can only fail');
  assert.match(text(row), /Sync paused/);
  assert.doesNotMatch(text(row), /Choose an answer|Write your own/);
  await click(all(row, n => n.tag === 'button')[0]);
  assert.equal(calls.length, 0);
  assert.equal(all(c.home(), n => String(n.attrs?.className || '').includes('home-need')).length, 0, 'gone for today');
});
