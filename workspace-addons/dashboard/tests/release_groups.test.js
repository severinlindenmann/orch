'use strict';
// ORCH-37: tickets carry a release; the Tickets list and the phone list can group by it; Properties shows it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const ticketSrc = fs.readFileSync(path.join(WEB, 'pages/ticket.js'), 'utf8');
const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; }, dataset:{}, classList:{add() {}}});
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];

const ALL = [
  {id:'a', title:'Board lanes', status:'active', release:'27'},
  {id:'b', title:'Triage', status:'open', release:'26'},
  {id:'c', title:'Old fix', status:'done', release:'25'},
  {id:'d', title:'Loose idea', status:'open'},
  {id:'e', title:'Release tag', status:'review', release:'26'},
];

function listCtx(group, items = ALL) {
  const store = {'orch.tickets.group':group};
  const c = {h, fragment:(...k) => h('frag', {}, ...k), window:{DashHelpers:helpers, UI:{}}, array:v => Array.isArray(v) ? v : [], clean:String,
    questions:t => (t.questions || []).filter(q => q.answer == null), shown:t => t, chip:(t, cls) => h('span', {className:'chip ' + cls}, t),
    statusChip:t => h('span', {className:'chip'}, t.status), state:{runs:{}}, starting:new Set(), needsList:() => [], tickets:() => items,
    name:v => String(v || ''), location:{hash:'#tickets'}, snapshot:true, href:id => '#t/' + id, render() {}, iconEl:() => null, now:() => Date.now(),
    titleTag:() => null, parentLine:() => null, localStorage:{getItem:k => store[k] ?? null, setItem:(k, v) => { store[k] = v; }},
    button:(label, cls) => h('button', {className:'btn ' + cls}, label)};
  vm.createContext(c); vm.runInContext(listSrc, c); return c;
}

test('release groups: open releases lowest first, finished releases after, No release last', () => {
  const c = listCtx('release');
  const groups = c.releaseGroups(ALL);
  assert.deepEqual([...groups.map(g => g.title)], ['Release 26', 'Release 27', 'Release 25', 'No release']);
  c.g = groups[0];
  assert.equal(vm.runInContext('releaseCount(g)', c), '0 of 2 done');
  assert.ok(groups[2].finished);
  assert.equal(vm.runInContext("releaseTitle('Spring launch')", c), 'Spring launch', 'a named release is shown as written');
});

test('the list grouped by release: one group head per release, each row says its status, a finished release starts folded', () => {
  const c = listCtx('release');
  const table = c.ticketTable(ALL);
  const heads = nodes(table).filter(n => n.attrs?.className === 'group-row').map(text);
  assert.deepEqual(heads.map(s => s.replace(/^[⌄›] /, '')), ['Release 26 0 of 2 done', 'Release 27 0 of 1 done', 'Release 25 1 of 1 done', 'No release 0 of 1 done']);
  assert.ok(heads[2].startsWith('›'), 'the finished release is folded');
  const rows = nodes(table).filter(n => n.attrs?.['data-key']?.startsWith('tree-'));
  assert.deepEqual(rows.map(r => r.attrs['data-key']), ['tree-b', 'tree-e', 'tree-a', 'tree-d']);
  assert.match(text(rows[1]), /review/, 'the row carries its status chip, since the group no longer says it');
});

test('by status stays the default; the Group choice shows only once a ticket has a release', () => {
  const plain = listCtx(null);
  const heads = nodes(plain.ticketTable(ALL)).filter(n => n.attrs?.className === 'group-row').map(text);
  assert.ok(!heads.some(s => /Release/.test(s)), 'grouped by status');
  assert.ok(nodes(h('div', {}, plain.ticketFilters())).some(n => n.attrs?.['data-key'] === 'ticket-group'));
  const none = listCtx(null, ALL.map(({release, ...t}) => t));
  assert.ok(!nodes(h('div', {}, none.ticketFilters())).some(n => n.attrs?.['data-key'] === 'ticket-group'), 'no releases: no choice');
});

test('search finds a ticket by its release', () => {
  const c = listCtx(null);
  assert.deepEqual([...c.filterTickets(ALL, '27', false).map(t => t.id)], ['a']);
});

test('the ticket page shows a Release row in Properties and offers the release names already used', () => {
  assert.match(ticketSrc, /field\('Release', inlineField\(t, 'release'\)\)/);
  assert.match(ticketSrc, /release:'Not set'/);
  assert.match(ticketSrc, /h\('datalist', \{id:'release-names-' \+ t\.id\}/);
});
