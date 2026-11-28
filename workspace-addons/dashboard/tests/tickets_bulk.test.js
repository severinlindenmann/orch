'use strict';
// ORCH-2034: pick several rows of the Tickets list and set Status, Priority or Epic for all of them in one click,
// through the same paths as one ticket (moveTicket = ticket.patch; ticket.edit for priority and epic), one notice with Undo.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const appSrc = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, querySelector() { return {replaceChildren() {}}; }, querySelectorAll() { return []; }, dataset:{}, style:{}, classList:{add(c) { this.list.push(c); }, list:[]}});
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];

const ALL = () => [
  {id:'ep', key:'ORCH-1', title:'Spring fair', status:'active', epic:true, created_at:'2026-11-17T01:00:00Z', revision:1},
  {id:'a', key:'ORCH-2', title:'Logo', status:'open', created_at:'2026-11-17T02:00:00Z', revision:1},
  {id:'b', key:'ORCH-3', title:'Survey', status:'ready', priority:'low', parent:'ep', created_at:'2026-11-17T03:00:00Z', revision:1},
  {id:'c', key:'ORCH-4', title:'Opening hours', status:'open', created_at:'2026-11-17T04:00:00Z', revision:1},
];

function ctx({snapshot = false} = {}) {
  const toasts = [], calls = [], moves = [];
  const c = {h, fragment:(...k) => h('frag', {}, ...k), array:v => Array.isArray(v) ? v : [], clean:String,
    questions:() => [], shown:t => t, chip:t => h('span', {}, t), statusChip:t => h('span', {}, t.status), state:{runs:{}, tickets:ALL()},
    starting:new Set(), needsList:() => [], name:v => String(v || ''), location:{hash:'#tickets'}, snapshot, href:id => '#t/' + id,
    render() {}, iconEl:() => null, now:() => Date.now(), titleTag:() => null, parentLine:() => null, localStorage:{getItem:() => null, setItem() {}},
    button:(label, cls) => h('button', {className:'btn ' + cls}, label), changeUnavailable:() => false,
    statusControl:t => h('details', {}, h('summary', {}, 'Move to')), sorted:list => [...list],
    activeTicket:t => !['done', 'dropped'].includes(t.status), MOVE_CHOICES:helpers.MOVE_CHOICES, STATUS_CHOICES:helpers.STATUS_CHOICES,
    window:{DashHelpers:helpers, UI:{bulkBar:o => ({...h('div', {className:'bulk-bar'}, o.actions, o.clear), opts:o})},
      orch:{toast:(text, kind) => { toasts.push([kind, text]); return {querySelector:() => null, remove() {}}; }}}};
  c.tickets = () => c.state.tickets;
  c.ticketOf = id => c.state.tickets.find(t => t.id === id);
  vm.createContext(c); vm.runInContext(listSrc, c);
  // the one-ticket paths, recorded: a status move and ticket.edit (both change the ticket like the server would)
  c.moveTicket = async (id, status, undoing, extra) => { moves.push([id, status, undoing, extra]); c.state.tickets = c.state.tickets.map(t => t.id === id ? {...t, status, ...(extra.data || {})} : t); };
  c.act = async (op, args) => { calls.push([op, args]); const {ticket, if_revision, ...set} = args; c.state.tickets = c.state.tickets.map(t => t.id === ticket ? {...t, ...set} : t); return {ok:args.ticket !== 'fail'}; };
  // app.js actRetry: one more try after a 409 when the change still applies (here: a ticket marked stale answers 409 once)
  c.actRetry = async (op, args, applies) => {
    const t = c.ticketOf(args().ticket);
    if (t?.stale) { calls.push([op + ' 409', args()]); c.state.tickets = c.state.tickets.map(x => x === t ? {...x, stale:false, revision:(x.revision || 0) + 1} : x); if (!applies()) return {ok:false, status:409}; }
    return c.act(op, args());
  };
  return {c, toasts, calls, moves};
}

test('a pick column, a header box that picks every shown row, and the bar only while rows are picked', () => {
  const {c} = ctx();
  const table = c.ticketTable(c.tickets());
  const boxes = nodes(table).filter(n => n.tag === 'input' && n.attrs['data-pick']);
  assert.deepEqual(boxes.map(n => n.attrs['data-pick']).sort(), ['*', 'a', 'b', 'c', 'ep']);
  assert.ok(boxes.every(n => n.attrs['aria-label'].startsWith('Select ')));
  assert.ok(nodes(table).filter(n => n.attrs?.colSpan).every(n => n.attrs.colSpan === 7), 'group rows span the extra column');
  assert.equal(c.bulkBar(c.tickets()), null, 'nothing picked: no bar');
  c.pickTicket('a', true); c.pickTicket('b', true);
  const head = nodes(c.ticketTable(c.tickets())).find(n => n.attrs?.['data-pick'] === '*');
  assert.equal(head.attrs['data-mixed'], 'true', 'some picked: the header box is mixed');
  const bar = c.bulkBar(c.tickets());
  assert.equal(bar.opts.count, 2);
  assert.deepEqual(nodes(bar).filter(n => n.attrs?.['data-field'] === 'status').map(n => n.children[0]), ['Backlog', 'To do', 'Working', 'Review', 'Done', "Won't do"]);
  assert.deepEqual(nodes(bar).filter(n => n.attrs?.['data-field'] === 'parent').map(n => n.attrs['data-value']), ['ep', ''], 'open epics, then Not in an epic');
  c.pickTicket('*', true);
  assert.equal(c.bulkBar(c.tickets()).opts.count, 4);
  c.pickTicket('*', false);
  assert.equal(c.bulkBar(c.tickets()), null);
});

test('a picked epic is never offered as the epic of the picked tickets; a row that is no longer shown is dropped', () => {
  const {c} = ctx();
  c.pickTicket('ep', true); c.pickTicket('a', true);
  assert.deepEqual(nodes(c.bulkBar(c.tickets())).filter(n => n.attrs?.['data-field'] === 'parent').map(n => n.attrs['data-value']), ['']);
  assert.equal(c.bulkBar(c.tickets().filter(t => t.id !== 'ep')).opts.count, 1);
});

test('Status: every picked ticket moves through moveTicket (quietly), one notice for all, Undo puts each back', async () => {
  const {c, toasts, moves} = ctx();
  c.pickTicket('a', true); c.pickTicket('b', true); c.pickTicket('c', true);
  await c.bulkAction({dataset:{field:'status', value:'ready'}});
  assert.deepEqual(moves.map(m => [m[0], m[1], m[3].quiet]).sort(), [['a', 'ready', true], ['c', 'ready', true]], 'b is in To do already');
  assert.deepEqual(toasts, [['ok', 'Moved 2 tickets to To do']]);
  let undo;
  c.window.orch.toast = () => ({querySelector:() => null, querySelectorAll:() => [{textContent:'Dismiss', getAttribute:() => null, before(n) { undo = n; }}], remove() {}});  // the master toast (ORCH-2149)
  c.pickTicket('a', true);
  await c.bulkAction({dataset:{field:'status', value:'done'}});
  assert.ok(undo, 'the notice carries Undo');
});

test('Priority and Epic use ticket.edit with the same arguments as the ticket page; a failed one says so', async () => {
  const {c, toasts, calls} = ctx();
  c.pickTicket('a', true); c.pickTicket('b', true);
  await c.bulkAction({dataset:{field:'priority', value:'high'}});
  assert.deepEqual(calls.map(([op, a]) => [op, a.ticket, a.priority, a.if_revision]).sort(), [['ticket.edit', 'a', 'high', 1], ['ticket.edit', 'b', 'high', 1]]);
  assert.deepEqual(toasts.pop(), ['ok', 'Priority High on 2 tickets']);
  calls.length = 0;
  await c.bulkAction({dataset:{field:'parent', value:'ep'}});
  assert.deepEqual(calls.map(([, a]) => [a.ticket, a.parent]), [['a', 'ep']], 'b is in the epic already');
  assert.deepEqual(toasts.pop(), ['ok', 'Moved 1 ticket into ORCH-1']);
  calls.length = 0;
  await c.bulkAction({dataset:{field:'parent', value:''}});
  assert.deepEqual(calls.map(([, a]) => [a.ticket, a.parent]).sort(), [['a', null], ['b', null]]);
  c.state.tickets.push({id:'fail', title:'Broken', status:'open', revision:1});
  c.pickTicket('fail', true);
  await c.bulkAction({dataset:{field:'priority', value:'low'}});
  assert.match(toasts.pop()[1], /^1 ticket could not be saved\./);
});

test('a ticket changed since the page read it (409) is read again and saved once more', async () => {
  const {c, toasts, calls} = ctx();
  c.state.tickets = c.state.tickets.map(t => t.id === 'a' ? {...t, stale:true} : t);
  c.pickTicket('a', true);
  await c.bulkAction({dataset:{field:'priority', value:'high'}});
  assert.deepEqual(calls.map(([op, a]) => [op, a.ticket, a.if_revision]), [['ticket.edit 409', 'a', 1], ['ticket.edit', 'a', 2]]);
  assert.deepEqual(toasts.pop(), ['ok', 'Priority High on 1 ticket']);
});

test('a shared copy has no pick column and no bar; the page wires the boxes and the bar actions', () => {
  const {c} = ctx({snapshot:true});
  assert.ok(!nodes(c.ticketTable(c.tickets())).some(n => n.attrs?.['data-pick']));
  assert.equal(c.bulkBar(c.tickets()), null);
  assert.match(appSrc, /input\[data-pick\]'\);[^\n]*\n\s*if \(pick\) \{ pickTicket\(pick\.dataset\.pick, pick\.checked\)/);
  assert.match(appSrc, /action === 'bulk-set'\) \{ await bulkAction\(control\)/);
  assert.match(appSrc, /target\.matches\('\[data-pick\]'\)\) \{ target\.checked = source\.checked; target\.indeterminate/);
});
