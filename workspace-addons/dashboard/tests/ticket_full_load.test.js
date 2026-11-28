// ORCH-522: the live state holds rows cut short ("slim"); ticketOf gives the whole ticket read from /api/ticket/<id>.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const block = src.slice(src.indexOf('const sameTicket'), src.indexOf('const href'));
function setup(rows, answers) {
  const log = {urls:[], renders:0};
  const c = vm.createContext({snapshot:false, log, state:{tickets:rows}, array:v => Array.isArray(v) ? v : [], String, Promise,
    render: () => { log.renders++; },
    fetch: async url => { log.urls.push(url); const body = answers[url]; return body ? {ok:true, status:200, json:async () => body} : {ok:false, status:404}; }});
  vm.runInContext(block + ';globalThis.ticketOf = ticketOf; globalThis.fullMissing = fullMissing;', c);
  return c;
}
const idle = ms => new Promise(r => setTimeout(r, ms));
test('a whole row is used as it is, nothing is read', () => {
  const c = setup([{id:'t_a', key:'WS-1', title:'A'}], {});
  assert.equal(c.ticketOf('ws-1').title, 'A');
  assert.equal(c.log.urls.length, 0);
});
test('a slim row: the whole ticket once read, by id or key', async () => {
  const c = setup([{id:'t_a', key:'WS-1', slim:true, updated_at:'2026-11-18T10:00:00Z', history:[1]}],
    {'/api/ticket/t_a': {ticket:{id:'t_a', key:'WS-1', updated_at:'2026-11-18T10:00:00Z', history:[1, 2, 3]}}});
  assert.equal(c.ticketOf('t_a').slim, true);
  await c.loadFullTicket('t_a');
  assert.equal(c.ticketOf('t_a').history.length, 3);
  assert.equal(c.ticketOf('WS-1').history.length, 3);
  assert.equal(c.log.renders, 1);
});
test('a newer row reads the ticket again and shows the last whole copy meanwhile', async () => {
  const c = setup([{id:'t_a', slim:true, updated_at:'2026-11-18T10:00:00Z'}],
    {'/api/ticket/t_a': {ticket:{id:'t_a', updated_at:'2026-11-18T10:00:00Z', v:1}}});
  await c.loadFullTicket('t_a');
  c.state.tickets = [{id:'t_a', slim:true, updated_at:'2026-11-18T11:00:00Z'}];
  assert.equal(c.ticketOf('t_a').v, 1);
  assert.deepEqual(c.log.urls, ['/api/ticket/t_a', '/api/ticket/t_a']);
  await idle(10);
});
test('a finished ticket outside the live state is found once read; an unknown one is marked missing', async () => {
  const c = setup([], {'/api/ticket/t_old': {ticket:{id:'t_old', status:'done'}}});
  assert.equal(c.ticketOf('t_old'), undefined);
  await c.loadFullTicket('t_old');
  assert.equal(c.ticketOf('t_old').status, 'done');
  assert.equal(await c.loadFullTicket('t_nope'), null);
  assert.equal(c.fullMissing.has('t_nope'), true);
});
test('the server answers an unknown ticket with ticket null (no 404): marked missing too', async () => {
  const c = setup([], {'/api/ticket/t_gone': {ticket:null}});
  assert.equal(await c.loadFullTicket('t_gone'), null);
  assert.equal(c.fullMissing.has('t_gone'), true);
});
test('a Looks good still being saved on the live row shows Done on the whole copy, which stays as read', async () => {
  const c = setup([{id:'t_a', slim:true, status:'review', updated_at:'2026-11-18T10:00:00Z'}],
    {'/api/ticket/t_a': {ticket:{id:'t_a', status:'review', updated_at:'2026-11-18T10:00:00Z', history:[1, 2]}}});
  await c.loadFullTicket('t_a');
  c.state.tickets = [{id:'t_a', slim:true, status:'done', accept_saving:true, accept_was:'review', updated_at:'2026-11-18T10:00:00Z'}];
  const t = c.ticketOf('t_a');
  assert.equal(t.status, 'done'); assert.equal(t.accept_saving, true); assert.equal(t.history.length, 2);
  c.state.tickets = [{id:'t_a', slim:true, status:'review', updated_at:'2026-11-18T10:00:00Z'}];  // Undo: the server's row again
  assert.equal(c.ticketOf('t_a').status, 'review');
});
test('a shared copy never reads', () => {
  const c = setup([], {}); c.snapshot = true;
  assert.equal(c.loadFullTicket('t_a'), null);
  assert.equal(c.log.urls.length, 0);
});
test('a failed read for a newer row is not tried again on every redraw', async () => {
  const c = setup([{id:'t_a', slim:true, updated_at:'2026-11-18T10:00:00Z'}],
    {'/api/ticket/t_a': {ticket:{id:'t_a', updated_at:'2026-11-18T10:00:00Z', v:1}}});
  await c.loadFullTicket('t_a');
  c.fetch = async url => { c.log.urls.push(url); return {ok:false, status:500}; };  // the server fails from now on
  c.render = () => { c.log.renders++; c.ticketOf('t_a'); };  // a redraw asks again, as the page does
  c.state.tickets = [{id:'t_a', slim:true, updated_at:'2026-11-18T11:00:00Z'}];
  c.ticketOf('t_a');
  await idle(30);
  assert.equal(c.log.urls.length, 2, 'one read for the newer row, not one per redraw');
  c.state.tickets = [{id:'t_a', slim:true, updated_at:'2026-11-18T12:00:00Z'}];  // the next change reads again
  c.ticketOf('t_a');
  await idle(30);
  assert.equal(c.log.urls.length, 3);
});
test('the parts counted at the last build show on the kept whole copy', async () => {
  const c = setup([{id:'t_a', slim:true, updated_at:'2026-11-18T10:00:00Z', parts_done:0, parts_total:2, children:['t_b', 't_c']}],
    {'/api/ticket/t_a': {ticket:{id:'t_a', updated_at:'2026-11-18T10:00:00Z', parts_done:0, parts_total:2, children:['t_b', 't_c'], v:1}}});
  await c.loadFullTicket('t_a');
  c.state.tickets = [{id:'t_a', slim:true, updated_at:'2026-11-18T10:00:00Z', parts_done:1, parts_total:2, children:['t_b', 't_c']}];  // a part finished
  const t = c.ticketOf('t_a');
  assert.equal(t.v, 1);
  assert.equal(t.parts_done, 1);
  assert.equal(c.log.urls.length, 1, 'the ticket itself did not change: not read again');
});

// ORCH-2388: the row is found through an index built once per ticket list, never by a scan per call.
test('ticketOf finds a row by id or key without scanning the list, and still gives what a scan gives', () => {
  const rows = Array.from({length:10000}, (_, i) => ({id:'t_' + i, key:'WS-' + i, title:'T' + i}));
  const c = setup(rows, {});
  let reads = 0;
  const counted = rows.map(r => new Proxy(r, {get(t, k) { if (k === 'id') reads++; return t[k]; }}));
  c.state.tickets = counted;
  assert.equal(c.ticketOf('t_9999').title, 'T9999');  // builds the index: one pass
  reads = 0;
  for (let i = 0; i < 200; i++) { assert.equal(c.ticketOf('t_' + (9999 - i)).title, 'T' + (9999 - i)); assert.equal(c.ticketOf('ws-' + (9000 - i)).title, 'T' + (9000 - i)); }
  assert.ok(reads < 2000, 'a few reads per look-up, not a scan of 10,000 rows each: ' + reads);
  assert.equal(c.ticketOf('t_nope'), undefined);
  // the first row that fits wins, as with the scan: an id that is another ticket's key
  c.state.tickets = [{id:'t_a', key:'WS-1', title:'A'}, {id:'WS-1', title:'B'}];
  assert.equal(c.ticketOf('WS-1').title, 'A');
  // a list changed in place (same length, or longer) is still answered right
  const list = [{id:'t_a', title:'A'}, {id:'t_b', title:'B'}];
  c.state.tickets = list;
  assert.equal(c.ticketOf('t_b').title, 'B');
  list[1] = {id:'t_c', title:'C'};
  assert.equal(c.ticketOf('t_c').title, 'C'); assert.equal(c.ticketOf('t_b'), undefined);
  list.push({id:'t_d', title:'D'}); list[0] = null;
  assert.equal(c.ticketOf('t_d').title, 'D'); assert.equal(c.ticketOf('t_a'), undefined);
  // a new list replaces the old one
  c.state.tickets = [{id:'t_b', title:'B2'}];
  assert.equal(c.ticketOf('t_b').title, 'B2');
});
