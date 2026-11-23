const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');

// persona test F6: the search words and List/Board were not in the address, so a reload or a shared link lost them.
function load(hash, stored) {
  const from = src.indexOf('const TICKET_VIEWS'), to = src.indexOf('const changesPending');
  const ctx = {location:{hash}, history:{replaceState:(_s, _t, url) => { ctx.location.hash = url; }}, searchFolds:new Set(),
    URLSearchParams, localStorage:{getItem:() => stored || null}, ticketSearch:'', ticketPerson:'', ticketGroup:'', ticketView:'list', calMode:'month', calDay:'', window:{DashHelpers:require('../src/orch_dashboard/web/helpers.js')}};
  vm.createContext(ctx);
  vm.runInContext(src.slice(from, to).replace('let ticketAddressKey', 'var ticketAddressKey') + '\nthis.api = {ticketAddress, writeTicketAddress, syncTicketAddress, savedView};', ctx);
  return ctx;
}
test('the address holds view, search words and the board', () => {
  const ctx = load('#tickets?view=working');
  assert.equal(ctx.api.ticketAddress(), '#tickets?view=working');
  ctx.ticketSearch = ' invoice run '; ctx.ticketView = 'board';
  assert.equal(ctx.api.ticketAddress(), '#tickets?view=working&q=invoice+run&layout=board');
  assert.equal(ctx.api.ticketAddress({view:''}), '#tickets?q=invoice+run&layout=board');
  ctx.ticketSearch = ''; ctx.ticketView = 'list';
  assert.equal(ctx.api.ticketAddress({view:''}), '#tickets');
  ctx.ticketPerson = 'anna';
  assert.equal(ctx.api.ticketAddress({view:''}), '#tickets?who=anna', 'ORCH-236: the Person filter is in the address');
});
test('typing writes the address without a new history entry; a reload adopts it', () => {
  const ctx = load('#tickets');
  ctx.api.syncTicketAddress();
  ctx.ticketSearch = 'bill';
  ctx.api.writeTicketAddress();
  assert.equal(ctx.location.hash, '#tickets?q=bill');
  const fresh = load(ctx.location.hash);
  fresh.api.syncTicketAddress();
  assert.equal(fresh.ticketSearch, 'bill');
  const board = load('#tickets?layout=board');
  board.api.syncTicketAddress();
  assert.equal(board.ticketView, 'board');
});
test('Back to an address with no search clears the search', () => {
  const ctx = load('#tickets?q=bill');
  ctx.api.syncTicketAddress();
  assert.equal(ctx.ticketSearch, 'bill');
  ctx.location.hash = '#tickets';
  ctx.api.syncTicketAddress();
  assert.equal(ctx.ticketSearch, '');
});
test('the address is not rewritten when another page is shown', () => {
  const ctx = load('#review');
  ctx.ticketSearch = 'x';
  ctx.api.writeTicketAddress();
  assert.equal(ctx.location.hash, '#review');
});
test('ORCH-1081: the calendar layout, its week view and shown day round-trip through the address', () => {
  const ctx = load('#tickets');
  ctx.ticketView = 'calendar';
  assert.equal(ctx.api.ticketAddress(), '#tickets?layout=calendar');
  ctx.calMode = 'week'; ctx.calDay = '2026-11-16'; ctx.ticketSearch = 'bill';
  ctx.location.hash = '#tickets';
  ctx.api.writeTicketAddress();
  assert.equal(ctx.location.hash, '#tickets?q=bill&layout=calendar&cal=week&day=2026-11-16');
  const fresh = load(ctx.location.hash);
  fresh.api.syncTicketAddress();
  assert.equal(fresh.ticketView, 'calendar');
  assert.equal(fresh.calMode, 'week');
  assert.equal(fresh.calDay, '2026-11-16');
  // the week and day belong to the calendar only; the list and the board never write them
  ctx.ticketView = 'list';
  assert.equal(ctx.api.ticketAddress({q:''}), '#tickets');
  // Back to the month view of today: the address changes, so the shown state follows
  fresh.location.hash = '#tickets?q=bill&layout=calendar';
  fresh.api.syncTicketAddress();
  assert.equal(fresh.calMode, 'month');
  assert.equal(fresh.calDay, '');
  const junk = load('#tickets?layout=calendar&day=tomorrow');
  junk.api.syncTicketAddress();
  assert.equal(junk.calDay, '', 'a broken day is ignored');
  const impossible = load('#tickets?layout=calendar&day=2026-02-30');
  impossible.api.syncTicketAddress();
  assert.equal(impossible.calDay, '', 'a day that does not exist means today, so Next steps from what is shown');
});
test('ORCH-1081: the calendar is remembered like the board when the address names no layout', () => {
  const ctx = load('#tickets', 'calendar');
  ctx.api.syncTicketAddress();
  assert.equal(ctx.ticketView, 'calendar');
});
test('ORCH-905: the Part of filter is in the address and a reload adopts it', () => {
  const ctx = load('#tickets');
  ctx.api.syncTicketAddress();
  ctx.ticketGroup = 't_abc123';
  ctx.api.writeTicketAddress();
  assert.equal(ctx.location.hash, '#tickets?part=t_abc123');
  const fresh = load(ctx.location.hash);
  fresh.api.syncTicketAddress();
  assert.equal(fresh.ticketGroup, 't_abc123');
  ctx.location.hash = '#tickets';
  ctx.api.syncTicketAddress();
  assert.equal(ctx.ticketGroup, '');
});
test('ORCH-905: the ticket page tab is written to and read from the address', () => {
  const t = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  const from = t.indexOf('// The selected tab lives'), to = t.indexOf('function selectTicketTab');
  const ctx = {location:{hash:'#ticket/t_x'}, history:{replaceState:(_a, _b, u) => { ctx.location.hash = u; }}, URLSearchParams, href:id => '#ticket/' + encodeURIComponent(id)};
  vm.createContext(ctx);
  vm.runInContext(t.slice(from, to) + '\nthis.api = {writeTicketTab, tabFromAddress};', ctx);
  ctx.api.writeTicketTab('t_x', 'tasks');
  assert.equal(ctx.location.hash, '#ticket/t_x?tab=tasks');
  assert.equal(ctx.api.tabFromAddress('t_x'), 'tasks');
  assert.equal(ctx.api.tabFromAddress('t_y'), '');
  ctx.api.writeTicketTab('t_x', 'overview');
  assert.equal(ctx.location.hash, '#ticket/t_x');
});
