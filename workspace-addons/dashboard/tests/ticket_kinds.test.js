'use strict';
// ORCH-906 (owner picked it, 20 Nov): an epic or a release says so wherever the ticket shows (list row, ticket page
// header, board card), and a release with no tickets yet reads "No tickets yet", never "0 of 0 done".
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

test('kindTag: a chip "Epic" or "Release", nothing for a plain ticket', () => {
  assert.equal(helpers.kindWord({release:true, epic:true}), 'Release');
  assert.equal(helpers.kindWord({epic:true}), 'Epic');
  assert.equal(helpers.kindWord({}), '');
  assert.equal(helpers.kindTag({id:'x'}, h), null);
  const tag = helpers.kindTag({epic:true}, h)[1];
  assert.equal(tag.attrs.className, 'chip kind');
  assert.equal(text(tag), 'Epic');
});

test('list row: the epic row carries an "Epic" chip, a plain ticket none', () => {
  const c = listCtx();
  const table = c.ticketTable(ALL);
  const row = key => nodes(table).find(n => n.attrs?.['data-key'] === key);
  assert.ok(nodes(row('tree-ep')).some(n => n.attrs?.['data-key'] === 'kind-epic' && text(n) === 'Epic'));
  assert.ok(!nodes(row('tree-fx')).some(n => String(n.attrs?.['data-key'] || '').startsWith('kind-')));
});

test('an empty release reads "No tickets yet", never "0 of 0 done"', () => {
  const items = [...ALL, {id:'r30', title:'Release 30', status:'open', release:true, created_at:at(7)}];
  const c = listCtx(items);
  const heads = nodes(c.ticketTable(items)).filter(n => n.attrs?.className === 'group-row').map(text);
  const empty = heads.find(s => /Release 30/.test(s));
  assert.ok(empty, 'the empty release still has its group');
  assert.match(empty, /No tickets yet/);
  assert.ok(!heads.some(s => /0 of 0/.test(s)));
  assert.ok(heads.some(s => /Release 26 1 of 4 done/.test(s)), 'a release with tickets keeps its count');
});

test('ticket page header (both variants) and an empty board card show the kind', () => {
  assert.match(ticketSrc, /const head = \[window\.DashHelpers\.keyTag\(t, h\), window\.DashHelpers\.kindTag\(t, h\), pill\]/, 'plain header: beside the number, in the line above the title (ORCH-2155)');
  assert.match(ticketSrc, /const parts = \[key \? h\('span', \{className:'key'\}, key\) : null, kind, pill,/, 'while a helper runs: in the line above the title');
  assert.match(listSrc, /kind \? h\('span', \{className:'kind-tag', 'data-kind':kind\.toLowerCase\(\)\}, kind\)/, 'a board tile (ORCH-576 status rows) shows its kind before the title');
});

test('phone list: the short row of an epic starts its fact line with "Epic"', () => {
  assert.match(listSrc, /fact:\[window\.DashHelpers\.kindWord\(row\.ticket\), shortFact\(/);
});
