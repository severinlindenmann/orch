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
test('a shared copy never reads', () => {
  const c = setup([], {}); c.snapshot = true;
  assert.equal(c.loadFullTicket('t_a'), null);
  assert.equal(c.log.urls.length, 0);
});
