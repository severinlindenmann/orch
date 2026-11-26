'use strict';
// ORCH-2159: fast typing must not synchronously redraw the dashboard, or serve an older query.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');
function harness() {
  let now = 0, serial = 0;
  const timers = new Map(), calls = [], renders = [];
  const ctx = vm.createContext({
    URLSearchParams, snapshot:false, location:{hash:'#tickets'}, window:{DashHelpers:require('../src/orch_dashboard/web/helpers.js')},
    state:{tickets:[]}, array:v => v || [], tickets:() => [],
    history:{replaceState:(_, __, hash) => { ctx.location.hash = hash; }},
    setTimeout:(fn, delay) => { const id = ++serial; timers.set(id, {fn, at:now + delay}); return id; },
    clearTimeout:id => timers.delete(id),
    render:() => renders.push(now),
    fetch:url => new Promise(resolve => calls.push({url, reply:out => resolve({ok:true, json:async () => out})})),
  });
  vm.runInContext(source + '\nthis.api = {changeTicketSearch, hits, searchServed, wantSearch};', ctx);
  return {ctx, calls, renders, advance(ms) {
    now += ms;
    for (const [id, t] of timers) if (t.at <= now) { timers.delete(id); t.fn(); }
  }};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
test('a, b, c update the input state and URL immediately and coalesce into one redraw and request', () => {
  const h = harness();
  for (const value of ['a', 'ab', 'abc']) { h.ctx.api.changeTicketSearch(value); h.advance(20); }
  assert.equal(h.ctx.location.hash, '#tickets?q=abc');
  assert.deepEqual(h.renders, []);
  h.advance(59);
  assert.deepEqual(h.renders, []);
  h.advance(1);
  assert.equal(h.renders.length, 1);
  h.advance(170);
  assert.equal(h.calls.length, 1);
  assert.match(h.calls[0].url, /q=abc&/);
});
test('clearing search cancels the pending request and redraws the unfiltered page', () => {
  const h = harness();
  h.ctx.api.changeTicketSearch('abc'); h.advance(20);
  h.ctx.api.changeTicketSearch(''); h.advance(300);
  assert.equal(h.ctx.location.hash, '#tickets');
  assert.equal(h.calls.length, 0);
  assert.equal(h.renders.length, 1);
});
test('a late reply does not redraw or clear the busy state of the new query', async () => {
  const h = harness();
  h.ctx.api.changeTicketSearch('a'); h.advance(250);
  h.ctx.api.changeTicketSearch('abc'); h.advance(250);
  const count = h.renders.length;
  h.calls[0].reply({items:[{id:'old'}], total:1}); await settle();
  assert.equal(h.renders.length, count);
  assert.equal(h.ctx.api.hits.busy, true);
  h.calls[1].reply({items:[{id:'new'}], total:1}); await settle();
  assert.equal(h.ctx.api.hits.rows[0].id, 'new');
  assert.equal(h.ctx.api.searchServed(), true);
  assert.equal(h.ctx.api.hits.busy, false);
});
test('a reply after clearing search is ignored', async () => {
  const h = harness();
  h.ctx.api.changeTicketSearch('abc'); h.advance(250);
  h.ctx.api.changeTicketSearch(''); h.advance(80);
  const count = h.renders.length;
  h.calls[0].reply({items:[{id:'old'}], total:1}); await settle();
  assert.equal(h.renders.length, count);
  assert.equal(h.ctx.api.searchServed(), false);
});
test('leaving Tickets during the pause does not redraw the destination', () => {
  const h = harness();
  h.ctx.api.changeTicketSearch('abc'); h.ctx.location.hash = '#home'; h.advance(80);
  assert.equal(h.renders.length, 0);
});
