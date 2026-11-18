// ORCH-580: a click carries an id; when its answer is lost (cut, ERR_CONTENT_LENGTH_MISMATCH) the page asks the
// server whether it went through before it says anything, and ends on what was made or a clear message.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const newticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/newticket.js'), 'utf8');
const slice = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from)));

function harness(routes) {
  const sent = [];
  const accepted = [];
  const fetch = async (url, opts = {}) => {
    sent.push({url, opts});
    const r = routes(url, opts, sent);
    if (r instanceof Error) throw r;
    return {status: r.status ?? 200, ok: (r.status ?? 200) === 200, json: async () => r.body, text: async () => String(r.body)};
  };
  const window = {crypto: {randomUUID: () => 'id-' + sent.length + '-0123456789'}, orch: {toast() {}}, DashHelpers: {
    applyStateDelta: (s, d) => (d.base === s.rev ? {...s, ...d.set, rev: 'r2'} : null),
  }};
  const c = vm.createContext({
    window, fetch, setTimeout: fn => setTimeout(fn, 0), Promise, Object, JSON, String, Uint8Array, Math, Error,
    encodeURIComponent, snapshot: false, state: {rev: 'r1', tickets: []}, writing: 0, mutation: 0, refreshAgain: false,
    starting: new Set(), startedAt: new Map(),
    busyOn: () => null, busyOff() {}, ticketOf: () => null, render() {}, refresh() {},
    accept: next => { accepted.push(next); c.state = next; },
  });
  vm.runInContext(slice('async function act(', 'let refreshAgain') + '\nthis.act = act;', c);
  return {c, sent, accepted};
}

const cut = () => new TypeError('Failed to fetch');  // what the browser gives for ERR_CONTENT_LENGTH_MISMATCH

test('a lost answer of a click that went through ends on what was made', async () => {
  const {c, sent, accepted} = harness(url => {
    if (url === '/api/act') return cut();
    if (url.startsWith('/api/act/status')) return {body: {state: 'done', status: 200, reply: {created: {id: 't_new001'}}}};
    if (url === '/api/state') return {body: {rev: 'r9', tickets: [{id: 't_new001'}]}};
    throw new Error('unexpected ' + url);
  });
  const out = await c.act('ticket.new', {title: 'T'}, {id: 'form-0123456789'});
  assert.equal(out.ok, true);
  assert.equal(out.recovered, true);
  assert.deepEqual(out.state.created, {id: 't_new001'});
  assert.equal(sent[0].opts.headers['X-Orch-Act-Id'], 'form-0123456789');
  assert.equal(sent[0].opts.headers['X-Orch-Have'], 'r1');
  assert.equal(sent[1].url, '/api/act/status?id=form-0123456789');
  assert.deepEqual(accepted.at(-1).tickets, [{id: 't_new001'}]);
  assert.equal(sent.filter(s => s.url === '/api/act').length, 1, 'never sent a second time by itself');
});

test('a lost answer of a click that did not arrive says so plainly', async () => {
  const {c} = harness(url => (url === '/api/act' ? cut() : {body: {state: 'unknown'}}));
  const out = await c.act('ticket.new', {title: 'T'});
  assert.equal(out.ok, false);
  assert.equal(out.lost, 'not-done');
  assert.match(out.text, /it was not done\. Nothing was saved, try again\./);
});

test('a click still running is waited for, then its result is used', async () => {
  let asked = 0;
  const {c} = harness(url => {
    if (url === '/api/act') return cut();
    if (url.startsWith('/api/act/status')) return {body: ++asked < 3 ? {state: 'running'} : {state: 'done', status: 200, reply: {created: {id: 't_x'}}}};
    return {body: {rev: 'r3', tickets: []}};
  });
  const out = await c.act('ticket.new', {title: 'T'});
  assert.equal(out.ok, true);
  assert.equal(asked, 3);
});

test('the server cannot be asked: the page says to look before trying again', async () => {
  const {c} = harness(() => cut());
  const out = await c.act('ticket.new', {title: 'T'});
  assert.equal(out.lost, 'unknown');
  assert.match(out.text, /Look in the ticket list before you try again/);
});

test('a delta answer is merged into the state held; the click keys come with it', async () => {
  const {c, accepted} = harness(() => ({body: {delta: true, base: 'r1', keys: ['rev', 'tickets', 'created'], set: {created: {id: 't_d'}}}}));
  const out = await c.act('ticket.new', {title: 'T'});
  assert.equal(out.ok, true);
  assert.deepEqual(out.state.created, {id: 't_d'});
  assert.equal(accepted.at(-1).rev, 'r2');
});

test('a delta that does not fit is replaced by the whole state, keeping the click keys', async () => {
  const {c} = harness(url => (url === '/api/act'
    ? {body: {delta: true, base: 'old', keys: ['rev', 'tickets', 'created'], set: {created: {id: 't_d'}}}}
    : {body: {rev: 'r5', tickets: [{id: 't_d'}]}}));
  const out = await c.act('ticket.new', {title: 'T'});
  assert.equal(out.state.rev, 'r5');
  assert.deepEqual(out.state.created, {id: 't_d'});
});

test('New ticket keeps one id until the ticket is made, so Retry never makes a second one', () => {
  assert.match(newticket, /newActIdOnce = newActIdOnce \|\| window\.orchActId\?\.\(\);\n\s+result = await act\('ticket\.new', args, \{id:newActIdOnce\}\)/);
  assert.match(newticket, /step\.actId = step\.actId \|\| window\.orchActId\?\.\(\);/);
});
