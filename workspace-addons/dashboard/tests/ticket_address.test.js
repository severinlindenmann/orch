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
    URLSearchParams, localStorage:{getItem:() => stored || null}, ticketSearch:'', ticketView:'list', window:{}};
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
