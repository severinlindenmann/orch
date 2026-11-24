// #ticket/<id> for a ticket that is not in the held state yet: fresh read (retry ~5 s) before "couldn't find".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const block = src.slice(src.indexOf('const ticketLookups'), src.indexOf('function detail(t)'));
function setup(responses, alone = {}) {
  const log = {fetches:0, renders:0, alone:0};
  const full = new Map();
  // app.js's one-ticket read (ORCH-522): GET /api/ticket/<id>; `alone` holds the tickets it finds
  const c = vm.createContext({snapshot:false, log, mutation:0, setTimeout, Date, fullMissing:new Set(),
    loadFullTicket: async id => { log.alone++; const t = alone[id] || null; if (t) full.set(id, t); else c.fullMissing.add(id); return t; },
    skeletonFor: k => ({loading:k}), ticketNotFound: () => ({notFound:true}),
    ticketOf: id => (c.state.tickets || []).find(t => t.id === id) || full.get(id), state:{tickets:[]},
    accept: next => { c.state = next; },
    render: () => { log.renders++; },
    fetch: async url => { log.fetches++; assert.equal(url, '/api/state?fresh=1'); const body = responses[Math.min(log.fetches - 1, responses.length - 1)]; return {ok:true, json:async () => body}; }});
  vm.runInContext(block, c);
  vm.runInContext('ticketLookupWait = 5', c);
  return c;
}
const idle = ms => new Promise(r => setTimeout(r, ms));
test('not in state: shows loading, a fresh read finds it, no not-found card', async () => {
  const c = setup([{tickets:[]}, {tickets:[{id:'t_new'}]}]);
  assert.deepEqual({...c.missingTicket('t_new')}, {loading:'ticket'});
  await idle(80);
  assert.equal(c.log.fetches, 2);
  assert.equal(vm.runInContext("ticketLookups.has('t_new')", c), false);
  assert.equal(c.log.renders, 0);
});
test('still missing after the time is up: not-found card, once', async () => {
  const c = setup([{tickets:[]}]);
  vm.runInContext('ticketLookupLimit = 40', c);
  assert.deepEqual({...c.missingTicket('t_x')}, {loading:'ticket'});
  await idle(150);
  assert.ok(c.log.fetches >= 2);
  assert.deepEqual({...c.missingTicket('t_x')}, {notFound:true});
  assert.equal(c.log.renders, 1);
  const n = c.log.fetches; c.missingTicket('t_x'); await idle(20);
  assert.equal(c.log.fetches, n);
});
test('a finished ticket not in the live state loads alone, without a fresh state read', async () => {
  const c = setup([{tickets:[]}], {t_old: {id:'t_old', status:'done'}});
  assert.deepEqual({...c.missingTicket('t_old')}, {loading:'ticket'});
  await idle(20);
  assert.equal(c.log.alone, 1);
  assert.equal(c.log.fetches, 0);
  assert.equal(vm.runInContext("ticketLookups.has('t_old')", c), false);
  assert.equal(c.ticketOf('t_old').status, 'done');
});
test('a shared copy never reads', () => {
  const c = setup([{tickets:[]}]); c.snapshot = true;
  assert.deepEqual({...c.missingTicket('t_x')}, {notFound:true});
  assert.equal(c.log.fetches, 0);
});
