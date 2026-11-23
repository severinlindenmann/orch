'use strict';
// ORCH-37 (owner picked B): a release is a ticket of its own; its epics and tickets sit under it. The Tickets list and
// the phone list show each release as one group with its whole tree; the ticket page has a Release switch.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const ticketSrc = fs.readFileSync(path.join(WEB, 'pages/ticket.js'), 'utf8');
const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; }, dataset:{}, style:{}, classList:{add() {}}});
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];

const at = n => '2026-11-17T0' + n + ':00:00Z';
const ALL = [
  {id:'r26', title:'Release 26', status:'open', release:true, created_at:at(1)},
  {id:'r25', title:'Release 25', status:'done', release:true, created_at:at(0)},
  {id:'ep', title:'Ticket flow', status:'active', epic:true, parent:'r26', created_at:at(2)},
  {id:'la', title:'Board lanes', status:'done', parent:'ep', created_at:at(3)},
  {id:'tr', title:'Triage', status:'review', parent:'ep', created_at:at(4)},
  {id:'fx', title:'Fix login', status:'open', parent:'r26', created_at:at(5)},
  {id:'old', title:'Old fix', status:'done', parent:'r25', created_at:at(0)},
  {id:'lo', title:'Loose idea', status:'open', created_at:at(6)},
];

function listCtx(items = ALL) {
  const c = {h, fragment:(...k) => h('frag', {}, ...k), window:{DashHelpers:helpers, UI:{}}, array:v => Array.isArray(v) ? v : [], clean:String,
    questions:t => (t.questions || []).filter(q => q.answer == null), shown:t => t, chip:(t, cls) => h('span', {className:'chip ' + cls}, t),
    statusChip:t => h('span', {className:'chip'}, t.status), state:{runs:{}}, starting:new Set(), needsList:() => [], tickets:() => items,
    name:v => String(v || ''), location:{hash:'#tickets'}, snapshot:true, href:id => '#t/' + id, render() {}, iconEl:() => null, now:() => Date.now(),
    titleTag:() => null, parentLine:t => h('p', {}, 'Sub-ticket of ' + t.parent), localStorage:{getItem:() => null, setItem() {}},
    button:(label, cls) => h('button', {className:'btn ' + cls}, label)};
  vm.createContext(c); vm.runInContext(listSrc, c); return c;
}

test('releases come first as their own groups: open ones first, a finished one after; loose tickets stay in status groups', () => {
  const c = listCtx();
  const {groups, inRelease} = c.releaseGroups(ALL);
  assert.deepEqual([...groups.map(g => g.title)], ['Release 26', 'Release 25']);
  assert.equal(groups[0].total, 4);
  c.g = groups[0];
  assert.equal(vm.runInContext('releaseCount(g)', c), '1 of 4 done');
  assert.ok(groups[1].finished);
  assert.ok(inRelease.has('r26') && inRelease.has('la') && !inRelease.has('lo'));
});

test('the list shows Release > Epic > Task as one tree, every row with its status, no "Sub-ticket of" line', () => {
  const c = listCtx();
  const table = c.ticketTable(ALL);
  const heads = nodes(table).filter(n => n.attrs?.className === 'group-row').map(text);
  assert.match(heads[0], /^⌄ Release 26 1 of 4 done/);
  assert.match(heads[1], /^› Release 25/, 'a finished release starts folded');
  assert.ok(heads.slice(2).some(s => /To do/.test(s) || /Backlog/.test(s) || /Ready/.test(s)), 'a status group follows for loose tickets');
  const rows = nodes(table).filter(n => n.attrs?.['data-key']?.startsWith('tree-')).map(n => n.attrs['data-key']);
  assert.deepEqual(rows.slice(0, 4), ['tree-ep', 'tree-la', 'tree-tr', 'tree-fx'], 'the epic, its tickets, then the next ticket of the release');
  assert.ok(rows.includes('tree-lo') && !rows.includes('tree-r26') && !rows.includes('tree-old'));
  const fix = nodes(table).find(n => n.attrs?.['data-key'] === 'tree-fx');
  assert.match(text(fix), /open/, 'the row carries its status chip');
  assert.doesNotMatch(text(fix), /Sub-ticket of/);
  assert.ok(nodes(table).some(n => n.attrs?.['data-key'] === 'release-open-r26' && text(n) === 'Open release'));
});

test('no release: the list is grouped by status exactly as before', () => {
  const c = listCtx(ALL.filter(t => !t.release).map(({parent, ...t}) => t));
  const heads = nodes(c.ticketTable(c.tickets())).filter(n => n.attrs?.className === 'group-row').map(text);
  assert.ok(heads.length && !heads.some(s => /Release/.test(s)));
});

test('ORCH-576: a release tile has the Release tag and its parts bar; a ticket under it says Part of: <release>', () => {
  assert.match(listSrc, /t\.release \? 'Release' : t\.epic \? 'Epic'/);
  assert.match(listSrc, /' tickets in this ' \+ boardKind\(t\)\.toLowerCase\(\)/);
  assert.match(listSrc, /'Part of: ' \+ clean\(parent\.title\)/);
});

test('ticket page: a Release switch in Properties, "Tickets in this release", releases first in Part of', () => {
  // ORCH-581: the row shows once the ticket is a release; "Mark as a release" in + Add turns it on
  assert.match(ticketSrc, /show\('release', !!t\.release\) \? field\('Release', releaseField\(t\), 'release'\)/);
  assert.match(ticketSrc, /\[!t\.release, 'release', 'Mark as a release'\]/);
  assert.match(ticketSrc, /role:'switch', 'aria-checked':String\(on\), 'aria-label':'This ticket is a release'/);
  assert.match(ticketSrc, /act\('ticket\.edit', \{ticket:t\.id, release:!on/);
  assert.match(ticketSrc, /t\.release \? 'Tickets in this release'/);
  assert.match(ticketSrc, /parent\.release \? 'Part of the release '/);
  const all = [{id:'e', epic:true, created_at:at(1)}, {id:'r', release:true, created_at:at(0)}, {id:'p', created_at:at(2)}, {id:'me', created_at:at(3)}];
  assert.deepEqual(helpers.parentChoices(all, all[3]).map(t => t.id), ['r', 'e', 'p']);
});
